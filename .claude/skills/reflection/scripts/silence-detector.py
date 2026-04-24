#!/usr/bin/env python3
"""
Silence detector - scans deal and people notes for overdue follow-ups and stale contacts.

Deals: checks `follow_up` field in YAML frontmatter
People: checks `last_contact` field in YAML frontmatter

Outputs JSON to stdout.
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

VAULT_DIR = Path(os.environ.get("OBSIDIAN_VAULT", Path.home() / "Documents/MyBrain"))
DEALS_DIR = Path(os.environ.get("OBSIDIAN_DEALS_DIR", VAULT_DIR / "Deals"))
PEOPLE_DIR = VAULT_DIR / "People"
PEOPLE_STALE_DAYS = 14
TODAY = date.today()


def parse_date(value):
    """Parse date from string. Returns date or None."""
    if not value:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("null", "none", ""):
        return None
    # Try YYYY-MM-DD
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    return None


def extract_frontmatter(filepath):
    """Extract YAML frontmatter from a markdown file. Returns dict or None."""
    try:
        text = Path(filepath).read_text(encoding="utf-8")
    except Exception:
        return None

    if not text.startswith("---"):
        return None

    end = text.find("\n---", 3)
    if end == -1:
        return None

    block = text[3:end].strip()
    if not block:
        return None

    # Simple YAML key: value parser (no dependencies beyond stdlib)
    data = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # Strip inline quotes
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        data[key] = val if val else None

    return data


def scan_deals():
    results = []
    for md in DEALS_DIR.rglob("*.md"):
        fm = extract_frontmatter(md)
        if not fm:
            continue

        follow_up = parse_date(fm.get("follow_up"))
        if not follow_up:
            continue

        delta = (TODAY - follow_up).days
        if delta > 0:
            results.append({
                "type": "deal",
                "name": md.stem,
                "field": "follow_up",
                "value": follow_up.isoformat(),
                "days_overdue": delta,
            })

    return results


def scan_people():
    results = []
    for md in PEOPLE_DIR.glob("*.md"):
        fm = extract_frontmatter(md)
        if not fm:
            continue

        last_contact = parse_date(fm.get("last_contact"))
        if not last_contact:
            continue

        delta = (TODAY - last_contact).days
        if delta >= PEOPLE_STALE_DAYS:
            results.append({
                "type": "person",
                "name": md.stem,
                "field": "last_contact",
                "value": last_contact.isoformat(),
                "days_overdue": delta,
            })

    return results


def main():
    items = scan_deals() + scan_people()
    # Sort: most overdue first
    items.sort(key=lambda x: x["days_overdue"], reverse=True)
    print(json.dumps(items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
