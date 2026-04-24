"""Tests for file-based collector functions in status_collector.py.

Tests: _get_recent_runs, _format_job_summaries, _collect_failing_jobs, _files_for_run.
Uses tmp_path for JSONL files, mocks subprocess for git calls.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from lib.status_collector import (
    _get_recent_runs,
    _format_job_summaries,
    _collect_failing_jobs,
    _files_for_run,
)


# ── _get_recent_runs ──────────────────────────────────────────────────

class TestGetRecentRuns:
    def test_returns_completed_and_failed(self, sample_jsonl):
        filepath = sample_jsonl(records=[
            {"job_id": "a", "status": "completed", "timestamp": "2026-02-23T10:00:00+00:00"},
            {"job_id": "b", "status": "failed", "timestamp": "2026-02-23T11:00:00+00:00"},
            {"job_id": "c", "status": "running", "timestamp": "2026-02-23T12:00:00+00:00"},
        ])
        result = _get_recent_runs(filepath, limit=10)
        assert len(result) == 2
        job_ids = [r["job_id"] for r in result]
        assert "a" in job_ids
        assert "b" in job_ids
        assert "c" not in job_ids

    def test_respects_limit(self, sample_jsonl):
        records = [
            {"job_id": f"job{i}", "status": "completed", "timestamp": f"2026-02-23T{10+i}:00:00+00:00"}
            for i in range(20)
        ]
        filepath = sample_jsonl(records=records)
        result = _get_recent_runs(filepath, limit=5)
        assert len(result) == 5

    def test_returns_most_recent(self, sample_jsonl):
        records = [
            {"job_id": "old", "status": "completed", "timestamp": "2026-02-20T10:00:00+00:00"},
            {"job_id": "new", "status": "completed", "timestamp": "2026-02-23T10:00:00+00:00"},
        ]
        filepath = sample_jsonl(records=records)
        result = _get_recent_runs(filepath, limit=1)
        assert len(result) == 1
        assert result[0]["job_id"] == "new"

    def test_empty_file(self, tmp_path):
        filepath = tmp_path / "empty.jsonl"
        filepath.write_text("")
        result = _get_recent_runs(filepath, limit=10)
        assert result == []

    def test_skips_blank_lines(self, tmp_path):
        filepath = tmp_path / "blank.jsonl"
        filepath.write_text(
            '{"job_id": "a", "status": "completed"}\n'
            '\n'
            '{"job_id": "b", "status": "completed"}\n'
        )
        result = _get_recent_runs(filepath, limit=10)
        assert len(result) == 2


# ── _format_job_summaries ─────────────────────────────────────────────

class TestFormatJobSummaries:
    @patch("lib.status_collector.datetime")
    def test_basic_summary(self, mock_dt):
        fixed_now = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        jobs = [{"id": "heartbeat", "name": "Heartbeat", "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_status = {"heartbeat": {"last_run": "2026-02-23T11:30:00+00:00", "status": "completed"}}

        result = _format_job_summaries(jobs, jobs_status)
        assert len(result) == 1
        assert result[0]["id"] == "heartbeat"
        assert result[0]["name"] == "Heartbeat"
        assert result[0]["status"] == "completed"
        assert result[0]["time_since"] is not None

    @patch("lib.status_collector.datetime")
    def test_missing_status(self, mock_dt):
        fixed_now = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        jobs = [{"id": "new_job", "name": "New Job", "schedule": {"type": "every", "interval_minutes": 60}}]
        jobs_status = {}

        result = _format_job_summaries(jobs, jobs_status)
        assert len(result) == 1
        assert result[0]["status"] == "pending"
        assert result[0]["time_since"] is None

    @patch("lib.status_collector.datetime")
    def test_enabled_flag(self, mock_dt):
        fixed_now = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.fromtimestamp = datetime.fromtimestamp
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        jobs = [
            {"id": "enabled_job", "name": "Enabled", "enabled": True, "schedule": {"type": "every", "interval_minutes": 30}},
            {"id": "disabled_job", "name": "Disabled", "enabled": False, "schedule": {"type": "every", "interval_minutes": 30}},
        ]
        result = _format_job_summaries(jobs, {})
        assert result[0]["enabled"] is True
        assert result[1]["enabled"] is False

    @patch("lib.status_collector.datetime")
    def test_empty_jobs(self, mock_dt):
        fixed_now = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        result = _format_job_summaries([], {})
        assert result == []


# ── _collect_failing_jobs ─────────────────────────────────────────────

class TestCollectFailingJobs:
    def test_identifies_failing_job(self):
        all_runs = [
            {"job_id": "hb", "status": "completed", "timestamp": "2026-02-23T10:00:00"},
            {"job_id": "hb", "status": "failed", "error": "timeout", "timestamp": "2026-02-23T11:00:00"},
        ]
        active_ids = {"hb"}
        result = _collect_failing_jobs(all_runs, active_ids)
        assert len(result) == 1
        assert result[0]["job_id"] == "hb"
        assert result[0]["consecutive"] == 1

    def test_consecutive_failures(self):
        all_runs = [
            {"job_id": "hb", "status": "completed", "timestamp": "2026-02-23T09:00:00"},
            {"job_id": "hb", "status": "failed", "error": "err1", "timestamp": "2026-02-23T10:00:00"},
            {"job_id": "hb", "status": "failed", "error": "err2", "timestamp": "2026-02-23T11:00:00"},
            {"job_id": "hb", "status": "failed", "error": "err3", "timestamp": "2026-02-23T12:00:00"},
        ]
        active_ids = {"hb"}
        result = _collect_failing_jobs(all_runs, active_ids)
        assert len(result) == 1
        assert result[0]["consecutive"] == 3

    def test_skips_healthcheck(self):
        all_runs = [
            {"job_id": "_healthcheck", "status": "failed", "error": "err", "timestamp": "2026-02-23T10:00:00"},
        ]
        active_ids = {"_healthcheck"}
        result = _collect_failing_jobs(all_runs, active_ids)
        assert len(result) == 0

    def test_skips_inactive_jobs(self):
        all_runs = [
            {"job_id": "old_job", "status": "failed", "error": "err", "timestamp": "2026-02-23T10:00:00"},
        ]
        active_ids = {"heartbeat"}
        result = _collect_failing_jobs(all_runs, active_ids)
        assert len(result) == 0

    def test_no_failures(self):
        all_runs = [
            {"job_id": "hb", "status": "completed", "timestamp": "2026-02-23T10:00:00"},
        ]
        active_ids = {"hb"}
        result = _collect_failing_jobs(all_runs, active_ids)
        assert len(result) == 0

    def test_sorted_by_consecutive(self):
        all_runs = [
            {"job_id": "a", "status": "failed", "error": "err", "timestamp": "2026-02-23T10:00:00"},
            {"job_id": "b", "status": "failed", "error": "err", "timestamp": "2026-02-23T10:00:00"},
            {"job_id": "b", "status": "failed", "error": "err", "timestamp": "2026-02-23T11:00:00"},
        ]
        active_ids = {"a", "b"}
        result = _collect_failing_jobs(all_runs, active_ids)
        assert len(result) == 2
        assert result[0]["job_id"] == "b"
        assert result[0]["consecutive"] == 2

    def test_empty_runs(self):
        result = _collect_failing_jobs([], {"hb"})
        assert result == []


# ── _files_for_run ────────────────────────────────────────────────────

class TestFilesForRun:
    def test_basic_file_matching(self):
        records = [
            {"tool": "Write", "ts": "2026-02-23T10:00:30+00:00", "summary": "/Users/test/file.py", "sid": "s1"},
            {"tool": "Read", "ts": "2026-02-23T10:00:15+00:00", "summary": "/Users/test/other.py", "sid": "s1"},
        ]
        session_starts = {"s1": datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)}
        result = _files_for_run(records, "2026-02-23T10:01:00+00:00", 60, session_starts)
        assert len(result) == 2

    def test_write_preferred_over_read(self):
        records = [
            {"tool": "Read", "ts": "2026-02-23T10:00:10+00:00", "summary": "/Users/test/file.py", "sid": "s1"},
            {"tool": "Write", "ts": "2026-02-23T10:00:20+00:00", "summary": "/Users/test/file.py", "sid": "s1"},
        ]
        session_starts = {"s1": datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)}
        result = _files_for_run(records, "2026-02-23T10:01:00+00:00", 60, session_starts)
        assert len(result) == 1
        assert result[0]["action"] == "write"

    def test_empty_run_ts(self):
        result = _files_for_run([], "", 60)
        assert result == []

    def test_none_run_ts(self):
        result = _files_for_run([], None, 60)
        assert result == []

    def test_filters_by_session(self):
        records = [
            {"tool": "Write", "ts": "2026-02-23T10:00:30+00:00", "summary": "/Users/test/a.py", "sid": "s1"},
            {"tool": "Write", "ts": "2026-02-23T10:00:30+00:00", "summary": "/Users/test/b.py", "sid": "s2"},
        ]
        session_starts = {
            "s1": datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc),
            # s2 started way before the run window
            "s2": datetime(2026, 2, 22, 10, 0, 0, tzinfo=timezone.utc),
        }
        result = _files_for_run(records, "2026-02-23T10:01:00+00:00", 60, session_starts)
        paths = [r["path"] for r in result]
        # s1 matches, s2 should be filtered out
        assert any("a.py" in p for p in paths)
        assert not any("b.py" in p for p in paths)

    def test_ignores_non_file_tools(self):
        records = [
            {"tool": "Bash", "ts": "2026-02-23T10:00:30+00:00", "summary": "ls", "sid": "s1"},
            {"tool": "Grep", "ts": "2026-02-23T10:00:30+00:00", "summary": "pattern", "sid": "s1"},
        ]
        session_starts = {"s1": datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)}
        result = _files_for_run(records, "2026-02-23T10:01:00+00:00", 60, session_starts)
        assert result == []

    def test_edit_is_write_action(self):
        records = [
            {"tool": "Edit", "ts": "2026-02-23T10:00:30+00:00", "summary": "/Users/test/file.py", "sid": "s1"},
        ]
        session_starts = {"s1": datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)}
        result = _files_for_run(records, "2026-02-23T10:01:00+00:00", 60, session_starts)
        assert len(result) == 1
        assert result[0]["action"] == "write"
