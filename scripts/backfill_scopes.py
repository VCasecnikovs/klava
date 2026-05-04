#!/usr/bin/env python3
"""Backfill scope tags on existing GTasks + session_log entries.

Two passes:

1. GTasks (open + recently completed): runs infer_scope on title+body,
   writes scope: <path> into the YAML frontmatter via update_task_notes.
   Skips anything already scoped or older than --max-age days.

2. Claude session files (~/.claude/projects/**/*.jsonl): extracts the
   first user prompt, runs infer_scope, appends to ~/.klava/sessions.jsonl
   with reconstructed metadata so the Scopes tab shows historical
   sessions. Skips sessions already represented in session_log.

Usage:
    python3 scripts/backfill_scopes.py            # dry run, both passes
    python3 scripts/backfill_scopes.py --apply    # execute
    python3 scripts/backfill_scopes.py --apply --tasks-only
    python3 scripts/backfill_scopes.py --apply --sessions-only
    python3 scripts/backfill_scopes.py --max-age 60  # only tasks <60d
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gateway"))

from tasks.queue import list_tasks, update_task_notes, build_frontmatter, parse_frontmatter, Task
from tasks.scope import infer_scope, validate_scope
from lib import session_log


def _age_days(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None


def _strip_tag_prefix(text: str) -> str:
    import re
    return re.sub(r"^\s*\[[A-Z][A-Z\s]*\]\s*", "", text or "")


def backfill_tasks(max_age_days: int, apply: bool) -> dict:
    """Walk the GTasks queue and tag every untagged task with infer_scope."""
    print(f"\n=== Pass 1: GTasks (max age {max_age_days}d) ===")
    try:
        tasks = list_tasks(include_completed=True)
    except Exception as e:
        print(f"FATAL: list_tasks failed: {e}", file=sys.stderr)
        return {"error": str(e)}

    print(f"Loaded {len(tasks)} tasks total.")

    proposals: list[tuple[Task, str]] = []  # (task, inferred_scope)
    skipped_already_scoped = 0
    skipped_too_old = 0
    skipped_no_match = 0

    for t in tasks:
        if t.scope:
            skipped_already_scoped += 1
            continue
        # Age filter — use whichever timestamp exists
        ref_ts = t.completed_at or t.created
        age = _age_days(ref_ts)
        # Always include tasks that are still pending, regardless of age
        if t.status not in ("pending", "running") and age is not None and age > max_age_days:
            skipped_too_old += 1
            continue
        text = _strip_tag_prefix(t.title) + " " + (t.body or "")
        inferred = infer_scope(text)
        if not inferred:
            skipped_no_match += 1
            continue
        proposals.append((t, inferred))

    by_scope = Counter(scope for _t, scope in proposals)
    print(f"  Already scoped:  {skipped_already_scoped}")
    print(f"  Skipped (too old): {skipped_too_old}")
    print(f"  Skipped (no match): {skipped_no_match}")
    print(f"  Will tag:        {len(proposals)}")
    print()
    print("Distribution by inferred scope:")
    for scope, n in by_scope.most_common(30):
        print(f"  {n:4d}  {scope}")
    if len(by_scope) > 30:
        print(f"  ... and {len(by_scope) - 30} more scopes")

    if not apply:
        print("\n(dry run — re-run with --apply to write)")
        return {"proposed": len(proposals), "by_scope": dict(by_scope)}

    print(f"\nApplying {len(proposals)} scope tags...")
    written = 0
    failures = 0
    for i, (t, scope) in enumerate(proposals):
        if i and i % 25 == 0:
            print(f"  ... {i}/{len(proposals)}")
        try:
            t.scope = scope
            update_task_notes(t.id, t.to_notes())
            written += 1
        except Exception as e:
            failures += 1
            print(f"  FAIL {t.id} ({t.title[:40]!r}): {e}", file=sys.stderr)
        # gentle rate limit
        if i and i % 10 == 0:
            time.sleep(0.5)

    print(f"\nDone. Tagged {written}, failed {failures}.")
    return {"tagged": written, "failed": failures, "by_scope": dict(by_scope)}


def backfill_sessions(max_age_days: int, apply: bool) -> dict:
    """Walk Claude session files, infer scope from first user turn,
    append to ~/.klava/sessions.jsonl."""
    print(f"\n=== Pass 2: Claude session files (max age {max_age_days}d) ===")
    proj_root = Path.home() / ".claude" / "projects"
    if not proj_root.exists():
        print(f"  {proj_root} not found, skipping.")
        return {"sessions": 0}

    files = list(proj_root.rglob("*.jsonl"))
    print(f"Found {len(files)} session files on disk.")

    # Read existing session_log to dedupe by sid
    existing = set()
    log_path = Path.home() / ".klava" / "sessions.jsonl"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("sid"):
                    existing.add(rec["sid"])
            except Exception:
                continue
    print(f"  Already in session_log: {len(existing)} sids")

    proposals = []
    skipped_old = 0
    skipped_dup = 0
    skipped_no_match = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    for path in files:
        sid = path.stem
        if sid in existing:
            skipped_dup += 1
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            continue
        if mtime < cutoff:
            skipped_old += 1
            continue
        # Read first ~5 user turns to get a scope-inferable corpus
        first_user = ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line_no, line in enumerate(f):
                    if line_no > 50:
                        break
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    msg = evt.get("message") or {}
                    if evt.get("type") == "user" and msg.get("role") == "user":
                        content = msg.get("content")
                        if isinstance(content, str):
                            first_user += " " + content
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    first_user += " " + c.get("text", "")
                        if len(first_user) > 2000:
                            break
        except Exception:
            continue

        if not first_user.strip():
            continue
        inferred = infer_scope(first_user[:4000])
        if not inferred:
            skipped_no_match += 1
            continue

        # Synthesize log entry
        proposals.append({
            "ts": mtime.isoformat(),
            "sid": sid,
            "scope": inferred,
            "trigger": "backfill:claude-session",
            "summary": (first_user.strip()[:200] or "(no prompt)").replace("\n", " "),
        })

    by_scope = Counter(p["scope"] for p in proposals)
    print(f"  Already in log: {skipped_dup}")
    print(f"  Too old:        {skipped_old}")
    print(f"  No scope match: {skipped_no_match}")
    print(f"  Will append:    {len(proposals)}")
    print()
    print("Distribution by inferred scope:")
    for scope, n in by_scope.most_common(20):
        print(f"  {n:4d}  {scope}")

    if not apply:
        print("\n(dry run — re-run with --apply to write)")
        return {"proposed": len(proposals), "by_scope": dict(by_scope)}

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        for p in proposals:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\nDone. Appended {len(proposals)} session entries to {log_path}")
    return {"appended": len(proposals), "by_scope": dict(by_scope)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="execute writes; default is dry-run")
    ap.add_argument("--max-age", type=int, default=90, help="max age in days (default 90)")
    ap.add_argument("--tasks-only", action="store_true")
    ap.add_argument("--sessions-only", action="store_true")
    args = ap.parse_args()

    do_tasks = not args.sessions_only
    do_sessions = not args.tasks_only

    if do_tasks:
        backfill_tasks(args.max_age, args.apply)
    if do_sessions:
        backfill_sessions(args.max_age, args.apply)


if __name__ == "__main__":
    main()
