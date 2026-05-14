#!/usr/bin/env python3
"""Lint State + Log notes for provenance + cache-drift issues.

Checks per file (only `vox-deal` / `personal-deal` tagged):
  1. has-state:        ## State section present.
  2. has-log:          ## Log section present.
  3. state-sources:    Every State bullet carries `src:`. Bullets with
                       `src: frontmatter` are reported as WEAK (eligible
                       for upgrade), not as a hard fail.
  4. cache-drift:      frontmatter `stage` / `last_contact` / `follow_up`
                       / `next_action` match the State bullet of the same
                       key. Frontmatter is the cache; State wins on
                       disagreement.
  5. log-order:        ### YYYY-MM-DD entries inside ## Log are strictly
                       reverse-chronological (newest first).
  6. duplicate-log:    No duplicate log-wrapper headers (## History etc).

Default output is human-readable. `--json` emits a machine-readable report.
`--fail-on hard|any|none` controls the exit code (default: hard).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict

DEAL_TAGS = {"vox-deal", "personal-deal"}
LOG_WRAPPER_HEADERS = {
    "log", "history", "история", "timeline", "хронология", "журнал",
}
CACHED_KEYS = ("stage", "last_contact", "follow_up", "next_action")
# Structural keys that don't need src: provenance (they index into other
# sourced content rather than asserting a fact themselves).
STRUCTURAL_KEYS = {"artifacts", "links", "related", "channels", "people"}

DATED_HEADING_RE = re.compile(
    r"^###\s+(\d{4}-\d{2}-\d{2})"
)
STATE_BULLET_RE = re.compile(
    r"^-\s+\*\*([A-Za-z_][A-Za-z0-9_\-]*)\s*:\s*\*\*\s*(.*?)\s*$"
)
STATE_SOURCE_RE = re.compile(r"src:\s*`?([^`\s]+)`?")


@dataclass
class Finding:
    rule: str
    severity: str  # "hard" | "soft"
    msg: str


@dataclass
class FileReport:
    path: str
    skipped: bool = False
    reason: str = ""
    findings: List[Finding] = field(default_factory=list)


def split_frontmatter(text: str):
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    closing = text.find("\n", end + 1)
    if closing == -1:
        return text, ""
    return text[: closing + 1], text[closing + 1 :]


def parse_frontmatter_keys(fm: str) -> Dict[str, str]:
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
            in_tags = False
    return False


def get_section_body(body: str, header_titles: set) -> Optional[List[str]]:
    """Return lines under the first matching `## <title>` (lowercased), or None.

    Stops at next `## ` heading.
    """
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("### "):
            title = line[3:].strip().lower().strip(" :")
            if title in header_titles:
                start = i + 1
                break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## ") and not lines[j].startswith("### "):
            end = j
            break
    return lines[start:end]


def lint_file(path: Path) -> FileReport:
    rep = FileReport(path=str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        rep.skipped = True
        rep.reason = f"read error: {e}"
        return rep

    fm, body = split_frontmatter(text)
    if not fm:
        rep.skipped = True
        rep.reason = "no frontmatter"
        return rep
    if not has_deal_tag(fm):
        rep.skipped = True
        rep.reason = "not deal-tagged"
        return rep

    fm_keys = parse_frontmatter_keys(fm)

    # 1 + 2: section presence
    state_lines = get_section_body(body, {"state", "состояние"})
    log_lines = get_section_body(body, {"log", "история"})
    if state_lines is None:
        rep.findings.append(Finding("has-state", "hard", "missing ## State section"))
    if log_lines is None:
        rep.findings.append(Finding("has-log", "hard", "missing ## Log section"))

    # 6: duplicate log-wrapper headers
    wrap_counts: Dict[str, int] = {}
    for line in body.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            title = line[3:].strip().lower().strip(" :")
            if title in LOG_WRAPPER_HEADERS:
                wrap_counts[title] = wrap_counts.get(title, 0) + 1
    for title, count in wrap_counts.items():
        if count > 1:
            rep.findings.append(Finding(
                "duplicate-log", "hard",
                f"section '## {title}' appears {count}× (should be one canonical '## Log')",
            ))

    # 3 + 4: state bullets and cache drift
    state_bullet_values: Dict[str, str] = {}
    if state_lines is not None:
        for line in state_lines:
            m = STATE_BULLET_RE.match(line)
            if not m:
                continue
            key, val_with_src = m.group(1), m.group(2)
            src_m = STATE_SOURCE_RE.search(val_with_src)
            if src_m is None:
                if key not in STRUCTURAL_KEYS:
                    rep.findings.append(Finding(
                        "state-sources", "hard",
                        f"State bullet `{key}` has no `src:` provenance",
                    ))
            else:
                src_val = src_m.group(1).strip()
                if src_val.lower() == "frontmatter":
                    rep.findings.append(Finding(
                        "state-sources", "soft",
                        f"State bullet `{key}` has weak src=`frontmatter`; upgrade to real URI",
                    ))
            # capture value (text before "·" / "src:" for cache compare)
            cap = val_with_src
            for sep in (" · src:", "  src:", " src:", "· src:", " · "):
                if sep in cap:
                    cap = cap.split(sep, 1)[0]
                    break
            state_bullet_values[key] = cap.strip().strip('"').strip("'")

    # 4: cache drift — compare frontmatter to leading value of State bullet.
    # State bullets often carry annotation after the value (`2026-04-25 —
    # push Dima for legal feedback`). We compare only the leading token up
    # to the first " — " / " - " / linebreak / backtick — what the cache
    # should match.
    def _leading_value(s: str) -> str:
        s = s.strip()
        for sep in (" — ", " – ", " - ", "\n"):
            if sep in s:
                s = s.split(sep, 1)[0]
        s = s.strip().strip('"').strip("'").strip("`").strip()
        return s.lower()

    for key in CACHED_KEYS:
        fm_val_raw = (fm_keys.get(key) or "").strip().strip('"').strip("'")
        st_val_raw = state_bullet_values.get(key)
        if fm_val_raw in {"", "null", "~"} and st_val_raw in (None, "", "null"):
            continue
        if st_val_raw is None:
            if fm_val_raw and fm_val_raw not in {"null", "~"}:
                rep.findings.append(Finding(
                    "cache-drift", "soft",
                    f"frontmatter `{key}={fm_val_raw!r}` has no mirror in ## State",
                ))
            continue
        fm_lead = _leading_value(fm_val_raw)
        st_lead = _leading_value(st_val_raw)
        if fm_lead != st_lead:
            rep.findings.append(Finding(
                "cache-drift", "hard",
                f"frontmatter `{key}={fm_val_raw!r}` disagrees with State leading value "
                f"`{st_val_raw!r}` — State wins, update cache",
            ))

    # 5: log order
    if log_lines is not None:
        dates = []
        for line in log_lines:
            m = DATED_HEADING_RE.match(line)
            if m:
                dates.append(m.group(1))
        for i in range(len(dates) - 1):
            if dates[i] < dates[i + 1]:
                rep.findings.append(Finding(
                    "log-order", "hard",
                    f"log entries out of order: {dates[i]} appears before {dates[i+1]} (expected newest first)",
                ))
                break

    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--glob", default="Vox Lab/Deals/**/*.md")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on", choices=("hard", "any", "none"), default="hard")
    args = ap.parse_args()

    vault = args.vault.expanduser().resolve()
    paths = sorted(vault.glob(args.glob))

    reports: List[FileReport] = []
    for p in paths:
        rep = lint_file(p)
        reports.append(rep)

    n_total = len(reports)
    n_skipped = sum(1 for r in reports if r.skipped)
    n_clean = sum(1 for r in reports if not r.skipped and not r.findings)
    n_with_hard = sum(
        1 for r in reports if any(f.severity == "hard" for f in r.findings)
    )
    n_with_soft = sum(
        1 for r in reports if any(f.severity == "soft" for f in r.findings)
        and not any(f.severity == "hard" for f in r.findings)
    )

    total_findings = sum(len(r.findings) for r in reports)
    hard_findings = sum(
        1 for r in reports for f in r.findings if f.severity == "hard"
    )
    soft_findings = total_findings - hard_findings

    if args.json:
        json.dump([asdict(r) for r in reports], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        # Group findings by file, hard first
        for r in reports:
            if r.skipped or not r.findings:
                continue
            rel = Path(r.path).relative_to(vault) if str(vault) in r.path else r.path
            print(f"\n{rel}")
            for f in sorted(r.findings, key=lambda x: (x.severity != "hard", x.rule)):
                marker = "✗" if f.severity == "hard" else "·"
                print(f"  {marker} [{f.rule}] {f.msg}")

        # Counts per rule
        rule_counts: Dict[str, Dict[str, int]] = {}
        for r in reports:
            for f in r.findings:
                rule_counts.setdefault(f.rule, {"hard": 0, "soft": 0})[f.severity] += 1
        print()
        print(f"Scanned: {n_total}  Skipped: {n_skipped}  Clean: {n_clean}")
        print(f"With hard findings: {n_with_hard}  with soft only: {n_with_soft}")
        print(f"Findings: {hard_findings} hard, {soft_findings} soft")
        if rule_counts:
            print()
            print(f"{'rule':<20} {'hard':>6} {'soft':>6}")
            for rule, c in sorted(rule_counts.items()):
                print(f"{rule:<20} {c['hard']:>6} {c['soft']:>6}")

    if args.fail_on == "none":
        return 0
    if args.fail_on == "hard":
        return 1 if hard_findings else 0
    return 1 if total_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
