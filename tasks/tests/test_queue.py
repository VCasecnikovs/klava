"""Tests for tasks/queue.py - frontmatter parsing, Task model, queue operations."""

import json
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch, MagicMock

from tasks.queue import (
    parse_frontmatter,
    build_frontmatter,
    Task,
    get_pending,
    get_running,
    PRIORITY_ORDER,
)


class TestParseFrontmatter:
    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("just plain text")
        assert meta == {}
        assert body == "just plain text"

    def test_empty_string(self):
        meta, body = parse_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_none(self):
        meta, body = parse_frontmatter(None)
        assert meta == {}
        assert body is None

    def test_basic_frontmatter(self):
        text = "---\nstatus: pending\npriority: high\n---\nTask body here"
        meta, body = parse_frontmatter(text)
        assert meta["status"] == "pending"
        assert meta["priority"] == "high"
        assert body == "Task body here"

    def test_frontmatter_no_body(self):
        text = "---\nstatus: running\n---"
        meta, body = parse_frontmatter(text)
        assert meta["status"] == "running"
        assert body == ""

    def test_incomplete_frontmatter(self):
        text = "---\nstatus: pending\nno closing delimiter"
        meta, body = parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_multiline_body(self):
        text = "---\nstatus: pending\n---\nLine 1\nLine 2\nLine 3"
        meta, body = parse_frontmatter(text)
        assert meta["status"] == "pending"
        assert body == "Line 1\nLine 2\nLine 3"

    def test_frontmatter_with_timestamps(self):
        text = "---\nstatus: running\nstarted_at: 2026-03-11T14:00:00+00:00\nsession_id: abc123\n---\nBody"
        meta, body = parse_frontmatter(text)
        assert meta["status"] == "running"
        assert meta["started_at"] == "2026-03-11T14:00:00+00:00"
        assert meta["session_id"] == "abc123"
        assert body == "Body"

    def test_empty_value(self):
        text = "---\nstatus:\n---"
        meta, body = parse_frontmatter(text)
        assert meta["status"] == ""

    def test_colon_in_value(self):
        text = "---\nresult: Done: created 3 files\n---"
        meta, body = parse_frontmatter(text)
        assert meta["result"] == "Done: created 3 files"


class TestBuildFrontmatter:
    def test_basic(self):
        fm = build_frontmatter({"status": "pending", "priority": "high"})
        assert fm == "---\nstatus: pending\npriority: high\n---"

    def test_skips_none_and_empty(self):
        fm = build_frontmatter({"status": "done", "session_id": None, "result": ""})
        assert "session_id" not in fm
        assert "result" not in fm
        assert "status: done" in fm

    def test_roundtrip(self):
        original = {"status": "running", "priority": "high", "session_id": "abc"}
        fm = build_frontmatter(original)
        parsed, _ = parse_frontmatter(fm)
        assert parsed == original


class TestTaskFromGtask:
    def test_with_frontmatter(self):
        gtask = {
            "id": "abc123",
            "title": "Research AcmeCorp",
            "notes": "---\nstatus: pending\npriority: high\nsource: chat\n---\nDo the research",
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.id == "abc123"
        assert task.title == "Research AcmeCorp"
        assert task.status == "pending"
        assert task.priority == "high"
        assert task.source == "chat"
        assert task.body == "Do the research"

    def test_without_frontmatter(self):
        gtask = {
            "id": "def456",
            "title": "Simple task",
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.status == "pending"
        assert task.priority == "medium"
        assert task.source == "manual"
        assert task.body == ""

    def test_completed_overrides_status(self):
        gtask = {
            "id": "xyz",
            "title": "Done task",
            "notes": "---\nstatus: running\n---",
            "status": "completed",
        }
        task = Task.from_gtask(gtask)
        assert task.status == "done"

    def test_with_parent(self):
        gtask = {
            "id": "sub1",
            "title": "Subtask",
            "parent": "parent1",
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.parent_id == "parent1"

    def test_notes_none(self):
        gtask = {"id": "x", "title": "No notes", "status": "needsAction"}
        task = Task.from_gtask(gtask)
        assert task.body == ""
        assert task.status == "pending"


class TestTaskToNotes:
    def test_basic(self):
        task = Task(
            id="x", title="Test",
            status="running", priority="high",
            session_id="sess123",
            started_at="2026-03-11T14:00:00",
            body="Do something",
        )
        notes = task.to_notes()
        assert "status: running" in notes
        assert "priority: high" in notes
        assert "session_id: sess123" in notes
        assert "started_at: 2026-03-11T14:00:00" in notes
        assert "Do something" in notes

    def test_minimal(self):
        task = Task(id="x", title="Test", status="pending")
        notes = task.to_notes()
        assert "status: pending" in notes
        assert "priority: medium" in notes
        assert "session_id" not in notes

    def test_roundtrip(self):
        task = Task(
            id="x", title="T",
            status="running", priority="high",
            source="heartbeat", session_id="s1",
            started_at="2026-03-11T14:00:00",
            body="Body text",
        )
        notes = task.to_notes()
        meta, body = parse_frontmatter(notes)
        assert meta["status"] == "running"
        assert meta["priority"] == "high"
        assert meta["source"] == "heartbeat"
        assert meta["session_id"] == "s1"
        assert body == "Body text"

    # Regression: 2026-04-19 consumer dedup bug. source_gtask_id must survive
    # the frontmatter round-trip so the consumer can see origin collisions
    # after a GTasks refresh.
    def test_source_gtask_id_roundtrip(self):
        task = Task(
            id="x", title="T", status="pending",
            source_gtask_id="origin-gtask-abc",
            body="",
        )
        notes = task.to_notes()
        assert "source_gtask_id: origin-gtask-abc" in notes
        meta, _ = parse_frontmatter(notes)
        assert meta["source_gtask_id"] == "origin-gtask-abc"

    def test_task_from_gtask_parses_source_gtask_id(self):
        gtask = {
            "id": "new-id",
            "title": "T",
            "notes": "---\nstatus: pending\nsource_gtask_id: origin-xyz\n---\n",
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.source_gtask_id == "origin-xyz"


class TestGetPending:
    def test_sorts_by_priority(self):
        tasks = [
            Task(id="1", title="Low", priority="low"),
            Task(id="2", title="High", priority="high"),
            Task(id="3", title="Medium", priority="medium"),
        ]
        pending = get_pending(tasks)
        assert [t.priority for t in pending] == ["high", "medium", "low"]

    def test_excludes_non_pending(self):
        tasks = [
            Task(id="1", title="Pending", status="pending"),
            Task(id="2", title="Running", status="running"),
            Task(id="3", title="Done", status="done"),
            Task(id="4", title="Failed", status="failed"),
        ]
        pending = get_pending(tasks)
        assert len(pending) == 1
        assert pending[0].title == "Pending"

    def test_empty_list(self):
        assert get_pending([]) == []

    def test_preserves_order_within_priority(self):
        tasks = [
            Task(id="1", title="First high", priority="high"),
            Task(id="2", title="Second high", priority="high"),
            Task(id="3", title="Low", priority="low"),
        ]
        pending = get_pending(tasks)
        assert pending[0].title == "First high"
        assert pending[1].title == "Second high"


# Regression: 2026-04-20. [ALERT] Wallet call task was re-queued every 5 min
# by the executor without a way to say "run only after T+30min"; the consumer
# picked the re-queued copy up each tick and fired the alert 8 times. Fix:
# execute_after on the Task + filter in get_pending() until that moment passes.
class TestExecuteAfterDefer:
    def test_is_deferred_future_timestamp(self):
        from tasks.queue import is_deferred
        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        task = Task(id="x", title="Deferred", execute_after=future)
        assert is_deferred(task) is True

    def test_is_deferred_past_timestamp(self):
        from tasks.queue import is_deferred
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        task = Task(id="x", title="Ready", execute_after=past)
        assert is_deferred(task) is False

    def test_is_deferred_none_field(self):
        from tasks.queue import is_deferred
        assert is_deferred(Task(id="x", title="No defer")) is False

    def test_is_deferred_invalid_timestamp(self):
        """Unparseable timestamp falls back to not-deferred so a corrupted
        field cannot permanently strand a task."""
        from tasks.queue import is_deferred
        task = Task(id="x", title="Bad", execute_after="not-a-date")
        assert is_deferred(task) is False

    def test_is_deferred_naive_timestamp_treated_as_utc(self):
        from tasks.queue import is_deferred
        future_naive = (datetime.now(timezone.utc) + timedelta(minutes=10)
                        ).strftime("%Y-%m-%dT%H:%M:%S")
        task = Task(id="x", title="Naive", execute_after=future_naive)
        assert is_deferred(task) is True

    def test_get_pending_excludes_deferred(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        tasks = [
            Task(id="ready", title="Ready now", status="pending",
                 priority="high", execute_after=past),
            Task(id="deferred", title="Alert 30min before call",
                 status="pending", priority="high", execute_after=future),
            Task(id="plain", title="No defer", status="pending",
                 priority="medium"),
        ]
        pending = get_pending(tasks)
        ids = [t.id for t in pending]
        assert "deferred" not in ids
        assert "ready" in ids
        assert "plain" in ids

    def test_execute_after_roundtrip(self):
        future = "2026-05-01T12:00:00+00:00"
        task = Task(
            id="x", title="Scheduled", status="pending",
            execute_after=future, body="details",
        )
        notes = task.to_notes()
        assert f"execute_after: {future}" in notes
        meta, body = parse_frontmatter(notes)
        assert meta["execute_after"] == future
        assert body == "details"

    def test_from_gtask_parses_execute_after(self):
        gtask = {
            "id": "t",
            "title": "[ALERT] Wallet call in 30min",
            "notes": (
                "---\nstatus: pending\n"
                "execute_after: 2026-05-01T12:00:00+00:00\n---\n"
                "Alert body"
            ),
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.execute_after == "2026-05-01T12:00:00+00:00"
        assert task.body == "Alert body"

    def test_defaults_skip_execute_after_field(self):
        """Ordinary tasks must not emit execute_after in frontmatter."""
        task = Task(id="t", title="Ordinary", status="pending")
        notes = task.to_notes()
        assert "execute_after" not in notes

    @patch("tasks.queue._run_gog")
    def test_create_task_wires_execute_after(self, mock_gog):
        from tasks.queue import create_task
        mock_gog.return_value = json.dumps({"task": {"id": "alert-1"}})
        future = "2026-05-01T12:00:00+00:00"
        create_task(
            "[ALERT] Wallet call",
            priority="high",
            source="self",
            execute_after=future,
        )
        call_args = mock_gog.call_args[0]
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert f"execute_after: {future}" in notes_arg


# Regression: 2026-04-23. Wallet preflight [ALERT] task encoded its defer as
# prose in the body ("execute only after T+30min") instead of execute_after.
# The consumer kept firing it early; each run called create_task() with the
# same title, producing 28 duplicate [ALERT] rows + matching [RESULT] cards.
# One session also wrote `-` while the next wrote `—`, so even a strict
# title-hash dedup would have missed half the duplicates.
class TestCreateTaskTitleDedup:
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_skips_identical_pending_title(self, mock_list, mock_gog):
        from tasks.queue import create_task
        mock_list.return_value = [
            Task(id="existing-1", title="[ALERT] Wallet call", status="pending"),
        ]
        tid = create_task("[ALERT] Wallet call", priority="high", source="self")
        assert tid == "existing-1"
        mock_gog.assert_not_called()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_folds_em_dash_to_hyphen(self, mock_list, mock_gog):
        """Title drift `-` -> `—` must not defeat dedup (the 04-23 failure mode)."""
        from tasks.queue import create_task
        mock_list.return_value = [
            Task(
                id="existing-1",
                title="[ALERT] Wallet call 19:00 - Acme preflight",
                status="pending",
            ),
        ]
        tid = create_task(
            "[ALERT] Wallet call 19:00 \u2014 Acme preflight",
            priority="high",
            source="self",
        )
        assert tid == "existing-1"
        mock_gog.assert_not_called()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_is_case_and_whitespace_insensitive(self, mock_list, mock_gog):
        from tasks.queue import create_task
        mock_list.return_value = [
            Task(id="existing-1", title="[ALERT] Wallet Call", status="pending"),
        ]
        tid = create_task("[alert]  wallet   call", priority="high")
        assert tid == "existing-1"
        mock_gog.assert_not_called()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_ignores_completed_siblings(self, mock_list, mock_gog):
        """A completed task with the same title must not block a fresh creation."""
        from tasks.queue import create_task
        mock_list.return_value = [
            Task(id="old-1", title="[ALERT] Wallet call", status="done"),
            Task(id="old-2", title="[ALERT] Wallet call", status="skipped"),
        ]
        mock_gog.return_value = json.dumps({"task": {"id": "new-1"}})
        tid = create_task("[ALERT] Wallet call", priority="high")
        assert tid == "new-1"
        mock_gog.assert_called_once()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_skips_result_cards(self, mock_list, mock_gog):
        """[RESULT] cards are audit trails — duplicates are allowed on purpose."""
        from tasks.queue import create_task
        mock_list.return_value = [
            Task(id="r1", title="[RESULT] Wallet call done", status="pending",
                 type="result"),
        ]
        mock_gog.return_value = json.dumps({"task": {"id": "r2"}})
        tid = create_task("[RESULT] Wallet call done", type="result",
                          priority="low")
        assert tid == "r2"
        mock_gog.assert_called_once()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_false_forces_create(self, mock_list, mock_gog):
        from tasks.queue import create_task
        mock_list.return_value = [
            Task(id="existing-1", title="Same title", status="pending"),
        ]
        mock_gog.return_value = json.dumps({"task": {"id": "fresh-1"}})
        tid = create_task("Same title", priority="medium", dedup=False)
        assert tid == "fresh-1"
        # list_tasks must not be consulted when dedup=False.
        mock_list.assert_not_called()
        mock_gog.assert_called_once()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_survives_snapshot_failure(self, mock_list, mock_gog):
        """Snapshot read failure must not block task creation."""
        from tasks.queue import create_task
        mock_list.side_effect = RuntimeError("snapshot offline")
        mock_gog.return_value = json.dumps({"task": {"id": "fresh-1"}})
        tid = create_task("New task", priority="medium")
        assert tid == "fresh-1"
        mock_gog.assert_called_once()


class TestGetRunning:
    def test_finds_running(self):
        tasks = [
            Task(id="1", title="Pending", status="pending"),
            Task(id="2", title="Running", status="running", started_at="2026-03-11T14:00:00"),
        ]
        running = get_running(tasks)
        assert running is not None
        assert running.title == "Running"

    def test_no_running(self):
        tasks = [
            Task(id="1", title="Pending", status="pending"),
        ]
        assert get_running(tasks) is None

    def test_empty(self):
        assert get_running([]) is None


class TestRunGog:
    @patch("tasks.queue.subprocess.run")
    def test_success(self, mock_run):
        from tasks.queue import _run_gog
        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}')
        result = _run_gog("tasks", "list", "lid123")
        assert result == '{"ok": true}'
        call_args = mock_run.call_args[0][0]
        # _gog_bin() resolves to an absolute path on machines with brew install.
        assert call_args[0].endswith("gog")
        assert "-a" in call_args

    @patch("tasks.queue.subprocess.run")
    def test_failure_raises(self, mock_run):
        from tasks.queue import _run_gog
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        with pytest.raises(RuntimeError, match="failed"):
            _run_gog("tasks", "list", "lid123")


class TestListTasks:
    """list_tasks now reads from tasks.snapshot, so we patch the snapshot's
    underlying gog call rather than queue._run_gog."""

    @patch("tasks.snapshot._gog_call")
    def test_parses_list(self, mock_gog, tmp_path, monkeypatch):
        from tasks import snapshot
        monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
        snapshot.reset_for_tests()
        from tasks.queue import list_tasks
        mock_gog.return_value = json.dumps([
            {"id": "1", "title": "Task 1", "status": "needsAction", "notes": "---\nstatus: pending\n---"},
            {"id": "2", "title": "Task 2", "status": "completed", "notes": ""},
        ])
        tasks = list_tasks(list_id="LID_TEST_PARSES")
        assert len(tasks) == 1
        assert tasks[0].title == "Task 1"

    @patch("tasks.snapshot._gog_call")
    def test_include_completed(self, mock_gog, tmp_path, monkeypatch):
        from tasks import snapshot
        monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
        snapshot.reset_for_tests()
        from tasks.queue import list_tasks
        mock_gog.return_value = json.dumps([
            {"id": "1", "title": "Task", "status": "needsAction"},
            {"id": "2", "title": "Done", "status": "completed"},
        ])
        tasks = list_tasks(list_id="LID_TEST_INCL", include_completed=True)
        assert len(tasks) == 2

    @patch("tasks.snapshot._gog_call")
    def test_dict_response(self, mock_gog, tmp_path, monkeypatch):
        from tasks import snapshot
        monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
        snapshot.reset_for_tests()
        from tasks.queue import list_tasks
        mock_gog.return_value = json.dumps({"items": [
            {"id": "1", "title": "T", "status": "needsAction"}
        ]})
        tasks = list_tasks(list_id="LID_TEST_DICT")
        assert len(tasks) == 1


class TestUpdateTaskNotes:
    @patch("tasks.queue._run_gog")
    def test_calls_gog(self, mock_gog):
        from tasks.queue import update_task_notes
        mock_gog.return_value = ""
        update_task_notes("task123", "---\nstatus: running\n---")
        mock_gog.assert_called_once()
        call_args = mock_gog.call_args[0]
        assert "update" in call_args


class TestCompleteTask:
    @patch("tasks.queue._run_gog")
    def test_calls_gog(self, mock_gog):
        from tasks.queue import complete_task
        mock_gog.return_value = ""
        complete_task("task123")
        mock_gog.assert_called_once()
        call_args = mock_gog.call_args[0]
        assert "done" in call_args


class TestCreateTask:
    @patch("tasks.queue._run_gog")
    def test_basic_create(self, mock_gog):
        from tasks.queue import create_task
        mock_gog.return_value = json.dumps({"task": {"id": "new123"}})
        task_id = create_task("Test task", priority="high", source="chat")
        assert task_id == "new123"

    @patch("tasks.queue._run_gog")
    def test_with_body(self, mock_gog):
        from tasks.queue import create_task
        mock_gog.return_value = json.dumps({"id": "new456"})
        task_id = create_task("Task", body="Details here")
        assert task_id == "new456"

    @patch("tasks.queue._run_gog")
    def test_with_due_and_parent(self, mock_gog):
        from tasks.queue import create_task
        mock_gog.return_value = json.dumps({"task": {"id": "new789"}})
        create_task("Sub task", due="2026-03-20", parent_id="parent1")
        call_args = mock_gog.call_args[0]
        assert "--due" in call_args
        assert "--parent" in call_args

    @patch("tasks.queue._run_gog")
    def test_body_over_notes(self, mock_gog):
        from tasks.queue import create_task
        mock_gog.return_value = json.dumps({"task": {"id": "x"}})
        create_task("Task", notes="old notes", body="body wins")
        call_args = mock_gog.call_args[0]
        # Find the notes arg
        notes_arg = [a for a in call_args if a.startswith("--notes=")]
        assert len(notes_arg) == 1
        assert "body wins" in notes_arg[0]


class TestTaskToNotesWithAllFields:
    def test_with_completed_and_result(self):
        task = Task(
            id="x", title="T", status="done", priority="high",
            source="chat", session_id="s1",
            started_at="2026-03-11T14:00:00",
            completed_at="2026-03-11T15:00:00",
            result="Success",
            body="Original body",
        )
        notes = task.to_notes()
        assert "completed_at" in notes
        assert "result: Success" in notes
        assert "Original body" in notes


# Regression: reject_proposal() used to silently drop the rejection reason,
# so the idle-research loop re-proposed shot-down ideas every hour.
# the user flagged this Apr 19 2026. Fix: persist rejections to JSONL and
# feed recent entries back into the idle-research prompt.
class TestRejectionLog:
    def test_log_rejection_writes_jsonl(self, tmp_path):
        from tasks.queue import log_rejection, Task as T
        path = tmp_path / "rejected.jsonl"
        task = T(
            id="gt-1",
            title="[PROPOSAL] Draft Daniel follow-up",
            type="proposal",
            shape="reply",
            mode_tags="deal,xov",
            priority="medium",
            source="idle_research",
            proposal_plan="1. Open note.\n2. Draft reply.",
        )
        log_rejection(task, reason="Already replied Apr 14")

        assert path.exists() is False  # default path wasn't used
        # use explicit path to verify round-trip
        log_rejection(task, reason="Already replied Apr 14", path=path)
        line = path.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["task_id"] == "gt-1"
        assert rec["title"].startswith("[PROPOSAL]")
        assert rec["reason"] == "Already replied Apr 14"
        assert rec["shape"] == "reply"
        assert rec["mode_tags"] == "deal,xov"
        assert "Draft reply" in rec["plan"]
        assert "rejected_at" in rec

    def test_log_rejection_appends(self, tmp_path):
        from tasks.queue import log_rejection, Task as T
        path = tmp_path / "rejected.jsonl"
        for i in range(3):
            log_rejection(
                T(id=f"gt-{i}", title=f"P{i}", type="proposal"),
                reason=f"r{i}",
                path=path,
            )
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        ids = [json.loads(l)["task_id"] for l in lines]
        assert ids == ["gt-0", "gt-1", "gt-2"]

    def test_recent_rejections_newest_first(self, tmp_path):
        from tasks.queue import log_rejection, recent_rejections, Task as T
        path = tmp_path / "rejected.jsonl"
        for i in range(5):
            log_rejection(
                T(id=f"gt-{i}", title=f"P{i}", type="proposal"),
                reason=f"r{i}",
                path=path,
            )
        recent = recent_rejections(limit=3, path=path)
        assert len(recent) == 3
        # newest first (log appended P0..P4, so newest is P4)
        assert [r["task_id"] for r in recent] == ["gt-4", "gt-3", "gt-2"]

    def test_recent_rejections_filters_old_entries(self, tmp_path):
        from tasks.queue import recent_rejections
        path = tmp_path / "rejected.jsonl"
        old_ts = (datetime.now(timezone.utc).replace(microsecond=0)
                  - timedelta(days=90)).isoformat()
        new_ts = datetime.now(timezone.utc).isoformat()
        path.write_text(
            json.dumps({"rejected_at": old_ts, "task_id": "ancient", "title": "old"}) + "\n"
            + json.dumps({"rejected_at": new_ts, "task_id": "fresh", "title": "new"}) + "\n",
            encoding="utf-8",
        )
        recent = recent_rejections(limit=10, max_days=30, path=path)
        ids = [r["task_id"] for r in recent]
        assert "fresh" in ids
        assert "ancient" not in ids

    def test_recent_rejections_missing_file(self, tmp_path):
        from tasks.queue import recent_rejections
        assert recent_rejections(path=tmp_path / "nope.jsonl") == []

    def test_recent_rejections_skips_malformed_lines(self, tmp_path):
        from tasks.queue import recent_rejections
        path = tmp_path / "rejected.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        path.write_text(
            "not json\n"
            + json.dumps({"rejected_at": now, "task_id": "ok", "title": "ok"}) + "\n"
            + "{broken\n",
            encoding="utf-8",
        )
        recent = recent_rejections(path=path)
        assert len(recent) == 1
        assert recent[0]["task_id"] == "ok"

    def test_reject_proposal_writes_to_log(self, tmp_path, monkeypatch):
        """End-to-end: reject_proposal() persists the rejection."""
        from tasks import queue as q

        log_path = tmp_path / "rejected.jsonl"
        monkeypatch.setattr(q, "REJECTED_PROPOSALS_PATH", log_path)

        fake_task = q.Task(
            id="gt-42",
            title="[PROPOSAL] Something dumb",
            type="proposal",
            proposal_status="pending",
            status="pending",
            shape="act",
            mode_tags="deal",
            body="",
        )
        monkeypatch.setattr(q, "list_tasks", lambda *a, **kw: [fake_task])
        monkeypatch.setattr(q, "update_task_notes", lambda *a, **kw: None)
        monkeypatch.setattr(q, "complete_task", lambda *a, **kw: None)
        monkeypatch.setattr(q, "_list_id", lambda: "list-x")

        out = q.reject_proposal("gt-42", reason="Not now, too early")
        assert out.proposal_status == "rejected"
        assert out.status == "skipped"

        assert log_path.exists(), "rejection log must be persisted"
        rec = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert rec["task_id"] == "gt-42"
        assert rec["reason"] == "Not now, too early"


# Result cards: every finished consumer task produces a [RESULT] card on the
# Deck so the user sees output without digging through TG/Lifeline. Round-trip,
# helper, and filtering behavior all need coverage.
class TestResultCards:
    def test_roundtrip_result_fields(self):
        task = Task(
            id="r-1",
            title="[RESULT] AcmeCorp status",
            type="result",
            result_of="gt-parent-99",
            result_status="new",
            dispatch="self",
            priority="low",
            source="consumer",
            body="## What was done\nChecked invoice\n",
        )
        notes = task.to_notes()
        meta, body = parse_frontmatter(notes)
        assert meta["type"] == "result"
        assert meta["result_of"] == "gt-parent-99"
        assert meta["result_status"] == "new"
        assert meta["dispatch"] == "self"
        assert "What was done" in body

    def test_from_gtask_parses_result(self):
        gtask = {
            "id": "r-2",
            "title": "[RESULT] Pulse digest",
            "notes": (
                "---\n"
                "status: pending\n"
                "type: result\n"
                "result_of: gt-9\n"
                "result_status: new\n"
                "dispatch: self\n"
                "---\n"
                "Digest body"
            ),
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.type == "result"
        assert task.result_of == "gt-9"
        assert task.result_status == "new"
        assert task.dispatch == "self"
        assert task.body == "Digest body"

    def test_defaults_skip_result_fields(self):
        """Ordinary tasks must not emit result_of / result_status in frontmatter."""
        task = Task(id="t", title="Ordinary", status="pending")
        notes = task.to_notes()
        assert "result_of" not in notes
        assert "result_status" not in notes
        assert "type:" not in notes  # default type=task is suppressed

    def test_get_pending_excludes_result_cards(self):
        """Consumer must never 'execute' a [RESULT] informational card."""
        tasks = [
            Task(id="t1", title="Real task", status="pending", priority="high"),
            Task(
                id="r1", title="[RESULT] done",
                status="pending", type="result",
                result_of="t-parent", result_status="new",
            ),
        ]
        pending = get_pending(tasks)
        assert [t.id for t in pending] == ["t1"]

    @patch("tasks.queue._run_gog")
    def test_create_result_wires_fields(self, mock_gog):
        from tasks.queue import create_result
        mock_gog.return_value = json.dumps({"task": {"id": "r-new"}})
        rid = create_result(
            parent_task_id="gt-parent-123",
            title="AcmeCorp invoicing",
            body="## What was done\nDrafted email.\n",
            shape="reply",
            mode_tags=["deal", "acmecorp"],
        )
        assert rid == "r-new"

        call_args = mock_gog.call_args[0]
        # Title must be prefixed
        title_idx = call_args.index("--title")
        assert call_args[title_idx + 1] == "[RESULT] AcmeCorp invoicing"
        # Notes must carry type=result + result_of backref
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert "type: result" in notes_arg
        assert "result_of: gt-parent-123" in notes_arg
        assert "result_status: new" in notes_arg
        assert "dispatch: self" in notes_arg
        assert "mode_tags: deal,acmecorp" in notes_arg
        assert "What was done" in notes_arg

    @patch("tasks.queue._run_gog")
    def test_create_result_respects_existing_tag(self, mock_gog):
        from tasks.queue import create_result
        mock_gog.return_value = json.dumps({"task": {"id": "r-x"}})
        create_result(
            parent_task_id="p-1",
            title="[RESULT] Already tagged",
            body="body",
        )
        call_args = mock_gog.call_args[0]
        title_idx = call_args.index("--title")
        # Must not double-prefix
        assert call_args[title_idx + 1] == "[RESULT] Already tagged"


# In-place conversion: Deck's Delegate/Proposal flow mutates the dispatched
# [ACTION] / [RESEARCH] row into a [RESULT] / [PROPOSAL] card keeping the same
# GTask id, so the user sees one card evolve instead of two.
class TestConvertInPlace:
    def _fake_task(self, **overrides):
        from tasks.queue import Task
        base = dict(
            id="gt-action-1",
            title="[ACTION] Reply to Bob",
            type="task",
            status="running",
            priority="medium",
            source="chat",
            body="## Source GTask\nid: gt-src-9\n",
        )
        base.update(overrides)
        return Task(**base)

    @patch("tasks.queue._run_gog")
    def test_convert_to_result_rewrites_title_and_type(self, mock_gog, monkeypatch):
        from tasks import queue as q
        mock_gog.return_value = ""
        monkeypatch.setattr(q, "list_tasks", lambda *a, **kw: [self._fake_task()])
        monkeypatch.setattr(q, "_list_id", lambda: "list-x")
        monkeypatch.setattr(q._snapshot, "apply_local_mutation", lambda *a, **kw: None)

        updated = q.convert_to_result(
            task_id="gt-action-1",
            body="## What was done\nReplied\n",
            mode_tags=["deal"],
            session_id="sess-42",
        )

        assert updated.id == "gt-action-1"
        assert updated.title == "[RESULT] Reply to Bob"
        assert updated.type == "result"
        assert updated.dispatch == "self"
        assert updated.result_status == "new"
        assert updated.status == "pending"
        assert updated.session_id == "sess-42"

        # gog invocation must be an update call (not create, not done)
        call_args = mock_gog.call_args[0]
        assert "update" in call_args
        assert "gt-action-1" in call_args
        title_idx = call_args.index("--title=[RESULT] Reply to Bob")
        assert title_idx >= 0
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert "type: result" in notes_arg
        assert "dispatch: self" in notes_arg
        assert "result_status: new" in notes_arg
        assert "#result" in notes_arg
        assert "What was done" in notes_arg

    @patch("tasks.queue._run_gog")
    def test_convert_to_result_strips_any_tag_prefix(self, mock_gog, monkeypatch):
        from tasks import queue as q
        mock_gog.return_value = ""
        fake = self._fake_task(title="[RESEARCH] Whatever")
        monkeypatch.setattr(q, "list_tasks", lambda *a, **kw: [fake])
        monkeypatch.setattr(q, "_list_id", lambda: "list-x")
        monkeypatch.setattr(q._snapshot, "apply_local_mutation", lambda *a, **kw: None)

        updated = q.convert_to_result(task_id="gt-action-1", body="done")
        # Any existing [TAG] prefix is dropped before the [RESULT] re-prefix.
        assert updated.title == "[RESULT] Whatever"

    @patch("tasks.queue._run_gog")
    def test_convert_to_proposal_rewrites_title_and_sets_plan(self, mock_gog, monkeypatch):
        from tasks import queue as q
        mock_gog.return_value = ""
        fake = self._fake_task(title="[RESEARCH] Draft XOV deck")
        monkeypatch.setattr(q, "list_tasks", lambda *a, **kw: [fake])
        monkeypatch.setattr(q, "_list_id", lambda: "list-x")
        monkeypatch.setattr(q._snapshot, "apply_local_mutation", lambda *a, **kw: None)

        updated = q.convert_to_proposal(
            task_id="gt-action-1",
            plan="step 1\nstep 2",
            shape="review",
        )

        assert updated.title == "[PROPOSAL] Draft XOV deck"
        assert updated.type == "proposal"
        assert updated.proposal_status == "pending"
        assert updated.dispatch == "session"
        assert updated.shape == "review"
        assert updated.status == "pending"
        assert "step 1" in (updated.proposal_plan or "")

        call_args = mock_gog.call_args[0]
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert "type: proposal" in notes_arg
        assert "proposal_status: pending" in notes_arg
        assert "## Plan" in notes_arg

    @patch("tasks.queue._run_gog")
    def test_convert_raises_when_task_missing(self, mock_gog, monkeypatch):
        from tasks import queue as q
        monkeypatch.setattr(q, "list_tasks", lambda *a, **kw: [])
        monkeypatch.setattr(q, "_list_id", lambda: "list-x")
        try:
            q.convert_to_result(task_id="gt-missing", body="x")
        except ValueError as e:
            assert "gt-missing" in str(e)
        else:
            raise AssertionError("expected ValueError for missing task")
