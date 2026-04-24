#!/usr/bin/env python3
"""
Telegram Gateway for Claude Code
Bidirectional messaging between Telegram and Claude Code CLI
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml
from dotenv import load_dotenv
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Load .env before anything reads config
load_dotenv(Path(__file__).parent.parent / ".env")

# Telethon for Premium voice transcription
from telethon import TelegramClient, functions
from telethon.sessions import StringSession

# Add lib to path for status collector
sys.path.insert(0, str(Path(__file__).parent))
from lib.status_collector import collect_status
from lib.main_session import (
    init_main_session, is_main_topic, get_main_session_id,
    save_main_session_id, get_main_topic_id
)
from lib.session_registry import register_session
from lib.spawn_agent_tool import (
    init_spawn_agent, parse_spawn_request, spawn_agent,
    format_spawn_result, get_spawn_tool_description
)
from lib.subagent_status import get_subagent_status_section
from lib.process_reaper import kill_sdk_subprocess, start_reaper_thread

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('/tmp/tg-gateway.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load config
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

from lib import config as _cfg

BOT_TOKEN = os.environ.get('TG_BOT_TOKEN', config['telegram']['bot_token'])
ALLOWED_USERS = set(config['telegram']['allowed_users'])
SESSIONS_DIR = _cfg.sessions_dir()
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
SKILLS_DIR = _cfg.skills_dir()
LAUNCHD_PREFIX = _cfg.launchd_prefix()
CLAUDE_CLI = _cfg.claude_cli()

# Initialize main session settings
init_main_session(config)

# Initialize spawn_agent for sub-agents
if config.get('subagents', {}).get('enabled', False):
    init_spawn_agent(config)

# MCP config path - contains MCP server definitions
MCP_CONFIG = str(_cfg.mcp_servers_file())

# Home directory prefix for path shortening in display
_HOME_PREFIX = str(Path.home()) + "/"

# Telethon client for Premium voice transcription
# Uses same session as telegram-mcp. All credentials from config (env-interpolated).
_telethon_cfg = _cfg.integrations().get('telethon', {}) or {}
TELETHON_API_ID = int(_telethon_cfg.get('api_id') or 0)
TELETHON_API_HASH = _telethon_cfg.get('api_hash') or ''
TELETHON_SESSION_STRING = _telethon_cfg.get('session_string') or ''
telethon_client: TelegramClient | None = None

# Draft streaming config (requires Threaded Mode enabled via @BotFather)
STREAM_MODE = config.get('telegram', {}).get('stream_mode', 'draft')  # 'draft', 'spinner', 'off'
DRAFT_THROTTLE_MS = config.get('telegram', {}).get('draft_throttle_ms', 500)  # Increased to avoid flood

# Track bot start time
BOT_START_TIME = datetime.now()

# Bot's own commands (not skills)
BOT_COMMANDS = {'start', 'new', 'status', 'id', 'skills'}

# Telegram-specific formatting instructions (shared by run_claude_async and run_claude)
TELEGRAM_INSTRUCTIONS = """IMPORTANT - Output in Telegram HTML format:
- <b>bold</b> for emphasis
- <i>italic</i> for subtle text
- <u>underline</u> for underlined
- <s>strikethrough</s> for crossed out
- <tg-spoiler>spoiler</tg-spoiler> for hidden text
- <code>mono</code> for code/paths/commands
- <pre>code block</pre> for code blocks
- <a href="url">link</a> for links
- <blockquote>quote</blockquote> for quotes

Escape only: < > & (use &lt; &gt; &amp;)
Keep responses concise

**A2UI - Interactive Buttons:**
Append to response: /buttons [{"text": "✅ Option 1", "data": "action_1"}, {"text": "🔍 Option 2", "data": "action_2"}]

**Send Files to User:**
To send files back: /sendfile /path/to/file
Or: /sendfile {"path": "/path/to/file", "caption": "Description"}

**Files from User:**
User files appear as [File attached: /path]. Use Read tool to analyze.
---

"""

# Pending permission requests: {request_id: asyncio.Event}
# Used for interactive permissions via TG buttons
PENDING_PERMISSIONS: dict[str, dict] = {}  # {request_id: {"event": Event, "response": str}}

# Active requests that can be cancelled: {topic_key: {"cancel_event": Event, "process": Process}}
ACTIVE_REQUESTS: dict[str, dict] = {}

# Per-topic locks to prevent race conditions when multiple messages come in
TOPIC_LOCKS: dict[str, asyncio.Lock] = {}

def get_topic_lock(topic_key: str) -> asyncio.Lock:
    """Get or create a lock for a specific topic."""
    if topic_key not in TOPIC_LOCKS:
        # Evict old locks if too many (prevent memory leak)
        if len(TOPIC_LOCKS) > 100:
            keys_to_remove = list(TOPIC_LOCKS.keys())[:50]
            for k in keys_to_remove:
                if not TOPIC_LOCKS[k].locked():
                    del TOPIC_LOCKS[k]
        TOPIC_LOCKS[topic_key] = asyncio.Lock()
    return TOPIC_LOCKS[topic_key]


def _parse_claude_result(data: dict) -> dict:
    """Parse Claude CLI JSON result into standardized response dict."""
    return {
        'result': data.get('result', 'No response'),
        'session_id': data.get('session_id'),
        'cost': data.get('total_cost_usd', 0),
        'duration': data.get('duration_ms', 0) / 1000,
        'turns': data.get('num_turns', 1),
        'models': list(data.get('modelUsage', {}).keys()),
        'input_tokens': data.get('usage', {}).get('input_tokens', 0),
        'output_tokens': data.get('usage', {}).get('output_tokens', 0),
        'cache_read': data.get('usage', {}).get('cache_read_input_tokens', 0),
    }


def get_available_skills() -> list[str]:
    """Get list of available skills from ~/.claude/skills/"""
    if not SKILLS_DIR.exists():
        return []
    return sorted([
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    ])


def get_session_key(user_id: int, thread_id: int | None = None) -> str:
    """Get session key based on user and optional thread (topic)"""
    if thread_id:
        return f"tg_{user_id}_topic_{thread_id}"
    return f"tg_{user_id}"


def get_session_id_file(user_id: int, thread_id: int | None = None) -> Path:
    """Get file that stores Claude session ID for a user/topic"""
    key = get_session_key(user_id, thread_id)
    return SESSIONS_DIR / f"{key}_claude_session.txt"


def get_session_log_file(user_id: int, thread_id: int | None = None) -> Path:
    """Get session log file path for a user/topic"""
    key = get_session_key(user_id, thread_id)
    return SESSIONS_DIR / f"{key}.jsonl"


def get_session_id(user_id: int, thread_id: int | None = None) -> str | None:
    """Get current Claude session ID for user/topic"""
    session_file = get_session_id_file(user_id, thread_id)
    if session_file.exists():
        return session_file.read_text().strip()
    return None


def save_session_id(user_id: int, session_id: str, thread_id: int | None = None):
    """Save Claude session ID for user/topic (atomic write)."""
    session_file = get_session_id_file(user_id, thread_id)
    tmp_file = session_file.with_suffix('.tmp')
    tmp_file.write_text(session_id)
    os.replace(tmp_file, session_file)
    key = get_session_key(user_id, thread_id)
    logger.info(f"Saved session {session_id[:8]}... for {key}")


def clear_session_id(user_id: int, thread_id: int | None = None):
    """Clear Claude session ID for user/topic"""
    session_file = get_session_id_file(user_id, thread_id)
    if session_file.exists():
        session_file.unlink()
        key = get_session_key(user_id, thread_id)
        logger.info(f"Cleared session for {key}")


def append_to_log(user_id: int, entry: dict, thread_id: int | None = None):
    """Append an entry to the session log"""
    log_file = get_session_log_file(user_id, thread_id)
    entry['timestamp'] = time.time()
    entry['datetime'] = datetime.now().isoformat()
    with open(log_file, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


async def run_claude_async(prompt: str, session_id: str | None = None, timeout: int = 1800,
                          tool_callback=None, text_callback=None,
                          permission_callback: Optional[Callable] = None) -> dict:
    """
    Run Claude Code via ClaudeSDKClient (streaming mode).
    Returns dict with: result, session_id, cost, duration, turns, models
    """
    from claude_agent_sdk import (
        ClaudeSDKClient, ClaudeAgentOptions,
        AssistantMessage as SDKAssistant, ResultMessage as SDKResult,
        TextBlock as SDKText, ToolUseBlock as SDKToolUse,
    )

    full_prompt = TELEGRAM_INSTRUCTIONS + prompt

    client = None
    try:
        opts = {
            "allowed_tools": ["*"],
            "permission_mode": "bypassPermissions",
            "cwd": Path.home(),
            "cli_path": CLAUDE_CLI,
        }

        if session_id:
            opts["resume"] = session_id

        if os.path.exists(MCP_CONFIG):
            opts["mcp_servers"] = MCP_CONFIG

        options = ClaudeAgentOptions(**opts)

        result_msg = None

        async with asyncio.timeout(timeout):
            async with ClaudeSDKClient(options) as client:
                await client.connect()
                await client.query(full_prompt)

                async for message in client.receive_messages():
                    if isinstance(message, SDKAssistant):
                        for block in message.content:
                            if isinstance(block, SDKText):
                                if text_callback:
                                    text_callback(block.text)
                            elif isinstance(block, SDKToolUse) and tool_callback:
                                tool_callback(block.name, block.input or {})

                    elif isinstance(message, SDKResult):
                        result_msg = message
                        break  # ResultMessage is final - iterator won't terminate on its own

        if not result_msg:
            return {'error': 'No result received', 'session_id': None}

        return {
            'result': result_msg.result or 'No response',
            'session_id': result_msg.session_id,
            'cost': result_msg.total_cost_usd or 0,
            'duration': (result_msg.duration_ms or 0) / 1000,
            'turns': result_msg.num_turns,
            'models': [],
            'input_tokens': (result_msg.usage or {}).get('input_tokens', 0),
            'output_tokens': (result_msg.usage or {}).get('output_tokens', 0),
            'cache_read': (result_msg.usage or {}).get('cache_read_input_tokens', 0),
        }

    except TimeoutError:
        return {'result': f'Request timed out after {timeout}s', 'session_id': None}
    except Exception as e:
        logger.exception("Error running Claude SDK")
        return {'result': f"Error: {str(e)}", 'session_id': None}
    finally:
        # Force-kill SDK subprocess to prevent zombie accumulation
        kill_sdk_subprocess(client)


def run_claude(prompt: str, session_id: str | None = None, timeout: int = 1800,
               tool_callback=None, text_callback=None, request_id: str | None = None,
               model: str | None = None) -> dict:
    """
    Synchronous wrapper - runs ClaudeSDKClient (streaming mode) in a new event loop.
    """
    from claude_agent_sdk import (
        ClaudeSDKClient, ClaudeAgentOptions,
        AssistantMessage as SDKAssistant, ResultMessage as SDKResult,
        TextBlock as SDKText, ToolUseBlock as SDKToolUse,
    )

    full_prompt = TELEGRAM_INSTRUCTIONS + prompt
    is_fast_mode = model == 'haiku'

    client_ref = [None]  # Mutable container to capture client for cleanup

    try:
        opts = {
            "permission_mode": "bypassPermissions",
            "cwd": Path.home(),
            "cli_path": CLAUDE_CLI,
        }

        if model:
            opts["model"] = model

        # For haiku: no tools for speed. For others: all tools
        if is_fast_mode:
            opts["allowed_tools"] = []
        else:
            opts["allowed_tools"] = ["*"]
            if os.path.exists(MCP_CONFIG):
                opts["mcp_servers"] = MCP_CONFIG

        if session_id:
            opts["resume"] = session_id

        options = ClaudeAgentOptions(**opts)

        async def _run():
            result_msg = None

            async with asyncio.timeout(timeout):
                async with ClaudeSDKClient(options) as client:
                    client_ref[0] = client
                    await client.connect()
                    await client.query(full_prompt)

                    async for message in client.receive_messages():
                        # Check cancellation
                        if request_id and ACTIVE_REQUESTS.get(request_id, {}).get("cancelled"):
                            logger.info(f"Request {request_id} cancelled, interrupting")
                            await client.interrupt()
                            return {'result': 'Cancelled', 'session_id': None}

                        if isinstance(message, SDKAssistant):
                            for block in message.content:
                                if isinstance(block, SDKText):
                                    if text_callback:
                                        text_callback(block.text)
                                elif isinstance(block, SDKToolUse) and tool_callback:
                                    tool_callback(block.name, block.input or {})

                        elif isinstance(message, SDKResult):
                            result_msg = message
                            break  # ResultMessage is final - iterator won't terminate on its own

            if not result_msg:
                return {'error': 'No result received', 'session_id': None}

            return {
                'result': result_msg.result or 'No response',
                'session_id': result_msg.session_id,
                'cost': result_msg.total_cost_usd or 0,
                'duration': (result_msg.duration_ms or 0) / 1000,
                'turns': result_msg.num_turns,
                'models': [],
                'input_tokens': (result_msg.usage or {}).get('input_tokens', 0),
                'output_tokens': (result_msg.usage or {}).get('output_tokens', 0),
                'cache_read': (result_msg.usage or {}).get('cache_read_input_tokens', 0),
            }

        return asyncio.run(_run())

    except TimeoutError:
        return {'result': f'Request timed out after {timeout}s', 'session_id': None}
    except Exception as e:
        logger.exception("Error running Claude SDK")
        return {'result': f"Error: {str(e)}", 'session_id': None}
    finally:
        # Force-kill SDK subprocess to prevent zombie accumulation
        kill_sdk_subprocess(client_ref[0])


def smart_chunk_text(text: str, max_length: int = 4096) -> list[str]:
    """
    Split text into chunks respecting code blocks and natural boundaries.

    Priority for split points:
    1. Paragraph breaks (\n\n)
    2. Line breaks (\n)
    3. Sentence endings (. ! ?)
    4. Word boundaries (spaces)
    5. Hard split (last resort)
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Find the best split point within max_length
        search_text = remaining[:max_length]

        # Check if we're inside a code block
        # Count opening and closing ``` before split point
        code_blocks_before = search_text.count('```')
        inside_code_block = code_blocks_before % 2 == 1

        if inside_code_block:
            # Find the start of this code block and don't split before it ends
            last_code_start = search_text.rfind('```')

            # Look for the closing ``` after our search area
            close_pos = remaining.find('```', last_code_start + 3)

            if close_pos != -1 and close_pos < len(remaining):
                # Include the closing ``` and some buffer
                end_of_block = close_pos + 3

                # Find next good split point after code block
                next_para = remaining.find('\n\n', end_of_block)
                next_line = remaining.find('\n', end_of_block)

                if next_para != -1 and next_para < max_length * 1.5:
                    split_at = next_para + 2
                elif next_line != -1 and next_line < max_length * 1.5:
                    split_at = next_line + 1
                elif end_of_block < max_length * 1.5:
                    split_at = end_of_block
                else:
                    # Code block too long, have to split it
                    split_at = max_length
            else:
                # No closing found, split at max
                split_at = max_length
        else:
            # Not in code block, find best natural break
            split_at = max_length

            # Try paragraph break first
            para_break = search_text.rfind('\n\n')
            if para_break > max_length * 0.5:  # At least 50% of max
                split_at = para_break + 2
            else:
                # Try line break
                line_break = search_text.rfind('\n')
                if line_break > max_length * 0.6:
                    split_at = line_break + 1
                else:
                    # Try sentence ending
                    for sep in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
                        pos = search_text.rfind(sep)
                        if pos > max_length * 0.7:
                            split_at = pos + len(sep)
                            break
                    else:
                        # Try word boundary
                        space = search_text.rfind(' ')
                        if space > max_length * 0.8:
                            split_at = space + 1

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks


def markdown_to_markdownv2(text: str) -> str:
    """Pass through - Claude outputs native MarkdownV2 format."""
    return text


def sanitize_markdown(text: str) -> str:
    """Fix common Markdown issues that break Telegram parsing."""
    import re

    # Count and fix unpaired markers
    markers = ['**', '`', '_']
    for marker in markers:
        count = text.count(marker)
        if count % 2 == 1:
            # Find last occurrence and escape it
            pos = text.rfind(marker)
            if pos != -1:
                escaped = '\\' + marker[0] if len(marker) == 1 else marker[0] + '\\' + marker[0]
                text = text[:pos] + escaped + text[pos+len(marker):]

    # Fix unpaired code blocks
    if text.count('```') % 2 == 1:
        text += '\n```'

    return text


async def safe_send_message(bot, chat_id, text, message_thread_id=None, reply_markup=None, **kwargs):
    """Send message with Markdown, fallback to plain text on parse error."""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='HTML',
            message_thread_id=message_thread_id,
            reply_markup=reply_markup,
            **kwargs
        )
    except Exception as e:
        if 'parse' in str(e).lower() or 'entities' in str(e).lower():
            # Markdown parse error - try without formatting
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=message_thread_id,
                reply_markup=reply_markup,
                **kwargs
            )
        raise


async def safe_edit_message(msg, text, reply_markup=None, **kwargs):
    """Edit message with Markdown, fallback to plain text on parse error."""
    try:
        return await msg.edit_text(text, parse_mode='HTML', reply_markup=reply_markup, **kwargs)
    except Exception as e:
        if 'parse' in str(e).lower() or 'entities' in str(e).lower():
            return await msg.edit_text(text, reply_markup=reply_markup, **kwargs)
        raise


def format_response_with_meta(response: dict) -> str:
    """Format response with metadata footer"""
    text = response.get('result', 'No response')

    # Build metadata footer - clean compact format
    meta_parts = []

    cost = response.get('cost', 0)
    if cost:
        meta_parts.append(f"${cost:.2f}")

    duration = response.get('duration', 0)
    if duration:
        meta_parts.append(f"{duration:.0f}s")

    turns = response.get('turns', 1)
    if turns > 1:
        meta_parts.append(f"{turns}t")

    # Token info - compact
    out_tokens = response.get('output_tokens', 0)
    cache_read = response.get('cache_read', 0)
    if cache_read:
        meta_parts.append(f"{cache_read//1000}k⚡")
    elif out_tokens:
        meta_parts.append(f"{out_tokens}tok")

    if meta_parts:
        # Use italic for subtle footer, dot separator (HTML format)
        footer = " · ".join(meta_parts)
        text = f"{text}\n\n<i>{footer}</i>"

    return text


def parse_inline_buttons(text: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Parse Telegram inline keyboard buttons from Claude response.

    Format: /buttons [{"text": "Label", "data": "callback_data"}, ...]
    Returns: (text_without_buttons, keyboard_markup or None)
    """
    import re

    # Find /buttons [...] pattern
    pattern = r'/buttons\s+(\[.*?\])'
    match = re.search(pattern, text, re.DOTALL)

    if not match:
        return text, None

    try:
        # Parse JSON array
        buttons_json = match.group(1)
        buttons_data = json.loads(buttons_json)

        # Build keyboard
        keyboard = []
        row = []
        for btn in buttons_data:
            if isinstance(btn, dict) and 'text' in btn:
                # Support both 'data' and 'url' buttons
                if 'data' in btn:
                    row.append(InlineKeyboardButton(btn['text'], callback_data=btn['data']))
                elif 'url' in btn:
                    row.append(InlineKeyboardButton(btn['text'], url=btn['url']))

                # Max 2 buttons per row for better mobile UX
                if len(row) >= 2:
                    keyboard.append(row)
                    row = []

        # Add remaining buttons
        if row:
            keyboard.append(row)

        # Remove /buttons [...] from text
        clean_text = text[:match.start()] + text[match.end():]
        clean_text = clean_text.strip()

        return clean_text, InlineKeyboardMarkup(keyboard)

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to parse inline buttons: {e}")
        return text, None


def parse_file_attachments(text: str) -> tuple[str, list[dict]]:
    """Parse file attachment commands from Claude response.

    Format: /sendfile /path/to/file
    Or: /sendfile {"path": "/path/to/file", "caption": "Description"}
    Returns: (text_without_commands, list of file dicts)
    """
    import re

    files = []

    # Pattern 1: /sendfile /path/to/file
    simple_pattern = r'/sendfile\s+([^\s\n]+)'
    for match in re.finditer(simple_pattern, text):
        path = match.group(1).strip()
        if path.startswith('{'):
            continue  # Skip JSON format, handled below
        files.append({"path": path, "caption": None})

    # Pattern 2: /sendfile {...}
    json_pattern = r'/sendfile\s+(\{[^}]+\})'
    for match in re.finditer(json_pattern, text):
        try:
            file_data = json.loads(match.group(1))
            files.append({
                "path": file_data.get("path", ""),
                "caption": file_data.get("caption")
            })
        except json.JSONDecodeError:
            continue

    # Remove all /sendfile commands from text
    clean_text = re.sub(r'/sendfile\s+(?:\{[^}]+\}|[^\s\n]+)', '', text)
    clean_text = clean_text.strip()

    return clean_text, files


async def send_files_to_user(context, chat_id: int, files: list[dict], message_thread_id: int | None = None):
    """Send files back to user in Telegram."""
    for file_info in files:
        path = file_info.get("path", "")
        caption = file_info.get("caption")

        if not path:
            continue

        # Expand home directory
        if path.startswith("~"):
            path = os.path.expanduser(path)

        file_path = Path(path)
        if not file_path.exists():
            logger.warning(f"File not found: {path}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ File not found: `{path}`",
                parse_mode='HTML',
                message_thread_id=message_thread_id
            )
            continue

        try:
            # Determine file type and send appropriately
            suffix = file_path.suffix.lower()

            if suffix in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                # Send as photo
                with open(file_path, 'rb') as f:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=caption,
                        message_thread_id=message_thread_id
                    )
            elif suffix in ['.mp4', '.mov', '.avi', '.webm']:
                # Send as video
                with open(file_path, 'rb') as f:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        caption=caption,
                        message_thread_id=message_thread_id
                    )
            elif suffix in ['.mp3', '.ogg', '.wav', '.m4a']:
                # Send as audio
                with open(file_path, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        caption=caption,
                        message_thread_id=message_thread_id
                    )
            else:
                # Send as document
                with open(file_path, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        caption=caption,
                        filename=file_path.name,
                        message_thread_id=message_thread_id
                    )

            logger.info(f"Sent file to user: {path}")

        except Exception as e:
            logger.error(f"Failed to send file {path}: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Failed to send file: `{path}`\nError: {str(e)[:100]}",
                parse_mode='HTML',
                message_thread_id=message_thread_id
            )


async def check_user(update: Update) -> bool:
    """Check if user is allowed"""
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USERS:
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        await update.message.reply_text("Unauthorized. This bot is private.")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if not await check_user(update):
        return

    await update.message.reply_text(
        "Клавдия - Claude Code Gateway\n\n"
        "Send any message to chat with Claude.\n"
        "Session is maintained by Claude (with compaction).\n\n"
        "Commands:\n"
        "/new - Start new session\n"
        "/status - System status\n"
        "/id - Show current session ID"
    )


def get_system_status(user_id: int, thread_id: int | None = None) -> dict:
    """Gather system status information"""
    status = {}

    # Bot uptime
    uptime = datetime.now() - BOT_START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    status['uptime'] = f"{hours}h {minutes}m {seconds}s"

    # Check if this is main session (persistent orchestrator)
    is_main = is_main_topic(thread_id)
    status['is_main_session'] = is_main

    # Session ID (topic-aware or main session)
    if is_main:
        session_id = get_main_session_id()
        status['session_type'] = "🧠 MAIN (Orchestrator)"
    else:
        session_id = get_session_id(user_id, thread_id)
        status['session_type'] = "Regular"
    status['session_id'] = session_id[:8] + "..." if session_id else "None"
    status['topic_id'] = thread_id

    # Collect comprehensive status from status_collector
    try:
        sys_status = collect_status()
        status['daemons'] = sys_status.get('daemons', {})
        status['jobs'] = sys_status.get('job_summaries', [])
        status['recent_runs'] = sys_status.get('recent_runs', [])
        status['daemon_start_time'] = sys_status.get('daemon_start_time')
    except Exception as e:
        logger.error(f"Status collection failed: {e}")
        status['daemons'] = {'error': 'Failed to check'}
        status['jobs'] = []
        status['recent_runs'] = []

    # Last heartbeat - keep existing logic for backward compatibility
    heartbeat_log = Path('/tmp/heartbeat.log')
    if heartbeat_log.exists():
        try:
            with open(heartbeat_log) as f:
                lines = f.readlines()
            for line in reversed(lines):
                if 'Starting heartbeat' in line or 'HEARTBEAT_OK' in line or 'Alert sent' in line:
                    status['last_heartbeat'] = line.strip()[:80]
                    break
            else:
                status['last_heartbeat'] = "No recent entries"
        except Exception:
            status['last_heartbeat'] = "Error reading log"
    else:
        status['last_heartbeat'] = "No log file"

    # Claude CLI
    try:
        result = subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=5)
        status['claude'] = result.stdout.strip() if result.returncode == 0 else "Not available"
    except Exception:
        status['claude'] = "Not available"

    return status


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    thread_id = getattr(update.message, 'message_thread_id', None)
    sys_status = get_system_status(user_id, thread_id)

    # Format daemons
    daemons = sys_status.get('daemons', {})
    daemons_str = "\n".join(
        f"  {name.replace(LAUNCHD_PREFIX + '.', '')}: {state}"
        for name, state in daemons.items()
    ) or "  None found"

    # Format scheduled jobs
    jobs = sys_status.get('jobs', [])
    if jobs:
        jobs_str = "\n".join(
            f"  {'✅' if j.get('status') == 'completed' else '⏸️' if not j.get('enabled') else '⏱️'} "
            f"**{j.get('name', j.get('id'))}**\n"
            f"    ↳ Last: {j.get('time_since', 'never')}, Next: {j.get('time_until', '?')}"
            for j in jobs[:5]  # Show max 5 jobs
        )
    else:
        jobs_str = "  No scheduled jobs"

    # Format recent runs
    recent = sys_status.get('recent_runs', [])
    if recent:
        latest = recent[-1]
        latest_str = (
            f"  **{latest.get('job_id')}** "
            f"{'✅' if latest.get('status') == 'completed' else '❌'}\n"
            f"    ↳ {latest.get('duration_seconds', 0)}s, "
            f"${latest.get('cost_usd', 0):.3f}"
        )
    else:
        latest_str = "  No recent runs"

    # Session type indicator
    session_type = sys_status.get('session_type', 'Regular')
    session_line = f"📱 **Session:** {session_type} `{sys_status['session_id']}`"

    # Sub-agent status section
    subagent_section = get_subagent_status_section()
    subagent_str = f"\n\n{subagent_section}" if subagent_section else ""

    msg = (
        f"🤖 **Клавдия - Claude Code Gateway**\n\n"
        f"{session_line}\n"
        f"⏱️ **Uptime:** {sys_status['uptime']}\n\n"
        f"⚙️ **Daemons:**\n{daemons_str}\n\n"
        f"📅 **Scheduled Jobs:**\n{jobs_str}\n\n"
        f"🏃 **Recent Run:**\n{latest_str}"
        f"{subagent_str}"
    )

    await update.message.reply_text(msg, parse_mode='HTML')


async def show_session_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /id command - show full session ID"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    thread_id = getattr(update.message, 'message_thread_id', None)

    # Check for main session
    is_main = is_main_topic(thread_id)
    if is_main:
        session_id = get_main_session_id()
        session_key = "main_session"
        session_type = "🧠 MAIN (Orchestrator)"
    else:
        session_id = get_session_id(user_id, thread_id)
        session_key = get_session_key(user_id, thread_id)
        session_type = "Regular"

    if session_id:
        await update.message.reply_text(
            f"**Type:** {session_type}\n**Session:** `{session_key}`\n**ID:** `{session_id}`",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(f"No active session for `{session_key}`. Send a message to start one.", parse_mode='HTML')


async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new command - start fresh session for current topic"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    thread_id = getattr(update.message, 'message_thread_id', None)

    # Prevent clearing main session (persistent orchestrator)
    if is_main_topic(thread_id):
        await update.message.reply_text(
            "⚠️ Main session is persistent and cannot be reset.\n"
            "This is the orchestrator brain with full context.",
            parse_mode='HTML'
        )
        return

    session_key = get_session_key(user_id, thread_id)

    clear_session_id(user_id, thread_id)

    # Also clear log
    log_file = get_session_log_file(user_id, thread_id)
    if log_file.exists():
        log_file.unlink()

    await update.message.reply_text(f"Session `{session_key}` cleared. Next message starts fresh.", parse_mode='HTML')


async def list_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skills command - list available skills"""
    if not await check_user(update):
        return

    skills = get_available_skills()
    if skills:
        skills_list = "\n".join(f"  /{s}" for s in skills)
        await update.message.reply_text(
            f"<b>Available skills:</b>\n{skills_list}\n\n"
            f"Use <code>/skill-name</code> to run a skill.",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text("No skills found.")


async def handle_skill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skill commands (/<skill-name> [args])"""
    if not await check_user(update):
        return

    message = update.message.text
    # Extract command name (without /)
    parts = message.split(maxsplit=1)
    cmd = parts[0][1:]  # Remove leading /
    args = parts[1] if len(parts) > 1 else ""

    # Skip bot's own commands
    if cmd in BOT_COMMANDS:
        return

    # Check if it's a valid skill (also try with dashes instead of underscores)
    skills = get_available_skills()
    skill_name = cmd
    if cmd not in skills:
        # Try converting underscores to dashes
        skill_name = cmd.replace('_', '-')
    if skill_name not in skills:
        await update.message.reply_text(f"Unknown command: /{cmd}\nUse /skills to see available skills.")
        return

    user_id = update.effective_user.id
    thread_id = getattr(update.message, 'message_thread_id', None)

    # Check for main session
    is_main = is_main_topic(thread_id)
    if is_main:
        session_id = get_main_session_id()
    else:
        session_id = get_session_id(user_id, thread_id)

    # Build prompt to run skill
    prompt = f"/{skill_name}" + (f" {args}" if args else "")

    logger.info(f"User {user_id} (topic={thread_id}{'[MAIN]' if is_main else ''}) running skill: {prompt}")

    # Log
    append_to_log(user_id, {
        "role": "user",
        "content": prompt,
        "type": "skill"
    }, thread_id)

    # Send typing indicator
    await update.message.chat.send_action("typing")

    # Run Claude with skill command
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, run_claude, prompt, session_id
    )

    # Save session ID if we got a new one
    if response.get('session_id'):
        if is_main:
            save_main_session_id(response['session_id'])
        else:
            save_session_id(user_id, response['session_id'], thread_id)
        register_session(
            session_id=response['session_id'],
            session_type="user",
            source="telegram",
            topic_id=thread_id,
        )

    # Log response
    append_to_log(user_id, {
        "role": "assistant",
        "content": response.get('result', ''),
        "cost": response.get('cost'),
        "duration": response.get('duration')
    }, thread_id)

    # Format response with metadata
    text = format_response_with_meta(response)

    # Parse inline buttons (A2UI) from response
    text, keyboard = parse_inline_buttons(text)

    # Send response using smart chunking
    chunks = smart_chunk_text(text, max_length=4096)
    if len(chunks) == 1:
        await update.message.reply_text(chunks[0], parse_mode='HTML', reply_markup=keyboard)
    else:
        for i, chunk in enumerate(chunks):
            # Add keyboard only to last chunk
            reply_markup = keyboard if (i == len(chunks) - 1 and keyboard) else None
            await update.message.reply_text(chunk, parse_mode='HTML', reply_markup=reply_markup)
            await asyncio.sleep(0.5)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming documents/files from user"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_thread_id = getattr(update.message, 'message_thread_id', None)

    document = update.message.document
    caption = update.message.caption or ""

    logger.info(f"User {user_id} sent document: {document.file_name} ({document.file_size} bytes)")

    # Download file to temp directory
    import tempfile
    temp_dir = Path(tempfile.gettempdir()) / "tg_gateway_files"
    temp_dir.mkdir(exist_ok=True)

    # Create unique filename
    file_ext = Path(document.file_name).suffix if document.file_name else ""
    temp_file = temp_dir / f"{user_id}_{document.file_unique_id}{file_ext}"

    try:
        # Download file
        tg_file = await document.get_file()
        await tg_file.download_to_drive(temp_file)
        logger.info(f"Downloaded file to {temp_file}")

        # Build prompt with file reference
        if caption:
            message = f"[File attached: {temp_file}]\n\nUser message: {caption}"
        else:
            message = f"[File attached: {temp_file}]\n\nAnalyze or process this file as appropriate. The file is: {document.file_name}"

        # Get session and process like regular message (check main session)
        is_main = is_main_topic(message_thread_id)
        if is_main:
            session_id = get_main_session_id()
        else:
            session_id = get_session_id(user_id, message_thread_id)
        use_draft_streaming = STREAM_MODE == 'draft' and message_thread_id is not None

        await _handle_message_impl(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming)

    except Exception as e:
        logger.exception(f"Error handling document: {e}")
        await update.message.reply_text(f"Error processing file: {str(e)[:200]}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos from user"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_thread_id = getattr(update.message, 'message_thread_id', None)

    # Get the largest photo
    photo = update.message.photo[-1]  # Last one is largest
    caption = update.message.caption or ""

    logger.info(f"User {user_id} sent photo: {photo.file_id} ({photo.width}x{photo.height})")

    # Download file to temp directory
    import tempfile
    temp_dir = Path(tempfile.gettempdir()) / "tg_gateway_files"
    temp_dir.mkdir(exist_ok=True)

    temp_file = temp_dir / f"{user_id}_{photo.file_unique_id}.jpg"

    try:
        # Download file
        tg_file = await photo.get_file()
        await tg_file.download_to_drive(temp_file)
        logger.info(f"Downloaded photo to {temp_file}")

        # Build prompt with file reference
        if caption:
            message = f"[Image attached: {temp_file}]\n\nUser message: {caption}"
        else:
            message = f"[Image attached: {temp_file}]\n\nAnalyze or describe this image."

        # Get session and process like regular message (check main session)
        is_main = is_main_topic(message_thread_id)
        if is_main:
            session_id = get_main_session_id()
        else:
            session_id = get_session_id(user_id, message_thread_id)
        use_draft_streaming = STREAM_MODE == 'draft' and message_thread_id is not None

        await _handle_message_impl(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming)

    except Exception as e:
        logger.exception(f"Error handling photo: {e}")
        await update.message.reply_text(f"Error processing photo: {str(e)[:200]}")


async def transcribe_voice_with_premium(voice_file_path: Path, bot_message_id: int, chat_id: int) -> str | None:
    """
    Transcribe voice message using Telegram Premium transcription.

    Strategy: Forward voice to Saved Messages, call transcribeAudio API.
    Returns transcribed text or None on failure.
    """
    global telethon_client

    if telethon_client is None:
        logger.error("Telethon client not initialized")
        return None

    try:
        # Use 'me' keyword for Saved Messages (avoids get_me() which can fail on new TL layer)
        # Send the voice file to Saved Messages
        sent_msg = await telethon_client.send_file(
            'me',  # 'me' = Saved Messages
            voice_file_path,
            voice=True
        )

        logger.info(f"Sent voice to Saved Messages: msg_id={sent_msg.id}")

        # Call transcribeAudio API
        result = await telethon_client(functions.messages.TranscribeAudioRequest(
            peer='me',
            msg_id=sent_msg.id
        ))

        # Check if transcription is pending (async on Telegram's side)
        if result.pending:
            # Wait for transcription to complete (poll a few times)
            for _ in range(10):
                await asyncio.sleep(1)
                result = await telethon_client(functions.messages.TranscribeAudioRequest(
                    peer='me',
                    msg_id=sent_msg.id
                ))
                if not result.pending:
                    break

        transcribed_text = result.text
        if transcribed_text:
            logger.info(f"Transcription result: {transcribed_text[:100]}...")
        else:
            logger.warning("Transcription returned empty/None text")

        # Clean up: delete message from Saved Messages
        await telethon_client.delete_messages('me', [sent_msg.id])

        return transcribed_text

    except Exception as e:
        logger.exception(f"Transcription error: {e}")
        return None


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming voice messages - transcribe using TG Premium and send to Claude"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_thread_id = getattr(update.message, 'message_thread_id', None)

    voice = update.message.voice
    caption = update.message.caption or ""
    duration = voice.duration

    logger.info(f"User {user_id} sent voice: {voice.file_id} ({duration}s)")

    # Send "transcribing" status
    status_msg = await update.message.reply_text(
        "🎤 Транскрибирую голосовое...",
        message_thread_id=message_thread_id
    )

    # Download voice file
    import tempfile
    temp_dir = Path(tempfile.gettempdir()) / "tg_gateway_files"
    temp_dir.mkdir(exist_ok=True)
    temp_file = temp_dir / f"{user_id}_{voice.file_unique_id}.ogg"

    try:
        tg_file = await voice.get_file()
        await tg_file.download_to_drive(temp_file)
        logger.info(f"Downloaded voice to {temp_file}")

        # Transcribe using TG Premium
        transcribed_text = await transcribe_voice_with_premium(
            temp_file,
            update.message.message_id,
            chat_id
        )

        if transcribed_text:
            # Update status message with transcription
            await status_msg.edit_text(f"🎤 <i>{transcribed_text}</i>", parse_mode='HTML')

            # Build message for Claude
            if caption:
                message = f"[Voice message transcribed]: {transcribed_text}\n\nUser comment: {caption}"
            else:
                message = f"[Voice message transcribed]: {transcribed_text}"

            # Process like regular message (check main session)
            is_main = is_main_topic(message_thread_id)
            if is_main:
                session_id = get_main_session_id()
            else:
                session_id = get_session_id(user_id, message_thread_id)
            use_draft_streaming = STREAM_MODE == 'draft' and message_thread_id is not None

            await _handle_message_impl(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming)
        else:
            await status_msg.edit_text("❌ Не удалось транскрибировать. Требуется Telegram Premium.")

        # Clean up temp file
        if temp_file.exists():
            temp_file.unlink()

    except Exception as e:
        logger.exception(f"Error handling voice: {e}")
        await update.message.reply_text(f"Error processing voice: {str(e)[:200]}")


async def _handle_tasks_topic(update, context, user_id, message, chat_id, message_thread_id):
    """Handle messages in Tasks topic - spawn background Claude session.

    When the owner sends or forwards a message to the Tasks topic,
    we spawn a background Claude session to handle it and report results
    back to the same topic.
    """
    # Build task prompt from message + forwarded context
    task_prompt = message or ""

    # Extract forwarded message context
    msg = update.message
    forward_info = ""
    if msg.forward_origin:
        origin = msg.forward_origin
        origin_type = getattr(origin, 'type', '')
        if hasattr(origin, 'sender_user') and origin.sender_user:
            sender = origin.sender_user
            forward_info = f"[Forwarded from {sender.first_name or ''} {sender.last_name or ''}".strip() + "]"
        elif hasattr(origin, 'chat') and origin.chat:
            forward_info = f"[Forwarded from chat: {origin.chat.title or origin.chat.id}]"
        elif hasattr(origin, 'sender_user_name') and origin.sender_user_name:
            forward_info = f"[Forwarded from {origin.sender_user_name}]"

    if forward_info:
        task_prompt = f"{forward_info}\n{task_prompt}"

    if not task_prompt.strip():
        await update.message.reply_text(
            "Пустое сообщение. Напиши или форвардни задачу.",
            message_thread_id=message_thread_id
        )
        return

    # Determine model from config
    tasks_config = config.get('tasks', {})
    model = tasks_config.get('model', 'sonnet')
    timeout = tasks_config.get('timeout', 1800)

    # Short label from first 40 chars
    label = task_prompt[:40].replace('\n', ' ').strip()
    if len(task_prompt) > 40:
        label += "..."

    logger.info(f"Tasks topic: spawning background session for: {label}")

    try:
        result = await spawn_agent(
            task=task_prompt,
            label=label,
            model=model,
            timeout_seconds=timeout,
            origin_topic=message_thread_id,
            announce_mode="direct"
        )

        if result["status"] == "spawned":
            await update.message.reply_text(
                f"Взяла в работу. Результат напишу сюда.\n"
                f"Model: {result.get('model', model)} | Timeout: {timeout // 60} min",
                message_thread_id=message_thread_id
            )
        else:
            reason = result.get('reason', result.get('error', 'Unknown'))
            await update.message.reply_text(
                f"Не смогла запустить: {reason}",
                message_thread_id=message_thread_id
            )

    except Exception as e:
        logger.exception(f"Tasks topic spawn error: {e}")
        await update.message.reply_text(
            f"Ошибка: {str(e)[:200]}",
            message_thread_id=message_thread_id
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages with optional draft streaming"""
    if not await check_user(update):
        return

    user_id = update.effective_user.id
    message = update.message.text
    chat_id = update.effective_chat.id

    # Check for threaded mode (message_thread_id present in private chat)
    message_thread_id = getattr(update.message, 'message_thread_id', None)

    # Tasks topic - spawn background session instead of interactive
    tasks_topic_id = config.get('tasks', {}).get('topic_id')
    if message_thread_id == tasks_topic_id:
        await _handle_tasks_topic(update, context, user_id, message, chat_id, message_thread_id)
        return

    # Check for reply context
    reply_to = update.message.reply_to_message
    if reply_to and reply_to.text:
        # Add reply context to the message
        reply_text = reply_to.text[:500]  # Limit to 500 chars
        if len(reply_to.text) > 500:
            reply_text += "..."
        # Format: show what user is replying to
        reply_from = "Claude" if reply_to.from_user and reply_to.from_user.is_bot else "User"
        message = f"[Replying to {reply_from}'s message: \"{reply_text}\"]\n\n{message}"

    # Check if this is the main session topic (persistent orchestrator)
    is_main = is_main_topic(message_thread_id)

    # Get session for this user+topic combination
    if is_main:
        # Main session uses persistent session ID (never resets per-user)
        session_id = get_main_session_id()
        session_key = "main_session"
    else:
        session_id = get_session_id(user_id, message_thread_id)
        session_key = get_session_key(user_id, message_thread_id)

    # Enable draft streaming if threaded mode is available
    use_draft_streaming = STREAM_MODE == 'draft' and message_thread_id is not None

    logger.info(f"User {user_id} ({session_key}{'[MAIN]' if is_main else ''}, session={session_id[:8] if session_id else 'new'}): {message[:100]}...")

    try:
        await _handle_message_impl(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming)
    except Exception as e:
        logger.exception(f"Error handling message from user {user_id}: {e}")
        try:
            await update.message.reply_text(f"Error: {str(e)[:200]}")
        except Exception:
            pass


async def _handle_message_impl(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming):
    """Internal implementation of message handling with interactive permissions"""

    # Acquire per-topic lock to prevent race conditions
    topic_key = f"{chat_id}_{message_thread_id or 'main'}"
    topic_lock = get_topic_lock(topic_key)

    async with topic_lock:
        await _handle_message_impl_locked(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming)


async def _handle_message_impl_locked(update, context, user_id, message, session_id, chat_id, message_thread_id, use_draft_streaming):
    """Actual implementation - called with topic lock held"""

    # Fast mode: if message starts with '!' use haiku model for quick responses
    use_model = None
    if message.startswith('!'):
        use_model = 'haiku'
        message = message[1:].lstrip()  # Remove '!' and leading whitespace

    # Log user message (topic-aware)
    append_to_log(user_id, {
        "role": "user",
        "content": message
    }, message_thread_id)

    # Track execution state
    import random
    current_tools = []  # Track multiple tools if running in parallel
    active_tasks = {}   # Track tasks: {task_id: {subject, status, activeForm}}
    active_agents = {}  # Track background agents: {agent_id: {description, subagent_type, start_time}}
    spinner_frame = [0]  # Mutable for closure

    # Draft streaming state
    text_buffer = [""]  # Accumulated text for draft
    draft_id = hash(f'{chat_id}_{message_thread_id}_{time.time()}') % (2**31 - 1)  # Unique draft ID per topic
    last_draft_update = [0.0]  # Last time we sent draft update

    # Status message reference for updates
    status_msg_holder = [None]

    # Spinner animation frames (used for tool display in both modes)
    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # Tool name to emoji mapping
    tool_emojis = {
        "Read": "📂",
        "Write": "✏️",
        "Edit": "✏️",
        "Bash": "⚙️",
        "Glob": "🔍",
        "Grep": "🔍",
        "WebFetch": "🌐",
        "WebSearch": "🔎",
        "Task": "🤖",  # Agent spawning
        "Skill": "🎯",
        "AskUserQuestion": "❓",
        "EnterPlanMode": "📝",
        "ExitPlanMode": "✅",
        "TaskCreate": "📝",
        "TaskUpdate": "✏️",
        "TaskGet": "📋",
        "TaskList": "📋",
        "NotebookEdit": "📓",
        "TaskOutput": "📤",
        "TaskStop": "🛑",
    }

    # Helper to format tool details
    def format_tool_details(tool_name, tool_input):
        """Extract key parameter from tool input for display."""
        if not tool_input:
            return tool_name

        # Extract relevant parameter for each tool
        if tool_name == "Read":
            path = tool_input.get("file_path", "")
            # Show relative path from home
            if path.startswith(_HOME_PREFIX):
                path = "~/" + path[len(_HOME_PREFIX):]
            return f"<b>Read</b> <code>{path}</code>"

        elif tool_name in ["Write", "Edit"]:
            path = tool_input.get("file_path", "")
            if path.startswith(_HOME_PREFIX):
                path = "~/" + path[len(_HOME_PREFIX):]
            action = "Writing" if tool_name == "Write" else "Editing"
            return f"<b>{action}</b> <code>{path}</code>"

        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")

            # Special handling for MCP calls
            if cmd.startswith("mcp-cli call "):
                # Extract server/tool from mcp-cli call
                parts = cmd.replace("mcp-cli call ", "").split(" ", 1)
                if parts:
                    mcp_tool = parts[0]
                    return f"<b>🔌 MCP</b> <code>{mcp_tool}</code>"
            elif cmd.startswith("mcp-cli info "):
                parts = cmd.replace("mcp-cli info ", "").split(" ", 1)
                if parts:
                    mcp_tool = parts[0]
                    return f"<b>🔌 MCP info</b> <code>{mcp_tool}</code>"

            # Common commands with better display
            if cmd.startswith("git "):
                return f"<b>Git</b> <code>{cmd[4:50]}</code>"
            elif cmd.startswith("python") or cmd.startswith("python3"):
                script = cmd.split(" ", 1)[1] if " " in cmd else ""
                script_short = script[:40] + "..." if len(script) > 40 else script
                return f"<b>🐍 Python</b> <code>{script_short}</code>"

            # Show first 50 chars of command
            cmd_short = cmd[:50] + "..." if len(cmd) > 50 else cmd
            return f"<b>Bash</b> <code>{cmd_short}</code>"

        elif tool_name == "WebSearch":
            query = tool_input.get("query", "")
            query_short = query[:60] + "..." if len(query) > 60 else query
            return f"<b>Search</b> \"{query_short}\""

        elif tool_name == "WebFetch":
            url = tool_input.get("url", "")
            # Show domain only
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc if url else url
                return f"<b>Fetch</b> <code>{domain}</code>"
            except Exception:
                return f"<b>Fetch</b> <code>{url[:50]}</code>"

        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            pattern_short = pattern[:40] + "..." if len(pattern) > 40 else pattern
            if path:
                if path.startswith(_HOME_PREFIX):
                    path = "~/" + path[len(_HOME_PREFIX):]
                return f"<b>Grep</b> <code>{pattern_short}</code> in <code>{path}</code>"
            return f"<b>Grep</b> <code>{pattern_short}</code>"

        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            if path:
                if path.startswith(_HOME_PREFIX):
                    path = "~/" + path[len(_HOME_PREFIX):]
                return f"<b>Glob</b> <code>{pattern}</code> in <code>{path}</code>"
            return f"<b>Glob</b> <code>{pattern}</code>"

        elif tool_name == "Task":
            # Agent/task spawning - show agent type and description
            subagent = tool_input.get("subagent_type", "")
            desc = tool_input.get("description", "")

            # Agent type emoji mapping
            agent_emojis = {
                "Bash": "⚙️",
                "Explore": "🔍",
                "Plan": "📋",
                "general-purpose": "🤖",
                "claude-code-guide": "📚",
            }

            agent_emoji = agent_emojis.get(subagent, "🔧")

            if subagent and desc:
                desc_short = desc[:50] + "..." if len(desc) > 50 else desc
                return f"<b>Agent</b> {agent_emoji} {subagent}\n    ↳ {desc_short}"
            elif subagent:
                return f"<b>Agent</b> {agent_emoji} {subagent}"
            return "<b>Task</b>"

        elif tool_name == "Skill":
            skill = tool_input.get("skill", "")
            return f"<b>Skill</b> <code>/{skill}</code>" if skill else "<b>Skill</b>"

        elif tool_name == "AskUserQuestion":
            # Permission request or question
            questions = tool_input.get("questions", [])
            if questions:
                first_q = questions[0].get("question", "")
                q_short = first_q[:60] + "..." if len(first_q) > 60 else first_q
                return f"<b>Question</b> {q_short}"
            return "<b>Asking question</b>"

        elif tool_name == "EnterPlanMode":
            return "<b>Entering plan mode</b> 📝"

        elif tool_name == "ExitPlanMode":
            return "<b>Plan ready for review</b> ✅"

        elif tool_name == "TaskCreate":
            subject = tool_input.get("subject", "")
            if subject:
                return f"<b>📝 New task:</b> {subject[:50]}"
            return "<b>📝 Creating task</b>"

        elif tool_name == "TaskUpdate":
            status = tool_input.get("status", "")
            task_id = tool_input.get("taskId", "")
            if status == "completed":
                return f"<b>✅ Task #{task_id} done</b>"
            elif status == "in_progress":
                return f"<b>▶️ Starting task #{task_id}</b>"
            return f"<b>📝 Updating task #{task_id}</b>"

        elif tool_name == "TaskGet":
            task_id = tool_input.get("taskId", "")
            return f"<b>📋 Getting task #{task_id}</b>"

        elif tool_name == "TaskList":
            return "<b>📋 Listing tasks</b>"

        elif tool_name == "NotebookEdit":
            path = tool_input.get("notebook_path", "")
            if path.startswith(_HOME_PREFIX):
                path = "~/" + path[len(_HOME_PREFIX):]
            return f"<b>📓 Notebook</b> <code>{path}</code>"

        # MCP tools (mcp-cli)
        elif tool_name == "mcp":
            # Try to parse MCP command
            return "<b>🔌 MCP call</b>"

        # Default: just return tool name
        return f"<b>{tool_name}</b>"

    # Progress callback for tool tracking
    def on_tool_use(tool_name, tool_input):
        tool_info = {"name": tool_name, "input": tool_input, "time": time.time()}
        current_tools.append(tool_info)
        if len(current_tools) > 3:
            current_tools.pop(0)

        # Track tasks
        if tool_name == "TaskCreate":
            # Will be assigned ID by Claude, track by subject for now
            subject = tool_input.get("subject", "")
            active_form = tool_input.get("activeForm", subject)
            if subject:
                # Use hash of subject as temp ID
                temp_id = str(hash(subject) % 1000)
                active_tasks[temp_id] = {
                    "subject": subject,
                    "status": "pending",
                    "activeForm": active_form,
                    "time": time.time()
                }

        elif tool_name == "TaskUpdate":
            task_id = tool_input.get("taskId", "")
            status = tool_input.get("status", "")
            if task_id and status:
                if status == "completed" or status == "deleted":
                    # Remove from active
                    active_tasks.pop(task_id, None)
                elif task_id in active_tasks:
                    active_tasks[task_id]["status"] = status

        # Track background agents
        elif tool_name == "Task":
            if tool_input.get("run_in_background"):
                desc = tool_input.get("description", "Agent")
                subagent = tool_input.get("subagent_type", "")
                agent_id = f"agent_{int(time.time())}"
                active_agents[agent_id] = {
                    "description": desc,
                    "subagent_type": subagent,
                    "start_time": time.time()
                }
                # Keep max 5 agents tracked
                if len(active_agents) > 5:
                    oldest = min(active_agents.keys(), key=lambda k: active_agents[k]["start_time"])
                    del active_agents[oldest]

    # Text callback for draft streaming
    def on_text_delta(delta: str):
        text_buffer[0] += delta

    # Permission callback for interactive approval via TG buttons
    async def on_permission_request(request_id: str, tool_name: str, description: str) -> bool:
        """Send permission request as inline buttons and wait for user response."""
        logger.info(f"Permission request {request_id}: {tool_name} - {description[:100]}")

        # Create inline keyboard with Allow/Deny buttons
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Allow", callback_data=f"perm_allow_{request_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"perm_deny_{request_id}"),
            ],
            [
                InlineKeyboardButton("✅ Always Allow", callback_data=f"perm_always_{request_id}"),
            ]
        ])

        # Format permission message
        desc_short = description[:500] + "..." if len(description) > 500 else description
        perm_text = (
            f"🔐 **Permission Request**\n\n"
            f"**Tool:** `{tool_name}`\n"
            f"**Action:** {desc_short}\n\n"
            f"Allow this action?"
        )

        # Create event for waiting
        event = asyncio.Event()
        PENDING_PERMISSIONS[request_id] = {"event": event, "response": None, "tool": tool_name}

        # Send permission request message
        try:
            perm_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=perm_text,
                parse_mode='HTML',
                reply_markup=keyboard,
                message_thread_id=message_thread_id
            )
            PENDING_PERMISSIONS[request_id]["message"] = perm_msg
        except Exception as e:
            logger.error(f"Failed to send permission request: {e}")
            del PENDING_PERMISSIONS[request_id]
            return False  # Deny on error

        # Wait for user response with timeout (60 seconds)
        try:
            await asyncio.wait_for(event.wait(), timeout=60.0)
            response = PENDING_PERMISSIONS[request_id].get("response", False)
            logger.info(f"Permission {request_id} response: {response}")
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Permission {request_id} timed out - denying")
            # Edit message to show timeout
            try:
                await perm_msg.edit_text(
                    f"🔐 **Permission Request** (⏰ timed out)\n\n"
                    f"**Tool:** `{tool_name}`\n"
                    f"Action was denied due to timeout.",
                    parse_mode='HTML'
                )
            except Exception:
                pass
            return False
        finally:
            # Cleanup
            if request_id in PENDING_PERMISSIONS:
                del PENDING_PERMISSIONS[request_id]

    # Determine which callbacks to use
    text_cb = on_text_delta if use_draft_streaming else None

    # Start time tracking
    start_time = time.time()

    # Generate unique request ID for cancellation
    request_id = f"{chat_id}_{message_thread_id or 'main'}_{int(time.time())}"
    cancel_event = asyncio.Event()
    ACTIVE_REQUESTS[request_id] = {"cancel_event": cancel_event, "cancelled": False}

    # Cancel button
    cancel_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{request_id}")]
    ])

    # Send initial status message with cancel button
    status_msg = await update.message.reply_text(
        "🔄 Начинаю работу...",
        message_thread_id=message_thread_id,
        reply_markup=cancel_keyboard
    )
    status_msg_holder[0] = status_msg

    # UI update state
    last_message = [""]
    update_counter = [0]
    text_started = [False]
    ui_running = [True]

    # State for hybrid streaming
    converted_to_message = [False]  # True once we convert draft to real message

    # Background task for UI updates - HYBRID APPROACH
    # Draft for text streaming, convert to message on tool, then edit
    async def update_ui():
        while ui_running[0]:
            await asyncio.sleep(2.0)  # 2 seconds between updates (reduced from 1.5 to avoid flood)

            if not ui_running[0]:
                break

            now = time.time()
            elapsed = int(now - start_time)
            spinner = SPINNER[spinner_frame[0] % len(SPINNER)]
            spinner_frame[0] += 1

            current_text = text_buffer[0]
            has_active_tool = bool(current_tools) and (now - current_tools[-1]["time"]) < 30

            # Build display text
            display_text = current_text[:3800] if current_text else ""
            if len(current_text) > 3800:
                display_text += "..."

            # Add tool status at bottom if tool is running
            if has_active_tool:
                latest_tool = current_tools[-1]
                tool_name = latest_tool["name"]
                tool_emoji = tool_emojis.get(tool_name, "🔧")
                tool_display = format_tool_details(tool_name, latest_tool.get("input", {}))
                tool_status = f"\n\n{spinner} {tool_emoji} <i>{tool_display}</i>"
                display_text += tool_status

            # CASE 1: No text yet, no tool - show thinking spinner
            if not current_text and not has_active_tool:
                if status_msg_holder[0]:
                    status_text = f"{spinner} <b>Thinking...</b>\n⏱️ {elapsed}s"
                    if status_text != last_message[0]:
                        try:
                            await status_msg_holder[0].edit_text(status_text, parse_mode='HTML', reply_markup=cancel_keyboard)
                            last_message[0] = status_text
                        except Exception as e:
                            logger.debug(f"Status update error: {e}")

            # CASE 2: No text yet, but tool running - show tool in status message
            elif not current_text and has_active_tool:
                if status_msg_holder[0]:
                    status_parts = []

                    # Show active tasks (in_progress only)
                    in_progress_tasks = [t for t in active_tasks.values() if t.get("status") == "in_progress"]
                    if in_progress_tasks:
                        task_lines = []
                        for t in in_progress_tasks[:3]:  # Max 3 tasks
                            active_form = t.get("activeForm", t.get("subject", "Task"))
                            task_lines.append(f"▶️ <i>{active_form}</i>")
                        status_parts.append("📋 <b>Tasks:</b>\n" + "\n".join(task_lines))

                    # Show active background agents
                    if active_agents:
                        agent_lines = []
                        for aid, a in list(active_agents.items())[-3:]:  # Max 3 agents
                            desc = a.get("description", "Agent")
                            subagent = a.get("subagent_type", "")
                            age = int(now - a.get("start_time", now))
                            agent_lines.append(f"🤖 <i>{desc}</i> ({age}s)")
                        status_parts.append("🤖 <b>Agents:</b>\n" + "\n".join(agent_lines))

                    # Show tools
                    recent_tools = current_tools[-3:]
                    tool_lines = []
                    for t in recent_tools:
                        t_name = t["name"]
                        t_input = t.get("input", {})
                        emoji = tool_emojis.get(t_name, "🔧")
                        tool_disp = format_tool_details(t_name, t_input)
                        age = now - t["time"]
                        if age < 2:
                            tool_lines.append(f"{emoji} {spinner} <i>{tool_disp}</i>")
                        else:
                            tool_lines.append(f"{emoji} ✅ <i>{tool_disp}</i>")
                    status_parts.append("\n".join(tool_lines))

                    status_text = "\n\n".join(status_parts) + f"\n\n⏱️ {elapsed}s"

                    if status_text != last_message[0]:
                        try:
                            await status_msg_holder[0].edit_text(status_text, parse_mode='HTML', reply_markup=cancel_keyboard)
                            last_message[0] = status_text
                        except Exception as e:
                            logger.debug(f"Status update error: {e}")

            # CASE 3: Have text - use draft or edit depending on state
            elif current_text:
                if not converted_to_message[0]:
                    # Still in draft mode
                    if not text_started[0]:
                        text_started[0] = True
                        # Delete status message when starting draft
                        try:
                            if status_msg_holder[0]:
                                await status_msg_holder[0].delete()
                                status_msg_holder[0] = None
                        except Exception:
                            pass
                        logger.info(f"Starting draft mode for user {user_id}")

                    # If tool is running, convert draft to real message
                    if has_active_tool:
                        # Send current text as real message with cancel button
                        try:
                            msg = await update.message.reply_text(
                                display_text,
                                message_thread_id=message_thread_id,
                                parse_mode='HTML',
                                reply_markup=cancel_keyboard
                            )
                            status_msg_holder[0] = msg
                            converted_to_message[0] = True
                            last_message[0] = display_text
                            logger.info(f"Converted draft to message for user {user_id}")
                        except Exception as e:
                            err_str = str(e).lower()
                            if 'flood' in err_str or 'retry' in err_str:
                                logger.warning(f"Flood control hit during convert, stopping UI")
                                ui_running[0] = False
                                return
                            logger.error(f"Failed to convert draft to message: {e}")
                    else:
                        # No tool - keep using draft
                        if (now - last_draft_update[0]) >= (DRAFT_THROTTLE_MS / 1000):
                            try:
                                await context.bot.send_message_draft(
                                    chat_id=chat_id,
                                    draft_id=draft_id,
                                    text=display_text,
                                    message_thread_id=message_thread_id,
                                    parse_mode='HTML'
                                )
                                last_draft_update[0] = now
                            except Exception as e:
                                logger.debug(f"Draft update error: {e}")

                else:
                    # Already converted to message - use edit with cancel button
                    if status_msg_holder[0] and display_text != last_message[0]:
                        try:
                            await status_msg_holder[0].edit_text(
                                display_text,
                                parse_mode='HTML',
                                reply_markup=cancel_keyboard
                            )
                            last_message[0] = display_text
                        except Exception as e:
                            err_str = str(e).lower()
                            if 'flood' in err_str or 'retry' in err_str:
                                # Flood control - stop updating UI entirely
                                logger.warning(f"Flood control hit, stopping UI updates")
                                ui_running[0] = False
                                return
                            elif 'not modified' not in err_str:
                                logger.debug(f"Edit error: {e}")

    # Start UI update task
    ui_task = asyncio.create_task(update_ui())

    # Run Claude with threading (sync version is more reliable)
    import threading
    done_event = threading.Event()
    response_container = {}

    def run_claude_bg():
        response = run_claude(message, session_id, tool_callback=on_tool_use, text_callback=text_cb, request_id=request_id, model=use_model)
        response_container['response'] = response
        done_event.set()

    executor_task = asyncio.get_event_loop().run_in_executor(None, run_claude_bg)

    # Wait for completion or cancellation
    while not done_event.is_set():
        await asyncio.sleep(0.5)
        # Check if cancelled
        if ACTIVE_REQUESTS.get(request_id, {}).get("cancelled"):
            logger.info(f"Request {request_id} was cancelled, stopping UI")
            break

    # Check if cancelled
    was_cancelled = ACTIVE_REQUESTS.get(request_id, {}).get("cancelled", False)

    if was_cancelled:
        # Try to cancel the executor task (won't kill running process but stops waiting)
        executor_task.cancel()
        try:
            await executor_task
        except asyncio.CancelledError:
            pass
        response = {'result': '❌ Отменено пользователем', 'session_id': session_id}
    else:
        await executor_task
        response = response_container.get('response', {})

    # Stop UI updates
    ui_running[0] = False
    ui_task.cancel()
    try:
        await ui_task
    except asyncio.CancelledError:
        pass

    # Cleanup active request
    if request_id in ACTIVE_REQUESTS:
        del ACTIVE_REQUESTS[request_id]

    # If cancelled, just return early
    if was_cancelled:
        return

    # Calculate final duration
    duration = int(time.time() - start_time)

    # Handle expired session - delete old session file
    # Note: main session never expires (persistent orchestrator)
    is_main = is_main_topic(message_thread_id)
    if response.get('session_expired') and not is_main:
        session_file = get_session_id_file(user_id, message_thread_id)
        if session_file.exists():
            session_file.unlink()
            logger.info(f"Deleted expired session file for user {user_id}")

    # Save session ID if we got a new one (topic-aware or main session)
    if response.get('session_id'):
        if is_main:
            save_main_session_id(response['session_id'])
            logger.info(f"Saved main session ID: {response['session_id'][:8]}...")
        else:
            save_session_id(user_id, response['session_id'], message_thread_id)
        register_session(
            session_id=response['session_id'],
            session_type="user",
            source="telegram",
            topic_id=message_thread_id,
        )

    # Log assistant response (topic-aware)
    append_to_log(user_id, {
        "role": "assistant",
        "content": response.get('result', ''),
        "cost": response.get('cost'),
        "duration": response.get('duration')
    }, message_thread_id)

    # Format response with metadata
    text = format_response_with_meta(response)

    # Check for spawn_agent requests (main session only)
    if is_main and config.get('subagents', {}).get('enabled', False):
        spawn_request = parse_spawn_request(text)
        if spawn_request:
            logger.info(f"Detected spawn_agent request: {spawn_request.get('label', 'Task')}")
            try:
                # Execute spawn
                spawn_result = await spawn_agent(
                    task=spawn_request.get('task', ''),
                    label=spawn_request.get('label', 'Task'),
                    model=spawn_request.get('model'),
                    timeout_seconds=spawn_request.get('timeout_seconds'),
                    tools=spawn_request.get('tools'),
                    origin_topic=message_thread_id
                )
                # Remove spawn_agent tag from text and add result notification
                import re
                text = re.sub(r'<spawn_agent>.*?</spawn_agent>', '', text, flags=re.DOTALL)
                text = text.strip() + "\n\n" + format_spawn_result(spawn_result)
            except Exception as e:
                logger.exception(f"Failed to spawn agent: {e}")
                text = text + f"\n\n❌ **Ошибка spawn_agent**: {str(e)[:200]}"

    # Parse file attachments from response
    text, files_to_send = parse_file_attachments(text)

    # Parse inline buttons (A2UI) from response
    text, keyboard = parse_inline_buttons(text)

    # Send files if any
    if files_to_send:
        await send_files_to_user(context, chat_id, files_to_send, message_thread_id)

    # Convert to HTML for reliable Telegram parsing
    text_html = markdown_to_markdownv2(text)
    chunks = smart_chunk_text(text_html, max_length=4096)

    async def send_chunk(chunk_text, reply_markup=None):
        """Send chunk with HTML, fallback to plain text."""
        try:
            return await update.message.reply_text(
                chunk_text,
                parse_mode='HTML',
                message_thread_id=message_thread_id,
                reply_markup=reply_markup
            )
        except Exception as e:
            if 'parse' in str(e).lower() or 'entities' in str(e).lower():
                logger.warning(f"HTML parse error, sending plain: {e}")
                return await update.message.reply_text(
                    chunk_text,
                    message_thread_id=message_thread_id,
                    reply_markup=reply_markup
                )
            raise

    if use_draft_streaming:
        # Hybrid mode - check if we converted to message
        if converted_to_message[0] and status_msg_holder[0]:
            # Already have a message - edit it with final content
            if len(chunks) == 1:
                try:
                    await status_msg_holder[0].edit_text(chunks[0], parse_mode='HTML', reply_markup=keyboard)
                except Exception as e:
                    logger.warning(f"Final edit failed: {e}")
                    await send_chunk(chunks[0], keyboard)
            else:
                # Multiple chunks - edit first, send rest
                try:
                    await status_msg_holder[0].edit_text(chunks[0], parse_mode='HTML')
                except Exception:
                    await send_chunk(chunks[0])
                for i, chunk in enumerate(chunks[1:], 1):
                    reply_markup = keyboard if (i == len(chunks) - 1 and keyboard) else None
                    await send_chunk(chunk, reply_markup)
                    await asyncio.sleep(0.5)
        else:
            # Still in draft mode - send as new message
            for i, chunk in enumerate(chunks):
                reply_markup = keyboard if (i == len(chunks) - 1 and keyboard) else None
                await send_chunk(chunk, reply_markup)
                if len(chunks) > 1:
                    await asyncio.sleep(0.5)
    else:
        # Spinner mode - edit status message or send chunks
        status_msg = status_msg_holder[0]
        if len(chunks) == 1 and status_msg:
            try:
                await status_msg.edit_text(chunks[0], parse_mode='HTML', reply_markup=keyboard)
            except Exception as e:
                if 'parse' in str(e).lower() or 'entities' in str(e).lower():
                    logger.warning(f"HTML parse error in edit, trying plain: {e}")
                    try:
                        await status_msg.edit_text(chunks[0], reply_markup=keyboard)
                    except Exception:
                        await send_chunk(chunks[0], keyboard)
                else:
                    logger.warning(f"Failed to edit message: {e}")
                    await send_chunk(chunks[0], keyboard)
        else:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            for i, chunk in enumerate(chunks):
                reply_markup = keyboard if (i == len(chunks) - 1 and keyboard) else None
                await send_chunk(chunk, reply_markup)
                await asyncio.sleep(0.5)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks (A2UI callbacks and permission responses)"""
    logger.info(f"🔘 Callback query received: {update.callback_query}")
    query = update.callback_query
    await query.answer()  # Acknowledge the click

    user_id = update.effective_user.id
    logger.info(f"👤 User ID: {user_id}, Allowed: {user_id in ALLOWED_USERS}")
    if user_id not in ALLOWED_USERS:
        logger.warning(f"❌ User {user_id} not in allowed list")
        return

    callback_data = query.data
    logger.info(f"✅ User {user_id} clicked button: {callback_data}")

    # Handle cancel callbacks
    if callback_data.startswith("cancel_"):
        request_id = callback_data[7:]  # Remove "cancel_" prefix
        if request_id in ACTIVE_REQUESTS:
            ACTIVE_REQUESTS[request_id]["cancelled"] = True
            ACTIVE_REQUESTS[request_id]["cancel_event"].set()
            # Kill process if PID is available
            pid = ACTIVE_REQUESTS[request_id].get("pid")
            if pid:
                try:
                    import os
                    import signal
                    os.kill(pid, signal.SIGTERM)
                    logger.info(f"Killed process {pid} for request {request_id}")
                except ProcessLookupError:
                    pass  # Process already finished
                except Exception as e:
                    logger.warning(f"Failed to kill process {pid}: {e}")
            logger.info(f"User {user_id} cancelled request {request_id}")
            try:
                await query.edit_message_text("❌ Отменено", parse_mode='HTML')
            except Exception as e:
                logger.warning(f"Failed to edit cancel message: {e}")
        else:
            try:
                await query.edit_message_text("⏰ Запрос уже завершён", parse_mode='HTML')
            except Exception:
                pass
        return

    # Handle permission callbacks
    if callback_data.startswith("perm_"):
        parts = callback_data.split("_", 2)  # perm_allow_REQUESTID or perm_deny_REQUESTID
        if len(parts) >= 3:
            action = parts[1]  # allow, deny, or always
            request_id = parts[2]

            if request_id in PENDING_PERMISSIONS:
                perm_data = PENDING_PERMISSIONS[request_id]
                tool_name = perm_data.get("tool", "Unknown")

                if action == "allow":
                    perm_data["response"] = True
                    # Edit message to show allowed
                    try:
                        await query.edit_message_text(
                            f"✅ **Allowed:** `{tool_name}`",
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass

                elif action == "deny":
                    perm_data["response"] = False
                    # Edit message to show denied
                    try:
                        await query.edit_message_text(
                            f"❌ **Denied:** `{tool_name}`",
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass

                elif action == "always":
                    perm_data["response"] = True
                    # TODO: Add to settings.json permissions.allow list
                    # For now just allow this instance
                    try:
                        await query.edit_message_text(
                            f"✅ **Always Allowed:** `{tool_name}`\n"
                            f"(Note: Permanent allow not yet implemented)",
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass

                # Signal the waiting coroutine
                perm_data["event"].set()
                return
            else:
                # Permission request expired
                try:
                    await query.edit_message_text(
                        f"⏰ Permission request expired",
                        parse_mode='HTML'
                    )
                except Exception:
                    pass
                return

    # Get thread_id first (needed for session lookup)
    thread_id = query.message.message_thread_id if hasattr(query.message, 'message_thread_id') else None
    logger.info(f"📝 Topic: message_thread_id={thread_id}")

    # Check for main session
    is_main = is_main_topic(thread_id)
    if is_main:
        session_id = get_main_session_id()
    else:
        session_id = get_session_id(user_id, thread_id)

    # Update the message to show what was selected
    try:
        await query.edit_message_reply_markup(reply_markup=None)  # Remove buttons
        await query.message.reply_text(f"➡️ Selected: `{callback_data}`", parse_mode='HTML',
                                       message_thread_id=thread_id)
    except Exception as e:
        logger.warning(f"Failed to edit callback message: {e}")

    # Create prompt from callback data
    prompt = f"[Button clicked: {callback_data}]"
    chat_id = update.effective_chat.id
    use_draft = STREAM_MODE == 'draft' and thread_id is not None

    # Create minimal fake update for reply_text
    class FakeMessage:
        def __init__(self, original_msg):
            self._original = original_msg
            self.chat = original_msg.chat

        async def reply_text(self, text, **kwargs):
            # Remove message_thread_id from kwargs if present (we set it ourselves)
            kwargs.pop('message_thread_id', None)
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=thread_id,
                **kwargs
            )

    fake_update = type('obj', (object,), {
        'effective_user': update.effective_user,
        'effective_chat': update.effective_chat,
        'message': FakeMessage(query.message)
    })()

    # Call message handler with callback as prompt
    await _handle_message_impl(
        fake_update, context, user_id, prompt,
        session_id, chat_id, thread_id, use_draft
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")


async def init_telethon_client():
    """Initialize Telethon client for voice transcription"""
    global telethon_client
    try:
        telethon_client = TelegramClient(
            StringSession(TELETHON_SESSION_STRING),
            TELETHON_API_ID,
            TELETHON_API_HASH
        )
        await telethon_client.connect()
        if not await telethon_client.is_user_authorized():
            logger.error("Telethon client not authorized!")
            telethon_client = None
        else:
            me = await telethon_client.get_me()
            logger.info(f"Telethon client initialized: {me.first_name} (@{me.username})")
    except Exception as e:
        logger.exception(f"Failed to initialize Telethon: {e}")
        telethon_client = None


async def post_init(application: Application):
    """Set bot commands after initialization"""
    # Initialize Telethon for voice transcription
    await init_telethon_client()

    # Base commands
    commands = [
        BotCommand("new", "Start new session"),
        BotCommand("status", "System status"),
        BotCommand("skills", "List available skills"),
        BotCommand("id", "Show session ID"),
        BotCommand("start", "Show help"),
    ]

    # Add some popular skills (Telegram limits to 100 commands)
    popular_skills = ['healthcheck', 'vox-deals-report', 'memory', 'signal', 'dayflow']
    skills = get_available_skills()
    for skill in popular_skills:
        if skill in skills:
            # Convert to valid command name (lowercase, no special chars)
            cmd_name = skill.replace('-', '_')
            commands.append(BotCommand(cmd_name, f"Run /{skill}"))

    await application.bot.set_my_commands(commands)
    logger.info(f"Bot commands registered ({len(commands)} total)")


def main():
    """Start the bot"""
    logger.info("Starting Клавдия (Telegram Gateway)...")

    # Create application
    # Enable concurrent updates so different topics can run in parallel
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_session))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("skills", list_skills))
    app.add_handler(CommandHandler("id", show_session_id))

    # Callback queries (A2UI button clicks)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Handle skill commands (any /<skill-name>)
    app.add_handler(MessageHandler(filters.COMMAND, handle_skill_command))

    # Handle regular messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Handle documents (files)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Handle photos
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Handle voice messages (transcribed via TG Premium)
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Error handler
    app.add_error_handler(error_handler)

    # Start background reaper to kill orphaned Claude SDK subprocesses
    # TG bot sessions are short-lived tasks, 30min max lifetime is generous
    start_reaper_thread(max_age_seconds=1800)

    # Start polling
    logger.info("Bot started, polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
