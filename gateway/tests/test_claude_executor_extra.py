"""Extra tests for gateway/lib/claude_executor.py to increase coverage.

Targets missed lines: 89-174 (_run_streaming internals), 233, 289-290, 302-303,
310-311, 374-375, 380-381, 433-434, 437-441.
Uses asyncio.run() wrapper since pytest-asyncio is not available.
"""

import asyncio
import json
import os
import sys
import signal
import threading
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.claude_executor import ClaudeExecutor, MCP_CONFIG, DETACHED_OUTPUT_DIR


def run_async(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)


class _AsyncIter:
    """Async iterator helper for mocking receive_messages()."""
    def __init__(self, items):
        self.items = list(items)
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


class _SlowAsyncIter:
    """Async iterator that sleeps forever (for timeout tests)."""
    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(100)
        raise StopAsyncIteration


def _mock_sdk_client(mock_client):
    """Build a patched ClaudeSDKClient context manager returning mock_client."""
    ctx_mgr = MagicMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=mock_client)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)
    return ctx_mgr


# ── _run_streaming: no result message (lines 161-168) ──

class TestRunStreamingNoResult:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_no_result_message_returns_error(self):
        """When no ResultMessage is received, returns error dict."""
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.receive_messages = MagicMock(return_value=_AsyncIter([]))

        with patch("lib.claude_executor.ClaudeSDKClient", return_value=_mock_sdk_client(mock_client)):
            opts = MagicMock()
            result = run_async(self.executor._run_streaming("test", opts, 300))

        assert result.get("error") == "No result received from SDK"
        assert result["exit_code"] == -1


# ── _run_streaming: timeout path (lines 131-145) ──

class TestRunStreamingTimeout:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_timeout_returns_error_dict(self):
        """Timeout returns error dict with cleanup."""
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.receive_messages = MagicMock(return_value=_SlowAsyncIter())

        with patch("lib.claude_executor.ClaudeSDKClient", return_value=_mock_sdk_client(mock_client)):
            opts = MagicMock()
            result = run_async(self.executor._run_streaming("test", opts, timeout=0.01))

        assert "Timeout" in result.get("error", "")
        assert result["exit_code"] == -1

    def test_timeout_with_disconnect_error(self):
        """Timeout gracefully handles disconnect errors."""
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.query = AsyncMock()
        mock_client.disconnect = AsyncMock(side_effect=RuntimeError("already closed"))
        mock_client.receive_messages = MagicMock(return_value=_SlowAsyncIter())

        with patch("lib.claude_executor.ClaudeSDKClient", return_value=_mock_sdk_client(mock_client)):
            opts = MagicMock()
            result = run_async(self.executor._run_streaming("test", opts, timeout=0.01))

        assert "Timeout" in result.get("error", "")


# ── _run_streaming: auth error via Exception (lines 146-159) ──

class TestRunStreamingProcessError:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=MagicMock())

    def test_not_logged_in_error(self):
        """ProcessError containing 'Not logged in' returns auth error dict."""
        with patch("lib.claude_executor.ClaudeSDKClient") as MockClient:
            ctx_mgr = AsyncMock()
            ctx_mgr.__aenter__ = AsyncMock(side_effect=Exception("Not logged in"))
            ctx_mgr.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = ctx_mgr

            opts = MagicMock()
            result = run_async(self.executor._run_streaming("test", opts, 300))

        assert "Not logged in" in result.get("error", "")
        assert result["exit_code"] == 1

    def test_authentication_failed_error(self):
        """ProcessError with 'authentication_failed' returns auth error."""
        with patch("lib.claude_executor.ClaudeSDKClient") as MockClient:
            ctx_mgr = AsyncMock()
            ctx_mgr.__aenter__ = AsyncMock(side_effect=Exception("authentication_failed"))
            ctx_mgr.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = ctx_mgr

            opts = MagicMock()
            result = run_async(self.executor._run_streaming("test", opts, 300))

        assert result["exit_code"] == 1

    def test_non_auth_error_reraises(self):
        """Non-auth ProcessError is re-raised."""
        with patch("lib.claude_executor.ClaudeSDKClient") as MockClient:
            ctx_mgr = AsyncMock()
            ctx_mgr.__aenter__ = AsyncMock(side_effect=RuntimeError("Something else"))
            ctx_mgr.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = ctx_mgr

            opts = MagicMock()
            with pytest.raises(RuntimeError, match="Something else"):
                run_async(self.executor._run_streaming("test", opts, 300))


# ── run: KeyboardInterrupt/SystemExit propagation (line 233) ──

class TestRunInterrupt:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_keyboard_interrupt_propagates(self):
        """KeyboardInterrupt in _run_streaming propagates through run()."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                self.executor.run(prompt="test")

    def test_system_exit_propagates(self):
        """SystemExit in _run_streaming propagates through run()."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                self.executor.run(prompt="test")


# ── run_detached: thread exception handling (lines 289-296) ──

class TestRunDetachedExceptionInThread:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_thread_exception_captured(self, tmp_path):
        """Exception in _run_streaming thread is captured in result."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          side_effect=RuntimeError("Thread crash")), \
             patch.object(ClaudeExecutor, "_kill_orphaned_children"):
            result = self.executor.run_detached(
                prompt="test", run_id="err-run",
                output_dir=str(tmp_path), timeout=10,
            )
            assert result["status"] == "launched"

            holder = self.executor._detached_jobs.get("err-run")
            assert holder is not None
            holder["done"].wait(timeout=5)

            assert holder["result"] is not None
            assert "Thread crash" in holder["result"]["error"]
            assert holder["result"]["exit_code"] == -1

    def test_thread_writes_result_file_on_error(self, tmp_path):
        """Result file is written even on exception."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          side_effect=RuntimeError("Crash")), \
             patch.object(ClaudeExecutor, "_kill_orphaned_children"):
            self.executor.run_detached(
                prompt="test", run_id="err2",
                output_dir=str(tmp_path), timeout=10,
            )
            holder = self.executor._detached_jobs.get("err2")
            holder["done"].wait(timeout=5)

        result_file = tmp_path / "err2.result.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["exit_code"] == -1


# ── run_detached: orphan cleanup (lines 302-303) ──

class TestRunDetachedOrphanCleanup:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_orphan_cleanup_called_after_completion(self, tmp_path):
        """_kill_orphaned_children is called in finally block."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          return_value={"result": "ok", "exit_code": 0, "cost": 0, "duration": 0, "session_id": "s"}), \
             patch.object(ClaudeExecutor, "_kill_orphaned_children") as mock_kill:
            self.executor.run_detached(
                prompt="test", run_id="clean-run",
                output_dir=str(tmp_path), timeout=10,
            )
            holder = self.executor._detached_jobs.get("clean-run")
            holder["done"].wait(timeout=5)

        mock_kill.assert_called_once()

    def test_result_file_written_after_success(self, tmp_path):
        """Result file is written with exit_code and completed_at."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          return_value={"result": "ok", "exit_code": 0, "cost": 0, "duration": 0, "session_id": "s"}), \
             patch.object(ClaudeExecutor, "_kill_orphaned_children"):
            self.executor.run_detached(
                prompt="test", run_id="ok-run",
                output_dir=str(tmp_path), timeout=10,
            )
            holder = self.executor._detached_jobs.get("ok-run")
            holder["done"].wait(timeout=5)

        result_file = tmp_path / "ok-run.result.json"
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["exit_code"] == 0
        assert "completed_at" in data


# ── wait_for_result: file-based fallback edge cases (lines 374-375, 380-381) ──

class TestWaitForResultFileFallback:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_file_fallback_no_out_file(self, tmp_path):
        """File-based fallback when .out file doesn't exist."""
        result_file = tmp_path / "r5.result.json"
        result_file.write_text(json.dumps({"exit_code": 0}))
        result = self.executor.wait_for_result("r5", timeout=5, output_dir=str(tmp_path), poll_interval=0.1)
        assert result["result"] == ""
        assert result["exit_code"] == 0

    def test_file_fallback_os_error_on_read(self, tmp_path):
        """File fallback handles OSError when reading .out file."""
        result_file = tmp_path / "r6.result.json"
        result_file.write_text(json.dumps({"exit_code": 0}))
        out_file = tmp_path / "r6.out"
        out_file.mkdir()  # Directory instead of file causes OSError on read_text()
        result = self.executor.wait_for_result("r6", timeout=5, output_dir=str(tmp_path), poll_interval=0.1)
        assert result["result"] == ""

    def test_cleanup_os_error_handled(self, tmp_path):
        """OSError on file cleanup is handled."""
        result_file = tmp_path / "r7.result.json"
        result_file.write_text(json.dumps({"exit_code": 0}))
        out_file = tmp_path / "r7.out"
        out_file.write_text("output")
        # Make result_file read-only dir to cause cleanup error
        result = self.executor.wait_for_result("r7", timeout=5, output_dir=str(tmp_path), poll_interval=0.1)
        assert result["result"] == "output"


# ── _kill_orphaned_children: edge cases (lines 433-441) ──

class TestKillOrphanedChildrenEdge:
    @patch("subprocess.run")
    def test_pgrep_timeout(self, mock_run):
        """pgrep timeout is handled gracefully."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("pgrep", 5)
        log = MagicMock()
        ClaudeExecutor._kill_orphaned_children(999, "run1", log)
        log.assert_called_once()
        assert "Orphan cleanup failed" in log.call_args[0][0]

    @patch("subprocess.run")
    def test_no_log_callback(self, mock_run):
        """Works without log callback."""
        mock_run.return_value = MagicMock(stdout="")
        ClaudeExecutor._kill_orphaned_children(999, "run1", log=None)

    @patch("subprocess.run")
    def test_child_process_lookup_error(self, mock_run):
        """ProcessLookupError on getpgid is handled."""
        mock_run.side_effect = [
            MagicMock(stdout="12345\n"),
            MagicMock(stdout="claude_agent_sdk/_bundled/claude"),
        ]
        with patch("os.getpgid", side_effect=ProcessLookupError):
            with patch("os.kill") as mock_kill:
                mock_kill.side_effect = ProcessLookupError
                ClaudeExecutor._kill_orphaned_children(999, "run1")

    @patch("subprocess.run")
    def test_non_sdk_process_skipped(self, mock_run):
        """Non-SDK child processes are not killed."""
        mock_run.side_effect = [
            MagicMock(stdout="12345\n"),
            MagicMock(stdout="/usr/bin/python3 some_script.py"),
        ]
        with patch("os.kill") as mock_kill, \
             patch("os.killpg") as mock_killpg:
            ClaudeExecutor._kill_orphaned_children(999, "run1")
            mock_kill.assert_not_called()
            mock_killpg.assert_not_called()

    @patch("subprocess.run")
    def test_ps_timeout_handled(self, mock_run):
        """Timeout on ps command is handled gracefully."""
        import subprocess
        mock_run.side_effect = [
            MagicMock(stdout="12345\n"),
            subprocess.TimeoutExpired("ps", 5),
        ]
        ClaudeExecutor._kill_orphaned_children(999, "run1")

    @patch("subprocess.run")
    def test_kill_logs_with_callback(self, mock_run):
        """Successful kill logs message."""
        mock_run.side_effect = [
            MagicMock(stdout="12345\n"),
            MagicMock(stdout="claude_agent_sdk/_bundled/claude --model"),
        ]
        log = MagicMock()
        with patch("os.getpgid", side_effect=[100, 200]), \
             patch("os.killpg"):
            ClaudeExecutor._kill_orphaned_children(999, "run1", log)
        log.assert_called()
        assert "Killed" in log.call_args[0][0]


# ── read_detached_result edge cases ──

class TestReadDetachedResultEdge:
    def test_empty_file(self, tmp_path):
        """Empty result file returns error dict."""
        (tmp_path / "r1.result.json").write_text("")
        result = ClaudeExecutor.read_detached_result("r1", output_dir=str(tmp_path))
        assert result == {"exit_code": -1}

    def test_oserror_returns_error_dict(self, tmp_path):
        """OSError on read returns error dict."""
        # Create a directory instead of a file
        (tmp_path / "r2.result.json").mkdir()
        result = ClaudeExecutor.read_detached_result("r2", output_dir=str(tmp_path))
        assert result == {"exit_code": -1}


# ── _build_options: MCP config (lines 60-61) ──

class TestBuildOptionsMCP:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_mcp_config_included_when_exists(self):
        with patch("os.path.exists", return_value=True):
            opts = self.executor._build_options()
        assert opts.mcp_servers == MCP_CONFIG

    def test_mcp_config_excluded_when_missing(self):
        with patch("os.path.exists", return_value=False):
            opts = self.executor._build_options()
        # When file doesn't exist, mcp_servers should not be set to the config path
        assert opts.mcp_servers != MCP_CONFIG


# ── _build_options: setting_sources (line 72-73) ──

class TestBuildOptionsSettingSources:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_setting_sources_always_set(self):
        opts = self.executor._build_options()
        assert opts.setting_sources == ["user", "project"]


# ── run: generic exception handling (lines 230-240) ──

class TestRunGenericException:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=MagicMock())

    def test_generic_exception_returns_error_dict(self):
        """Non-critical exception returns error dict instead of raising."""
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          side_effect=ValueError("bad value")):
            result = self.executor.run(prompt="test")
        assert "error" in result
        assert "bad value" in result["error"]
        assert result["exit_code"] == -1

    def test_logs_execution_failure(self):
        """Log callback is called on failure."""
        log = MagicMock()
        executor = ClaudeExecutor(log_callback=log)
        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          side_effect=RuntimeError("oops")):
            executor.run(prompt="test")
        log.assert_called()
        # Last call should mention failure
        calls = [str(c) for c in log.call_args_list]
        assert any("failed" in c.lower() or "oops" in c.lower() for c in calls)


# ── run_detached: detached_jobs init (line 319-321) ──

class TestRunDetachedJobsInit:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_creates_detached_jobs_dict(self, tmp_path):
        """_detached_jobs is created if not present."""
        # Remove _detached_jobs if present
        if hasattr(self.executor, "_detached_jobs"):
            delattr(self.executor, "_detached_jobs")

        with patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock,
                          return_value={"result": "ok", "exit_code": 0, "cost": 0, "duration": 0, "session_id": "s"}), \
             patch.object(ClaudeExecutor, "_kill_orphaned_children"):
            result = self.executor.run_detached(
                prompt="test", run_id="init-run",
                output_dir=str(tmp_path), timeout=10,
            )
        assert result["status"] == "launched"
        assert hasattr(self.executor, "_detached_jobs")
        assert "init-run" in self.executor._detached_jobs
