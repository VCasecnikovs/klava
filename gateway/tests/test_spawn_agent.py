"""Tests for gateway/lib/spawn_agent_tool.py - subagent spawn helpers."""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.spawn_agent_tool import (
    parse_spawn_request,
    format_spawn_result,
    create_subagent_job,
    init_spawn_agent,
    get_spawn_tool_description,
)


class TestParseSpawnRequest:
    def test_valid_json(self):
        text = '<spawn_agent>{"task": "do something", "label": "Test"}</spawn_agent>'
        result = parse_spawn_request(text)
        assert result == {"task": "do something", "label": "Test"}

    def test_multiline(self):
        text = """Some text before
<spawn_agent>
{
    "task": "research thing",
    "label": "Research",
    "model": "haiku"
}
</spawn_agent>
Some text after"""
        result = parse_spawn_request(text)
        assert result["task"] == "research thing"
        assert result["model"] == "haiku"

    def test_no_tag(self):
        text = "No spawn agent tag here"
        assert parse_spawn_request(text) is None

    def test_invalid_json(self):
        text = "<spawn_agent>not json{</spawn_agent>"
        assert parse_spawn_request(text) is None

    def test_empty_tag(self):
        text = "<spawn_agent></spawn_agent>"
        assert parse_spawn_request(text) is None

    def test_with_whitespace(self):
        text = "<spawn_agent>  {\"task\": \"x\"}  </spawn_agent>"
        result = parse_spawn_request(text)
        assert result["task"] == "x"


class TestFormatSpawnResult:
    def test_spawned(self):
        result = {
            "status": "spawned",
            "label": "Research",
            "model": "sonnet",
            "timeout": 600,
            "job_id": "subagent_abc12345",
        }
        formatted = format_spawn_result(result)
        assert "Research" in formatted
        assert "sonnet" in formatted
        assert "10 min" in formatted
        assert "subagent_abc12345" in formatted

    def test_rejected(self):
        result = {
            "status": "rejected",
            "reason": "Max concurrent sub-agents (3) reached",
            "active_count": 3,
        }
        formatted = format_spawn_result(result)
        assert "3" in formatted
        assert "reached" in formatted

    def test_error(self):
        result = {
            "status": "error",
            "error": "SDK crash",
        }
        formatted = format_spawn_result(result)
        assert "SDK crash" in formatted

    def test_spawned_defaults(self):
        result = {
            "status": "spawned",
            "job_id": "test",
        }
        formatted = format_spawn_result(result)
        assert "Task" in formatted  # default label
        assert "sonnet" in formatted  # default model

    def test_unknown_status(self):
        result = {"status": "unknown", "error": "something"}
        formatted = format_spawn_result(result)
        assert "something" in formatted


class TestCreateSubagentJob:
    @patch("lib.spawn_agent_tool._config", {"announce_topic": 100001, "announce_mode": "agent_turn"})
    def test_basic_job(self):
        job = create_subagent_job(task="Do research", label="Research")
        assert job["name"] == "Sub-agent: Research"
        assert job["enabled"] is True
        assert job["type"] == "subagent"
        assert job["execution"]["prompt_template"] == "Do research"
        assert job["delete_after_run"] is True
        assert job["id"].startswith("subagent_")

    @patch("lib.spawn_agent_tool._config", {})
    @patch("lib.spawn_agent_tool.DEFAULT_MODEL", "sonnet")
    @patch("lib.spawn_agent_tool.DEFAULT_TIMEOUT", 600)
    def test_defaults(self):
        job = create_subagent_job(task="test")
        assert job["execution"]["model"] == "sonnet"
        assert job["execution"]["timeout_seconds"] == 600
        assert job["execution"]["allowedTools"] == ["*"]

    @patch("lib.spawn_agent_tool._config", {})
    def test_custom_params(self):
        job = create_subagent_job(
            task="complex task",
            label="Complex",
            model="opus",
            timeout_seconds=1200,
            tools=["Bash", "Read"],
            origin_topic=100002,
            announce_mode="full_output",
        )
        assert job["execution"]["model"] == "opus"
        assert job["execution"]["timeout_seconds"] == 1200
        assert job["execution"]["allowedTools"] == ["Bash", "Read"]
        assert job["announce"]["topic_id"] == 100002
        assert job["announce"]["mode"] == "full_output"

    @patch("lib.spawn_agent_tool._config", {})
    def test_unique_ids(self):
        job1 = create_subagent_job(task="a")
        job2 = create_subagent_job(task="b")
        assert job1["id"] != job2["id"]


class TestInitSpawnAgent:
    @patch("lib.spawn_agent_tool.init_subagent_state")
    def test_loads_config(self, mock_init_state):
        config = {
            "subagents": {
                "default_model": "opus",
                "default_timeout": 900,
                "max_concurrent": 5,
            }
        }
        init_spawn_agent(config)
        # Check globals were set
        from lib.spawn_agent_tool import DEFAULT_MODEL, DEFAULT_TIMEOUT, MAX_CONCURRENT
        assert DEFAULT_MODEL == "opus"
        assert DEFAULT_TIMEOUT == 900
        assert MAX_CONCURRENT == 5
        mock_init_state.assert_called_once_with(config)

    @patch("lib.spawn_agent_tool.init_subagent_state")
    def test_empty_config(self, mock_init_state):
        init_spawn_agent({})
        from lib.spawn_agent_tool import DEFAULT_MODEL, DEFAULT_TIMEOUT, MAX_CONCURRENT
        assert DEFAULT_MODEL == "sonnet"
        assert DEFAULT_TIMEOUT == 600
        assert MAX_CONCURRENT == 3


class TestGetSpawnToolDescription:
    def test_returns_description(self):
        desc = get_spawn_tool_description()
        assert "spawn_agent" in desc
        assert "task" in desc
        assert "label" in desc
        assert "model" in desc


class TestFeedModule:
    """Tests for gateway/lib/feed.py"""

    def test_topic_constants(self):
        from lib.feed import TOPIC_NAMES, TOPIC_IDS
        assert TOPIC_NAMES[100001] == "Heartbeat"
        assert TOPIC_IDS["Heartbeat"] == 100001
        assert TOPIC_IDS["Alerts"] == 100006

    def test_get_tg_config_loads(self, tmp_path, monkeypatch):
        from lib import feed
        # Reset cache
        feed._tg_config = None
        monkeypatch.delenv("TG_BOT_TOKEN", raising=False)

        config_file = tmp_path / "settings.json"
        config = {
            "telegram": {
                "bot_token": "test-token",
                "allowed_users": [12345],
            }
        }
        config_file.write_text(json.dumps(config))

        # Patch expanduser to point to our test settings
        orig_expanduser = os.path.expanduser
        def mock_expanduser(path):
            if "settings.json" in path:
                return str(config_file)
            return orig_expanduser(path)

        monkeypatch.setattr("os.path.expanduser", mock_expanduser)
        result = feed._get_tg_config()
        assert result["bot_token"] == "test-token"
        assert result["chat_id"] == 12345

        # Reset for other tests
        feed._tg_config = None

    def test_get_tg_config_missing_file(self, tmp_path, monkeypatch):
        from lib import feed
        feed._tg_config = None
        monkeypatch.delenv("TG_BOT_TOKEN", raising=False)

        orig_expanduser = os.path.expanduser
        def mock_expanduser(path):
            if "settings.json" in path:
                return str(tmp_path / "nonexistent.json")
            return orig_expanduser(path)

        monkeypatch.setattr("os.path.expanduser", mock_expanduser)
        result = feed._get_tg_config()
        assert result["bot_token"] == ""
        assert result["chat_id"] == 0

        feed._tg_config = None

    def test_write_log(self, tmp_path, monkeypatch):
        from lib import feed
        log_path = str(tmp_path / "feed" / "messages.jsonl")
        monkeypatch.setattr(feed, "FEED_LOG", log_path)

        feed._write_log("test message", "Heartbeat", 100001, "HTML", "job1", "sess1", None)

        with open(log_path) as f:
            entry = json.loads(f.read().strip())
        assert entry["message"] == "test message"
        assert entry["topic"] == "Heartbeat"
        assert entry["job_id"] == "job1"
        assert entry["session_id"] == "sess1"

    def test_write_log_with_deltas(self, tmp_path, monkeypatch):
        from lib import feed
        log_path = str(tmp_path / "feed" / "messages.jsonl")
        monkeypatch.setattr(feed, "FEED_LOG", log_path)

        deltas = [{"type": "new_deal", "name": "Acme"}]
        feed._write_log("msg", "Heartbeat", 100001, None, None, None, deltas)

        with open(log_path) as f:
            entry = json.loads(f.read().strip())
        assert entry["deltas"] == deltas

    @patch("lib.feed._send_telegram")
    def test_send_feed_with_telegram(self, mock_tg, tmp_path, monkeypatch):
        from lib import feed
        log_path = str(tmp_path / "feed" / "messages.jsonl")
        monkeypatch.setattr(feed, "FEED_LOG", log_path)

        feed.send_feed("test", topic="Heartbeat", telegram=True)
        mock_tg.assert_called_once()

    @patch("lib.feed._send_telegram")
    def test_send_feed_without_telegram(self, mock_tg, tmp_path, monkeypatch):
        from lib import feed
        log_path = str(tmp_path / "feed" / "messages.jsonl")
        monkeypatch.setattr(feed, "FEED_LOG", log_path)

        feed.send_feed("test", topic="Heartbeat", telegram=False)
        mock_tg.assert_not_called()

    @patch("lib.feed._send_telegram")
    def test_send_feed_unknown_topic_no_telegram(self, mock_tg, tmp_path, monkeypatch):
        from lib import feed
        log_path = str(tmp_path / "feed" / "messages.jsonl")
        monkeypatch.setattr(feed, "FEED_LOG", log_path)

        feed.send_feed("test", topic="UnknownTopic", telegram=True)
        mock_tg.assert_not_called()  # No topic_id mapping
