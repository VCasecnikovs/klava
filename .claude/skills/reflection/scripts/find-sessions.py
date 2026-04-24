#!/usr/bin/env python3
"""
Find today's Claude Code sessions and extract markers.

Usage:
  python3 find-sessions.py --today              # List today's sessions
  python3 find-sessions.py --today --summary    # With message summaries
  python3 find-sessions.py --today --grep "qq|йй"  # Find qq/йй markers with context
  python3 find-sessions.py --days 3              # Last 3 days
  python3 find-sessions.py --hours 2             # Last 2 hours
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Configuration - respect CLAUDE_CONFIG_DIR if set
_config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
SESSIONS_DIR = _config_dir / "projects"


def find_sessions(since: datetime, max_messages: int = 30) -> list:
    """Find all session files modified since given time."""
    sessions = []

    for jsonl_file in SESSIONS_DIR.rglob("*.jsonl"):
        if jsonl_file.name.startswith("agent-"):
            continue

        try:
            mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime, tz=timezone.utc)
            size = jsonl_file.stat().st_size

            if mtime > since and size > 500:
                sessions.append({
                    "path": str(jsonl_file),
                    "modified": mtime.isoformat(),
                    "size": size,
                    "name": jsonl_file.stem,
                })
        except OSError:
            continue

    sessions.sort(key=lambda s: s["modified"])
    return sessions


def extract_text_from_content(content) -> str:
    """Extract text from message content."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif item.get("type") == "tool_use":
                    texts.append(f"[Tool: {item.get('name', 'unknown')}]")
        return " ".join(texts)

    return str(content)


def get_session_messages(session_path: str, max_messages: int = 30) -> list:
    """Parse session file and return messages."""
    messages = []

    try:
        with open(session_path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    msg_type = obj.get("type")
                    timestamp = obj.get("timestamp", "")

                    if msg_type == "user":
                        content = obj.get("message", {}).get("content", [])
                        text = extract_text_from_content(content)
                        if text:
                            messages.append({
                                "role": "user",
                                "text": text[:500],
                                "timestamp": timestamp,
                            })

                    elif msg_type == "assistant":
                        content = obj.get("message", {}).get("content", [])
                        text = extract_text_from_content(content)
                        if text:
                            messages.append({
                                "role": "assistant",
                                "text": text[:300],
                                "timestamp": timestamp,
                            })

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        print(f"Error reading {session_path}: {e}", file=sys.stderr)

    return messages[-max_messages:]


def get_session_stats(session_path: str) -> dict:
    """Parse session file and return stats: message counts, tool usage, errors."""
    stats = {
        "user_messages": 0,
        "assistant_messages": 0,
        "tool_calls": {},
        "tool_errors": 0,
        "error_details": [],
    }

    try:
        with open(session_path) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    msg_type = obj.get("type")

                    if msg_type == "user":
                        stats["user_messages"] += 1

                    elif msg_type == "assistant":
                        stats["assistant_messages"] += 1
                        content = obj.get("message", {}).get("content", [])
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "tool_use":
                                    name = item.get("name", "unknown")
                                    stats["tool_calls"][name] = stats["tool_calls"].get(name, 0) + 1

                    elif msg_type == "tool_result":
                        if obj.get("is_error"):
                            stats["tool_errors"] += 1
                            error_text = ""
                            content = obj.get("content", "")
                            if isinstance(content, str):
                                error_text = content[:150]
                            elif isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        error_text = item.get("text", "")[:150]
                                        break
                            if error_text and len(stats["error_details"]) < 5:
                                stats["error_details"].append(error_text)

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        print(f"Error reading {session_path}: {e}", file=sys.stderr)

    return stats


def grep_sessions(sessions: list, pattern: str, context: int = 10) -> list:
    """Find messages matching pattern with context."""
    results = []

    for session in sessions:
        messages = get_session_messages(session["path"], max_messages=1000)

        for i, msg in enumerate(messages):
            # Support | as OR separator (e.g., "qq|йй")
            patterns = [p.strip().lower() for p in pattern.split("|")]
            if any(p in msg["text"].lower() for p in patterns):
                # Get context: N messages before and after
                start = max(0, i - context)
                end = min(len(messages), i + context + 1)
                context_msgs = messages[start:end]

                results.append({
                    "session": session["name"],
                    "session_path": session["path"],
                    "match_index": i,
                    "match_message": msg,
                    "context": context_msgs,
                })

    return results


def main():
    days = 1
    hours = 0
    summary = False
    grep_pattern = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--today":
            days = 1
        elif args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 1
        elif args[i] == "--hours" and i + 1 < len(args):
            hours = int(args[i + 1])
            i += 1
        elif args[i] == "--summary":
            summary = True
        elif args[i] == "--grep" and i + 1 < len(args):
            grep_pattern = args[i + 1]
            i += 1
        elif args[i] in ("--help", "-h"):
            print(__doc__)
            return
        i += 1

    since = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    sessions = find_sessions(since)

    if not sessions:
        print(f"No sessions found in the last {days} day(s).")
        return

    if grep_pattern:
        results = grep_sessions(sessions, grep_pattern)
        if not results:
            print(f'No matches for "{grep_pattern}" in {len(sessions)} session(s).')
            return

        print(f'Found {len(results)} match(es) for "{grep_pattern}":\n')
        for r in results:
            print(f"=== Session: {r['session']} ===")
            print(f"Path: {r['session_path']}")
            print(f"Match in message #{r['match_index']}:")
            print()
            for msg in r["context"]:
                role = "USER" if msg["role"] == "user" else "ASST"
                marker = " <<<" if msg is r["match_message"] else ""
                print(f"  [{role}] {msg['text'][:200]}{marker}")
            print()
        return

    print(f"Found {len(sessions)} session(s) in the last {days} day(s):\n")
    total_errors = 0
    for s in sessions:
        print(f"  {s['name']}")
        print(f"    Modified: {s['modified']}")
        print(f"    Size: {s['size']:,} bytes")
        print(f"    Path: {s['path']}")

        if summary:
            stats = get_session_stats(s["path"])
            total_errors += stats["tool_errors"]
            print(f"    Messages: {stats['user_messages']} user, {stats['assistant_messages']} assistant")
            top_tools = sorted(stats["tool_calls"].items(), key=lambda x: -x[1])[:5]
            if top_tools:
                tools_str = ", ".join(f"{name}({count})" for name, count in top_tools)
                print(f"    Tools: {tools_str}")
            if stats["tool_errors"]:
                print(f"    Errors: {stats['tool_errors']}")
                for err in stats["error_details"][:3]:
                    print(f"      - {err[:120]}")

            messages = get_session_messages(s["path"], max_messages=5)
            if messages:
                print("    First messages:")
                for msg in messages[:3]:
                    role = "User" if msg["role"] == "user" else "Asst"
                    print(f"      [{role}] {msg['text'][:100]}")
        print()

    if summary:
        print(f"Total: {len(sessions)} sessions, {total_errors} tool errors")


if __name__ == "__main__":
    main()
