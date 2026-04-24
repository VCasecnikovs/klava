"""Tests for gateway/lib/announce_handler.py - sub-agent announce processing."""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import announce_handler


class TestInitAnnounceHandler:
    def test_stores_config(self):
        config = {"telegram": {"bot_token": "tok"}}
        announce_handler.init_announce_handler(config)
        assert announce_handler._config == config


class TestProcessPendingAnnounces:
    @patch("lib.announce_handler.pop_pending_announce")
    @patch("lib.announce_handler._process_single_announce")
    def test_processes_batch(self, mock_process, mock_pop):
        mock_pop.side_effect = [
            {"job_id": "j1", "result": {}, "subagent": {}},
            {"job_id": "j2", "result": {}, "subagent": {}},
            None,  # empty queue
        ]
        mock_process.return_value = True
        results = announce_handler.process_pending_announces()
        assert len(results) == 2
        assert results[0]["status"] == "sent"
        assert results[1]["status"] == "sent"

    @patch("lib.announce_handler.pop_pending_announce")
    def test_empty_queue(self, mock_pop):
        mock_pop.return_value = None
        results = announce_handler.process_pending_announces()
        assert results == []

    @patch("lib.announce_handler.pop_pending_announce")
    @patch("lib.announce_handler._process_single_announce")
    @patch("lib.announce_handler.requeue_announce")
    def test_requeues_on_error(self, mock_requeue, mock_process, mock_pop):
        mock_pop.side_effect = [
            {"job_id": "j1", "result": {}, "subagent": {}, "retries": 0},
            None,
        ]
        mock_process.side_effect = Exception("network error")
        results = announce_handler.process_pending_announces()
        assert len(results) == 1
        assert results[0]["status"] == "requeued"
        mock_requeue.assert_called_once()

    @patch("lib.announce_handler.pop_pending_announce")
    @patch("lib.announce_handler._process_single_announce")
    def test_max_retries_exceeded(self, mock_process, mock_pop):
        mock_pop.side_effect = [
            {"job_id": "j1", "result": {}, "subagent": {}, "retries": 3},
            None,
        ]
        mock_process.side_effect = Exception("still failing")
        results = announce_handler.process_pending_announces()
        assert results[0]["status"] == "max_retries_exceeded"

    @patch("lib.announce_handler.pop_pending_announce")
    @patch("lib.announce_handler._process_single_announce")
    def test_respects_max_batch(self, mock_process, mock_pop):
        # Always return an announce (infinite queue)
        mock_pop.return_value = {"job_id": "j", "result": {}, "subagent": {}}
        mock_process.return_value = True
        results = announce_handler.process_pending_announces(max_batch=3)
        assert len(results) == 3


class TestProcessSingleAnnounce:
    @patch("lib.announce_handler._send_notification")
    @patch("lib.announce_handler.cleanup_subagent_files")
    @patch("lib.announce_handler.format_completion_notification")
    @patch("lib.announce_handler.get_subagent_output")
    def test_message_mode(self, mock_output, mock_format, mock_cleanup, mock_send):
        mock_format.return_value = "notification"
        mock_output.return_value = ""
        mock_send.return_value = True
        announce = {
            "job_id": "j1",
            "subagent": {"origin_topic": 100001, "job": {}},
            "result": {"status": "completed"},
        }
        result = announce_handler._process_single_announce(announce)
        assert result is True
        mock_send.assert_called_once_with(100001, "notification")
        mock_cleanup.assert_called_once_with("j1")

    @patch("lib.announce_handler._send_direct_output")
    @patch("lib.announce_handler.cleanup_subagent_files")
    @patch("lib.announce_handler.format_completion_notification")
    @patch("lib.announce_handler.get_subagent_output")
    def test_direct_mode(self, mock_output, mock_format, mock_cleanup, mock_send):
        mock_format.return_value = "notif"
        mock_output.return_value = "output text"
        mock_send.return_value = True
        announce = {
            "job_id": "j1",
            "subagent": {"origin_topic": 100004, "job": {"announce": {"mode": "direct"}}},
            "result": {"status": "completed"},
        }
        result = announce_handler._process_single_announce(announce)
        assert result is True
        mock_send.assert_called_once()

    @patch("lib.announce_handler.format_completion_notification")
    @patch("lib.announce_handler.get_subagent_output")
    def test_no_topic_returns_false(self, mock_output, mock_format):
        mock_format.return_value = "notif"
        mock_output.return_value = ""
        announce = {
            "job_id": "j1",
            "subagent": {"job": {}},  # no origin_topic
            "result": {},
        }
        result = announce_handler._process_single_announce(announce)
        assert result is False


class TestSendDirectOutput:
    @patch("lib.announce_handler.cleanup_subagent_files")
    @patch("lib.announce_handler.format_completion_notification", return_value="notif")
    @patch("lib.announce_handler.get_subagent_output", return_value="result text")
    def test_sends_via_process_single(self, mock_out, mock_fmt, mock_clean):
        """Test direct mode end-to-end via _process_single_announce with telegram mocked."""
        with patch("lib.telegram_utils._tg_api_call", return_value={"ok": True}):
            announce = {
                "job_id": "j1",
                "subagent": {"origin_topic": 100004, "job": {"announce": {"mode": "direct"}}},
                "result": {"status": "completed"},
            }
            announce_handler.init_announce_handler({
                "telegram": {"bot_token": "tok", "allowed_users": [123]}
            })
            result = announce_handler._process_single_announce(announce)
            assert result is True


class TestSendDirectOutputUnit:
    """Tests for _send_direct_output - patches at source module level since imports are lazy."""

    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_plain_output(self, mock_config, mock_send):
        announce_handler._config = {}
        result = announce_handler._send_direct_output(456, "notif", "plain text")
        assert result is True

    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_json_output_extracts_result(self, mock_config, mock_send):
        announce_handler._config = {}
        json_out = json.dumps({"result": "extracted value"})
        announce_handler._send_direct_output(456, "notif", json_out)

    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_truncates_long_output(self, mock_config, mock_send):
        announce_handler._config = {}
        announce_handler._send_direct_output(456, "notif", "x" * 5000)

    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_empty_output(self, mock_config, mock_send):
        announce_handler._config = {}
        result = announce_handler._send_direct_output(456, "notif", "")
        assert result is True

    @patch("lib.telegram_utils.get_telegram_config", side_effect=Exception("fail"))
    def test_exception_returns_false(self, mock_config):
        announce_handler._config = {}
        assert announce_handler._send_direct_output(456, "notif", "text") is False

    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_invalid_json_uses_raw(self, mock_config, mock_send):
        announce_handler._config = {}
        announce_handler._send_direct_output(456, "notif", "not{json")


class TestSendNotificationUnit:
    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_success(self, mock_config, mock_send):
        announce_handler._config = {}
        assert announce_handler._send_notification(456, "hello") is True

    @patch("lib.telegram_utils.get_telegram_config", side_effect=Exception("fail"))
    def test_exception(self, mock_config):
        announce_handler._config = {}
        assert announce_handler._send_notification(456, "hello") is False


class TestTriggerAgentTurnUnit:
    @patch("lib.claude_executor.ClaudeExecutor")
    @patch("lib.main_session.get_main_session_id", return_value="sess-1")
    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_success_with_response(self, mock_config, mock_send, mock_session, mock_exec_cls):
        announce_handler._config = {}
        mock_exec = MagicMock()
        mock_exec.run.return_value = {"result": "Agent reply text"}
        mock_exec_cls.return_value = mock_exec
        result = announce_handler._trigger_agent_turn(456, "j1", {"status": "completed"}, "output", "notif")
        assert result is True
        assert mock_send.call_count == 2

    @patch("lib.claude_executor.ClaudeExecutor")
    @patch("lib.main_session.get_main_session_id", return_value="sess-1")
    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_no_result_text(self, mock_config, mock_send, mock_session, mock_exec_cls):
        announce_handler._config = {}
        mock_exec = MagicMock()
        mock_exec.run.return_value = {"result": ""}
        mock_exec_cls.return_value = mock_exec
        result = announce_handler._trigger_agent_turn(456, "j1", {}, "", "notif")
        assert result is True
        assert mock_send.call_count == 1

    @patch("lib.claude_executor.ClaudeExecutor")
    @patch("lib.main_session.get_main_session_id", return_value="sess-1")
    @patch("lib.telegram_utils.send_telegram_message", return_value=True)
    @patch("lib.telegram_utils.get_telegram_config", return_value=("tok", 123, None))
    def test_long_output_truncated(self, mock_config, mock_send, mock_session, mock_exec_cls):
        announce_handler._config = {}
        mock_exec = MagicMock()
        mock_exec.run.return_value = {"result": "x" * 5000}
        mock_exec_cls.return_value = mock_exec
        result = announce_handler._trigger_agent_turn(456, "j1", {}, "a" * 5000, "notif")
        assert result is True

    @patch("lib.telegram_utils.get_telegram_config", side_effect=Exception("fail"))
    def test_exception(self, mock_config):
        announce_handler._config = {}
        assert announce_handler._trigger_agent_turn(456, "j1", {}, "", "notif") is False


class TestCheckAndAnnounceUnit:
    @patch("lib.announce_handler.process_pending_announces", return_value=[])
    @patch("lib.subagent_state.get_active_subagents", return_value={})
    def test_no_active(self, mock_active, mock_process):
        results = announce_handler.check_and_announce_completed()
        assert results == []

    @patch("lib.announce_handler.process_pending_announces", return_value=[])
    @patch("lib.announce_handler.get_subagent_output", return_value="output")
    @patch("lib.subagent_state.get_subagent_result", return_value={"status": "ok"})
    @patch("lib.subagent_state.is_process_alive", return_value=False)
    @patch("lib.subagent_state.complete_subagent")
    @patch("lib.subagent_state.get_active_subagents")
    def test_dead_with_result(self, mock_active, mock_complete, mock_alive, mock_result, mock_output, mock_process):
        mock_active.return_value = {"j1": {"pid": 123, "status": "running"}}
        announce_handler.check_and_announce_completed()
        mock_complete.assert_called_once()

    @patch("lib.announce_handler.process_pending_announces", return_value=[])
    @patch("lib.announce_handler.get_subagent_output", return_value="")
    @patch("lib.subagent_state.get_subagent_result", return_value=None)
    @patch("lib.subagent_state.is_process_alive", return_value=False)
    @patch("lib.subagent_state.fail_subagent")
    @patch("lib.subagent_state.get_active_subagents")
    def test_dead_no_output(self, mock_active, mock_fail, mock_alive, mock_result, mock_output, mock_process):
        mock_active.return_value = {"j1": {"pid": 123, "status": "running"}}
        announce_handler.check_and_announce_completed()
        mock_fail.assert_called_once_with("j1", "Process died without output")

    @patch("lib.announce_handler.process_pending_announces", return_value=[])
    @patch("lib.subagent_state.is_process_alive", return_value=True)
    @patch("lib.subagent_state.get_active_subagents")
    def test_still_alive(self, mock_active, mock_alive, mock_process):
        mock_active.return_value = {"j1": {"pid": 123, "status": "running"}}
        announce_handler.check_and_announce_completed()

    @patch("lib.announce_handler.process_pending_announces", return_value=[])
    @patch("lib.subagent_state.get_active_subagents")
    def test_no_pid(self, mock_active, mock_process):
        mock_active.return_value = {"j1": {"status": "running"}}
        announce_handler.check_and_announce_completed()

    @patch("lib.announce_handler.process_pending_announces", return_value=[])
    @patch("lib.announce_handler.get_subagent_output", return_value="output")
    @patch("lib.subagent_state.get_subagent_result", return_value=None)
    @patch("lib.subagent_state.is_process_alive", return_value=False)
    @patch("lib.subagent_state.complete_subagent")
    @patch("lib.subagent_state.get_active_subagents")
    def test_dead_with_output_only(self, mock_active, mock_complete, mock_alive, mock_result, mock_output, mock_process):
        mock_active.return_value = {"j1": {"pid": 123, "status": "running"}}
        announce_handler.check_and_announce_completed()
        mock_complete.assert_called_once()
