"""Tests for gateway/routes/agents.py - Agent Hub API routes."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask
from routes.agents import agents_bp, _load_subagent_state, _subagent_to_agent


@pytest.fixture
def app():
    app = Flask(__name__)
    app.register_blueprint(agents_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestLoadSubagentState:
    def test_returns_default_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", tmp_path / "nonexistent.json")
        state = _load_subagent_state()
        assert state == {"active": {}, "pending_announces": [], "last_updated": None}

    def test_loads_valid_json(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"active": {"j1": {"status": "running"}}, "pending_announces": [], "last_updated": "now"}))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        state = _load_subagent_state()
        assert "j1" in state["active"]

    def test_handles_corrupt_json(self, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text("not json{{{")
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        state = _load_subagent_state()
        assert state == {"active": {}, "pending_announces": [], "last_updated": None}


class TestSubagentToAgent:
    def test_basic_conversion(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        sub = {
            "status": "running",
            "session_id": "sess-1",
            "started_at": "2026-03-16T10:00:00+00:00",
            "job": {
                "name": "test-job",
                "execution": {"model": "opus"},
            },
        }
        result = _subagent_to_agent("job-123", sub)
        assert result["id"] == "job-123"
        assert result["name"] == "test-job"
        assert result["type"] == "dispatch"
        assert result["status"] == "running"
        assert result["model"] == "opus"
        assert result["session_id"] == "sess-1"

    def test_default_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        result = _subagent_to_agent("abcd12345678", {"job": {}})
        assert result["name"] == "dispatch-12345678"

    def test_reads_output_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        (tmp_path / "j1.out").write_text("line 1\nline 2\nline 3")
        result = _subagent_to_agent("j1", {"job": {}})
        assert result["output_lines"] == 3
        assert result["last_output"] == "line 3"

    def test_no_output_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        result = _subagent_to_agent("j1", {"job": {}})
        assert result["output_lines"] == 0
        assert result["last_output"] == ""

    def test_invalid_started_at(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        result = _subagent_to_agent("j1", {"job": {}, "started_at": "invalid"})
        assert result["started"] is None

    def test_failure_reason(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        result = _subagent_to_agent("j1", {"job": {}, "failure_reason": "OOM"})
        assert result["error"] == "OOM"


class TestApiAgentsList:
    def test_empty_state(self, client, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", Path("/tmp/nonexistent_state.json"))
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", Path("/tmp/nonexistent_dir"))
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agents"] == []
        assert data["max_concurrent"] == 3

    def test_with_active_agents(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "running", "job": {"name": "test"}}},
            "pending_announces": [],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        resp = client.get("/api/agents")
        data = resp.get_json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "test"

    def test_with_pending_announces(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {},
            "pending_announces": [{"job_id": "j2", "subagent": {"job": {"name": "announce-job"}}}],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        resp = client.get("/api/agents")
        data = resp.get_json()
        assert len(data["agents"]) == 1

    def test_reads_max_concurrent_from_config(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"active": {}, "pending_announces": []}))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        config_dir = tmp_path / "gateway"
        config_dir.mkdir()
        import yaml
        (config_dir / "config.yaml").write_text(yaml.dump({"subagents": {"max_concurrent": 5}}))
        monkeypatch.setattr("routes.agents.CLAUDE_DIR", tmp_path)
        resp = client.get("/api/agents")
        data = resp.get_json()
        assert data["max_concurrent"] == 5


class TestApiAgentDetail:
    def test_not_found(self, client, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", Path("/tmp/nonexistent.json"))
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", Path("/tmp/nonexistent_dir"))
        resp = client.get("/api/agents/unknown")
        assert resp.status_code == 404

    def test_found_in_active(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "running", "job": {"name": "test"}}},
            "pending_announces": [],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        resp = client.get("/api/agents/j1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "test"
        assert "output" in data
        assert "todos" in data

    def test_found_in_pending(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {},
            "pending_announces": [{"job_id": "j2", "subagent": {"job": {"name": "pending-job"}}}],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        resp = client.get("/api/agents/j2")
        assert resp.status_code == 200

    def test_reads_json_output(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "completed", "job": {}}},
            "pending_announces": [],
        }))
        (tmp_path / "j1.out").write_text(json.dumps({
            "result": "Line1\nLine2",
            "todos": [{"text": "Fix bug", "status": "pending"}],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        resp = client.get("/api/agents/j1")
        data = resp.get_json()
        assert len(data["todos"]) == 1
        assert len(data["output"]) == 2

    def test_reads_plain_output(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "completed", "job": {}}},
            "pending_announces": [],
        }))
        (tmp_path / "j1.out").write_text("plain line 1\nplain line 2")
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        resp = client.get("/api/agents/j1")
        data = resp.get_json()
        assert len(data["output"]) == 2


class TestApiAgentKill:
    def test_not_found(self, client, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", Path("/tmp/nonexistent.json"))
        resp = client.post("/api/agents/unknown/kill")
        assert resp.status_code == 404

    def test_kill_success(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "running", "pid": 99999, "job": {}}},
            "pending_announces": [],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None
            resp = client.post("/api/agents/j1/kill")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "killed"

    def test_kill_not_running(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "running", "pid": 99999, "job": {}}},
            "pending_announces": [],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        with patch("os.kill", side_effect=ProcessLookupError):
            resp = client.post("/api/agents/j1/kill")
            data = resp.get_json()
            assert data["status"] == "not_running"

    def test_no_pid(self, client, tmp_path, monkeypatch):
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "active": {"j1": {"status": "running", "job": {}}},
            "pending_announces": [],
        }))
        monkeypatch.setattr("routes.agents.SUBAGENT_STATE_FILE", state_file)
        resp = client.post("/api/agents/j1/kill")
        data = resp.get_json()
        assert data["status"] == "no_pid"
