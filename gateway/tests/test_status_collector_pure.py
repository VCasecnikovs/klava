"""Tests for pure functions in gateway/lib/status_collector.py.

Focuses on helpers that don't require subprocess or network calls.
"""

import json
import os
import sys
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.status_collector import (
    _safe_json_load,
    _format_timedelta,
    _calculate_next_run,
    _get_recent_runs,
    _categorize_commit,
    _parse_diff_sections,
    _fmt_seconds,
    _parse_klava_frontmatter,
    _categorize_task,
    _parse_deal_frontmatter,
    _parse_deal_stage,
    _parse_deal_date,
    _parse_deal_value,
    _clean_lead,
    _get_deal_weight,
    _format_job_summaries,
    _time_ago,
)


# ── _safe_json_load ──

class TestSafeJsonLoad:
    def test_loads_valid_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        assert _safe_json_load(f) == {"key": "value"}

    def test_default_on_bad_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json{{{")
        assert _safe_json_load(f, default={}) == {}

    def test_raises_without_default(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _safe_json_load(f)

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _safe_json_load(tmp_path / "missing.json")


# ── _format_timedelta ──

class TestFormatTimedelta:
    def test_seconds(self):
        assert _format_timedelta(timedelta(seconds=30)) == "30s"

    def test_minutes(self):
        assert _format_timedelta(timedelta(minutes=5)) == "5m"

    def test_hours(self):
        assert _format_timedelta(timedelta(hours=3)) == "3h"

    def test_days(self):
        assert _format_timedelta(timedelta(days=2)) == "2d"

    def test_negative_shows_in_prefix(self):
        result = _format_timedelta(timedelta(seconds=-120))
        assert result.startswith("in ")
        assert "2m" in result

    def test_zero(self):
        assert _format_timedelta(timedelta(0)) == "0s"


# ── _calculate_next_run ──

class TestCalculateNextRun:
    def test_every_minutes(self):
        job = {"schedule": {"type": "every", "interval_minutes": 30}}
        from_time = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert result is not None
        assert (result - from_time).total_seconds() == 1800

    def test_every_hours(self):
        job = {"schedule": {"type": "every", "interval_hours": 2}}
        from_time = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert (result - from_time).total_seconds() == 7200

    def test_every_days(self):
        job = {"schedule": {"type": "every", "interval_days": 1}}
        from_time = datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert (result - from_time).total_seconds() == 86400

    def test_every_no_interval(self):
        job = {"schedule": {"type": "every"}}
        result = _calculate_next_run(job, datetime.now(timezone.utc))
        assert result is None

    def test_cron_returns_none(self):
        job = {"schedule": {"type": "cron", "expression": "*/5 * * * *"}}
        result = _calculate_next_run(job, datetime.now(timezone.utc))
        assert result is None

    def test_at_type(self):
        job = {"schedule": {"type": "at", "datetime": "2026-03-20T10:00:00+00:00"}}
        result = _calculate_next_run(job, datetime.now(timezone.utc))
        assert result is not None

    def test_unknown_type(self):
        job = {"schedule": {"type": "unknown"}}
        result = _calculate_next_run(job, datetime.now(timezone.utc))
        assert result is None

    def test_no_schedule(self):
        result = _calculate_next_run({}, datetime.now(timezone.utc))
        assert result is None


# ── _get_recent_runs ──

class TestGetRecentRuns:
    def test_reads_jsonl(self, tmp_path):
        f = tmp_path / "runs.jsonl"
        entries = [
            {"status": "completed", "job_id": "a"},
            {"status": "failed", "job_id": "b"},
            {"status": "running", "job_id": "c"},  # not completed
        ]
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        result = _get_recent_runs(f)
        assert len(result) == 2  # only completed + failed

    def test_respects_limit(self, tmp_path):
        f = tmp_path / "runs.jsonl"
        entries = [{"status": "completed", "job_id": str(i)} for i in range(20)]
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        result = _get_recent_runs(f, limit=5)
        assert len(result) == 5

    def test_skips_bad_json(self, tmp_path):
        f = tmp_path / "runs.jsonl"
        f.write_text('{"status":"completed"}\nnot json\n{"status":"failed"}\n')
        result = _get_recent_runs(f)
        assert len(result) == 2

    def test_empty_file(self, tmp_path):
        f = tmp_path / "runs.jsonl"
        f.write_text("")
        result = _get_recent_runs(f)
        assert result == []


# ── _categorize_commit ──

class TestCategorizeCommit:
    def test_fix_prefix(self):
        assert _categorize_commit("fix: broken import", []) == "fix"

    def test_fix_with_space(self):
        assert _categorize_commit("fix broken thing", []) == "fix"

    def test_qq_marker(self):
        assert _categorize_commit("qq fix something", []) == "fix"

    def test_reflection(self):
        assert _categorize_commit("reflection: daily grooming", []) == "learning"

    def test_scenario(self):
        assert _categorize_commit("add scenario tests", []) == "learning"

    def test_claude_md_change(self):
        assert _categorize_commit("update instructions", [".claude/CLAUDE.md"]) == "claude_md"

    def test_skill_change(self):
        assert _categorize_commit("improve skill", [".claude/skills/heartbeat/SKILL.md"]) == "skill"

    def test_feat_prefix(self):
        assert _categorize_commit("feat: new dashboard tab", []) == "capability"

    def test_add_prefix(self):
        assert _categorize_commit("add new endpoint", []) == "capability"

    def test_default_infra(self):
        assert _categorize_commit("refactor internal code", []) == "infra"

    def test_claude_md_plus_skills(self):
        # When both touched, skill wins
        files = [".claude/CLAUDE.md", ".claude/skills/foo/SKILL.md"]
        assert _categorize_commit("update stuff", files) == "skill"


# ── _parse_diff_sections ──

class TestParseDiffSections:
    def test_extracts_sections_from_hunk_headers(self):
        diff = """diff --git a/CLAUDE.md b/CLAUDE.md
index abc..def 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -10,5 +10,6 @@ ## Memory System
+New line added
"""
        sections, lines = _parse_diff_sections(diff)
        assert "Memory System" in sections
        assert any("+New line added" in l for l in lines)

    def test_extracts_sections_from_added_headers(self):
        diff = """+## New Section
+content here
-## Old Section
-removed content
"""
        sections, lines = _parse_diff_sections(diff)
        assert "New Section" in sections
        assert "Old Section" in sections

    def test_empty_diff(self):
        sections, lines = _parse_diff_sections("")
        assert sections == []
        assert lines == []

    def test_ignores_diff_metadata(self):
        diff = """diff --git a/file.py b/file.py
index 123..456
--- a/file.py
+++ b/file.py
+real change
"""
        _, lines = _parse_diff_sections(diff)
        assert len(lines) == 1
        assert "+real change" in lines[0]


# ── _fmt_seconds ──

class TestFmtSeconds:
    def test_seconds(self):
        assert _fmt_seconds(45) == "45s"

    def test_minutes(self):
        assert _fmt_seconds(125) == "2m05s"

    def test_hours(self):
        assert _fmt_seconds(3725) == "1h02m"

    def test_zero(self):
        assert _fmt_seconds(0) == "0s"

    def test_exactly_60(self):
        assert _fmt_seconds(60) == "1m00s"


# ── _parse_klava_frontmatter ──

class TestParseKlavaFrontmatter:
    def test_with_frontmatter(self):
        text = "---\nstatus: running\npriority: high\n---\nTask body here"
        result = _parse_klava_frontmatter(text)
        assert result["status"] == "running"
        assert result["priority"] == "high"
        assert result["_body"] == "Task body here"

    def test_no_frontmatter(self):
        text = "Just plain text"
        result = _parse_klava_frontmatter(text)
        assert result["_body"] == "Just plain text"

    def test_empty_text(self):
        result = _parse_klava_frontmatter("")
        assert result["_body"] == ""

    def test_none_text(self):
        result = _parse_klava_frontmatter(None)
        assert result["_body"] == ""

    def test_unclosed_frontmatter(self):
        text = "---\nstatus: pending\nno closing"
        result = _parse_klava_frontmatter(text)
        assert "_body" in result

    def test_key_without_value(self):
        text = "---\nempty_key:\n---\nbody"
        result = _parse_klava_frontmatter(text)
        assert result["empty_key"] == ""


# ── _categorize_task ──

class TestCategorizeTask:
    def test_critical_tag(self):
        result = _categorize_task("[CRITICAL] Fix bug", None, "2026-03-16", "gtasks")
        assert result["section"] == "overdue"  # critical = urgent
        assert result["bold"] is True
        assert any(t["name"] == "CRITICAL" for t in result["tags"])

    def test_deal_tag(self):
        result = _categorize_task("[DEAL] AcmeCorp follow-up", None, "2026-03-16", "gtasks")
        assert result["section"] == "deals"
        assert result["clean_title"] == "AcmeCorp follow-up"

    def test_reply_tag(self):
        result = _categorize_task("[REPLY] Answer John", None, "2026-03-16", "gtasks")
        assert result["section"] == "replies"

    def test_overdue_by_date(self):
        result = _categorize_task("Some task", "2026-03-15T00:00:00", "2026-03-16", "gtasks")
        assert result["overdue"] is True
        assert result["section"] == "overdue"

    def test_today_by_date(self):
        result = _categorize_task("Some task", "2026-03-16T00:00:00", "2026-03-16", "gtasks")
        assert result["is_today"] is True
        assert result["section"] == "today"

    def test_github_source(self):
        result = _categorize_task("Fix CI", None, "2026-03-16", "github")
        assert result["section"] == "primary-gh"

    def test_no_tags_personal(self):
        result = _categorize_task("Buy groceries", None, "2026-03-16", "gtasks")
        assert result["section"] == "personal"
        assert result["tags"] == []

    def test_sig_tag(self):
        result = _categorize_task("[SIG] Reply to Alex", None, "2026-03-16", "gtasks")
        assert result["section"] == "replies"


# ── Deal parsing functions ──

class TestParseDealStage:
    def test_numbered_stage(self):
        num, name = _parse_deal_stage("5-proposal")
        assert num == 5
        assert name == "proposal"

    def test_number_only(self):
        num, name = _parse_deal_stage("13")
        assert num == 13
        assert name == "delivery"  # from _STAGE_NAMES

    def test_none(self):
        num, name = _parse_deal_stage(None)
        assert num == 0
        assert name == "unknown"

    def test_empty(self):
        num, name = _parse_deal_stage("")
        assert num == 0

    def test_text_only(self):
        num, name = _parse_deal_stage("custom")
        assert num == 0
        assert name == "custom"


class TestParseDealDate:
    def test_valid_date(self):
        result = _parse_deal_date("2026-03-16")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3

    def test_none(self):
        assert _parse_deal_date(None) is None

    def test_invalid_format(self):
        assert _parse_deal_date("not-a-date") is None

    def test_empty(self):
        assert _parse_deal_date("") is None


class TestParseDealValue:
    def test_integer(self):
        assert _parse_deal_value("50000") == 50000.0

    def test_with_dollar(self):
        assert _parse_deal_value("$85,000") == 85000.0

    def test_float(self):
        assert _parse_deal_value("0.05") == 0.05

    def test_none(self):
        assert _parse_deal_value(None) is None

    def test_invalid(self):
        assert _parse_deal_value("not a number") is None


class TestCleanLead:
    def test_wikilink(self):
        assert _clean_lead("[[John Doe]]") == "John Doe"

    def test_single_brackets(self):
        assert _clean_lead("[John]") == "John"

    def test_plain_name(self):
        assert _clean_lead("John Doe") == "John Doe"

    def test_none(self):
        assert _clean_lead(None) == "Unknown"

    def test_empty(self):
        assert _clean_lead("") == "Unknown"


class TestGetDealWeight:
    def test_early_stage(self):
        assert _get_deal_weight(1) == 0.10

    def test_mid_stage(self):
        assert _get_deal_weight(7) == 0.50

    def test_late_stage(self):
        assert _get_deal_weight(13) == 0.90

    def test_out_of_range(self):
        assert _get_deal_weight(99) == 0.0

    def test_zero(self):
        assert _get_deal_weight(0) == 0.0


class TestParseDealFrontmatter:
    def test_valid_frontmatter(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("---\nstage: 5-proposal\nvalue: 50000\nlead: '[[John]]'\n---\n\n# Notes")
        result = _parse_deal_frontmatter(f)
        assert result["stage"] == "5-proposal"
        assert result["value"] == "50000"
        assert result["lead"] == "[[John]]"

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("# Just a file\nno frontmatter")
        assert _parse_deal_frontmatter(f) is None

    def test_quoted_values(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text('---\nstage: "5-proposal"\nvalue: \'50000\'\n---\n')
        result = _parse_deal_frontmatter(f)
        assert result["stage"] == "5-proposal"
        assert result["value"] == "50000"

    def test_null_value(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("---\nstage: 5-proposal\nfollow_up: null\n---\n")
        result = _parse_deal_frontmatter(f)
        assert result["follow_up"] is None

    def test_nonexistent_file(self, tmp_path):
        assert _parse_deal_frontmatter(tmp_path / "missing.md") is None


# ── _time_ago ──

class TestTimeAgo:
    def test_recent(self):
        now = datetime.now(timezone.utc)
        result = _time_ago(now.isoformat())
        assert "s" in result or "just" in result.lower() or "0" in result

    def test_none(self):
        assert _time_ago(None) == "never"

    def test_old_date(self):
        result = _time_ago("2020-01-01T00:00:00+00:00")
        assert "d" in result or "h" in result


# ── _format_job_summaries ──

class TestFormatJobSummaries:
    def test_basic_summary(self):
        jobs = [{"id": "heartbeat", "name": "Heartbeat", "schedule": {"type": "every", "interval_minutes": 30}}]
        status = {"heartbeat": {"last_run": "2026-03-16T10:00:00+00:00", "status": "completed"}}
        result = _format_job_summaries(jobs, status)
        assert len(result) == 1
        assert result[0]["id"] == "heartbeat"
        assert result[0]["status"] == "completed"
        assert result[0]["time_since"] is not None

    def test_no_status(self):
        jobs = [{"id": "new-job", "name": "New"}]
        result = _format_job_summaries(jobs, {})
        assert result[0]["status"] == "pending"
        assert result[0]["time_since"] is None

    def test_multiple_jobs(self):
        jobs = [
            {"id": "a", "name": "Job A"},
            {"id": "b", "name": "Job B"},
        ]
        result = _format_job_summaries(jobs, {})
        assert len(result) == 2
