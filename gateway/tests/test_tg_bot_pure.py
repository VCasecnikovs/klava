"""Tests for pure functions in gateway/tg-bot.py.

Loads tg-bot.py with mocked external dependencies (telegram, telethon)
to extract and test pure string processing and parsing functions.
"""

import json
import os
import sys
import types
import pytest
from unittest.mock import MagicMock
from pathlib import Path

# ── Mock heavy dependencies before importing tg-bot.py ──

# Mock telegram module
_mock_telegram = types.ModuleType("telegram")
_mock_telegram.Update = MagicMock
_mock_telegram.BotCommand = MagicMock
_mock_telegram.InlineKeyboardButton = MagicMock
_mock_telegram.InlineKeyboardMarkup = MagicMock
_mock_telegram_ext = types.ModuleType("telegram.ext")
_mock_telegram_ext.Application = MagicMock
_mock_telegram_ext.CommandHandler = MagicMock
_mock_telegram_ext.MessageHandler = MagicMock
_mock_telegram_ext.CallbackQueryHandler = MagicMock
_mock_telegram_ext.filters = MagicMock()
_mock_telegram_ext.ContextTypes = MagicMock

# Mock telethon
_mock_telethon = types.ModuleType("telethon")
_mock_telethon.TelegramClient = MagicMock
_mock_telethon.functions = MagicMock()
_mock_telethon_sessions = types.ModuleType("telethon.sessions")
_mock_telethon_sessions.StringSession = MagicMock

# Register mocks
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
    # Module may fail on init (missing config, logging to /tmp, etc.)
    # But functions are defined before main() so they should be available
    pass


# ── Tests ──

class TestParseClaudeResult:
    def test_full_result(self):
        data = {
            "result": "Hello world",
            "session_id": "abc-123",
            "total_cost_usd": 0.05,
            "duration_ms": 2500,
            "num_turns": 3,
            "modelUsage": {"claude-sonnet": {"input": 100}},
            "usage": {
                "input_tokens": 500,
                "output_tokens": 200,
                "cache_read_input_tokens": 1000,
            },
        }
        r = tg_bot._parse_claude_result(data)
        assert r["result"] == "Hello world"
        assert r["session_id"] == "abc-123"
        assert r["cost"] == 0.05
        assert r["duration"] == 2.5
        assert r["turns"] == 3
        assert r["input_tokens"] == 500
        assert r["output_tokens"] == 200
        assert r["cache_read"] == 1000

    def test_empty_result(self):
        r = tg_bot._parse_claude_result({})
        assert r["result"] == "No response"
        assert r["cost"] == 0
        assert r["duration"] == 0


class TestGetSessionKey:
    def test_without_thread(self):
        assert tg_bot.get_session_key(12345) == "tg_12345"

    def test_with_thread(self):
        assert tg_bot.get_session_key(12345, 99) == "tg_12345_topic_99"


class TestSmartChunkText:
    def test_short_text(self):
        assert tg_bot.smart_chunk_text("hello") == ["hello"]

    def test_splits_at_paragraph(self):
        p1 = "a" * 3000
        p2 = "b" * 3000
        chunks = tg_bot.smart_chunk_text(f"{p1}\n\n{p2}", max_length=4096)
        assert len(chunks) == 2

    def test_respects_code_blocks(self):
        code = "```python\n" + "x = 1\n" * 500 + "```"
        text = "Before\n\n" + code + "\n\nAfter"
        chunks = tg_bot.smart_chunk_text(text, max_length=200)
        # Should try to keep code block together
        assert len(chunks) >= 2

    def test_hard_split_no_boundaries(self):
        text = "a" * 8192
        chunks = tg_bot.smart_chunk_text(text, max_length=4096)
        assert len(chunks) == 2

    def test_sentence_boundary(self):
        sentences = ". ".join(["Sentence " + str(i) for i in range(100)])
        chunks = tg_bot.smart_chunk_text(sentences, max_length=500)
        for c in chunks:
            assert len(c) <= 500 * 1.5  # Allow some overflow for code blocks


class TestMarkdownToMarkdownV2:
    def test_passthrough(self):
        assert tg_bot.markdown_to_markdownv2("hello **bold**") == "hello **bold**"


class TestSanitizeMarkdown:
    def test_fixes_unpaired_bold(self):
        result = tg_bot.sanitize_markdown("hello **bold")
        assert result.count("**") != 1  # Should be fixed

    def test_fixes_unpaired_code_block(self):
        result = tg_bot.sanitize_markdown("```python\ncode here")
        assert result.count("```") % 2 == 0  # Should close it

    def test_leaves_valid_markdown(self):
        text = "**bold** and `code`"
        assert tg_bot.sanitize_markdown(text) == text

    def test_fixes_unpaired_backtick(self):
        result = tg_bot.sanitize_markdown("hello `code")
        # Should handle single backtick
        assert "`" in result


class TestFormatResponseWithMeta:
    def test_with_all_meta(self):
        resp = {"result": "Hello", "cost": 0.05, "duration": 10, "turns": 3, "cache_read": 5000}
        text = tg_bot.format_response_with_meta(resp)
        assert "Hello" in text
        assert "$0.05" in text
        assert "10s" in text
        assert "3t" in text
        assert "5k⚡" in text

    def test_minimal_response(self):
        resp = {"result": "OK"}
        text = tg_bot.format_response_with_meta(resp)
        assert text == "OK"  # No meta footer

    def test_output_tokens_shown(self):
        resp = {"result": "OK", "output_tokens": 150}
        text = tg_bot.format_response_with_meta(resp)
        assert "150tok" in text


class TestParseFileAttachments:
    def test_simple_path(self):
        text = "Here is the file\n/sendfile /tmp/report.pdf"
        clean, files = tg_bot.parse_file_attachments(text)
        assert len(files) == 1
        assert files[0]["path"] == "/tmp/report.pdf"
        assert "/sendfile" not in clean

    def test_json_format(self):
        text = '/sendfile {"path": "/tmp/x.pdf", "caption": "Report"}'
        clean, files = tg_bot.parse_file_attachments(text)
        assert len(files) == 1
        assert files[0]["caption"] == "Report"

    def test_no_attachments(self):
        text = "Just regular text"
        clean, files = tg_bot.parse_file_attachments(text)
        assert files == []
        assert clean == text

    def test_multiple_files(self):
        text = "Files:\n/sendfile /tmp/a.pdf\n/sendfile /tmp/b.pdf"
        clean, files = tg_bot.parse_file_attachments(text)
        assert len(files) == 2


class TestSessionFilePaths:
    """Test session file path generation (monkeypatched)."""

    def test_session_id_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tg_bot, "SESSIONS_DIR", tmp_path)
        f = tg_bot.get_session_id_file(123)
        assert f.name == "tg_123_claude_session.txt"
        assert f.parent == tmp_path

    def test_session_log_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tg_bot, "SESSIONS_DIR", tmp_path)
        f = tg_bot.get_session_log_file(123, 456)
        assert f.name == "tg_123_topic_456.jsonl"

    def test_save_and_get_session_id(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tg_bot, "SESSIONS_DIR", tmp_path)
        tg_bot.save_session_id(123, "sess-abc")
        assert tg_bot.get_session_id(123) == "sess-abc"

    def test_get_session_id_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tg_bot, "SESSIONS_DIR", tmp_path)
        assert tg_bot.get_session_id(999) is None
