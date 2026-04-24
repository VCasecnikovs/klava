#!/usr/bin/env python3
"""PreToolUse hook - blocks gh issue/pr comment commands.

Heartbeat and other automated agents must NEVER post comments to production
GitHub issues. This hook provides a hard guard against accidental comments.

Allows: gh issue view, gh issue list, gh issue create (via vox-tasks skill), gh pr comment, gh issue comment
Blocks: gh api with comment endpoints (raw API posts)
"""
import json
import re
import sys


# Patterns that indicate a GH comment attempt
BLOCKED_PATTERNS = [
    # gh issue comment and gh pr comment are allowed in interactive sessions
    # Original block was for heartbeat incident (Mar 23) - protection moved to heartbeat level
    # r'\bgh\s+issue\s+comment\b',
    # r'\bgh\s+pr\s+comment\b',
    r'\bgh\s+api\b.*\b(comments|reviews)\b.*\b(POST|--method\s+POST|-X\s+POST)\b',
    r'\b(POST|--method\s+POST|-X\s+POST)\b.*\bgh\s+api\b.*\b(comments|reviews)\b',
]

BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # Can't parse = allow

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Only check Bash commands
    if tool_name != "Bash":
        return

    command = tool_input.get("command", "")
    if not command:
        return

    for pattern in BLOCKED_RE:
        if pattern.search(command):
            # Block the tool call
            result = {
                "decision": "block",
                "reason": (
                    "BLOCKED: Posting comments to GitHub issues is not allowed. "
                    "Use Google Tasks or Obsidian to track findings. "
                    "To create issues, use the /vox-tasks skill."
                ),
            }
            print(json.dumps(result))
            return


if __name__ == "__main__":
    main()
