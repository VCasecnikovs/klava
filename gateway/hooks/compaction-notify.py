#!/usr/bin/env python3
"""Claude Code PreCompact hook - logs compaction events and updates statusline state."""
import json
import sys
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config as _cfg

LOG_DIR = _cfg.logs_dir()
LOG_FILE = LOG_DIR / "compaction.jsonl"
STATE_DIR = _cfg.state_dir() / "sessions"


def _notify_dashboard(session_id: str, event: str, trigger: str, duration_sec: float | None = None) -> None:
    """Best-effort POST to the webhook server so the Chat tab can render a compaction block."""
    try:
        cfg = _cfg.load()
        webhook = cfg.get("webhook", {})
        port = int(webhook.get("port", 18788))
    except Exception:
        port = 18788
    payload = {"session_id": session_id, "event": event, "trigger": trigger}
    if duration_sec is not None:
        payload["duration_sec"] = duration_sec
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/chat/compaction",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=0.5).read()
    except Exception:
        pass


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    session_id = data.get("session_id", "")
    trigger = data.get("trigger", "auto")  # "manual" or "auto"

    # Log the compaction event
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sid": session_id[:16],
        "trigger": trigger,
        "event": "pre_compact",
    }
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Write compaction state for statusline to pick up
    if session_id:
        state_file = STATE_DIR / f"{session_id[:16]}.json"
        state = {}
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
            except Exception:
                pass
        state["compacting"] = True
        state["compact_started"] = datetime.now(timezone.utc).isoformat()
        state["compact_trigger"] = trigger
        try:
            state_file.write_text(json.dumps(state, ensure_ascii=False))
        except Exception:
            pass

    if session_id:
        _notify_dashboard(session_id, "start", trigger)


if __name__ == "__main__":
    main()
