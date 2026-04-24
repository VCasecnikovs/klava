"""Shared Telegram utilities for gateway components."""

import json
import logging
import os
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


def _tg_api_call(url: str, params: dict, timeout: int = 10) -> dict:
    """Make Telegram API call, bypassing macOS system proxy.

    Uses curl subprocess because Python urllib picks up macOS system proxy
    (e.g. 127.0.0.1:9090 from Surge/ClashX) which may not be running.
    """
    data = json.dumps(params)
    try:
        result = subprocess.run(
            ['curl', '-s', '-X', 'POST', url,
             '-H', 'Content-Type: application/json',
             '-d', data],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"curl TG API call failed: {e}")
    return {}


def markdown_to_html(text: str) -> str:
    """Convert common Markdown patterns to Telegram HTML.

    Handles: **bold**, *italic*, `code`, ```code blocks```, [links](url).
    Strips unsupported MD syntax (headers, bullet prefixes stay as-is).
    """
    # Code blocks first (before other transforms)
    text = re.sub(r'```(?:\w+)?\n?(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Bold (**text** or __text__)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Italic (*text* or _text_ - but not inside words with underscores)
    text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<i>\1</i>', text)
    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    # Strip markdown header prefixes (## Header -> Header)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text


def _split_message(text: str, max_length: int = 4000) -> list[str]:
    """Split long message into chunks at natural boundaries.

    Tries to split at: paragraph breaks > line breaks > sentence ends > spaces.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        search_text = remaining[:max_length]

        # Try paragraph break
        split_at = search_text.rfind('\n\n')
        if split_at > max_length * 0.5:
            split_at += 2
        else:
            # Try line break
            split_at = search_text.rfind('\n')
            if split_at > max_length * 0.6:
                split_at += 1
            else:
                # Try sentence end
                split_at = max_length
                for sep in ['. ', '! ', '? ']:
                    pos = search_text.rfind(sep)
                    if pos > max_length * 0.7:
                        split_at = pos + len(sep)
                        break
                else:
                    # Try space
                    space = search_text.rfind(' ')
                    if space > max_length * 0.8:
                        split_at = space + 1
                    else:
                        split_at = max_length

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks


def send_telegram_message(
    bot_token: str,
    chat_id: int,
    message: str,
    topic_id: Optional[int] = None,
    parse_mode: str = "Markdown",
    fallback_to_plain: bool = True,
    log_prefix: str = "",
    custom_logger: Optional[logging.Logger] = None,
) -> bool:
    """Send message to Telegram via Bot API.

    Args:
        bot_token: Telegram bot token
        chat_id: Chat ID to send to
        message: Message text
        topic_id: Optional topic/thread ID
        parse_mode: Parse mode ("Markdown", "HTML", or None)
        fallback_to_plain: If True, retry without parse_mode on error
        log_prefix: Optional prefix for log messages
        custom_logger: Optional custom logger

    Returns:
        True if message sent successfully, False otherwise
    """
    log = custom_logger or logger
    prefix = f"{log_prefix}: " if log_prefix else ""

    # Convert Markdown formatting to HTML when using HTML parse_mode
    if parse_mode == "HTML":
        message = markdown_to_html(message)

    # Split into chunks instead of truncating
    chunks = _split_message(message)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    all_ok = True

    for chunk in chunks:
        # Try with parse_mode first, then without if fallback enabled
        modes_to_try = [parse_mode]
        if fallback_to_plain and parse_mode:
            modes_to_try.append(None)

        sent = False
        for mode in modes_to_try:
            params = {'chat_id': chat_id, 'text': chunk}
            if topic_id:
                params['message_thread_id'] = topic_id
            if mode:
                params['parse_mode'] = mode

            result = _tg_api_call(url, params)
            if result.get('ok'):
                sent = True
                break
            elif result.get('error_code') == 400 and mode and fallback_to_plain:
                log.warning(f"{prefix}{mode} failed, retrying as plain text")
                # Strip HTML tags so they don't show literally in plain text
                chunk = re.sub(r'<[^>]+>', '', chunk)
                continue
            elif result:
                log.error(f"{prefix}Telegram API error: {result}")
                break
            else:
                log.error(f"{prefix}Telegram send failed: no response")
                break

        if not sent:
            all_ok = False
            break

    if all_ok:
        log.info(f"{prefix}Sent to Telegram (chat_id={chat_id}, topic={topic_id}, chunks={len(chunks)})")
    return all_ok


def send_telegram_message_with_id(
    bot_token: str,
    chat_id: int,
    message: str,
    topic_id: Optional[int] = None,
    parse_mode: str = "HTML"
) -> Optional[int]:
    """Send message and return message_id for later editing.

    Returns:
        message_id if successful, None otherwise
    """
    if len(message) > 4000:
        message = message[:3997] + "..."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    params = {'chat_id': chat_id, 'text': message}
    if topic_id:
        params['message_thread_id'] = topic_id
    if parse_mode:
        params['parse_mode'] = parse_mode

    result = _tg_api_call(url, params)
    if result.get('ok'):
        return result.get('result', {}).get('message_id')

    if result:
        logger.error(f"Telegram send failed: {result}")
    return None


def edit_telegram_message(
    bot_token: str,
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: str = "HTML"
) -> bool:
    """Edit existing Telegram message.

    Returns:
        True if successful, False otherwise
    """
    if len(text) > 4000:
        text = text[:3997] + "..."

    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"

    params = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text
    }
    if parse_mode:
        params['parse_mode'] = parse_mode

    result = _tg_api_call(url, params)
    if result.get('ok'):
        return True
    # Message not modified is OK (content unchanged)
    if result.get('error_code') == 400:
        return True
    if result:
        logger.error(f"Telegram edit failed: {result}")
    return False


def get_telegram_config(config: dict) -> tuple[str, int, Optional[int]]:
    """Extract Telegram config from gateway config.

    Args:
        config: Gateway config dict

    Returns:
        Tuple of (bot_token, chat_id, default_topic_id)
    """
    tg_config = config.get("telegram", {})
    bot_token = os.environ.get("TG_BOT_TOKEN", tg_config.get("bot_token", ""))
    allowed_users = tg_config.get("allowed_users", [])
    chat_id = allowed_users[0] if allowed_users else 0

    heartbeat_config = config.get("heartbeat", {})
    default_topic_id = heartbeat_config.get("topic_id")

    return bot_token, chat_id, default_topic_id
