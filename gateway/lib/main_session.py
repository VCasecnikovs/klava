"""
Main Session Management for Claude Gateway

The main session is a persistent session that acts as the orchestrator brain.
It can spawn sub-agents and process their results.
"""

import os
import re
from pathlib import Path
from typing import Optional

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

# Will be loaded from config. MAIN_SESSION_TOPIC is optional - when None,
# is_main_topic() always returns False (no special handling for any topic).
SESSIONS_DIR: Path = Path.home() / "Documents" / "GitHub" / "claude" / "gateway" / "sessions"
MAIN_SESSION_TOPIC: Optional[int] = None
MAIN_SESSION_KEY: str = "main"


def init_main_session(config: dict):
    """Initialize main session settings from config"""
    global SESSIONS_DIR, MAIN_SESSION_TOPIC, MAIN_SESSION_KEY

    sessions_config = config.get("sessions", {})
    main_config = config.get("main_session", {})

    if sessions_config.get("dir"):
        SESSIONS_DIR = Path(sessions_config["dir"])

    MAIN_SESSION_TOPIC = main_config.get("topic_id")  # None when absent
    MAIN_SESSION_KEY = main_config.get("session_key", "main")


def get_main_session_file() -> Path:
    """Get path to main session ID file"""
    return SESSIONS_DIR / f"{MAIN_SESSION_KEY}_claude_session.txt"


def get_main_session_id() -> Optional[str]:
    """Get current main session ID (returns None if file missing or content is not a valid UUID)"""
    session_file = get_main_session_file()
    if session_file.exists():
        value = session_file.read_text().strip()
        if value and _UUID_RE.match(value):
            return value
    return None


def save_main_session_id(session_id: str):
    """Save main session ID"""
    session_file = get_main_session_file()
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(session_id)


def clear_main_session_id():
    """Clear main session ID (use with caution - loses context)"""
    session_file = get_main_session_file()
    if session_file.exists():
        session_file.unlink()


def is_main_topic(topic_id: Optional[int]) -> bool:
    """True only when a main topic is configured AND matches."""
    return MAIN_SESSION_TOPIC is not None and topic_id == MAIN_SESSION_TOPIC


def get_main_topic_id() -> Optional[int]:
    """Get main session topic ID, or None if not configured."""
    return MAIN_SESSION_TOPIC


def get_main_session_key() -> str:
    """Get main session key"""
    return MAIN_SESSION_KEY
