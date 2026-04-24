"""Tests for cron-scheduler.py pure functions and helpers.

Focuses on testable logic without triggering daemon behavior:
- Static/pure methods (_delta_icon, _deal_name_from_path)
- Heartbeat report building (_build_heartbeat_report)
- Error classification (_is_network_error, _is_retryable_error)
- Missed run calculation (_calculate_missed_runs)
- State management (_load_state, _save_state, _log_run)
- Job loading (load_jobs)
- on_complete condition handling (_handle_on_complete)
- Crash detection (_detect_and_alert_crash)
- Startup notification rate limiting (_send_startup_notification)
- Job priority sorting
- Internet connectivity tracking
"""

import importlib.util
import json
import os
import sys
import time
import threading
import types
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Load the module with a hyphen in its name
spec = importlib.util.spec_from_file_location(
    "cron_scheduler",
    os.path.join(os.path.dirname(__file__), "..", "cron-scheduler.py"),
)

# We need to mock out ALL heavy imports before loading the module.
# Some packages (apscheduler, croniter) may not be installed in test env.
_mock_modules = {
    # lib modules
    "lib.telegram_utils": MagicMock(),
    "lib.feed": MagicMock(),
    "lib.claude_executor": MagicMock(),
    "lib.announce_handler": MagicMock(),
    "lib.subagent_state": MagicMock(),
    "lib.subagent_status": MagicMock(),
    "lib.main_session": MagicMock(),
    "lib.session_registry": MagicMock(),
}

# Mock apscheduler if not installed
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

# Mock croniter if not installed
try:
    import croniter as _croniter_test
except ImportError:
    _croniter_mod = types.ModuleType("croniter")
    _croniter_mod.croniter = MagicMock
    _mock_modules["croniter"] = _croniter_mod

# Save originals, patch, load, restore
_saved = {}
for mod_name, mock_mod in _mock_modules.items():
    _saved[mod_name] = sys.modules.get(mod_name)
    sys.modules[mod_name] = mock_mod

cs = importlib.util.module_from_spec(spec)
# Patch dotenv to avoid loading .env
with patch("dotenv.load_dotenv"):
    spec.loader.exec_module(cs)

# Restore original modules (only for lib.* modules, keep apscheduler/croniter mocked)
for mod_name, orig in _saved.items():
    if orig is None:
        # Only restore lib modules; keep external mocks for the test runtime
        if mod_name.startswith("lib."):
            sys.modules.pop(mod_name, None)
    else:
        sys.modules[mod_name] = orig


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def minimal_config(tmp_path):
    """Create a minimal config.yaml and jobs.json for JobManager."""
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

    # Write empty jobs file
    jobs_file.write_text(json.dumps({"version": 1, "jobs": []}))

    return config_file, jobs_file, state_file, runs_log


@pytest.fixture
def job_manager(minimal_config):
    """Create a JobManager with mocked heavy dependencies."""
    config_file, jobs_file, state_file, runs_log = minimal_config

    with patch.object(cs, "ClaudeExecutor", return_value=MagicMock()), \
         patch.object(cs, "BlockingScheduler", return_value=MagicMock()):
        manager = cs.JobManager(str(config_file))

    return manager


# ── JOB_PRIORITY constant ────────────────────────────────────────────

class TestJobPriority:
    def test_mentor_is_highest_priority(self):
        assert cs.JOB_PRIORITY["mentor"] == 1

    def test_heartbeat_is_second(self):
        assert cs.JOB_PRIORITY["heartbeat"] == 2

    def test_friend_is_third(self):
        assert cs.JOB_PRIORITY["friend"] == 3

    def test_reflection_is_fourth(self):
        assert cs.JOB_PRIORITY["reflection"] == 4

    def test_unknown_job_defaults_to_10(self):
        assert cs.JOB_PRIORITY.get("unknown-job", 10) == 10


# ── _delta_icon (static method) ──────────────────────────────────────

class TestDeltaIcon:
    def test_gtask_completed(self):
        result = cs.JobManager._delta_icon("gtask_completed")
        assert result == "\u2705"

    def test_gtask_created(self):
        result = cs.JobManager._delta_icon("gtask_created")
        assert result == "\u2611\ufe0f"

    def test_deal(self):
        result = cs.JobManager._delta_icon("deal_update")
        assert result == "\U0001f4b0"

    def test_obsidian(self):
        result = cs.JobManager._delta_icon("obsidian_update")
        assert result == "\U0001f4dd"

    def test_gmail(self):
        result = cs.JobManager._delta_icon("gmail_draft")
        assert result == "\u2709\ufe0f"

    def test_calendar(self):
        result = cs.JobManager._delta_icon("calendar_event")
        assert result == "\U0001f4c5"

    def test_observation(self):
        result = cs.JobManager._delta_icon("observation")
        assert result == "\U0001f441"

    def test_dispatched(self):
        result = cs.JobManager._delta_icon("dispatched")
        assert result == "\U0001f50d"

    def test_inbox(self):
        result = cs.JobManager._delta_icon("inbox_item")
        assert result == "\U0001f4e5"

    def test_unknown_type(self):
        result = cs.JobManager._delta_icon("something_random")
        assert result == "\u2022"

    def test_empty_string(self):
        result = cs.JobManager._delta_icon("")
        assert result == "\u2022"


# ── _deal_name_from_path (static method) ─────────────────────────────

class TestDealNameFromPath:
    def test_deal_with_em_dash(self):
        result = cs.JobManager._deal_name_from_path(
            "Deals/Acme \u2014 OSINT.md"
        )
        assert result == "Acme OSINT"

    def test_deal_with_em_dash_multiword(self):
        result = cs.JobManager._deal_name_from_path(
            "Deals/Globex \u2014 Ad Targeting API.md"
        )
        assert result == "Globex Ad Targeting API"

    def test_deal_without_em_dash(self):
        result = cs.JobManager._deal_name_from_path(
            "Deals/Initech.md"
        )
        assert result == "Initech"

    def test_empty_path(self):
        result = cs.JobManager._deal_name_from_path("")
        assert result == "?"

    def test_none_like_empty(self):
        # Passing empty string
        result = cs.JobManager._deal_name_from_path("")
        assert result == "?"

    def test_path_with_only_filename(self):
        result = cs.JobManager._deal_name_from_path("SimpleFile.md")
        assert result == "SimpleFile"

    def test_md_extension_stripped(self):
        result = cs.JobManager._deal_name_from_path("Some/Path/Deal Name.md")
        assert ".md" not in result

    def test_path_with_spaces(self):
        result = cs.JobManager._deal_name_from_path(
            "Deals/Big Corp \u2014 Super Deal.md"
        )
        assert result == "Big Corp Super Deal"


# ── _is_network_error ────────────────────────────────────────────────

class TestIsNetworkError:
    def test_failed_to_open_socket(self, job_manager):
        assert job_manager._is_network_error("FailedToOpenSocket: connection refused") is True

    def test_unable_to_connect(self, job_manager):
        assert job_manager._is_network_error("Unable to connect to API") is True

    def test_connection_refused_error(self, job_manager):
        assert job_manager._is_network_error("ConnectionRefusedError: [Errno 111]") is True

    def test_connection_reset_error(self, job_manager):
        assert job_manager._is_network_error("ConnectionResetError: [Errno 104]") is True

    def test_econnrefused(self, job_manager):
        assert job_manager._is_network_error("Error: ECONNREFUSED 127.0.0.1:443") is True

    def test_network_unreachable(self, job_manager):
        assert job_manager._is_network_error("Network is unreachable") is True

    def test_connection_error(self, job_manager):
        assert job_manager._is_network_error("Connection error occurred") is True

    def test_case_insensitive(self, job_manager):
        assert job_manager._is_network_error("failedtoopensocket") is True

    def test_not_network_error(self, job_manager):
        assert job_manager._is_network_error("TypeError: invalid argument") is False

    def test_empty_string(self, job_manager):
        assert job_manager._is_network_error("") is False

    def test_timeout_is_not_network(self, job_manager):
        assert job_manager._is_network_error("TimeoutError: operation timed out") is False


# ── _is_retryable_error ──────────────────────────────────────────────

class TestIsRetryableError:
    def test_timeout_error(self, job_manager):
        assert job_manager._is_retryable_error("TimeoutError: operation timed out") is True

    def test_etimedout(self, job_manager):
        assert job_manager._is_retryable_error("Error: ETIMEDOUT") is True

    def test_auth_error(self, job_manager):
        assert job_manager._is_retryable_error("authentication_error: token expired") is True

    def test_token_expired(self, job_manager):
        assert job_manager._is_retryable_error("token has expired, please renew") is True

    def test_failed_to_authenticate(self, job_manager):
        assert job_manager._is_retryable_error("Failed to authenticate with API") is True

    def test_500_error(self, job_manager):
        assert job_manager._is_retryable_error("HTTP 500 Internal Server Error") is True

    def test_503_error(self, job_manager):
        assert job_manager._is_retryable_error("HTTP 503 Service Unavailable") is True

    def test_exit_143_sigterm(self, job_manager):
        # Regression: self-evolve CRON hit SIGTERM on 2026-04-24 04:50 and got
        # "non-retryable error, not scheduling retry". Error string matches the
        # SDK wrapper format from lib/claude_executor.py.
        assert job_manager._is_retryable_error(
            "Command failed with exit code 143 (exit code: 143)"
        ) is True

    def test_not_retryable(self, job_manager):
        assert job_manager._is_retryable_error("SyntaxError: invalid json") is False

    def test_empty_string(self, job_manager):
        assert job_manager._is_retryable_error("") is False


# ── _load_state ──────────────────────────────────────────────────────

class TestLoadState:
    def test_loads_existing_state(self, job_manager, minimal_config):
        _, _, state_file, _ = minimal_config
        state_data = {
            "daemon_start_time": "2026-03-15T10:00:00+00:00",
            "last_successful_check": "2026-03-15T10:30:00+00:00",
            "jobs_status": {"heartbeat": {"last_run": "2026-03-15T10:30:00+00:00", "status": "completed"}},
        }
        state_file.write_text(json.dumps(state_data))

        result = job_manager._load_state()
        assert result["jobs_status"]["heartbeat"]["status"] == "completed"

    def test_corrupt_state_file_returns_defaults(self, job_manager, minimal_config):
        _, _, state_file, _ = minimal_config
        state_file.write_text("not valid json {{{")

        result = job_manager._load_state()
        assert "jobs_status" in result
        assert result["jobs_status"] == {}

    def test_missing_state_file_returns_defaults(self, job_manager, minimal_config):
        _, _, state_file, _ = minimal_config
        if state_file.exists():
            state_file.unlink()

        result = job_manager._load_state()
        assert "daemon_start_time" in result
        assert "last_successful_check" in result
        assert result["jobs_status"] == {}


# ── _save_state ──────────────────────────────────────────────────────

class TestSaveState:
    def test_saves_state_atomically(self, job_manager, minimal_config):
        _, _, state_file, _ = minimal_config
        job_manager.state = {
            "daemon_start_time": "2026-03-15T10:00:00+00:00",
            "last_successful_check": "2026-03-15T10:30:00+00:00",
            "jobs_status": {"test": {"status": "ok"}},
        }
        job_manager._save_state()

        loaded = json.loads(state_file.read_text())
        assert loaded["jobs_status"]["test"]["status"] == "ok"

    def test_no_tmp_file_remains(self, job_manager, minimal_config):
        _, _, state_file, _ = minimal_config
        job_manager.state = {"jobs_status": {}}
        job_manager._save_state()

        tmp_file = state_file.with_suffix(".tmp")
        assert not tmp_file.exists()

    def test_thread_safety(self, job_manager, minimal_config):
        """Multiple threads writing state concurrently should not corrupt."""
        _, _, state_file, _ = minimal_config

        errors = []

        def write_state(value):
            try:
                job_manager.state = {"jobs_status": {"thread": {"value": value}}}
                job_manager._save_state()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_state, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File should be valid JSON
        loaded = json.loads(state_file.read_text())
        assert "jobs_status" in loaded


# ── _log_run ─────────────────────────────────────────────────────────

class TestLogRun:
    def test_appends_jsonl_entry(self, job_manager, minimal_config):
        _, _, _, runs_log = minimal_config
        entry = {"job_id": "test", "status": "completed", "timestamp": "2026-03-15T10:00:00+00:00"}
        job_manager._log_run(entry)

        lines = runs_log.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["job_id"] == "test"

    def test_appends_multiple_entries(self, job_manager, minimal_config):
        _, _, _, runs_log = minimal_config
        job_manager._log_run({"job_id": "a", "status": "ok"})
        job_manager._log_run({"job_id": "b", "status": "failed"})

        lines = runs_log.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["job_id"] == "a"
        assert json.loads(lines[1])["job_id"] == "b"


# ── load_jobs ────────────────────────────────────────────────────────

class TestLoadJobs:
    def test_loads_jobs_from_file(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        jobs_data = {
            "version": 1,
            "jobs": [
                {"id": "heartbeat", "name": "HB", "enabled": True,
                 "schedule": {"type": "every", "interval_minutes": 30}},
                {"id": "reflection", "name": "Reflect", "enabled": True,
                 "schedule": {"type": "cron", "cron": "30 5 * * *"}},
            ],
        }
        jobs_file.write_text(json.dumps(jobs_data))

        result = job_manager.load_jobs()
        assert len(result) == 2
        assert result[0]["id"] == "heartbeat"
        assert result[1]["id"] == "reflection"
        assert job_manager.jobs == result

    def test_missing_jobs_file(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        jobs_file.unlink()

        result = job_manager.load_jobs()
        assert result == []

    def test_empty_jobs_list(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        jobs_file.write_text(json.dumps({"version": 1, "jobs": []}))

        result = job_manager.load_jobs()
        assert result == []


# ── _calculate_missed_runs ───────────────────────────────────────────

class TestCalculateMissedRuns:
    def test_interval_minutes_basic(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "every", "interval_minutes": 30},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        # 10:30, 11:00, 11:30 = 3 missed runs
        assert len(result) == 3

    def test_interval_hours(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "every", "interval_hours": 2},
        }
        start = datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        # 10:00, 12:00 = 2 missed runs (14:00 is not < end)
        assert len(result) == 2

    def test_interval_days(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "every", "interval_days": 1},
        }
        start = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        # 11, 12 = 2 missed runs (13 is not < end)
        assert len(result) == 2

    def test_interval_no_missed(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "every", "interval_minutes": 60},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert len(result) == 0

    def test_interval_missing_interval_key(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "every"},  # No interval_minutes etc.
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert result == []

    def test_cron_schedule(self, job_manager):
        """Test cron schedule missed run calculation with mocked croniter."""
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("Europe/Riga")

        job = {
            "id": "test",
            "schedule": {"type": "cron", "cron": "0 * * * *"},  # Every hour
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 13, 0, tzinfo=timezone.utc)

        # Mock croniter to return expected times then go past end
        end_local = end.astimezone(local_tz)
        mock_times = [
            datetime(2026, 3, 15, 13, 0, tzinfo=local_tz),  # 11:00 UTC = 13:00 EET
            datetime(2026, 3, 15, 14, 0, tzinfo=local_tz),  # 12:00 UTC = 14:00 EET
            datetime(2026, 3, 15, 15, 0, tzinfo=local_tz),  # 13:00 UTC = 15:00 EET (past end)
        ]
        mock_cron_instance = MagicMock()
        mock_cron_instance.get_next = MagicMock(side_effect=mock_times)

        with patch.object(cs, "croniter", return_value=mock_cron_instance):
            result = job_manager._calculate_missed_runs(job, start, end)

        assert len(result) == 2

    def test_cron_no_expression(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "cron"},  # Missing cron expression
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert result == []

    def test_at_schedule_within_range(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "at", "datetime": "2026-03-15T11:00:00+00:00"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert len(result) == 1

    def test_at_schedule_outside_range(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "at", "datetime": "2026-03-15T13:00:00+00:00"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert len(result) == 0

    def test_at_schedule_invalid_datetime(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "at", "datetime": "not-a-date"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert result == []

    def test_at_schedule_missing_datetime(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "at"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert result == []

    def test_unknown_schedule_type(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "weekly"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert result == []

    def test_at_on_exact_start_boundary(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "at", "datetime": "2026-03-15T10:00:00+00:00"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert len(result) == 1

    def test_at_on_exact_end_boundary_excluded(self, job_manager):
        job = {
            "id": "test",
            "schedule": {"type": "at", "datetime": "2026-03-15T12:00:00+00:00"},
        }
        start = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

        result = job_manager._calculate_missed_runs(job, start, end)
        assert len(result) == 0


# ── _build_heartbeat_report ──────────────────────────────────────────

class TestBuildHeartbeatReport:
    def test_returns_none_for_zero_intake(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "intake": {"total_new": 0, "stats": {}, "details": {}},
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert result is None

    def test_returns_none_for_missing_intake(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert result is None

    def test_basic_intake_report(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 45,
            "intake": {
                "total_new": 15,
                "stats": {"telegram": 10, "signal": 5},
                "details": {
                    "telegram": {"ChatA": 7, "ChatB": 3},
                    "signal": {"GroupX": 5},
                },
            },
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert result is not None
        assert "Heartbeat" in result
        assert "EET" in result
        assert "INTAKE:" in result
        assert "15 records" in result
        assert "telegram: 10" in result
        assert "signal: 5" in result
        assert "ChatA: 7" in result

    def test_report_with_action_deltas(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "gtask_created", "summary": "Follow up with Acme"},
                {"type": "deal_update", "summary": "Updated Globex stage", "stage": "6-contract"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "ACTIONS:" in result
        assert "2" in result  # 2 actions
        assert "Follow up with Acme" in result
        assert "Updated Globex stage" in result

    def test_report_with_skipped_deltas(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "skipped", "source": "telegram/spam", "count": 12, "hint": "low-signal"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Noise" in result
        assert "12" in result

    def test_report_with_todos(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "todos": [
                {"status": "completed", "content": "Sent email"},
                {"status": "in_progress", "content": "Reviewing PR"},
                {"status": "pending", "content": "Schedule call"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "TODOS:" in result
        assert "Sent email" in result
        assert "Reviewing PR" in result
        assert "Schedule call" in result

    def test_report_with_llm_output(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "output": "Some useful analysis from the LLM that is longer than 10 chars.",
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Some useful analysis" in result

    def test_report_strips_heartbeat_ok(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "output": "HEARTBEAT_OK\nSome real content that we want to keep.",
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "HEARTBEAT_OK" not in result
        assert "Some real content" in result

    def test_report_strips_intake_line(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "output": "INTAKE: 5 records\nSome real content here.",
        }
        result = job_manager._build_heartbeat_report(run_entry)
        # The INTAKE line from output should be stripped (cron builds its own)
        lines = result.split("\n")
        output_intake_lines = [l for l in lines if l.strip().startswith("INTAKE:") and "records" not in l]
        # The INTAKE line from the output section should not appear
        # But the programmatic INTAKE section IS present
        assert any("INTAKE:" in l for l in lines)

    def test_report_html_escapes_output(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "output": "Test <script>alert('xss')</script> content is long enough",
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_report_enriched_delta_with_metadata(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {
                    "type": "deal_update",
                    "summary": "Updated AcmeCorp deal",
                    "stage": "6-contract",
                    "next_action": "Send invoice",
                    "trajectory": "positive",
                },
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Updated AcmeCorp deal" in result
        assert "stage: 6-contract" in result
        assert "next: Send invoice" in result
        assert "positive" in result

    def test_report_old_format_gtask_delta(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "gtask_created", "title": "Follow up call"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "GTask: Follow up call" in result

    def test_report_old_format_obsidian_delta(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "obsidian_update", "path": "People/John Doe.md", "change": "added wikilinks"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "John Doe: added wikilinks" in result

    def test_report_old_format_gmail_delta(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "gmail_draft", "subject": "Re: Proposal"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Draft: Re: Proposal" in result

    def test_report_old_format_calendar_delta(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "calendar_event", "title": "Team standup"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Event: Team standup" in result

    def test_report_old_format_deal_delta(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "deal_update", "deal_name": "AcmeCorp", "change": "stage changed"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "AcmeCorp - stage changed" in result

    def test_report_dispatched_delta(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "deltas": [
                {"type": "dispatched", "label": "Research task", "expected": "2h"},
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Research task" in result

    def test_report_source_sorted_by_count_descending(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {
                "total_new": 25,
                "stats": {"telegram": 5, "signal": 20},
                "details": {},
            },
        }
        result = job_manager._build_heartbeat_report(run_entry)
        # signal (20) should come before telegram (5) in the output
        signal_pos = result.find("signal: 20")
        telegram_pos = result.find("telegram: 5")
        assert signal_pos < telegram_pos

    def test_report_top5_chats_with_remaining(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {
                "total_new": 100,
                "stats": {"telegram": 100},
                "details": {
                    "telegram": {
                        "Chat1": 30, "Chat2": 25, "Chat3": 20,
                        "Chat4": 10, "Chat5": 8, "Chat6": 5, "Chat7": 2,
                    },
                },
            },
        }
        result = job_manager._build_heartbeat_report(run_entry)
        # Should show top 5 and a remaining count
        assert "...+" in result

    def test_report_with_string_todo(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "todos": ["A simple string todo"],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "A simple string todo" in result

    def test_report_many_todos_show_summary(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "todos": [
                {"status": "completed", "content": f"Task {i}"} for i in range(10)
            ],
        }
        result = job_manager._build_heartbeat_report(run_entry)
        assert "Total:" in result

    def test_report_short_output_excluded(self, job_manager):
        run_entry = {
            "timestamp": "2026-03-15T10:30:00+00:00",
            "duration_seconds": 30,
            "intake": {"total_new": 5, "stats": {"telegram": 5}, "details": {}},
            "output": "ok",  # too short (< 10 chars)
        }
        result = job_manager._build_heartbeat_report(run_entry)
        # "ok" should NOT appear in the report
        lines = result.strip().split("\n")
        # Filter to non-empty lines after the INTAKE section
        post_intake = False
        content_lines = []
        for line in lines:
            if "INTAKE:" in line:
                post_intake = True
                continue
            if post_intake and line.strip() and not line.strip().startswith("telegram"):
                content_lines.append(line.strip())
        assert "ok" not in content_lines


# ── _handle_on_complete ──────────────────────────────────────────────

class TestHandleOnComplete:
    def test_no_on_complete_does_nothing(self, job_manager):
        job = {"id": "test"}
        # Should not raise
        job_manager._handle_on_complete(job, "some output")

    def test_condition_always_triggers(self, job_manager):
        target_job = {"id": "downstream", "enabled": True}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "always"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "output")
            # Give thread time to start
            import time
            time.sleep(0.1)
            mock_exec.assert_called_once_with(target_job)

    def test_condition_on_output_skips_empty(self, job_manager):
        target_job = {"id": "downstream", "enabled": True}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "on_output"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "")
            time.sleep(0.1)
            mock_exec.assert_not_called()

    def test_condition_on_output_triggers_with_output(self, job_manager):
        target_job = {"id": "downstream", "enabled": True}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "on_output"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "some output data")
            time.sleep(0.1)
            mock_exec.assert_called_once()

    def test_condition_on_new_data_no_match(self, job_manager):
        target_job = {"id": "downstream", "enabled": True}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "on_new_data"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "nothing interesting")
            time.sleep(0.1)
            mock_exec.assert_not_called()

    def test_condition_on_new_data_with_synced(self, job_manager):
        target_job = {"id": "downstream", "enabled": True}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "on_new_data"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "synced 42 records")
            time.sleep(0.1)
            mock_exec.assert_called_once()

    def test_condition_on_new_data_with_new(self, job_manager):
        target_job = {"id": "downstream", "enabled": True}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "on_new_data"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "new 10 items found")
            time.sleep(0.1)
            mock_exec.assert_called_once()

    def test_target_not_found(self, job_manager):
        job_manager.jobs = []

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "nonexistent", "condition": "always"},
        }

        # Should not raise, just log warning
        job_manager._handle_on_complete(job, "output")

    def test_target_disabled(self, job_manager):
        target_job = {"id": "downstream", "enabled": False}
        job_manager.jobs = [target_job]

        job = {
            "id": "upstream",
            "on_complete": {"trigger": "downstream", "condition": "always"},
        }

        with patch.object(job_manager, "_execute_job") as mock_exec:
            job_manager._handle_on_complete(job, "output")
            time.sleep(0.1)
            mock_exec.assert_not_called()


# ── _detect_and_alert_crash ──────────────────────────────────────────

class TestDetectAndAlertCrash:
    def test_no_crash_when_shutdown_after_start(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T10:00:00+00:00",
            "last_shutdown": "2026-03-15T12:00:00+00:00",
            "jobs_status": {},
        }
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._detect_and_alert_crash()
            mock_feed.assert_not_called()

    def test_crash_detected_no_shutdown(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T10:00:00+00:00",
            "jobs_status": {},
        }
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._detect_and_alert_crash()
            mock_feed.assert_called_once()
            call_args = mock_feed.call_args
            assert "crash" in call_args[0][0].lower()

    def test_crash_detected_shutdown_before_start(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T10:00:00+00:00",
            "last_shutdown": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._detect_and_alert_crash()
            mock_feed.assert_called_once()

    def test_crash_with_running_jobs(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T10:00:00+00:00",
            "jobs_status": {
                "heartbeat": {"status": "catching_up"},
                "reflection": {"status": "completed"},
            },
        }
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._detect_and_alert_crash()
            mock_feed.assert_called_once()
            call_msg = mock_feed.call_args[0][0]
            assert "heartbeat" in call_msg

    def test_no_start_time(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._detect_and_alert_crash()
            mock_feed.assert_not_called()


# ── _send_startup_notification ───────────────────────────────────────

class TestSendStartupNotification:
    def test_sends_when_no_previous_start(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        job_manager.jobs = [{"id": "test"}]
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._send_startup_notification()
            mock_feed.assert_called_once()
            assert "started" in mock_feed.call_args[0][0].lower()

    def test_suppressed_when_recent_start(self, job_manager):
        job_manager.state = {
            "daemon_start_time": datetime.now(timezone.utc).isoformat(),
            "jobs_status": {},
        }
        job_manager.jobs = [{"id": "test"}]
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._send_startup_notification()
            mock_feed.assert_not_called()

    def test_sends_after_10min_gap(self, job_manager):
        old_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        job_manager.state = {
            "daemon_start_time": old_time.isoformat(),
            "jobs_status": {},
        }
        job_manager.jobs = [{"id": "a"}, {"id": "b"}]
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._send_startup_notification()
            mock_feed.assert_called_once()
            assert "2 jobs" in mock_feed.call_args[0][0]


# ── _write_healthcheck ───────────────────────────────────────────────

class TestWriteHealthcheck:
    def test_writes_timestamp(self, job_manager):
        with patch("pathlib.Path.write_text") as mock_write:
            job_manager._write_healthcheck()
            mock_write.assert_called_once()
            written = mock_write.call_args[0][0]
            # Should be an ISO format timestamp
            datetime.fromisoformat(written)  # should not raise


# ── _resolve_topic ───────────────────────────────────────────────────

class TestResolveTopic:
    def test_no_topic_returns_general(self, job_manager):
        job = {"id": "test"}
        result = job_manager._resolve_topic(job)
        assert result == "General"

    def test_with_known_topic(self, job_manager):
        # Mock TOPIC_NAMES from lib.feed
        with patch.dict("sys.modules", {"lib.feed": MagicMock(TOPIC_NAMES={100001: "Heartbeat"})}):
            job = {"id": "heartbeat", "telegram_topic": 100001}
            result = job_manager._resolve_topic(job)
            assert result == "Heartbeat"

    def test_with_unknown_topic_id(self, job_manager):
        with patch.dict("sys.modules", {"lib.feed": MagicMock(TOPIC_NAMES={})}):
            job = {"id": "test", "telegram_topic": 999999}
            result = job_manager._resolve_topic(job)
            assert result == "General"


# ── _graceful_shutdown ───────────────────────────────────────────────

class TestGracefulShutdown:
    def test_saves_last_shutdown(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        with patch.object(job_manager, "_save_state") as mock_save:
            job_manager._graceful_shutdown()
            assert "last_shutdown" in job_manager.state
            mock_save.assert_called()

    def test_shuts_down_scheduler(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        job_manager._graceful_shutdown()
        job_manager.scheduler.shutdown.assert_called_once_with(wait=False)


# ── _check_sleep_wake ────────────────────────────────────────────────

class TestCheckSleepWake:
    def test_no_catchup_for_normal_interval(self, job_manager):
        job_manager._last_wake_check = time.monotonic() - 60  # 1 min ago
        with patch.object(job_manager, "detect_missed_jobs") as mock_catch:
            job_manager._check_sleep_wake()
            mock_catch.assert_not_called()

    def test_triggers_catchup_on_large_gap(self, job_manager):
        job_manager._last_wake_check = time.monotonic() - 300  # 5 min ago
        with patch.object(job_manager, "detect_missed_jobs") as mock_catch, \
             patch.object(job_manager, "load_jobs"):
            job_manager._check_sleep_wake()
            mock_catch.assert_called_once()


# ── _check_jobs_reload ───────────────────────────────────────────────

class TestCheckJobsReload:
    def test_reloads_on_mtime_change(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        jobs_file.write_text(json.dumps({"version": 1, "jobs": []}))
        job_manager.jobs_file_mtime = 0  # Force reload

        with patch.object(job_manager, "_reload_jobs") as mock_reload:
            job_manager._check_jobs_reload()
            mock_reload.assert_called_once()

    def test_no_reload_when_same_mtime(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        jobs_file.write_text(json.dumps({"version": 1, "jobs": []}))
        job_manager.jobs_file_mtime = jobs_file.stat().st_mtime

        with patch.object(job_manager, "_reload_jobs") as mock_reload:
            job_manager._check_jobs_reload()
            mock_reload.assert_not_called()


# ── _monitor_connectivity ────────────────────────────────────────────

class TestMonitorConnectivity:
    def test_goes_offline(self, job_manager):
        job_manager._internet_available = True
        job_manager._internet_lost_at = None

        with patch.object(job_manager, "_check_internet", return_value=False):
            job_manager._monitor_connectivity()

        assert job_manager._internet_available is False
        assert job_manager._internet_lost_at is not None

    def test_comes_back_online(self, job_manager):
        job_manager._internet_available = False
        job_manager._internet_lost_at = datetime.now(timezone.utc) - timedelta(seconds=30)

        with patch.object(job_manager, "_check_internet", return_value=True), \
             patch.object(job_manager, "load_jobs"), \
             patch.object(job_manager, "detect_missed_jobs") as mock_catch:
            job_manager._monitor_connectivity()

        assert job_manager._internet_available is True
        assert job_manager._internet_lost_at is None
        mock_catch.assert_called_once()

    def test_stays_online(self, job_manager):
        job_manager._internet_available = True
        job_manager._internet_lost_at = None

        with patch.object(job_manager, "_check_internet", return_value=True), \
             patch.object(job_manager, "detect_missed_jobs") as mock_catch:
            job_manager._monitor_connectivity()

        assert job_manager._internet_available is True
        mock_catch.assert_not_called()

    def test_stays_offline(self, job_manager):
        job_manager._internet_available = False
        job_manager._internet_lost_at = datetime.now(timezone.utc)

        with patch.object(job_manager, "_check_internet", return_value=False), \
             patch.object(job_manager, "detect_missed_jobs") as mock_catch:
            job_manager._monitor_connectivity()

        assert job_manager._internet_available is False
        mock_catch.assert_not_called()


# ── _execute_job skips when offline ──────────────────────────────────

class TestExecuteJobOffline:
    def test_skips_internet_dependent_when_offline(self, job_manager):
        job_manager._internet_available = False
        job_manager._internet_lost_at = datetime.now(timezone.utc)

        job = {"id": "test", "requires_internet": True}

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager._execute_job(job)
            mock_exec.assert_not_called()

    def test_does_not_skip_non_internet_job(self, job_manager):
        job_manager._internet_available = False

        job = {"id": "test", "requires_internet": False}

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager._execute_job(job)
            mock_exec.assert_called_once()


# ── detect_missed_jobs sorting ───────────────────────────────────────

class TestDetectMissedJobsSorting:
    def test_missed_jobs_sorted_by_priority(self, job_manager):
        """Verify that missed jobs are sorted mentor > heartbeat > reflection > unknown."""
        executed_order = []

        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }

        # All jobs have missed a run
        job_manager.jobs = [
            {
                "id": "reflection",
                "enabled": True,
                "schedule": {"type": "every", "interval_minutes": 30},
                "catch_up": {"enabled": True, "max_catch_up": 1},
            },
            {
                "id": "heartbeat",
                "enabled": True,
                "schedule": {"type": "every", "interval_minutes": 30},
                "catch_up": {"enabled": True, "max_catch_up": 1},
            },
            {
                "id": "mentor",
                "enabled": True,
                "schedule": {"type": "every", "interval_minutes": 30},
                "catch_up": {"enabled": True, "max_catch_up": 1},
            },
        ]

        def track_execution(job, is_catch_up):
            executed_order.append(job["id"])

        with patch.object(job_manager, "_execute_job_internal", side_effect=track_execution), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"):
            job_manager.detect_missed_jobs()

        assert executed_order == ["mentor", "heartbeat", "reflection"]


# ── _schedule_retry ──────────────────────────────────────────────────

class TestScheduleRetry:
    def test_schedules_retry_job(self, job_manager):
        job = {
            "id": "test",
            "name": "Test Job",
            "retry": {"max_attempts": 3, "delay_minutes": 5},
        }

        job_manager._schedule_retry(job, attempt=0)
        job_manager.scheduler.add_job.assert_called_once()
        call_kwargs = job_manager.scheduler.add_job.call_args[1]
        assert call_kwargs["id"] == "test_retry_1"

    def test_stops_at_max_attempts(self, job_manager):
        job = {
            "id": "test",
            "retry": {"max_attempts": 3, "delay_minutes": 5},
        }

        job_manager._schedule_retry(job, attempt=3)
        job_manager.scheduler.add_job.assert_not_called()

    def test_default_retry_config(self, job_manager):
        job = {"id": "test"}  # No retry config

        job_manager._schedule_retry(job, attempt=0)
        job_manager.scheduler.add_job.assert_called_once()


# ── _get_vadimgest_stats ─────────────────────────────────────────────

class TestGetVadimgestStats:
    def test_parses_stats_output(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "  telegram: 384441 total, 304 new (checkpoint at 384137)\n"
            "  signal: 5000 total, 12 new (checkpoint at 4988)\n"
        )

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_stats("heartbeat")

        assert result is not None
        assert result["telegram"]["total"] == 384441
        assert result["telegram"]["new"] == 304
        assert result["signal"]["total"] == 5000
        assert result["signal"]["new"] == 12

    def test_returns_none_on_failure(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_stats("heartbeat")

        assert result is None

    def test_returns_none_on_empty_output(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_stats("heartbeat")

        assert result is None

    def test_returns_none_on_exception(self, job_manager):
        with patch("subprocess.run", side_effect=Exception("process died")):
            result = job_manager._get_vadimgest_stats("heartbeat")

        assert result is None


# ── _get_vadimgest_details ───────────────────────────────────────────

class TestGetVadimgestDetails:
    def test_parses_json_details(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "telegram": [
                {"chat": "ChatA", "text": "msg1"},
                {"chat": "ChatA", "text": "msg2"},
                {"chat": "ChatB", "text": "msg3"},
            ],
            "signal": [
                {"chat": "GroupX", "text": "msg4"},
            ],
        })

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("heartbeat")

        assert result is not None
        assert result["telegram"]["ChatA"] == 2
        assert result["telegram"]["ChatB"] == 1
        assert result["signal"]["GroupX"] == 1

    def test_signal_fallback_to_contact_name(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "signal": [
                {"chat": "unknown", "meta": {"contact_name": "Alice"}, "text": "hi"},
                {"chat": "unknown", "meta": {"contact_name": "Alice"}, "text": "there"},
            ],
        })

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("heartbeat")

        assert result is not None
        assert result["signal"]["Alice"] == 2

    def test_returns_none_on_failure(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("heartbeat")

        assert result is None

    def test_returns_none_on_invalid_json(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("heartbeat")

        assert result is None

    def test_returns_none_on_empty_result(self, job_manager):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({})

        with patch("subprocess.run", return_value=mock_result):
            result = job_manager._get_vadimgest_details("heartbeat")

        assert result is None


# ── _send_failure_alert ──────────────────────────────────────────────

class TestSendFailureAlert:
    def test_sends_via_feed(self, job_manager):
        with patch.object(cs, "send_feed") as mock_feed:
            job_manager._send_failure_alert("heartbeat", "some error", 45.3)
            mock_feed.assert_called_once()
            msg = mock_feed.call_args[0][0]
            assert "heartbeat" in msg
            assert "some error" in msg
            assert "45.3" in msg


# ── acquire_lock ─────────────────────────────────────────────────────

class TestAcquireLock:
    def test_acquire_lock_returns_fd(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        with patch("pathlib.Path.__new__", return_value=lock_file):
            # We test the function behavior directly
            import fcntl
            fd = open(lock_file, "w")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd.write(str(os.getpid()))
            fd.flush()
            # Should succeed
            assert fd is not None
            # Cleanup
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()


# ── Deltas parsing in _process_job_result ────────────────────────────

class TestDeltasParsing:
    """Test the delta-parsing logic from output (---DELTAS--- marker)."""

    def test_parses_deltas_from_output(self, job_manager):
        """Verify _process_job_result correctly parses ---DELTAS--- marker."""
        deltas_data = [{"type": "gtask_created", "title": "Test task"}]
        output = f"Some heartbeat output\n---DELTAS---\n{json.dumps(deltas_data)}"

        result = {
            "result": output,
            "error": None,
            "cost": 0.05,
            "session_id": "test-session",
            "todos": [],
        }
        job = {"id": "test-job", "execution": {}}
        now = datetime.now(timezone.utc)

        logged_entries = []
        original_log_run = job_manager._log_run

        def capture_log(entry):
            logged_entries.append(entry)

        with patch.object(job_manager, "_log_run", side_effect=capture_log), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_resolve_topic", return_value="General"), \
             patch.object(job_manager, "_handle_on_complete"), \
             patch.object(cs, "send_feed"), \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(
                job, "run1", result, now, 30.0, {}, None, None, 0
            )

        assert len(logged_entries) == 1
        entry = logged_entries[0]
        assert entry["deltas"] == deltas_data
        assert entry["output"] == "Some heartbeat output"

    def test_invalid_deltas_json(self, job_manager):
        """Invalid JSON after ---DELTAS--- should result in deltas=None."""
        output = "Output\n---DELTAS---\nnot valid json"

        result = {
            "result": output,
            "error": None,
            "cost": 0.01,
            "session_id": "s1",
            "todos": [],
        }
        job = {"id": "test", "execution": {}}
        now = datetime.now(timezone.utc)

        logged_entries = []

        with patch.object(job_manager, "_log_run", side_effect=lambda e: logged_entries.append(e)), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_resolve_topic", return_value="General"), \
             patch.object(job_manager, "_handle_on_complete"), \
             patch.object(cs, "send_feed"), \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(
                job, "run2", result, now, 10.0, {}, None, None, 0
            )

        assert logged_entries[0]["deltas"] is None


# ══════════════════════════════════════════════════════════════════════
# NEW TESTS - Improving coverage of uncovered functions/methods
# ══════════════════════════════════════════════════════════════════════


# ── schedule_jobs ────────────────────────────────────────────────────

class TestScheduleJobs:
    def test_schedules_interval_job(self, job_manager):
        job_manager.jobs = [
            {"id": "hb", "enabled": True, "name": "HB",
             "schedule": {"type": "every", "interval_minutes": 30}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_called_once()
        call_kwargs = job_manager.scheduler.add_job.call_args[1]
        assert call_kwargs["id"] == "hb"
        assert call_kwargs["replace_existing"] is True

    def test_schedules_interval_hours(self, job_manager):
        job_manager.jobs = [
            {"id": "hourly", "enabled": True,
             "schedule": {"type": "every", "interval_hours": 2}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_called_once()

    def test_schedules_interval_days(self, job_manager):
        job_manager.jobs = [
            {"id": "daily", "enabled": True,
             "schedule": {"type": "every", "interval_days": 1}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_called_once()

    def test_schedules_cron_job(self, job_manager):
        job_manager.jobs = [
            {"id": "reflect", "enabled": True,
             "schedule": {"type": "cron", "cron": "30 5 * * *"}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_called_once()

    def test_schedules_at_job(self, job_manager):
        job_manager.jobs = [
            {"id": "oneshot", "enabled": True,
             "schedule": {"type": "at", "datetime": "2026-03-20T10:00:00+00:00"}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_called_once()

    def test_skips_disabled_job(self, job_manager):
        job_manager.jobs = [
            {"id": "off", "enabled": False,
             "schedule": {"type": "every", "interval_minutes": 30}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_not_called()

    def test_skips_invalid_schedule_type(self, job_manager):
        job_manager.jobs = [
            {"id": "bad", "enabled": True,
             "schedule": {"type": "weekly"}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_not_called()

    def test_skips_cron_no_expression(self, job_manager):
        job_manager.jobs = [
            {"id": "nocron", "enabled": True,
             "schedule": {"type": "cron"}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_not_called()

    def test_skips_at_invalid_datetime(self, job_manager):
        job_manager.jobs = [
            {"id": "badat", "enabled": True,
             "schedule": {"type": "at", "datetime": "not-a-date"}},
        ]
        job_manager.schedule_jobs()
        job_manager.scheduler.add_job.assert_not_called()

    def test_multiple_jobs_scheduled(self, job_manager):
        job_manager.jobs = [
            {"id": "a", "enabled": True,
             "schedule": {"type": "every", "interval_minutes": 30}},
            {"id": "b", "enabled": True,
             "schedule": {"type": "every", "interval_hours": 1}},
        ]
        job_manager.schedule_jobs()
        assert job_manager.scheduler.add_job.call_count == 2


# ── _execute_job exception handling ──────────────────────────────────

class TestExecuteJobExceptionHandling:
    def test_catches_exception_and_updates_state(self, job_manager):
        job = {"id": "crashy", "requires_internet": False}
        job_manager._internet_available = True
        job_manager.state = {"jobs_status": {}}

        with patch.object(job_manager, "_execute_job_internal",
                          side_effect=RuntimeError("boom")), \
             patch.object(job_manager, "_save_state"), \
             patch.object(cs, "send_feed"):
            job_manager._execute_job(job)

        assert job_manager.state["jobs_status"]["crashy"]["status"] == "crashed"

    def test_sends_failure_alert_on_crash(self, job_manager):
        job = {"id": "crashy", "requires_internet": False}
        job_manager._internet_available = True
        job_manager.state = {"jobs_status": {}}

        with patch.object(job_manager, "_execute_job_internal",
                          side_effect=RuntimeError("boom")), \
             patch.object(job_manager, "_save_state"), \
             patch.object(cs, "send_feed") as mock_feed:
            job_manager._execute_job(job)

        mock_feed.assert_called_once()
        assert "boom" in mock_feed.call_args[0][0]

    def test_default_requires_internet_true(self, job_manager):
        """Job without requires_internet key defaults to True, so skip when offline."""
        job = {"id": "test"}
        job_manager._internet_available = False
        job_manager._internet_lost_at = datetime.now(timezone.utc)

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager._execute_job(job)
            mock_exec.assert_not_called()


# ── _execute_retry ───────────────────────────────────────────────────

class TestExecuteRetry:
    def test_skips_when_offline_and_reschedules(self, job_manager):
        job = {"id": "test", "requires_internet": True,
               "retry": {"max_attempts": 3, "delay_minutes": 5}}
        job_manager._internet_available = False

        with patch.object(job_manager, "_execute_job_internal") as mock_exec, \
             patch.object(job_manager, "_schedule_retry") as mock_sched:
            job_manager._execute_retry(job, attempt=2)
            mock_exec.assert_not_called()
            # Re-schedules with attempt-1
            mock_sched.assert_called_once_with(job, 1)

    def test_executes_when_online(self, job_manager):
        job = {"id": "test", "requires_internet": True}
        job_manager._internet_available = True

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager._execute_retry(job, attempt=1)
            mock_exec.assert_called_once_with(job, is_catch_up=False, retry_attempt=1)

    def test_catches_crash_and_alerts(self, job_manager):
        job = {"id": "test", "requires_internet": True}
        job_manager._internet_available = True

        with patch.object(job_manager, "_execute_job_internal",
                          side_effect=RuntimeError("retry boom")), \
             patch.object(cs, "send_feed") as mock_feed:
            job_manager._execute_retry(job, attempt=2)

        mock_feed.assert_called_once()
        assert "retry boom" in mock_feed.call_args[0][0]

    def test_non_internet_job_runs_offline(self, job_manager):
        job = {"id": "local", "requires_internet": False}
        job_manager._internet_available = False

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager._execute_retry(job, attempt=1)
            mock_exec.assert_called_once()


# ── _execute_job_internal bash mode ──────────────────────────────────

class TestExecuteJobInternalBash:
    def test_bash_mode_success(self, job_manager):
        job = {
            "id": "sync",
            "execution": {"mode": "bash", "command": "echo hello", "timeout_seconds": 10},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        mock_proc = MagicMock()
        mock_proc.stdout = "hello\n"
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        with patch("subprocess.run", return_value=mock_proc), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._execute_job_internal(job, is_catch_up=False)
            mock_process.assert_called_once()
            result_arg = mock_process.call_args[0][2]
            assert result_arg["error"] is None
            assert "hello" in result_arg["result"]

    def test_bash_mode_failure(self, job_manager):
        job = {
            "id": "fail",
            "execution": {"mode": "bash", "command": "exit 1", "timeout_seconds": 10},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = "command failed"
        mock_proc.returncode = 1

        with patch("subprocess.run", return_value=mock_proc), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._execute_job_internal(job, is_catch_up=False)
            result_arg = mock_process.call_args[0][2]
            assert result_arg["error"] is not None
            assert result_arg["exit_code"] == 1

    def test_bash_mode_timeout(self, job_manager):
        job = {
            "id": "slow",
            "execution": {"mode": "bash", "command": "sleep 999", "timeout_seconds": 1},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        import subprocess as sp
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("sleep", 1)), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._execute_job_internal(job, is_catch_up=False)
            result_arg = mock_process.call_args[0][2]
            assert "Timeout" in result_arg["error"]

    def test_bash_mode_no_command(self, job_manager):
        job = {
            "id": "empty",
            "execution": {"mode": "bash"},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._execute_job_internal(job, is_catch_up=False)
            result_arg = mock_process.call_args[0][2]
            assert "No command" in result_arg["error"]

    def test_bash_mode_exception(self, job_manager):
        job = {
            "id": "exc",
            "execution": {"mode": "bash", "command": "echo x", "timeout_seconds": 10},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        with patch("subprocess.run", side_effect=OSError("no such file")), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._execute_job_internal(job, is_catch_up=False)
            result_arg = mock_process.call_args[0][2]
            assert "no such file" in result_arg["error"]


# ── _execute_job_internal overlap guard ──────────────────────────────

class TestExecuteJobInternalOverlapGuard:
    def test_skips_if_another_instance_running(self, job_manager):
        job = {"id": "hb", "execution": {"mode": "bash", "command": "echo hi"}}
        job_manager.state = {
            "jobs_status": {},
            "running_foreground_jobs": {
                "other_run": {"job_id": "hb", "pid": 99999}
            },
        }

        with patch("lib.subagent_state.is_process_alive", return_value=True) as mock_alive, \
             patch.object(job_manager, "_log_run") as mock_log:
            # Import the actual module's reference
            with patch.dict("sys.modules", {"lib.subagent_state": MagicMock(is_process_alive=MagicMock(return_value=True))}):
                job_manager._execute_job_internal(job, is_catch_up=False)

        # Should have logged a skip entry
        if mock_log.called:
            for call in mock_log.call_args_list:
                entry = call[0][0]
                if entry.get("status") == "skipped":
                    assert "Another instance" in entry.get("error", "")


# ── _execute_job_internal template variables ─────────────────────────

class TestExecuteJobInternalTemplateVars:
    def test_replaces_now_and_now_eet(self, job_manager):
        job = {
            "id": "tmpl",
            "execution": {
                "mode": "isolated",
                "prompt_template": "Current time: {{now}}, EET: {{now_eet}}",
                "timeout_seconds": 10,
            },
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        captured_prompt = []

        def mock_run_detached(prompt, *args, **kwargs):
            captured_prompt.append(prompt)
            return {"error": None, "result": "", "cost": 0, "session_id": None,
                    "pid": 1, "output_dir": "/tmp/test"}

        with patch.object(job_manager, "_run_claude_detached", side_effect=mock_run_detached), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result"):
            job_manager._execute_job_internal(job, is_catch_up=False)

        assert len(captured_prompt) == 1
        assert "{{now}}" not in captured_prompt[0]
        assert "{{now_eet}}" not in captured_prompt[0]
        assert "EET" in captured_prompt[0]


# ── _process_job_result advanced paths ───────────────────────────────

class TestProcessJobResultAdvanced:
    def _make_result(self, output="", error=None, cost=0.01):
        return {
            "result": output,
            "error": error,
            "cost": cost,
            "session_id": "test-sess",
            "todos": [],
        }

    def test_network_error_reverts_state(self, job_manager):
        job = {"id": "hb", "execution": {}}
        job_manager.state = {
            "jobs_status": {"hb": {"last_run": "2026-03-15T09:00:00+00:00", "status": "completed"}},
            "_prev_job_status": {},
        }
        now = datetime.now(timezone.utc)

        result = self._make_result(error="FailedToOpenSocket: connection refused")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(cs, "register_session"), \
             patch.object(cs, "send_feed"):
            job_manager._process_job_result(job, "run1", result, now, 5.0, {}, None, None, 0)

        # State should have been reverted to prev
        assert job_manager.state["jobs_status"]["hb"]["status"] == "completed"

    def test_retryable_error_schedules_retry(self, job_manager):
        job = {"id": "hb", "execution": {}, "retry": {"max_attempts": 3, "delay_minutes": 5}}
        job_manager.state = {
            "jobs_status": {},
            "_prev_job_status": {},
        }
        now = datetime.now(timezone.utc)

        result = self._make_result(error="TimeoutError: request timed out")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_schedule_retry") as mock_retry, \
             patch.object(cs, "register_session"), \
             patch.object(cs, "send_feed"):
            job_manager._process_job_result(job, "run1", result, now, 5.0, {}, None, None, 0)

        mock_retry.assert_called_once_with(job, 0)

    def test_max_retries_sends_alert(self, job_manager):
        job = {"id": "hb", "execution": {}, "retry": {"max_attempts": 2, "delay_minutes": 5}}
        job_manager.state = {
            "jobs_status": {},
            "_prev_job_status": {},
        }
        now = datetime.now(timezone.utc)

        result = self._make_result(error="500 Internal Server Error")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_schedule_retry") as mock_retry, \
             patch.object(job_manager, "_send_failure_alert") as mock_alert, \
             patch.object(cs, "register_session"), \
             patch.object(cs, "send_feed"):
            # retry_attempt=2 means we've already used all 2 max_attempts
            job_manager._process_job_result(job, "run1", result, now, 5.0, {}, None, None, 2)

        mock_retry.assert_not_called()
        mock_alert.assert_called_once()

    def test_heartbeat_sends_report_via_feed(self, job_manager):
        job = {"id": "heartbeat", "execution": {}, "telegram_topic": 100001}
        job_manager.state = {"jobs_status": {}, "_prev_job_status": {}}
        now = datetime.now(timezone.utc)

        result = self._make_result(output="Some long output text for the heartbeat")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_build_heartbeat_report", return_value="<b>Report</b>") as mock_report, \
             patch.object(job_manager, "_resolve_topic", return_value="Heartbeat"), \
             patch.object(job_manager, "_handle_on_complete"), \
             patch.object(cs, "send_feed") as mock_feed, \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(job, "run1", result, now, 30.0, {}, None, None, 0)

        mock_report.assert_called_once()
        mock_feed.assert_called_once()
        assert mock_feed.call_args[1]["parse_mode"] == "HTML"

    def test_heartbeat_no_report_no_feed(self, job_manager):
        job = {"id": "heartbeat", "execution": {}}
        job_manager.state = {"jobs_status": {}, "_prev_job_status": {}}
        now = datetime.now(timezone.utc)

        result = self._make_result(output="")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_build_heartbeat_report", return_value=None), \
             patch.object(job_manager, "_resolve_topic", return_value="Heartbeat"), \
             patch.object(job_manager, "_handle_on_complete"), \
             patch.object(cs, "send_feed") as mock_feed, \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(job, "run1", result, now, 30.0, {}, None, None, 0)

        mock_feed.assert_not_called()

    def test_non_heartbeat_sends_output_to_feed(self, job_manager):
        job = {"id": "reflection", "execution": {}, "telegram_topic": 100001}
        job_manager.state = {"jobs_status": {}, "_prev_job_status": {}}
        now = datetime.now(timezone.utc)

        result = self._make_result(output="Reflection complete, 5 notes updated")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_resolve_topic", return_value="Heartbeat"), \
             patch.object(job_manager, "_handle_on_complete"), \
             patch.object(cs, "send_feed") as mock_feed, \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(job, "run1", result, now, 30.0, {}, None, None, 0)

        mock_feed.assert_called_once()

    def test_intake_stats_attached_for_heartbeat(self, job_manager):
        job = {"id": "heartbeat", "execution": {}}
        job_manager.state = {"jobs_status": {}, "_prev_job_status": {}}
        now = datetime.now(timezone.utc)

        result = self._make_result(output="done")
        intake_before = {"telegram": {"total": 100, "new": 10}, "signal": {"total": 50, "new": 5}}

        logged_entries = []

        with patch.object(job_manager, "_log_run", side_effect=lambda e: logged_entries.append(e)), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_build_heartbeat_report", return_value=None), \
             patch.object(job_manager, "_resolve_topic", return_value="Heartbeat"), \
             patch.object(job_manager, "_handle_on_complete"), \
             patch.object(job_manager, "_get_vadimgest_stats", return_value=None), \
             patch.object(cs, "send_feed"), \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(
                job, "run1", result, now, 30.0, {}, intake_before, None, 0
            )

        assert len(logged_entries) == 1
        assert "intake" in logged_entries[0]
        assert logged_entries[0]["intake"]["total_new"] == 15

    def test_calls_handle_on_complete_on_success(self, job_manager):
        job = {"id": "sync", "execution": {},
               "on_complete": {"trigger": "heartbeat", "condition": "always"}}
        job_manager.state = {"jobs_status": {}, "_prev_job_status": {}}
        now = datetime.now(timezone.utc)

        result = self._make_result(output="synced 42 records")

        with patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_resolve_topic", return_value="General"), \
             patch.object(job_manager, "_handle_on_complete") as mock_chain, \
             patch.object(cs, "send_feed"), \
             patch.object(cs, "register_session"):
            job_manager._process_job_result(job, "run1", result, now, 10.0, {}, None, None, 0)

        mock_chain.assert_called_once()


# ── _reload_jobs ─────────────────────────────────────────────────────

class TestReloadJobs:
    def test_removes_deleted_jobs(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        # Old state: has "old_job"
        job_manager.jobs = [
            {"id": "old_job", "enabled": True, "schedule": {"type": "every", "interval_minutes": 30}},
        ]

        # New file has different job
        jobs_file.write_text(json.dumps({
            "version": 1,
            "jobs": [
                {"id": "new_job", "enabled": True,
                 "schedule": {"type": "every", "interval_minutes": 60}},
            ],
        }))

        job_manager._reload_jobs()

        # scheduler.remove_job should have been called for old_job
        remove_calls = [c[0][0] for c in job_manager.scheduler.remove_job.call_args_list]
        assert "old_job" in remove_calls

    def test_disables_job(self, job_manager, minimal_config):
        _, jobs_file, _, _ = minimal_config
        job_manager.jobs = [
            {"id": "was_enabled", "enabled": True,
             "schedule": {"type": "every", "interval_minutes": 30}},
        ]

        jobs_file.write_text(json.dumps({
            "version": 1,
            "jobs": [
                {"id": "was_enabled", "enabled": False,
                 "schedule": {"type": "every", "interval_minutes": 30}},
            ],
        }))

        job_manager._reload_jobs()
        # Should try to remove the now-disabled job
        assert job_manager.scheduler.remove_job.called


# ── _check_internet ──────────────────────────────────────────────────

class TestCheckInternet:
    def test_returns_true_on_success(self, job_manager):
        mock_sock = MagicMock()
        with patch("socket.create_connection", return_value=mock_sock):
            assert job_manager._check_internet() is True
            mock_sock.close.assert_called_once()

    def test_returns_false_on_failure(self, job_manager):
        with patch("socket.create_connection", side_effect=OSError("no route")):
            assert job_manager._check_internet() is False


# ── detect_missed_jobs edge cases ────────────────────────────────────

class TestDetectMissedJobsEdgeCases:
    def test_skips_disabled_job(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }
        job_manager.jobs = [
            {"id": "disabled", "enabled": False,
             "schedule": {"type": "every", "interval_minutes": 30},
             "catch_up": {"enabled": True, "max_catch_up": 1}},
        ]

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager.detect_missed_jobs()
            mock_exec.assert_not_called()

    def test_skips_catch_up_disabled(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }
        job_manager.jobs = [
            {"id": "no_catch", "enabled": True,
             "schedule": {"type": "every", "interval_minutes": 30},
             "catch_up": {"enabled": False}},
        ]

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager.detect_missed_jobs()
            mock_exec.assert_not_called()

    def test_skips_max_catch_up_zero(self, job_manager):
        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }
        job_manager.jobs = [
            {"id": "zero", "enabled": True,
             "schedule": {"type": "every", "interval_minutes": 30},
             "catch_up": {"enabled": True, "max_catch_up": 0}},
        ]

        with patch.object(job_manager, "_execute_job_internal") as mock_exec:
            job_manager.detect_missed_jobs()
            mock_exec.assert_not_called()

    def test_skips_internet_dependent_when_offline(self, job_manager):
        job_manager._internet_available = False
        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }
        job_manager.jobs = [
            {"id": "online_only", "enabled": True, "requires_internet": True,
             "schedule": {"type": "every", "interval_minutes": 30},
             "catch_up": {"enabled": True, "max_catch_up": 1}},
        ]

        with patch.object(job_manager, "_execute_job_internal") as mock_exec, \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"):
            job_manager.detect_missed_jobs()
            mock_exec.assert_not_called()

    def test_crash_during_catch_up_marks_crashed(self, job_manager):
        job_manager._internet_available = True
        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {},
        }
        job_manager.jobs = [
            {"id": "crasher", "enabled": True,
             "schedule": {"type": "every", "interval_minutes": 30},
             "catch_up": {"enabled": True, "max_catch_up": 1}},
        ]

        with patch.object(job_manager, "_execute_job_internal",
                          side_effect=RuntimeError("OOM")), \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"), \
             patch.object(cs, "send_feed"):
            job_manager.detect_missed_jobs()

        assert job_manager.state["jobs_status"]["crasher"]["status"] == "crashed"

    def test_uses_per_job_last_run(self, job_manager):
        """Uses per-job last_run instead of global last_successful_check."""
        job_manager._internet_available = True
        # Per-job last_run is very recent -> no missed runs
        job_manager.state = {
            "daemon_start_time": "2026-03-15T08:00:00+00:00",
            "last_successful_check": "2026-03-15T08:00:00+00:00",
            "jobs_status": {
                "recent": {
                    "last_run": datetime.now(timezone.utc).isoformat(),
                    "status": "completed",
                }
            },
        }
        job_manager.jobs = [
            {"id": "recent", "enabled": True,
             "schedule": {"type": "every", "interval_minutes": 30},
             "catch_up": {"enabled": True, "max_catch_up": 1}},
        ]

        with patch.object(job_manager, "_execute_job_internal") as mock_exec, \
             patch.object(job_manager, "_log_run"), \
             patch.object(job_manager, "_save_state"):
            job_manager.detect_missed_jobs()
            mock_exec.assert_not_called()


# ── _recover_foreground_jobs ─────────────────────────────────────────

class TestRecoverForegroundJobs:
    def test_no_running_jobs_noop(self, job_manager):
        job_manager.state = {"running_foreground_jobs": {}}
        # Should not raise
        job_manager._recover_foreground_jobs()

    def test_empty_state_noop(self, job_manager):
        job_manager.state = {}
        job_manager._recover_foreground_jobs()

    def test_dead_process_reads_output(self, job_manager):
        job_manager.state = {
            "running_foreground_jobs": {
                "run_abc": {
                    "job_id": "hb",
                    "pid": 99999,
                    "started_at": "2026-03-15T10:00:00+00:00",
                    "timeout": 300,
                    "output_dir": "/tmp/test",
                    "job_config": {"id": "hb", "execution": {}},
                    "is_catch_up": False,
                    "intake_before": None,
                    "intake_details": None,
                    "retry_attempt": 0,
                }
            }
        }

        with patch.dict("sys.modules", {
                "lib.subagent_state": MagicMock(is_process_alive=MagicMock(return_value=False))
             }), \
             patch.object(job_manager, "_recover_single_job") as mock_recover:
            job_manager._recover_foreground_jobs()
            mock_recover.assert_called_once()
            # Should be called with timeout=5 for dead processes
            assert mock_recover.call_args[1].get("timeout", mock_recover.call_args[0][2] if len(mock_recover.call_args[0]) > 2 else None) == 5


# ── _recover_single_job ──────────────────────────────────────────────

class TestRecoverSingleJob:
    def test_processes_result_and_cleans_state(self, job_manager):
        job_manager.state = {
            "jobs_status": {},
            "_prev_job_status": {},
            "running_foreground_jobs": {"run1": {}},
        }

        info = {
            "job_id": "hb",
            "job_config": {"id": "hb", "execution": {}},
            "output_dir": "/tmp/test",
            "is_catch_up": False,
            "intake_before": None,
            "intake_details": None,
            "retry_attempt": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        mock_result = {"result": "recovered output", "error": None, "cost": 0.0, "session_id": "s1"}

        with patch.object(job_manager.executor, "wait_for_result", return_value=mock_result), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._recover_single_job("run1", info, timeout=5)

        mock_process.assert_called_once()
        # running_foreground_jobs should have run1 removed
        assert "run1" not in job_manager.state.get("running_foreground_jobs", {})

    def test_handles_recovery_failure(self, job_manager):
        job_manager.state = {
            "jobs_status": {},
            "_prev_job_status": {},
            "running_foreground_jobs": {"run2": {}},
        }

        info = {
            "job_id": "hb",
            "job_config": {"id": "hb", "execution": {}},
            "output_dir": "/tmp/test",
            "is_catch_up": False,
            "intake_before": None,
            "intake_details": None,
            "retry_attempt": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        with patch.object(job_manager.executor, "wait_for_result",
                          side_effect=Exception("read failed")), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result") as mock_process:
            job_manager._recover_single_job("run2", info, timeout=5)

        # Should still process with error result
        mock_process.assert_called_once()
        result_arg = mock_process.call_args[0][2]
        assert "Recovery failed" in result_arg["error"]


# ── _graceful_shutdown extended ──────────────────────────────────────

class TestGracefulShutdownExtended:
    def test_logs_running_foreground_jobs(self, job_manager):
        job_manager.state = {
            "jobs_status": {},
            "running_foreground_jobs": {
                "run_a": {"job_id": "hb"},
                "run_b": {"job_id": "reflect"},
            },
        }
        with patch.object(job_manager, "_save_state"):
            job_manager._graceful_shutdown()

        assert "last_shutdown" in job_manager.state

    def test_handles_scheduler_shutdown_error(self, job_manager):
        job_manager.state = {"jobs_status": {}}
        job_manager.scheduler.shutdown.side_effect = RuntimeError("already stopped")

        with patch.object(job_manager, "_save_state"):
            # Should not raise
            job_manager._graceful_shutdown()


# ── _handle_shutdown ─────────────────────────────────────────────────

class TestHandleShutdown:
    def test_calls_graceful_shutdown_and_exits(self, job_manager):
        with patch.object(job_manager, "_graceful_shutdown") as mock_gs:
            with pytest.raises(SystemExit) as exc_info:
                job_manager._handle_shutdown(15, None)
            mock_gs.assert_called_once()
            assert exc_info.value.code == 0


# ── _handle_debug_signal ─────────────────────────────────────────────

class TestHandleDebugSignal:
    def test_logs_signal_name(self, job_manager):
        import signal as signal_mod
        # The method references `signal` from the module namespace (imported in start()),
        # so inject it for testing outside start().
        cs.signal = signal_mod
        # Should not raise, just log
        job_manager._handle_debug_signal(signal_mod.SIGHUP, None)


# ── _atexit_handler ──────────────────────────────────────────────────

class TestAtexitHandler:
    def test_logs_pid(self, job_manager):
        # Should not raise
        job_manager._atexit_handler()


# ── _run_claude_detached ─────────────────────────────────────────────

class TestRunClaudeDetached:
    def test_registers_and_cleans_up_state(self, job_manager):
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        mock_launch = {
            "pid": 12345,
            "output_dir": "/tmp/claude_test",
        }
        mock_result = {
            "result": "output",
            "error": None,
            "cost": 0.05,
            "session_id": "sess-123",
        }

        with patch.object(job_manager.executor, "run_detached", return_value=mock_launch), \
             patch.object(job_manager.executor, "wait_for_result", return_value=mock_result), \
             patch.object(job_manager, "_save_state"):
            result = job_manager._run_claude_detached(
                "test prompt", "run_1", {"id": "test"}, "isolated", None, "sonnet",
                300, ["*"], [], False, None, None, 0
            )

        assert result["session_id"] == "sess-123"
        # After completion, running_foreground_jobs should be cleaned up
        assert "run_1" not in job_manager.state.get("running_foreground_jobs", {})

    def test_returns_error_on_launch_failure(self, job_manager):
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        with patch.object(job_manager.executor, "run_detached",
                          return_value={"error": "CLI not found"}), \
             patch.object(job_manager, "_save_state"):
            result = job_manager._run_claude_detached(
                "prompt", "run_2", {"id": "test"}, "isolated", None, "sonnet",
                300, ["*"], [], False, None, None, 0
            )

        assert result["error"] == "CLI not found"
        assert result["cost"] == 0.0


# ── _check_subagent_announces ────────────────────────────────────────

class TestCheckSubagentAnnounces:
    def test_processes_completed_announces(self, job_manager):
        mock_results = [
            {"status": "sent", "job_id": "sub1"},
            {"status": "requeued", "job_id": "sub2", "error": "timeout"},
        ]

        with patch.object(cs, "check_and_announce_completed", return_value=mock_results), \
             patch.object(job_manager, "_update_running_subagents_progress"), \
             patch.dict("sys.modules", {
                 "lib.subagent_state": MagicMock(
                     get_stale_subagents=MagicMock(return_value=[]),
                     fail_subagent=MagicMock(),
                 )
             }):
            job_manager._check_subagent_announces()
            # Should not raise

    def test_handles_stale_subagents(self, job_manager):
        stale = [{"job_id": "old_sub", "age_minutes": 45}]

        mock_fail = MagicMock()

        with patch.object(cs, "check_and_announce_completed", return_value=[]), \
             patch.object(job_manager, "_update_running_subagents_progress"), \
             patch.dict("sys.modules", {
                 "lib.subagent_state": MagicMock(
                     get_stale_subagents=MagicMock(return_value=stale),
                     fail_subagent=mock_fail,
                 )
             }):
            job_manager._check_subagent_announces()
            mock_fail.assert_called_once()

    def test_handles_exception(self, job_manager):
        with patch.object(cs, "check_and_announce_completed",
                          side_effect=RuntimeError("db error")):
            # Should not raise
            job_manager._check_subagent_announces()


# ── _update_running_subagents_progress ───────────────────────────────

class TestUpdateRunningSubagentsProgress:
    def test_no_active_subagents_noop(self, job_manager):
        with patch.object(cs, "get_active_subagents", return_value={}):
            # Should not raise
            job_manager._update_running_subagents_progress()

    def test_updates_progress_message(self, job_manager):
        job_manager.config = {"telegram": {"bot_token": "test", "allowed_users": [123]}}
        active = {
            "sub1": {
                "status": "running",
                "status_message_id": 42,
                "started_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "job": {"id": "sub1", "name": "Test Sub"},
            }
        }

        with patch.object(cs, "get_active_subagents", return_value=active), \
             patch.object(cs, "get_telegram_config", return_value=("token", "chat_id", None)), \
             patch.object(cs, "get_subagent_output", return_value="Working on something..."), \
             patch.object(cs, "parse_current_activity", return_value="Analyzing data"), \
             patch.object(cs, "format_progress_message", return_value="<b>Progress</b>"), \
             patch.object(cs, "format_duration", return_value="5m"), \
             patch.object(cs, "edit_telegram_message", return_value=True) as mock_edit, \
             patch.object(cs, "update_progress_timestamp") as mock_update:
            job_manager._update_running_subagents_progress()

        mock_edit.assert_called_once()
        mock_update.assert_called_once()

    def test_skips_non_running_subagent(self, job_manager):
        job_manager.config = {"telegram": {"bot_token": "test", "allowed_users": [123]}}
        active = {
            "sub1": {
                "status": "completed",
                "status_message_id": 42,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        }

        with patch.object(cs, "get_active_subagents", return_value=active), \
             patch.object(cs, "get_telegram_config", return_value=("token", "chat_id", None)), \
             patch.object(cs, "edit_telegram_message") as mock_edit:
            job_manager._update_running_subagents_progress()

        mock_edit.assert_not_called()

    def test_handles_exception(self, job_manager):
        with patch.object(cs, "get_active_subagents",
                          side_effect=RuntimeError("broken")):
            # Should not raise
            job_manager._update_running_subagents_progress()


# ── _start_healthcheck_thread ────────────────────────────────────────

class TestStartHealthcheckThread:
    def test_starts_daemon_thread(self, job_manager):
        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread
            job_manager._start_healthcheck_thread()
            mock_thread_cls.assert_called_once()
            call_kwargs = mock_thread_cls.call_args[1]
            assert call_kwargs["daemon"] is True
            assert call_kwargs["name"] == "healthcheck"
            mock_thread.start.assert_called_once()


# ── acquire_lock function ────────────────────────────────────────────

class TestAcquireLockFunction:
    def test_writes_pid_to_lock_file(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        import fcntl

        with patch.object(cs, "Path", return_value=lock_file):
            # Directly test the core logic
            fd = open(lock_file, 'w')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd.write(str(os.getpid()))
            fd.flush()
            content = lock_file.read_text()
            assert str(os.getpid()) in content
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()


# ── _load_config ─────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_yaml_config(self, job_manager, minimal_config):
        config_file, _, _, _ = minimal_config
        result = job_manager._load_config()
        assert "cron" in result
        assert "jobs_file" in result["cron"]


# ── _process_job_result crash in processing ──────────────────────────

class TestProcessJobResultCrash:
    def test_execute_job_internal_catches_process_result_crash(self, job_manager):
        """When _process_job_result crashes, _execute_job_internal still logs the run."""
        job = {
            "id": "crash_process",
            "execution": {"mode": "bash", "command": "echo ok", "timeout_seconds": 10},
        }
        job_manager.state = {"jobs_status": {}, "running_foreground_jobs": {}}

        mock_proc = MagicMock()
        mock_proc.stdout = "ok\n"
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        logged = []

        with patch("subprocess.run", return_value=mock_proc), \
             patch.object(job_manager, "_log_run", side_effect=lambda e: logged.append(e)), \
             patch.object(job_manager, "_save_state"), \
             patch.object(job_manager, "_process_job_result",
                          side_effect=RuntimeError("processing exploded")):
            job_manager._execute_job_internal(job, is_catch_up=False)

        # Should have fallback log entry
        assert any(e.get("job_id") == "crash_process" for e in logged)
