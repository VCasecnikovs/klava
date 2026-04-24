"""Tests for pure functions in gateway/webhook-server.py.

Uses the conftest flask_app fixture to load the module safely.
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def ws():
    """Get the webhook_server module via conftest loading."""
    return sys.modules.get("webhook_server") or __import__("webhook_server")


class TestParseSessionEntry:
    """Test _parse_session_entry - converts JSONL entries to display format."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        """Load webhook_server module via flask_app fixture."""
        import webhook_server as ws
        self.parse = ws._parse_session_entry

    def test_user_entry_simple(self):
        entry = {
            "type": "user",
            "message": {"content": "Hello Claude"},
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result["role"] == "user"
        assert result["text"] == "Hello Claude"

    def test_user_entry_list_content(self):
        entry = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                    {"type": "image", "source": "data:..."},
                ]
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result["role"] == "user"
        assert "Part 1" in result["text"]
        assert "Part 2" in result["text"]

    def test_user_entry_empty_content(self):
        entry = {"type": "user", "message": {"content": ""}}
        result = self.parse(entry)
        assert result is None

    def test_assistant_text_only(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Here is my response"}],
                "model": "claude-sonnet-4-5",
            },
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result["role"] == "assistant"
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Here is my response"
        assert result["model"] == "claude-sonnet-4-5"
        assert result["usage"]["input"] == 100

    def test_assistant_tool_use(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Let me check..."},
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/test.py"}},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "tool_use"
        assert result["content"][1]["tool"] == "Read"

    def test_assistant_ask_user_question(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "AskUserQuestion",
                     "input": {"questions": [{"question": "Choose?", "options": ["A", "B"]}]}},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        # Should have both tool_use and question markers
        types = [c["type"] for c in result["content"]]
        assert "tool_use" in types
        assert "question" in types

    def test_assistant_plan_mode(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "EnterPlanMode", "input": {}},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        types = [c["type"] for c in result["content"]]
        assert "plan_mode" in types

    def test_assistant_thinking(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "I need to think about this..." * 100},
                    {"type": "text", "text": "Here's my answer"},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        thinking = [c for c in result["content"] if c["type"] == "thinking"]
        assert len(thinking) == 1
        assert len(thinking[0]["text"]) <= 1000  # truncated

    def test_assistant_empty_content(self):
        entry = {
            "type": "assistant",
            "message": {"content": []},
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result is None

    def test_assistant_only_empty_text(self):
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "   "}]},
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result is None

    def test_result_entry(self):
        entry = {
            "type": "result",
            "result": "Task completed successfully",
            "session_id": "sess-abc-123",
            "cost_usd": 0.05,
            "duration_seconds": 30,
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result["role"] == "result"
        assert result["text"] == "Task completed successfully"
        assert result["cost"] == 0.05
        assert result["duration"] == 30

    def test_result_truncated(self):
        entry = {
            "type": "result",
            "result": "x" * 5000,
            "session_id": "sess",
        }
        result = self.parse(entry)
        assert len(result["text"]) <= 2000

    def test_progress_entry(self):
        entry = {"type": "progress", "timestamp": "2026-03-16T10:00:00"}
        result = self.parse(entry)
        assert result["role"] == "progress"

    def test_unknown_type(self):
        entry = {"type": "unknown_type"}
        result = self.parse(entry)
        assert result is None


class TestCheckRateLimit:
    """Test check_rate_limit function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.ws = ws

    def test_allows_first_request(self):
        # Clear rate limit store
        self.ws.rate_limit_store.clear()
        assert self.ws.check_rate_limit("test-client") is True

    def test_blocks_after_limit(self):
        self.ws.rate_limit_store.clear()
        # Fill up to limit
        for _ in range(self.ws.MAX_REQUESTS_PER_HOUR):
            self.ws.check_rate_limit("flood-client")
        # Next should fail
        assert self.ws.check_rate_limit("flood-client") is False

    def test_different_clients_independent(self):
        self.ws.rate_limit_store.clear()
        for _ in range(self.ws.MAX_REQUESTS_PER_HOUR):
            self.ws.check_rate_limit("client-a")
        # client-b should still work
        assert self.ws.check_rate_limit("client-b") is True


class TestSessionsAPI:
    """Test /api/sessions endpoint."""

    def test_sessions_list(self, client, auth_headers):
        resp = client.get("/api/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "sessions" in data

    def test_sessions_registry(self, client, auth_headers):
        resp = client.get("/api/sessions/registry", headers=auth_headers)
        assert resp.status_code == 200


class TestChatStateAPI:
    """Test /api/chat/state endpoints."""

    def test_get_chat_state(self, client, auth_headers):
        resp = client.get("/api/chat/state", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_sessions" in data

    def test_set_active_session(self, client, auth_headers):
        resp = client.post("/api/chat/state/active",
                          headers=auth_headers,
                          json={"session_id": "test-sess-123", "action": "add"})
        assert resp.status_code == 200

    def test_remove_active_session(self, client, auth_headers):
        resp = client.post("/api/chat/state/active",
                          headers=auth_headers,
                          json={"session_id": "test-sess-123", "action": "remove"})
        assert resp.status_code == 200

    def test_invalid_action(self, client, auth_headers):
        resp = client.post("/api/chat/state/active",
                          headers=auth_headers,
                          json={"session_id": "test-sess-123"})
        assert resp.status_code == 400

    def test_name_session(self, client, auth_headers):
        resp = client.post("/api/chat/state/name",
                          headers=auth_headers,
                          json={"session_id": "test-sess-123", "name": "My Session"})
        assert resp.status_code == 200

    def test_cancel_session(self, client, auth_headers):
        resp = client.post("/api/chat/state/cancel",
                          headers=auth_headers,
                          json={"session_id": "test-sess-123"})
        # May return 200 or 404 depending on state
        assert resp.status_code in (200, 404)


class TestWriteResultToJsonl:
    """Test _write_result_to_jsonl."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.ws = ws

    def test_no_session_id(self):
        # Should not crash
        self.ws._write_result_to_jsonl(None, 0.05, 30, "sonnet")

    def test_session_not_found(self):
        # Should not crash
        self.ws._write_result_to_jsonl("nonexistent-sess-id", 0.05, 30, "sonnet")
