"""Tests for gateway/lib/claude_executor.py - option building and result parsing."""

import json
import os
import sys
import threading
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.claude_executor import ClaudeExecutor, MCP_CONFIG


class TestBuildOptions:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_default_options(self):
        from lib.claude_executor import DEFAULT_MODEL
        opts = self.executor._build_options()
        assert opts.model == DEFAULT_MODEL
        assert opts.allowed_tools == ["*"]

    def test_custom_model(self):
        opts = self.executor._build_options(model="opus")
        assert opts.model == "opus"

    def test_resume_mode(self):
        opts = self.executor._build_options(mode="main", session_id="sess-123")
        assert opts.resume == "sess-123"

    def test_isolated_mode_no_resume(self):
        opts = self.executor._build_options(mode="isolated", session_id="sess-123")
        assert not hasattr(opts, "resume") or opts.resume is None

    def test_skip_permissions(self):
        opts = self.executor._build_options(skip_permissions=True)
        assert opts.permission_mode == "bypassPermissions"

    def test_add_dirs(self):
        opts = self.executor._build_options(add_dirs=["~/Documents", "/tmp"])
        assert len(opts.add_dirs) == 2
        assert "/tmp" in opts.add_dirs

    def test_effort(self):
        opts = self.executor._build_options(effort="low")
        assert opts.effort == "low"

    def test_max_budget(self):
        opts = self.executor._build_options(max_budget_usd=5.0)
        assert opts.max_budget_usd == 5.0

    def test_allowed_tools(self):
        opts = self.executor._build_options(allowed_tools=["Bash", "Read"])
        assert opts.allowed_tools == ["Bash", "Read"]

    def test_betas(self):
        opts = self.executor._build_options(betas=["interleaved-thinking-2025-04-14"])
        assert opts.betas == ["interleaved-thinking-2025-04-14"]

    def test_none_model_defaults(self):
        from lib.claude_executor import DEFAULT_MODEL
        opts = self.executor._build_options(model=None)
        assert opts.model == DEFAULT_MODEL

    def test_max_buffer_size_default(self):
        # Regression: 2026-04-23 consumer crashed 4x/24h with
        # "JSON message exceeded maximum buffer size of 1048576 bytes" on an
        # opus blog post task. ClaudeAgentOptions.max_buffer_size defaults to
        # None in the SDK (-> 1 MiB), so the executor must raise it explicitly.
        opts = self.executor._build_options()
        assert opts.max_buffer_size is not None
        assert opts.max_buffer_size >= 8 * 1024 * 1024

    def test_max_buffer_size_env_override(self):
        from unittest.mock import patch as _patch
        with _patch.dict(os.environ, {"CLAUDE_SDK_MAX_BUFFER_SIZE": "4194304"}):
            opts = self.executor._build_options()
            assert opts.max_buffer_size == 4 * 1024 * 1024

    def test_max_buffer_size_env_garbage_falls_back(self):
        from unittest.mock import patch as _patch
        with _patch.dict(os.environ, {"CLAUDE_SDK_MAX_BUFFER_SIZE": "not-a-number"}):
            opts = self.executor._build_options()
            assert opts.max_buffer_size >= 8 * 1024 * 1024


class TestExecutorInit:
    def test_default_log(self):
        executor = ClaudeExecutor()
        assert executor.log is not None

    def test_custom_log(self):
        log_fn = MagicMock()
        executor = ClaudeExecutor(log_callback=log_fn)
        assert executor.log is log_fn


class TestRun:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_main_mode_requires_session_id(self):
        result = self.executor.run(prompt="test", mode="main")
        assert "error" in result
        assert "session_id required" in result["error"]

    @patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock)
    def test_run_returns_result(self, mock_streaming):
        mock_streaming.return_value = {
            "result": "Done",
            "session_id": "s1",
            "cost": 0.05,
            "duration": 10,
            "exit_code": 0,
        }
        result = self.executor.run(prompt="hello", model="haiku")
        assert result["result"] == "Done"
        assert result["cost"] == 0.05

    @patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock)
    def test_run_handles_exception(self, mock_streaming):
        mock_streaming.side_effect = RuntimeError("SDK crash")
        result = self.executor.run(prompt="hello")
        assert "error" in result
        assert "SDK crash" in result["error"]
        assert result["exit_code"] == -1

    @patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock)
    def test_run_main_mode_with_session(self, mock_streaming):
        mock_streaming.return_value = {"result": "OK", "session_id": "s1", "cost": 0, "duration": 0, "exit_code": 0}
        result = self.executor.run(prompt="hello", mode="main", session_id="s1")
        assert result["result"] == "OK"


class TestRunDetached:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_main_mode_requires_session_id(self):
        result = self.executor.run_detached(prompt="test", run_id="r1", mode="main")
        assert "error" in result

    @patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock)
    def test_launches_detached(self, mock_streaming, tmp_path):
        mock_streaming.return_value = {"result": "Done", "session_id": "s1", "cost": 0.01, "duration": 5, "exit_code": 0}
        result = self.executor.run_detached(
            prompt="hello", run_id="test-run",
            output_dir=str(tmp_path), timeout=10,
        )
        assert result["status"] == "launched"
        assert result["run_id"] == "test-run"
        # Wait for thread to complete
        holder = self.executor._detached_jobs.get("test-run")
        if holder:
            holder["done"].wait(timeout=5)

    @patch.object(ClaudeExecutor, "_run_streaming", new_callable=AsyncMock)
    def test_detached_writes_result_file(self, mock_streaming, tmp_path):
        mock_streaming.return_value = {"result": "OK", "session_id": "s1", "cost": 0, "duration": 1, "exit_code": 0}
        self.executor.run_detached(
            prompt="hello", run_id="r2",
            output_dir=str(tmp_path), timeout=10,
        )
        holder = self.executor._detached_jobs.get("r2")
        if holder:
            holder["done"].wait(timeout=5)
        result_file = tmp_path / "r2.result.json"
        assert result_file.exists()


class TestWaitForResult:
    def setup_method(self):
        self.executor = ClaudeExecutor(log_callback=lambda x: None)

    def test_waits_for_in_memory_result(self):
        holder = {"done": threading.Event(), "result": None}
        if not hasattr(self.executor, "_detached_jobs"):
            self.executor._detached_jobs = {}
        self.executor._detached_jobs["r1"] = holder

        def _set_result():
            time.sleep(0.1)
            holder["result"] = {"result": "done", "exit_code": 0, "cost": 0.1, "duration": 1, "session_id": "s1"}
            holder["done"].set()

        t = threading.Thread(target=_set_result)
        t.start()
        result = self.executor.wait_for_result("r1", timeout=5)
        t.join()
        assert result["result"] == "done"

    def test_timeout_returns_error(self):
        holder = {"done": threading.Event(), "result": None}
        if not hasattr(self.executor, "_detached_jobs"):
            self.executor._detached_jobs = {}
        self.executor._detached_jobs["r2"] = holder
        with patch.object(ClaudeExecutor, "_kill_orphaned_children"):
            result = self.executor.wait_for_result("r2", timeout=0.1)
        assert "error" in result
        assert "Timeout" in result["error"]

    def test_file_based_fallback(self, tmp_path):
        # No in-memory holder, uses file polling
        result_file = tmp_path / "r3.result.json"
        out_file = tmp_path / "r3.out"
        out_file.write_text("Output text")
        result_file.write_text(json.dumps({"exit_code": 0}))
        result = self.executor.wait_for_result("r3", timeout=5, output_dir=str(tmp_path), poll_interval=0.1)
        assert result["result"] == "Output text"
        assert result["exit_code"] == 0

    def test_file_based_timeout(self, tmp_path):
        result = self.executor.wait_for_result("r4", timeout=0.2, output_dir=str(tmp_path), poll_interval=0.1)
        assert "error" in result
        assert "Timeout" in result["error"]


class TestReadDetachedResult:
    def test_no_file(self, tmp_path):
        result = ClaudeExecutor.read_detached_result("r1", output_dir=str(tmp_path))
        assert result is None

    def test_reads_result(self, tmp_path):
        (tmp_path / "r2.result.json").write_text(json.dumps({"exit_code": 0, "completed_at": "2026-03-16"}))
        result = ClaudeExecutor.read_detached_result("r2", output_dir=str(tmp_path))
        assert result["exit_code"] == 0

    def test_corrupt_json(self, tmp_path):
        (tmp_path / "r3.result.json").write_text("not json")
        result = ClaudeExecutor.read_detached_result("r3", output_dir=str(tmp_path))
        assert result == {"exit_code": -1}


class TestKillOrphanedChildren:
    @patch("subprocess.run")
    def test_kills_sdk_children(self, mock_run):
        # pgrep returns child PIDs
        mock_run.side_effect = [
            MagicMock(stdout="12345\n"),  # pgrep
            MagicMock(stdout="claude_agent_sdk/_bundled/claude --model"),  # ps
        ]
        log = MagicMock()
        with patch("os.getpgid", side_effect=[100, 200]), \
             patch("os.killpg") as mock_killpg:
            ClaudeExecutor._kill_orphaned_children(999, "run1", log)
            mock_killpg.assert_called_once()

    @patch("subprocess.run")
    def test_no_children(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        log = MagicMock()
        ClaudeExecutor._kill_orphaned_children(999, "run1", log)
        # Should not raise

    @patch("subprocess.run")
    def test_same_process_group(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="12345\n"),
            MagicMock(stdout="claude_agent_sdk/_bundled/claude"),
        ]
        with patch("os.getpgid", return_value=100), \
             patch("os.kill") as mock_kill:
            ClaudeExecutor._kill_orphaned_children(999, "run1")
            mock_kill.assert_called_once()
