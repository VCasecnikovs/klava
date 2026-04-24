"""Universal notification feed.

send_feed() is the single entry point for all notifications. Writes to a JSONL
log and optionally forwards to Telegram. No topic routing - everything goes to
the configured chat.
"""

import json
import logging
import os
from datetime import datetime, timezone

from lib import config

logger = logging.getLogger(__name__)


def send_feed(
    message: str,
    topic: str = "General",
    parse_mode: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    telegram: bool = True,
    deltas: list | None = None,
):
    """Universal notification - writes to feed log, optionally sends to Telegram.

    `topic` is just a label stored in the log. It no longer routes to a
    specific Telegram thread.
    """
    _write_log(message, topic, parse_mode, job_id, session_id, deltas)

    if telegram:
        _send_telegram(message, parse_mode, job_id)


def _write_log(message, topic, parse_mode, job_id, session_id, deltas):
    """Append to feed JSONL log."""
    log_path = str(config.feed_log())
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "message": message,
            "parse_mode": parse_mode,
        }
        if job_id:
            entry["job_id"] = job_id
        if session_id:
            entry["session_id"] = session_id
        if deltas:
            entry["deltas"] = deltas
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write feed log: {e}")


def _send_telegram(message, parse_mode, job_id):
    """Deliver to Telegram default chat."""
    try:
        from .telegram_utils import send_telegram_message
        tg = config.telegram()
        bot_token = tg.get("bot_token") or ""
        chat_id = config.telegram_chat_id()
        if not bot_token or not chat_id:
            return
        send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            message=message,
            parse_mode=parse_mode or "HTML",
            log_prefix=f"Feed/{job_id}" if job_id else "Feed",
        )
    except Exception as e:
        logger.warning(f"Failed to send Telegram: {e}")
