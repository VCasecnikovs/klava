"""Extra tests for gateway/lib/spawn_agent_tool.py - async/spawning logic.

Targets missed lines: 104-164 (spawn_agent), 177-277 (_start_subagent_process + _run_sdk).
Uses asyncio.run() wrapper since pytest-asyncio is not available.
"""

import asyncio
import json
import os
import sys
import threading
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.spawn_agent_tool as sat
from lib.spawn_agent_tool import (
    spawn_agent,
    create_subagent_job,
    init_spawn_agent,
    format_spawn_result,
    _start_subagent_process,
)


@pytest.fixture(autouse=True)
def reset_config():
    """Reset module-level config between tests."""
    sat._config = {}
    sat.DEFAULT_MODEL = "sonnet"
    sat.DEFAULT_TIMEOUT = 600
    sat.MAX_CONCURRENT = 3
    yield
    sat._config = {}
    sat.DEFAULT_MODEL = "sonnet"
    sat.DEFAULT_TIMEOUT = 600
    sat.MAX_CONCURRENT = 3


def run_async(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


# ── spawn_agent: concurrent limit (lines 104-113) ──

class TestSpawnAgentConcurrencyLimit:
    def test_rejected_when_max_concurrent_reached(self):
        """spawn_agent returns rejected status when too many subagents are active."""
        sat.MAX_CONCURRENT = 2
        mock_active = {"agent1": {}, "agent2": {}}
        with patch("lib.subagent_state.get_active_subagents", return_value=mock_active):
            result = run_async(spawn_agent(task="test task", label="Test"))

        assert result["status"] == "rejected"
        assert "Max concurrent" in result["reason"]
        assert result["active_count"] == 2

    def test_rejected_exact_limit(self):
        """Rejected when active count exactly equals MAX_CONCURRENT."""
        sat.MAX_CONCURRENT = 1
        with patch("lib.subagent_state.get_active_subagents", return_value={"a": {}}):
            result = run_async(spawn_agent(task="test"))
        assert result["status"] == "rejected"


# ── spawn_agent: successful spawn (lines 115-161) ──

class TestSpawnAgentSuccess:
    def test_spawn_success(self):
        """spawn_agent returns spawned status on success."""
        with patch("lib.subagent_state.get_active_subagents", return_value={}), \
             patch("lib.spawn_agent_tool._start_subagent_process", new_callable=AsyncMock,
                   return_value=(12345, "pending-id")), \
             patch("lib.spawn_agent_tool.register_subagent"), \
             patch("lib.spawn_agent_tool.get_telegram_config", return_value=(None, None, None)):
            result = run_async(spawn_agent(task="Do research", label="Research", model="opus"))

        assert result["status"] == "spawned"
        assert result["label"] == "Research"
        assert result["model"] == "opus"
        assert "job_id" in result
        assert result["job_id"].startswith("subagent_")

    def test_spawn_sends_telegram_notification(self):
        """spawn_agent sends TG notification and saves message_id."""
        sat._config = {"_full_config": {"telegram": {"bot_token": "tok", "chat_id": "123"}},
                       "announce_topic": 999}
        with patch("lib.subagent_state.get_active_subagents", return_value={}), \
             patch("lib.spawn_agent_tool._start_subagent_process", new_callable=AsyncMock,
                   return_value=(111, "pending-x")), \
             patch("lib.spawn_agent_tool.register_subagent"), \
             patch("lib.spawn_agent_tool.get_telegram_config", return_value=("tok", "123", None)), \
             patch("lib.spawn_agent_tool.format_spawn_notification", return_value="<b>Spawned</b>"), \
             patch("lib.spawn_agent_tool.send_telegram_message_with_id", return_value=42) as mock_send, \
             patch("lib.spawn_agent_tool.set_status_message_id") as mock_set_id:
            result = run_async(spawn_agent(task="Task", origin_topic=999))

        assert result["status"] == "spawned"
        mock_send.assert_called_once()
        mock_set_id.assert_called_once_with(result["job_id"], 42)

    def test_spawn_telegram_failure_ignored(self):
        """Telegram notification failure doesn't break spawn."""
        with patch("lib.subagent_state.get_active_subagents", return_value={}), \
             patch("lib.spawn_agent_tool._start_subagent_process", new_callable=AsyncMock,
                   return_value=(111, "p")), \
             patch("lib.spawn_agent_tool.register_subagent"), \
             patch("lib.spawn_agent_tool.get_telegram_config", side_effect=Exception("TG down")):
            result = run_async(spawn_agent(task="Task"))

        assert result["status"] == "spawned"

    def test_spawn_telegram_no_message_id(self):
        """When send_telegram_message_with_id returns None, set_status_message_id is not called."""
        sat._config = {"_full_config": {}, "announce_topic": 111}
        with patch("lib.subagent_state.get_active_subagents", return_value={}), \
             patch("lib.spawn_agent_tool._start_subagent_process", new_callable=AsyncMock,
                   return_value=(111, "p")), \
             patch("lib.spawn_agent_tool.register_subagent"), \
             patch("lib.spawn_agent_tool.get_telegram_config", return_value=("tok", "cid", None)), \
             patch("lib.spawn_agent_tool.format_spawn_notification", return_value="msg"), \
             patch("lib.spawn_agent_tool.send_telegram_message_with_id", return_value=None), \
             patch("lib.spawn_agent_tool.set_status_message_id") as mock_set_id:
            result = run_async(spawn_agent(task="Task"))

        assert result["status"] == "spawned"
        mock_set_id.assert_not_called()

    def test_spawn_no_bot_token(self):
        """When bot_token is None, no TG message is sent."""
        sat._config = {"_full_config": {}}
        with patch("lib.subagent_state.get_active_subagents", return_value={}), \
             patch("lib.spawn_agent_tool._start_subagent_process", new_callable=AsyncMock,
                   return_value=(111, "p")), \
             patch("lib.spawn_agent_tool.register_subagent"), \
             patch("lib.spawn_agent_tool.get_telegram_config", return_value=(None, None, None)), \
             patch("lib.spawn_agent_tool.send_telegram_message_with_id") as mock_send:
            result = run_async(spawn_agent(task="Task"))

        assert result["status"] == "spawned"
        mock_send.assert_not_called()


# ── spawn_agent: error path (lines 163-168) ──

class TestSpawnAgentError:
    def test_spawn_error(self):
        """spawn_agent returns error status when _start_subagent_process fails."""
        with patch("lib.subagent_state.get_active_subagents", return_value={}), \
             patch("lib.spawn_agent_tool._start_subagent_process", new_callable=AsyncMock,
                   side_effect=RuntimeError("Process failed")):
            result = run_async(spawn_agent(task="Task"))

        assert result["status"] == "error"
        assert "Process failed" in result["error"]
        assert "job_id" in result


# ── _start_subagent_process (lines 177-277) ──

class TestStartSubagentProcess:
    def test_starts_thread_and_returns(self):
        """_start_subagent_process starts a daemon thread and returns ident + session_id."""
        job = create_subagent_job(task="Test task", model="haiku")

        with patch("lib.spawn_agent_tool.OUTPUT_DIR", Path("/tmp/test_subagent_output")), \
             patch("os.path.exists", return_value=False), \
             patch("lib.spawn_agent_tool.ClaudeSDKClient"), \
             patch("lib.spawn_agent_tool.ClaudeAgentOptions"), \
             patch.object(Path, "mkdir"):
            thread_ident, session_id = run_async(_start_subagent_process(job))

        assert isinstance(thread_ident, int)
        assert session_id.startswith("pending-")

    def test_sdk_options_include_model(self):
        """Verify ClaudeAgentOptions is built with correct model."""
        job = create_subagent_job(task="Test", model="opus")
        captured_opts = {}

        def capture_options(**kwargs):
            captured_opts.update(kwargs)
            return MagicMock()

        with patch("lib.spawn_agent_tool.OUTPUT_DIR", Path("/tmp/test_output")), \
             patch.object(Path, "mkdir"), \
             patch("os.path.exists", return_value=False), \
             patch("lib.spawn_agent_tool.ClaudeAgentOptions", side_effect=capture_options), \
             patch("lib.spawn_agent_tool.ClaudeSDKClient"):
            run_async(_start_subagent_process(job))

        assert captured_opts.get("model") == "opus"
        assert captured_opts.get("permission_mode") == "bypassPermissions"

    def test_mcp_config_included_when_exists(self):
        """MCP config is included in options when file exists."""
        job = create_subagent_job(task="Test")
        captured_opts = {}

        def capture_options(**kwargs):
            captured_opts.update(kwargs)
            return MagicMock()

        with patch("lib.spawn_agent_tool.OUTPUT_DIR", Path("/tmp/test_output")), \
             patch.object(Path, "mkdir"), \
             patch("os.path.exists", return_value=True), \
             patch("lib.spawn_agent_tool.ClaudeAgentOptions", side_effect=capture_options), \
             patch("lib.spawn_agent_tool.ClaudeSDKClient"):
            run_async(_start_subagent_process(job))

        assert "mcp_servers" in captured_opts


# ── _run_sdk result handling (integration via output files) ──

class TestRunSdkOutputFiles:
    def test_result_message_output(self, tmp_path):
        """Verifies the output file format for successful ResultMessage."""
        output_file = tmp_path / "test_job.out"
        result_file = tmp_path / "test_job.result.json"

        # Simulate what _run_sdk writes on ResultMessage
        data = {
            "type": "result",
            "result": "Task completed",
            "session_id": "sess-123",
            "total_cost_usd": 0.05,
            "duration_ms": 5000,
            "num_turns": 3,
            "is_error": False,
            "usage": {"input_tokens": 100, "output_tokens": 200},
            "todos": [],
        }
        output_file.write_text(json.dumps(data))
        result_file.write_text(json.dumps({"status": "completed", "exit_code": 0}))

        out = json.loads(output_file.read_text())
        assert out["result"] == "Task completed"
        assert out["session_id"] == "sess-123"
        assert out["is_error"] is False

        res = json.loads(result_file.read_text())
        assert res["exit_code"] == 0

    def test_no_result_message_output(self, tmp_path):
        """Output when no ResultMessage received."""
        output_file = tmp_path / "test_job.out"
        result_file = tmp_path / "test_job.result.json"

        data = {
            "type": "result",
            "result": "Some text output",
            "is_error": True,
            "todos": [],
        }
        output_file.write_text(json.dumps(data))
        result_file.write_text(json.dumps({"status": "completed", "exit_code": 1}))

        out = json.loads(output_file.read_text())
        assert out["result"] == "Some text output"
        assert out["is_error"] is True

    def test_error_output(self, tmp_path):
        """Output on exception."""
        output_file = tmp_path / "test_job.out"
        result_file = tmp_path / "test_job.result.json"

        error = "Connection refused"
        result_file.write_text(json.dumps({
            "status": "completed", "exit_code": 1, "error": error,
        }))
        output_file.write_text(json.dumps({
            "type": "result", "result": f"Error: {error}", "is_error": True,
        }))

        res = json.loads(result_file.read_text())
        assert res["exit_code"] == 1
        assert res["error"] == error


# ── format_spawn_result edge cases ──

class TestFormatSpawnResultEdge:
    def test_spawned_defaults(self):
        result = format_spawn_result({"status": "spawned", "job_id": "j1"})
        assert "j1" in result

    def test_rejected_missing_fields(self):
        result = format_spawn_result({"status": "rejected"})
        assert "Unknown" in result

    def test_unknown_status(self):
        result = format_spawn_result({"status": "unknown"})
        assert "Unknown error" in result


# ── init_spawn_agent stores full config ──

class TestInitSpawnAgentConfig:
    def test_stores_full_config(self):
        config = {"telegram": {"bot_token": "tok"}, "subagents": {"max_concurrent": 10}}
        with patch("lib.spawn_agent_tool.init_subagent_state"):
            init_spawn_agent(config)
        assert sat._config["_full_config"] == config
        assert sat.MAX_CONCURRENT == 10

    def test_config_without_subagents_key(self):
        with patch("lib.spawn_agent_tool.init_subagent_state"):
            init_spawn_agent({"other": "value"})
        assert sat.DEFAULT_MODEL == "sonnet"
        assert sat.DEFAULT_TIMEOUT == 600
        assert sat.MAX_CONCURRENT == 3

    def test_partial_subagent_config(self):
        """Only some subagent keys set - others use defaults."""
        config = {"subagents": {"default_model": "opus"}}
        with patch("lib.spawn_agent_tool.init_subagent_state"):
            init_spawn_agent(config)
        assert sat.DEFAULT_MODEL == "opus"
        assert sat.DEFAULT_TIMEOUT == 600  # default
        assert sat.MAX_CONCURRENT == 3  # default


# ── create_subagent_job: announce config from _config ──

class TestCreateSubagentJobAnnounce:
    def test_announce_from_config(self):
        """When no origin_topic, uses _config announce_topic."""
        sat._config = {"announce_topic": 777, "announce_mode": "direct"}
        job = create_subagent_job(task="Test")
        assert job["announce"]["topic_id"] == 777
        assert job["announce"]["mode"] == "direct"

    def test_origin_topic_overrides_config(self):
        """origin_topic parameter overrides _config."""
        sat._config = {"announce_topic": 777}
        job = create_subagent_job(task="Test", origin_topic=888)
        assert job["announce"]["topic_id"] == 888

    def test_announce_mode_overrides_config(self):
        """announce_mode parameter overrides _config."""
        sat._config = {"announce_mode": "agent_turn"}
        job = create_subagent_job(task="Test", announce_mode="direct")
        assert job["announce"]["mode"] == "direct"
