#!/usr/bin/env python3
"""Migrate deal/entity notes to the State + Log convention.

Convention:
- Frontmatter holds stable identifiers + a denormalized cache of mutable
  fields (stage, last_contact, follow_up, next_action) so the dashboard
  + /vox-crm + silence-detector keep working.
- `## State` is the canonical state list with provenance (`src:` per bullet).
- `## Log` is append-only, reverse-chronological, every entry sourced.

Migration is conservative:
- Preserves all existing content.
- Detects dated sub-headings (`### YYYY-MM-DD ...` or `## YYYY-MM-DD ...`)
  anywhere in the body, including inside `## History` / `## История` /
  `## Timeline` / `## Log` wrappers.
- Promotes them into one canonical `## Log` section at the bottom,
  reverse-chronological.
- Wraps the surviving non-dated body content above as-is.
- Adds a `## State` section seeded from frontmatter values with weak
  `src: frontmatter` provenance — heartbeat / manual edits upgrade these
  over time to real source URIs.
- Idempotent: re-running on a migrated file is a no-op.

Usage:
  python scripts/migrate_to_state_log.py --vault ~/Documents/MyBrain \\
      --glob 'Vox Lab/Deals/**/*.md' [--apply]

Defaults to dry-run; pass --apply to write changes.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Tags that mark a note as needing State+Log shape.
DEAL_TAGS = {"vox-deal", "personal-deal", "person", "org"}

# Section headers (case-insensitive) treated as "log wrappers" — their
# contents are flattened into the canonical ## Log.
LOG_WRAPPER_HEADERS = {
    "log", "history", "история", "timeline", "хронология", "журнал",
}

# Section headers we explicitly own — we replace them in place.
OWNED_HEADERS = {"state", "состояние", "log", "история", "timeline"}

# YAML keys mirrored into ## State as cached projections.
STATE_MIRROR_KEYS = ("stage", "last_contact", "follow_up", "next_action")

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\b")
# Heading start with optional date prefix.
DATED_HEADING_RE = re.compile(
    r"^(#{2,4})\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"\s*[—\-–:]*\s*"
    r"(?P<title>.*?)\s*$"
)
ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")


@dataclass
class LogEntry:
    date: str           # ISO YYYY-MM-DD
    title: str          # rest of the heading line
    body: str = ""      # everything until next heading at the same or higher level
    src_line: Optional[str] = None   # if explicit "Source:" / "src:" line found
    raw_heading_level: int = 3       # number of #'s on original heading

    def render(self) -> str:
        # Normalise to ### YYYY-MM-DD — title
        title = self.title.strip(" -—–:")
        head = f"### {self.date} — {title}" if title else f"### {self.date}"
        body = self.body.strip()
        return head + ("\n" + body if body else "")


@dataclass
class Section:
    """A second-level heading section. Header None = preamble before any ##."""
    header: Optional[str]      # raw "## ..." line, or None for preamble
    title_normalized: str = "" # lowercased header text, for matching
    body_lines: List[str] = field(default_factory=list)


def split_frontmatter(text: str) -> Tuple[str, str]:
    """Return (frontmatter_block_including_delimiters, body). Empty fm if missing."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    # advance past the closing --- and following newline
    closing = text.find("\n", end + 1)
    if closing == -1:
        return text, ""
    return text[: closing + 1], text[closing + 1 :]


def parse_frontmatter_keys(fm: str) -> dict:
    """Naive YAML key-value parser. Lists/objects ignored. Good enough for ours."""
    out = {}
    inside = False
    for line in fm.splitlines():
        s = line.strip()
        if s == "---":
            inside = not inside
            continue
        if not inside or not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        # Strip surrounding quotes
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        out[key] = raw
    return out


def has_deal_tag(fm: str) -> bool:
    inside = False
    in_tags = False
    for line in fm.splitlines():
        s = line.strip()
        if s == "---":
            inside = not inside
            continue
        if not inside:
            continue
        if re.match(r"^tags\s*:", line):
            in_tags = True
            # inline form `tags: [a, b]`
            inline = line.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                items = [t.strip().strip('"').strip("'") for t in inline[1:-1].split(",")]
                return bool(DEAL_TAGS & set(items))
            continue
        if in_tags:
            m = re.match(r"^\s+-\s*(.+?)\s*$", line)
            if m:
                if m.group(1).strip().strip('"').strip("'") in DEAL_TAGS:
                    return True
                continue
            # Tags list ended.
            in_tags = False
    return False


def split_sections(body: str) -> List[Section]:
    """Split body by top-level `## ` headings (level-2). Preamble = first section."""
    sections: List[Section] = [Section(header=None, title_normalized="")]
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        # Only level-2 here — match exactly "## ", not "### "
        if line.startswith("## ") and not line.startswith("### "):
            title = line[3:].strip()
            sections.append(Section(header=line, title_normalized=title.lower()))
        else:
            sections[-1].body_lines.append(line)
    return sections


def extract_dated_entries(lines: List[str]) -> Tuple[List[LogEntry], List[str]]:
    """Find dated sub-headings (### YYYY-MM-DD ...) and pull their content out.

    Returns (entries, surviving_lines). Surviving_lines keeps all content that
    isn't part of a dated block.
    """
    entries: List[LogEntry] = []
    surviving: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = DATED_HEADING_RE.match(line)
        if m and line.lstrip().startswith("##"):
            level = len(re.match(r"^(#+)", line).group(1))
            date = m.group("date")
            title = m.group("title").strip()
            j = i + 1
            buf = []
            while j < n:
                nxt = lines[j]
                # stop at next heading at the same or higher level
                hm = ANY_HEADING_RE.match(nxt)
                if hm and len(hm.group(1)) <= level:
                    break
                buf.append(nxt)
                j += 1
            body_text = "\n".join(buf).rstrip()
            entries.append(LogEntry(
                date=date, title=title, body=body_text, raw_heading_level=level
            ))
            i = j
            continue
        surviving.append(line)
        i += 1
    return entries, surviving


def looks_like_log_wrapper(section: Section) -> bool:
    if section.header is None:
        return False
    t = section.title_normalized.strip(" :")
    return t in LOG_WRAPPER_HEADERS


def looks_like_state_section(section: Section) -> bool:
    if section.header is None:
        return False
    return section.title_normalized.strip(" :") in {"state", "состояние"}


STATE_BULLET_KEY_RE = re.compile(r"^-\s+\*\*([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*\*\*")
STATE_BULLET_FULL_RE = re.compile(
    r"^-\s+\*\*([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*\*\*\s*(.*?)\s*$"
)


def extract_state_leading_values(state_lines: List[str]) -> dict:
    """Pull {key: leading_value} from rendered State bullets.

    Leading value = text before " — " / " - " / " · src:" / linebreak.
    Used to keep the frontmatter cache in sync with State (canonical truth).
    Bullets whose source is `frontmatter` are skipped — those carry no new
    information and would overwrite a real value with a stale one in a
    round-trip migration.
    """
    out: dict = {}
    for line in state_lines:
        m = STATE_BULLET_FULL_RE.match(line)
        if not m:
            continue
        key, payload = m.group(1), m.group(2)
        if key not in STATE_MIRROR_KEYS:
            continue
        # Skip weak-source bullets — they were seeded FROM frontmatter, so
        # writing them back would be a no-op at best and lossy at worst
        # (annotation gets dropped).
        src_m = re.search(r"src:\s*`?([^`\s]+)`?", payload)
        if src_m and src_m.group(1).strip().lower() == "frontmatter":
            continue
        # Strip annotation tail and src clause to get the bare value.
        val = payload
        for sep in (" — ", " – ", " - ", "  src:", " · src:"):
            if sep in val:
                val = val.split(sep, 1)[0]
                break
        val = val.strip().strip('"').strip("'").strip("`").strip()
        if val:
            out[key] = val
    return out


def sync_frontmatter_cache(fm: str, leading: dict) -> str:
    """Overwrite frontmatter values for cached keys with State leading values.

    Only touches keys present in `leading`. Keys absent from State stay as
    frontmatter has them. Preserves YAML indentation + comments verbatim.
    """
    if not leading:
        return fm
    out_lines = []
    for line in fm.splitlines(keepends=True):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*(.*)$", line.rstrip("\n"))
        if m and m.group(1) in leading:
            key = m.group(1)
            new_val = leading[key]
            # Quote if value contains characters that would break YAML.
            if any(c in new_val for c in ":#") or new_val.startswith(("[", "{", "!", "&", "*", "?", "|", ">", "%", "@", "`")):
                new_val = '"' + new_val.replace('"', '\\"') + '"'
            out_lines.append(f"{key}: {new_val}\n")
        else:
            out_lines.append(line)
    return "".join(out_lines)


def build_state_section(fm_keys: dict, existing_state_lines: List[str]) -> str:
    """Merge: preserve existing State bullets with strong sources; refresh
    bullets with weak `src: frontmatter` from current frontmatter; add weak
    mirrors only for cached keys not already covered.

    Three-way merge resolution:
      - Bullet with strong src (signal://, hlopya://, etc.) → preserve verbatim.
        Its value will sync FROM State TO frontmatter via `sync_frontmatter_cache`.
      - Bullet with weak `src: frontmatter` → refresh value from current
        frontmatter. The seed bullet should always reflect the cache.
      - Cached key with no State bullet yet → add weak mirror.

    This makes the script non-destructive on re-runs: hand-curated bullets with
    real `src: signal://...` survive a re-migration; the cache mirrors stay
    fresh; nothing goes stale silently.
    """
    existing_keys: set = set()
    preserved: List[str] = []
    for line in existing_state_lines:
        m = STATE_BULLET_KEY_RE.match(line)
        if m:
            key = m.group(1)
            existing_keys.add(key)
            # Detect weak source. If weak AND key is in MIRROR_KEYS, refresh
            # from frontmatter to keep the seed bullet aligned with cache.
            full = STATE_BULLET_FULL_RE.match(line)
            payload = full.group(2) if full else ""
            src_m = re.search(r"src:\s*`?([^`\s]+)`?", payload)
            is_weak = src_m is not None and src_m.group(1).strip().lower() == "frontmatter"
            if is_weak and key in STATE_MIRROR_KEYS:
                fm_val = fm_keys.get(key)
                if fm_val and fm_val not in {"null", "~"}:
                    preserved.append(
                        f"- **{key}:** {fm_val} · src: `frontmatter` · _needs upgrade_"
                    )
                    continue
            preserved.append(line)
        elif preserved and line.startswith("  "):
            # continuation line under a bullet (e.g. "  - sub: ...")
            preserved.append(line)
        elif preserved and not line.strip():
            preserved.append(line)

    added: List[str] = []
    for key in STATE_MIRROR_KEYS:
        if key in existing_keys:
            continue
        val = fm_keys.get(key)
        if val is None or val == "" or val == "null":
            continue
        added.append(f"- **{key}:** {val} · src: `frontmatter` · _needs upgrade_")

    if not preserved and not added:
        return "_(no state mirrored — populate as facts surface)_\n"
    out_lines = preserved
    if added:
        if out_lines and out_lines[-1].strip():
            out_lines = out_lines + [""]
        out_lines = out_lines + added
    return "\n".join(out_lines).rstrip() + "\n"


def render_log(entries: List[LogEntry]) -> str:
    if not entries:
        return "_(no dated entries yet)_\n"
    return "\n\n".join(e.render() for e in entries) + "\n"


def migrate_text(text: str) -> Tuple[str, dict]:
    """Return (new_text, report). report has keys: skipped, reason, n_entries."""
    fm, body = split_frontmatter(text)
    if not fm:
        return text, {"skipped": True, "reason": "no frontmatter"}
    if not has_deal_tag(fm):
        return text, {"skipped": True, "reason": "not a deal-tagged note"}

    fm_keys = parse_frontmatter_keys(fm)

    sections = split_sections(body)

    # Collect all dated entries from EVERY section. Log-wrapper sections lose
    # their wrapper. Other sections keep theirs but with dated entries pulled
    # out. Existing State sections are dropped — we rebuild from frontmatter.
    all_entries: List[LogEntry] = []
    surviving_sections: List[Section] = []
    existing_state_lines: List[str] = []
    for sec in sections:
        if looks_like_state_section(sec):
            # Capture existing bullets so we can preserve them instead of
            # dropping. Real `src: signal://...` provenance must survive a
            # re-migration.
            existing_state_lines = list(sec.body_lines)
            continue
        entries, surviving_lines = extract_dated_entries(sec.body_lines)
        all_entries.extend(entries)
        if looks_like_log_wrapper(sec):
            # The wrapper itself goes away; only stray non-dated text would
            # have survived inside it. Discard the header line; keep stray
            # text only if substantive (>10 non-whitespace chars).
            stray = "\n".join(surviving_lines).strip()
            if len(stray) > 10:
                # Keep as a level-2 "Notes from old <wrapper>" section so we
                # don't silently lose anything.
                surviving_sections.append(Section(
                    header=f"## Notes from old {sec.title_normalized}",
                    title_normalized=f"notes from old {sec.title_normalized}",
                    body_lines=surviving_lines,
                ))
            continue
        sec.body_lines = surviving_lines
        surviving_sections.append(sec)

    # Dedup entries by (date, normalized title) — duplicate History sections
    # often contain the same item written twice.
    seen = {}
    deduped: List[LogEntry] = []
    for e in all_entries:
        key = (e.date, re.sub(r"\s+", " ", e.title.lower()).strip())
        if key in seen:
            # Prefer the one with longer body.
            if len(e.body) > len(seen[key].body):
                deduped[deduped.index(seen[key])] = e
                seen[key] = e
            continue
        seen[key] = e
        deduped.append(e)

    deduped.sort(key=lambda e: e.date, reverse=True)

    # Reassemble body.
    out_parts: List[str] = []
    for sec in surviving_sections:
        if sec.header is None:
            text_chunk = "\n".join(sec.body_lines).rstrip()
            if text_chunk:
                out_parts.append(text_chunk)
        else:
            chunk = sec.header + "\n" + "\n".join(sec.body_lines)
            out_parts.append(chunk.rstrip())

    state_section_body = build_state_section(fm_keys, existing_state_lines)
    state_block = "## State\n\n" + state_section_body

    # Sync frontmatter cache from State leading values (State wins on drift).
    leading = extract_state_leading_values(state_section_body.splitlines())
    fm = sync_frontmatter_cache(fm, leading)

    log_block = "## Log\n\n" + render_log(deduped)

    out_parts.append(state_block.rstrip())
    out_parts.append(log_block.rstrip())

    new_body = "\n\n".join(p for p in out_parts if p.strip()) + "\n"
    return fm + new_body, {
        "skipped": False,
        "n_entries": len(deduped),
        "n_sections_kept": len(surviving_sections),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--glob", default="Vox Lab/Deals/**/*.md")
    ap.add_argument("--apply", action="store_true",
                    help="Write changes. Without this flag, dry-run only.")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    vault = args.vault.expanduser().resolve()
    if not vault.is_dir():
        print(f"vault not found: {vault}", file=sys.stderr)
        return 2

    paths = sorted(vault.glob(args.glob))
    if not paths:
        print(f"no files matched: {args.glob}")
        return 0

    n_total = n_migrated = n_skipped = n_changed = n_errors = 0
    for p in paths:
        n_total += 1
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[err] {p}: {e}", file=sys.stderr)
            n_errors += 1
            continue
        try:
            new_text, report = migrate_text(text)
        except Exception as e:
            print(f"[err] {p}: {e}", file=sys.stderr)
            n_errors += 1
            continue
        if report.get("skipped"):
            n_skipped += 1
            if args.verbose:
                print(f"[skip] {p.relative_to(vault)} — {report['reason']}")
            continue
        n_migrated += 1
        if new_text != text:
            n_changed += 1
            if args.apply:
                p.write_text(new_text, encoding="utf-8")
            tag = "[write]" if args.apply else "[dry  ]"
            print(f"{tag} {p.relative_to(vault)} — {report.get('n_entries')} log entries")
        else:
            if args.verbose:
                print(f"[noop] {p.relative_to(vault)} — already in canonical shape")

    print()
    print(f"Total scanned: {n_total}")
    print(f"Eligible:      {n_migrated}")
    print(f"Skipped:       {n_skipped}")
    print(f"Changed:       {n_changed} ({'written' if args.apply else 'dry-run'})")
    print(f"Errors:        {n_errors}")
    return 0 if n_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
