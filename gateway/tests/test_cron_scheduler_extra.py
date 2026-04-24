"""Extra tests for cron-scheduler.py to cover remaining missed lines.

Covers: _get_vadimgest_details, _build_heartbeat_report edge cases,
_execute_job_internal session fallback & auto-recovery, _process_job_result
(auth errors, retry rollback, intake consumed, main session save),
_recover_foreground_jobs, _recover_single_job, _reload_jobs/schedule_jobs,
_write_healthcheck error path, _check_jobs_reload error, _check_subagent_announces,
_update_running_subagents_progress, _start_healthcheck_thread,
_detect_and_alert_crash exception, _send_startup_notification exception,
start(), acquire_lock(), main().
"""

import importlib.util
import json
import os
import sys
import time
import types
import fcntl
import signal
import threading
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, call

# ── Load module (same approach as existing test file) ──
spec = importlib.util.spec_from_file_location(
    "cron_scheduler",
    os.path.join(os.path.dirname(__file__), "..", "cron-scheduler.py"),
)

_mock_modules = {
    "lib.telegram_utils": MagicMock(),
    "lib.feed": MagicMock(),
    "lib.claude_executor": MagicMock(),
    "lib.announce_handler": MagicMock(),
    "lib.subagent_state": MagicMock(),
    "lib.subagent_status": MagicMock(),
    "lib.main_session": MagicMock(),
    "lib.session_registry": MagicMock(),
}

try:
    import apscheduler
except ImportError:
    _aps = types.ModuleType("apscheduler")
    _aps_sched = types.ModuleType("apscheduler.schedulers")
    _aps_sched_blocking = types.ModuleType("apscheduler.schedulers.blocking")
    _aps_sched_blocking.BlockingScheduler = MagicMock
    _aps_exec = types.ModuleType("apscheduler.executors")
    _aps_exec_pool = types.ModuleType("apscheduler.executors.pool")
    _aps_exec_pool.ThreadPoolExecutor = MagicMock
    _aps_trig = types.ModuleType("apscheduler.triggers")
    _aps_trig_cron = types.ModuleType("apscheduler.triggers.cron")
    _aps_trig_cron.CronTrigger = MagicMock()
    _aps_trig_interval = types.ModuleType("apscheduler.triggers.interval")
    _aps_trig_interval.IntervalTrigger = MagicMock
    _aps_trig_date = types.ModuleType("apscheduler.triggers.date")
    _aps_trig_date.DateTrigger = MagicMock
    _mock_modules.update({
        "apscheduler": _aps,
        "apscheduler.schedulers": _aps_sched,
        "apscheduler.schedulers.blocking": _aps_sched_blocking,
        "apscheduler.executors": _aps_exec,
        "apscheduler.executors.pool": _aps_exec_pool,
        "apscheduler.triggers": _aps_trig,
        "apscheduler.triggers.cron": _aps_trig_cron,
        "apscheduler.triggers.interval": _aps_trig_interval,
        "apscheduler.triggers.date": _aps_trig_date,
    })

try:
    import croniter as _croniter_test
except ImportError:
    _croniter_mod = types.ModuleType("croniter")
    _croniter_mod.croniter = MagicMock
    _mock_modules["croniter"] = _croniter_mod

_saved = {}
for mod_name, mock_mod in _mock_modules.items():
    _saved[mod_name] = sys.modules.get(mod_name)
    sys.modules[mod_name] = mock_mod

cs = importlib.util.module_from_spec(spec)
with patch("dotenv.load_dotenv"):
    spec.loader.exec_module(cs)

for mod_name, orig in _saved.items():
    if orig is None:
        if mod_name.startswith("lib."):
            sys.modules.pop(mod_name, None)
    else:
        sys.modules[mod_name] = orig

# The source code uses `signal.SIGKILL` in _recover_foreground_jobs and
# `signal.Signals` in _handle_debug_signal, but `import signal` only happens
# inside start(). Inject it into the module namespace so tests can run these
# methods in isolation.
import signal as _signal_mod
cs.signal = _signal_mod


# ── Fixtures ──

@pytest.fixture
def minimal_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    jobs_file = tmp_path / "cron" / "jobs.json"
    state_file = tmp_path / "cron" / "state.json"
    runs_log = tmp_path / "cron" / "runs.jsonl"
    (tmp_path / "cron").mkdir(exist_ok=True)

    config = {
        "cron": {
            "jobs_file": str(jobs_file),
            "state_file": str(state_file),
            "runs_log": str(runs_log),
        },
        "telegram": {"bot_token": "test", "allowed_users": [123]},
    }
    import yaml
    config_file.write_text(yaml.dump(config))
    jobs_file.write_text(json.dumps({"version": 1, "jobs": []}))

    return config_file, jobs_file, state_file, runs_log


@pytest.fixture
def job_manager(minimal_config):
    config_file, jobs_file, state_file, runs_log = minimal_config
    with patch.object(cs, "ClaudeExecutor", return_value=MagicMock()), \
         patch.object(cs, "BlockingScheduler", return_value=MagicMock()):
        manager = cs.JobManager(str(config_file))
    return manager


# ── _get_vadimgest_details ─────────────────────────────────────────

class TestGetVadimgestDetails:
    def test_non_list_records_skipped(self, job_manager):
        """Line 186: records that aren't lists should be skipped."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"telegram": "not-a-list", "signal": [{"chat": "test"}]})

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("intake")

        assert "telegram" not in result
        assert "signal" in result
        assert result["signal"]["test"] == 1

    def test_outer_exception_returns_none(self, job_manager):
        """Lines 196-197: outer except catches any exception."""
        with patch("subprocess.run", side_effect=OSError("disk full")):
            result = job_manager._get_vadimgest_details("intake")

        assert result is None

    def test_signal_uses_contact_name_fallback(self, job_manager):
        """Line 192: signal records without chat use meta.contact_name."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "signal": [
                {"meta": {"contact_name": "Alice"}},
                {"chat": "GroupChat"},
            ]
        })

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("intake")

        assert result["signal"]["Alice"] == 1
        assert result["signal"]["GroupChat"] == 1


# ── _build_heartbeat_report edge cases ──────────────────────────────

class TestBuildHeartbeatReportEdgeCases:
    def test_unknown_delta_type_fallback(self, job_manager):
        """Lines 294-295: unknown delta type uses generic format."""
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {
                "total_new": 5,
                "stats": {"telegram": 5},
                "details": {},
            },
            "deltas": [
                {"type": "some_weird_type", "title": "My Title"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "some_weird_type" in result
        assert "My Title" in result

    def test_many_todos_in_progress_and_pending_summary(self, job_manager):
        """Lines 347, 349: in_progress and pending counts in summary for >8 todos."""
        todos = []
        for i in range(4):
            todos.append({"status": "completed", "content": f"Done {i}"})
        for i in range(3):
            todos.append({"status": "in_progress", "content": f"Working {i}"})
        for i in range(3):
            todos.append({"status": "pending", "content": f"Todo {i}"})

        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {
                "total_new": 5,
                "stats": {"telegram": 5},
                "details": {},
            },
            "todos": todos,
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Total:" in result


# ── _execute_job_internal: session fallback & auto-recovery ─────────

class TestExecuteJobInternal:
    def test_heartbeat_captures_intake(self, job_manager):
        """Lines 811-813: heartbeat jobs capture vadimgest stats."""
        job = {
            "id": "heartbeat",
            "execution": {"mode": "isolated", "timeout_seconds": 60},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        mock_stats = {"telegram": {"total": 100, "new": 5}}
        mock_details = {"telegram": {"Chat1": 3, "Chat2": 2}}

        with patch.object(job_manager, "_get_vadimgest_stats", return_value=mock_stats), \
             patch.object(job_manager, "_get_vadimgest_details", return_value=mock_details), \
             patch.object(job_manager, "_run_claude_detached", return_value={"result": "ok"}), \
             patch.object(job_manager, "_process_job_result") as mock_process, \
             patch.object(job_manager, "_log_run"):
            job_manager._execute_job_internal(job, is_catch_up=False)

        # _process_job_result should be called with intake_before and intake_details
        call_args = mock_process.call_args
        assert call_args[0][5] == job.get("execution", {})  # exec_config
        assert call_args[0][6] == mock_stats  # intake_before
        assert call_args[0][7] == mock_details  # intake_details

    def test_main_session_fallback_to_isolated(self, job_manager):
        """Lines 867-870: $main with no session falls back to isolated."""
        job = {
            "id": "test-job",
            "execution": {
                "mode": "main",
                "session_id": "$main",
                "timeout_seconds": 60,
                "prompt": "hello",
            },
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        with patch.object(cs, "get_main_session_id", return_value=None), \
             patch.object(job_manager, "_run_claude_detached", return_value={"result": "ok"}) as mock_run, \
             patch.object(job_manager, "_process_job_result"), \
             patch.object(job_manager, "_log_run"):
            job_manager._execute_job_internal(job, is_catch_up=False)

        # Should have been called (mode internally changed to isolated)
        mock_run.assert_called_once()

    def test_auto_recovery_on_session_expired(self, job_manager):
        """Lines 882-900: session expired triggers retry in isolated mode."""
        job = {
            "id": "heartbeat",
            "execution": {
                "mode": "main",
                "session_id": "$main",
                "timeout_seconds": 60,
                "prompt": "hello",
            },
        }
        job_manager.state = {"jobs_status": {"heartbeat": {"session_id": "old"}}, "running_foreground_jobs": {}}

        mock_clear = MagicMock()

        # First call returns session error, second call succeeds
        with patch.object(cs, "get_main_session_id", return_value="sess-123"), \
             patch.object(job_manager, "_run_claude_detached", side_effect=[
                 {"error": "No conversation found for session sess-123"},
                 {"result": "ok"},
             ]) as mock_run, \
             patch.dict("sys.modules", {"lib.main_session": MagicMock(clear_main_session_id=mock_clear)}), \
             patch.object(job_manager, "_process_job_result"), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_get_vadimgest_stats", return_value=None), \
             patch.object(job_manager, "_get_vadimgest_details", return_value=None):
            job_manager._execute_job_internal(job, is_catch_up=False)

        assert mock_run.call_count == 2
        mock_clear.assert_called_once()


# ── _process_job_result ─────────────────────────────────────────────

class TestProcessJobResult:
    def _make_exec_config(self, **overrides):
        cfg = {"mode": "isolated", "timeout_seconds": 60}
        cfg.update(overrides)
        return cfg

    def test_saves_main_session_id(self, job_manager):
        """Lines 973-974: main session ID saved when $main and result has session_id."""
        job = {"id": "heartbeat"}
        result = {"result": "ok", "session_id": "new-sess-456"}
        exec_config = self._make_exec_config(session_id="$main")
        now = datetime.now(timezone.utc)

        job_manager.state = {"jobs_status": {}}

        with patch.object(cs, "save_main_session_id") as mock_save, \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_log_run"), \
             patch.object(cs, "register_session"), \
             patch.object(cs, "send_feed"):
            job_manager._process_job_result(
                job, "run1", result, now, 10.0, exec_config, None, None, 0
            )

        mock_save.assert_called_once_with("new-sess-456")

    def test_intake_consumed_calculation(self, job_manager):
        """Lines 988-995: intake consumed delta calculated correctly."""
        job = {"id": "heartbeat"}
        result = {"result": "ok"}
        exec_config = self._make_exec_config()
        now = datetime.now(timezone.utc)
        intake_before = {
            "telegram": {"total": 100, "new": 10},
            "signal": {"total": 50, "new": 5},
        }
        intake_after = {
            "telegram": {"total": 100, "new": 3},
            "signal": {"total": 50, "new": 0},
        }

        job_manager.state = {"jobs_status": {}}

        with patch.object(job_manager, "_get_vadimgest_stats", return_value=intake_after), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_log_run") as mock_log, \
             patch.object(cs, "register_session"), \
             patch.object(cs, "send_feed"):
            job_manager._process_job_result(
                job, "run1", result, now, 10.0, exec_config, intake_before, None, 0
            )

        logged = mock_log.call_args[0][0]
        intake = logged["intake"]
        assert intake["consumed"]["telegram"]["had"] == 10
        assert intake["consumed"]["telegram"]["consumed"] == 7
        assert intake["consumed"]["telegram"]["remaining"] == 3

    def test_auth_error_sends_alert_no_retry(self, job_manager):
        """Lines 1071-1079: auth error triggers alert, no retry."""
        job = {"id": "test-job"}
        result = {"result": "", "error": "Not logged in"}
        exec_config = self._make_exec_config()
        now = datetime.now(timezone.utc)

        job_manager.state = {"jobs_status": {}}

        with patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_send_failure_alert") as mock_alert, \
             patch.object(job_manager, "_schedule_retry") as mock_retry:
            job_manager._process_job_result(
                job, "run1", result, now, 5.0, exec_config, None, None, 0
            )

        mock_alert.assert_called_once()
        assert "AUTH FAILED" in mock_alert.call_args[0][1]
        mock_retry.assert_not_called()

    def test_retry_rollback_with_prev_status(self, job_manager):
        """Lines 1088-1089: retry rollback restores previous status and saves state."""
        job = {"id": "test-job", "retry": {"max_attempts": 3}}
        # Use a retryable error (HTTP 500) so _is_retryable_error passes
        result = {"result": "", "error": "HTTP 500 Internal Server Error"}
        exec_config = self._make_exec_config()
        now = datetime.now(timezone.utc)

        prev_status = {"last_run": "2026-03-15T09:00:00+00:00", "status": "completed"}
        job_manager.state = {
            "jobs_status": {"test-job": prev_status.copy()},
            "_prev_job_status": {"test-job": prev_status.copy()},
        }

        with patch.object(job_manager, "_save_state") as mock_save, \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_schedule_retry") as mock_retry:
            job_manager._process_job_result(
                job, "run1", result, now, 5.0, exec_config, None, None, 0
            )

        mock_retry.assert_called_once()
        # State should be restored to prev_status
        assert job_manager.state["jobs_status"]["test-job"]["status"] == "completed"


# ── _recover_foreground_jobs ────────────────────────────────────────

class TestRecoverForegroundJobs:
    def test_invalid_started_at_handled(self, job_manager):
        """Lines 1139-1140: ValueError/TypeError on started_at parsing."""
        job_manager.state = {
            "running_foreground_jobs": {
                "run1": {
                    "pid": 99999,
                    "job_id": "test",
                    "timeout": 60,
                    "started_at": "not-a-date",
                }
            }
        }

        with patch("lib.subagent_state.is_process_alive", return_value=False), \
             patch.object(job_manager, "_recover_single_job") as mock_recover:
            job_manager._recover_foreground_jobs()

        mock_recover.assert_called_once()

    def test_process_alive_past_timeout_kills(self, job_manager):
        """Lines 1145-1158: process alive past timeout gets killed."""
        started = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        job_manager.state = {
            "running_foreground_jobs": {
                "run1": {
                    "pid": 12345,
                    "job_id": "test",
                    "timeout": 60,
                    "started_at": started,
                }
            }
        }

        with patch("lib.subagent_state.is_process_alive", return_value=True), \
             patch("os.killpg") as mock_killpg, \
             patch("time.sleep"), \
             patch.object(job_manager, "_recover_single_job") as mock_recover:
            job_manager._recover_foreground_jobs()

        mock_killpg.assert_called_once()
        mock_recover.assert_called_once()

    def test_process_alive_within_timeout_waits(self, job_manager):
        """Lines 1160-1170: process alive within timeout starts background thread."""
        started = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        job_manager.state = {
            "running_foreground_jobs": {
                "run1": {
                    "pid": 12345,
                    "job_id": "test",
                    "timeout": 600,
                    "started_at": started,
                }
            }
        }

        with patch("lib.subagent_state.is_process_alive", return_value=True), \
             patch.object(job_manager, "_recover_single_job"), \
             patch("threading.Thread") as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            job_manager._recover_foreground_jobs()

            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()

    def test_process_alive_killpg_fails_tries_kill(self, job_manager):
        """Lines 1153-1156: killpg fails, falls back to kill."""
        started = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        job_manager.state = {
            "running_foreground_jobs": {
                "run1": {
                    "pid": 12345,
                    "job_id": "test",
                    "timeout": 60,
                    "started_at": started,
                }
            }
        }

        with patch("lib.subagent_state.is_process_alive", return_value=True), \
             patch("os.killpg", side_effect=OSError("No such process group")), \
             patch("os.kill") as mock_kill, \
             patch("time.sleep"), \
             patch.object(job_manager, "_recover_single_job"):
            job_manager._recover_foreground_jobs()

        mock_kill.assert_called_once_with(12345, signal.SIGKILL)


# ── _recover_single_job ─────────────────────────────────────────────

class TestRecoverSingleJob:
    def test_invalid_started_at_defaults_duration_zero(self, job_manager):
        """Lines 1203-1204: ValueError on started_at gives duration=0."""
        info = {
            "job_id": "test",
            "job_config": {"id": "test"},
            "output_dir": "/tmp/claude_jobs",
            "is_catch_up": False,
            "started_at": "garbage",
            "pid": 12345,
        }

        job_manager.state = {"running_foreground_jobs": {"run1": info}, "jobs_status": {}}

        mock_executor = MagicMock()
        mock_executor.collect_output.return_value = {"result": "done"}
        job_manager.executor = mock_executor

        with patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._recover_single_job("run1", info, timeout=5)

        # duration should be 0 (fallback)
        call_args = mock_process.call_args[0]
        assert call_args[4] == 0  # duration


# ── _write_healthcheck error ────────────────────────────────────────

class TestWriteHealthcheckError:
    def test_exception_logged(self, job_manager):
        """Lines 1250-1251: exception in healthcheck write is logged."""
        with patch("pathlib.Path.write_text", side_effect=PermissionError("denied")):
            # Should not raise
            job_manager._write_healthcheck()


# ── _start_healthcheck_thread ───────────────────────────────────────

class TestStartHealthcheckThread:
    def test_thread_started(self, job_manager):
        """Lines 1261-1263: healthcheck loop thread is started."""
        with patch("threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance
            job_manager._start_healthcheck_thread()

            mock_thread.assert_called_once()
            assert mock_thread.call_args[1]["daemon"] is True
            mock_instance.start.assert_called_once()


# ── _check_jobs_reload error ────────────────────────────────────────

class TestCheckJobsReloadError:
    def test_exception_logged(self, job_manager):
        """Lines 1297-1298: exception in jobs reload check is logged."""
        # Use a non-existent path that will fail on stat()
        job_manager.jobs_file = Path("/nonexistent/path/jobs.json")
        # Should not raise
        job_manager._check_jobs_reload()


# ── _check_subagent_announces ───────────────────────────────────────

class TestCheckSubagentAnnounces:
    def test_requeued_status_logged(self, job_manager):
        """Lines 1315-1316: requeued and max_retries_exceeded statuses."""
        results = [
            {"status": "requeued", "job_id": "sub1", "error": "network"},
            {"status": "max_retries_exceeded", "job_id": "sub2"},
        ]

        mock_subagent_state = MagicMock()
        mock_subagent_state.get_stale_subagents.return_value = []
        mock_subagent_state.fail_subagent = MagicMock()

        with patch.object(cs, "check_and_announce_completed", return_value=results), \
             patch.object(job_manager, "_update_running_subagents_progress"), \
             patch.dict("sys.modules", {"lib.subagent_state": mock_subagent_state}):
            # Should not raise
            job_manager._check_subagent_announces()


# ── _update_running_subagents_progress ──────────────────────────────

class TestUpdateRunningSubagentsProgress:
    def test_no_bot_token_returns(self, job_manager):
        """Line 1341: no bot_token returns early."""
        with patch.object(cs, "get_active_subagents", return_value={"sub1": {}}), \
             patch.object(cs, "get_telegram_config", return_value=(None, None, None)):
            job_manager._update_running_subagents_progress()

    def test_no_message_id_skips(self, job_manager):
        """Line 1351: no status_message_id skips the subagent."""
        with patch.object(cs, "get_active_subagents", return_value={
                "sub1": {"status": "running"}
             }), \
             patch.object(cs, "get_telegram_config", return_value=("token", "123", None)):
            job_manager._update_running_subagents_progress()

    def test_no_started_at_skips(self, job_manager):
        """Line 1356: no started_at skips the subagent."""
        with patch.object(cs, "get_active_subagents", return_value={
                "sub1": {"status": "running", "status_message_id": 42}
             }), \
             patch.object(cs, "get_telegram_config", return_value=("token", "123", None)):
            job_manager._update_running_subagents_progress()

    def test_invalid_started_at_gives_question_mark(self, job_manager):
        """Lines 1362-1363: invalid started_at results in age_str='?'."""
        with patch.object(cs, "get_active_subagents", return_value={
                "sub1": {
                    "status": "running",
                    "status_message_id": 42,
                    "started_at": "not-a-date",
                    "job": {"id": "sub1"},
                }
             }), \
             patch.object(cs, "get_telegram_config", return_value=("token", "123", None)), \
             patch.object(cs, "get_subagent_output", return_value=""), \
             patch.object(cs, "format_progress_message", return_value="msg") as mock_fmt, \
             patch.object(cs, "edit_telegram_message", return_value=True), \
             patch.object(cs, "update_progress_timestamp"):
            job_manager._update_running_subagents_progress()

        # age_str should be "?"
        mock_fmt.assert_called_once()
        assert mock_fmt.call_args[0][2] == "?"


# ── _reload_jobs (schedule_jobs paths) ──────────────────────────────

class TestReloadJobs:
    def test_removes_old_jobs_and_schedules_new(self, job_manager, minimal_config):
        """Lines 1401-1406, 1415-1416: removed/disabled jobs."""
        _, jobs_file, _, _ = minimal_config

        # First load with one job
        job_manager.jobs = [{"id": "old-job", "enabled": True}]

        # New config has a different job
        new_jobs = [{"id": "new-job", "enabled": True, "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        job_manager._reload_jobs()

        # scheduler.remove_job should have been called for old-job
        job_manager.scheduler.remove_job.assert_called()

    def test_interval_hours_and_days(self, job_manager, minimal_config):
        """Lines 1427-1430: interval_hours and interval_days triggers."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = []
        new_jobs = [
            {"id": "hourly", "enabled": True, "schedule": {"type": "every", "interval_hours": 2}},
            {"id": "daily", "enabled": True, "schedule": {"type": "every", "interval_days": 1}},
        ]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        job_manager._reload_jobs()
        assert job_manager.scheduler.add_job.call_count >= 2

    def test_at_schedule_type(self, job_manager, minimal_config):
        """Lines 1436-1443: 'at' schedule type with DateTrigger."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = []
        new_jobs = [
            {
                "id": "onetime",
                "enabled": True,
                "schedule": {"type": "at", "datetime": "2026-12-01T10:00:00"},
            },
        ]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        job_manager._reload_jobs()
        assert job_manager.scheduler.add_job.called

    def test_at_schedule_invalid_datetime(self, job_manager, minimal_config):
        """Lines 1440-1443: invalid datetime for 'at' type."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = []
        new_jobs = [
            {
                "id": "bad-date",
                "enabled": True,
                "schedule": {"type": "at", "datetime": "not-a-date"},
            },
        ]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        # Should not raise
        job_manager._reload_jobs()

    def test_disabled_job_removed_from_scheduler(self, job_manager, minimal_config):
        """Lines 1412-1416: disabled job gets remove_job called."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = [{"id": "was-enabled", "enabled": True}]
        new_jobs = [
            {"id": "was-enabled", "enabled": False, "schedule": {"type": "every", "interval_minutes": 30}},
        ]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        job_manager._reload_jobs()
        # remove_job should be called for the disabled job
        job_manager.scheduler.remove_job.assert_called()


# ── _detect_and_alert_crash exception path ──────────────────────────

class TestDetectAndAlertCrashException:
    def test_exception_in_crash_detection(self, job_manager):
        """Lines 1494-1495: exception during crash detection is caught."""
        job_manager.state = {
            "daemon_start_time": "not-parseable-as-datetime",
        }
        # Should not raise
        job_manager._detect_and_alert_crash()


# ── _send_startup_notification exception path ───────────────────────

class TestSendStartupNotificationException:
    def test_exception_caught(self, job_manager):
        """Lines 1512-1513: exception in startup notification is caught."""
        job_manager.state = {}
        job_manager.jobs = [{"id": "test"}]
        with patch.object(cs, "send_feed", side_effect=Exception("TG down")):
            # Should not raise
            job_manager._send_startup_notification()


# ── start() method ──────────────────────────────────────────────────

class TestStart:
    def test_start_full_flow(self, job_manager):
        """Lines 1517-1636: full start() method flow."""
        job_manager.state = {}
        job_manager.jobs = [{"id": "test"}]

        # Make scheduler.start() raise KeyboardInterrupt to exit the blocking loop
        job_manager.scheduler.start.side_effect = KeyboardInterrupt()

        with patch("signal.signal"), \
             patch("atexit.register"), \
             patch.object(job_manager, "load_jobs"), \
             patch.object(job_manager, "_recover_foreground_jobs"), \
             patch.object(job_manager, "_detect_and_alert_crash"), \
             patch.object(job_manager, "_send_startup_notification"), \
             patch.object(job_manager, "_write_healthcheck"), \
             patch.object(job_manager, "_start_healthcheck_thread"), \
             patch.object(job_manager, "detect_missed_jobs"), \
             patch.object(job_manager, "schedule_jobs"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_graceful_shutdown") as mock_shutdown:
            job_manager.start()

        mock_shutdown.assert_called_once()

    def test_start_with_main_session(self, job_manager):
        """Lines 1542-1544: main session initialization."""
        job_manager.state = {}
        job_manager.config["main_session"] = {"enabled": True}
        job_manager.scheduler.start.side_effect = SystemExit()

        with patch("signal.signal"), \
             patch("atexit.register"), \
             patch.object(job_manager, "load_jobs"), \
             patch.object(cs, "init_main_session") as mock_init, \
             patch.object(job_manager, "_recover_foreground_jobs"), \
             patch.object(job_manager, "_detect_and_alert_crash"), \
             patch.object(job_manager, "_send_startup_notification"), \
             patch.object(job_manager, "_write_healthcheck"), \
             patch.object(job_manager, "_start_healthcheck_thread"), \
             patch.object(job_manager, "detect_missed_jobs"), \
             patch.object(job_manager, "schedule_jobs"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_graceful_shutdown"):
            job_manager.start()

        mock_init.assert_called_once()

    def test_start_with_subagents(self, job_manager):
        """Lines 1547-1554: sub-agent initialization."""
        job_manager.state = {}
        job_manager.config["subagents"] = {"enabled": True}
        job_manager.scheduler.start.side_effect = KeyboardInterrupt()

        with patch("signal.signal"), \
             patch("atexit.register"), \
             patch.object(job_manager, "load_jobs"), \
             patch.object(cs, "init_subagent_state") as mock_init_sa, \
             patch.object(cs, "init_announce_handler") as mock_init_ah, \
             patch.object(cs, "recover_crashed_subagents", return_value=["sa1"]), \
             patch.object(job_manager, "_recover_foreground_jobs"), \
             patch.object(job_manager, "_detect_and_alert_crash"), \
             patch.object(job_manager, "_send_startup_notification"), \
             patch.object(job_manager, "_write_healthcheck"), \
             patch.object(job_manager, "_start_healthcheck_thread"), \
             patch.object(job_manager, "detect_missed_jobs"), \
             patch.object(job_manager, "schedule_jobs"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_graceful_shutdown"):
            job_manager.start()

        mock_init_sa.assert_called_once()
        mock_init_ah.assert_called_once()


# ── acquire_lock ────────────────────────────────────────────────────

class TestAcquireLock:
    def test_acquire_lock_success(self, tmp_path):
        """Lines 1687-1694: successful lock acquisition."""
        lock_file = tmp_path / "test.lock"
        with patch("pathlib.Path", return_value=lock_file), \
             patch("builtins.open", mock_open()) as m_open, \
             patch("fcntl.flock"):
            fd = cs.acquire_lock()
            assert fd is not None

    def test_acquire_lock_already_running(self):
        """Lines 1695-1697: IOError when another instance running."""
        with patch("builtins.open", mock_open()), \
             patch("fcntl.flock", side_effect=IOError("locked")), \
             pytest.raises(SystemExit):
            cs.acquire_lock()


# ── main() ──────────────────────────────────────────────────────────

class TestMain:
    def test_main_runs(self, tmp_path):
        """Lines 1703-1714, 1718: main entry point."""
        config_file = tmp_path / "config.yaml"
        import yaml
        config = {
            "cron": {
                "jobs_file": str(tmp_path / "cron" / "jobs.json"),
                "state_file": str(tmp_path / "cron" / "state.json"),
                "runs_log": str(tmp_path / "cron" / "runs.jsonl"),
            },
            "telegram": {"bot_token": "test", "allowed_users": [123]},
        }
        (tmp_path / "cron").mkdir(exist_ok=True)
        config_file.write_text(yaml.dump(config))
        (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"version": 1, "jobs": []}))

        mock_lock = MagicMock()
        with patch.object(cs, "acquire_lock", return_value=mock_lock), \
             patch("pathlib.Path.expanduser", return_value=config_file), \
             patch.object(cs, "ClaudeExecutor", return_value=MagicMock()), \
             patch.object(cs, "BlockingScheduler", return_value=MagicMock()), \
             patch.object(cs.JobManager, "start") as mock_start, \
             patch("fcntl.flock") as mock_flock:
            cs.main()

        mock_start.assert_called_once()
        mock_lock.close.assert_called_once()


# ── _handle_debug_signal & _atexit_handler ──────────────────────────

class TestDebugSignalAndAtexit:
    def test_handle_debug_signal(self, job_manager):
        """Line 1641-1643: debug signal handler logs warning."""
        import traceback
        frame = MagicMock()
        # Should not raise
        with patch("traceback.format_stack", return_value=["frame1\n"]):
            job_manager._handle_debug_signal(signal.SIGHUP, frame)

    def test_atexit_handler(self, job_manager):
        """Line 1648: atexit handler logs PID."""
        # Should not raise
        job_manager._atexit_handler()


# ── _handle_shutdown ────────────────────────────────────────────────

class TestHandleShutdown:
    def test_handle_shutdown_calls_graceful(self, job_manager):
        """Lines 1650-1654: SIGTERM handler calls graceful shutdown."""
        job_manager.state = {"jobs_status": {}}

        with patch.object(job_manager, "_graceful_shutdown"), \
             pytest.raises(SystemExit):
            job_manager._handle_shutdown(signal.SIGTERM, None)


# ── Additional coverage for remaining lines ─────────────────────────

class TestRecoverForegroundJobsKillFallback:
    def test_both_killpg_and_kill_fail(self, job_manager):
        """Lines 1155-1156: both killpg and kill raise ProcessLookupError."""
        started = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
        job_manager.state = {
            "running_foreground_jobs": {
                "run1": {
                    "pid": 12345,
                    "job_id": "test",
                    "timeout": 60,
                    "started_at": started,
                }
            }
        }

        with patch("lib.subagent_state.is_process_alive", return_value=True), \
             patch("os.killpg", side_effect=ProcessLookupError("gone")), \
             patch("os.kill", side_effect=ProcessLookupError("also gone")), \
             patch("time.sleep"), \
             patch.object(job_manager, "_recover_single_job"):
            job_manager._recover_foreground_jobs()


class TestReloadJobsRemoveException:
    def test_remove_job_exception_suppressed(self, job_manager, minimal_config):
        """Lines 1405-1406: exception in scheduler.remove_job for removed jobs."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = [{"id": "old-job", "enabled": True}]
        job_manager.scheduler.remove_job.side_effect = Exception("job not found")

        new_jobs = [{"id": "new-job", "enabled": True, "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        # Should not raise
        job_manager._reload_jobs()

    def test_disabled_job_remove_exception_suppressed(self, job_manager, minimal_config):
        """Lines 1415-1416: exception when removing disabled job from scheduler."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = [{"id": "my-job", "enabled": True}]
        job_manager.scheduler.remove_job.side_effect = Exception("not scheduled")

        new_jobs = [{"id": "my-job", "enabled": False, "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        # Should not raise
        job_manager._reload_jobs()

    def test_cron_schedule_type(self, job_manager, minimal_config):
        """Lines 1433-1435: cron schedule type in _reload_jobs."""
        _, jobs_file, _, _ = minimal_config

        job_manager.jobs = []
        new_jobs = [
            {"id": "cron-job", "enabled": True, "schedule": {"type": "cron", "cron": "*/5 * * * *"}},
        ]
        jobs_file.write_text(json.dumps({"version": 1, "jobs": new_jobs}))

        job_manager._reload_jobs()
        assert job_manager.scheduler.add_job.called


# Regression: Issue #4 - heartbeat containment (GH issue #4, Apr 2026).
# Silent-loop heartbeat burned ~$3.44 over 9h because nothing skipped the
# session on consecutive failures, timeouts were treated as retryable, and
# every failure spammed its own alert.
class TestCircuitBreaker:
    def _write_runs(self, runs_log: Path, entries: list):
        with open(runs_log, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_consecutive_failures_counts_only_trailing(self, job_manager, minimal_config):
        _, _, _, runs_log = minimal_config
        self._write_runs(runs_log, [
            {"job_id": "heartbeat", "status": "completed"},
            {"job_id": "heartbeat", "status": "failed"},
            {"job_id": "other",     "status": "failed"},
            {"job_id": "heartbeat", "status": "started"},
            {"job_id": "heartbeat", "status": "failed"},
            {"job_id": "heartbeat", "status": "failed"},
        ])
        # Started markers and other-job entries are skipped; the three
        # trailing heartbeat failures are counted (the 'completed' at the
        # head gates off anything older).
        assert job_manager._consecutive_failures("heartbeat", limit=5) == 3

    def test_consecutive_failures_stops_at_success(self, job_manager, minimal_config):
        _, _, _, runs_log = minimal_config
        self._write_runs(runs_log, [
            {"job_id": "heartbeat", "status": "failed"},
            {"job_id": "heartbeat", "status": "failed"},
            {"job_id": "heartbeat", "status": "completed"},
            {"job_id": "heartbeat", "status": "failed"},
        ])
        # Only the single trailing failure counts; older run before 'completed' is gated off.
        assert job_manager._consecutive_failures("heartbeat", limit=3) == 1

    def test_execute_job_skips_when_breaker_open(self, job_manager, minimal_config):
        _, _, _, runs_log = minimal_config
        self._write_runs(runs_log, [
            {"job_id": "heartbeat", "status": "failed"},
            {"job_id": "heartbeat", "status": "failed"},
            {"job_id": "heartbeat", "status": "failed"},
        ])
        job = {"id": "heartbeat", "requires_internet": False}
        job_manager._internet_available = True
        job_manager.state = {"jobs_status": {}}

        with patch.object(job_manager, "_execute_job_internal") as mock_internal, \
             patch.object(job_manager, "_send_failure_alert") as mock_alert, \
             patch.object(cs.ClaudeExecutor, "reap_stale_children"):
            job_manager._execute_job(job)

        mock_internal.assert_not_called()
        mock_alert.assert_called_once()


class TestTimeoutNotRetryable:
    def test_timeout_after_is_not_retryable(self, job_manager):
        # Regression: "Timeout after Ns" (claude_executor wall-clock timeout)
        # was being retried under the old unconditional path.
        assert job_manager._is_retryable_error("Timeout after 3630s") is False

    def test_timeout_error_still_retryable(self, job_manager):
        # Python TimeoutError exception remains retryable - it's transient.
        assert job_manager._is_retryable_error("TimeoutError: socket") is True

    def test_timeout_error_uppercase(self, job_manager):
        assert job_manager._is_retryable_error("TIMEOUT AFTER 600s") is False


class TestAlertDedup:
    def test_duplicate_alerts_within_cooldown_suppressed(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        with patch.object(cs, "send_feed") as mock_send, \
             patch.object(job_manager, "_save_state"):
            job_manager._send_failure_alert("heartbeat", "Timeout after 3630s", 3630.0)
            job_manager._send_failure_alert("heartbeat", "Timeout after 3630s", 3630.0)
            job_manager._send_failure_alert("heartbeat", "Timeout after 3630s", 3630.0)
        assert mock_send.call_count == 1

    def test_different_errors_alert_independently(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        with patch.object(cs, "send_feed") as mock_send, \
             patch.object(job_manager, "_save_state"):
            job_manager._send_failure_alert("heartbeat", "Timeout after 3630s", 3630.0)
            job_manager._send_failure_alert("heartbeat", "HTTP 500 Internal Error", 10.0)
        assert mock_send.call_count == 2

    def test_escalation_after_cooldown_elapsed(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        with patch.object(cs, "send_feed") as mock_send, \
             patch.object(job_manager, "_save_state"):
            job_manager._send_failure_alert("heartbeat", "Timeout after 3630s", 3630.0)
            # Force the last-sent timestamp back beyond the 1h cooldown.
            key = job_manager._alert_key("heartbeat", "Timeout after 3630s")
            job_manager.state["alert_history"][key]["last_sent"] -= 3700
            job_manager._send_failure_alert("heartbeat", "Timeout after 3630s", 3630.0)
        assert mock_send.call_count == 2


class TestIntakeConsumedFieldNames:
    def test_pending_before_after_fields_present(self, job_manager):
        # Regression: `had`/`remaining` read as "total in file" during silent
        # heartbeat loop and misled the reader. New fields spell out intent;
        # legacy aliases retained so existing consumers don't break.
        job = {"id": "heartbeat", "retry": {"max_attempts": 1}}
        result = {"result": "", "error": None, "cost": 0.0}
        exec_config = {
            "allowedTools": ["*"], "add_dirs": [], "session_id": None,
            "model": "sonnet", "prompt_template": "test",
        }
        now = datetime.now(timezone.utc)
        intake_before = {"telegram": {"total": 100, "new": 10}}
        intake_after = {"telegram": {"total": 100, "new": 3}}
        job_manager.state = {"jobs_status": {}}

        logged = {}
        with patch.object(job_manager, "_get_vadimgest_stats", return_value=intake_after), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_log_run", side_effect=lambda e: logged.update(e)), \
             patch.object(cs, "register_session"), \
             patch.object(cs, "send_feed"):
            job_manager._process_job_result(
                job, "run1", result, now, 10.0, exec_config, intake_before, None, 0
            )
        tel = logged["intake"]["consumed"]["telegram"]
        assert tel["pending_before"] == 10
        assert tel["consumed"] == 7
        assert tel["pending_after"] == 3
        # Legacy aliases survive one release cycle.
        assert tel["had"] == 10
        assert tel["remaining"] == 3
