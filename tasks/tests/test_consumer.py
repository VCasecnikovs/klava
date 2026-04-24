"""Tests for tasks/consumer.py - consumer logic, stale detection, task execution."""

import os
import fcntl
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

from tasks.consumer import (
    is_stale, build_task_prompt, check_and_execute,
    consumer_lock, _find_source_duplicate, _pick_next_task,
)
from tasks.queue import Task


@pytest.fixture(autouse=True)
def _isolated_consumer_lock(tmp_path, monkeypatch):
    """Point CONSUMER_LOCK_PATH at a per-test file so tests never collide
    with the real cron consumer's `/tmp/klava-consumer.lock` — which, given
    this module is exactly the thing preventing parallel consumers, is
    guaranteed to be held whenever CI runs while the cron fires.
    """
    import tasks.consumer as consumer_mod
    monkeypatch.setattr(
        consumer_mod, "CONSUMER_LOCK_PATH", tmp_path / "consumer.lock",
    )


class TestIsStale:
    def test_not_stale(self):
        now = datetime.now(timezone.utc)
        task = Task(
            id="1", title="Test", status="running",
            started_at=now.isoformat(),
        )
        assert is_stale(task, timeout_minutes=30) is False

    def test_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        task = Task(
            id="1", title="Test", status="running",
            started_at=old,
        )
        assert is_stale(task, timeout_minutes=30) is True

    def test_exactly_at_boundary(self):
        boundary = (datetime.now(timezone.utc) - timedelta(minutes=30, seconds=1)).isoformat()
        task = Task(id="1", title="Test", status="running", started_at=boundary)
        assert is_stale(task, timeout_minutes=30) is True

    def test_no_started_at(self):
        task = Task(id="1", title="Test", status="running")
        assert is_stale(task, timeout_minutes=30) is True

    def test_invalid_timestamp(self):
        task = Task(id="1", title="Test", status="running", started_at="not-a-date")
        assert is_stale(task, timeout_minutes=30) is True

    def test_naive_timestamp_treated_as_utc(self):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5))
        # Strip timezone info to simulate naive timestamp
        naive_str = recent.strftime("%Y-%m-%dT%H:%M:%S")
        task = Task(id="1", title="Test", status="running", started_at=naive_str)
        assert is_stale(task, timeout_minutes=30) is False


class TestBuildTaskPrompt:
    def test_basic(self):
        task = Task(
            id="abc", title="Research AcmeCorp needs",
            priority="high", body="Check their current AI data requirements",
        )
        prompt = build_task_prompt(task)
        assert "Research AcmeCorp needs" in prompt
        assert "high" in prompt
        assert "Check their current AI data requirements" in prompt

    def test_subtask(self):
        task = Task(
            id="abc", title="Write pricing section",
            priority="medium", body="Part of pitch deck",
            parent_id="parent123",
        )
        prompt = build_task_prompt(task)
        assert "subtask" in prompt.lower()
        assert "Write pricing section" in prompt

    def test_no_body(self):
        task = Task(id="abc", title="Do something", priority="medium")
        prompt = build_task_prompt(task)
        assert "Do something" in prompt
        assert "Details" not in prompt

    def test_includes_executor_doctrine(self):
        """Prompt must carry the executor skill doctrine (Result card contract)."""
        task = Task(id="x", title="Anything", priority="low")
        prompt = build_task_prompt(task)
        # Doctrine hallmarks from .claude/skills/executor/SKILL.md
        assert "What was done" in prompt
        assert "RESULT" in prompt or "Result card" in prompt

    def test_includes_draft_only_guard(self):
        """Regression: 2026-04-24 Acme neurology dataset incident.

        The executor doctrine must carry an explicit draft-only guard so a
        neutral-prefix task (`[REPLY]`, `[OPS]`, `[PREP]`, no prefix) can't
        silently graduate into an irreversible external action (appointment
        booking, payment, outbound personal message). If this assertion
        fails, the SKILL.md was edited in a way that removed the guard —
        re-add it before shipping.
        """
        task = Task(id="x", title="[OPS] Something benign", priority="low")
        prompt = build_task_prompt(task)
        # Hallmarks of the draft-only section
        assert "Draft-only" in prompt or "draft-only" in prompt
        assert "Appointment booking" in prompt
        assert "[PROPOSAL]" in prompt
        # Concrete examples so the guard can't be gutted to a single word
        assert "neurologist" in prompt.lower() or "dentist" in prompt.lower()

    def test_falls_back_when_skill_missing(self, tmp_path, monkeypatch):
        """A missing executor skill file must not brick the consumer."""
        import tasks.consumer as consumer_mod
        monkeypatch.setattr(
            consumer_mod, "EXECUTOR_SKILL_PATH", tmp_path / "nonexistent.md",
        )
        task = Task(id="x", title="Ping", priority="low", body="b")
        prompt = build_task_prompt(task)
        assert "Ping" in prompt
        assert "b" in prompt
        # Fallback still mentions the Result card contract
        assert "RESULT" in prompt


class TestCheckAndExecute:
    @patch("tasks.consumer._idle_branch")
    @patch("tasks.consumer.list_tasks")
    def test_empty_queue(self, mock_list, mock_idle):
        """Empty queue must delegate to _idle_branch (which decides to idle or propose)."""
        mock_list.return_value = []
        mock_idle.return_value = {"action": "idle", "reason": "empty"}
        result = check_and_execute()
        assert result["action"] == "idle"
        mock_idle.assert_called_once()

    @patch("tasks.consumer.list_tasks")
    def test_already_running_not_stale(self, mock_list):
        now = datetime.now(timezone.utc).isoformat()
        mock_list.return_value = [
            Task(id="1", title="Running task", status="running", started_at=now),
        ]
        result = check_and_execute()
        assert result["action"] == "locked"

    @patch("tasks.consumer.send_feed")
    @patch("tasks.consumer.mark_failed")
    @patch("tasks.consumer.list_tasks")
    def test_stale_task_recovered(self, mock_list, mock_mark, mock_feed):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mock_list.return_value = [
            Task(id="1", title="Stale task", status="running", started_at=old),
        ]
        result = check_and_execute()
        assert result["action"] == "stale_recovered"
        mock_mark.assert_called_once()

    @patch("tasks.consumer.mark_done")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_executes_highest_priority(self, mock_list, mock_exec, mock_mark_run, mock_mark_done):
        mock_list.return_value = [
            Task(id="1", title="Low task", status="pending", priority="low"),
            Task(id="2", title="High task", status="pending", priority="high"),
        ]
        mock_exec.return_value = {"result": "Done", "session_id": "s1", "cost": 0.5, "duration": 30}
        result = check_and_execute()
        assert result["action"] == "executed"
        # Should pick task 2 (high priority)
        executed_task = mock_exec.call_args[0][0]
        assert executed_task.id == "2"
        assert executed_task.priority == "high"

    @patch("tasks.consumer.mark_failed")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_handles_execution_error(self, mock_list, mock_exec, mock_mark_run, mock_mark_fail):
        mock_list.return_value = [
            Task(id="1", title="Task", status="pending"),
        ]
        mock_exec.return_value = {"error": "Timeout after 300s", "cost": 0, "duration": 300}
        result = check_and_execute()
        assert result["action"] == "failed"
        mock_mark_fail.assert_called_once()

    @patch("tasks.consumer.mark_failed")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_handles_execution_exception(self, mock_list, mock_exec, mock_mark_run, mock_mark_fail):
        mock_list.return_value = [
            Task(id="1", title="Task", status="pending"),
        ]
        mock_exec.side_effect = Exception("Connection refused")
        result = check_and_execute()
        assert result["action"] == "error"
        mock_mark_fail.assert_called_once()

    @patch("tasks.consumer._idle_branch")
    @patch("tasks.consumer.list_tasks")
    def test_no_pending_tasks(self, mock_list, mock_idle):
        mock_list.return_value = [
            Task(id="1", title="Done", status="done"),
            Task(id="2", title="Failed", status="failed"),
        ]
        mock_idle.return_value = {"action": "idle", "reason": "empty"}
        result = check_and_execute()
        assert result["action"] == "idle"
        mock_idle.assert_called_once()

    @patch("tasks.consumer.list_tasks")
    def test_list_tasks_error(self, mock_list):
        mock_list.side_effect = RuntimeError("gog failed")
        result = check_and_execute()
        assert result["action"] == "error"

    @patch("tasks.consumer.mark_running", side_effect=Exception("API error"))
    @patch("tasks.consumer.list_tasks")
    def test_mark_running_failure(self, mock_list, mock_mark):
        mock_list.return_value = [
            Task(id="1", title="Task", status="pending"),
        ]
        result = check_and_execute()
        assert result["action"] == "error"
        assert "API error" in result["error"]


class TestConsumerDedup:
    """Regression: 2026-04-19 Alex Reed + DexCo dex_pay double-execution.

    Two overlapping cron consumer invocations pulled the same upstream
    work within ~48s and ran it end-to-end twice. Two layers protect
    against recurrence:

      1. `source_gtask_id` dedup stops any task that already has a
         non-terminal peer referencing the same origin.
      2. A process-level flock (`consumer_lock`) pins list/claim/execute
         to one consumer at a time.
    """

    @patch("tasks.consumer.mark_done")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_skips_when_sibling_shares_source_gtask_id(
        self, mock_list, mock_exec, mock_mark_run, mock_mark_done,
    ):
        mock_list.return_value = [
            Task(id="A", title="[ACTION] Alex Reed followup",
                 status="pending", priority="medium",
                 source_gtask_id="milan-src-001"),
            Task(id="B", title="[ACTION] Alex Reed followup",
                 status="pending", priority="medium",
                 source_gtask_id="milan-src-001"),
        ]
        result = check_and_execute()
        assert result["action"] == "dup_source"
        assert result["source_gtask_id"] == "milan-src-001"
        mock_exec.assert_not_called()
        mock_mark_run.assert_not_called()

    @patch("tasks.consumer.mark_done")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_runs_when_source_gtask_id_is_unique(
        self, mock_list, mock_exec, mock_mark_run, mock_mark_done,
    ):
        mock_list.return_value = [
            Task(id="A", title="[ACTION] Solo",
                 status="pending", priority="high",
                 source_gtask_id="solo-src-001"),
            Task(id="B", title="[ACTION] Unrelated",
                 status="pending", priority="low",
                 source_gtask_id="different-src-002"),
        ]
        mock_exec.return_value = {"result": "ok", "session_id": "s1", "cost": 0, "duration": 1}
        result = check_and_execute()
        assert result["action"] == "executed"
        assert mock_exec.call_args[0][0].id == "A"

    @patch("tasks.consumer.mark_done")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_ignores_terminal_siblings(
        self, mock_list, mock_exec, mock_mark_run, mock_mark_done,
    ):
        """Completed/failed peers sharing source_gtask_id don't block a rerun."""
        mock_list.return_value = [
            Task(id="A", title="[ACTION] Retry",
                 status="pending", priority="medium",
                 source_gtask_id="retry-src-001"),
            Task(id="B", title="[ACTION] Earlier run",
                 status="failed", priority="medium",
                 source_gtask_id="retry-src-001"),
        ]
        mock_exec.return_value = {"result": "ok", "session_id": "s1", "cost": 0, "duration": 1}
        result = check_and_execute()
        assert result["action"] == "executed"
        assert mock_exec.call_args[0][0].id == "A"

    def test_consumer_lock_is_exclusive(self, tmp_path):
        lock_path = tmp_path / "consumer.lock"
        with consumer_lock(lock_path) as first:
            assert first is True
            with consumer_lock(lock_path) as second:
                assert second is False
        with consumer_lock(lock_path) as third:
            assert third is True

    @patch("tasks.consumer._check_and_execute_locked")
    def test_overlapping_cron_invocation_is_skipped(
        self, mock_locked, tmp_path, monkeypatch,
    ):
        import tasks.consumer as consumer_mod
        lock_path = tmp_path / "consumer.lock"
        monkeypatch.setattr(consumer_mod, "CONSUMER_LOCK_PATH", lock_path)

        # Hold the lock from a separate fd so the inner `check_and_execute`
        # call models a second overlapping cron invocation rather than a
        # reentrant one.
        held_fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = check_and_execute()
        finally:
            fcntl.flock(held_fd, fcntl.LOCK_UN)
            os.close(held_fd)

        assert result["action"] == "locked_by_peer"
        mock_locked.assert_not_called()


class TestExecuteTask:
    @patch("tasks.consumer.ClaudeExecutor")
    def test_calls_executor(self, mock_cls):
        from tasks.consumer import execute_task
        mock_exec = MagicMock()
        mock_exec.run.return_value = {"result": "Done", "session_id": "s1", "cost": 0.1, "duration": 5}
        mock_cls.return_value = mock_exec
        task = Task(id="1", title="Test", priority="high", body="details")
        result = execute_task(task)
        assert result["result"] == "Done"
        mock_exec.run.assert_called_once()
        call_kwargs = mock_exec.run.call_args[1]
        assert call_kwargs["mode"] == "isolated"
        assert call_kwargs["skip_permissions"] is True


class TestMarkRunning:
    @patch("tasks.consumer.update_task_notes")
    def test_updates_status(self, mock_update):
        from tasks.consumer import mark_running
        task = Task(id="1", title="Test")
        mark_running(task)
        assert task.status == "running"
        assert task.started_at is not None
        mock_update.assert_called_once()


class TestMarkDone:
    """mark_done converts the finished task into a [RESULT] or [PROPOSAL]
    card in place (same GTask id). The Deck shows one card evolving instead
    of emitting a second card. Legacy create_result + complete_task path is
    a fallback only — used when conversion raises."""

    @patch("tasks.consumer.convert_to_result")
    @patch("tasks.consumer.convert_to_proposal")
    def test_delegate_path_converts_to_result(self, mock_proposal, mock_result):
        """An [ACTION] task produces a [RESULT] conversion, not a new card."""
        from tasks.consumer import mark_done
        task = Task(
            id="gt-action-1",
            title="[ACTION] Draft AcmeCorp reply",
            body="## Source GTask\nid: gt-src-9",
            shape="reply",
            mode_tags="deal,microsoft",
        )
        result = {
            "result": "## What was done\nDrafted reply.\n",
            "session_id": "sess-xyz",
        }
        mark_done(task, result)

        mock_proposal.assert_not_called()
        mock_result.assert_called_once()
        kwargs = mock_result.call_args.kwargs
        assert kwargs["task_id"] == "gt-action-1"
        assert kwargs["title"] == "[ACTION] Draft AcmeCorp reply"
        assert "Drafted reply" in kwargs["body"]
        assert kwargs["mode_tags"] == ["deal", "microsoft"]
        assert kwargs["session_id"] == "sess-xyz"

    @patch("tasks.consumer.convert_to_result")
    @patch("tasks.consumer.convert_to_proposal")
    def test_proposal_dispatch_converts_to_proposal(self, mock_proposal, mock_result):
        """A [RESEARCH] task produces a [PROPOSAL] conversion."""
        from tasks.consumer import mark_done
        task = Task(
            id="gt-research-1",
            title="[RESEARCH] Plan Sentinel pitch",
            body="",
            shape="review",
            mode_tags="deal",
        )
        result = {
            "result": "## Plan\nStep 1\nStep 2\n",
            "session_id": "sess-abc",
        }
        mark_done(task, result)

        mock_result.assert_not_called()
        mock_proposal.assert_called_once()
        kwargs = mock_proposal.call_args.kwargs
        assert kwargs["task_id"] == "gt-research-1"
        assert kwargs["title"] == "[RESEARCH] Plan Sentinel pitch"
        assert "Step 1" in kwargs["plan"]
        assert kwargs["shape"] == "review"
        assert kwargs["mode_tags"] == ["deal"]

    @patch("tasks.consumer.convert_to_result")
    @patch("tasks.consumer.convert_to_proposal")
    def test_truncates_long_output_before_conversion(self, mock_proposal, mock_result):
        from tasks.consumer import mark_done
        task = Task(id="1", title="[ACTION] Big task", body="")
        result = {"result": "x" * 9000, "session_id": "s1"}
        mark_done(task, result)
        body = mock_result.call_args.kwargs["body"]
        assert "truncated" in body
        assert len(body) <= 7600

    @patch("tasks.consumer.create_result")
    @patch("tasks.consumer.complete_task")
    @patch("tasks.consumer.update_task_notes")
    @patch("tasks.consumer.convert_to_result")
    @patch("tasks.consumer.convert_to_proposal")
    def test_empty_output_completes_without_conversion(
        self, mock_proposal, mock_convert, mock_update, mock_complete, mock_create,
    ):
        """No output => nothing to show on the Deck; just close the task."""
        from tasks.consumer import mark_done
        task = Task(id="1", title="[ACTION] Test", body="Body")
        result = {"result": "", "session_id": "s1"}
        mark_done(task, result)
        assert task.status == "done"
        mock_convert.assert_not_called()
        mock_proposal.assert_not_called()
        mock_create.assert_not_called()
        mock_complete.assert_called_once_with("1")

    @patch("tasks.consumer.create_result")
    @patch("tasks.consumer.complete_task")
    @patch("tasks.consumer.update_task_notes")
    @patch("tasks.consumer.convert_to_result", side_effect=RuntimeError("gog down"))
    def test_falls_back_to_legacy_flow_on_conversion_failure(
        self, mock_convert, mock_update, mock_complete, mock_create,
    ):
        """If in-place conversion fails, the legacy create_result +
        complete_task path must kick in so the task never stays in `running`."""
        from tasks.consumer import mark_done
        task = Task(
            id="gt-action-9",
            title="[ACTION] Follow up Bruno",
            body="",
            shape="reply",
        )
        result = {"result": "## What was done\nPing sent.\n", "session_id": "s1"}
        mark_done(task, result)
        mock_convert.assert_called_once()
        mock_complete.assert_called_once_with("gt-action-9")
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["parent_task_id"] == "gt-action-9"
        assert kwargs["title"] == "[ACTION] Follow up Bruno"


class TestMarkFailed:
    @patch("tasks.consumer.update_task_notes")
    def test_marks_failed(self, mock_update):
        from tasks.consumer import mark_failed
        task = Task(id="1", title="Test", body="Original")
        mark_failed(task, "Timeout error")
        assert task.status == "failed"
        assert task.completed_at is not None
        assert "Timeout error" in task.body


class TestMain:
    @patch("tasks.consumer.check_and_execute")
    def test_idle(self, mock_check, capsys):
        from tasks.consumer import main
        mock_check.return_value = {"action": "idle"}
        main()
        out = capsys.readouterr().out
        assert "TASK_CONSUMER_OK" in out

    @patch("tasks.consumer.check_and_execute")
    def test_locked(self, mock_check, capsys):
        from tasks.consumer import main
        mock_check.return_value = {"action": "locked", "task_id": "t1"}
        main()
        out = capsys.readouterr().out
        assert "task running" in out

    @patch("tasks.consumer.check_and_execute")
    def test_executed(self, mock_check, capsys):
        from tasks.consumer import main
        mock_check.return_value = {"action": "executed", "task_id": "t1", "cost": 0.5, "duration": 30}
        main()
        out = capsys.readouterr().out
        assert "completed" in out.lower()

    @patch("tasks.consumer.check_and_execute")
    def test_stale_recovered(self, mock_check, capsys):
        from tasks.consumer import main
        mock_check.return_value = {"action": "stale_recovered", "task_id": "t1"}
        main()
        out = capsys.readouterr().out
        assert "stale" in out.lower()

    @patch("tasks.consumer.check_and_execute")
    def test_error_exits(self, mock_check):
        from tasks.consumer import main
        mock_check.return_value = {"action": "error", "error": "boom"}
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


# Regression: 2026-04-19. Two consumer cron invocations landing in the same
# window both called list_tasks(), saw the same top-pending row, and raced
# to mark_running() — producing duplicate [RESULT] cards (Alex Reed WSJ
# FOLLOW-UP executed twice) and duplicate [PROPOSAL]/[REFINE] rows (DexCo
# dex_pay x3). The consumer now wraps its critical section in an fcntl
# flock and walks pending tasks looking for source_gtask_id collisions.
class TestConsumerLock:
    def test_acquires_when_free(self, tmp_path):
        lock = tmp_path / "klava.lock"
        with consumer_lock(lock) as acquired:
            assert acquired is True
            assert lock.exists()

    def test_releases_on_exit(self, tmp_path):
        lock = tmp_path / "klava.lock"
        with consumer_lock(lock) as first:
            assert first is True
        # After release the same path must be acquirable again.
        with consumer_lock(lock) as second:
            assert second is True

    def test_rejects_when_held(self, tmp_path):
        lock = tmp_path / "klava.lock"
        # Hold the flock manually on a separate fd to simulate peer consumer.
        holder_fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY, 0o644)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with consumer_lock(lock) as acquired:
                assert acquired is False
        finally:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
            os.close(holder_fd)

    def test_writes_pid(self, tmp_path):
        lock = tmp_path / "klava.lock"
        with consumer_lock(lock) as acquired:
            assert acquired is True
            assert lock.read_text().strip() == str(os.getpid())


class TestCheckAndExecuteLock:
    def test_returns_locked_by_peer_when_lock_held(self):
        """When a peer consumer holds the lock, this tick must bail cleanly.

        Uses the autouse-isolated CONSUMER_LOCK_PATH so this does not touch
        the real cron lock file at /tmp/klava-consumer.lock.
        """
        import tasks.consumer as consumer_mod
        lock = Path(str(consumer_mod.CONSUMER_LOCK_PATH))

        holder_fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY, 0o644)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # list_tasks must never be called — we bail before the RPC.
            with patch("tasks.consumer.list_tasks") as mock_list:
                result = check_and_execute()
                assert result["action"] == "locked_by_peer"
                mock_list.assert_not_called()
        finally:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
            os.close(holder_fd)


class TestFindSourceDuplicate:
    def test_no_source_id_returns_none(self):
        target = Task(id="a", title="T", status="pending")
        others = [Task(id="b", title="U", status="pending")]
        assert _find_source_duplicate(target, others + [target]) is None

    def test_finds_running_peer(self):
        target = Task(id="a", title="T", status="pending", source_gtask_id="src-1")
        peer = Task(id="b", title="U", status="running", source_gtask_id="src-1")
        dup = _find_source_duplicate(target, [target, peer])
        assert dup is not None
        assert dup.id == "b"

    def test_finds_pending_peer(self):
        target = Task(id="a", title="T", status="pending", source_gtask_id="src-1")
        peer = Task(id="b", title="U", status="pending", source_gtask_id="src-1")
        dup = _find_source_duplicate(target, [target, peer])
        assert dup is not None

    def test_ignores_done_peer(self):
        """A completed peer is terminal — does NOT block re-execution."""
        target = Task(id="a", title="T", status="pending", source_gtask_id="src-1")
        peer = Task(id="b", title="U", status="done", source_gtask_id="src-1",
                    gtask_status="completed")
        assert _find_source_duplicate(target, [target, peer]) is None

    def test_ignores_different_source(self):
        target = Task(id="a", title="T", status="pending", source_gtask_id="src-1")
        peer = Task(id="b", title="U", status="running", source_gtask_id="src-2")
        assert _find_source_duplicate(target, [target, peer]) is None

    def test_self_is_not_a_duplicate(self):
        target = Task(id="a", title="T", status="pending", source_gtask_id="src-1")
        assert _find_source_duplicate(target, [target]) is None


class TestPickNextTask:
    def test_picks_unique_top(self):
        a = Task(id="a", title="A", status="pending", priority="high")
        b = Task(id="b", title="B", status="pending", priority="low")
        picked, blocker = _pick_next_task([a, b], [a, b])
        assert picked.id == "a"
        assert blocker is None

    def test_skips_duplicate_picks_next(self):
        """Top candidate has a running peer; picker walks to the next one."""
        running_peer = Task(id="x", title="R", status="running", source_gtask_id="src-1")
        blocked = Task(id="a", title="A", status="pending", priority="high",
                       source_gtask_id="src-1")
        free = Task(id="b", title="B", status="pending", priority="medium")
        picked, blocker = _pick_next_task([blocked, free], [running_peer, blocked, free])
        assert picked.id == "b"

    def test_all_blocked_returns_none(self):
        running_peer = Task(id="x", title="R", status="running", source_gtask_id="src-1")
        blocked = Task(id="a", title="A", status="pending", source_gtask_id="src-1")
        picked, blocker = _pick_next_task([blocked], [running_peer, blocked])
        assert picked is None
        assert blocker is not None
        assert blocker.id == "x"


class TestCheckAndExecuteDedup:
    @patch("tasks.consumer.list_tasks")
    def test_skips_when_source_already_running(self, mock_list):
        """A pending task whose source_gtask_id matches a running peer must not execute."""
        now = datetime.now(timezone.utc).isoformat()
        # The running peer uses a different task row (a leftover duplicate).
        # Here we build a scenario where no task is in status="running" (so the
        # get_running guard doesn't fire) but a completed-looking peer-in-flight
        # would still block — actually, the simplest regression case is: a
        # pending row with a source_gtask_id that ALREADY has a non-terminal
        # peer. get_running() fires first if a peer is status="running".
        # So this test exercises: pending candidate is unique but another
        # PENDING row with same source_gtask_id sits elsewhere in the queue.
        a = Task(id="a", title="Dup-A", status="pending", priority="high",
                 source_gtask_id="src-42")
        b = Task(id="b", title="Dup-B", status="pending", priority="high",
                 source_gtask_id="src-42")
        mock_list.return_value = [a, b]
        # Both share the same source; _pick_next_task walks both and finds
        # each blocked by the other → returns dup_source.
        with patch("tasks.consumer.mark_running"), patch("tasks.consumer.execute_task"):
            result = check_and_execute()
        assert result["action"] == "dup_source"
        assert result["source_gtask_id"] == "src-42"

    @patch("tasks.consumer.mark_done")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_unique_source_still_executes(self, mock_list, mock_exec, mock_run, mock_done):
        a = Task(id="a", title="Solo", status="pending", priority="high",
                 source_gtask_id="src-99")
        mock_list.return_value = [a]
        mock_exec.return_value = {"result": "Done", "session_id": "s1", "cost": 0.1, "duration": 5}
        result = check_and_execute()
        assert result["action"] == "executed"
        assert result["task_id"] == "a"

    @patch("tasks.consumer.mark_done")
    @patch("tasks.consumer.mark_running")
    @patch("tasks.consumer.execute_task")
    @patch("tasks.consumer.list_tasks")
    def test_no_source_id_not_affected(self, mock_list, mock_exec, mock_run, mock_done):
        """Tasks without source_gtask_id bypass dedup entirely (backward compat)."""
        a = Task(id="a", title="Legacy A", status="pending", priority="high")
        b = Task(id="b", title="Legacy B", status="pending", priority="medium")
        mock_list.return_value = [a, b]
        mock_exec.return_value = {"result": "Done", "session_id": "s1", "cost": 0.1, "duration": 5}
        result = check_and_execute()
        assert result["action"] == "executed"
        assert result["task_id"] == "a"


# Regression: 2026-04-19 follow-up. The cron-only flock left the
# dashboard-vs-cron race open: gateway/routes/dashboard_api.py::_launch_klava
# spawned a Chat session without the consumer lock, so a cron consumer that
# had already list_tasks()'d in that window would see the task as pending
# and double-spawn. _launch_klava now acquires consumer_lock and re-checks
# task state before marking it running.
class TestLaunchKlavaLockIntegration:
    """Dashboard _launch_klava and cron check_and_execute must never both
    claim the same task. This is an integration test: it exercises the
    real flock + real KlavaLaunchContention exception across two threads.
    """

    def _setup_mock_gateway(self, monkeypatch, spawned):
        """Wire dashboard_api to mock collaborators so _launch_klava is callable
        without a running webhook-server. Records every spawn on the shared
        `spawned` list so we can assert exactly one session was started.
        """
        import sys
        import types
        root = Path(__file__).resolve().parent.parent.parent
        gw = root / "gateway"
        for p in (str(root), str(gw)):
            if p not in sys.path:
                sys.path.insert(0, p)

        from gateway.routes import dashboard_api

        class MockChatNS:
            def _run_claude(self, *args, **kwargs):
                # args[2] is tab_id
                spawned.append(("dashboard", args[2]))

        monkeypatch.setattr(dashboard_api, "_chat_ns", MockChatNS())
        monkeypatch.setattr(dashboard_api, "_socketio", None)
        return dashboard_api

    def _setup_mock_queue(self, monkeypatch, task):
        """Stateful in-memory mock for tasks.queue so status transitions
        committed by one thread are visible to the other.
        """
        state = {task.id: task}

        def fake_list_tasks(*args, **kwargs):
            return [Task(**{k: getattr(v, k) for k in v.__dataclass_fields__})
                    for v in state.values()]

        def fake_update_notes(task_id, notes, list_id=None):
            from tasks.queue import parse_frontmatter
            meta, body = parse_frontmatter(notes)
            t = state[task_id]
            if "status" in meta:
                t.status = meta["status"]
            if "started_at" in meta:
                t.started_at = meta["started_at"]

        # Patch at every import site
        monkeypatch.setattr("tasks.queue.list_tasks", fake_list_tasks)
        monkeypatch.setattr("tasks.queue.update_task_notes", fake_update_notes)
        monkeypatch.setattr("tasks.consumer.list_tasks", fake_list_tasks)
        monkeypatch.setattr("tasks.consumer.update_task_notes", fake_update_notes)
        return state

    def test_concurrent_launch_and_consumer_spawns_once(self, monkeypatch):
        """Fire _launch_klava and check_and_execute from two threads at the
        same instant. The flock must serialize them so exactly one spawns
        a session.
        """
        import threading
        import tasks.consumer as consumer_mod
        from tasks.consumer import KlavaLaunchContention

        spawned: list[tuple[str, str]] = []
        errors: list[tuple[str, BaseException]] = []

        task = Task(
            id="race-task-001",
            title="Race regression",
            status="pending",
            priority="high",
            source_gtask_id="origin-race-001",
        )
        self._setup_mock_queue(monkeypatch, task)
        dashboard_api = self._setup_mock_gateway(monkeypatch, spawned)

        def fake_execute(task_obj):
            spawned.append(("consumer", task_obj.id))
            # Give the other thread a chance to observe the running state
            import time
            time.sleep(0.02)
            return {
                "result": "## What was done\nExecuted\n",
                "session_id": "cons-sess",
                "cost": 0, "duration": 1,
            }

        def fake_mark_done(task_obj, result):
            task_obj.status = "done"

        monkeypatch.setattr(consumer_mod, "execute_task", fake_execute)
        monkeypatch.setattr(consumer_mod, "mark_done", fake_mark_done)

        barrier = threading.Barrier(2)

        def run_dashboard():
            try:
                barrier.wait()
                dashboard_api._launch_klava(
                    task.id, task.title, "", task.priority, "dashboard",
                )
            except KlavaLaunchContention:
                # Expected if cron won the lock race
                pass
            except Exception as e:
                errors.append(("dashboard", e))

        def run_consumer():
            try:
                barrier.wait()
                consumer_mod.check_and_execute()
            except Exception as e:
                errors.append(("consumer", e))

        t1 = threading.Thread(target=run_dashboard)
        t2 = threading.Thread(target=run_consumer)
        t1.start(); t2.start()
        t1.join(timeout=5); t2.join(timeout=5)

        assert not errors, f"unexpected errors: {errors}"
        # Exactly one path started a session — whichever grabbed the lock first.
        # The loser either saw KlavaLaunchContention (dashboard) or
        # locked_by_peer / status=running (consumer) and bailed.
        assert len(spawned) == 1, (
            f"expected exactly one spawn, got {len(spawned)}: {spawned}"
        )

    def test_launch_raises_contention_when_lock_held(self, monkeypatch):
        """A blocking peer (simulating an in-flight cron consumer) must
        force _launch_klava to raise KlavaLaunchContention.
        """
        import tasks.consumer as consumer_mod
        from tasks.consumer import KlavaLaunchContention

        spawned: list = []
        task = Task(id="held-task", title="Held", status="pending",
                    priority="high")
        self._setup_mock_queue(monkeypatch, task)
        dashboard_api = self._setup_mock_gateway(monkeypatch, spawned)

        lock_path = str(consumer_mod.CONSUMER_LOCK_PATH)
        holder_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(KlavaLaunchContention):
                dashboard_api._launch_klava(
                    task.id, task.title, "", task.priority, "dashboard",
                )
        finally:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
            os.close(holder_fd)

        # No session should have been spawned while the peer held the lock.
        assert spawned == []
        # The task must still be pending — we refused to claim it.
        assert task.status == "pending"

    def test_launch_raises_contention_when_task_already_running(self, monkeypatch):
        """If the cron consumer already marked the task running, the
        dashboard path must refuse to re-spawn it.
        """
        import tasks.consumer as consumer_mod  # noqa: F401
        from tasks.consumer import KlavaLaunchContention

        spawned: list = []
        task = Task(id="already-running", title="AR", status="running",
                    priority="medium")
        self._setup_mock_queue(monkeypatch, task)
        dashboard_api = self._setup_mock_gateway(monkeypatch, spawned)

        with pytest.raises(KlavaLaunchContention):
            dashboard_api._launch_klava(
                task.id, task.title, "", task.priority, "dashboard",
            )

        assert spawned == []
