#!/usr/bin/env python3
"""UserPromptSubmit hook - detects qq/йй frustration markers and injects fix protocol."""
import json
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config as _cfg

QQ_LOG = _cfg.cron_dir() / "qq_markers.jsonl"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = data.get("prompt", "")
    session_id = data.get("session_id", "")

    # Match qq/йй at START of message only (avoid false positives from discussions)
    if not re.match(r"^(qq|йй)\b", prompt.strip(), re.IGNORECASE):
        sys.exit(0)

    description = re.sub(r"^(qq|йй)\s*", "", prompt.strip(), flags=re.IGNORECASE)

    # Log marker to structured file for heartbeat/reflection pickup
    marker = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sid": session_id[:16] if session_id else "",
        "description": description[:500],
        "status": "detected",
    }
    try:
        QQ_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(QQ_LOG, "a") as f:
            f.write(json.dumps(marker, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Inject aggressive fix protocol as additionalContext
    context = f"""[QQ FRUSTRATION DETECTED]: {description}

PROTOCOL (MANDATORY - DO NOT SKIP):
1. STOP current task. This takes priority.
2. Read last 10+ messages to understand what went wrong.
3. EDIT A FILE to fix the root cause:
   - Skill behavior wrong -> Edit ~/.claude/skills/SKILL_NAME/SKILL.md
   - CLAUDE.md instruction wrong -> Edit CLAUDE.md <INSTRUCTIONS> section
   - Heartbeat issue -> Edit HEARTBEAT.md
   - Missing knowledge -> Add to <MEMORY> section or create Obsidian note
   - Tone/style issue -> Update voice skill or add instruction
4. VERIFY the fix - re-read the edited file, confirm it prevents recurrence.
5. Log to daily notes: "qq fix: [what happened] -> [file changed]"
6. Create scenario test in ~/.claude/skills/scenarios/ if the failure is testable.

DO NOT just say "I'll remember for next time". EDIT A FILE NOW.
DO NOT ask "what do you mean?" - the context is in the conversation."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
