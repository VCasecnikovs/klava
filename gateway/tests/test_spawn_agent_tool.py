"""Tests for gateway/lib/spawn_agent_tool.py - pure functions only."""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.spawn_agent_tool import (
    create_subagent_job,
    parse_spawn_request,
    format_spawn_result,
    get_spawn_tool_description,
    init_spawn_agent,
)


class TestCreateSubagentJob:
    def test_default_fields(self):
        job = create_subagent_job(task="Do something")
        assert job["id"].startswith("subagent_")
        assert job["name"] == "Sub-agent: Task"
        assert job["enabled"] is True
        assert job["type"] == "subagent"
        assert job["schedule"]["type"] == "immediate"
        assert job["execution"]["prompt_template"] == "Do something"
        assert job["execution"]["mode"] == "isolated"
        assert job["delete_after_run"] is True

    def test_custom_label(self):
        job = create_subagent_job(task="Research", label="Web Research")
        assert job["name"] == "Sub-agent: Web Research"

    def test_custom_model(self):
        job = create_subagent_job(task="Think hard", model="opus")
        assert job["execution"]["model"] == "opus"

    def test_custom_timeout(self):
        job = create_subagent_job(task="Quick task", timeout_seconds=60)
        assert job["execution"]["timeout_seconds"] == 60

    def test_custom_tools(self):
        job = create_subagent_job(task="Read only", tools=["Read", "Grep"])
        assert job["execution"]["allowedTools"] == ["Read", "Grep"]

    def test_origin_topic(self):
        job = create_subagent_job(task="Task", origin_topic=12345)
        assert job["announce"]["topic_id"] == 12345

    def test_announce_mode(self):
        job = create_subagent_job(task="Task", announce_mode="direct")
        assert job["announce"]["mode"] == "direct"

    def test_unique_ids(self):
        j1 = create_subagent_job(task="A")
        j2 = create_subagent_job(task="B")
        assert j1["id"] != j2["id"]


class TestParseSpawnRequest:
    def test_valid_json(self):
        text = 'some text <spawn_agent>{"task": "hello", "label": "test"}</spawn_agent> more'
        result = parse_spawn_request(text)
        assert result["task"] == "hello"
        assert result["label"] == "test"

    def test_no_tag(self):
        assert parse_spawn_request("no spawn tag here") is None

    def test_invalid_json(self):
        text = '<spawn_agent>not json at all</spawn_agent>'
        assert parse_spawn_request(text) is None

    def test_multiline(self):
        text = '''<spawn_agent>
{
    "task": "Research topic",
    "model": "opus"
}
</spawn_agent>'''
        result = parse_spawn_request(text)
        assert result["task"] == "Research topic"
        assert result["model"] == "opus"

    def test_whitespace_handling(self):
        text = '<spawn_agent>  {"task": "test"}  </spawn_agent>'
        result = parse_spawn_request(text)
        assert result["task"] == "test"


class TestFormatSpawnResult:
    def test_spawned(self):
        result = format_spawn_result({
            "status": "spawned",
            "label": "Research",
            "model": "sonnet",
            "timeout": 600,
            "job_id": "subagent_abc123",
        })
        assert "запущен" in result
        assert "Research" in result
        assert "sonnet" in result
        assert "10 min" in result
        assert "subagent_abc123" in result

    def test_rejected(self):
        result = format_spawn_result({
            "status": "rejected",
            "reason": "Too many running",
            "active_count": 3,
        })
        assert "отклонён" in result
        assert "Too many running" in result

    def test_error(self):
        result = format_spawn_result({
            "status": "error",
            "error": "Connection failed",
        })
        assert "Ошибка" in result
        assert "Connection failed" in result


class TestGetSpawnToolDescription:
    def test_returns_string(self):
        desc = get_spawn_tool_description()
        assert "spawn_agent" in desc
        assert "task" in desc
        assert "model" in desc


class TestInitSpawnAgent:
    def test_sets_defaults(self):
        config = {
            "subagents": {
                "default_model": "opus",
                "default_timeout": 300,
                "max_concurrent": 5,
            }
        }
        with patch("lib.spawn_agent_tool.init_subagent_state"):
            init_spawn_agent(config)

        from lib.spawn_agent_tool import DEFAULT_MODEL, DEFAULT_TIMEOUT, MAX_CONCURRENT
        assert DEFAULT_MODEL == "opus"
        assert DEFAULT_TIMEOUT == 300
        assert MAX_CONCURRENT == 5

    def test_empty_config(self):
        with patch("lib.spawn_agent_tool.init_subagent_state"):
            init_spawn_agent({})

        from lib.spawn_agent_tool import DEFAULT_MODEL, DEFAULT_TIMEOUT, MAX_CONCURRENT
        assert DEFAULT_MODEL == "sonnet"
        assert DEFAULT_TIMEOUT == 600
        assert MAX_CONCURRENT == 3
