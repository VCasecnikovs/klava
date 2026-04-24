"""Tests for pure functions in status_collector.py.

Zero I/O, fully deterministic. Mocks datetime.now for time-dependent functions.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from lib.status_collector import (
    _format_timedelta,
    _time_ago,
    _categorize_commit,
    _parse_diff_sections,
    _calculate_next_run,
    _fmt_seconds,
    _parse_deal_stage,
    _parse_deal_value,
    _parse_deal_date,
    _clean_lead,
    _get_deal_weight,
)


# ── _format_timedelta ──────────────────────────────────────────────────

class TestFormatTimedelta:
    def test_seconds(self):
        delta = timedelta(seconds=45)
        assert _format_timedelta(delta) == "45s"

    def test_zero_seconds(self):
        delta = timedelta(seconds=0)
        assert _format_timedelta(delta) == "0s"

    def test_minutes(self):
        delta = timedelta(minutes=5)
        assert _format_timedelta(delta) == "5m"

    def test_minutes_boundary(self):
        delta = timedelta(seconds=59)
        assert _format_timedelta(delta) == "59s"

    def test_minutes_exact(self):
        delta = timedelta(seconds=60)
        assert _format_timedelta(delta) == "1m"

    def test_hours(self):
        delta = timedelta(hours=3)
        assert _format_timedelta(delta) == "3h"

    def test_hours_boundary(self):
        delta = timedelta(seconds=3599)
        assert _format_timedelta(delta) == "59m"

    def test_hours_exact(self):
        delta = timedelta(seconds=3600)
        assert _format_timedelta(delta) == "1h"

    def test_days(self):
        delta = timedelta(days=7)
        assert _format_timedelta(delta) == "7d"

    def test_days_boundary(self):
        delta = timedelta(seconds=86399)
        assert _format_timedelta(delta) == "23h"

    def test_negative_timedelta_has_prefix(self):
        delta = timedelta(seconds=-120)
        result = _format_timedelta(delta)
        assert result.startswith("in ")
        assert "2m" in result

    def test_negative_seconds(self):
        delta = timedelta(seconds=-30)
        result = _format_timedelta(delta)
        assert result == "in 30s"

    def test_negative_hours(self):
        delta = timedelta(hours=-5)
        result = _format_timedelta(delta)
        assert result == "in 5h"


# ── _time_ago ──────────────────────────────────────────────────────────

class TestTimeAgo:
    FIXED_NOW = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)

    @patch("lib.status_collector.datetime")
    def test_seconds_ago(self, mock_dt):
        mock_dt.now.return_value = self.FIXED_NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _time_ago("2026-02-23T11:59:30+00:00")
        assert result == "30s ago"

    @patch("lib.status_collector.datetime")
    def test_minutes_ago(self, mock_dt):
        mock_dt.now.return_value = self.FIXED_NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _time_ago("2026-02-23T11:50:00+00:00")
        assert result == "10m ago"

    @patch("lib.status_collector.datetime")
    def test_hours_ago(self, mock_dt):
        mock_dt.now.return_value = self.FIXED_NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _time_ago("2026-02-23T09:00:00+00:00")
        assert result == "3h ago"

    @patch("lib.status_collector.datetime")
    def test_days_ago(self, mock_dt):
        mock_dt.now.return_value = self.FIXED_NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _time_ago("2026-02-20T12:00:00+00:00")
        assert result == "3d ago"

    def test_none_input(self):
        assert _time_ago(None) == "never"

    def test_none_string_input(self):
        assert _time_ago("None") == "never"

    def test_empty_string(self):
        assert _time_ago("") == "never"

    @patch("lib.status_collector.datetime")
    def test_future_timestamp(self, mock_dt):
        mock_dt.now.return_value = self.FIXED_NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _time_ago("2026-02-23T13:00:00+00:00")
        assert result == "just now"

    def test_invalid_iso_string(self):
        result = _time_ago("not-a-date")
        assert result == "not-a-date"

    @patch("lib.status_collector.datetime")
    def test_naive_timestamp_treated_as_utc(self, mock_dt):
        mock_dt.now.return_value = self.FIXED_NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _time_ago("2026-02-23T11:00:00")
        assert result == "1h ago"


# ── _categorize_commit ─────────────────────────────────────────────────

class TestCategorizeCommit:
    def test_fix_prefix(self):
        assert _categorize_commit("fix: broken import", []) == "fix"

    def test_fix_prefix_space(self):
        assert _categorize_commit("fix broken thing", []) == "fix"

    def test_qq_marker(self):
        assert _categorize_commit("resolve qq issue", []) == "fix"

    def test_cyrillic_yy_marker(self):
        assert _categorize_commit("resolve йй issue", []) == "fix"

    def test_reflection_prefix(self):
        assert _categorize_commit("reflection: nightly summary", []) == "learning"

    def test_mentor_scenario(self):
        assert _categorize_commit("add scenario for heartbeat", ["scenarios/heartbeat.md"]) == "learning"

    def test_claude_md_only(self):
        files = [".claude/CLAUDE.md"]
        assert _categorize_commit("update context", files) == "claude_md"

    def test_skills_files(self):
        files = [".claude/skills/heartbeat/SKILL.md"]
        assert _categorize_commit("improve heartbeat skill", files) == "skill"

    def test_claude_md_and_skills_prefers_skill(self):
        files = [".claude/CLAUDE.md", ".claude/skills/test/SKILL.md"]
        assert _categorize_commit("update things", files) == "skill"

    def test_feat_prefix(self):
        assert _categorize_commit("feat: new dashboard tab", []) == "capability"

    def test_add_prefix(self):
        assert _categorize_commit("add new endpoint", []) == "capability"

    def test_implement_keyword(self):
        assert _categorize_commit("implement webhook handler", []) == "capability"

    def test_default_infra(self):
        assert _categorize_commit("update config", ["gateway/config.yaml"]) == "infra"

    def test_fix_takes_precedence_over_skills(self):
        files = [".claude/skills/test/SKILL.md"]
        assert _categorize_commit("fix: skill import error", files) == "fix"


# ── _parse_diff_sections ──────────────────────────────────────────────

class TestParseDiffSections:
    def test_basic_diff(self):
        diff = """diff --git a/file.md b/file.md
index abc..def 100644
--- a/file.md
+++ b/file.md
@@ -1,5 +1,6 @@
+new line added
-old line removed"""
        sections, lines = _parse_diff_sections(diff)
        assert "+new line added" in lines
        assert "-old line removed" in lines

    def test_section_header_in_added_line(self):
        diff = """+## New Section
+some content"""
        sections, lines = _parse_diff_sections(diff)
        assert "New Section" in sections

    def test_section_header_in_removed_line(self):
        diff = """-## Old Section
-old content"""
        sections, lines = _parse_diff_sections(diff)
        assert "Old Section" in sections

    def test_hunk_header_with_section_context(self):
        diff = """@@ -10,5 +10,6 @@ ## Context Section
+new line"""
        sections, lines = _parse_diff_sections(diff)
        assert "Context Section" in sections

    def test_skips_diff_headers(self):
        diff = """diff --git a/f.md b/f.md
index abc..def 100644
--- a/f.md
+++ b/f.md
+actual change"""
        sections, lines = _parse_diff_sections(diff)
        assert len(lines) == 1
        assert lines[0] == "+actual change"

    def test_empty_diff(self):
        sections, lines = _parse_diff_sections("")
        assert sections == []
        assert lines == []


# ── _calculate_next_run ────────────────────────────────────────────────

class TestCalculateNextRun:
    def test_every_minutes(self):
        job = {"schedule": {"type": "every", "interval_minutes": 30}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert result == datetime(2026, 2, 23, 10, 30, 0, tzinfo=timezone.utc)

    def test_every_hours(self):
        job = {"schedule": {"type": "every", "interval_hours": 2}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert result == datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)

    def test_every_days(self):
        job = {"schedule": {"type": "every", "interval_days": 1}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert result == datetime(2026, 2, 24, 10, 0, 0, tzinfo=timezone.utc)

    def test_cron_returns_none(self):
        job = {"schedule": {"type": "cron", "cron": "0 5 * * *"}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        assert _calculate_next_run(job, from_time) is None

    def test_at_schedule(self):
        job = {"schedule": {"type": "at", "datetime": "2026-03-01T10:00:00+00:00"}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        result = _calculate_next_run(job, from_time)
        assert result is not None

    def test_unknown_schedule_returns_none(self):
        job = {"schedule": {"type": "unknown"}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        assert _calculate_next_run(job, from_time) is None

    def test_every_missing_interval_returns_none(self):
        job = {"schedule": {"type": "every"}}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        assert _calculate_next_run(job, from_time) is None

    def test_no_schedule_key(self):
        job = {}
        from_time = datetime(2026, 2, 23, 10, 0, 0, tzinfo=timezone.utc)
        assert _calculate_next_run(job, from_time) is None


# ── _fmt_seconds ───────────────────────────────────────────────────────

class TestFmtSeconds:
    def test_seconds_only(self):
        assert _fmt_seconds(45) == "45s"

    def test_zero(self):
        assert _fmt_seconds(0) == "0s"

    def test_exact_minute(self):
        assert _fmt_seconds(60) == "1m00s"

    def test_minutes_and_seconds(self):
        assert _fmt_seconds(90) == "1m30s"

    def test_exact_hour(self):
        assert _fmt_seconds(3600) == "1h00m"

    def test_hours_and_minutes(self):
        assert _fmt_seconds(3661) == "1h01m"

    def test_large_value(self):
        assert _fmt_seconds(7200) == "2h00m"


# ── _parse_deal_stage ──────────────────────────────────────────────────

class TestParseDealStage:
    def test_standard_format(self):
        num, name = _parse_deal_stage("5-proposal")
        assert num == 5
        assert name == "proposal"

    def test_number_only(self):
        num, name = _parse_deal_stage("7")
        assert num == 7
        assert name == "pilot"  # from _STAGE_NAMES

    def test_empty_string(self):
        num, name = _parse_deal_stage("")
        assert num == 0
        assert name == "unknown"

    def test_none_input(self):
        num, name = _parse_deal_stage(None)
        assert num == 0
        assert name == "unknown"

    def test_non_numeric_string(self):
        num, name = _parse_deal_stage("custom-stage")
        assert num == 0
        assert name == "custom-stage"

    def test_stalled_stage(self):
        num, name = _parse_deal_stage("16-stalled")
        assert num == 16
        assert name == "stalled"

    def test_lost_stage(self):
        num, name = _parse_deal_stage("17-lost")
        assert num == 17
        assert name == "lost"


# ── _parse_deal_value ──────────────────────────────────────────────────

class TestParseDealValue:
    def test_plain_number(self):
        assert _parse_deal_value("50000") == 50000.0

    def test_with_dollar_sign(self):
        assert _parse_deal_value("$10000") == 10000.0

    def test_with_commas(self):
        assert _parse_deal_value("1,000,000") == 1000000.0

    def test_dollar_and_commas(self):
        assert _parse_deal_value("$50,000") == 50000.0

    def test_none_input(self):
        assert _parse_deal_value(None) is None

    def test_non_numeric_string(self):
        assert _parse_deal_value("not-a-number") is None

    def test_float_value(self):
        assert _parse_deal_value("99.99") == 99.99

    def test_with_spaces(self):
        assert _parse_deal_value("  5000  ") == 5000.0


# ── _parse_deal_date ───────────────────────────────────────────────────

class TestParseDealDate:
    def test_valid_date(self):
        result = _parse_deal_date("2026-02-23")
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 23

    def test_none_input(self):
        assert _parse_deal_date(None) is None

    def test_empty_string(self):
        assert _parse_deal_date("") is None

    def test_invalid_format(self):
        assert _parse_deal_date("02/23/2026") is None

    def test_non_date_string(self):
        assert _parse_deal_date("tomorrow") is None

    def test_with_spaces(self):
        result = _parse_deal_date(" 2026-02-23 ")
        assert result is not None
        assert result.day == 23


# ── _clean_lead ────────────────────────────────────────────────────────

class TestCleanLead:
    def test_wikilink_format(self):
        assert _clean_lead("[[John Doe]]") == "John Doe"

    def test_single_brackets(self):
        assert _clean_lead("[John Doe]") == "John Doe"

    def test_plain_name(self):
        assert _clean_lead("John Doe") == "John Doe"

    def test_none_input(self):
        assert _clean_lead(None) == "Unknown"

    def test_empty_string(self):
        assert _clean_lead("") == "Unknown"

    def test_nested_brackets(self):
        result = _clean_lead("[[Jane]]")
        assert "Jane" in result
        assert "[" not in result


# ── _get_deal_weight ───────────────────────────────────────────────────

class TestGetDealWeight:
    def test_prospecting_stage(self):
        assert _get_deal_weight(1) == 0.10

    def test_outreach_stage(self):
        assert _get_deal_weight(2) == 0.10

    def test_meeting_stage(self):
        assert _get_deal_weight(3) == 0.10

    def test_qualified_stage(self):
        assert _get_deal_weight(4) == 0.25

    def test_negotiation_stage(self):
        assert _get_deal_weight(6) == 0.25

    def test_pilot_stage(self):
        assert _get_deal_weight(7) == 0.50

    def test_contract_stage(self):
        assert _get_deal_weight(9) == 0.50

    def test_procurement_stage(self):
        assert _get_deal_weight(10) == 0.75

    def test_signed_stage(self):
        assert _get_deal_weight(11) == 0.75

    def test_delivery_stage(self):
        assert _get_deal_weight(13) == 0.90

    def test_expansion_stage(self):
        assert _get_deal_weight(15) == 0.90

    def test_stalled_returns_zero(self):
        assert _get_deal_weight(16) == 0.0

    def test_lost_returns_zero(self):
        assert _get_deal_weight(17) == 0.0

    def test_zero_stage(self):
        assert _get_deal_weight(0) == 0.0

    def test_negative_stage(self):
        assert _get_deal_weight(-1) == 0.0
