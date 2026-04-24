#!/usr/bin/env python3
"""Claude Code SessionStart hook (matcher: compact) - clears compaction state after compaction completes."""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config as _cfg

LOG_FILE = _cfg.logs_dir() / "compaction.jsonl"
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
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    session_id = data.get("session_id", "")
    if not session_id:
        return

    # Log compaction completion
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sid": session_id[:16],
        "event": "compact_done",
    }

    # Calculate duration from state file
    state_file = STATE_DIR / f"{session_id[:16]}.json"
    duration_sec = None
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            started = state.get("compact_started")
            if started:
                start_dt = datetime.fromisoformat(started)
                duration_sec = (datetime.now(timezone.utc) - start_dt).total_seconds()
                record["duration_sec"] = round(duration_sec, 1)
        except Exception:
            pass

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Clear compaction state
    trigger = "auto"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            trigger = state.get("compact_trigger") or trigger
            state.pop("compacting", None)
            state.pop("compact_started", None)
            state.pop("compact_trigger", None)
            state_file.write_text(json.dumps(state, ensure_ascii=False))
        except Exception:
            pass

    _notify_dashboard(session_id, "done", trigger, duration_sec)


if __name__ == "__main__":
    main()
