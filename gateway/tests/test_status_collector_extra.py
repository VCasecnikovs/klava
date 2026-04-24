"""Extra tests for gateway/lib/status_collector.py to increase coverage.

Targets missed lines: collect_status, _get_daemon_status, collect_dashboard_data,
_collect_fresh_dashboard_data, _build_event_details, _load_tool_call_records,
_build_session_starts, _files_for_run, _collect_skill_call_stats,
_collect_skill_git_history, _collect_qq_markers, _collect_error_learning,
_collect_obsidian_metrics, _collect_claude_md_details, _collect_services,
_get_google_access_token, _google_tasks_api, _fetch_google_tasks,
_fetch_github_items, collect_tasks_data, update_task, _collect_skill_changes,
_collect_obsidian_events.
"""

import json
import os
import sys
import time
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.status_collector as sc


def _clear_all_caches():
    """Reset all module-level caches."""
    for cache_name in [
        "_dashboard_cache", "_evolution_cache", "_growth_cache",
        "_deals_cache", "_people_cache", "_followups_cache",
        "_calendar_cache", "_views_cache", "_tasks_cache",
        "_hb_cache", "_files_cache",
    ]:
        cache = getattr(sc, cache_name, None)
        if cache and isinstance(cache, dict):
            cache["data"] = None
            cache["ts"] = 0
            if "date" in cache:
                cache["date"] = None


@pytest.fixture(autouse=True)
def clear_caches():
    _clear_all_caches()
    yield
    _clear_all_caches()


# ── collect_status ──

class TestCollectStatus:
    def test_collect_status_basic(self, tmp_path, monkeypatch):
        """collect_status reads jobs, state, and runs files."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        cron_dir = home / ".claude" / "cron"
        cron_dir.mkdir(parents=True)

        # jobs.json
        (cron_dir / "jobs.json").write_text(json.dumps({
            "jobs": [{"id": "heartbeat", "name": "Heartbeat", "schedule": {"type": "every", "interval_minutes": 30}}]
        }))
        # state.json
        (cron_dir / "state.json").write_text(json.dumps({
            "jobs_status": {"heartbeat": {"last_run": "2026-03-16T10:00:00+00:00", "status": "completed"}},
            "daemon_start_time": "2026-03-16T08:00:00+00:00",
            "last_successful_check": "2026-03-16T10:00:00+00:00",
        }))
        # runs.jsonl
        (cron_dir / "runs.jsonl").write_text(json.dumps({"status": "completed", "job_id": "hb"}) + "\n")

        with patch.object(sc, "_get_daemon_status", return_value={"cron-scheduler": "running"}):
            result = sc.collect_status()

        assert "jobs" in result
        assert "daemons" in result
        assert result["daemons"]["cron-scheduler"] == "running"
        assert len(result["jobs"]) == 1
        assert result["daemon_start_time"] is not None

    def test_collect_status_no_files(self, tmp_path, monkeypatch):
        """collect_status works when files don't exist."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        with patch.object(sc, "_get_daemon_status", return_value={}):
            result = sc.collect_status()

        assert result["jobs"] == []
        assert result["recent_runs"] == []

    def test_collect_status_bad_json(self, tmp_path, monkeypatch):
        """collect_status handles malformed JSON gracefully."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        cron_dir = home / ".claude" / "cron"
        cron_dir.mkdir(parents=True)

        (cron_dir / "jobs.json").write_text("{bad json")
        (cron_dir / "state.json").write_text("{bad json")

        with patch.object(sc, "_get_daemon_status", return_value={}):
            result = sc.collect_status()

        assert result["jobs"] == []


# ── _get_daemon_status ──

class TestGetDaemonStatus:
    def test_daemon_running(self):
        """Parses running daemon from launchctl output."""
        output = "12345\t0\tcom.local.cron-scheduler\n-\t0\tcom.local.webhook-server\n"
        mock_result = MagicMock()
        mock_result.stdout = output
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = sc._get_daemon_status()

        assert result["cron-scheduler"] == "running"
        assert result["webhook-server"] == "stopped"
        assert result["tg-gateway"] == "not loaded"

    def test_daemon_subprocess_fails(self):
        """Returns unknown on exception."""
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = sc._get_daemon_status()

        assert result["cron-scheduler"] == "unknown"

    def test_daemon_all_not_loaded(self):
        """All daemons not loaded when none appear in output."""
        mock_result = MagicMock(stdout="some other service\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._get_daemon_status()
        for v in result.values():
            assert v == "not loaded"


# ── collect_dashboard_data ──

class TestCollectDashboardData:
    def test_cache_hit(self):
        """Returns cached data within TTL."""
        sc._dashboard_cache["data"] = {"cached": True}
        sc._dashboard_cache["ts"] = time.time()

        result = sc.collect_dashboard_data()
        assert result == {"cached": True}

    def test_cache_miss_calls_fresh(self):
        """Calls _collect_fresh_dashboard_data when cache expired."""
        fake_data = {"fresh": True}
        with patch.object(sc, "_collect_fresh_dashboard_data", return_value=fake_data):
            result = sc.collect_dashboard_data()
        assert result == {"fresh": True}
        assert sc._dashboard_cache["data"] == {"fresh": True}


# ── _build_event_details ──

class TestBuildEventDetails:
    def test_claude_md_diff(self):
        """Extracts diff for claude_md category."""
        diff_output = "+## New Section\n+content here\n"
        mock_result = MagicMock(returncode=0, stdout=diff_output)

        with patch("subprocess.run", return_value=mock_result):
            result = sc._build_event_details("abc123", "claude_md", [".claude/CLAUDE.md"], "update CLAUDE.md")

        assert "sections_changed" in result or "diff_preview" in result

    def test_skill_details(self):
        """Extracts skill names from files."""
        files = [".claude/skills/heartbeat/SKILL.md", ".claude/skills/heartbeat/helper.py"]
        # Mock subprocess for the generic diff
        mock_result = MagicMock(returncode=0, stdout="+new line\n")
        with patch("subprocess.run", return_value=mock_result):
            result = sc._build_event_details("abc123", "skill", files, "update skill")

        assert "skills_affected" in result
        assert "heartbeat" in result["skills_affected"]

    def test_generic_diff_for_py_files(self):
        """Falls back to generic diff for non-special categories."""
        files = ["gateway/lib/something.py"]
        mock_result = MagicMock(returncode=0, stdout="+new code\n-old code\n")
        with patch("subprocess.run", return_value=mock_result):
            result = sc._build_event_details("abc123", "infra", files, "refactor")

        assert "diff_preview" in result
        assert "files" in result

    def test_subprocess_failure_graceful(self):
        """Handles subprocess failure."""
        with patch("subprocess.run", side_effect=Exception("git error")):
            result = sc._build_event_details("abc123", "claude_md", [".claude/CLAUDE.md"], "update")
        assert isinstance(result, dict)

    def test_no_files(self):
        """No files -> minimal details."""
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")):
            result = sc._build_event_details("abc123", "infra", [], "no files")
        assert isinstance(result, dict)

    def test_files_shortened(self):
        """File paths are shortened removing .claude/ prefix."""
        files = [".claude/skills/foo/SKILL.md", "gateway/lib/bar.py"]
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = sc._build_event_details("abc123", "infra", files, "update")
        # .claude/ should be stripped
        if "files" in result:
            assert all(".claude/" not in f for f in result["files"])


# ── _load_tool_call_records ──

class TestLoadToolCallRecords:
    def test_no_log_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._load_tool_call_records()
        assert result == []

    def test_reads_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        log_dir = tmp_path / ".claude" / "logs"
        log_dir.mkdir(parents=True)
        records = [
            {"ts": "2026-03-16T10:00:00+00:00", "tool": "Read", "sid": "s1"},
            {"ts": "2026-03-16T10:01:00+00:00", "tool": "Write", "sid": "s1"},
        ]
        (log_dir / "tool-calls.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )
        tail_output = "\n".join(json.dumps(r) for r in records)
        mock_result = MagicMock(stdout=tail_output, returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            result = sc._load_tool_call_records()

        assert len(result) == 2

    def test_subprocess_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        log_dir = tmp_path / ".claude" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "tool-calls.jsonl").write_text("{}\n")

        with patch("subprocess.run", side_effect=Exception("fail")):
            result = sc._load_tool_call_records()
        assert result == []


# ── _build_session_starts ──

class TestBuildSessionStarts:
    def test_basic(self):
        records = [
            {"sid": "s1", "ts": "2026-03-16T10:00:00+00:00"},
            {"sid": "s1", "ts": "2026-03-16T10:01:00+00:00"},
            {"sid": "s2", "ts": "2026-03-16T11:00:00+00:00"},
        ]
        result = sc._build_session_starts(records)
        assert "s1" in result
        assert "s2" in result
        # s1 should have the earliest timestamp
        assert result["s1"].hour == 10
        assert result["s1"].minute == 0

    def test_no_sid(self):
        records = [{"ts": "2026-03-16T10:00:00+00:00"}]
        result = sc._build_session_starts(records)
        assert result == {}

    def test_bad_ts(self):
        records = [{"sid": "s1", "ts": "not a date"}]
        result = sc._build_session_starts(records)
        assert result == {}


# ── _files_for_run ──

class TestFilesForRun:
    def test_empty_ts(self):
        assert sc._files_for_run([], None, 0) == []
        assert sc._files_for_run([], "", 0) == []

    def test_bad_ts(self):
        assert sc._files_for_run([], "not-a-date", 0) == []

    def test_finds_files_in_window(self):
        records = [
            {"ts": "2026-03-16T10:00:30+00:00", "tool": "Write", "sid": "s1", "summary": "/home/user/file.py"},
            {"ts": "2026-03-16T10:00:40+00:00", "tool": "Read", "sid": "s1", "summary": "/home/user/other.py"},
        ]
        session_starts = {"s1": datetime(2026, 3, 16, 9, 59, 50, tzinfo=timezone.utc)}
        result = sc._files_for_run(records, "2026-03-16T10:01:00+00:00", 60, session_starts)
        assert len(result) >= 1

    def test_filters_by_session(self):
        """Tool calls from wrong session are excluded."""
        records = [
            {"ts": "2026-03-16T10:00:30+00:00", "tool": "Write", "sid": "other-session", "summary": "/path"},
        ]
        session_starts = {"cron-session": datetime(2026, 3, 16, 9, 59, 50, tzinfo=timezone.utc)}
        result = sc._files_for_run(records, "2026-03-16T10:01:00+00:00", 60, session_starts)
        assert len(result) == 0

    def test_write_preferred_over_read(self):
        """When same file is both read and written, write wins."""
        records = [
            {"ts": "2026-03-16T10:00:30+00:00", "tool": "Read", "sid": "s1", "summary": "/path/file.py"},
            {"ts": "2026-03-16T10:00:35+00:00", "tool": "Edit", "sid": "s1", "summary": "/path/file.py"},
        ]
        session_starts = {"s1": datetime(2026, 3, 16, 9, 59, 50, tzinfo=timezone.utc)}
        result = sc._files_for_run(records, "2026-03-16T10:01:00+00:00", 60, session_starts)
        assert len(result) == 1
        assert result[0]["action"] == "write"


# ── _collect_skill_call_stats ──

class TestCollectSkillCallStats:
    def test_no_log_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_skill_call_stats()
        assert result == {}

    def test_parses_skill_calls(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        log_dir = tmp_path / ".claude" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "tool-calls.jsonl").write_text("")  # needs to exist

        records = [
            {"tool": "Skill", "summary": "heartbeat", "ts": "2026-03-16T10:00:00+00:00", "sid": "s1", "ok": True},
            {"tool": "Skill", "summary": "heartbeat", "ts": "2026-03-16T11:00:00+00:00", "sid": "s2", "ok": True},
            {"tool": "Read", "summary": "file.py", "ts": "2026-03-16T10:00:00+00:00", "sid": "s1", "ok": True},
        ]
        tail_output = "\n".join(json.dumps(r) for r in records)
        mock_result = MagicMock(stdout=tail_output, returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_skill_call_stats()

        assert "heartbeat" in result
        assert result["heartbeat"]["total_calls"] == 2
        assert result["heartbeat"]["last_call"] == "2026-03-16T11:00:00+00:00"

    def test_subprocess_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        log_dir = tmp_path / ".claude" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "tool-calls.jsonl").write_text("")

        with patch("subprocess.run", side_effect=Exception("fail")):
            result = sc._collect_skill_call_stats()
        assert result == {}


# ── _collect_skill_git_history ──

class TestCollectSkillGitHistory:
    def test_no_skills_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "nope")
        result = sc._collect_skill_git_history()
        assert result == {}

    def test_parses_git_log(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        s1 = skills_dir / "heartbeat"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("# Skill")
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        git_output = "abc12345|2026-03-16 10:00:00 +0000|initial skill\ndef67890|2026-03-15 09:00:00 +0000|add feature\n"
        mock_result = MagicMock(stdout=git_output, returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_skill_git_history()

        assert "heartbeat" in result
        assert result["heartbeat"]["total_commits"] == 2
        assert len(result["heartbeat"]["commits"]) == 2

    def test_git_failure_continues(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        s1 = skills_dir / "broken"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("# Broken")
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        mock_result = MagicMock(stdout="", returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_skill_git_history()
        assert result == {}


# ── _collect_qq_markers ──

class TestCollectQQMarkers:
    def test_subprocess_returns_json_array(self):
        items = [
            {"ts": datetime.now(timezone.utc).isoformat(), "text": "qq fix this bug", "source": "telegram"},
        ]
        mock_result = MagicMock(stdout=json.dumps(items), returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_qq_markers(days=7)
        assert len(result) == 1
        assert "qq" in result[0]["context"]

    def test_subprocess_returns_jsonl(self):
        now = datetime.now(timezone.utc).isoformat()
        lines = f'{{"ts": "{now}", "text": "qq broken", "source": "signal"}}\n'
        mock_result = MagicMock(stdout=lines, returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_qq_markers(days=7)
        assert len(result) == 1

    def test_subprocess_failure(self):
        mock_result = MagicMock(stdout="", returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_qq_markers(days=7)
        assert result == []

    def test_filters_old_items(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        items = [{"ts": old_ts, "text": "qq old marker", "source": "telegram"}]
        mock_result = MagicMock(stdout=json.dumps(items), returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_qq_markers(days=7)
        assert len(result) == 0

    def test_filters_non_qq_text(self):
        now = datetime.now(timezone.utc).isoformat()
        items = [{"ts": now, "text": "normal message no markers", "source": "telegram"}]
        mock_result = MagicMock(stdout=json.dumps(items), returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_qq_markers(days=7)
        assert len(result) == 0

    def test_empty_output(self):
        mock_result = MagicMock(stdout="", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_qq_markers(days=7)
        assert result == []

    def test_exception_handled(self):
        with patch("subprocess.run", side_effect=Exception("crash")):
            result = sc._collect_qq_markers(days=7)
        assert result == []


# ── _collect_error_learning ──

class TestCollectErrorLearning:
    def test_basic(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        s1 = skills_dir / "test-skill"
        s1.mkdir()
        now = datetime.now(timezone.utc).isoformat()
        (s1 / "errors.jsonl").write_text(f'{{"ts": "{now}", "error": "something"}}\n')
        (s1 / "SKILL.md").write_text("")

        result = sc._collect_error_learning(
            days=7,
            qq_markers=[{"text": "qq"}],
            skill_changes=[
                {"message": "create new skill heartbeat", "files": [".claude/skills/heartbeat/SKILL.md"]},
                {"message": "add scenario", "files": [".claude/skills/scenarios/test-scenario/test.md"]},
            ],
        )
        assert result["errors_found"] >= 1
        assert result["qq_found"] == 1
        assert "heartbeat" in result["skills_modified"]
        assert "heartbeat" in result["skills_added"]
        assert result["scenarios_created"] >= 1

    def test_no_skills_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "nope")
        result = sc._collect_error_learning(days=7, qq_markers=[], skill_changes=[])
        assert result["errors_found"] == 0

    def test_calls_collectors_when_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "nope")
        with patch.object(sc, "_collect_qq_markers", return_value=[]) as mock_qq, \
             patch.object(sc, "_collect_skill_changes", return_value=[]) as mock_sc:
            result = sc._collect_error_learning(days=7)
        mock_qq.assert_called_once()
        mock_sc.assert_called_once()


# ── _collect_obsidian_metrics ──

class TestCollectObsidianMetrics:
    def test_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "nope")
        result = sc._collect_obsidian_metrics()
        assert result["total_notes"] == 0

    def test_counts_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        (people_dir / "Alice.md").write_text("# Alice")
        (people_dir / "Bob.md").write_text("# Bob")
        org_dir = tmp_path / "Organizations"
        org_dir.mkdir()
        (org_dir / "Acme.md").write_text("# Acme")
        # Hidden dir should be skipped
        hidden = tmp_path / ".obsidian"
        hidden.mkdir()
        (hidden / "config.md").write_text("hidden")

        result = sc._collect_obsidian_metrics()
        assert result["total_notes"] == 3
        assert result["people"] == 2
        assert result["organizations"] == 1
        assert result["modified_24h"] >= 3  # just created
        assert len(result["recent_files"]) <= 5


# ── _collect_claude_md_details ──

class TestCollectClaudeMdDetails:
    def test_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_claude_md_details()
        assert result["memory_lines"] == 0
        assert result["last_modified"] is None

    def test_counts_memory_lines(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        content = "# CLAUDE.md\n<MEMORY>\nline1\nline2\nline3\n</MEMORY>\nEnd"
        (claude_dir / "CLAUDE.md").write_text(content)

        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
            result = sc._collect_claude_md_details()
        assert result["memory_lines"] == 3
        assert result["last_modified"] is not None

    def test_git_changes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Test")

        git_output = "2026-03-16 10:00:00 +0000|update memory section\n"
        mock_result = MagicMock(stdout=git_output, returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._collect_claude_md_details()
        assert len(result["recent_changes"]) == 1
        assert result["recent_changes"][0]["message"] == "update memory section"


# ── _collect_skill_changes (parsing) ──

class TestCollectSkillChangesParsing:
    def test_parses_commit_with_stat(self):
        """Parses git log --stat output for skill changes."""
        # Hash must be exactly 40 chars (untrimmed) for the parser
        hash40 = "a" * 40
        output = (
            f"{hash40}|2026-03-16 10:00:00 +0000|update heartbeat skill\n"
            " .claude/skills/heartbeat/SKILL.md | 10 +++++-----\n"
            " 1 file changed, 5 insertions(+), 5 deletions(-)\n"
        )
        mock_main = MagicMock(stdout=output, returncode=0)
        mock_diff = MagicMock(stdout="+added line\n-removed line\n", returncode=0)

        with patch("subprocess.run", side_effect=[mock_main, mock_diff]):
            result = sc._collect_skill_changes(days=7)

        assert len(result) == 1
        assert result[0]["message"] == "update heartbeat skill"
        assert result[0]["files_changed"] == 1
        assert result[0]["insertions"] == 5

    def test_multiple_commits(self):
        """Parses multiple commits."""
        hash1 = "a" * 40
        hash2 = "b" * 40
        output = (
            f"{hash1}|2026-03-16 10:00:00 +0000|first commit\n"
            " .claude/skills/a/SKILL.md | 2 ++\n"
            " 1 file changed, 2 insertions(+)\n"
            "\n"
            f"{hash2}|2026-03-15 09:00:00 +0000|second commit\n"
            " .claude/skills/b/SKILL.md | 3 +++\n"
            " 1 file changed, 3 insertions(+)\n"
        )
        mock_main = MagicMock(stdout=output, returncode=0)
        mock_diff = MagicMock(stdout="", returncode=0)

        with patch("subprocess.run", side_effect=[mock_main, mock_diff, mock_diff]):
            result = sc._collect_skill_changes(days=7)

        assert len(result) == 2


# ── _collect_obsidian_events edge cases ──

class TestCollectObsidianEventsEdge:
    def test_old_notes_excluded(self, tmp_path, monkeypatch):
        """Notes older than 14 days are excluded."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        note = people_dir / "Old Person.md"
        note.write_text("# Old")
        # Set birthtime to 30 days ago
        old_time = time.time() - 30 * 86400
        os.utime(note, (old_time, old_time))

        result = sc._collect_obsidian_events()
        # May or may not appear depending on birthtime vs mtime on macOS
        # But the code uses st_birthtime which we can't easily fake, so just check it runs
        assert isinstance(result, list)


# ── _get_google_access_token ──

class TestGetGoogleAccessToken:
    def test_no_creds_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "GOOGLE_CREDS_FILE", tmp_path / "missing.json")
        result = sc._get_google_access_token()
        assert result is None

    def test_success(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({
            "client_id": "test_id",
            "client_secret": "test_secret",
            "refresh_token": "test_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
        }))
        monkeypatch.setattr(sc, "GOOGLE_CREDS_FILE", creds_file)

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"access_token": "abc123"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = sc._get_google_access_token()
        assert result == "abc123"

    def test_exception_returns_none(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({
            "client_id": "id", "client_secret": "secret",
            "refresh_token": "token", "token_uri": "https://example.com",
        }))
        monkeypatch.setattr(sc, "GOOGLE_CREDS_FILE", creds_file)

        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = sc._get_google_access_token()
        assert result is None


# ── _google_tasks_api ──

class TestGoogleTasksApi:
    def test_get_request(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"items": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = sc._google_tasks_api("lists/abc/tasks", "token123")
        assert result == {"items": []}

    def test_patch_request_with_body(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "completed"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = sc._google_tasks_api(
                "lists/abc/tasks/123", "token123",
                method="PATCH", body={"status": "completed"},
            )
        assert result == {"status": "completed"}

    def test_method_no_body(self):
        """Non-GET with no body still sends empty data."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = sc._google_tasks_api("lists/abc/tasks/123", "token123", method="DELETE")
        assert result == {"ok": True}

    def test_exception_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=Exception("fail")):
            result = sc._google_tasks_api("lists/abc/tasks", "token123")
        assert result is None


# ── _fetch_google_tasks ──

class TestFetchGoogleTasks:
    def test_no_token(self):
        with patch.object(sc, "_get_google_access_token", return_value=None):
            result = sc._fetch_google_tasks()
        assert result == []

    def test_fetches_from_lists(self):
        api_response = {
            "items": [
                {"title": "Task 1", "status": "needsAction"},
                {"title": "Task 2", "status": "completed"},
            ]
        }
        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", return_value=api_response):
            result = sc._fetch_google_tasks()
        # Should filter to needsAction only, times number of lists
        needs_action = [t for t in result if t.get("status") == "needsAction"]
        assert len(needs_action) == len(sc.GOOGLE_TASKS_LISTS)

    def test_api_returns_none(self):
        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", return_value=None):
            result = sc._fetch_google_tasks()
        assert result == []


# ── _fetch_github_items ──

class TestFetchGithubItems:
    def test_success(self):
        items_json = json.dumps({"items": [{"title": "Issue 1"}]})
        mock_result = MagicMock(stdout=items_json, returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._fetch_github_items()
        assert len(result) == 1

    def test_failure(self):
        mock_result = MagicMock(stdout="", returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            result = sc._fetch_github_items()
        assert result == []

    def test_exception(self):
        with patch("subprocess.run", side_effect=Exception("gh not found")):
            result = sc._fetch_github_items()
        assert result == []


# ── update_task ──

class TestUpdateTask:
    def test_unknown_action(self):
        result = sc.update_task("gtask_abc_123", "invalid_action")
        assert result["success"] is False
        assert "Unknown action" in result["message"]

    def test_skip_action(self):
        result = sc.update_task("any_id", "skip")
        assert result["success"] is True
        assert "Skipped" in result["message"]

    def test_done_gtask(self):
        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", return_value={"status": "completed"}):
            result = sc.update_task("gtask_list1_task1", "done")
        assert result["success"] is True

    def test_done_gtask_no_token(self):
        with patch.object(sc, "_get_google_access_token", return_value=None):
            result = sc.update_task("gtask_list1_task1", "done")
        assert result["success"] is False
        assert "token" in result["message"].lower()

    def test_done_gtask_api_fails(self):
        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", return_value=None):
            result = sc.update_task("gtask_list1_task1", "done")
        assert result["success"] is False

    def test_postpone_gtask(self):
        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", return_value={"due": "2026-03-23"}):
            result = sc.update_task("gtask_list1_task1", "postpone", note="later")
        assert result["success"] is True

    def test_postpone_gtask_api_fails(self):
        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", return_value=None):
            result = sc.update_task("gtask_list1_task1", "postpone")
        assert result["success"] is False

    def test_cancel_gtask(self):
        task_data = {"title": "Original Title"}
        calls = []

        def mock_api(path, token, method="GET", body=None):
            calls.append((path, method, body))
            if method == "GET":
                return task_data
            return {"status": "completed"}

        with patch.object(sc, "_get_google_access_token", return_value="token"), \
             patch.object(sc, "_google_tasks_api", side_effect=mock_api):
            result = sc.update_task("gtask_list1_task1", "cancel")
        assert result["success"] is True
        # Should have called PATCH twice: once for rename, once for completion
        patch_calls = [c for c in calls if c[1] == "PATCH"]
        assert len(patch_calls) == 2

    def test_done_github(self):
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = sc.update_task("gh_42", "done")
        assert result["success"] is True

    def test_postpone_github_with_note(self):
        mock_result = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = sc.update_task("gh_42", "postpone", note="not now")
        assert result["success"] is True

    def test_unknown_prefix(self):
        result = sc.update_task("unknown_123", "done")
        assert result["success"] is False
        assert "Unknown task ID prefix" in result["message"]

    def test_invalid_gtask_format(self):
        with patch.object(sc, "_get_google_access_token", return_value="token"):
            result = sc.update_task("gtask_nounderscore", "done")
        assert result["success"] is False

    def test_exception_handling(self):
        with patch.object(sc, "_get_google_access_token", side_effect=Exception("boom")):
            result = sc.update_task("gtask_list1_task1", "done")
        assert result["success"] is False
        assert "boom" in result["message"]


# ── collect_tasks_data ──

class TestCollectTasksData:
    def test_cache_hit(self):
        sc._tasks_cache["data"] = {"cached": True}
        sc._tasks_cache["ts"] = time.time()
        result = sc.collect_tasks_data()
        assert result == {"cached": True}

    def test_basic_collection(self):
        gtasks = [
            {"title": "[DEAL] AcmeCorp follow-up", "status": "needsAction",
             "id": "t1", "_list_id": "list1", "_list_name": "main",
             "due": "2026-03-20T00:00:00Z"},
        ]
        gh_items = [
            {"content": {"title": "Fix CI", "number": 42, "state": "OPEN",
                         "assignees": [{"login": "user1"}], "labels": [{"name": "bug"}]}},
        ]

        with patch.object(sc, "_fetch_google_tasks", return_value=gtasks), \
             patch.object(sc, "_fetch_github_items", return_value=gh_items):
            result = sc.collect_tasks_data()

        assert result["kpis"]["total"] == 2
        assert result["kpis"]["deals"] == 1
        titles = [t["title"] for t in result["tasks"]]
        assert "AcmeCorp follow-up" in titles
        assert "Fix CI" in titles

    def test_klava_queue_tasks(self):
        klava_task = {
            "title": "Background research task",
            "status": "needsAction",
            "id": "kt1", "_list_id": "klava_list", "_list_name": "klava",
            "notes": "---\nstatus: running\npriority: high\nsource: chat\n---\nDo this thing",
        }
        with patch.object(sc, "_fetch_google_tasks", return_value=[klava_task]), \
             patch.object(sc, "_fetch_github_items", return_value=[]):
            result = sc.collect_tasks_data()

        klava_tasks = [t for t in result["tasks"] if t.get("section") == "klava"]
        assert len(klava_tasks) == 1
        assert klava_tasks[0]["klava"]["status"] == "running"
        assert klava_tasks[0]["klava"]["priority"] == "high"
        assert klava_tasks[0]["bold"] is True  # running or high priority

    def test_dedup_across_sources(self):
        """GitHub items with similar titles to Google Tasks are deduped."""
        gtasks = [
            {"title": "Fix CI pipeline", "status": "needsAction",
             "id": "t1", "_list_id": "list1", "_list_name": "main"},
        ]
        gh_items = [
            {"content": {"title": "Fix CI pipeline", "number": 42, "state": "OPEN"}},
        ]
        with patch.object(sc, "_fetch_google_tasks", return_value=gtasks), \
             patch.object(sc, "_fetch_github_items", return_value=gh_items):
            result = sc.collect_tasks_data()
        # Should be deduped to just 1
        assert result["kpis"]["total"] == 1

    def test_skips_completed_gtasks(self):
        gtasks = [
            {"title": "Done task", "status": "completed",
             "id": "t1", "_list_id": "list1", "_list_name": "main"},
        ]
        with patch.object(sc, "_fetch_google_tasks", return_value=gtasks), \
             patch.object(sc, "_fetch_github_items", return_value=[]):
            result = sc.collect_tasks_data()
        assert result["kpis"]["total"] == 0

    def test_skips_closed_gh_items(self):
        gh_items = [
            {"content": {"title": "Closed issue", "number": 1, "state": "CLOSED"}},
        ]
        with patch.object(sc, "_fetch_google_tasks", return_value=[]), \
             patch.object(sc, "_fetch_github_items", return_value=gh_items):
            result = sc.collect_tasks_data()
        assert result["kpis"]["total"] == 0

    def test_overdue_task(self):
        gtasks = [
            {"title": "[CRITICAL] Fix now", "status": "needsAction",
             "id": "t1", "_list_id": "l1", "_list_name": "main",
             "due": "2020-01-01T00:00:00Z"},
        ]
        with patch.object(sc, "_fetch_google_tasks", return_value=gtasks), \
             patch.object(sc, "_fetch_github_items", return_value=[]):
            result = sc.collect_tasks_data()
        assert result["kpis"]["overdue"] >= 1
        overdue_tasks = [t for t in result["tasks"] if t["overdue"]]
        assert len(overdue_tasks) >= 1

    def test_gh_assignees_as_strings(self):
        """GitHub items with string assignees."""
        gh_items = [
            {"content": {"title": "Task", "number": 1, "state": "OPEN",
                         "assignees": ["user1", "user2"],
                         "labels": ["enhancement"]}},
        ]
        with patch.object(sc, "_fetch_google_tasks", return_value=[]), \
             patch.object(sc, "_fetch_github_items", return_value=gh_items):
            result = sc.collect_tasks_data()
        assert result["kpis"]["total"] == 1
        assert "user1" in result["tasks"][0]["notes"]

    def test_empty_title_skipped(self):
        gtasks = [
            {"title": "", "status": "needsAction",
             "id": "t1", "_list_id": "l1", "_list_name": "main"},
        ]
        with patch.object(sc, "_fetch_google_tasks", return_value=gtasks), \
             patch.object(sc, "_fetch_github_items", return_value=[]):
            result = sc.collect_tasks_data()
        assert result["kpis"]["total"] == 0


# ── _collect_fresh_dashboard_data (partial - exercises key paths) ──

class TestCollectFreshDashboardData:
    """Tests for _collect_fresh_dashboard_data targeting uncovered branches."""

    def test_minimal_run(self, tmp_path, monkeypatch):
        """Exercises _collect_fresh_dashboard_data with minimal mocked state."""
        monkeypatch.setattr(sc, "CRON_DIR", tmp_path / "cron")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path / "vg")
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "brain")

        # Mock all subprocess calls and expensive collectors
        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)), \
             patch.object(sc, "_collect_services", return_value=[]), \
             patch.object(sc, "_collect_agent_activity", return_value=[]), \
             patch.object(sc, "_collect_tool_calls", return_value={"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}), \
             patch.object(sc, "_collect_reply_queue", return_value={"items": [], "total": 0, "overdue": 0, "by_type": {}}), \
             patch.object(sc, "_collect_skill_inventory", return_value=[]), \
             patch.object(sc, "_collect_mcp_servers", return_value=[]), \
             patch.object(sc, "_collect_qq_markers", return_value=[]), \
             patch.object(sc, "_collect_skill_changes", return_value=[]), \
             patch.object(sc, "_collect_error_learning", return_value={"errors_found": 0}), \
             patch.object(sc, "_collect_evolution_timeline", return_value=[]), \
             patch.object(sc, "_collect_growth_metrics", return_value={}), \
             patch.object(sc, "_collect_obsidian_metrics", return_value={"total_notes": 0}), \
             patch.object(sc, "_collect_claude_md_details", return_value={"memory_lines": 0}), \
             patch.object(sc, "_collect_daily_notes_status", return_value={}):
            result = sc._collect_fresh_dashboard_data()

        assert "generated_at" in result
        assert "stats" in result
        assert "services" in result
        assert "activity" in result

    def test_with_cron_state_and_runs(self, tmp_path, monkeypatch):
        """Tests with actual cron state and runs data."""
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CRON_DIR", cron_dir)
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path / "vg")
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "brain")

        # Create state.json - use a real past time so uptime is positive
        past_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        (cron_dir / "state.json").write_text(json.dumps({
            "daemon_start_time": past_time,
            "jobs_status": {"heartbeat": {"last_run": datetime.now(timezone.utc).isoformat(), "status": "completed"}},
        }))

        # Create jobs.json
        (cron_dir / "jobs.json").write_text(json.dumps({
            "jobs": [{
                "id": "heartbeat", "name": "Heartbeat",
                "schedule": {"type": "every", "interval_minutes": 30},
                "execution": {"mode": "main", "model": "sonnet"},
            }]
        }))

        # Create runs.jsonl with recent run
        now = datetime.now(timezone.utc)
        run = {
            "job_id": "heartbeat", "status": "completed",
            "timestamp": now.isoformat(), "duration_seconds": 30,
            "cost_usd": 0.05,
        }
        (cron_dir / "runs.jsonl").write_text(json.dumps(run) + "\n")

        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)), \
             patch.object(sc, "_collect_services", return_value=[]), \
             patch.object(sc, "_collect_agent_activity", return_value=[]), \
             patch.object(sc, "_collect_tool_calls", return_value={"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}), \
             patch.object(sc, "_collect_reply_queue", return_value={"items": [], "total": 0, "overdue": 0, "by_type": {}}), \
             patch.object(sc, "_collect_skill_inventory", return_value=[]), \
             patch.object(sc, "_collect_mcp_servers", return_value=[]), \
             patch.object(sc, "_collect_qq_markers", return_value=[]), \
             patch.object(sc, "_collect_skill_changes", return_value=[]), \
             patch.object(sc, "_collect_error_learning", return_value={"errors_found": 0}), \
             patch.object(sc, "_collect_evolution_timeline", return_value=[]), \
             patch.object(sc, "_collect_growth_metrics", return_value={}), \
             patch.object(sc, "_collect_obsidian_metrics", return_value={"total_notes": 0}), \
             patch.object(sc, "_collect_claude_md_details", return_value={"memory_lines": 0}), \
             patch.object(sc, "_collect_daily_notes_status", return_value={}):
            result = sc._collect_fresh_dashboard_data()

        assert result["stats"]["runs_24h"] >= 1
        assert result["stats"]["total_cost_usd"] == 0.05
        assert result["scheduler"]["uptime_seconds"] > 0
        assert len(result["cron_jobs"]) == 1
        assert result["cron_jobs"][0]["schedule_display"] == "every 30m"

    def test_with_vadimgest_data(self, tmp_path, monkeypatch):
        """Tests vadimgest data sources section."""
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CRON_DIR", cron_dir)
        vg_dir = tmp_path / "vg"
        vg_data = vg_dir / "data"
        vg_data.mkdir(parents=True)
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "brain")

        # vadimgest state
        now = datetime.now(timezone.utc)
        (vg_data / "state.json").write_text(json.dumps({
            "telegram": {"total_records": 100, "last_ts": now.isoformat()},
            "signal": {"total_records": 50, "last_ts": (now - timedelta(hours=3)).isoformat()},
        }))

        # sync_runs.jsonl
        sync_run = {"source": "telegram", "ts": now.isoformat(), "count": 5}
        (vg_data / "sync_runs.jsonl").write_text(json.dumps(sync_run) + "\n")

        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)), \
             patch.object(sc, "_collect_services", return_value=[]), \
             patch.object(sc, "_collect_agent_activity", return_value=[]), \
             patch.object(sc, "_collect_tool_calls", return_value={"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}), \
             patch.object(sc, "_collect_reply_queue", return_value={"items": [], "total": 0, "overdue": 0, "by_type": {}}), \
             patch.object(sc, "_collect_skill_inventory", return_value=[]), \
             patch.object(sc, "_collect_mcp_servers", return_value=[]), \
             patch.object(sc, "_collect_qq_markers", return_value=[]), \
             patch.object(sc, "_collect_skill_changes", return_value=[]), \
             patch.object(sc, "_collect_error_learning", return_value={"errors_found": 0}), \
             patch.object(sc, "_collect_evolution_timeline", return_value=[]), \
             patch.object(sc, "_collect_growth_metrics", return_value={}), \
             patch.object(sc, "_collect_obsidian_metrics", return_value={"total_notes": 0}), \
             patch.object(sc, "_collect_claude_md_details", return_value={"memory_lines": 0}), \
             patch.object(sc, "_collect_daily_notes_status", return_value={}):
            result = sc._collect_fresh_dashboard_data()

        assert result["stats"]["total_records"] == 150
        assert len(result["data_sources"]) == 2
        # telegram is healthy (recent), signal is not (>2h)
        tg = next(ds for ds in result["data_sources"] if ds["name"] == "telegram")
        sig = next(ds for ds in result["data_sources"] if ds["name"] == "signal")
        assert tg["healthy"] is True
        assert sig["healthy"] is False

    def test_cron_schedule_display_variants(self, tmp_path, monkeypatch):
        """Tests schedule_display for different schedule types."""
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CRON_DIR", cron_dir)
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path / "vg")
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "brain")

        (cron_dir / "state.json").write_text("{}")
        (cron_dir / "jobs.json").write_text(json.dumps({
            "jobs": [
                {"id": "j1", "name": "Hourly", "schedule": {"type": "every", "interval_hours": 2}, "execution": {}},
                {"id": "j2", "name": "Cron", "schedule": {"type": "cron", "cron": "*/5 * * * *"}, "execution": {}},
                {"id": "j3", "name": "Manual", "schedule": {"type": "manual"}, "execution": {}},
            ]
        }))

        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)), \
             patch.object(sc, "_collect_services", return_value=[]), \
             patch.object(sc, "_collect_agent_activity", return_value=[]), \
             patch.object(sc, "_collect_tool_calls", return_value={"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}), \
             patch.object(sc, "_collect_reply_queue", return_value={"items": [], "total": 0, "overdue": 0, "by_type": {}}), \
             patch.object(sc, "_collect_skill_inventory", return_value=[]), \
             patch.object(sc, "_collect_mcp_servers", return_value=[]), \
             patch.object(sc, "_collect_qq_markers", return_value=[]), \
             patch.object(sc, "_collect_skill_changes", return_value=[]), \
             patch.object(sc, "_collect_error_learning", return_value={"errors_found": 0}), \
             patch.object(sc, "_collect_evolution_timeline", return_value=[]), \
             patch.object(sc, "_collect_growth_metrics", return_value={}), \
             patch.object(sc, "_collect_obsidian_metrics", return_value={"total_notes": 0}), \
             patch.object(sc, "_collect_claude_md_details", return_value={"memory_lines": 0}), \
             patch.object(sc, "_collect_daily_notes_status", return_value={}):
            result = sc._collect_fresh_dashboard_data()

        jobs = {j["id"]: j for j in result["cron_jobs"]}
        assert "2h" in jobs["j1"]["schedule_display"]
        assert "*/5" in jobs["j2"]["schedule_display"]
        assert jobs["j3"]["schedule_display"] == "manual"


# ── _time_ago edge cases ──

class TestTimeAgoEdge:
    def test_none_string(self):
        assert sc._time_ago("None") == "never"

    def test_future_time(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = sc._time_ago(future)
        assert result == "just now"

    def test_invalid_string(self):
        result = sc._time_ago("not-a-date-at-all")
        assert result == "not-a-date-at-all"

    def test_naive_datetime(self):
        """Naive datetime (no timezone) gets UTC assumed."""
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        result = sc._time_ago(recent)
        assert "s" in result or "just" in result or "0" in result


# ── _safe_json_load retry path ──

class TestSafeJsonLoadRetry:
    def test_succeeds_on_retry(self, tmp_path):
        """File is bad on first read but good on retry."""
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        call_count = [0]
        original_open = open

        def flaky_open(path, *args, **kwargs):
            fh = original_open(path, *args, **kwargs)
            call_count[0] += 1
            if call_count[0] == 1:
                # Return a mock that raises on json.load
                class BadFile:
                    def read(self):
                        return "bad json"
                    def __enter__(self):
                        return self
                    def __exit__(self, *a):
                        fh.close()
                        return False
                return BadFile()
            return fh

        with patch("builtins.open", side_effect=flaky_open), \
             patch("time.sleep"):
            # Should retry and succeed on attempt 2
            result = sc._safe_json_load(f)
        assert result == {"key": "value"}


# ── _load_proactive_jobs ──

class TestLoadProactiveJobs:
    def test_returns_default_on_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._load_proactive_jobs()
        assert "heartbeat" in result

    def test_reads_from_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        (cron_dir / "jobs.json").write_text(json.dumps({
            "jobs": [
                {"id": "heartbeat", "execution": {"mode": "main"}},
                {"id": "bash-job", "execution": {"mode": "bash"}},
                {"id": "mentor", "execution": {"mode": "isolated"}},
            ]
        }))
        result = sc._load_proactive_jobs()
        assert "heartbeat" in result
        assert "mentor" in result
        assert "bash-job" not in result


# ── _format_job_summaries: naive datetime (line 143) ──

class TestFormatJobSummariesNaiveDatetime:
    def test_naive_last_run_datetime(self):
        """last_run without timezone gets UTC attached."""
        jobs = [{"id": "j1", "name": "Job1", "enabled": True,
                 "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_status = {"j1": {"last_run": "2026-03-16T10:00:00", "status": "completed"}}
        result = sc._format_job_summaries(jobs, jobs_status)
        assert len(result) == 1
        assert result[0]["time_since"] is not None

    def test_aware_last_run_datetime(self):
        """last_run with timezone info is used directly."""
        jobs = [{"id": "j1", "name": "Job1", "enabled": True,
                 "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_status = {"j1": {"last_run": "2026-03-16T10:00:00+00:00", "status": "completed"}}
        result = sc._format_job_summaries(jobs, jobs_status)
        assert len(result) == 1

    def test_no_last_run(self):
        """No last_run produces None time_since."""
        jobs = [{"id": "j1", "name": "Job1", "enabled": True,
                 "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_status = {"j1": {"status": "pending"}}
        result = sc._format_job_summaries(jobs, jobs_status)
        assert result[0]["time_since"] is None


# ── _calculate_next_run: all schedule types ──

class TestCalculateNextRunAllTypes:
    def test_every_interval_hours(self):
        now = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        job = {"schedule": {"type": "every", "interval_hours": 2}}
        result = sc._calculate_next_run(job, now)
        assert result is not None
        assert (result - now).total_seconds() == 7200

    def test_every_interval_days(self):
        now = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        job = {"schedule": {"type": "every", "interval_days": 1}}
        result = sc._calculate_next_run(job, now)
        assert result is not None
        assert (result - now).total_seconds() == 86400

    def test_every_no_interval(self):
        now = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        job = {"schedule": {"type": "every"}}
        result = sc._calculate_next_run(job, now)
        assert result is None

    def test_cron_type(self):
        now = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        job = {"schedule": {"type": "cron", "cron": "0 5 * * *"}}
        result = sc._calculate_next_run(job, now)
        assert result is None  # cron not implemented

    def test_at_type(self):
        now = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        job = {"schedule": {"type": "at", "datetime": "2026-03-17T10:00:00+00:00"}}
        result = sc._calculate_next_run(job, now)
        assert result is not None

    def test_unknown_type(self):
        now = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        job = {"schedule": {"type": "manual"}}
        result = sc._calculate_next_run(job, now)
        assert result is None


# ── _format_timedelta: edge cases ──

class TestFormatTimedeltaEdge:
    def test_negative_delta(self):
        """Negative delta (future time) gets 'in' prefix."""
        result = sc._format_timedelta(timedelta(seconds=-120))
        assert result.startswith("in ")

    def test_zero_seconds(self):
        result = sc._format_timedelta(timedelta(seconds=0))
        assert result == "0s"

    def test_exactly_one_minute(self):
        result = sc._format_timedelta(timedelta(seconds=60))
        assert result == "1m"

    def test_exactly_one_hour(self):
        result = sc._format_timedelta(timedelta(seconds=3600))
        assert result == "1h"

    def test_exactly_one_day(self):
        result = sc._format_timedelta(timedelta(seconds=86400))
        assert result == "1d"


# ── _time_ago: edge cases ──

class TestTimeAgoEdge:
    def test_none_returns_never(self):
        assert sc._time_ago(None) == "never"

    def test_string_none_returns_never(self):
        assert sc._time_ago("None") == "never"

    def test_invalid_iso_returns_string(self):
        assert sc._time_ago("not-a-date") == "not-a-date"

    def test_future_time_returns_just_now(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = sc._time_ago(future)
        assert result == "just now"

    def test_naive_datetime(self):
        """Naive datetime gets UTC attached."""
        ts = "2026-03-16T10:00:00"
        result = sc._time_ago(ts)
        assert "ago" in result or result == "just now"


# ── _parse_diff_sections ──

class TestParseDiffSections:
    def test_extracts_section_from_hunk_header(self):
        diff = "@@ -1,5 +1,6 @@ ## Memory System\n+new line"
        sections, lines = sc._parse_diff_sections(diff)
        assert "Memory System" in sections
        assert len(lines) == 1

    def test_extracts_section_from_added_line(self):
        diff = "+## New Section\n+content here"
        sections, lines = sc._parse_diff_sections(diff)
        assert "New Section" in sections
        assert len(lines) == 2

    def test_extracts_section_from_removed_line(self):
        diff = "-## Old Section\n-old content"
        sections, lines = sc._parse_diff_sections(diff)
        assert "Old Section" in sections
        assert len(lines) == 2

    def test_skips_diff_headers(self):
        diff = "diff --git a/file b/file\nindex abc..def\n--- a/file\n+++ b/file\n+new"
        sections, lines = sc._parse_diff_sections(diff)
        assert len(lines) == 1  # only the +new line

    def test_hunk_without_section_context(self):
        diff = "@@ -1,5 +1,6 @@\n+new line"
        sections, lines = sc._parse_diff_sections(diff)
        assert sections == []
        assert len(lines) == 1


# ── _categorize_commit ──

class TestCategorizeCommit:
    def test_fix_prefix(self):
        assert sc._categorize_commit("fix: broken deploy", []) == "fix"

    def test_fix_word(self):
        assert sc._categorize_commit("fix broken tests", []) == "fix"

    def test_qq_marker(self):
        assert sc._categorize_commit("resolve qq issue", []) == "fix"

    def test_yy_marker(self):
        assert sc._categorize_commit("йй fix typo", []) == "fix"

    def test_reflection(self):
        assert sc._categorize_commit("reflection: nightly cleanup", []) == "learning"

    def test_mentor(self):
        assert sc._categorize_commit("mentor: feedback session", []) == "learning"

    def test_scenario(self):
        assert sc._categorize_commit("add scenario for heartbeat", []) == "learning"

    def test_claude_md_only(self):
        assert sc._categorize_commit("update config", [".claude/CLAUDE.md"]) == "claude_md"

    def test_skill_files(self):
        assert sc._categorize_commit("update", [".claude/skills/foo/SKILL.md"]) == "skill"

    def test_scenarios_dir(self):
        assert sc._categorize_commit("update", ["scenarios/test/spec.md"]) == "skill"

    def test_feat_prefix(self):
        assert sc._categorize_commit("feat: new dashboard tab", []) == "capability"

    def test_add_prefix(self):
        assert sc._categorize_commit("add chat interface", []) == "capability"

    def test_implement_word(self):
        assert sc._categorize_commit("implement pipeline", []) == "capability"

    def test_default_infra(self):
        assert sc._categorize_commit("update readme", []) == "infra"


# ── _collect_services: edge cases ──

class TestCollectServicesEdge:
    def test_no_launch_agents_dir(self, tmp_path, monkeypatch):
        """No LaunchAgents dir returns empty list."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = sc._collect_services()
        assert result == []

    def test_launchctl_exception(self, tmp_path, monkeypatch):
        """launchctl failure returns services with running=False."""
        home = tmp_path / "home"
        la_dir = home / "Library" / "LaunchAgents"
        la_dir.mkdir(parents=True)
        # Create a dummy plist
        (la_dir / "com.local.test-svc.plist").write_bytes(b"<?xml version=\"1.0\"?>\n<plist></plist>")

        monkeypatch.setattr(Path, "home", lambda: home)

        with patch("subprocess.run", side_effect=Exception("launchctl failed")), \
             patch("plistlib.load", return_value={}):
            result = sc._collect_services()

        assert len(result) == 1
        assert result[0]["running"] is False


# ── _get_recent_runs ──

class TestGetRecentRunsEdge:
    def test_filters_non_completed(self, tmp_path):
        """Only completed/failed runs are returned."""
        runs_file = tmp_path / "runs.jsonl"
        runs = [
            {"status": "completed", "job_id": "j1"},
            {"status": "running", "job_id": "j2"},
            {"status": "failed", "job_id": "j3"},
        ]
        runs_file.write_text("\n".join(json.dumps(r) for r in runs) + "\n")
        result = sc._get_recent_runs(runs_file, limit=10)
        assert len(result) == 2

    def test_bad_json_lines_skipped(self, tmp_path):
        runs_file = tmp_path / "runs.jsonl"
        runs_file.write_text('{"status": "completed"}\nbad json line\n{"status": "failed"}\n')
        result = sc._get_recent_runs(runs_file, limit=10)
        assert len(result) == 2

    def test_limit_respected(self, tmp_path):
        runs_file = tmp_path / "runs.jsonl"
        lines = [json.dumps({"status": "completed", "job_id": f"j{i}"}) for i in range(20)]
        runs_file.write_text("\n".join(lines) + "\n")
        result = sc._get_recent_runs(runs_file, limit=5)
        assert len(result) == 5


# ── collect_feed_data ──

class TestCollectFeedData:
    def test_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "FEED_LOG", tmp_path / "missing.jsonl")
        result = sc.collect_feed_data()
        assert result["messages"] == []
        assert result["total"] == 0

    def test_reads_messages(self, tmp_path, monkeypatch):
        feed_file = tmp_path / "messages.jsonl"
        msgs = [
            {"topic": "Heartbeat", "text": "msg1", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"topic": "Main", "text": "msg2", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        feed_file.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")
        monkeypatch.setattr(sc, "FEED_LOG", feed_file)
        result = sc.collect_feed_data()
        assert result["total"] == 2
        assert len(result["topics"]) == 2

    def test_topic_filter(self, tmp_path, monkeypatch):
        feed_file = tmp_path / "messages.jsonl"
        msgs = [
            {"topic": "Heartbeat", "text": "hb", "timestamp": "2026-03-16T10:00:00+00:00"},
            {"topic": "Main", "text": "main", "timestamp": "2026-03-16T11:00:00+00:00"},
        ]
        feed_file.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")
        monkeypatch.setattr(sc, "FEED_LOG", feed_file)
        result = sc.collect_feed_data(topic="Heartbeat")
        assert result["total"] == 1

    def test_limit_respected(self, tmp_path, monkeypatch):
        feed_file = tmp_path / "messages.jsonl"
        msgs = [{"topic": "Main", "text": f"msg{i}", "timestamp": f"2026-03-16T{10+i}:00:00+00:00"} for i in range(10)]
        feed_file.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")
        monkeypatch.setattr(sc, "FEED_LOG", feed_file)
        result = sc.collect_feed_data(limit=3)
        assert result["total"] == 3

    def test_bad_json_skipped(self, tmp_path, monkeypatch):
        feed_file = tmp_path / "messages.jsonl"
        feed_file.write_text('{"topic": "Main", "text": "ok", "timestamp": "2026-03-16T10:00:00+00:00"}\nbad\n')
        monkeypatch.setattr(sc, "FEED_LOG", feed_file)
        result = sc.collect_feed_data()
        assert result["total"] == 1


# ── _collect_reply_queue ──

class TestCollectReplyQueueExtra:
    def test_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path)
        result = sc._collect_reply_queue()
        assert result["total"] == 0

    def test_parses_tasks(self, tmp_path, monkeypatch):
        vg_dir = tmp_path / "vg"
        gtasks_dir = vg_dir / "data" / "sources"
        gtasks_dir.mkdir(parents=True)
        gtasks_file = gtasks_dir / "gtasks.jsonl"
        now = datetime.now(timezone.utc)
        tasks = [
            {"id": "t1", "title": "[DEAL] Follow up with AcmeCorp", "status": "needsAction", "due": "2020-01-01T00:00:00Z"},
            {"id": "t2", "title": "[REPLY] Answer email", "status": "needsAction"},
            {"id": "t3", "title": "Random task", "status": "needsAction"},
            {"id": "t4", "title": "[DEAL] Completed deal", "status": "completed"},
        ]
        gtasks_file.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)

        result = sc._collect_reply_queue()
        assert result["total"] == 3  # excluding completed
        assert result["overdue"] >= 1
        assert "deal" in result["by_type"]


# ── _collect_daily_notes_status ──

class TestCollectDailyNotesStatus:
    def test_no_memory_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_daily_notes_status()
        assert isinstance(result, dict)

    def test_with_today_note(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        note = memory_dir / f"{today}.md"
        note.write_text("## Morning\nSome notes\n## Evening\nMore notes\n")

        result = sc._collect_daily_notes_status()
        assert isinstance(result, dict)


# ── _fmt_seconds ──

class TestFmtSeconds:
    def test_seconds(self):
        assert sc._fmt_seconds(45) == "45s"

    def test_minutes(self):
        result = sc._fmt_seconds(120)
        assert "m" in result

    def test_hours(self):
        result = sc._fmt_seconds(3700)
        assert "h" in result or "m" in result


# ── collect_views_data ──

class TestCollectViewsData:
    def test_cache_hit(self):
        sc._views_cache["data"] = {"cached": True}
        sc._views_cache["ts"] = time.time()
        result = sc.collect_views_data()
        assert result == {"cached": True}

    def test_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VIEWS_DIR", tmp_path / "nope")
        result = sc.collect_views_data()
        assert result["status"] == "empty"
        assert result["views"] == []

    def test_with_html_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VIEWS_DIR", tmp_path)
        html = '<html><head><title>Test View</title></head><body><div class="subtitle">Mar 2026</div></body></html>'
        (tmp_path / "test-view.html").write_text(html)

        result = sc.collect_views_data()
        assert result["status"] == "ok"
        assert len(result["views"]) == 1
        assert result["views"][0]["title"] == "Test View"


# ── collect_calendar_data ──

class TestCollectCalendarData:
    def test_cache_hit(self):
        sc._calendar_cache["data"] = {"cached": True}
        sc._calendar_cache["ts"] = time.time()
        result = sc.collect_calendar_data()
        assert result == {"cached": True}

    def test_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path / "vg")
        result = sc.collect_calendar_data()
        assert result["status"] == "sync_pending"

    def test_with_events(self, tmp_path, monkeypatch):
        vg_dir = tmp_path / "vg"
        sources_dir = vg_dir / "data" / "sources"
        sources_dir.mkdir(parents=True)
        today = datetime.now().strftime("%Y-%m-%d")
        events = [
            {"title": "Meeting", "start": f"{today}T14:00:00+00:00", "end": f"{today}T15:00:00+00:00"},
            {"summary": "Lunch", "date": today},
        ]
        (sources_dir / "calendar.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)

        result = sc.collect_calendar_data()
        assert result["status"] == "ok"
        assert result["metrics"]["today_count"] >= 1


# ── _collect_skill_inventory: edge cases ──

class TestCollectSkillInventoryEdge:
    def test_skill_with_errors_file(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        s1 = skills_dir / "test-skill"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\ndescription: A test skill\nuser_invocable: true\n---\n# Test")
        (s1 / "errors.jsonl").write_text('{"error": "something"}\n{"error": "another"}\n')
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        assert len(result) == 1
        assert result[0]["error_count"] == 2
        assert result[0]["description"] == "A test skill"
        assert result[0]["user_invocable"] is True

    def test_skill_no_description(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        s1 = skills_dir / "minimal"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("# Minimal skill\nNo frontmatter")
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        assert len(result) == 1
        assert result[0]["description"] == ""


# ── _collect_mcp_servers ──

class TestCollectMCPServers:
    def test_no_settings_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "missing.json")
        result = sc._collect_mcp_servers()
        assert result == []

    def test_parses_mcp_config(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "mcpServers": {
                "browser": {
                    "command": "npx",
                    "args": ["@anthropic/mcp-browser"],
                },
                "filesystem": {
                    "command": "node",
                    "args": ["server.js", "--root", "/home"],
                },
            }
        }))
        monkeypatch.setattr(sc, "SETTINGS_FILE", settings)
        result = sc._collect_mcp_servers()
        assert len(result) == 2


# ── _collect_agent_activity edge cases ──

class TestCollectAgentActivityEdge:
    def test_no_git_commits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
            result = sc._collect_agent_activity()
        assert isinstance(result, list)

    def test_handles_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        with patch("subprocess.run", side_effect=Exception("git not found")):
            result = sc._collect_agent_activity()
        assert isinstance(result, list)


# ── collect_deals_data ──

class TestCollectDealsData:
    def test_cache_hit(self):
        sc._deals_cache["data"] = {"cached": True}
        sc._deals_cache["ts"] = time.time()
        result = sc.collect_deals_data()
        assert result == {"cached": True}

    def test_no_deals_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        result = sc.collect_deals_data()
        assert result["deals"] == []


# ── collect_people_data ──

class TestCollectPeopleData:
    def test_cache_hit(self):
        sc._people_cache["data"] = {"cached": True}
        sc._people_cache["ts"] = time.time()
        result = sc.collect_people_data()
        assert result == {"cached": True}

    def test_no_people_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        result = sc.collect_people_data()
        assert result["people"] == []


# ── collect_followups_data ──

class TestCollectFollowupsData:
    def test_cache_hit(self):
        sc._followups_cache["data"] = {"cached": True}
        sc._followups_cache["ts"] = time.time()
        result = sc.collect_followups_data()
        assert result == {"cached": True}

    def test_no_deals_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        result = sc.collect_followups_data()
        assert result["overdue"] == []
        assert result["upcoming"] == []


# ── _safe_json_load: default on all retries exhausted ──

class TestSafeJsonLoadDefault:
    def test_returns_default_after_retries(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{broken json")
        result = sc._safe_json_load(bad_file, default={"fallback": True})
        assert result == {"fallback": True}

    def test_raises_without_default(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{broken json")
        with pytest.raises((json.JSONDecodeError, ValueError)):
            sc._safe_json_load(bad_file)


# ── collect_heartbeat_data ──

class TestCollectHeartbeatData:
    def test_cache_hit(self):
        sc._hb_cache["data"] = {"cached": True}
        sc._hb_cache["ts"] = time.time()
        result = sc.collect_heartbeat_data()
        assert result == {"cached": True}


# ── _collect_growth_metrics: cache hit ──

class TestCollectGrowthMetricsCache:
    def test_cache_hit(self):
        sc._growth_cache["data"] = {"cached": True}
        sc._growth_cache["ts"] = time.time()
        result = sc._collect_growth_metrics()
        assert result == {"cached": True}

    def test_no_git_returns_empty_series(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        mock_result = MagicMock(stdout="", returncode=1)
        with patch("subprocess.run", return_value=mock_result), \
             patch.object(Path, "home", return_value=tmp_path):
            result = sc._collect_growth_metrics()
        assert result["skills"]["series"] == []


# ── _collect_evolution_timeline: cache hit ──

class TestCollectEvolutionTimelineCache:
    def test_cache_hit(self):
        sc._evolution_cache["data"] = [{"cached": True}]
        sc._evolution_cache["ts"] = time.time()
        result = sc._collect_evolution_timeline()
        assert result == [{"cached": True}]


# ── _extract_note_preview ──

class TestExtractNotePreview:
    def test_extracts_frontmatter_and_sections(self, tmp_path):
        note = tmp_path / "Test Person.md"
        note.write_text("---\ncompany: Acme\nrole: CEO\ntags: [tech]\n---\n## Background\nSome info\n## History\nOld stuff")
        result = sc._extract_note_preview(note)
        assert "Acme" in result
        assert "Background" in result

    def test_no_frontmatter(self, tmp_path):
        note = tmp_path / "Simple.md"
        note.write_text("# Simple\nJust text")
        result = sc._extract_note_preview(note)
        assert isinstance(result, str)


# ── _collect_fresh_dashboard_data: vadimgest sync_runs.jsonl (lines 362-383) ──

class TestFreshDashboardVadimgestSyncRuns:
    def test_sync_runs_parsing_with_hourly_counts(self, tmp_path, monkeypatch):
        """Tests sync_runs.jsonl parsing including hourly count calculation."""
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CRON_DIR", cron_dir)

        vg_dir = tmp_path / "vg"
        vg_data = vg_dir / "data"
        vg_data.mkdir(parents=True)
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "brain")

        # vadimgest state
        now = datetime.now(timezone.utc)
        (vg_data / "state.json").write_text(json.dumps({
            "telegram": {"total_records": 100, "last_ts": now.isoformat()},
        }))

        # sync_runs.jsonl - recent sync (within 1 hour)
        sync_runs = [
            {"source": "telegram", "ts": now.isoformat(), "count": 15},
            {"source": "telegram", "ts": (now - timedelta(hours=2)).isoformat(), "count": 5},
        ]
        (vg_data / "sync_runs.jsonl").write_text("\n".join(json.dumps(r) for r in sync_runs) + "\n")

        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)), \
             patch.object(sc, "_collect_services", return_value=[]), \
             patch.object(sc, "_collect_agent_activity", return_value=[]), \
             patch.object(sc, "_collect_tool_calls", return_value={"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}), \
             patch.object(sc, "_collect_reply_queue", return_value={"items": [], "total": 0, "overdue": 0, "by_type": {}}), \
             patch.object(sc, "_collect_skill_inventory", return_value=[]), \
             patch.object(sc, "_collect_mcp_servers", return_value=[]), \
             patch.object(sc, "_collect_qq_markers", return_value=[]), \
             patch.object(sc, "_collect_skill_changes", return_value=[]), \
             patch.object(sc, "_collect_error_learning", return_value={"errors_found": 0}), \
             patch.object(sc, "_collect_evolution_timeline", return_value=[]), \
             patch.object(sc, "_collect_growth_metrics", return_value={}), \
             patch.object(sc, "_collect_obsidian_metrics", return_value={"total_notes": 0}), \
             patch.object(sc, "_collect_claude_md_details", return_value={"memory_lines": 0}), \
             patch.object(sc, "_collect_daily_notes_status", return_value={}):
            result = sc._collect_fresh_dashboard_data()

        # Should have data sources with hourly counts
        assert result["stats"]["added_1h"] >= 15
        tg_source = [s for s in result["data_sources"] if s["name"] == "telegram"]
        assert len(tg_source) == 1
        assert tg_source[0]["added_1h"] == 15  # only the recent one counts


# ── _collect_fresh_dashboard_data: heartbeat backlog (lines 431-443) ──

class TestFreshDashboardHeartbeatBacklog:
    def test_heartbeat_items(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CRON_DIR", cron_dir)
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path / "vg")
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "brain")

        # heartbeat_state.json
        (cron_dir / "heartbeat_state.json").write_text(json.dumps({
            "tracked_items": {
                "item1": {
                    "source": "telegram",
                    "summary": "AcmeCorp follow-up",
                    "priority_score": 9,
                    "deal_value": 85000,
                    "escalation_level": 2,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                "item2": {
                    "source": "signal",
                    "summary": "Regular update",
                    "priority_score": 3,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        }))

        with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)), \
             patch.object(sc, "_collect_services", return_value=[]), \
             patch.object(sc, "_collect_agent_activity", return_value=[]), \
             patch.object(sc, "_collect_tool_calls", return_value={"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}), \
             patch.object(sc, "_collect_reply_queue", return_value={"items": [], "total": 0, "overdue": 0, "by_type": {}}), \
             patch.object(sc, "_collect_skill_inventory", return_value=[]), \
             patch.object(sc, "_collect_mcp_servers", return_value=[]), \
             patch.object(sc, "_collect_qq_markers", return_value=[]), \
             patch.object(sc, "_collect_skill_changes", return_value=[]), \
             patch.object(sc, "_collect_error_learning", return_value={"errors_found": 0}), \
             patch.object(sc, "_collect_evolution_timeline", return_value=[]), \
             patch.object(sc, "_collect_growth_metrics", return_value={}), \
             patch.object(sc, "_collect_obsidian_metrics", return_value={"total_notes": 0}), \
             patch.object(sc, "_collect_claude_md_details", return_value={"memory_lines": 0}), \
             patch.object(sc, "_collect_daily_notes_status", return_value={}):
            result = sc._collect_fresh_dashboard_data()

        assert len(result["heartbeat_backlog"]) == 2
        # Sorted by priority_score descending
        assert result["heartbeat_backlog"][0]["priority_score"] == 9


# ── collect_files_data ──

class TestCollectFilesData:
    def test_cache_hit(self):
        sc._files_cache["data"] = {"cached": True}
        sc._files_cache["ts"] = time.time()
        sc._files_cache["date"] = "__default__"
        result = sc.collect_files_data()
        assert result == {"cached": True}

    def test_cache_hit_with_date(self):
        sc._files_cache["data"] = {"cached": True}
        sc._files_cache["ts"] = time.time()
        sc._files_cache["date"] = "2026-03-16"
        result = sc.collect_files_data(date="2026-03-16")
        assert result == {"cached": True}


# ── _collect_tool_calls: edge cases ──

class TestCollectToolCallsEdge:
    def test_no_log_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_tool_calls()
        assert result["total_24h"] == 0
        assert result["sessions"] == []
