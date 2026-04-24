"""Tests for gateway/pipeline.py - state machine CLI."""

import json
import pytest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pipeline as pm


SAMPLE_PIPELINE = {
    "name": "test-pipeline",
    "description": "A test pipeline",
    "settings": {
        "initial_state": "plan",
        "max_retries": 3,
        "retry_counter_transitions": [{"from": "execute", "to": "plan"}],
    },
    "states": {
        "plan": {"description": "Planning phase", "instructions": "Make a plan"},
        "execute": {"description": "Execution phase"},
        "done": {"description": "Completed", "terminal": True},
        "failed": {"description": "Failed", "terminal": True},
    },
    "transitions": [
        {"from": "plan", "to": "execute"},
        {"from": "execute", "to": "done"},
        {"from": "execute", "to": "plan", "label": "revise"},
        {"from": "execute", "to": "failed"},
    ],
}


@pytest.fixture(autouse=True)
def isolate_dirs(tmp_path, monkeypatch):
    """Redirect all pipeline dirs to tmp_path."""
    monkeypatch.setattr(pm, "STATE_DIR", tmp_path / "sessions")
    monkeypatch.setattr(pm, "COMPLETED_DIR", tmp_path / "completed")
    monkeypatch.setattr(pm, "PIPELINES_DIR", tmp_path / "pipelines")
    (tmp_path / "sessions").mkdir()
    (tmp_path / "completed").mkdir()
    (tmp_path / "pipelines").mkdir()


@pytest.fixture
def write_pipeline(tmp_path):
    """Write a pipeline YAML to the pipelines dir."""
    import yaml
    def _write(name="test-pipeline", data=None):
        if data is None:
            data = SAMPLE_PIPELINE
        path = tmp_path / "pipelines" / f"{name}.yaml"
        path.write_text(yaml.dump(data))
        return path
    return _write


# ── Pure functions ──

class TestFmtDuration:
    def test_seconds(self):
        assert pm._fmt_duration(timedelta(seconds=5)) == "5s"

    def test_minutes(self):
        assert pm._fmt_duration(timedelta(minutes=3, seconds=5)) == "3m05s"

    def test_hours(self):
        assert pm._fmt_duration(timedelta(hours=2, minutes=15)) == "2h15m"

    def test_zero(self):
        assert pm._fmt_duration(timedelta(0)) == "0s"

    def test_negative(self):
        assert pm._fmt_duration(timedelta(seconds=-5)) == "0s"

    def test_exactly_60s(self):
        assert pm._fmt_duration(timedelta(seconds=60)) == "1m00s"


class TestParseDurationHours:
    def test_hours(self):
        assert pm._parse_duration_hours("24h") == 24.0

    def test_days(self):
        assert pm._parse_duration_hours("2d") == 48.0

    def test_weeks(self):
        assert pm._parse_duration_hours("1w") == 168.0

    def test_bare_number(self):
        assert pm._parse_duration_hours("12") == 12.0


class TestGetValidTransitions:
    def test_from_plan(self):
        valid = pm.get_valid_transitions(SAMPLE_PIPELINE, "plan")
        assert len(valid) == 1
        assert valid[0]["to"] == "execute"

    def test_from_execute(self):
        valid = pm.get_valid_transitions(SAMPLE_PIPELINE, "execute")
        assert len(valid) == 3  # done, plan (revise), failed

    def test_from_terminal(self):
        valid = pm.get_valid_transitions(SAMPLE_PIPELINE, "done")
        assert len(valid) == 0

    def test_from_unknown(self):
        valid = pm.get_valid_transitions(SAMPLE_PIPELINE, "nonexistent")
        assert len(valid) == 0


class TestStateFilePath:
    def test_short_sid(self, tmp_path):
        path = pm.state_file_path("abc")
        assert path.name == "abc.json"

    def test_long_sid_truncated(self, tmp_path):
        sid = "a" * 40
        path = pm.state_file_path(sid)
        assert path.name == f"{'a' * 16}.json"


# ── File I/O ──

class TestLoadSaveState:
    def test_load_none_when_missing(self):
        assert pm.load_state("nonexistent") is None

    def test_save_and_load(self, tmp_path):
        state = {"current_state": "plan", "pipeline": "test"}
        pm.save_state("test-sid-12345678", state)
        loaded = pm.load_state("test-sid-12345678")
        assert loaded["current_state"] == "plan"

    def test_load_handles_corrupt(self, tmp_path):
        f = tmp_path / "sessions" / "corrupt.json"
        f.write_text("not json{{{")
        # Direct load by path - need to construct correct sid
        pm.save_state("corrupt", {"x": 1})
        # Overwrite with corrupt data
        pm.state_file_path("corrupt").write_text("not json")
        assert pm.load_state("corrupt") is None


class TestLoadPipeline:
    def test_loads_yaml(self, write_pipeline):
        write_pipeline()
        p = pm.load_pipeline("test-pipeline")
        assert p["name"] == "test-pipeline"
        assert "plan" in p["states"]

    def test_exit_on_missing(self, write_pipeline):
        with pytest.raises(SystemExit):
            pm.load_pipeline("nonexistent")


class TestListPipelines:
    def test_lists_all(self, write_pipeline):
        write_pipeline("p1", {**SAMPLE_PIPELINE, "name": "p1"})
        write_pipeline("p2", {**SAMPLE_PIPELINE, "name": "p2"})
        result = pm.list_pipelines()
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "p1" in names
        assert "p2" in names

    def test_empty_when_no_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pm, "PIPELINES_DIR", tmp_path / "nope")
        assert pm.list_pipelines() == []


# ── Commands ──

class TestCmdStart:
    def test_start_creates_state(self, write_pipeline, capsys):
        write_pipeline()
        args = Namespace(sid="test-session-id", name="test-pipeline", context=None, force=False)
        pm.cmd_start(args)
        state = pm.load_state("test-session-id")
        assert state is not None
        assert state["current_state"] == "plan"
        assert state["pipeline"] == "test-pipeline"
        assert len(state["history"]) == 1

    def test_start_with_context(self, write_pipeline):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context='{"task":"build"}', force=False)
        pm.cmd_start(args)
        state = pm.load_state("sid1")
        assert state["context"] == {"task": "build"}

    def test_start_rejects_duplicate(self, write_pipeline):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context=None, force=False)
        pm.cmd_start(args)
        with pytest.raises(SystemExit):
            pm.cmd_start(args)

    def test_start_force_overwrites(self, write_pipeline, capsys):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context=None, force=False)
        pm.cmd_start(args)
        args2 = Namespace(sid="sid1", name="test-pipeline", context=None, force=True)
        pm.cmd_start(args2)  # should not raise

    def test_start_no_sid(self, write_pipeline):
        write_pipeline()
        args = Namespace(sid="", name="test-pipeline", context=None, force=False)
        with pytest.raises(SystemExit):
            pm.cmd_start(args)


class TestCmdTransition:
    def _start(self, write_pipeline):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context=None, force=False)
        pm.cmd_start(args)

    def test_valid_transition(self, write_pipeline, capsys):
        self._start(write_pipeline)
        args = Namespace(sid="sid1", state="execute", label=None)
        pm.cmd_transition(args)
        state = pm.load_state("sid1")
        assert state["current_state"] == "execute"

    def test_invalid_transition(self, write_pipeline):
        self._start(write_pipeline)
        args = Namespace(sid="sid1", state="done", label=None)  # can't go plan -> done
        with pytest.raises(SystemExit):
            pm.cmd_transition(args)

    def test_transition_to_terminal(self, write_pipeline, capsys):
        self._start(write_pipeline)
        # plan -> execute
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        # execute -> done (terminal)
        pm.cmd_transition(Namespace(sid="sid1", state="done", label=None))
        # State file should be moved to completed
        assert pm.load_state("sid1") is None

    def test_retry_counter(self, write_pipeline, capsys):
        self._start(write_pipeline)
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        # execute -> plan (revise) = retry
        pm.cmd_transition(Namespace(sid="sid1", state="plan", label="revise"))
        state = pm.load_state("sid1")
        assert state["retry_count"] == 1

    def test_max_retries_auto_fail(self, write_pipeline, capsys):
        self._start(write_pipeline)
        for _ in range(4):  # 3 retries + 1 to trigger auto-fail
            pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
            pm.cmd_transition(Namespace(sid="sid1", state="plan", label="revise"))
        state = pm.load_state("sid1")
        assert state["current_state"] == "failed"

    def test_no_sid(self, write_pipeline):
        args = Namespace(sid="", state="execute", label=None)
        with pytest.raises(SystemExit):
            pm.cmd_transition(args)

    def test_no_active_pipeline(self, write_pipeline):
        args = Namespace(sid="nonexistent", state="execute", label=None)
        with pytest.raises(SystemExit):
            pm.cmd_transition(args)

    def test_unknown_target_state(self, write_pipeline):
        self._start(write_pipeline)
        args = Namespace(sid="sid1", state="nonexistent", label=None)
        with pytest.raises(SystemExit):
            pm.cmd_transition(args)

    def test_transition_with_label(self, write_pipeline, capsys):
        self._start(write_pipeline)
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        pm.cmd_transition(Namespace(sid="sid1", state="plan", label="revise"))
        state = pm.load_state("sid1")
        assert state["current_state"] == "plan"
        assert any(h.get("label") == "revise" for h in state["history"])


class TestCmdCleanup:
    def test_removes_stale(self, write_pipeline, tmp_path, capsys):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context=None, force=False)
        pm.cmd_start(args)
        # Backdate the started_at
        state = pm.load_state("sid1")
        state["started_at"] = "2020-01-01T00:00:00+00:00"
        pm.save_state("sid1", state)
        # Cleanup
        pm.cmd_cleanup(Namespace(older_than="1h"))
        out = capsys.readouterr().out
        assert "1" in out  # removed 1 file

    def test_keeps_fresh(self, write_pipeline, capsys):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context=None, force=False)
        pm.cmd_start(args)
        pm.cmd_cleanup(Namespace(older_than="24h"))
        assert pm.load_state("sid1") is not None


class TestCmdStatus:
    def test_no_sid(self, capsys):
        with pytest.raises(SystemExit):
            pm.cmd_status(Namespace(sid=""))

    def test_no_active_pipeline(self, capsys):
        pm.cmd_status(Namespace(sid="nonexistent"))
        out = capsys.readouterr().out
        assert "No active pipeline" in out

    def test_shows_status(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_status(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "test-pipeline" in out
        assert "plan" in out.lower()

    def test_status_with_context(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context='{"task":"test"}', force=False))
        pm.cmd_status(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "test" in out

    def test_status_shows_transitions(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_status(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "execute" in out.lower()


class TestCmdEnd:
    def test_no_sid(self):
        with pytest.raises(SystemExit):
            pm.cmd_end(Namespace(sid="", reason=None))

    def test_no_active_pipeline(self, capsys):
        pm.cmd_end(Namespace(sid="nonexistent", reason=None))
        out = capsys.readouterr().out
        assert "No active pipeline" in out

    def test_ends_pipeline(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_end(Namespace(sid="sid1", reason="test-reason"))
        out = capsys.readouterr().out
        assert "ended" in out.lower()
        assert "test-reason" in out

    def test_ends_with_default_reason(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_end(Namespace(sid="sid1", reason=None))
        out = capsys.readouterr().out
        assert "manual" in out


class TestCmdList:
    def test_no_pipelines(self, capsys):
        pm.cmd_list(Namespace())
        out = capsys.readouterr().out
        assert "No pipelines" in out

    def test_lists_pipelines(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_list(Namespace())
        out = capsys.readouterr().out
        assert "test-pipeline" in out


class TestCmdShow:
    def test_shows_pipeline(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_show(Namespace(name="test-pipeline"))
        out = capsys.readouterr().out
        assert "test-pipeline" in out
        assert "plan" in out
        assert "execute" in out
        assert "done" in out

    def test_shows_transitions(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_show(Namespace(name="test-pipeline"))
        out = capsys.readouterr().out
        assert "->" in out


class TestCmdHistory:
    def test_no_sid(self):
        with pytest.raises(SystemExit):
            pm.cmd_history(Namespace(sid=""))

    def test_no_active_pipeline(self, capsys):
        pm.cmd_history(Namespace(sid="nonexistent"))
        out = capsys.readouterr().out
        assert "No active pipeline" in out

    def test_shows_history(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        capsys.readouterr()  # clear
        pm.cmd_history(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "test-pipeline" in out
        assert "->" in out


class TestCmdDashboard:
    def test_empty_dashboard(self, capsys):
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "No active" in out

    def test_shows_active_sessions(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        capsys.readouterr()  # clear
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "test-pipeline" in out
        assert "PLAN" in out
        assert "1 active" in out


class TestCompleteSession:
    def test_moves_to_completed(self, write_pipeline, tmp_path):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        state = pm.load_state("sid1")
        pm._complete_session("sid1", state)
        # Should have file in completed dir
        completed_files = list((tmp_path / "completed").glob("*.json"))
        assert len(completed_files) == 1

    def test_complete_handles_move_failure(self, write_pipeline, tmp_path, monkeypatch):
        """When shutil.move fails, _complete_session should fall back to unlinking src."""
        import shutil
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        state = pm.load_state("sid1")
        # Make shutil.move fail
        def bad_move(src, dst):
            raise OSError("move failed")
        monkeypatch.setattr(shutil, "move", bad_move)
        pm._complete_session("sid1", state)
        # src should be unlinked
        assert pm.load_state("sid1") is None


# ── Additional coverage tests ──

class TestCmdStartInvalidInitialState:
    def test_invalid_initial_state_exits(self, tmp_path):
        import yaml
        bad_pipeline = {
            "name": "bad",
            "settings": {"initial_state": "nonexistent"},
            "states": {"plan": {"description": "Plan"}},
            "transitions": [],
        }
        (tmp_path / "pipelines" / "bad.yaml").write_text(yaml.dump(bad_pipeline))
        args = Namespace(sid="sid1", name="bad", context=None, force=False)
        with pytest.raises(SystemExit):
            pm.cmd_start(args)

    def test_invalid_json_context_exits(self, write_pipeline):
        write_pipeline()
        args = Namespace(sid="sid1", name="test-pipeline", context="not-json{", force=False)
        with pytest.raises(SystemExit):
            pm.cmd_start(args)

    def test_sub_pipeline_prints_message(self, tmp_path, capsys):
        import yaml
        pipeline_with_sub = {
            "name": "sub-test",
            "settings": {"initial_state": "plan"},
            "states": {
                "plan": {"description": "Plan", "sub_pipeline": "sub-plan", "instructions": "Do stuff"},
            },
            "transitions": [],
        }
        (tmp_path / "pipelines" / "sub-test.yaml").write_text(yaml.dump(pipeline_with_sub))
        args = Namespace(sid="sid1", name="sub-test", context=None, force=False)
        pm.cmd_start(args)
        out = capsys.readouterr().out
        assert "SUB-PIPELINE" in out
        assert "sub-plan" in out


class TestCmdTransitionEdgeCases:
    def _start(self, write_pipeline):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))

    def test_transition_from_terminal_state(self, write_pipeline):
        self._start(write_pipeline)
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        pm.cmd_transition(Namespace(sid="sid1", state="done", label=None))
        # Now start fresh and manually put state in "done"
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid2", name="test-pipeline", context=None, force=False))
        state = pm.load_state("sid2")
        state["current_state"] = "done"
        pm.save_state("sid2", state)
        with pytest.raises(SystemExit):
            pm.cmd_transition(Namespace(sid="sid2", state="plan", label=None))

    def test_transition_sub_pipeline_message(self, tmp_path, capsys):
        import yaml
        pipeline_with_sub = {
            "name": "sub-trans",
            "settings": {"initial_state": "plan"},
            "states": {
                "plan": {"description": "Plan"},
                "execute": {"description": "Execute", "sub_pipeline": "child-pipe"},
            },
            "transitions": [{"from": "plan", "to": "execute"}],
        }
        (tmp_path / "pipelines" / "sub-trans.yaml").write_text(yaml.dump(pipeline_with_sub))
        pm.cmd_start(Namespace(sid="sid1", name="sub-trans", context=None, force=False))
        capsys.readouterr()  # clear
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        out = capsys.readouterr().out
        assert "SUB-PIPELINE" in out
        assert "child-pipe" in out


class TestCmdStatusEdgeCases:
    def test_status_with_retries(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        pm.cmd_transition(Namespace(sid="sid1", state="plan", label="revise"))
        capsys.readouterr()  # clear
        pm.cmd_status(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "Retries" in out

    def test_status_long_context_truncated(self, write_pipeline, capsys):
        write_pipeline()
        long_context = json.dumps({"data": "x" * 200})
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=long_context, force=False))
        capsys.readouterr()  # clear
        pm.cmd_status(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "..." in out
        assert "Context" in out


class TestCmdHistoryEdgeCases:
    def test_history_with_invalid_timestamp(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        # Manually add a history entry with bad timestamp
        state = pm.load_state("sid1")
        state["history"].append({"from": "plan", "to": "execute", "at": "invalid-date"})
        pm.save_state("sid1", state)
        capsys.readouterr()
        pm.cmd_history(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        # Should show the invalid date as-is instead of crashing
        assert "invalid-date" in out

    def test_history_with_retry_count(self, write_pipeline, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        pm.cmd_transition(Namespace(sid="sid1", state="execute", label=None))
        pm.cmd_transition(Namespace(sid="sid1", state="plan", label="revise"))
        capsys.readouterr()
        pm.cmd_history(Namespace(sid="sid1"))
        out = capsys.readouterr().out
        assert "retry" in out


class TestCmdDashboardEdgeCases:
    def test_dashboard_no_state_dir(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(pm, "STATE_DIR", tmp_path / "nonexistent")
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "No active sessions" in out

    def test_dashboard_corrupt_session_file(self, tmp_path, capsys):
        (tmp_path / "sessions" / "corrupt.json").write_text("not json{{{")
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "No active" in out

    def test_dashboard_with_completed_today(self, write_pipeline, tmp_path, capsys):
        from datetime import datetime, timezone
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        # Create completed file with today's date
        today = datetime.now().strftime("%Y%m%d")
        today_iso = datetime.now(timezone.utc).isoformat()
        completed = tmp_path / "completed" / "done_session.json"
        completed.write_text(json.dumps({"started_at": today_iso}))
        capsys.readouterr()
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        # Should show completed count
        assert "completed today" in out

    def test_dashboard_corrupt_completed_file(self, write_pipeline, tmp_path, capsys):
        write_pipeline()
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline", context=None, force=False))
        # Add corrupt file to completed dir
        (tmp_path / "completed" / "bad.json").write_text("not json")
        capsys.readouterr()
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "active" in out

    def test_dashboard_invalid_started_at(self, tmp_path, capsys):
        """Session with invalid started_at should show '?' duration."""
        write_pipeline_data = {**SAMPLE_PIPELINE}
        import yaml
        (tmp_path / "pipelines" / "test-pipeline.yaml").write_text(yaml.dump(write_pipeline_data))
        state = {
            "session_id": "test-sid-1234567890",
            "pipeline": "test-pipeline",
            "instance_id": "te_20260316",
            "current_state": "plan",
            "started_at": "invalid-date",
            "state_entered_at": "invalid-date",
            "retry_count": 0,
            "context": {},
            "history": [],
        }
        (tmp_path / "sessions" / "test-sid-1234567.json").write_text(json.dumps(state))
        capsys.readouterr()
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "?" in out

    def test_dashboard_pipeline_not_found(self, tmp_path, capsys):
        """Session referencing a nonexistent pipeline shows retry count as plain number."""
        state = {
            "session_id": "test-sid-1234567890",
            "pipeline": "nonexistent-pipeline",
            "instance_id": "ne_20260316",
            "current_state": "plan",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "state_entered_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 2,
            "context": {},
            "history": [],
        }
        (tmp_path / "sessions" / "test-sid-1234567.json").write_text(json.dumps(state))
        capsys.readouterr()
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "2" in out  # retry count shown as plain number

    def test_dashboard_long_task_truncated(self, write_pipeline, tmp_path, capsys):
        write_pipeline()
        long_task = "a" * 30
        pm.cmd_start(Namespace(sid="sid1", name="test-pipeline",
                               context=json.dumps({"task": long_task}), force=False))
        capsys.readouterr()
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "..." in out

    def test_dashboard_no_sessions_with_completed(self, tmp_path, capsys):
        """No active sessions but completed today should show count."""
        today_iso = datetime.now(timezone.utc).isoformat()
        (tmp_path / "completed" / "done.json").write_text(json.dumps({"started_at": today_iso}))
        pm.cmd_dashboard(Namespace())
        out = capsys.readouterr().out
        assert "No active sessions" in out
        assert "completed today" in out


class TestCmdCleanupEdgeCases:
    def test_cleanup_corrupt_active_session(self, tmp_path, capsys):
        """Corrupt active session files should be removed during cleanup."""
        (tmp_path / "sessions" / "corrupt.json").write_text("not json")
        pm.cmd_cleanup(Namespace(older_than="1h"))
        out = capsys.readouterr().out
        assert "1" in out  # removed 1 corrupt file

    def test_cleanup_completed_sessions(self, tmp_path, capsys):
        """Old completed session files should be cleaned up."""
        import os
        completed_file = tmp_path / "completed" / "old.json"
        completed_file.write_text(json.dumps({"started_at": "2020-01-01T00:00:00+00:00"}))
        # Backdate the file mtime
        os.utime(completed_file, (0, 0))
        pm.cmd_cleanup(Namespace(older_than="1h"))
        out = capsys.readouterr().out
        assert not completed_file.exists()


class TestCmdCleanupCompleted:
    def test_cleanup_completed_oserror_fallback(self, tmp_path, capsys, monkeypatch):
        """When stat() fails on a completed file, it should still be removed."""
        completed_file = tmp_path / "completed" / "bad.json"
        completed_file.write_text("{}")
        original_stat = Path.stat

        def broken_stat(self):
            if "bad.json" in str(self):
                raise OSError("stat failed")
            return original_stat(self)

        monkeypatch.setattr(Path, "stat", broken_stat)
        pm.cmd_cleanup(Namespace(older_than="1h"))
        out = capsys.readouterr().out
        assert "1" in out  # removed the bad file


class TestMain:
    def test_no_command_exits(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["pipeline.py"])
        with pytest.raises(SystemExit):
            pm.main()

    def test_list_command(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["pipeline.py", "list"])
        pm.main()
        out = capsys.readouterr().out
        assert "No pipelines" in out

    def test_sid_from_env(self, monkeypatch, write_pipeline, capsys):
        write_pipeline()
        monkeypatch.setenv("CLAUDE_SESSION_ID", "env-session-id")
        monkeypatch.setattr("sys.argv", ["pipeline.py", "start", "test-pipeline"])
        pm.main()
        state = pm.load_state("env-session-id")
        assert state is not None
        assert state["pipeline"] == "test-pipeline"
