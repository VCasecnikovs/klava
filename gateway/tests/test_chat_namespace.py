"""Tests for ChatNamespace helper methods.

Covers:
- _build_blocks_from_entry: JSONL entry -> blocks conversion
- _build_blocks_from_jsonl: full JSONL file parsing
- _save_stream_state / _clear_stream_state: stream state persistence
- _prepare_prompt: file reference injection
- _emit_buffered: buffered event emission
- _block_add / _block_update: block state management
- _emit_queue_update: queue state emission
- _get_session_process: process lookup
- on_send_message: message validation and routing
- on_queue_remove: queue item removal
- on_draft_save: draft persistence
- on_resume_stream: stream reconnection replay
- on_cancel: session cancellation
- on_remove_active / on_add_active: active session management
- on_connect / on_disconnect: connection lifecycle
- on_permission_response: permission handling
- on_question_response: question answer handling
- on_detach_all: socket detachment
- _route_message: message routing to existing sessions
"""

import json
import os
import asyncio
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


@pytest.fixture
def flask_app_module(flask_app):
    """Return the webhook_server module (loaded by flask_app fixture)."""
    import webhook_server
    return webhook_server


@pytest.fixture
def chat_ns(flask_app_module):
    """Create a ChatNamespace instance for testing helper methods."""
    ns = flask_app_module.ChatNamespace("/chat")
    return ns


@pytest.fixture
def stream_state_dir(tmp_path, flask_app_module, monkeypatch):
    """Redirect CHAT_STREAM_DIR and CHAT_STREAM_STATE to tmp_path."""
    stream_dir = tmp_path / "chat_stream"
    stream_state = stream_dir / "streaming.json"
    monkeypatch.setattr(flask_app_module, "CHAT_STREAM_DIR", stream_dir)
    monkeypatch.setattr(flask_app_module, "CHAT_STREAM_STATE", stream_state)
    return stream_dir, stream_state


# ── _build_blocks_from_entry ─────────────────────────────────────────


class TestBuildBlocksFromEntry:
    """Tests for _build_blocks_from_entry."""

    def test_user_text_content(self, chat_ns):
        entry = {"type": "user", "message": {"content": "Hello world"}}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "user"
        assert blocks[0]["id"] == 0
        assert blocks[0]["text"] == "Hello world"
        assert blocks[0]["files"] == []

    def test_user_list_content(self, chat_ns):
        entry = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "Part one"},
                    {"type": "text", "text": "Part two"},
                    {"type": "image", "source": {"data": "..."}},
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 5)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "user"
        assert blocks[0]["id"] == 5
        assert blocks[0]["text"] == "Part one Part two"

    def test_user_empty_content_produces_no_blocks(self, chat_ns):
        entry = {"type": "user", "message": {"content": ""}}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert blocks == []

    def test_user_whitespace_only_produces_no_blocks(self, chat_ns):
        entry = {"type": "user", "message": {"content": "   "}}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert blocks == []

    def test_user_with_image_attachment(self, chat_ns):
        entry = {
            "type": "user",
            "message": {"content": "[Image attached: /tmp/photo.png]\nDescribe this"},
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["text"] == "Describe this"
        assert len(b["files"]) == 1
        assert b["files"][0]["name"] == "photo.png"
        assert b["files"][0]["path"] == "/tmp/photo.png"
        assert "image" in b["files"][0]["type"]

    def test_user_with_file_attachment(self, chat_ns):
        entry = {
            "type": "user",
            "message": {"content": "[File attached: /tmp/data.csv (report.csv)]\nAnalyze this"},
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["text"] == "Analyze this"
        assert len(b["files"]) == 1
        assert b["files"][0]["name"] == "report.csv"
        assert b["files"][0]["path"] == "/tmp/data.csv"

    def test_user_with_multiple_attachments(self, chat_ns):
        entry = {
            "type": "user",
            "message": {
                "content": (
                    "[Image attached: /tmp/a.png]\n"
                    "[File attached: /tmp/b.txt (notes.txt)]\n"
                    "Review these"
                )
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert len(blocks[0]["files"]) == 2
        assert blocks[0]["text"] == "Review these"

    def test_assistant_text(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Here is my response."}]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 10)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "assistant"
        assert blocks[0]["id"] == 10
        assert blocks[0]["text"] == "Here is my response."

    def test_assistant_empty_text_skipped(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "  "}]},
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert blocks == []

    def test_assistant_thinking(self, chat_ns):
        thinking_text = "I need to consider the options carefully " * 10
        entry = {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": thinking_text}]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "thinking"
        assert b["id"] == 0
        assert len(b["text"]) <= 1000  # truncated to 1000 chars
        assert b["words"] > 0
        assert len(b["preview"]) <= 60

    def test_assistant_thinking_truncation(self, chat_ns):
        long_text = "x" * 2000
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": long_text}]},
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks[0]["text"]) == 1000

    def test_assistant_empty_thinking_skipped(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": ""}]},
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert blocks == []

    def test_assistant_tool_use_regular(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "ls -la"},
                    }
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 3)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "tool_use"
        assert b["id"] == 3
        assert b["tool"] == "Bash"
        assert b["input"] == {"command": "ls -la"}
        assert b["running"] is False

    def test_assistant_tool_use_ask_user_question(self, chat_ns):
        questions = [{"text": "Which option?", "options": ["A", "B"]}]
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "AskUserQuestion",
                        "input": {"questions": questions},
                    }
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "question"
        assert b["questions"] == questions
        assert b["answered"] is True

    def test_assistant_tool_use_enter_plan_mode(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "EnterPlanMode", "input": {}}
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "plan"
        assert blocks[0]["active"] is True

    def test_assistant_tool_use_exit_plan_mode(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "ExitPlanMode", "input": {}}
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "plan"
        assert blocks[0]["active"] is False

    def test_assistant_tool_use_agent(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Agent",
                        "input": {"prompt": "do something"},
                    }
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "agent"
        assert b["tool"] == "Agent"
        assert b["input"] == {"prompt": "do something"}
        assert b["running"] is False
        assert b["agent_blocks"] == []

    def test_assistant_tool_use_task(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"prompt": "research X"},
                    }
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "agent"
        assert blocks[0]["tool"] == "Task"

    def test_assistant_mixed_content(self, chat_ns):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Let me think..."},
                    {"type": "text", "text": "Here is my answer."},
                    {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/f"}},
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 3
        assert blocks[0]["type"] == "thinking"
        assert blocks[0]["id"] == 0
        assert blocks[1]["type"] == "assistant"
        assert blocks[1]["id"] == 1
        assert blocks[2]["type"] == "tool_use"
        assert blocks[2]["id"] == 2

    def test_tool_result_text(self, chat_ns):
        entry = {"type": "tool_result", "content": "Command output here"}
        blocks = chat_ns._build_blocks_from_entry(entry, 7)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "tool_result"
        assert b["id"] == 7
        assert b["content"] == "Command output here"
        assert b["tool"] == ""

    def test_tool_result_list_content(self, chat_ns):
        entry = {
            "type": "tool_result",
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
                {"type": "image", "source": {}},
            ],
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert blocks[0]["content"] == "Line 1\nLine 2"

    def test_tool_result_truncation(self, chat_ns):
        entry = {"type": "tool_result", "content": "x" * 5000}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks[0]["content"]) == 2000

    def test_result_with_cost(self, chat_ns):
        entry = {
            "type": "result",
            "cost_usd": 0.042,
            "duration_seconds": 15.7,
            "session_id": "abc-123",
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        b = blocks[0]
        assert b["type"] == "cost"
        assert b["cost"] == 0.042
        assert b["seconds"] == 15
        assert b["session_id"] == "abc-123"

    def test_result_without_optional_fields(self, chat_ns):
        entry = {"type": "result"}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert len(blocks) == 1
        assert blocks[0]["cost"] == 0
        assert blocks[0]["seconds"] == 0
        assert blocks[0]["session_id"] == ""

    def test_unknown_entry_type(self, chat_ns):
        entry = {"type": "system", "content": "ignored"}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert blocks == []

    def test_missing_type(self, chat_ns):
        entry = {"content": "no type field"}
        blocks = chat_ns._build_blocks_from_entry(entry, 0)
        assert blocks == []

    def test_start_id_propagation(self, chat_ns):
        """Block IDs increment correctly from start_id."""
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "First"},
                    {"type": "text", "text": "Second"},
                ]
            },
        }
        blocks = chat_ns._build_blocks_from_entry(entry, 100)
        assert blocks[0]["id"] == 100
        assert blocks[1]["id"] == 101


# ── _build_blocks_from_jsonl ─────────────────────────────────────────


class TestBuildBlocksFromJsonl:
    """Tests for _build_blocks_from_jsonl."""

    def test_basic_conversation(self, chat_ns, tmp_path, flask_app):
        """Parse a simple user-assistant exchange."""
        lines = [
            json.dumps({"type": "user", "message": {"content": "Hello"}}),
            json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4-5-20250514",
                    "content": [{"type": "text", "text": "Hi there!"}],
                },
            }),
            json.dumps({
                "type": "result",
                "cost_usd": 0.01,
                "duration_seconds": 5,
                "session_id": "s1",
            }),
        ]
        f = tmp_path / "session.jsonl"
        f.write_text("\n".join(lines) + "\n")

        with flask_app.app_context():
            blocks, model = chat_ns._build_blocks_from_jsonl(str(f))

        assert len(blocks) == 3
        assert blocks[0]["type"] == "user"
        assert blocks[1]["type"] == "assistant"
        assert blocks[2]["type"] == "cost"
        assert model == "claude-sonnet-4-5-20250514"

    def test_block_ids_sequential(self, chat_ns, tmp_path, flask_app):
        lines = [
            json.dumps({"type": "user", "message": {"content": "Q1"}}),
            json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "A1"}]},
            }),
            json.dumps({"type": "user", "message": {"content": "Q2"}}),
            json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "A2"}]},
            }),
        ]
        f = tmp_path / "session.jsonl"
        f.write_text("\n".join(lines) + "\n")

        with flask_app.app_context():
            blocks, _ = chat_ns._build_blocks_from_jsonl(str(f))

        ids = [b["id"] for b in blocks]
        assert ids == [0, 1, 2, 3]

    def test_empty_file(self, chat_ns, tmp_path, flask_app):
        f = tmp_path / "empty.jsonl"
        f.write_text("")

        with flask_app.app_context():
            blocks, model = chat_ns._build_blocks_from_jsonl(str(f))

        assert blocks == []
        assert model is None

    def test_malformed_json_lines_skipped(self, chat_ns, tmp_path, flask_app):
        lines = [
            "not valid json",
            json.dumps({"type": "user", "message": {"content": "Valid"}}),
            "{broken",
        ]
        f = tmp_path / "bad.jsonl"
        f.write_text("\n".join(lines) + "\n")

        with flask_app.app_context():
            blocks, _ = chat_ns._build_blocks_from_jsonl(str(f))

        assert len(blocks) == 1
        assert blocks[0]["text"] == "Valid"

    def test_blank_lines_skipped(self, chat_ns, tmp_path, flask_app):
        lines = [
            "",
            json.dumps({"type": "user", "message": {"content": "Hello"}}),
            "",
            "",
        ]
        f = tmp_path / "blanks.jsonl"
        f.write_text("\n".join(lines) + "\n")

        with flask_app.app_context():
            blocks, _ = chat_ns._build_blocks_from_jsonl(str(f))

        assert len(blocks) == 1

    def test_model_detected_from_result(self, chat_ns, tmp_path, flask_app):
        lines = [
            json.dumps({"type": "user", "message": {"content": "Hi"}}),
            json.dumps({
                "type": "result",
                "model": "claude-opus-4-6-20250515",
                "cost_usd": 0.05,
            }),
        ]
        f = tmp_path / "session.jsonl"
        f.write_text("\n".join(lines) + "\n")

        with flask_app.app_context():
            _, model = chat_ns._build_blocks_from_jsonl(str(f))

        assert model == "claude-opus-4-6-20250515"

    def test_plan_content_merge(self, chat_ns, tmp_path, flask_app):
        """ExitPlanMode followed by tool_result merges content into plan block."""
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "ExitPlanMode", "input": {}},
                    ]
                },
            }),
            json.dumps({"type": "tool_result", "content": "Plan summary here"}),
        ]
        f = tmp_path / "plan.jsonl"
        f.write_text("\n".join(lines) + "\n")

        with flask_app.app_context():
            blocks, _ = chat_ns._build_blocks_from_jsonl(str(f))

        # tool_result should be merged into the plan block
        assert len(blocks) == 1
        assert blocks[0]["type"] == "plan"
        assert blocks[0]["active"] is False
        assert blocks[0]["content"] == "Plan summary here"

    def test_nonexistent_file(self, chat_ns, flask_app):
        with flask_app.app_context():
            blocks, model = chat_ns._build_blocks_from_jsonl("/nonexistent/path.jsonl")

        assert blocks == []
        assert model is None


# ── _save_stream_state / _clear_stream_state ─────────────────────────


class TestStreamStatePersistence:
    """Tests for _save_stream_state and _clear_stream_state."""

    def test_save_creates_dir_and_file(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._save_stream_state("tab-1", {"session_id": "s1", "status": "streaming"})

        assert stream_dir.exists()
        assert stream_state.exists()
        data = json.loads(stream_state.read_text())
        assert data["tab-1"]["session_id"] == "s1"

    def test_save_multiple_tabs(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._save_stream_state("tab-1", {"status": "streaming"})
            ChatNamespace._save_stream_state("tab-2", {"status": "queued"})

        data = json.loads(stream_state.read_text())
        assert "tab-1" in data
        assert "tab-2" in data

    def test_save_overwrites_same_tab(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._save_stream_state("tab-1", {"v": 1})
            ChatNamespace._save_stream_state("tab-1", {"v": 2})

        data = json.loads(stream_state.read_text())
        assert data["tab-1"]["v"] == 2

    def test_clear_removes_tab(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._save_stream_state("tab-1", {"status": "streaming"})
            ChatNamespace._save_stream_state("tab-2", {"status": "streaming"})
            ChatNamespace._clear_stream_state("tab-1")

        data = json.loads(stream_state.read_text())
        assert "tab-1" not in data
        assert "tab-2" in data

    def test_clear_nonexistent_tab_no_error(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._save_stream_state("tab-1", {"status": "ok"})
            # Clearing a tab that doesn't exist should not raise
            ChatNamespace._clear_stream_state("tab-nonexistent")

        data = json.loads(stream_state.read_text())
        assert "tab-1" in data

    def test_clear_when_no_state_file(self, flask_app, stream_state_dir):
        """Clearing when no state file exists should not raise."""
        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._clear_stream_state("tab-1")
        # No exception = pass

    def test_save_handles_corrupted_state(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        stream_dir.mkdir(parents=True, exist_ok=True)
        stream_state.write_text("not valid json{{{")

        with flask_app.app_context():
            from webhook_server import ChatNamespace
            ChatNamespace._save_stream_state("tab-1", {"status": "ok"})

        data = json.loads(stream_state.read_text())
        assert data["tab-1"]["status"] == "ok"

    def test_clear_handles_corrupted_state(self, flask_app, stream_state_dir):
        stream_dir, stream_state = stream_state_dir
        stream_dir.mkdir(parents=True, exist_ok=True)
        stream_state.write_text("broken json")

        with flask_app.app_context():
            from webhook_server import ChatNamespace
            # Should not raise - corrupted state resets to empty
            ChatNamespace._clear_stream_state("tab-1")


# ── _prepare_prompt ──────────────────────────────────────────────────


class TestPreparePrompt:
    """Tests for _prepare_prompt."""

    def test_no_files_returns_prompt(self, chat_ns):
        result = chat_ns._prepare_prompt("Hello", None)
        assert result == "Hello"

    def test_empty_files_list_returns_prompt(self, chat_ns):
        result = chat_ns._prepare_prompt("Hello", [])
        assert result == "Hello"

    def test_image_file(self, chat_ns):
        files = [{"path": "/tmp/photo.png", "name": "photo.png", "type": "image/png"}]
        result = chat_ns._prepare_prompt("Describe", files)
        assert "[Image attached: /tmp/photo.png]" in result
        assert result.endswith("Describe")

    def test_non_image_file(self, chat_ns):
        files = [{"path": "/tmp/data.csv", "name": "report.csv", "type": "text/csv"}]
        result = chat_ns._prepare_prompt("Analyze", files)
        assert "[File attached: /tmp/data.csv (report.csv)]" in result
        assert result.endswith("Analyze")

    def test_multiple_files(self, chat_ns):
        files = [
            {"path": "/tmp/img.jpg", "name": "img.jpg", "type": "image/jpeg"},
            {"path": "/tmp/doc.pdf", "name": "doc.pdf", "type": "application/pdf"},
        ]
        result = chat_ns._prepare_prompt("Review", files)
        assert "[Image attached: /tmp/img.jpg]" in result
        assert "[File attached: /tmp/doc.pdf (doc.pdf)]" in result
        assert result.endswith("Review")

    def test_no_prompt_with_files_uses_default(self, chat_ns):
        files = [{"path": "/tmp/f.txt", "name": "f.txt", "type": "text/plain"}]
        result = chat_ns._prepare_prompt(None, files)
        assert "Analyze the attached files." in result

    def test_empty_prompt_with_files_uses_default(self, chat_ns):
        files = [{"path": "/tmp/f.txt", "name": "f.txt", "type": "text/plain"}]
        result = chat_ns._prepare_prompt("", files)
        assert "Analyze the attached files." in result

    def test_file_refs_before_prompt(self, chat_ns):
        files = [{"path": "/tmp/x.txt", "name": "x.txt", "type": "text/plain"}]
        result = chat_ns._prepare_prompt("My prompt", files)
        lines = result.split("\n")
        # File reference is on first line, prompt comes after blank line
        assert "[File attached:" in lines[0]
        assert lines[-1] == "My prompt"


# ── _emit_buffered ──────────────────────────────────────────────────


class TestEmitBuffered:
    """Tests for _emit_buffered - buffered event emission."""

    def test_emit_to_subscribed_sockets(self, chat_ns, flask_app_module, flask_app):
        """Events are emitted to all subscribed sockets."""
        tab_id = "tab-emit-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"sock1", "sock2"},
                "buffer": [],
            }
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._emit_buffered(tab_id, "test_event", {"key": "val"})

            assert mock_emit.call_count == 2
            # Check that tab_id is injected
            for call in mock_emit.call_args_list:
                assert call[0][1]["tab_id"] == tab_id
                assert call[0][1]["key"] == "val"

            # Cleanup
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_buffer_capped_at_500(self, chat_ns, flask_app_module, flask_app):
        """Buffer is trimmed to last 500 entries."""
        tab_id = "tab-emit-cap"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "buffer": [{"event": "x", "data": {}}] * 499,
            }
            chat_ns._emit_buffered(tab_id, "evt1", {"a": 1})
            chat_ns._emit_buffered(tab_id, "evt2", {"a": 2})

            buf = flask_app_module.CHAT_SESSIONS[tab_id]["buffer"]
            assert len(buf) == 500
            # Most recent is last
            assert buf[-1]["data"]["a"] == 2

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_emit_no_session_is_noop(self, chat_ns, flask_app_module, flask_app):
        """If tab_id is not in CHAT_SESSIONS, nothing happens."""
        with flask_app.app_context():
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._emit_buffered("nonexistent-tab", "evt", {"x": 1})
            mock_emit.assert_not_called()

    def test_emit_handles_socket_error(self, chat_ns, flask_app_module, flask_app):
        """Disconnected sockets don't crash the emit loop."""
        tab_id = "tab-emit-err"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"sock1", "sock2"},
                "buffer": [],
            }
            with patch.object(flask_app_module.socketio, "emit", side_effect=Exception("disconnected")):
                # Should not raise
                chat_ns._emit_buffered(tab_id, "evt", {"x": 1})

            # Buffer still got the event
            assert len(flask_app_module.CHAT_SESSIONS[tab_id]["buffer"]) == 1
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)


# ── _block_add / _block_update ──────────────────────────────────────


class TestBlockAddUpdate:
    """Tests for _block_add and _block_update."""

    def test_block_add_assigns_sequential_ids(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-blk-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "blocks": [],
                "last_activity_ts": 0,
            }
            with patch.object(flask_app_module.socketio, "emit"):
                chat_ns._block_add(tab_id, {"type": "user", "text": "Hello"})
                chat_ns._block_add(tab_id, {"type": "assistant", "text": "Hi"})

            blocks = flask_app_module.CHAT_SESSIONS[tab_id]["blocks"]
            assert blocks[0]["id"] == 0
            assert blocks[1]["id"] == 1
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_block_add_updates_last_activity(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-blk-ts"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "blocks": [],
                "last_activity_ts": 0,
            }
            with patch.object(flask_app_module.socketio, "emit"):
                chat_ns._block_add(tab_id, {"type": "user", "text": "test"})

            assert flask_app_module.CHAT_SESSIONS[tab_id]["last_activity_ts"] > 0
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_block_add_emits_to_sockets(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-blk-emit"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"s1"},
                "blocks": [],
                "last_activity_ts": 0,
            }
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._block_add(tab_id, {"type": "user", "text": "test"})

            mock_emit.assert_called_once()
            args = mock_emit.call_args[0]
            assert args[0] == "realtime_block_add"
            assert args[1]["block"]["type"] == "user"
            assert args[1]["tab_id"] == tab_id
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_block_add_no_session_is_noop(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._block_add("nonexistent", {"type": "user", "text": "test"})
            mock_emit.assert_not_called()

    def test_block_update_patches_block(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-blk-upd"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "blocks": [{"id": 0, "type": "assistant", "text": "partial"}],
                "last_activity_ts": 0,
            }
            with patch.object(flask_app_module.socketio, "emit"):
                chat_ns._block_update(tab_id, 0, {"text": "full response"})

            assert flask_app_module.CHAT_SESSIONS[tab_id]["blocks"][0]["text"] == "full response"
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_block_update_out_of_range_is_noop(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-blk-oor"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "blocks": [{"id": 0, "type": "user", "text": "test"}],
                "last_activity_ts": 0,
            }
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._block_update(tab_id, 5, {"text": "nope"})
            mock_emit.assert_not_called()
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_block_update_emits_to_sockets(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-blk-upd-emit"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"s1"},
                "blocks": [{"id": 0, "type": "thinking", "text": "hmm"}],
                "last_activity_ts": 0,
            }
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._block_update(tab_id, 0, {"text": "updated"})

            mock_emit.assert_called_once()
            args = mock_emit.call_args[0]
            assert args[0] == "realtime_block_update"
            assert args[1]["id"] == 0
            assert args[1]["patch"] == {"text": "updated"}
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)


# ── _emit_queue_update ──────────────────────────────────────────────


class TestEmitQueueUpdate:
    """Tests for _emit_queue_update."""

    def test_queue_update_emits_to_sockets(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qu-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"s1"},
                "message_queue": [
                    {"prompt": "First message in queue"},
                    {"prompt": "Second message in queue"},
                ],
            }
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._emit_queue_update(tab_id)

            mock_emit.assert_called_once()
            data = mock_emit.call_args[0][1]
            assert len(data["queue"]) == 2
            assert data["queue"][0]["text"] == "First message in queue"[:80]
            assert data["queue"][0]["index"] == 0
            assert data["queue"][1]["index"] == 1
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_queue_update_no_session_is_noop(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._emit_queue_update("nonexistent")
            mock_emit.assert_not_called()

    def test_queue_update_truncates_text(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qu-trunc"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"s1"},
                "message_queue": [
                    {"prompt": "x" * 200},
                ],
            }
            with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                chat_ns._emit_queue_update(tab_id)

            data = mock_emit.call_args[0][1]
            assert len(data["queue"][0]["text"]) == 80
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)


# ── _get_session_process ────────────────────────────────────────────


class TestGetSessionProcess:
    """Tests for _get_session_process."""

    def test_returns_active_process(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-proc-1"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process is alive
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": mock_proc,
                "process_done": False,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock1"] = {tab_id}

            result = chat_ns._get_session_process("sock1")
            assert result is mock_proc

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock1", None)

    def test_returns_none_for_dead_process(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-proc-dead"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Process exited
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": mock_proc,
                "process_done": False,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock1"] = {tab_id}

            result = chat_ns._get_session_process("sock1")
            assert result is None

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock1", None)

    def test_returns_none_for_process_done(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-proc-done"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": mock_proc,
                "process_done": True,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock1"] = {tab_id}

            result = chat_ns._get_session_process("sock1")
            assert result is None

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock1", None)

    def test_returns_none_no_subscription(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            result = chat_ns._get_session_process("unsubscribed-sock")
            assert result is None

    def test_returns_specific_session_process(self, chat_ns, flask_app_module, flask_app):
        tab1, tab2 = "tab-proc-a", "tab-proc-b"
        mock_proc_a = MagicMock()
        mock_proc_a.poll.return_value = None
        mock_proc_b = MagicMock()
        mock_proc_b.poll.return_value = None
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab1] = {"process": mock_proc_a, "process_done": False}
            flask_app_module.CHAT_SESSIONS[tab2] = {"process": mock_proc_b, "process_done": False}
            flask_app_module.SOCKET_TO_SESSIONS["sock1"] = {tab1, tab2}

            result = chat_ns._get_session_process("sock1", session_id=tab1)
            assert result is mock_proc_a

            flask_app_module.CHAT_SESSIONS.pop(tab1, None)
            flask_app_module.CHAT_SESSIONS.pop(tab2, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock1", None)


# ── on_send_message ─────────────────────────────────────────────────


class TestOnSendMessage:
    """Tests for on_send_message event handler."""

    def _mock_request(self, sid):
        mock_req = MagicMock()
        mock_req.sid = sid
        return mock_req

    def test_empty_prompt_emits_error(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-1")):
                with patch("webhook_server.emit") as mock_emit:
                    chat_ns.on_send_message({"prompt": "", "tab_id": "t1", "model": "opus"})
                    mock_emit.assert_called_once_with("error", {"message": "Empty prompt"})

    def test_no_model_emits_error(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-2")):
                with patch("webhook_server.emit") as mock_emit:
                    chat_ns.on_send_message({"prompt": "hello", "tab_id": "t1", "model": ""})
                    mock_emit.assert_called_once_with("error", {"message": "model is required"})

    def test_no_tab_id_emits_error(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-3")):
                with patch("webhook_server.emit") as mock_emit:
                    chat_ns.on_send_message({"prompt": "hello", "model": "opus"})
                    mock_emit.assert_called_once_with("error", {"message": "tab_id required"})

    def test_valid_message_calls_route_and_spawns_thread(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-4")):
                with patch("webhook_server.emit"):
                    with patch.object(chat_ns, "_route_message", return_value=False) as mock_route:
                        with patch("threading.Thread") as mock_thread:
                            mock_thread.return_value.start = MagicMock()
                            chat_ns.on_send_message({
                                "prompt": "hello world",
                                "tab_id": "tab-sm-4",
                                "model": "sonnet",
                            })
                            mock_route.assert_called_once()
                            mock_thread.assert_called_once()
                            mock_thread.return_value.start.assert_called_once()

    def test_valid_message_routed_does_not_spawn_thread(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-5")):
                with patch("webhook_server.emit"):
                    with patch.object(chat_ns, "_route_message", return_value=True) as mock_route:
                        with patch("threading.Thread") as mock_thread:
                            chat_ns.on_send_message({
                                "prompt": "hello",
                                "tab_id": "tab-sm-5",
                                "model": "opus",
                            })
                            mock_route.assert_called_once()
                            mock_thread.assert_not_called()

    def test_files_only_message_is_accepted(self, chat_ns, flask_app_module, flask_app):
        """A message with files but empty prompt should still be accepted."""
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-6")):
                with patch("webhook_server.emit"):
                    with patch.object(chat_ns, "_route_message", return_value=False):
                        with patch("threading.Thread") as mock_thread:
                            mock_thread.return_value.start = MagicMock()
                            chat_ns.on_send_message({
                                "prompt": "",
                                "tab_id": "tab-sm-6",
                                "model": "opus",
                                "files": [{"path": "/tmp/f.txt", "name": "f.txt", "type": "text/plain"}],
                            })
                            # With files, prompt becomes the file ref, so thread should spawn
                            mock_thread.assert_called_once()

    def test_effort_and_mode_defaults(self, chat_ns, flask_app_module, flask_app):
        """Default effort='high' and mode='bypass' are passed through."""
        with flask_app.app_context():
            with patch("webhook_server.request", self._mock_request("sock-sm-7")):
                with patch("webhook_server.emit"):
                    with patch.object(chat_ns, "_route_message", return_value=False) as mock_route:
                        with patch("threading.Thread") as mock_thread:
                            mock_thread.return_value.start = MagicMock()
                            chat_ns.on_send_message({
                                "prompt": "test",
                                "tab_id": "tab-sm-7",
                                "model": "opus",
                            })
                            call_args = mock_thread.call_args
                            # _run_claude args: (sid, prompt, tab_id, resume_session_id, model, effort, mode)
                            assert call_args[1]["args"][5] == "high"  # effort
                            assert call_args[1]["args"][6] == "bypass"  # mode


# ── on_queue_remove ─────────────────────────────────────────────────


class TestOnQueueRemove:
    """Tests for on_queue_remove event handler."""

    def test_remove_valid_index(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qr-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "message_queue": [
                    {"prompt": "msg0"},
                    {"prompt": "msg1"},
                    {"prompt": "msg2"},
                ],
                "socket_sids": set(),
            }
            with patch.object(flask_app_module.socketio, "emit"):
                chat_ns.on_queue_remove({"tab_id": tab_id, "index": 1})

            queue = flask_app_module.CHAT_SESSIONS[tab_id]["message_queue"]
            assert len(queue) == 2
            assert queue[0]["prompt"] == "msg0"
            assert queue[1]["prompt"] == "msg2"
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_remove_out_of_range_index(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qr-2"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "message_queue": [{"prompt": "only"}],
                "socket_sids": set(),
            }
            with patch.object(flask_app_module.socketio, "emit"):
                chat_ns.on_queue_remove({"tab_id": tab_id, "index": 5})

            assert len(flask_app_module.CHAT_SESSIONS[tab_id]["message_queue"]) == 1
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_remove_no_tab_id(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch.object(flask_app_module.socketio, "emit"):
                # Should not raise
                chat_ns.on_queue_remove({"index": 0})

    def test_remove_no_index(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch.object(flask_app_module.socketio, "emit"):
                chat_ns.on_queue_remove({"tab_id": "t1"})


# ── on_draft_save ───────────────────────────────────────────────────


class TestOnDraftSave:
    """Tests for on_draft_save event handler."""

    def test_save_draft_text(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-ds-1")):
                with patch.object(flask_app_module.socketio, "emit"):
                    with patch.object(flask_app_module, "_save_chat_ui_state"):
                        chat_ns.on_draft_save({"session_id": "s1", "text": "my draft"})

            drafts = flask_app_module._chat_ui_state.get("drafts", {})
            assert drafts.get("s1") == "my draft"
            # Cleanup
            drafts.pop("s1", None)

    def test_clear_draft_on_empty_text(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state.setdefault("drafts", {})["s2"] = "old draft"
            with patch("webhook_server.request", MagicMock(sid="sock-ds-2")):
                with patch.object(flask_app_module.socketio, "emit"):
                    with patch.object(flask_app_module, "_save_chat_ui_state"):
                        chat_ns.on_draft_save({"session_id": "s2", "text": ""})

            assert "s2" not in flask_app_module._chat_ui_state.get("drafts", {})

    def test_no_session_id_is_noop(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-ds-3")):
                with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                    chat_ns.on_draft_save({"text": "orphan"})
                mock_emit.assert_not_called()

    def test_none_data_is_noop(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-ds-4")):
                with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                    chat_ns.on_draft_save(None)
                mock_emit.assert_not_called()

    def test_broadcasts_to_other_clients(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-ds-5")):
                with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                    with patch.object(flask_app_module, "_save_chat_ui_state"):
                        chat_ns.on_draft_save({"session_id": "s5", "text": "typed"})

                mock_emit.assert_called_once()
                args, kwargs = mock_emit.call_args
                assert args[0] == "draft_update"
                assert args[1]["session_id"] == "s5"
                assert kwargs["skip_sid"] == "sock-ds-5"
            # Cleanup
            flask_app_module._chat_ui_state.get("drafts", {}).pop("s5", None)


# ── on_resume_stream ────────────────────────────────────────────────


class TestOnResumeStream:
    """Tests for on_resume_stream event handler."""

    def test_resume_replays_buffered_events(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-rs-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "buffer": [
                    {"event": "e1", "data": {"x": 1}},
                    {"event": "e2", "data": {"x": 2}},
                    {"event": "e3", "data": {"x": 3}},
                ],
            }
            with patch("webhook_server.request", MagicMock(sid="sock-rs-1")):
                with patch.object(flask_app_module.socketio, "emit") as mock_emit:
                    chat_ns.on_resume_stream({"tab_id": tab_id, "buffer_offset": 1})

            # Should replay events from offset 1 (2 events)
            assert mock_emit.call_count == 2
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-rs-1", None)

    def test_resume_adds_socket_to_session(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-rs-2"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": set(),
                "buffer": [],
            }
            with patch("webhook_server.request", MagicMock(sid="sock-rs-2")):
                with patch.object(flask_app_module.socketio, "emit"):
                    chat_ns.on_resume_stream({"tab_id": tab_id})

            assert "sock-rs-2" in flask_app_module.CHAT_SESSIONS[tab_id]["socket_sids"]
            assert tab_id in flask_app_module.SOCKET_TO_SESSIONS.get("sock-rs-2", set())
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-rs-2", None)

    def test_resume_no_session_emits_error(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-rs-3")):
                with patch("webhook_server.emit") as mock_emit:
                    chat_ns.on_resume_stream({"tab_id": "nonexistent"})
                    mock_emit.assert_called_once_with("error", {"message": "No active session to resume"})

    def test_resume_no_tab_id_emits_error(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-rs-4")):
                with patch("webhook_server.emit") as mock_emit:
                    chat_ns.on_resume_stream({})
                    mock_emit.assert_called_once_with("error", {"message": "No active session to resume"})


# ── on_remove_active / on_add_active ────────────────────────────────


class TestActiveSessionManagement:
    """Tests for on_remove_active and on_add_active event handlers."""

    def test_remove_active_by_tab_id(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s1"},
                {"tab_id": "t2", "session_id": "s2"},
            ]
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module, "_broadcast_chat_state"):
                    chat_ns.on_remove_active({"tab_id": "t1"})

            assert len(flask_app_module._chat_ui_state["active_sessions"]) == 1
            assert flask_app_module._chat_ui_state["active_sessions"][0]["tab_id"] == "t2"

    def test_remove_active_by_session_id(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s1"},
                {"tab_id": "t2", "session_id": "s2"},
            ]
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module, "_broadcast_chat_state"):
                    chat_ns.on_remove_active({"session_id": "s2"})

            assert len(flask_app_module._chat_ui_state["active_sessions"]) == 1
            assert flask_app_module._chat_ui_state["active_sessions"][0]["session_id"] == "s1"

    def test_remove_active_no_ids_is_noop(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s1"},
            ]
            with patch.object(flask_app_module, "_broadcast_chat_state") as mock_bc:
                chat_ns.on_remove_active({})
            mock_bc.assert_not_called()
            assert len(flask_app_module._chat_ui_state["active_sessions"]) == 1

    def test_add_active_new_session(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = []
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module, "_broadcast_chat_state"):
                    chat_ns.on_add_active({"session_id": "new-session"})

            active = flask_app_module._chat_ui_state["active_sessions"]
            assert len(active) == 1
            assert active[0]["session_id"] == "new-session"
            assert active[0]["tab_id"] is None

    def test_add_active_duplicate_by_session_id(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "existing"},
            ]
            with patch.object(flask_app_module, "_broadcast_chat_state"):
                chat_ns.on_add_active({"session_id": "existing"})

            assert len(flask_app_module._chat_ui_state["active_sessions"]) == 1

    def test_add_active_duplicate_by_tab_id(self, chat_ns, flask_app_module, flask_app):
        """If session_id matches an existing tab_id, it's considered duplicate."""
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = [
                {"tab_id": "same-id", "session_id": None},
            ]
            with patch.object(flask_app_module, "_broadcast_chat_state"):
                chat_ns.on_add_active({"session_id": "same-id"})

            assert len(flask_app_module._chat_ui_state["active_sessions"]) == 1

    def test_add_active_no_session_id_is_noop(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = []
            with patch.object(flask_app_module, "_broadcast_chat_state") as mock_bc:
                chat_ns.on_add_active({})
            mock_bc.assert_not_called()

    def test_add_active_caps_at_20(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            flask_app_module._chat_ui_state["active_sessions"] = [
                {"tab_id": f"t{i}", "session_id": f"s{i}"} for i in range(20)
            ]
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module, "_broadcast_chat_state"):
                    chat_ns.on_add_active({"session_id": "overflow"})

            assert len(flask_app_module._chat_ui_state["active_sessions"]) == 20
            # New session is inserted at front
            assert flask_app_module._chat_ui_state["active_sessions"][0]["session_id"] == "overflow"


# ── on_connect / on_disconnect ──────────────────────────────────────


class TestConnectDisconnect:
    """Tests for on_connect and on_disconnect event handlers."""

    def test_on_connect_emits_chat_state_sync(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-conn-1")):
                with patch("webhook_server.emit") as mock_emit:
                    with patch.object(flask_app_module, "_get_chat_state_snapshot", return_value={"test": True}):
                        chat_ns.on_connect()
                mock_emit.assert_called_once_with("chat_state_sync", {"test": True})

    def test_on_disconnect_removes_socket_from_sessions(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-disc-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"sock-disc-1", "sock-disc-2"},
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-disc-1"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-disc-1")):
                chat_ns.on_disconnect()

            assert "sock-disc-1" not in flask_app_module.CHAT_SESSIONS[tab_id]["socket_sids"]
            assert "sock-disc-2" in flask_app_module.CHAT_SESSIONS[tab_id]["socket_sids"]
            assert "sock-disc-1" not in flask_app_module.SOCKET_TO_SESSIONS

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-disc-2", None)

    def test_on_disconnect_stops_watchers(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            stop_evt = threading.Event()
            flask_app_module.SESSION_WATCHERS["w1"] = {
                "socket_sid": "sock-disc-w",
                "stop": stop_evt,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-disc-w"] = set()

            with patch("webhook_server.request", MagicMock(sid="sock-disc-w")):
                chat_ns.on_disconnect()

            assert stop_evt.is_set()
            assert "w1" not in flask_app_module.SESSION_WATCHERS

    def test_on_disconnect_unsubscribed_socket(self, chat_ns, flask_app_module, flask_app):
        """Disconnecting a socket with no subscriptions is safe."""
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-disc-nobody")):
                chat_ns.on_disconnect()  # Should not raise


# ── on_cancel ───────────────────────────────────────────────────────


class TestOnCancel:
    """Tests for on_cancel event handler."""

    def test_cancel_specific_tab_with_process(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-cancel-1"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "sdk_client": None,
                "sdk_loop": None,
                "process": mock_proc,
                "_detached_pid": None,
                "socket_sids": set(),
                "process_done": False,
            }
            with patch("webhook_server.request", MagicMock(sid="sock-cancel-1")):
                with patch("webhook_server.emit"):
                    with patch.object(flask_app_module, "_broadcast_chat_state"):
                        chat_ns.on_cancel({"tab_id": tab_id})

            mock_proc.terminate.assert_called_once()
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_cancel_all_subscribed(self, chat_ns, flask_app_module, flask_app):
        tab1, tab2 = "tab-cancel-a", "tab-cancel-b"
        proc1 = MagicMock()
        proc1.poll.return_value = None
        proc2 = MagicMock()
        proc2.poll.return_value = None
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab1] = {
                "sdk_client": None, "sdk_loop": None, "process": proc1,
                "_detached_pid": None, "socket_sids": set(), "process_done": False,
            }
            flask_app_module.CHAT_SESSIONS[tab2] = {
                "sdk_client": None, "sdk_loop": None, "process": proc2,
                "_detached_pid": None, "socket_sids": set(), "process_done": False,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-cancel-all"] = {tab1, tab2}

            with patch("webhook_server.request", MagicMock(sid="sock-cancel-all")):
                with patch("webhook_server.emit"):
                    with patch.object(flask_app_module, "_broadcast_chat_state"):
                        chat_ns.on_cancel()

            proc1.terminate.assert_called_once()
            proc2.terminate.assert_called_once()

            flask_app_module.CHAT_SESSIONS.pop(tab1, None)
            flask_app_module.CHAT_SESSIONS.pop(tab2, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-cancel-all", None)

    def test_cancel_emits_cancelled(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-cancel-noop")):
                with patch("webhook_server.emit") as mock_emit:
                    with patch.object(flask_app_module, "_broadcast_chat_state"):
                        chat_ns.on_cancel()
                mock_emit.assert_called_once_with("cancelled", {})


# ── on_detach_all ───────────────────────────────────────────────────


class TestOnDetachAll:
    """Tests for on_detach_all event handler."""

    def test_detach_removes_socket_from_sessions(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-det-1"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "socket_sids": {"sock-det-1", "sock-det-2"},
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-det-1"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-det-1")):
                chat_ns.on_detach_all()

            assert "sock-det-1" not in flask_app_module.CHAT_SESSIONS[tab_id]["socket_sids"]
            assert "sock-det-2" in flask_app_module.CHAT_SESSIONS[tab_id]["socket_sids"]
            assert "sock-det-1" not in flask_app_module.SOCKET_TO_SESSIONS

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)

    def test_detach_no_subscriptions(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-det-none")):
                chat_ns.on_detach_all()  # Should not raise


# ── on_permission_response ──────────────────────────────────────────


class TestOnPermissionResponse:
    """Tests for on_permission_response event handler."""

    def test_allow_writes_y_to_stdin(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-perm-1"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": mock_proc,
                "process_done": False,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-perm-1"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-perm-1")):
                chat_ns.on_permission_response({"allow": True})

            mock_proc.stdin.write.assert_called_once_with(b"y\n")
            mock_proc.stdin.flush.assert_called_once()

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-perm-1", None)

    def test_deny_writes_n_to_stdin(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-perm-2"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": mock_proc,
                "process_done": False,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-perm-2"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-perm-2")):
                chat_ns.on_permission_response({"allow": False})

            mock_proc.stdin.write.assert_called_once_with(b"n\n")

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-perm-2", None)

    def test_no_process_logs_warning(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-perm-none")):
                # Should not raise, just log warning
                chat_ns.on_permission_response({"allow": True})


# ── on_question_response ────────────────────────────────────────────


class TestOnQuestionResponse:
    """Tests for on_question_response event handler."""

    def _make_loop_and_future(self):
        """Create a mock loop that executes call_soon_threadsafe immediately."""
        loop = MagicMock()
        future = MagicMock()
        future.done.return_value = False
        # call_soon_threadsafe(fn, arg) -> fn(arg) immediately
        loop.call_soon_threadsafe = lambda fn, arg: fn(arg)
        return loop, future

    def test_resolves_question_future_with_answers_dict(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qr-1"
        loop, future = self._make_loop_and_future()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process_done": False,
                "_question_future": future,
                "_question_input": {"questions": [{"question": "Q1"}]},
                "sdk_client": MagicMock(),
                "sdk_loop": loop,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-qr-1"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-qr-1")):
                chat_ns.on_question_response({
                    "answers": {"Q1": "A1"},
                    "questions": [{"question": "Q1"}],
                })

            future.set_result.assert_called_once()
            result = future.set_result.call_args[0][0]
            assert result.updated_input["answers"] == {"Q1": "A1"}

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-qr-1", None)

    def test_resolves_with_plain_answer(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qr-2"
        loop, future = self._make_loop_and_future()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process_done": False,
                "_question_future": future,
                "_question_input": {"questions": [{"question": "Pick one"}]},
                "sdk_client": MagicMock(),
                "sdk_loop": loop,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-qr-2"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-qr-2")):
                chat_ns.on_question_response({"answer": "Option B"})

            future.set_result.assert_called_once()
            result = future.set_result.call_args[0][0]
            assert result.updated_input["answers"]["Pick one"] == "Option B"

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-qr-2", None)

    def test_empty_answer_is_noop(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-qr-3"
        loop, future = self._make_loop_and_future()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process_done": False,
                "_question_future": future,
                "_question_input": {"questions": []},
                "sdk_client": MagicMock(),
                "sdk_loop": loop,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-qr-3"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-qr-3")):
                chat_ns.on_question_response({"answer": ""})

            # set_result should NOT have been called
            future.set_result.assert_not_called()

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-qr-3", None)

    def test_fallback_to_client_query(self, chat_ns, flask_app_module, flask_app):
        """When no question_future, falls back to client.query()."""
        tab_id = "tab-qr-4"
        mock_loop = MagicMock()
        mock_client = MagicMock()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process_done": False,
                "sdk_client": mock_client,
                "sdk_loop": mock_loop,
            }
            flask_app_module.SOCKET_TO_SESSIONS["sock-qr-4"] = {tab_id}

            with patch("webhook_server.request", MagicMock(sid="sock-qr-4")):
                with patch("asyncio.run_coroutine_threadsafe") as mock_run:
                    chat_ns.on_question_response({"answer": "fallback answer"})
                    mock_run.assert_called_once()

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-qr-4", None)

    def test_no_active_session_logs_warning(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch("webhook_server.request", MagicMock(sid="sock-qr-none")):
                # Should not raise
                chat_ns.on_question_response({"answer": "test"})

    def test_explicit_tab_id_in_data(self, chat_ns, flask_app_module, flask_app):
        """on_question_response can receive explicit tab_id."""
        tab_id = "tab-qr-explicit"
        loop, future = self._make_loop_and_future()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process_done": False,
                "_question_future": future,
                "_question_input": {"questions": [{"question": "Q?"}]},
                "sdk_client": MagicMock(),
                "sdk_loop": loop,
            }
            # Socket NOT subscribed to this tab_id, but tab_id provided explicitly
            flask_app_module.SOCKET_TO_SESSIONS["sock-qr-exp"] = set()

            with patch("webhook_server.request", MagicMock(sid="sock-qr-exp")):
                chat_ns.on_question_response({
                    "tab_id": tab_id,
                    "answer": "explicit",
                })

            future.set_result.assert_called_once()

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("sock-qr-exp", None)


# ── _route_message ──────────────────────────────────────────────────


class TestRouteMessage:
    """Tests for _route_message - message routing to existing sessions."""

    def test_route_to_idle_session_wakes_it(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-route-idle"
        loop = asyncio.new_event_loop()
        incoming = asyncio.Queue()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": None,
                "sdk_client": MagicMock(),
                "sdk_loop": loop,
                "incoming_queue": incoming,
                "session_idle": True,
                "process_done": False,
                "socket_sids": set(),
                "blocks": [],
            }
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module, "_broadcast_chat_state"):
                    with patch.object(flask_app_module.socketio, "emit"):
                        result = chat_ns._route_message(
                            "hello", tab_id, None, "opus", "high", "bypass", [], socket_sid="s1"
                        )

            assert result is True
            assert flask_app_module.CHAT_SESSIONS[tab_id]["session_idle"] is False

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("s1", None)
            loop.close()

    def test_route_to_busy_session_queues(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-route-busy"
        loop = asyncio.new_event_loop()
        incoming = asyncio.Queue()
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": None,
                "sdk_client": MagicMock(),
                "sdk_loop": loop,
                "incoming_queue": incoming,
                "session_idle": False,
                "process_done": False,
                "socket_sids": set(),
                "blocks": [],
                "message_queue": [],
            }
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module, "_broadcast_chat_state"):
                    with patch.object(flask_app_module.socketio, "emit"):
                        with patch.object(chat_ns, "_block_add"):
                            result = chat_ns._route_message(
                                "queued msg", tab_id, None, "opus", "high", "bypass", [], socket_sid="s1"
                            )

            assert result is True
            assert len(flask_app_module.CHAT_SESSIONS[tab_id]["message_queue"]) == 1
            assert flask_app_module.CHAT_SESSIONS[tab_id]["message_queue"][0]["prompt"] == "queued msg"

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
            flask_app_module.SOCKET_TO_SESSIONS.pop("s1", None)
            loop.close()

    def test_route_returns_false_for_new_session(self, chat_ns, flask_app_module, flask_app):
        with flask_app.app_context():
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module.socketio, "emit"):
                    result = chat_ns._route_message(
                        "new msg", "tab-new-session", None, "opus", "high", "bypass", []
                    )

            assert result is False

    def test_route_returns_false_for_done_session(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-route-done"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process": None,
                "sdk_client": None,
                "process_done": True,
                "incoming_queue": None,
                "socket_sids": set(),
            }
            with patch.object(flask_app_module, "_save_chat_ui_state"):
                with patch.object(flask_app_module.socketio, "emit"):
                    result = chat_ns._route_message(
                        "msg", tab_id, None, "opus", "high", "bypass", []
                    )

            assert result is False
            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)


# ── _run_claude (error handling only) ───────────────────────────────


class TestRunClaudeErrorHandling:
    """Tests for _run_claude error handling (without spawning real sessions)."""

    def test_run_claude_catches_sdk_error(self, chat_ns, flask_app_module, flask_app):
        tab_id = "tab-rc-err"
        with flask_app.app_context():
            flask_app_module.CHAT_SESSIONS[tab_id] = {
                "process_done": False,
                "socket_sids": set(),
                "blocks": [],
                "last_activity_ts": 0,
            }

            with patch.object(chat_ns, "_run_claude_sdk", new_callable=AsyncMock, side_effect=RuntimeError("SDK crashed")):
                with patch.object(chat_ns, "_block_add") as mock_add:
                    with patch.object(chat_ns, "_clear_stream_state"):
                        with patch.object(flask_app_module, "_broadcast_chat_state"):
                            chat_ns._run_claude("sock1", "hello", tab_id, None, "opus")

            # Should have added an error block
            mock_add.assert_called()
            err_block = mock_add.call_args[0][1]
            assert err_block["type"] == "error"
            assert "SDK crashed" in err_block["message"]
            assert flask_app_module.CHAT_SESSIONS[tab_id]["process_done"] is True

            flask_app_module.CHAT_SESSIONS.pop(tab_id, None)
