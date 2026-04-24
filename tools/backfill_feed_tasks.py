#!/usr/bin/env python3
"""One-time script: backfill truncated task results in feed from GTasks notes.

The old consumer.py truncated task output to 500 chars. GTasks notes have
the full result (up to 2000 chars). This script patches messages.jsonl
with the full content.

Usage:
    python3 tools/backfill_feed_tasks.py          # dry run
    python3 tools/backfill_feed_tasks.py --apply   # write changes
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

FEED_LOG = Path(os.path.expanduser("~/.claude/feed/messages.jsonl"))

_CFG_PATH = Path(__file__).resolve().parent.parent / "gateway" / "config.yaml"
if not _CFG_PATH.exists():
    print(f"ERROR: {_CFG_PATH} not found. Run setup.sh first.")
    sys.exit(1)

_cfg = yaml.safe_load(_CFG_PATH.read_text()) or {}
ACCOUNT = (_cfg.get("identity") or {}).get("email") or ""
_tasks_lists = ((_cfg.get("integrations") or {}).get("google") or {}).get("tasks_lists") or {}
_queue_list_name = (_cfg.get("tasks") or {}).get("gtasks_list") or ""
TASK_QUEUE_LIST_ID = _tasks_lists.get(_queue_list_name, "")

if not ACCOUNT or not TASK_QUEUE_LIST_ID:
    print("ERROR: set identity.email and tasks.gtasks_list + matching entry under "
          "integrations.google.tasks_lists in gateway/config.yaml.")
    sys.exit(1)


def get_completed_tasks() -> dict:
    """Fetch completed tasks from GTasks, return {title: full_result}."""
    cmd = [
        "gog", "tasks", "list", TASK_QUEUE_LIST_ID,
        "--json", "--results-only", "--show-completed",
        "-a", ACCOUNT,
    ]
    raw = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if raw.returncode != 0:
        print(f"ERROR: gog failed: {raw.stderr[:200]}")
        sys.exit(1)

    data = json.loads(raw.stdout)
    items = data if isinstance(data, list) else data.get("items", [])

    results = {}
    for item in items:
        if item.get("status") != "completed":
            continue
        title = item.get("title", "")
        notes = item.get("notes", "")
        if "## Result" not in notes:
            continue
        full_result = notes.split("## Result", 1)[1].strip()
        results[title] = full_result

    return results


def backfill(apply: bool = False):
    if not FEED_LOG.exists():
        print("No feed log found")
        return

    task_results = get_completed_tasks()
    print(f"Found {len(task_results)} completed tasks with results in GTasks\n")

    lines = FEED_LOG.read_text().strip().split("\n")
    updated = 0
    new_lines = []

    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        # Only patch task-consumer messages
        if entry.get("job_id") != "task-consumer":
            new_lines.append(line)
            continue

        msg = entry.get("message", "")
        if not msg.startswith("<b>Task done:</b>"):
            new_lines.append(line)
            continue

        # Extract title from "<b>Task done:</b> TITLE\n..."
        first_line = msg.split("\n")[0]
        title = first_line.replace("<b>Task done:</b>", "").strip()

        if title not in task_results:
            new_lines.append(line)
            continue

        # Check if message is truncated (ends with "...")
        if not msg.rstrip().endswith("..."):
            new_lines.append(line)
            continue

        # Rebuild message with full result
        full_result = task_results[title]
        # Keep header lines (Task done + Duration), replace output
        msg_lines = msg.split("\n")
        header = "\n".join(msg_lines[:2])  # "Task done:..." and "Duration:..."
        new_msg = f"{header}\n\n{full_result}"

        old_len = len(msg)
        new_len = len(new_msg)
        print(f"  PATCH: {title[:60]}")
        print(f"    old: {old_len} chars -> new: {new_len} chars (+{new_len - old_len})")

        entry["message"] = new_msg
        new_lines.append(json.dumps(entry, ensure_ascii=False))
        updated += 1

    print(f"\n{updated} messages to patch")

    if apply and updated > 0:
        # Backup
        backup = FEED_LOG.with_suffix(".jsonl.bak")
        FEED_LOG.rename(backup)
        print(f"Backup: {backup}")

        FEED_LOG.write_text("\n".join(new_lines) + "\n")
        print(f"Written: {FEED_LOG}")
    elif updated > 0:
        print("\nDry run. Use --apply to write changes.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    backfill(apply=apply)
