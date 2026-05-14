#!/usr/bin/env python3
"""Bulk-add `person` / `org` frontmatter tags to entity notes.

Tags are added idempotently so the State+Log migration + linter can target
People/ and Organizations/ notes the same way they target `vox-deal` /
`personal-deal` notes.

Behavior per file:
  - Has frontmatter + already tagged    -> noop
  - Has frontmatter, tags: [a, b]       -> rewrite as tags: [a, b, <tag>]
  - Has frontmatter, tags:\\n  - a       -> append `  - <tag>` line
  - Has frontmatter, no tags key        -> insert `tags: [<tag>]` before closing ---
  - No frontmatter                      -> create minimal `---\\ntags: [<tag>]\\n---`

Usage:
  python3 scripts/tag_entity_notes.py --vault ~/Documents/MyBrain [--apply]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Tuple


def split_frontmatter(text: str) -> Tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    closing = text.find("\n", end + 1)
    if closing == -1:
        return text, ""
    return text[: closing + 1], text[closing + 1 :]


_TAG_INLINE_RE = re.compile(r"^(tags\s*:\s*)\[(.*)\]\s*$")
_TAG_BLOCK_HEAD_RE = re.compile(r"^tags\s*:\s*$")
_TAG_BLOCK_ITEM_RE = re.compile(r"^\s+-\s+(.+?)\s*$")


def has_tag(fm: str, tag: str) -> bool:
    in_tags_block = False
    for line in fm.splitlines():
        if _TAG_BLOCK_HEAD_RE.match(line):
            in_tags_block = True
            continue
        if in_tags_block:
            m = _TAG_BLOCK_ITEM_RE.match(line)
            if m:
                t = m.group(1).strip().strip('"').strip("'")
                if t == tag:
                    return True
                continue
            in_tags_block = False
        m = _TAG_INLINE_RE.match(line)
        if m:
            items = [t.strip().strip('"').strip("'") for t in m.group(2).split(",")]
            if tag in items:
                return True
    return False


def add_tag(text: str, tag: str) -> str:
    fm, body = split_frontmatter(text)
    if not fm:
        return f"---\ntags: [{tag}]\n---\n\n" + text

    if has_tag(fm, tag):
        return text

    fm_lines = fm.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    in_tags_block = False
    block_start_idx = None

    for i, line in enumerate(fm_lines):
        if not inserted and in_tags_block:
            if _TAG_BLOCK_ITEM_RE.match(line):
                out.append(line)
                continue
            # block ended; append our item right before this line
            indent = "  "
            out.append(f"{indent}- {tag}\n")
            in_tags_block = False
            inserted = True
            out.append(line)
            continue

        if not inserted:
            m = _TAG_INLINE_RE.match(line)
            if m:
                items = [t.strip() for t in m.group(2).split(",") if t.strip()]
                items.append(tag)
                new = f"{m.group(1)}[{', '.join(items)}]\n"
                out.append(new)
                inserted = True
                continue
            if _TAG_BLOCK_HEAD_RE.match(line):
                in_tags_block = True
                block_start_idx = i
                out.append(line)
                continue
        out.append(line)

    if not inserted:
        # No tags key existed. Insert before the closing ---.
        new_out: list[str] = []
        for line in out:
            if line.strip() == "---" and new_out:
                new_out.append(f"tags: [{tag}]\n")
                inserted = True
            new_out.append(line)
        out = new_out

    if in_tags_block and not inserted:
        out.append(f"  - {tag}\n")

    return "".join(out) + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    vault = args.vault.expanduser().resolve()
    pairs = [
        (vault / "People", "person"),
        (vault / "Organizations", "org"),
    ]

    n_changed = n_noop = n_missing = 0
    for folder, tag in pairs:
        if not folder.is_dir():
            print(f"[warn] {folder} missing, skipping")
            continue
        for p in sorted(folder.glob("*.md")):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError as e:
                print(f"[err] {p}: {e}", file=sys.stderr)
                continue
            fm, _ = split_frontmatter(text)
            if not fm:
                n_missing += 1
                if args.apply:
                    new = add_tag(text, tag)
                    p.write_text(new, encoding="utf-8")
                continue
            if has_tag(fm, tag):
                n_noop += 1
                continue
            new = add_tag(text, tag)
            if new == text:
                n_noop += 1
                continue
            n_changed += 1
            if args.apply:
                p.write_text(new, encoding="utf-8")
                print(f"[write] {p.relative_to(vault)}")

    print(f"\nChanged: {n_changed}  Noop: {n_noop}  Created frontmatter: {n_missing}  ({'applied' if args.apply else 'dry-run'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
