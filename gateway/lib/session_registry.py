"""Session registry - tracks all gateway-launched Claude sessions with metadata."""
import json
from datetime import datetime, timezone

from . import config as _cfg

REGISTRY_FILE = _cfg.sessions_dir() / "registry.jsonl"


def register_session(session_id: str, session_type: str, job_id: str = None,
                     model: str = None, run_id: str = None, **extra):
    """Append a session entry to the registry.

    Args:
        session_id: Claude CLI session UUID
        session_type: "cron", "user", or "auxiliary"
        job_id: cron job ID (e.g. "heartbeat", "self-evolve")
        model: model used (e.g. "sonnet", "opus", "haiku")
        run_id: cron run ID for linking to runs.jsonl
        **extra: additional metadata (source, topic_id, etc.)
    """
    if not session_id:
        return

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "type": session_type,
    }
    if job_id:
        entry["job_id"] = job_id
    if model:
        entry["model"] = model
    if run_id:
        entry["run_id"] = run_id
    if extra:
        entry.update(extra)

    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def list_sessions(session_type: str = None, job_id: str = None, limit: int = 50) -> list:
    """Read sessions from registry, optionally filtered."""
    if not REGISTRY_FILE.exists():
        return []
    sessions = []
    with open(REGISTRY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if session_type and entry.get("type") != session_type:
                    continue
                if job_id and entry.get("job_id") != job_id:
                    continue
                sessions.append(entry)
            except json.JSONDecodeError:
                continue
    return sessions[-limit:]
