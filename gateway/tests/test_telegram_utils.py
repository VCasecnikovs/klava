"""Tests for gateway/lib/telegram_utils.py - markdown conversion and message splitting."""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.telegram_utils import markdown_to_html, _split_message, get_telegram_config


class TestMarkdownToHtml:
    def test_bold_asterisks(self):
        assert markdown_to_html("**bold**") == "<b>bold</b>"

    def test_bold_underscores(self):
        assert markdown_to_html("__bold__") == "<b>bold</b>"

    def test_italic(self):
        assert markdown_to_html("*italic*") == "<i>italic</i>"

    def test_inline_code(self):
        assert markdown_to_html("`code`") == "<code>code</code>"

    def test_code_block(self):
        result = markdown_to_html("```python\nprint('hi')\n```")
        assert "<pre>" in result
        assert "print('hi')" in result

    def test_code_block_no_lang(self):
        result = markdown_to_html("```\ncode\n```")
        assert "<pre>" in result

    def test_link(self):
        result = markdown_to_html("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' == result

    def test_strip_headers(self):
        assert markdown_to_html("## Header") == "Header"
        assert markdown_to_html("# H1") == "H1"
        assert markdown_to_html("### H3") == "H3"

    def test_mixed(self):
        result = markdown_to_html("**bold** and *italic* and `code`")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<code>code</code>" in result

    def test_passthrough_plain(self):
        assert markdown_to_html("plain text") == "plain text"

    def test_multiline_headers(self):
        text = "## First\nText\n## Second"
        result = markdown_to_html(text)
        assert result == "First\nText\nSecond"


class TestSplitMessage:
    def test_short_message_no_split(self):
        assert _split_message("hello") == ["hello"]

    def test_exact_limit(self):
        msg = "a" * 4000
        assert _split_message(msg) == [msg]

    def test_splits_at_paragraph(self):
        # Two paragraphs, each 3000 chars
        p1 = "a" * 3000
        p2 = "b" * 3000
        msg = p1 + "\n\n" + p2
        chunks = _split_message(msg, max_length=4000)
        assert len(chunks) == 2
        assert chunks[0] == p1
        assert chunks[1] == p2

    def test_splits_at_newline(self):
        # Lines that are too long for one chunk
        lines = ["line " + str(i) + " " + "x" * 100 for i in range(50)]
        msg = "\n".join(lines)
        chunks = _split_message(msg, max_length=500)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 500

    def test_splits_at_space(self):
        words = ["word"] * 1000
        msg = " ".join(words)
        chunks = _split_message(msg, max_length=100)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 100

    def test_hard_split_no_boundaries(self):
        msg = "a" * 8000  # no spaces, no newlines
        chunks = _split_message(msg, max_length=4000)
        assert len(chunks) == 2
        assert len(chunks[0]) == 4000
        assert len(chunks[1]) == 4000

    def test_custom_max_length(self):
        msg = "a" * 200
        chunks = _split_message(msg, max_length=50)
        assert len(chunks) == 4


class TestGetTelegramConfig:
    def test_extracts_config(self, monkeypatch):
        monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
        config = {
            "telegram": {
                "bot_token": "tok123",
                "allowed_users": [12345, 67890],
            },
            "heartbeat": {"topic_id": 100001},
        }
        token, chat_id, topic = get_telegram_config(config)
        assert token == "tok123"
        assert chat_id == 12345
        assert topic == 100001

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("TG_BOT_TOKEN", "env-token")
        config = {"telegram": {"bot_token": "file-token", "allowed_users": [1]}}
        token, chat_id, topic = get_telegram_config(config)
        assert token == "env-token"

    def test_empty_config(self, monkeypatch):
        monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
        token, chat_id, topic = get_telegram_config({})
        assert token == ""
        assert chat_id == 0
        assert topic is None

    def test_no_allowed_users(self, monkeypatch):
        monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
        config = {"telegram": {"bot_token": "tok", "allowed_users": []}}
        token, chat_id, topic = get_telegram_config(config)
        assert chat_id == 0


# ── _tg_api_call ──

from lib.telegram_utils import _tg_api_call, send_telegram_message_with_id, edit_telegram_message, send_telegram_message


class TestTgApiCall:
    @patch("lib.telegram_utils.subprocess.run")
    def test_successful_call(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok":true,"result":{}}')
        result = _tg_api_call("https://api.telegram.org/bot123/sendMessage", {"chat_id": 1, "text": "hi"})
        assert result == {"ok": True, "result": {}}
        mock_run.assert_called_once()

    @patch("lib.telegram_utils.subprocess.run")
    def test_non_zero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = _tg_api_call("https://url", {"a": 1})
        assert result == {}

    @patch("lib.telegram_utils.subprocess.run")
    def test_timeout_returns_empty(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="curl", timeout=10)
        result = _tg_api_call("https://url", {}, timeout=10)
        assert result == {}

    @patch("lib.telegram_utils.subprocess.run")
    def test_invalid_json_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not json{{{")
        result = _tg_api_call("https://url", {})
        assert result == {}


class TestSendTelegramMessageWithId:
    @patch("lib.telegram_utils._tg_api_call")
    def test_returns_message_id(self, mock_api):
        mock_api.return_value = {"ok": True, "result": {"message_id": 42}}
        mid = send_telegram_message_with_id("tok", 123, "hello")
        assert mid == 42

    @patch("lib.telegram_utils._tg_api_call")
    def test_with_topic_id(self, mock_api):
        mock_api.return_value = {"ok": True, "result": {"message_id": 99}}
        mid = send_telegram_message_with_id("tok", 123, "hi", topic_id=555)
        assert mid == 99
        call_params = mock_api.call_args[0][1]
        assert call_params["message_thread_id"] == 555

    @patch("lib.telegram_utils._tg_api_call")
    def test_truncates_long_message(self, mock_api):
        mock_api.return_value = {"ok": True, "result": {"message_id": 1}}
        send_telegram_message_with_id("tok", 123, "a" * 5000)
        call_params = mock_api.call_args[0][1]
        assert len(call_params["text"]) == 4000

    @patch("lib.telegram_utils._tg_api_call")
    def test_api_error_returns_none(self, mock_api):
        mock_api.return_value = {"ok": False, "error_code": 403}
        mid = send_telegram_message_with_id("tok", 123, "hi")
        assert mid is None

    @patch("lib.telegram_utils._tg_api_call")
    def test_empty_response_returns_none(self, mock_api):
        mock_api.return_value = {}
        mid = send_telegram_message_with_id("tok", 123, "hi")
        assert mid is None


class TestEditTelegramMessage:
    @patch("lib.telegram_utils._tg_api_call")
    def test_successful_edit(self, mock_api):
        mock_api.return_value = {"ok": True}
        assert edit_telegram_message("tok", 123, 42, "new text") is True

    @patch("lib.telegram_utils._tg_api_call")
    def test_not_modified_is_ok(self, mock_api):
        mock_api.return_value = {"ok": False, "error_code": 400, "description": "message is not modified"}
        assert edit_telegram_message("tok", 123, 42, "same text") is True

    @patch("lib.telegram_utils._tg_api_call")
    def test_truncates_long_text(self, mock_api):
        mock_api.return_value = {"ok": True}
        edit_telegram_message("tok", 123, 42, "a" * 5000)
        call_params = mock_api.call_args[0][1]
        assert len(call_params["text"]) == 4000

    @patch("lib.telegram_utils._tg_api_call")
    def test_other_error_returns_false(self, mock_api):
        mock_api.return_value = {"ok": False, "error_code": 500}
        assert edit_telegram_message("tok", 123, 42, "text") is False

    @patch("lib.telegram_utils._tg_api_call")
    def test_empty_response_returns_false(self, mock_api):
        mock_api.return_value = {}
        assert edit_telegram_message("tok", 123, 42, "text") is False


class TestSendTelegramMessage:
    @patch("lib.telegram_utils._tg_api_call")
    def test_successful_send(self, mock_api):
        mock_api.return_value = {"ok": True}
        assert send_telegram_message("tok", 123, "hello") is True

    @patch("lib.telegram_utils._tg_api_call")
    def test_with_topic_id(self, mock_api):
        mock_api.return_value = {"ok": True}
        send_telegram_message("tok", 123, "hello", topic_id=555)
        call_params = mock_api.call_args[0][1]
        assert call_params["message_thread_id"] == 555

    @patch("lib.telegram_utils._tg_api_call")
    def test_html_parse_mode_converts(self, mock_api):
        mock_api.return_value = {"ok": True}
        send_telegram_message("tok", 123, "**bold**", parse_mode="HTML")
        call_params = mock_api.call_args[0][1]
        assert "<b>bold</b>" in call_params["text"]

    @patch("lib.telegram_utils._tg_api_call")
    def test_fallback_to_plain_on_400(self, mock_api):
        mock_api.side_effect = [
            {"ok": False, "error_code": 400},  # first try with parse_mode
            {"ok": True},  # retry without
        ]
        assert send_telegram_message("tok", 123, "hello", parse_mode="HTML", fallback_to_plain=True) is True
        assert mock_api.call_count == 2

    @patch("lib.telegram_utils._tg_api_call")
    def test_no_fallback(self, mock_api):
        mock_api.return_value = {"ok": False, "error_code": 400}
        assert send_telegram_message("tok", 123, "hello", parse_mode="HTML", fallback_to_plain=False) is False

    @patch("lib.telegram_utils._tg_api_call")
    def test_long_message_split(self, mock_api):
        mock_api.return_value = {"ok": True}
        long_msg = "a" * 3000 + "\n\n" + "b" * 3000
        send_telegram_message("tok", 123, long_msg)
        assert mock_api.call_count == 2

    @patch("lib.telegram_utils._tg_api_call")
    def test_api_error_returns_false(self, mock_api):
        mock_api.return_value = {"ok": False, "error_code": 500}
        assert send_telegram_message("tok", 123, "hello") is False

    @patch("lib.telegram_utils._tg_api_call")
    def test_empty_response_returns_false(self, mock_api):
        mock_api.return_value = {}
        assert send_telegram_message("tok", 123, "hello") is False

    @patch("lib.telegram_utils._tg_api_call")
    def test_custom_logger(self, mock_api):
        mock_api.return_value = {"ok": True}
        custom_log = MagicMock()
        send_telegram_message("tok", 123, "hi", custom_logger=custom_log)
        custom_log.info.assert_called_once()
