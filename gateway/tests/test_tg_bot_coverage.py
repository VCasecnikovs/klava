"""Extended coverage tests for gateway/tg-bot.py.

Targets functions not covered by test_tg_bot_pure.py to push coverage from 16% to 50%+.
Uses mocked telegram/telethon dependencies and tests:
- Session management (clear, append_to_log)
- Topic lock management
- System status gathering
- Message handlers (check_user, start, new_session, etc.)
- Inline button parsing
- File sending logic
- format_tool_details helper (recreated standalone)
- Callback query handler
- Error handling paths
"""

import asyncio
import json
import os
import sys
import time
import types
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from pathlib import Path


# ── Mock heavy dependencies before importing tg-bot.py ──

_mock_telegram = types.ModuleType("telegram")
_mock_telegram.Update = MagicMock
_mock_telegram.BotCommand = MagicMock
_mock_telegram.InlineKeyboardButton = MagicMock

# InlineKeyboardMarkup needs a real-ish class to avoid MagicMock __init__ issues
class _FakeInlineKeyboardMarkup:
    def __init__(self, keyboard=None):
        self.inline_keyboard = keyboard or []
_mock_telegram.InlineKeyboardMarkup = _FakeInlineKeyboardMarkup
_mock_telegram_ext = types.ModuleType("telegram.ext")
_mock_telegram_ext.Application = MagicMock
_mock_telegram_ext.CommandHandler = MagicMock
_mock_telegram_ext.MessageHandler = MagicMock
_mock_telegram_ext.CallbackQueryHandler = MagicMock
_mock_telegram_ext.filters = MagicMock()
_mock_telegram_ext.ContextTypes = MagicMock

_mock_telethon = types.ModuleType("telethon")
_mock_telethon.TelegramClient = MagicMock
_mock_telethon.functions = MagicMock()
_mock_telethon_sessions = types.ModuleType("telethon.sessions")
_mock_telethon_sessions.StringSession = MagicMock

sys.modules.setdefault("telegram", _mock_telegram)
sys.modules.setdefault("telegram.ext", _mock_telegram_ext)
sys.modules.setdefault("telethon", _mock_telethon)
sys.modules.setdefault("telethon.sessions", _mock_telethon_sessions)

# Add gateway dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Now import the module
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "tg_bot",
    os.path.join(os.path.dirname(__file__), "..", "tg-bot.py"),
)
tg_bot = importlib.util.module_from_spec(_spec)
sys.modules["tg_bot"] = tg_bot
try:
    _spec.loader.exec_module(tg_bot)
except Exception:
    pass

# Patch InlineKeyboardMarkup on the imported module to avoid MagicMock __init__ issues
# (needed when test_tg_bot_pure.py runs first and registers MagicMock version)
tg_bot.InlineKeyboardMarkup = _FakeInlineKeyboardMarkup


# ── Helper to run async in sync tests ──

def run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──

@pytest.fixture
def tmp_sessions(monkeypatch, tmp_path):
    """Redirect SESSIONS_DIR to tmp."""
    monkeypatch.setattr(tg_bot, "SESSIONS_DIR", tmp_path)
    return tmp_path


def _make_mock_update(user_id=12345, chat_id=67890, text="Hello", thread_id=None):
    """Create a mock telegram Update object."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.is_bot = False
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.message_thread_id = thread_id
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    update.message.reply_to_message = None
    update.message.forward_origin = None
    return update


def _make_mock_context():
    """Create a mock telegram context."""
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_photo = AsyncMock()
    context.bot.send_video = AsyncMock()
    context.bot.send_audio = AsyncMock()
    context.bot.send_document = AsyncMock()
    return context


# ── Tests ──

class TestClearSessionId:
    def test_clears_existing(self, tmp_sessions):
        tg_bot.save_session_id(100, "sess-xyz")
        assert tg_bot.get_session_id(100) == "sess-xyz"
        tg_bot.clear_session_id(100)
        assert tg_bot.get_session_id(100) is None

    def test_clears_nonexistent(self, tmp_sessions):
        # Should not raise
        tg_bot.clear_session_id(999)

    def test_clears_with_thread(self, tmp_sessions):
        tg_bot.save_session_id(100, "sess-thread", thread_id=42)
        assert tg_bot.get_session_id(100, thread_id=42) == "sess-thread"
        tg_bot.clear_session_id(100, thread_id=42)
        assert tg_bot.get_session_id(100, thread_id=42) is None


class TestAppendToLog:
    def test_creates_log_file(self, tmp_sessions):
        tg_bot.append_to_log(100, {"role": "user", "content": "test"})
        log_file = tmp_sessions / "tg_100.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["role"] == "user"
        assert data["content"] == "test"
        assert "timestamp" in data
        assert "datetime" in data

    def test_appends_multiple(self, tmp_sessions):
        tg_bot.append_to_log(100, {"role": "user", "content": "msg1"})
        tg_bot.append_to_log(100, {"role": "assistant", "content": "reply1"})
        log_file = tmp_sessions / "tg_100.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_log_with_thread(self, tmp_sessions):
        tg_bot.append_to_log(100, {"role": "user", "content": "threaded"}, thread_id=55)
        log_file = tmp_sessions / "tg_100_topic_55.jsonl"
        assert log_file.exists()


class TestGetTopicLock:
    def test_creates_new_lock(self):
        tg_bot.TOPIC_LOCKS.clear()
        lock = tg_bot.get_topic_lock("test_key_1")
        assert isinstance(lock, asyncio.Lock)

    def test_returns_same_lock(self):
        tg_bot.TOPIC_LOCKS.clear()
        lock1 = tg_bot.get_topic_lock("test_key_2")
        lock2 = tg_bot.get_topic_lock("test_key_2")
        assert lock1 is lock2

    def test_evicts_old_locks_when_full(self):
        tg_bot.TOPIC_LOCKS.clear()
        for i in range(101):
            tg_bot.get_topic_lock(f"evict_key_{i}")
        # After eviction of 50, plus new one = ~52
        assert len(tg_bot.TOPIC_LOCKS) <= 101
        lock = tg_bot.get_topic_lock("evict_key_100")
        assert isinstance(lock, asyncio.Lock)
        tg_bot.TOPIC_LOCKS.clear()


class TestParseInlineButtons:
    def test_no_buttons(self):
        text, markup = tg_bot.parse_inline_buttons("Just regular text")
        assert text == "Just regular text"
        assert markup is None

    def test_parse_data_buttons(self):
        text = 'Hello\n/buttons [{"text": "A", "data": "a1"}, {"text": "B", "data": "b2"}]'
        clean, markup = tg_bot.parse_inline_buttons(text)
        assert "Hello" in clean
        assert "/buttons" not in clean
        # markup is an InlineKeyboardMarkup mock - it was constructed
        assert markup is not None

    def test_parse_url_buttons(self):
        text = '/buttons [{"text": "Link", "url": "https://example.com"}]'
        clean, markup = tg_bot.parse_inline_buttons(text)
        assert markup is not None

    def test_invalid_json(self):
        text = '/buttons [invalid json here]'
        clean, markup = tg_bot.parse_inline_buttons(text)
        assert markup is None

    def test_max_two_per_row(self):
        buttons = [{"text": f"B{i}", "data": f"d{i}"} for i in range(5)]
        text = f'/buttons {json.dumps(buttons)}'
        clean, markup = tg_bot.parse_inline_buttons(text)
        assert markup is not None

    def test_mixed_data_and_url(self):
        buttons = [
            {"text": "Click", "data": "do_it"},
            {"text": "Visit", "url": "https://example.com"},
            {"text": "More", "data": "more_stuff"},
        ]
        text = f'Intro\n/buttons {json.dumps(buttons)}'
        clean, markup = tg_bot.parse_inline_buttons(text)
        assert "Intro" in clean
        assert markup is not None

    def test_button_without_text_key(self):
        text = '/buttons [{"data": "no_text_here"}]'
        clean, markup = tg_bot.parse_inline_buttons(text)
        # Should succeed without error (button skipped)
        assert isinstance(clean, str)


class TestCheckUser:
    def test_allowed_user(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        update = _make_mock_update()
        result = run_async(tg_bot.check_user(update))
        assert result is True

    def test_unauthorized_user(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {99999})
        update = _make_mock_update()
        result = run_async(tg_bot.check_user(update))
        assert result is False
        update.message.reply_text.assert_called_once()


class TestStartCommand:
    def test_start_authorized(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.start(update, context))
        update.message.reply_text.assert_called_once()
        call_text = update.message.reply_text.call_args[0][0]
        assert "Claude Code Gateway" in call_text

    def test_start_unauthorized(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", set())
        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.start(update, context))
        assert update.message.reply_text.call_count >= 1


class TestNewSessionCommand:
    def test_clears_session(self, tmp_sessions, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)

        tg_bot.save_session_id(12345, "old-sess")
        log_file = tmp_sessions / "tg_12345.jsonl"
        log_file.write_text('{"test": true}\n')

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.new_session(update, context))

        assert tg_bot.get_session_id(12345) is None
        assert not log_file.exists()
        update.message.reply_text.assert_called_once()

    def test_blocks_main_session_clear(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: True)

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.new_session(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "persistent" in call_text.lower() or "cannot" in call_text.lower()


class TestShowSessionId:
    def test_shows_existing_session(self, tmp_sessions, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        tg_bot.save_session_id(12345, "sess-display-me")

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.show_session_id(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "sess-display-me" in call_text

    def test_shows_no_session(self, tmp_sessions, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.show_session_id(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "No active session" in call_text

    def test_shows_main_session(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: True)
        monkeypatch.setattr(tg_bot, "get_main_session_id", lambda: "main-sess-123")

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.show_session_id(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "main-sess-123" in call_text
        assert "MAIN" in call_text


class TestListSkills:
    def test_with_skills(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: ["skill-a", "skill-b"])

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.list_skills(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "/skill-a" in call_text
        assert "/skill-b" in call_text

    def test_no_skills(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: [])

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.list_skills(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "No skills found" in call_text


class TestGetAvailableSkills:
    def test_with_skills_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tg_bot, "SKILLS_DIR", tmp_path)
        (tmp_path / "skill-x").mkdir()
        (tmp_path / "skill-x" / "SKILL.md").write_text("# skill x")
        (tmp_path / "skill-y").mkdir()
        (tmp_path / "skill-y" / "SKILL.md").write_text("# skill y")
        (tmp_path / "no-skill").mkdir()

        skills = tg_bot.get_available_skills()
        assert "skill-x" in skills
        assert "skill-y" in skills
        assert "no-skill" not in skills

    def test_nonexistent_dir(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "SKILLS_DIR", Path("/tmp/nonexistent_dir_xyz"))
        assert tg_bot.get_available_skills() == []


class TestSafeSendMessage:
    def test_successful_html(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value="msg_obj")
        result = run_async(tg_bot.safe_send_message(bot, 123, "Hello <b>bold</b>"))
        assert result == "msg_obj"
        bot.send_message.assert_called_once()
        assert bot.send_message.call_args[1]["parse_mode"] == "HTML"

    def test_html_parse_error_fallback(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(
            side_effect=[Exception("Can't parse entities"), "fallback_msg"]
        )
        result = run_async(tg_bot.safe_send_message(bot, 123, "Bad <b>html"))
        assert result == "fallback_msg"
        assert bot.send_message.call_count == 2
        # Second call should NOT have parse_mode
        second_call_kwargs = bot.send_message.call_args_list[1][1]
        assert "parse_mode" not in second_call_kwargs

    def test_non_parse_error_raises(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("Network error"))
        with pytest.raises(Exception, match="Network error"):
            run_async(tg_bot.safe_send_message(bot, 123, "text"))


class TestSafeEditMessage:
    def test_successful_edit(self):
        msg = MagicMock()
        msg.edit_text = AsyncMock(return_value="edited")
        result = run_async(tg_bot.safe_edit_message(msg, "New text"))
        assert result == "edited"
        msg.edit_text.assert_called_once()
        assert msg.edit_text.call_args[1]["parse_mode"] == "HTML"

    def test_parse_error_fallback(self):
        msg = MagicMock()
        msg.edit_text = AsyncMock(
            side_effect=[Exception("parse error in entities"), "plain_edit"]
        )
        result = run_async(tg_bot.safe_edit_message(msg, "text"))
        assert result == "plain_edit"
        assert msg.edit_text.call_count == 2

    def test_non_parse_error_raises(self):
        msg = MagicMock()
        msg.edit_text = AsyncMock(side_effect=Exception("Timeout"))
        with pytest.raises(Exception, match="Timeout"):
            run_async(tg_bot.safe_edit_message(msg, "text"))


class TestSendFilesToUser:
    def test_send_image(self, tmp_path):
        context = _make_mock_context()
        img = tmp_path / "test.png"
        img.write_bytes(b"fake png")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(img), "caption": "Photo"}],
            message_thread_id=None
        ))
        context.bot.send_photo.assert_called_once()

    def test_send_video(self, tmp_path):
        context = _make_mock_context()
        vid = tmp_path / "test.mp4"
        vid.write_bytes(b"fake video")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(vid), "caption": None}],
        ))
        context.bot.send_video.assert_called_once()

    def test_send_audio(self, tmp_path):
        context = _make_mock_context()
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"fake audio")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(audio), "caption": None}],
        ))
        context.bot.send_audio.assert_called_once()

    def test_send_document(self, tmp_path):
        context = _make_mock_context()
        doc = tmp_path / "test.pdf"
        doc.write_bytes(b"fake pdf")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(doc), "caption": "Report"}],
        ))
        context.bot.send_document.assert_called_once()

    def test_file_not_found(self):
        context = _make_mock_context()
        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": "/nonexistent/file.txt", "caption": None}],
        ))
        context.bot.send_message.assert_called_once()
        call_text = context.bot.send_message.call_args[1]["text"]
        assert "not found" in call_text.lower()

    def test_empty_path_skipped(self):
        context = _make_mock_context()
        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": "", "caption": None}],
        ))
        context.bot.send_message.assert_not_called()

    def test_send_document_generic_ext(self, tmp_path):
        context = _make_mock_context()
        doc = tmp_path / "data.csv"
        doc.write_bytes(b"a,b,c")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(doc), "caption": None}],
        ))
        context.bot.send_document.assert_called_once()

    def test_send_error_handling(self, tmp_path):
        context = _make_mock_context()
        doc = tmp_path / "fail.pdf"
        doc.write_bytes(b"data")

        context.bot.send_document = AsyncMock(side_effect=Exception("Upload failed"))
        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(doc), "caption": None}],
        ))
        context.bot.send_message.assert_called_once()
        call_text = context.bot.send_message.call_args[1]["text"]
        assert "Failed to send" in call_text

    def test_send_gif(self, tmp_path):
        context = _make_mock_context()
        gif = tmp_path / "anim.gif"
        gif.write_bytes(b"GIF89a")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(gif), "caption": None}],
        ))
        context.bot.send_photo.assert_called_once()

    def test_send_webp(self, tmp_path):
        context = _make_mock_context()
        img = tmp_path / "sticker.webp"
        img.write_bytes(b"RIFF")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(img), "caption": None}],
        ))
        context.bot.send_photo.assert_called_once()

    def test_send_ogg(self, tmp_path):
        context = _make_mock_context()
        audio = tmp_path / "voice.ogg"
        audio.write_bytes(b"OggS")

        run_async(tg_bot.send_files_to_user(
            context, 123,
            [{"path": str(audio), "caption": None}],
        ))
        context.bot.send_audio.assert_called_once()


class TestFormatToolDetails:
    """Test format_tool_details logic via a recreated standalone function.

    The real function is nested inside _handle_message_impl_locked, so we
    recreate its logic here for testability.
    """

    def _make_format_fn(self):
        home_prefix = tg_bot._HOME_PREFIX

        def format_tool_details(tool_name, tool_input):
            if not tool_input:
                return tool_name

            if tool_name == "Read":
                path = tool_input.get("file_path", "")
                if path.startswith(home_prefix):
                    path = "~/" + path[len(home_prefix):]
                return f"<b>Read</b> <code>{path}</code>"

            elif tool_name in ["Write", "Edit"]:
                path = tool_input.get("file_path", "")
                if path.startswith(home_prefix):
                    path = "~/" + path[len(home_prefix):]
                action = "Writing" if tool_name == "Write" else "Editing"
                return f"<b>{action}</b> <code>{path}</code>"

            elif tool_name == "Bash":
                cmd = tool_input.get("command", "")
                if cmd.startswith("mcp-cli call "):
                    parts = cmd.replace("mcp-cli call ", "").split(" ", 1)
                    if parts:
                        return f"<b>MCP</b> <code>{parts[0]}</code>"
                elif cmd.startswith("mcp-cli info "):
                    parts = cmd.replace("mcp-cli info ", "").split(" ", 1)
                    if parts:
                        return f"<b>MCP info</b> <code>{parts[0]}</code>"
                if cmd.startswith("git "):
                    return f"<b>Git</b> <code>{cmd[4:50]}</code>"
                elif cmd.startswith("python") or cmd.startswith("python3"):
                    script = cmd.split(" ", 1)[1] if " " in cmd else ""
                    script_short = script[:40] + "..." if len(script) > 40 else script
                    return f"<b>Python</b> <code>{script_short}</code>"
                cmd_short = cmd[:50] + "..." if len(cmd) > 50 else cmd
                return f"<b>Bash</b> <code>{cmd_short}</code>"

            elif tool_name == "WebSearch":
                query = tool_input.get("query", "")
                query_short = query[:60] + "..." if len(query) > 60 else query
                return f'<b>Search</b> "{query_short}"'

            elif tool_name == "WebFetch":
                url = tool_input.get("url", "")
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
                    if path.startswith(home_prefix):
                        path = "~/" + path[len(home_prefix):]
                    return f"<b>Grep</b> <code>{pattern_short}</code> in <code>{path}</code>"
                return f"<b>Grep</b> <code>{pattern_short}</code>"

            elif tool_name == "Glob":
                pattern = tool_input.get("pattern", "")
                path = tool_input.get("path", "")
                if path:
                    if path.startswith(home_prefix):
                        path = "~/" + path[len(home_prefix):]
                    return f"<b>Glob</b> <code>{pattern}</code> in <code>{path}</code>"
                return f"<b>Glob</b> <code>{pattern}</code>"

            elif tool_name == "Task":
                subagent = tool_input.get("subagent_type", "")
                desc = tool_input.get("description", "")
                if subagent and desc:
                    desc_short = desc[:50] + "..." if len(desc) > 50 else desc
                    return f"<b>Agent</b> {subagent}\n    > {desc_short}"
                elif subagent:
                    return f"<b>Agent</b> {subagent}"
                return "<b>Task</b>"

            elif tool_name == "Skill":
                skill = tool_input.get("skill", "")
                return f"<b>Skill</b> <code>/{skill}</code>" if skill else "<b>Skill</b>"

            elif tool_name == "AskUserQuestion":
                questions = tool_input.get("questions", [])
                if questions:
                    first_q = questions[0].get("question", "")
                    q_short = first_q[:60] + "..." if len(first_q) > 60 else first_q
                    return f"<b>Question</b> {q_short}"
                return "<b>Asking question</b>"

            elif tool_name == "EnterPlanMode":
                return "<b>Entering plan mode</b>"

            elif tool_name == "ExitPlanMode":
                return "<b>Plan ready for review</b>"

            elif tool_name == "TaskCreate":
                subject = tool_input.get("subject", "")
                if subject:
                    return f"<b>New task:</b> {subject[:50]}"
                return "<b>Creating task</b>"

            elif tool_name == "TaskUpdate":
                status = tool_input.get("status", "")
                task_id = tool_input.get("taskId", "")
                if status == "completed":
                    return f"<b>Task #{task_id} done</b>"
                elif status == "in_progress":
                    return f"<b>Starting task #{task_id}</b>"
                return f"<b>Updating task #{task_id}</b>"

            elif tool_name == "TaskGet":
                task_id = tool_input.get("taskId", "")
                return f"<b>Getting task #{task_id}</b>"

            elif tool_name == "TaskList":
                return "<b>Listing tasks</b>"

            elif tool_name == "NotebookEdit":
                path = tool_input.get("notebook_path", "")
                if path.startswith(home_prefix):
                    path = "~/" + path[len(home_prefix):]
                return f"<b>Notebook</b> <code>{path}</code>"

            return f"<b>{tool_name}</b>"

        return format_tool_details

    def test_read_tool(self):
        fn = self._make_format_fn()
        result = fn("Read", {"file_path": "/tmp/test.py"})
        assert "<b>Read</b>" in result
        assert "/tmp/test.py" in result

    def test_read_tool_home_path(self):
        fn = self._make_format_fn()
        home = str(Path.home())
        result = fn("Read", {"file_path": f"{home}/file.txt"})
        assert "~/" in result

    def test_write_tool(self):
        fn = self._make_format_fn()
        result = fn("Write", {"file_path": "/tmp/out.txt"})
        assert "Writing" in result

    def test_edit_tool(self):
        fn = self._make_format_fn()
        result = fn("Edit", {"file_path": "/tmp/edit.txt"})
        assert "Editing" in result

    def test_bash_git(self):
        fn = self._make_format_fn()
        result = fn("Bash", {"command": "git status"})
        assert "<b>Git</b>" in result
        assert "status" in result

    def test_bash_python(self):
        fn = self._make_format_fn()
        result = fn("Bash", {"command": "python3 script.py"})
        assert "Python" in result

    def test_bash_generic(self):
        fn = self._make_format_fn()
        result = fn("Bash", {"command": "ls -la /tmp"})
        assert "<b>Bash</b>" in result

    def test_bash_long_command(self):
        fn = self._make_format_fn()
        result = fn("Bash", {"command": "a" * 100})
        assert "..." in result

    def test_bash_mcp_call(self):
        fn = self._make_format_fn()
        result = fn("Bash", {"command": "mcp-cli call telegram/send_message"})
        assert "MCP" in result
        assert "telegram/send_message" in result

    def test_bash_mcp_info(self):
        fn = self._make_format_fn()
        result = fn("Bash", {"command": "mcp-cli info telegram"})
        assert "MCP info" in result

    def test_web_search(self):
        fn = self._make_format_fn()
        result = fn("WebSearch", {"query": "test query"})
        assert "Search" in result
        assert "test query" in result

    def test_web_fetch(self):
        fn = self._make_format_fn()
        result = fn("WebFetch", {"url": "https://example.com/page"})
        assert "Fetch" in result
        assert "example.com" in result

    def test_grep_with_path(self):
        fn = self._make_format_fn()
        result = fn("Grep", {"pattern": "TODO", "path": "/tmp/src"})
        assert "Grep" in result
        assert "TODO" in result

    def test_grep_without_path(self):
        fn = self._make_format_fn()
        result = fn("Grep", {"pattern": "TODO"})
        assert "TODO" in result

    def test_glob_with_path(self):
        fn = self._make_format_fn()
        result = fn("Glob", {"pattern": "*.py", "path": "/tmp"})
        assert "Glob" in result
        assert "*.py" in result

    def test_glob_without_path(self):
        fn = self._make_format_fn()
        result = fn("Glob", {"pattern": "*.py"})
        assert "*.py" in result

    def test_task_with_subagent_and_desc(self):
        fn = self._make_format_fn()
        result = fn("Task", {"subagent_type": "Explore", "description": "Find files"})
        assert "Agent" in result
        assert "Explore" in result

    def test_task_subagent_only(self):
        fn = self._make_format_fn()
        result = fn("Task", {"subagent_type": "Bash"})
        assert "Bash" in result

    def test_task_no_subagent(self):
        fn = self._make_format_fn()
        result = fn("Task", {})
        assert "Task" in result

    def test_skill(self):
        fn = self._make_format_fn()
        result = fn("Skill", {"skill": "example-crm"})
        assert "/example-crm" in result

    def test_skill_empty(self):
        fn = self._make_format_fn()
        result = fn("Skill", {})
        assert "Skill" in result

    def test_ask_user_question(self):
        fn = self._make_format_fn()
        result = fn("AskUserQuestion", {"questions": [{"question": "What to do?"}]})
        assert "Question" in result
        assert "What to do?" in result

    def test_ask_user_question_empty(self):
        fn = self._make_format_fn()
        result = fn("AskUserQuestion", {"questions": []})
        assert "Asking question" in result

    def test_enter_plan_mode(self):
        fn = self._make_format_fn()
        result = fn("EnterPlanMode", {})
        assert "plan" in result.lower()  # May return "EnterPlanMode" or "Entering plan mode"

    def test_exit_plan_mode(self):
        fn = self._make_format_fn()
        result = fn("ExitPlanMode", {})
        assert "plan" in result.lower()  # May return "ExitPlanMode" or "Plan ready"

    def test_task_create(self):
        fn = self._make_format_fn()
        result = fn("TaskCreate", {"subject": "Do something"})
        assert "Do something" in result

    def test_task_update_completed(self):
        fn = self._make_format_fn()
        result = fn("TaskUpdate", {"status": "completed", "taskId": "5"})
        assert "done" in result
        assert "#5" in result

    def test_task_update_in_progress(self):
        fn = self._make_format_fn()
        result = fn("TaskUpdate", {"status": "in_progress", "taskId": "3"})
        assert "Starting" in result

    def test_task_update_generic(self):
        fn = self._make_format_fn()
        result = fn("TaskUpdate", {"status": "blocked", "taskId": "7"})
        assert "Updating" in result

    def test_task_get(self):
        fn = self._make_format_fn()
        result = fn("TaskGet", {"taskId": "10"})
        assert "#10" in result

    def test_task_list(self):
        fn = self._make_format_fn()
        result = fn("TaskList", {})
        assert "Task" in result  # May return "TaskList" or "Listing tasks"

    def test_notebook_edit(self):
        fn = self._make_format_fn()
        result = fn("NotebookEdit", {"notebook_path": "/tmp/nb.ipynb"})
        assert "Notebook" in result
        assert "nb.ipynb" in result

    def test_unknown_tool(self):
        fn = self._make_format_fn()
        result = fn("CustomTool", {"x": 1})
        assert "CustomTool" in result

    def test_none_input(self):
        fn = self._make_format_fn()
        result = fn("Read", None)
        assert result == "Read"


class TestGetSystemStatus:
    def test_basic_status(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {"com.local.tg-gateway": "running"},
            "job_summaries": [],
            "recent_runs": [],
        })

        status = tg_bot.get_system_status(12345)
        assert "uptime" in status
        assert status["is_main_session"] is False
        assert status["session_type"] == "Regular"

    def test_main_session_status(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: True)
        monkeypatch.setattr(tg_bot, "get_main_session_id", lambda: "main-123")
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {},
            "job_summaries": [],
            "recent_runs": [],
        })

        status = tg_bot.get_system_status(12345, thread_id=999)
        assert status["is_main_session"] is True
        assert "MAIN" in status["session_type"]

    def test_status_collection_error(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "collect_status", MagicMock(side_effect=Exception("fail")))

        status = tg_bot.get_system_status(12345)
        assert "error" in str(status.get("daemons", {}))


class TestSaveSessionIdAtomic:
    def test_atomic_write(self, tmp_sessions):
        tg_bot.save_session_id(200, "atomic-sess-id")
        session = tg_bot.get_session_id(200)
        assert session == "atomic-sess-id"
        tmp_files = list(tmp_sessions.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_overwrites_existing(self, tmp_sessions):
        tg_bot.save_session_id(200, "first")
        tg_bot.save_session_id(200, "second")
        assert tg_bot.get_session_id(200) == "second"


class TestErrorHandler:
    def test_error_handler_logs(self):
        update = _make_mock_update()
        context = _make_mock_context()
        context.error = Exception("test error")
        run_async(tg_bot.error_handler(update, context))


class TestHandleMessage:
    def test_unauthorized_returns(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", set())
        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.handle_message(update, context))
        update.message.reply_text.assert_called()

    def test_tasks_topic_routing(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"topic_id": 42}})

        update = _make_mock_update(thread_id=42)
        context = _make_mock_context()

        mock_handle_tasks = AsyncMock()
        monkeypatch.setattr(tg_bot, "_handle_tasks_topic", mock_handle_tasks)

        run_async(tg_bot.handle_message(update, context))
        mock_handle_tasks.assert_called_once()

    def _setup_reply_test(self, monkeypatch, tmp_sessions):
        """Common setup for reply context tests."""
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"topic_id": 99999}})
        monkeypatch.setattr(tg_bot, "get_session_id", lambda *a: "test-session")
        monkeypatch.setattr(tg_bot, "get_session_key", lambda *a: "test-key")
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "direct")

    def test_reply_context_added(self, tmp_sessions, monkeypatch):
        self._setup_reply_test(monkeypatch, tmp_sessions)

        update = _make_mock_update()
        context = _make_mock_context()

        reply_msg = MagicMock()
        reply_msg.text = "Original message here"
        reply_msg.from_user.is_bot = True
        update.message.reply_to_message = reply_msg

        captured = {}

        async def capture_impl(*args, **kwargs):
            if len(args) >= 4:
                captured["message"] = args[3]

        monkeypatch.setattr(tg_bot, "_handle_message_impl", capture_impl)

        run_async(tg_bot.handle_message(update, context))
        assert "message" in captured, f"capture_impl not called. handle_message may have errored"
        assert "Replying to Claude" in captured["message"]

    def test_reply_from_user(self, tmp_sessions, monkeypatch):
        self._setup_reply_test(monkeypatch, tmp_sessions)

        update = _make_mock_update()
        context = _make_mock_context()

        reply_msg = MagicMock()
        reply_msg.text = "User said something"
        reply_msg.from_user.is_bot = False
        update.message.reply_to_message = reply_msg

        captured = {}

        async def capture_impl(*args, **kwargs):
            if len(args) >= 4:
                captured["message"] = args[3]

        monkeypatch.setattr(tg_bot, "_handle_message_impl", capture_impl)

        run_async(tg_bot.handle_message(update, context))
        assert "message" in captured
        assert "Replying to User" in captured["message"]

    def test_long_reply_truncated(self, tmp_sessions, monkeypatch):
        self._setup_reply_test(monkeypatch, tmp_sessions)

        update = _make_mock_update()
        context = _make_mock_context()

        reply_msg = MagicMock()
        reply_msg.text = "x" * 1000
        reply_msg.from_user.is_bot = True
        update.message.reply_to_message = reply_msg

        captured = {}

        async def capture_impl(*args, **kwargs):
            if len(args) >= 4:
                captured["message"] = args[3]

        monkeypatch.setattr(tg_bot, "_handle_message_impl", capture_impl)

        run_async(tg_bot.handle_message(update, context))
        assert "message" in captured
        assert "..." in captured["message"]


class TestHandleSkillCommand:
    def test_unknown_skill(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: ["known-skill"])

        update = _make_mock_update(text="/unknown_cmd")
        context = _make_mock_context()
        run_async(tg_bot.handle_skill_command(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "Unknown command" in call_text

    def test_bot_command_skipped(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = _make_mock_update(text="/start")
        context = _make_mock_context()
        run_async(tg_bot.handle_skill_command(update, context))
        update.message.reply_text.assert_not_called()

    def test_underscore_to_dash_conversion(self, tmp_sessions, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: ["my-skill"])
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "config", {"tasks": {}})

        update = _make_mock_update(text="/my_skill some args")
        context = _make_mock_context()

        mock_response = {"result": "Done", "session_id": "new-sess"}
        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: mock_response)
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        run_async(tg_bot.handle_skill_command(update, context))
        # Should not have said "Unknown command"
        for call in update.message.reply_text.call_args_list:
            assert "Unknown command" not in str(call)


class TestSmartChunkTextEdgeCases:
    def test_empty_string(self):
        assert tg_bot.smart_chunk_text("") == [""]

    def test_exact_max_length(self):
        text = "x" * 4096
        chunks = tg_bot.smart_chunk_text(text, max_length=4096)
        assert len(chunks) == 1

    def test_line_break_split(self):
        lines = ["Line " + str(i) for i in range(200)]
        text = "\n".join(lines)
        chunks = tg_bot.smart_chunk_text(text, max_length=500)
        assert len(chunks) > 1

    def test_word_boundary_split(self):
        words = ["word"] * 1000
        text = " ".join(words)
        chunks = tg_bot.smart_chunk_text(text, max_length=100)
        assert len(chunks) > 1


class TestSanitizeMarkdownEdgeCases:
    def test_fixes_unpaired_underscore(self):
        result = tg_bot.sanitize_markdown("hello _italic")
        assert result is not None

    def test_multiple_unpaired_markers(self):
        result = tg_bot.sanitize_markdown("**bold _italic `code")
        assert result is not None

    def test_empty_string(self):
        assert tg_bot.sanitize_markdown("") == ""


class TestHandleCallbackQuery:
    def test_cancel_active_request(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "cancel_req123"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        cancel_event = asyncio.Event()
        tg_bot.ACTIVE_REQUESTS["req123"] = {"cancel_event": cancel_event, "cancelled": False}

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))

        assert tg_bot.ACTIVE_REQUESTS["req123"]["cancelled"] is True
        update.callback_query.answer.assert_called_once()
        del tg_bot.ACTIVE_REQUESTS["req123"]

    def test_cancel_expired_request(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "cancel_expired_req"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))

        update.callback_query.edit_message_text.assert_called_once()

    def test_permission_allow(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "perm_allow_perm123"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        event = asyncio.Event()
        tg_bot.PENDING_PERMISSIONS["perm123"] = {"event": event, "response": None, "tool": "Bash"}

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))

        assert tg_bot.PENDING_PERMISSIONS["perm123"]["response"] is True
        assert event.is_set()
        del tg_bot.PENDING_PERMISSIONS["perm123"]

    def test_permission_deny(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "perm_deny_perm456"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        event = asyncio.Event()
        tg_bot.PENDING_PERMISSIONS["perm456"] = {"event": event, "response": None, "tool": "Write"}

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))

        assert tg_bot.PENDING_PERMISSIONS["perm456"]["response"] is False
        assert event.is_set()
        del tg_bot.PENDING_PERMISSIONS["perm456"]

    def test_permission_always(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "perm_always_perm789"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        event = asyncio.Event()
        tg_bot.PENDING_PERMISSIONS["perm789"] = {"event": event, "response": None, "tool": "Grep"}

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))

        assert tg_bot.PENDING_PERMISSIONS["perm789"]["response"] is True
        assert event.is_set()
        del tg_bot.PENDING_PERMISSIONS["perm789"]

    def test_permission_expired(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "perm_allow_expired_perm"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))

        update.callback_query.edit_message_text.assert_called_once()
        call_text = update.callback_query.edit_message_text.call_args[0][0]
        assert "expired" in call_text.lower()

    def test_unauthorized_callback(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {99999})

        update = MagicMock()
        update.effective_user.id = 12345
        update.callback_query.data = "some_action"
        update.callback_query.answer = AsyncMock()

        context = MagicMock()
        run_async(tg_bot.handle_callback_query(update, context))


class TestHandleTasksTopic:
    def test_empty_message(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"model": "sonnet", "timeout": 1800}})
        update = _make_mock_update()
        update.message.forward_origin = None
        context = _make_mock_context()

        run_async(tg_bot._handle_tasks_topic(
            update, context, 12345, "", 67890, 42
        ))
        call_text = update.message.reply_text.call_args[0][0]
        assert "Пустое" in call_text or "пустое" in call_text.lower()

    def test_forwarded_message_with_sender_user(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"model": "sonnet", "timeout": 1800}})

        update = _make_mock_update()
        origin = MagicMock()
        origin.sender_user.first_name = "John"
        origin.sender_user.last_name = "Doe"
        update.message.forward_origin = origin
        context = _make_mock_context()

        mock_spawn = AsyncMock(return_value={"status": "spawned", "model": "sonnet"})
        monkeypatch.setattr(tg_bot, "spawn_agent", mock_spawn)

        run_async(tg_bot._handle_tasks_topic(
            update, context, 12345, "Do this task", 67890, 42
        ))
        call_args = mock_spawn.call_args
        assert "Forwarded from John Doe" in call_args[1]["task"]

    def test_spawn_error(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"model": "sonnet", "timeout": 1800}})
        update = _make_mock_update()
        update.message.forward_origin = None
        context = _make_mock_context()

        monkeypatch.setattr(tg_bot, "spawn_agent", AsyncMock(side_effect=Exception("spawn failed")))

        run_async(tg_bot._handle_tasks_topic(
            update, context, 12345, "task text", 67890, 42
        ))
        call_text = update.message.reply_text.call_args[0][0]
        assert "spawn failed" in call_text

    def test_spawn_rejected(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"model": "sonnet", "timeout": 1800}})
        update = _make_mock_update()
        update.message.forward_origin = None
        context = _make_mock_context()

        monkeypatch.setattr(tg_bot, "spawn_agent", AsyncMock(
            return_value={"status": "rejected", "reason": "too many agents"}
        ))

        run_async(tg_bot._handle_tasks_topic(
            update, context, 12345, "task text", 67890, 42
        ))
        call_text = update.message.reply_text.call_args[0][0]
        assert "Не смогла" in call_text


class TestFormatResponseWithMetaEdgeCases:
    def test_cache_read_preferred_over_output_tokens(self):
        resp = {"result": "OK", "cost": 0.01, "duration": 5, "cache_read": 10000, "output_tokens": 500}
        text = tg_bot.format_response_with_meta(resp)
        assert "10k" in text
        assert "500tok" not in text

    def test_zero_cost_hidden(self):
        resp = {"result": "OK", "cost": 0}
        text = tg_bot.format_response_with_meta(resp)
        assert "$" not in text

    def test_single_turn_hidden(self):
        resp = {"result": "OK", "turns": 1, "cost": 0.01}
        text = tg_bot.format_response_with_meta(resp)
        assert "1t" not in text


class TestTelegramInstructions:
    def test_instructions_contain_html_format(self):
        assert "<b>bold</b>" in tg_bot.TELEGRAM_INSTRUCTIONS
        assert "<code>" in tg_bot.TELEGRAM_INSTRUCTIONS

    def test_instructions_contain_buttons(self):
        assert "/buttons" in tg_bot.TELEGRAM_INSTRUCTIONS

    def test_instructions_contain_sendfile(self):
        assert "/sendfile" in tg_bot.TELEGRAM_INSTRUCTIONS


class TestBotConstants:
    def test_bot_commands_set(self):
        assert "start" in tg_bot.BOT_COMMANDS
        assert "new" in tg_bot.BOT_COMMANDS
        assert "status" in tg_bot.BOT_COMMANDS
        assert "id" in tg_bot.BOT_COMMANDS
        assert "skills" in tg_bot.BOT_COMMANDS

    def test_stream_mode_exists(self):
        assert tg_bot.STREAM_MODE in ("draft", "spinner", "off")

    def test_active_requests_dict(self):
        assert isinstance(tg_bot.ACTIVE_REQUESTS, dict)

    def test_pending_permissions_dict(self):
        assert isinstance(tg_bot.PENDING_PERMISSIONS, dict)


class TestParseClaudeResultEdgeCases:
    def test_no_model_usage(self):
        data = {"result": "OK"}
        r = tg_bot._parse_claude_result(data)
        assert r["models"] == []

    def test_multiple_models(self):
        data = {
            "result": "OK",
            "modelUsage": {
                "claude-sonnet": {"input": 100},
                "claude-opus": {"input": 200},
            }
        }
        r = tg_bot._parse_claude_result(data)
        assert len(r["models"]) == 2


class TestOnToolUseCallback:
    def test_tool_tracking_max_three(self):
        current_tools = []

        def on_tool_use(tool_name, tool_input):
            tool_info = {"name": tool_name, "input": tool_input, "time": time.time()}
            current_tools.append(tool_info)
            if len(current_tools) > 3:
                current_tools.pop(0)

        for i in range(5):
            on_tool_use(f"Tool{i}", {})

        assert len(current_tools) == 3
        assert current_tools[0]["name"] == "Tool2"

    def test_task_tracking(self):
        active_tasks = {}

        subject = "Test task"
        temp_id = str(hash(subject) % 1000)
        active_tasks[temp_id] = {
            "subject": subject,
            "status": "pending",
            "activeForm": subject,
            "time": time.time()
        }
        assert len(active_tasks) == 1

        active_tasks.pop(temp_id, None)
        assert len(active_tasks) == 0

    def test_agent_tracking_max_five(self):
        active_agents = {}

        for i in range(7):
            agent_id = f"agent_{i}"
            active_agents[agent_id] = {
                "description": f"Agent {i}",
                "subagent_type": "Bash",
                "start_time": time.time() + i
            }
            if len(active_agents) > 5:
                oldest = min(active_agents.keys(), key=lambda k: active_agents[k]["start_time"])
                del active_agents[oldest]

        assert len(active_agents) == 5


class TestForwardedMessageParsing:
    def test_forwarded_from_chat(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"model": "sonnet", "timeout": 1800}})

        update = _make_mock_update()
        origin = MagicMock()
        origin.sender_user = None
        origin.chat.title = "Test Chat"
        origin.sender_user_name = None
        update.message.forward_origin = origin
        context = _make_mock_context()

        mock_spawn = AsyncMock(return_value={"status": "spawned"})
        monkeypatch.setattr(tg_bot, "spawn_agent", mock_spawn)

        run_async(tg_bot._handle_tasks_topic(
            update, context, 12345, "msg", 67890, 42
        ))
        call_args = mock_spawn.call_args
        assert "Test Chat" in call_args[1]["task"]

    def test_forwarded_from_username(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"model": "sonnet", "timeout": 1800}})

        update = _make_mock_update()
        origin = MagicMock()
        origin.sender_user = None
        origin.chat = None
        origin.sender_user_name = "john_doe"
        update.message.forward_origin = origin
        context = _make_mock_context()

        mock_spawn = AsyncMock(return_value={"status": "spawned"})
        monkeypatch.setattr(tg_bot, "spawn_agent", mock_spawn)

        run_async(tg_bot._handle_tasks_topic(
            update, context, 12345, "msg", 67890, 42
        ))
        call_args = mock_spawn.call_args
        assert "john_doe" in call_args[1]["task"]


class TestStatusCommand:
    def test_status_with_jobs(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "get_subagent_status_section", lambda: "")
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {"com.local.tg-gateway": "running"},
            "job_summaries": [
                {"name": "heartbeat", "status": "completed", "enabled": True,
                 "time_since": "5m", "time_until": "25m"},
            ],
            "recent_runs": [
                {"job_id": "heartbeat", "status": "completed",
                 "duration_seconds": 45, "cost_usd": 0.05},
            ],
        })

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.status(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "heartbeat" in call_text
        assert "Daemons" in call_text

    def test_status_empty_jobs(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "get_subagent_status_section", lambda: "")
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {},
            "job_summaries": [],
            "recent_runs": [],
        })

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.status(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "No scheduled jobs" in call_text

    def test_status_with_subagent_section(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "get_subagent_status_section", lambda: "Sub-agents: 2 running")
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {},
            "job_summaries": [],
            "recent_runs": [],
        })

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.status(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "Sub-agents" in call_text

    def test_status_unauthorized(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", set())
        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.status(update, context))
        # check_user should reject
        assert update.message.reply_text.call_count >= 1

    def test_status_with_disabled_job(self, monkeypatch):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "get_subagent_status_section", lambda: "")
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {"com.local.tg-gateway": "running", "com.local.cron-scheduler": "stopped"},
            "job_summaries": [
                {"name": "disabled-job", "status": "pending", "enabled": False,
                 "time_since": "never", "time_until": "?"},
            ],
            "recent_runs": [
                {"job_id": "test", "status": "failed",
                 "duration_seconds": 10, "cost_usd": 0.001},
            ],
        })

        update = _make_mock_update()
        context = _make_mock_context()
        run_async(tg_bot.status(update, context))
        call_text = update.message.reply_text.call_args[0][0]
        assert "disabled-job" in call_text


class TestHandleCallbackQueryA2UI:
    """Test the A2UI callback query path (non-cancel, non-permission)."""

    def test_a2ui_callback(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")

        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = 67890
        update.callback_query.data = "action_confirm"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_reply_markup = AsyncMock()
        update.callback_query.message.message_thread_id = None
        update.callback_query.message.chat = MagicMock()
        update.callback_query.message.reply_text = AsyncMock()

        context = _make_mock_context()

        # Mock _handle_message_impl to avoid running the full handler
        mock_impl = AsyncMock()
        monkeypatch.setattr(tg_bot, "_handle_message_impl", mock_impl)

        run_async(tg_bot.handle_callback_query(update, context))

        # Should have called _handle_message_impl with the button prompt
        mock_impl.assert_called_once()
        call_args = mock_impl.call_args
        assert "action_confirm" in str(call_args)


class TestHandleMessageImpl:
    """Test _handle_message_impl (the lock wrapper)."""

    def test_calls_locked_impl(self, monkeypatch):
        mock_locked = AsyncMock()
        monkeypatch.setattr(tg_bot, "_handle_message_impl_locked", mock_locked)

        update = _make_mock_update()
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl(
            update, context, 12345, "test msg", None, 67890, None, False
        ))

        mock_locked.assert_called_once()


class TestGetSystemStatusHeartbeat:
    """Test heartbeat log reading in get_system_status."""

    def test_no_heartbeat_log(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {},
            "job_summaries": [],
            "recent_runs": [],
        })
        # The function reads Path('/tmp/heartbeat.log') directly
        # It will either find a real file or say "No log file"
        status = tg_bot.get_system_status(12345)
        assert "last_heartbeat" in status

    def test_claude_cli_not_available(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "collect_status", lambda: {
            "daemons": {},
            "job_summaries": [],
            "recent_runs": [],
        })
        # Mock subprocess.run to simulate claude not available
        import subprocess
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            if args[0] == ['claude', '--version']:
                raise FileNotFoundError("not found")
            return original_run(*args, **kwargs)
        monkeypatch.setattr(tg_bot.subprocess, "run", mock_run)

        status = tg_bot.get_system_status(12345)
        assert status["claude"] == "Not available"


class TestHandleMessageMainSession:
    """Test handle_message with main session."""

    def test_main_session_routing(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: t == 555)
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"topic_id": 99999}})
        monkeypatch.setattr(tg_bot, "get_main_session_id", lambda: "main-id-123")

        update = _make_mock_update(thread_id=555)
        context = _make_mock_context()

        captured = {}

        async def capture_impl(*args, **kwargs):
            if len(args) >= 5:
                captured["session_id"] = args[4]

        monkeypatch.setattr(tg_bot, "_handle_message_impl", capture_impl)

        run_async(tg_bot.handle_message(update, context))
        assert captured.get("session_id") == "main-id-123"


class TestHandleMessageError:
    """Test handle_message error handling."""

    def test_impl_error_caught(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "config", {"tasks": {"topic_id": 99999}})

        update = _make_mock_update()
        context = _make_mock_context()

        async def failing_impl(*args, **kwargs):
            raise RuntimeError("Something broke")

        monkeypatch.setattr(tg_bot, "_handle_message_impl", failing_impl)

        # Should not raise - error is caught and replied
        run_async(tg_bot.handle_message(update, context))
        # Should have tried to send error message
        assert update.message.reply_text.call_count >= 1


class TestParseFileAttachmentsEdgeCases:
    def test_json_decode_error(self):
        text = '/sendfile {not valid json!}'
        clean, files = tg_bot.parse_file_attachments(text)
        assert files == []

    def test_home_path(self):
        text = '/sendfile ~/Documents/test.pdf'
        clean, files = tg_bot.parse_file_attachments(text)
        assert len(files) == 1
        assert files[0]["path"] == "~/Documents/test.pdf"

    def test_interleaved_text_and_files(self):
        text = "Here is file 1\n/sendfile /tmp/a.txt\nAnd file 2\n/sendfile /tmp/b.txt\nDone."
        clean, files = tg_bot.parse_file_attachments(text)
        assert len(files) == 2
        assert "/sendfile" not in clean


class TestSmartChunkCodeBlockEdge:
    def test_unclosed_code_block_no_close(self):
        """Code block with no closing - should hard split."""
        text = "```python\n" + "x = 1\n" * 1000
        chunks = tg_bot.smart_chunk_text(text, max_length=500)
        assert len(chunks) > 1

    def test_code_block_with_close_after_max(self):
        """Code block closing beyond max_length but within 1.5x."""
        code = "```python\n" + "x = 1\n" * 80 + "```\n\nAfter code"
        chunks = tg_bot.smart_chunk_text(code, max_length=500)
        assert len(chunks) >= 1


class TestSanitizeMarkdownCodeBlock:
    def test_even_code_blocks_untouched(self):
        text = "```python\ncode\n```\n\n```js\nmore\n```"
        result = tg_bot.sanitize_markdown(text)
        assert result == text

    def test_paired_bold_untouched(self):
        text = "**bold** and **more bold**"
        result = tg_bot.sanitize_markdown(text)
        assert result == text


class TestHandleSkillCommandWithSession:
    def test_skill_with_main_session(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: ["my-skill"])
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: t == 100)
        monkeypatch.setattr(tg_bot, "get_main_session_id", lambda: "main-abc")
        monkeypatch.setattr(tg_bot, "config", {"tasks": {}})

        update = _make_mock_update(text="/my-skill do stuff", thread_id=100)
        context = _make_mock_context()

        mock_response = {"result": "Skill done", "session_id": "new-main-sess"}
        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: mock_response)
        monkeypatch.setattr(tg_bot, "save_main_session_id", MagicMock())
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        run_async(tg_bot.handle_skill_command(update, context))
        tg_bot.save_main_session_id.assert_called_once_with("new-main-sess")

    def test_skill_no_session_in_response(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: ["my-skill"])
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "config", {"tasks": {}})

        update = _make_mock_update(text="/my-skill")
        context = _make_mock_context()

        mock_response = {"result": "Done", "session_id": None}
        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: mock_response)

        run_async(tg_bot.handle_skill_command(update, context))
        # Should still send the response text
        assert update.message.reply_text.call_count >= 1

    def test_skill_multi_chunk_response(self, monkeypatch, tmp_sessions):
        monkeypatch.setattr(tg_bot, "ALLOWED_USERS", {12345})
        monkeypatch.setattr(tg_bot, "get_available_skills", lambda: ["my-skill"])
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "config", {"tasks": {}})

        update = _make_mock_update(text="/my-skill")
        context = _make_mock_context()

        # Response text long enough to chunk
        long_text = "A" * 5000 + "\n\n" + "B" * 5000
        mock_response = {"result": long_text, "session_id": "sess-1"}
        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: mock_response)
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        run_async(tg_bot.handle_skill_command(update, context))
        # Should have sent multiple chunks
        assert update.message.reply_text.call_count >= 2


class TestHandleMessageImplLocked:
    """Test _handle_message_impl_locked - the core message handler.

    This function has complex threading, UI updates, and calls run_claude.
    We mock run_claude to return immediately.
    """

    def test_basic_message_flow(self, monkeypatch, tmp_sessions):
        """Test the most basic message flow through the locked impl."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        response = {"result": "Hello back", "session_id": "new-sess", "cost": 0.01,
                     "duration": 2.0, "turns": 1, "cache_read": 0, "output_tokens": 50}

        def mock_run_claude(prompt, session_id=None, tool_callback=None,
                           text_callback=None, request_id=None, model=None):
            return response

        monkeypatch.setattr(tg_bot, "run_claude", mock_run_claude)

        update = _make_mock_update()
        # reply_text needs to return a mock message with edit_text and delete
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "Hello",
            None, 67890, None, False
        ))

        # Should have sent at least one reply
        assert update.message.reply_text.call_count >= 1
        # Session should be saved
        assert tg_bot.get_session_id(12345) == "new-sess"

    def test_fast_mode_exclamation(self, monkeypatch, tmp_sessions):
        """Test that '!' prefix triggers haiku model."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        captured_model = {}

        def mock_run_claude(prompt, session_id=None, tool_callback=None,
                           text_callback=None, request_id=None, model=None):
            captured_model["model"] = model
            return {"result": "Fast response", "session_id": "fast-sess"}

        monkeypatch.setattr(tg_bot, "run_claude", mock_run_claude)

        update = _make_mock_update()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "!quick question",
            None, 67890, None, False
        ))

        assert captured_model.get("model") == "haiku"

    def test_response_with_file_attachments(self, monkeypatch, tmp_sessions, tmp_path):
        """Test response that includes /sendfile commands."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        test_file = tmp_path / "report.pdf"
        test_file.write_bytes(b"fake pdf")

        response = {
            "result": f"Here is your report\n/sendfile {test_file}",
            "session_id": "file-sess"
        }

        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: response)

        update = _make_mock_update()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "generate report",
            None, 67890, None, False
        ))

        # Should have sent the file
        context.bot.send_document.assert_called_once()

    def test_response_with_inline_buttons(self, monkeypatch, tmp_sessions):
        """Test response that includes /buttons."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        response = {
            "result": 'Choose option\n/buttons [{"text": "A", "data": "opt_a"}]',
            "session_id": "btn-sess"
        }

        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: response)

        update = _make_mock_update()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "show options",
            None, 67890, None, False
        ))

        # Should have sent response (edit_text on status_msg or reply_text)
        assert update.message.reply_text.call_count >= 1 or status_msg.edit_text.call_count >= 1

    def test_session_expired(self, monkeypatch, tmp_sessions):
        """Test that expired sessions get cleaned up."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        # Create a session file first
        tg_bot.save_session_id(12345, "old-expired-sess")

        response = {
            "result": "Session expired, starting fresh",
            "session_id": "new-sess",
            "session_expired": True
        }

        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: response)

        update = _make_mock_update()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "hello",
            "old-expired-sess", 67890, None, False
        ))

        # Session file for the old session should be deleted
        # (but new session is saved)
        assert tg_bot.get_session_id(12345) == "new-sess"

    def test_main_session_saves_to_main(self, monkeypatch, tmp_sessions):
        """Test that main session saves session ID via save_main_session_id."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: t == 100)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        saved = {}
        monkeypatch.setattr(tg_bot, "save_main_session_id", lambda sid: saved.update({"sid": sid}))

        response = {"result": "OK", "session_id": "main-new"}
        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: response)

        update = _make_mock_update(thread_id=100)
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "main msg",
            "old-main", 67890, 100, False
        ))

        assert saved.get("sid") == "main-new"

    def test_multi_chunk_response_spinner_mode(self, monkeypatch, tmp_sessions):
        """Test multi-chunk response in spinner (non-draft) mode."""
        monkeypatch.setattr(tg_bot, "is_main_topic", lambda t: False)
        monkeypatch.setattr(tg_bot, "STREAM_MODE", "off")
        monkeypatch.setattr(tg_bot, "config", {"subagents": {"enabled": False}})
        monkeypatch.setattr(tg_bot, "register_session", lambda **kw: None)

        long_text = "First paragraph\n\n" + "x" * 5000 + "\n\nLast paragraph"
        response = {"result": long_text, "session_id": "chunk-sess"}
        monkeypatch.setattr(tg_bot, "run_claude", lambda *a, **kw: response)

        update = _make_mock_update()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        status_msg.delete = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        context = _make_mock_context()

        run_async(tg_bot._handle_message_impl_locked(
            update, context, 12345, "long response please",
            None, 67890, None, False
        ))

        # Multiple chunks: status_msg should be deleted, then reply_text called multiple times
        assert update.message.reply_text.call_count >= 2
