"""Tests for gateway/lib/subagent_state.py - sub-agent state management."""

import json
import os
import pytest
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import subagent_state


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """Redirect state file and output dir to tmp_path."""
    monkeypatch.setattr(subagent_state, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(subagent_state, "OUTPUT_DIR", tmp_path / "output")
    (tmp_path / "output").mkdir()


class TestLoadState:
    def test_default_when_no_file(self):
        state = subagent_state.load_state()
        assert state == {"active": {}, "pending_announces": [], "last_updated": None}

    def test_loads_existing(self, tmp_path):
        data = {"active": {"j1": {"status": "running"}}, "pending_announces": [], "last_updated": "2026-01-01"}
        (tmp_path / "state.json").write_text(json.dumps(data))
        state = subagent_state.load_state()
        assert "j1" in state["active"]

    def test_handles_corrupt_json(self, tmp_path):
        (tmp_path / "state.json").write_text("not json{{{")
        state = subagent_state.load_state()
        assert state["active"] == {}


class TestSaveState:
    def test_writes_json(self, tmp_path):
        state = {"active": {}, "pending_announces": []}
        subagent_state.save_state(state)
        loaded = json.loads((tmp_path / "state.json").read_text())
        assert "last_updated" in loaded

    def test_atomic_write(self, tmp_path):
        """Save uses tmp + rename so partial writes don't corrupt."""
        state = {"active": {"j1": {"x": 1}}, "pending_announces": []}
        subagent_state.save_state(state)
        assert not (tmp_path / "state.tmp").exists()
        assert (tmp_path / "state.json").exists()


class TestRegisterSubagent:
    def test_registers_new(self, tmp_path):
        job = {"name": "Research", "execution": {"model": "sonnet"}}
        result = subagent_state.register_subagent("j1", job, origin_topic=100002, pid=12345)
        assert result["status"] == "running"
        assert result["job"] == job
        assert result["origin_topic"] == 100002
        assert result["pid"] == 12345

        # Verify persisted
        state = subagent_state.load_state()
        assert "j1" in state["active"]

    def test_registers_with_session_id(self):
        job = {"name": "Task"}
        result = subagent_state.register_subagent("j1", job, origin_topic=0, session_id="sess-1")
        assert result["session_id"] == "sess-1"

    def test_output_file_paths(self, tmp_path):
        job = {"name": "Task"}
        result = subagent_state.register_subagent("j1", job, origin_topic=0)
        assert result["output_file"] == str(tmp_path / "output" / "j1.out")
        assert result["result_file"] == str(tmp_path / "output" / "j1.result.json")


class TestUpdateSubagentStatus:
    def test_updates_status(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        subagent_state.update_subagent_status("j1", "pending_retry")
        state = subagent_state.load_state()
        assert state["active"]["j1"]["status"] == "pending_retry"

    def test_updates_pid(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        subagent_state.update_subagent_status("j1", "running", pid=9999)
        state = subagent_state.load_state()
        assert state["active"]["j1"]["pid"] == 9999

    def test_noop_for_missing_job(self):
        subagent_state.update_subagent_status("nonexistent", "running")  # should not raise


class TestSetStatusMessageId:
    def test_sets_message_id(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        subagent_state.set_status_message_id("j1", 42)
        state = subagent_state.load_state()
        assert state["active"]["j1"]["status_message_id"] == 42


class TestCompleteSubagent:
    def test_moves_to_pending(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        result = subagent_state.complete_subagent("j1", {"status": "completed", "output": "done"})
        assert result is not None
        assert result["status"] == "completed"

        state = subagent_state.load_state()
        assert "j1" not in state["active"]
        assert len(state["pending_announces"]) == 1
        assert state["pending_announces"][0]["job_id"] == "j1"

    def test_returns_none_for_unknown(self):
        assert subagent_state.complete_subagent("unknown", {}) is None


class TestFailSubagent:
    def test_marks_failed_and_queues_announce(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        result = subagent_state.fail_subagent("j1", "timeout")
        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"

        state = subagent_state.load_state()
        assert "j1" not in state["active"]
        assert len(state["pending_announces"]) == 1

    def test_returns_none_for_unknown(self):
        assert subagent_state.fail_subagent("unknown", "err") is None


class TestGetActiveSubagents:
    def test_empty(self):
        assert subagent_state.get_active_subagents() == {}

    def test_returns_active(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        active = subagent_state.get_active_subagents()
        assert "j1" in active


class TestPopPendingAnnounce:
    def test_pops_first(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        subagent_state.complete_subagent("j1", {"status": "completed"})
        announce = subagent_state.pop_pending_announce()
        assert announce is not None
        assert announce["job_id"] == "j1"
        # Queue should be empty now
        assert subagent_state.pop_pending_announce() is None

    def test_returns_none_when_empty(self):
        assert subagent_state.pop_pending_announce() is None


class TestRequeueAnnounce:
    def test_increments_retries(self):
        announce = {"job_id": "j1", "retries": 0}
        subagent_state.requeue_announce(announce)
        state = subagent_state.load_state()
        assert state["pending_announces"][0]["retries"] == 1
        assert "retry_at" in state["pending_announces"][0]


class TestIsProcessAlive:
    def test_own_pid_is_alive(self):
        assert subagent_state.is_process_alive(os.getpid()) is True

    def test_invalid_pid(self):
        assert subagent_state.is_process_alive(999999999) is False

    def test_none_pid(self):
        assert subagent_state.is_process_alive(None) is False

    def test_zero_pid(self):
        assert subagent_state.is_process_alive(0) is False


class TestGetSubagentOutput:
    def test_reads_output(self, tmp_path):
        (tmp_path / "output" / "j1.out").write_text("hello output")
        assert subagent_state.get_subagent_output("j1") == "hello output"

    def test_returns_none_when_missing(self):
        assert subagent_state.get_subagent_output("nonexistent") is None


class TestGetSubagentResult:
    def test_reads_result(self, tmp_path):
        (tmp_path / "output" / "j1.result.json").write_text('{"status":"ok"}')
        result = subagent_state.get_subagent_result("j1")
        assert result == {"status": "ok"}

    def test_returns_none_for_bad_json(self, tmp_path):
        (tmp_path / "output" / "j1.result.json").write_text("not json")
        assert subagent_state.get_subagent_result("j1") is None

    def test_returns_none_when_missing(self):
        assert subagent_state.get_subagent_result("nonexistent") is None


class TestCleanupSubagentFiles:
    def test_removes_all_files(self, tmp_path):
        out_dir = tmp_path / "output"
        for suffix in [".out", ".result.json", ".sh", ".pid", ".prompt"]:
            (out_dir / f"j1{suffix}").write_text("data")
        subagent_state.cleanup_subagent_files("j1")
        for suffix in [".out", ".result.json", ".sh", ".pid", ".prompt"]:
            assert not (out_dir / f"j1{suffix}").exists()

    def test_noop_when_no_files(self):
        subagent_state.cleanup_subagent_files("nonexistent")  # should not raise


class TestGetStaleSubagents:
    def test_detects_stale(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        # Manually backdate the started_at
        state = subagent_state.load_state()
        old_time = (datetime.now() - timedelta(minutes=60)).isoformat()
        state["active"]["j1"]["started_at"] = old_time
        subagent_state.save_state(state)

        stale = subagent_state.get_stale_subagents(max_age_minutes=30)
        assert len(stale) == 1
        assert stale[0]["job_id"] == "j1"

    def test_fresh_not_stale(self):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0)
        stale = subagent_state.get_stale_subagents(max_age_minutes=30)
        assert len(stale) == 0


class TestRecoverCrashedSubagents:
    def test_completes_from_result_file(self, tmp_path):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0, pid=999999999)
        # Write result file
        (tmp_path / "output" / "j1.result.json").write_text('{"status":"completed","output":"done"}')
        recoveries = subagent_state.recover_crashed_subagents()
        assert len(recoveries) == 1
        assert recoveries[0]["action"] == "completed_from_result"

    def test_fails_with_partial_output(self, tmp_path):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0, pid=999999999)
        (tmp_path / "output" / "j1.out").write_text("partial output here")
        recoveries = subagent_state.recover_crashed_subagents()
        assert len(recoveries) == 1
        assert recoveries[0]["action"] == "failed_with_output"

    def test_retries_when_no_output(self, tmp_path):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0, pid=999999999)
        recoveries = subagent_state.recover_crashed_subagents()
        assert len(recoveries) == 1
        assert recoveries[0]["action"] == "pending_retry"

    def test_skips_alive_process(self, tmp_path):
        subagent_state.register_subagent("j1", {"name": "T"}, origin_topic=0, pid=os.getpid())
        recoveries = subagent_state.recover_crashed_subagents()
        assert len(recoveries) == 0


class TestInitSubagentState:
    def test_custom_paths(self, tmp_path, monkeypatch):
        config = {
            "subagents": {
                "state_file": str(tmp_path / "custom" / "state.json"),
                "output_dir": str(tmp_path / "custom_out"),
            }
        }
        subagent_state.init_subagent_state(config)
        assert subagent_state.STATE_FILE == tmp_path / "custom" / "state.json"
        assert subagent_state.OUTPUT_DIR == Path(str(tmp_path / "custom_out"))
