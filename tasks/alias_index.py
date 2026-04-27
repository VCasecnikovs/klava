"""Person/org alias index built from Obsidian People/ frontmatter.

Used by `tasks.llm_matcher` to inject canonical-entity hints into the
dedup prompt — so two RESULT cards about the same person under different
names ("Александр Орлов" vs "Rich Bro", "Shawn Schneider" vs "Eldil AI")
get correctly grouped.

Cache: `/tmp/klava-alias-index.json`. Refreshed when the People/
directory mtime changes (i.e. any note added/edited).

Build cost: ~1s for 1000 notes; negligible after cache warms.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

PEOPLE_DIR = Path(os.path.expanduser("~/Documents/MyBrain/People"))
CACHE_FILE = Path("/tmp/klava-alias-index.json")
CACHE_TTL_SECONDS = 6 * 3600  # belt-and-suspenders; mtime check is primary


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_LIST_INLINE_RE = re.compile(r"\[(.*?)\]")
_HANDLE_CLEAN_RE = re.compile(r"^@+")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def _parse_frontmatter(text: str) -> Dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: Dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def _split_list_value(raw: str) -> List[str]:
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        parts = [p.strip().strip('"').strip("'") for p in inner.split(",")]
        return [p for p in parts if p]
    return [raw.strip().strip('"').strip("'")]


def _strip_wikilinks(s: str) -> str:
    return _WIKILINK_RE.sub(r"\1", s)


def _name_from_filename(stem: str) -> Tuple[str, List[str]]:
    """Extract base name and parenthetical (company/disambiguator) from
    `FirstName LastName (Company)`.
    """
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", stem)
    if m:
        return m.group(1).strip(), [m.group(2).strip()]
    return stem.strip(), []


def _build_index() -> Dict[str, List[str]]:
    """Return {canonical_name: [alias, alias, ...]}.

    Canonical = file basename without extension.
    Aliases = base name minus parens, parens contents, frontmatter
    `aliases`, `handle` (with leading @ stripped), `company` (wikilinks
    unwrapped, comma-split).
    """
    if not PEOPLE_DIR.is_dir():
        return {}

    index: Dict[str, List[str]] = {}
    for path in PEOPLE_DIR.glob("*.md"):
        stem = path.stem
        canonical = stem
        base_name, paren_aliases = _name_from_filename(stem)

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = _parse_frontmatter(text)

        bag: Set[str] = set()
        bag.add(base_name)
        for p in paren_aliases:
            bag.add(p)

        for key in ("aliases",):
            for v in _split_list_value(fm.get(key, "")):
                bag.add(v)

        handle = fm.get("handle", "").strip().strip('"').strip("'")
        if handle:
            handle_clean = _HANDLE_CLEAN_RE.sub("", handle)
            if handle_clean:
                bag.add(handle_clean)

        company_raw = fm.get("company", "").strip().strip('"').strip("'")
        if company_raw:
            unwrapped = _strip_wikilinks(company_raw)
            for piece in unwrapped.split(","):
                piece = piece.strip()
                if piece:
                    bag.add(piece)

        bag.discard(canonical)
        bag = {a for a in bag if a and len(a) >= 2}

        if bag:
            index[canonical] = sorted(bag)

    return index


def _people_dir_mtime() -> float:
    if not PEOPLE_DIR.is_dir():
        return 0.0
    try:
        return PEOPLE_DIR.stat().st_mtime
    except Exception:
        return 0.0


def load_index(force: bool = False) -> Dict[str, List[str]]:
    """Cached alias index. Rebuilds when People/ dir mtime changes."""
    cur_mtime = _people_dir_mtime()
    if not force and CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            if (
                data.get("dir_mtime") == cur_mtime
                and time.time() - data.get("ts", 0) < CACHE_TTL_SECONDS
            ):
                return data.get("index") or {}
        except Exception:
            pass

    index = _build_index()
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "ts": time.time(),
            "dir_mtime": cur_mtime,
            "index": index,
        }))
    except Exception:
        pass
    return index


def relevant_aliases(titles: List[str], max_hints: int = 8) -> List[str]:
    """Find canonical entities whose names/aliases appear in `titles`.

    Returns list of human-readable hint lines like
        "Shawn Schneider (Eldil AI) — also known as: Shawn Schneider, Eldil AI, shawns2759"
    Limited to `max_hints` entries to keep the dedup prompt small.
    """
    if not titles:
        return []
    index = load_index()
    if not index:
        return []

    haystack = " \n ".join(t for t in titles if t).lower()
    hints: List[Tuple[str, List[str]]] = []
    for canonical, aliases in index.items():
        names = [canonical] + aliases
        if any(name.lower() in haystack for name in names if len(name) >= 3):
            hints.append((canonical, aliases))

    hints.sort(key=lambda x: -len(x[1]))
    out: List[str] = []
    for canonical, aliases in hints[:max_hints]:
        unique = []
        seen = set()
        for a in [canonical] + aliases:
            if a.lower() in seen:
                continue
            seen.add(a.lower())
            unique.append(a)
        out.append(f"{canonical} — also known as: {', '.join(unique[1:])}")
    return out
