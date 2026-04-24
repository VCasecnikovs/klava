"""Tests for gateway/lib/subagent_status.py - formatting functions."""

import pytest
from datetime import datetime
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.subagent_status import (
    format_duration,
    format_spawn_notification,
    parse_current_activity,
    format_progress_message,
    format_completion_notification,
    format_active_subagents_status,
    format_pending_announces_status,
    get_subagent_status_section,
)


class TestFormatDuration:
    def test_seconds(self):
        assert format_duration(5) == "5s"
        assert format_duration(59) == "59s"

    def test_minutes(self):
        assert format_duration(60) == "1m 0s"
        assert format_duration(90) == "1m 30s"
        assert format_duration(3599) == "59m 59s"

    def test_hours(self):
        assert format_duration(3600) == "1h 0m"
        assert format_duration(3660) == "1h 1m"
        assert format_duration(7200) == "2h 0m"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_fractional(self):
        assert format_duration(1.7) == "1s"


class TestFormatSpawnNotification:
    def test_basic(self):
        job = {"name": "Research task", "execution": {"model": "opus", "timeout_seconds": 600}}
        result = format_spawn_notification("job-123", job)
        assert "Research task" in result
        assert "opus" in result
        assert "10 min" in result
        assert "job-123" in result

    def test_defaults(self):
        result = format_spawn_notification("j1", {})
        assert "Sub-agent" in result
        assert "sonnet" in result


class TestParseCurrentActivity:
    def test_empty_output(self):
        assert parse_current_activity("") == "Working..."
        assert parse_current_activity(None) == "Working..."

    def test_spinner_detection(self):
        output = "some text\n⠋ Reading file.py\nmore"
        result = parse_current_activity(output)
        assert "Reading file.py" in result

    def test_tool_emoji_detection(self):
        output = "blah\n📂 Searching codebase\n"
        result = parse_current_activity(output)
        assert "Searching codebase" in result

    def test_no_indicators(self):
        output = "plain text\nno special markers\n"
        assert parse_current_activity(output) == "Working..."

    def test_truncates_long_lines(self):
        output = "⠋ " + "A" * 100
        result = parse_current_activity(output)
        assert len(result) <= 50


class TestFormatProgressMessage:
    def test_basic(self):
        job = {"name": "My Task", "execution": {"model": "haiku", "timeout_seconds": 300}}
        result = format_progress_message("j1", job, "2m 30s", "Reading files")
        assert "My Task" in result
        assert "haiku" in result
        assert "2m 30s" in result
        assert "Reading files" in result


class TestFormatCompletionNotification:
    def test_success(self):
        result_data = {"status": "completed", "tokens": 5000, "cost_usd": 0.012}
        subagent = {
            "job": {"name": "Research"},
            "started_at": "2026-03-16T01:00:00",
            "completed_at": "2026-03-16T01:05:00",
        }
        result = format_completion_notification("j1", result_data, subagent)
        assert "✅" in result
        assert "Research" in result
        assert "5000" in result
        assert "$0.012" in result
        assert "completed" in result

    def test_failure(self):
        result_data = {"status": "failed", "error": "timeout exceeded"}
        subagent = {"job": {"name": "Build"}}
        result = format_completion_notification("j1", result_data, subagent)
        assert "❌" in result
        assert "timeout exceeded" in result

    def test_no_subagent(self):
        result_data = {"status": "completed"}
        result = format_completion_notification("j1", result_data)
        assert "Sub-agent" in result
        assert "N/A" in result

    def test_duration_calculation(self):
        result_data = {"status": "completed"}
        subagent = {
            "job": {"name": "Test"},
            "started_at": "2026-03-16T01:00:00",
            "completed_at": "2026-03-16T01:02:30",
        }
        result = format_completion_notification("j1", result_data, subagent)
        assert "2m 30s" in result

    def test_error_truncated(self):
        result_data = {"status": "failed", "error": "x" * 500}
        subagent = {"job": {"name": "Task"}}
        result = format_completion_notification("j1", result_data, subagent)
        # Error should be truncated to 200 chars
        assert len(result) < 800

    def test_invalid_timestamps_fallback(self):
        """Line 129-130: invalid timestamps should not crash, duration stays N/A."""
        result_data = {"status": "completed"}
        subagent = {
            "job": {"name": "Task"},
            "started_at": "not-a-date",
            "completed_at": "also-not-a-date",
        }
        result = format_completion_notification("j1", result_data, subagent)
        assert "N/A" in result
        assert "Task" in result

    def test_completed_at_none_uses_now(self):
        """When completed_at is None, datetime.now() is used."""
        result_data = {"status": "completed"}
        subagent = {
            "job": {"name": "Task"},
            "started_at": "2026-03-16T01:00:00",
            "completed_at": None,
        }
        result = format_completion_notification("j1", result_data, subagent)
        # Should calculate some duration (not N/A) since started_at is valid
        assert "Task" in result

    def test_no_tokens_no_cost(self):
        """When neither tokens nor cost present, last line uses └──."""
        result_data = {"status": "completed"}
        subagent = {"job": {"name": "Simple"}}
        result = format_completion_notification("j1", result_data, subagent)
        # No tokens line, no cost line - last line should have └──
        assert "└──" in result
        # tokens N/A means no tokens line appended
        assert "Tokens" not in result

    def test_tokens_present_no_cost(self):
        """Tokens present but no cost - tokens line added, cost replaced with └──."""
        result_data = {"status": "completed", "tokens": 1234}
        subagent = {"job": {"name": "T"}}
        result = format_completion_notification("j1", result_data, subagent)
        assert "1234" in result
        # Cost is N/A, so last ├── should become └──
        assert "└──" in result

    def test_cost_from_cost_key(self):
        """cost key (not cost_usd) should also work."""
        result_data = {"status": "completed", "cost": 0.5}
        subagent = {"job": {"name": "T"}}
        result = format_completion_notification("j1", result_data, subagent)
        assert "$0.500" in result


class TestParseCurrentActivityEdgeCases:
    def test_empty_lines_skipped(self):
        """Line 65: empty lines after last content should be skipped in reverse scan."""
        # After strip+split, reversed order: "plain text", "", "", "📂 Found it"
        # The empty lines in between must be skipped via continue (line 65)
        output = "📂 Found it\n\n\nplain text"
        result = parse_current_activity(output)
        # "plain text" has no indicator, "" empty lines hit continue, then "📂 Found it" matches
        assert "Found it" in result

    def test_spinner_with_empty_clean(self):
        """Spinner char alone (clean is empty) should not be returned."""
        output = "⠋\nplain text"
        result = parse_current_activity(output)
        # Spinner alone has empty clean, so falls through to "Working..."
        assert result == "Working..."

    def test_spinner_alone_then_emoji(self):
        """Spinner with empty text, but earlier line has tool emoji."""
        output = "📂 Earlier search\n⠋  "
        result = parse_current_activity(output)
        # Spinner line: clean is empty after strip -> skip
        # Then emoji line: should match
        assert "Earlier search" in result


@patch("lib.subagent_status.get_active_subagents")
class TestFormatActiveSubagentsStatus:
    def test_no_active_returns_none(self, mock_active):
        """Line 167-168: empty dict returns None."""
        mock_active.return_value = {}
        assert format_active_subagents_status() is None

    def test_single_running_agent(self, mock_active):
        """Lines 170-196: single running agent formatted correctly."""
        mock_active.return_value = {
            "job-1": {
                "job": {"name": "Research task"},
                "status": "running",
                "started_at": datetime.now().isoformat(),
            }
        }
        result = format_active_subagents_status()
        assert result is not None
        assert "Active Sub-agents" in result
        assert "Research task" in result
        assert "🔄" in result

    def test_pending_retry_status(self, mock_active):
        """Line 191-192: pending_retry gets 🔁 emoji."""
        mock_active.return_value = {
            "job-1": {
                "job": {"name": "Retry task"},
                "status": "pending_retry",
                "started_at": "2026-03-16T01:00:00",
            }
        }
        result = format_active_subagents_status()
        assert "🔁" in result
        assert "Retry task" in result

    def test_unknown_status_gets_hourglass(self, mock_active):
        """Line 193-194: unknown status gets ⏳ emoji."""
        mock_active.return_value = {
            "job-1": {
                "job": {"name": "Waiting"},
                "status": "queued",
                "started_at": "2026-03-16T01:00:00",
            }
        }
        result = format_active_subagents_status()
        assert "⏳" in result

    def test_no_started_at_shows_question_mark(self, mock_active):
        """Lines 180-181: missing started_at shows '?'."""
        mock_active.return_value = {
            "job-1": {
                "job": {"name": "No time"},
                "status": "running",
            }
        }
        result = format_active_subagents_status()
        assert "(?" in result or "?)" in result

    def test_invalid_started_at_shows_question_mark(self, mock_active):
        """Lines 185-186: invalid timestamp stays '?'."""
        mock_active.return_value = {
            "job-1": {
                "job": {"name": "Bad time"},
                "status": "running",
                "started_at": "not-a-datetime",
            }
        }
        result = format_active_subagents_status()
        assert "?" in result

    def test_more_than_five_agents_truncated(self, mock_active):
        """Lines 199-202: more than 5 agents shows '... and N more'."""
        agents = {}
        for i in range(8):
            agents[f"job-{i}"] = {
                "job": {"name": f"Task {i}"},
                "status": "running",
                "started_at": "2026-03-16T01:00:00",
            }
        mock_active.return_value = agents
        result = format_active_subagents_status()
        assert "... and" in result
        assert "more" in result

    def test_defaults_for_missing_job_fields(self, mock_active):
        """Default name 'Sub-agent' when job dict is missing."""
        mock_active.return_value = {
            "job-1": {
                "status": "running",
                "started_at": "2026-03-16T01:00:00",
            }
        }
        result = format_active_subagents_status()
        assert "Sub-agent" in result


@patch("lib.subagent_status.get_pending_announces")
class TestFormatPendingAnnouncesStatus:
    def test_no_pending_returns_none(self, mock_pending):
        """Line 215-216: empty list returns None."""
        mock_pending.return_value = []
        assert format_pending_announces_status() is None

    def test_single_completed_announce(self, mock_pending):
        """Lines 218-229: single completed pending announce."""
        mock_pending.return_value = [
            {
                "job_id": "abcdef123456789",
                "result": {"status": "completed"},
                "retries": 0,
            }
        ]
        result = format_pending_announces_status()
        assert result is not None
        assert "Pending Announces" in result
        assert "✅" in result
        assert "abcdef123456" in result  # truncated to 12 chars
        assert "completed" in result

    def test_failed_announce_with_retries(self, mock_pending):
        """Lines 226-228: failed status with retries shown."""
        mock_pending.return_value = [
            {
                "job_id": "failedjob123456",
                "result": {"status": "failed"},
                "retries": 3,
            }
        ]
        result = format_pending_announces_status()
        assert "❌" in result
        assert "retry #3" in result

    def test_more_than_three_shows_remainder(self, mock_pending):
        """Lines 231-232: more than 3 pending shows '... and N more'."""
        items = []
        for i in range(6):
            items.append({
                "job_id": f"job-{i}-padding-long",
                "result": {"status": "completed"},
                "retries": 0,
            })
        mock_pending.return_value = items
        result = format_pending_announces_status()
        assert "... and 3 more" in result

    def test_zero_retries_no_retry_string(self, mock_pending):
        """retries=0 should not show retry string."""
        mock_pending.return_value = [
            {
                "job_id": "job-abc-123456",
                "result": {"status": "completed"},
                "retries": 0,
            }
        ]
        result = format_pending_announces_status()
        assert "retry" not in result

    def test_defaults_for_missing_fields(self, mock_pending):
        """Missing fields use defaults."""
        mock_pending.return_value = [{}]
        result = format_pending_announces_status()
        assert "unknown" in result  # job_id defaults to "unknown"
        assert "?" in result  # status defaults to "?"


@patch("lib.subagent_status.format_pending_announces_status")
@patch("lib.subagent_status.format_active_subagents_status")
class TestGetSubagentStatusSection:
    def test_nothing_active_returns_none(self, mock_active, mock_pending):
        """Lines 253-254: no active, no pending -> None."""
        mock_active.return_value = None
        mock_pending.return_value = None
        assert get_subagent_status_section() is None

    def test_only_active(self, mock_active, mock_pending):
        """Lines 246-247: only active agents, no pending."""
        mock_active.return_value = "🤖 <b>Active Sub-agents:</b>\n  🔄 Task (5s)"
        mock_pending.return_value = None
        result = get_subagent_status_section()
        assert result is not None
        assert "Active Sub-agents" in result

    def test_only_pending(self, mock_active, mock_pending):
        """Lines 249-250: only pending announces, no active."""
        mock_active.return_value = None
        mock_pending.return_value = "📢 <b>Pending Announces:</b>\n  ✅ abc... completed"
        result = get_subagent_status_section()
        assert result is not None
        assert "Pending Announces" in result

    def test_both_active_and_pending(self, mock_active, mock_pending):
        """Lines 246-256: both parts present, joined with double newline."""
        mock_active.return_value = "active section"
        mock_pending.return_value = "pending section"
        result = get_subagent_status_section()
        assert "active section" in result
        assert "pending section" in result
        assert "\n\n" in result
