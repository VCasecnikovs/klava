"""Tests for gateway/lib/session_registry.py - JSONL session tracking."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import session_registry


@pytest.fixture(autouse=True)
def isolate_registry(tmp_path, monkeypatch):
    """Redirect registry file to tmp_path."""
    monkeypatch.setattr(session_registry, "REGISTRY_FILE", tmp_path / "registry.jsonl")


class TestRegisterSession:
    def test_creates_file_and_appends(self, tmp_path):
        session_registry.register_session("uuid-1", "cron", job_id="heartbeat")
        f = tmp_path / "registry.jsonl"
        assert f.exists()
        entry = json.loads(f.read_text().strip())
        assert entry["session_id"] == "uuid-1"
        assert entry["type"] == "cron"
        assert entry["job_id"] == "heartbeat"
        assert "ts" in entry

    def test_appends_multiple(self, tmp_path):
        session_registry.register_session("uuid-1", "cron")
        session_registry.register_session("uuid-2", "user")
        lines = (tmp_path / "registry.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2

    def test_skips_empty_session_id(self, tmp_path):
        session_registry.register_session("", "cron")
        session_registry.register_session(None, "cron")
        assert not (tmp_path / "registry.jsonl").exists()

    def test_includes_optional_fields(self, tmp_path):
        session_registry.register_session(
            "uuid-1", "cron", job_id="hb", model="sonnet", run_id="run-1", source="test"
        )
        entry = json.loads((tmp_path / "registry.jsonl").read_text().strip())
        assert entry["model"] == "sonnet"
        assert entry["run_id"] == "run-1"
        assert entry["source"] == "test"

    def test_omits_none_optional_fields(self, tmp_path):
        session_registry.register_session("uuid-1", "cron")
        entry = json.loads((tmp_path / "registry.jsonl").read_text().strip())
        assert "job_id" not in entry
        assert "model" not in entry

    def test_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep = tmp_path / "a" / "b" / "registry.jsonl"
        monkeypatch.setattr(session_registry, "REGISTRY_FILE", deep)
        session_registry.register_session("uuid-1", "cron")
        assert deep.exists()


class TestListSessions:
    def test_empty_when_no_file(self):
        assert session_registry.list_sessions() == []

    def test_reads_all_entries(self, tmp_path):
        f = tmp_path / "registry.jsonl"
        entries = [
            {"ts": "2026-01-01T00:00:00", "session_id": f"s{i}", "type": "cron"}
            for i in range(3)
        ]
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        result = session_registry.list_sessions()
        assert len(result) == 3

    def test_filters_by_type(self, tmp_path):
        f = tmp_path / "registry.jsonl"
        lines = [
            json.dumps({"session_id": "s1", "type": "cron"}),
            json.dumps({"session_id": "s2", "type": "user"}),
            json.dumps({"session_id": "s3", "type": "cron"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        result = session_registry.list_sessions(session_type="cron")
        assert len(result) == 2
        assert all(e["type"] == "cron" for e in result)

    def test_filters_by_job_id(self, tmp_path):
        f = tmp_path / "registry.jsonl"
        lines = [
            json.dumps({"session_id": "s1", "type": "cron", "job_id": "heartbeat"}),
            json.dumps({"session_id": "s2", "type": "cron", "job_id": "reflection"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        result = session_registry.list_sessions(job_id="heartbeat")
        assert len(result) == 1

    def test_limit(self, tmp_path):
        f = tmp_path / "registry.jsonl"
        lines = [json.dumps({"session_id": f"s{i}", "type": "cron"}) for i in range(10)]
        f.write_text("\n".join(lines) + "\n")
        result = session_registry.list_sessions(limit=3)
        assert len(result) == 3
        # Should be last 3
        assert result[0]["session_id"] == "s7"

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "registry.jsonl"
        f.write_text('{"session_id":"s1","type":"cron"}\n\n\n{"session_id":"s2","type":"cron"}\n')
        result = session_registry.list_sessions()
        assert len(result) == 2

    def test_skips_bad_json(self, tmp_path):
        f = tmp_path / "registry.jsonl"
        f.write_text('{"session_id":"s1","type":"cron"}\nnot json\n{"session_id":"s2","type":"cron"}\n')
        result = session_registry.list_sessions()
        assert len(result) == 2
