"""Tests for tasks/queue.py - frontmatter parsing, Task model, queue operations."""

import json
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch, MagicMock

from tasks import snapshot as _snapshot_module
from tasks.queue import (
    parse_frontmatter,
    build_frontmatter,
    Task,
    get_pending,
    get_running,
    PRIORITY_ORDER,
)


@pytest.fixture(autouse=True)
def _isolate_snapshot(tmp_path, monkeypatch):
    """Redirect snapshot files to tmp_path so tests never pollute the production
    snapshot at /tmp/klava-snapshot-<real_list_id>.json.

    Regression: 2026-04-24 — create_task tests mocked _run_gog but NOT
    _snapshot.apply_local_insert, so every test run inserted phantom tasks
    (alert-1, new-1, r2, fresh-1 …) into the live snapshot, blocking the
    consumer with 400 badRequest on every 5-min tick.
    """
    monkeypatch.setattr(_snapshot_module, "SNAPSHOT_DIR", tmp_path)
    _snapshot_module.reset_for_tests()


@pytest.fixture(autouse=True)
def _stub_llm_matcher(monkeypatch, request):
    """Stub the LLM topic matcher so tests don't spawn `claude` CLI.

    Returning [] forces _find_topic_match to fall back to token-Jaccard,
    which is what the existing tests were written against. Tests that want
    LLM behavior should patch `tasks.llm_matcher.topic_matches_llm` directly.

    Skips for `TestLLMMatcherUnit`, which exercises the matcher's own
    subprocess plumbing and needs the real function reference.
    """
    cls = getattr(request.node, "cls", None)
    if cls is not None and cls.__name__ == "TestLLMMatcherUnit":
        yield
        return
    from tasks import llm_matcher
    monkeypatch.setattr(llm_matcher, "topic_matches_llm",
                        lambda *args, **kwargs: [])
    yield


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


# Regression: 2026-05-05. The Deck accumulated 67 pending [PROPOSAL] cards
# because heartbeat re-emitted paraphrased duplicates ("Reply Karl Fisox -
# clarify code deal" vs "Karl - which unlicensed code deal") and the
# rejection-only dedup couldn't see them. Fix 1 wires the same LLM matcher
# used by `_find_topic_match` (for [RESULT] cards) into `create_task`,
# scoped to non-result types from automated sources.
class TestCreateTaskLLMTopicDedup:
    def _now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_llm_match_against_pending_proposal_skips_create(
        self, mock_list, mock_gog, monkeypatch,
    ):
        """A heartbeat-sourced proposal whose title paraphrases an existing
        pending proposal must reuse the existing card, not create a new row."""
        from tasks.queue import create_task
        from tasks import llm_matcher
        existing = Task(
            id="prop-1",
            title="[PROPOSAL] Reply Karl Fisox - clarify which unlicensed code deal",
            status="pending",
            type="proposal",
            created=self._now_iso(),
        )
        mock_list.return_value = [existing]
        # Force the LLM matcher to return prop-1 as a same-topic match.
        monkeypatch.setattr(
            llm_matcher, "topic_matches_llm",
            lambda new, candidates, **kw: ["prop-1"],
        )
        tid = create_task(
            "[PROPOSAL] Karl - which unlicensed code deal he meant",
            type="proposal",
            source="heartbeat",
        )
        assert tid == "prop-1"
        mock_gog.assert_not_called()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_llm_match_against_recently_completed_skips_create(
        self, mock_list, mock_gog, monkeypatch,
    ):
        """If the user already completed a same-topic proposal in the last
        48h, the next heartbeat must not resurrect it."""
        from tasks.queue import create_task
        from tasks import llm_matcher
        recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        existing = Task(
            id="done-1",
            title="[PROPOSAL] Reply Jack McGrath - schedule fresh slots",
            status="done",
            type="proposal",
            created=recent,
            completed_at=recent,
        )
        mock_list.return_value = [existing]
        monkeypatch.setattr(
            llm_matcher, "topic_matches_llm",
            lambda new, candidates, **kw: ["done-1"],
        )
        tid = create_task(
            "[PROPOSAL] Monda.ai - send Jack McGrath reply with fresh slots",
            type="proposal",
            source="heartbeat",
        )
        # Returns the existing done id; no new card created.
        assert tid == "done-1"
        mock_gog.assert_not_called()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_old_completed_proposal_does_not_block(
        self, mock_list, mock_gog, monkeypatch,
    ):
        """A proposal completed more than 48h ago must not block a fresh one
        — too much time has passed; the topic may legitimately resurface."""
        from tasks.queue import create_task
        from tasks import llm_matcher
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        existing = Task(
            id="old-1",
            title="[PROPOSAL] Reply Jack McGrath - schedule fresh slots",
            status="done",
            type="proposal",
            created=old,
            completed_at=old,
        )
        mock_list.return_value = [existing]
        monkeypatch.setattr(
            llm_matcher, "topic_matches_llm",
            lambda new, candidates, **kw: ["old-1"],
        )
        mock_gog.return_value = json.dumps({"task": {"id": "fresh-1"}})
        tid = create_task(
            "[PROPOSAL] Reply Jack McGrath again - new opening",
            type="proposal",
            source="heartbeat",
        )
        assert tid == "fresh-1"
        mock_gog.assert_called_once()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_user_driven_source_bypasses_llm_dedup(
        self, mock_list, mock_gog, monkeypatch,
    ):
        """Tasks the user explicitly typed (chat/manual) must not be silently
        merged into a same-topic predecessor — the user knows what they want."""
        from tasks.queue import create_task
        from tasks import llm_matcher
        existing = Task(
            id="prop-1",
            title="[PROPOSAL] Reply Karl",
            status="pending",
            type="proposal",
            created=self._now_iso(),
        )
        mock_list.return_value = [existing]
        called = {"n": 0}

        def fake_matcher(*args, **kwargs):
            called["n"] += 1
            return ["prop-1"]

        monkeypatch.setattr(llm_matcher, "topic_matches_llm", fake_matcher)
        mock_gog.return_value = json.dumps({"task": {"id": "fresh-1"}})
        tid = create_task(
            "Karl follow-up - different angle",
            type="task",
            source="chat",
        )
        # Fresh row created; LLM matcher never invoked for user-driven source.
        assert tid == "fresh-1"
        assert called["n"] == 0
        mock_gog.assert_called_once()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_llm_dedup_skipped_for_result_type(
        self, mock_list, mock_gog, monkeypatch,
    ):
        """Result cards have their own dedup path (_find_topic_match);
        the open-topic helper must not interfere."""
        from tasks.queue import create_task
        from tasks import llm_matcher
        called = {"n": 0}

        def fake_matcher(*args, **kwargs):
            called["n"] += 1
            return []

        monkeypatch.setattr(llm_matcher, "topic_matches_llm", fake_matcher)
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "r1"}})
        tid = create_task("[RESULT] Some result", type="result", source="consumer")
        assert tid == "r1"
        # LLM dedup branch is skipped for type=result.
        assert called["n"] == 0

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_disable_env_var_bypasses_llm_dedup(
        self, mock_list, mock_gog, monkeypatch,
    ):
        """KLAVA_DISABLE_LLM_DEDUP=1 must short-circuit the LLM path so the
        system can run without claude CLI in emergencies."""
        from tasks.queue import create_task
        from tasks import llm_matcher
        existing = Task(
            id="prop-1",
            title="[PROPOSAL] Reply Karl",
            status="pending",
            type="proposal",
            created=self._now_iso(),
        )
        mock_list.return_value = [existing]
        called = {"n": 0}

        def fake_matcher(*args, **kwargs):
            called["n"] += 1
            return ["prop-1"]

        monkeypatch.setattr(llm_matcher, "topic_matches_llm", fake_matcher)
        monkeypatch.setenv("KLAVA_DISABLE_LLM_DEDUP", "1")
        mock_gog.return_value = json.dumps({"task": {"id": "fresh-1"}})
        tid = create_task(
            "[PROPOSAL] Karl - other topic",
            type="proposal",
            source="heartbeat",
        )
        assert tid == "fresh-1"
        assert called["n"] == 0


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


# Regression: 2026-04-30 — `[PROPOSAL] Draft Daniel follow-up` was rejected
# 4 times in 3 days (Apr 27, Apr 30 x3) with identical reason
# "Already replied Apr 14". Idle-research already inject the rejection log into
# the prompt, but the LLM kept resurfacing the same idea anyway. The fix is
# enforcement at the create_proposal() layer: if the normalized title matches a
# recent rejection, skip creation entirely.
class TestProposalRejectionDedup:
    def test_is_recently_rejected_normalized_match(self, tmp_path):
        from tasks.queue import is_recently_rejected, log_rejection, Task as T
        path = tmp_path / "rejected.jsonl"
        log_rejection(
            T(id="gt-1", title="[PROPOSAL] Draft Daniel follow-up", type="proposal"),
            reason="Already replied Apr 14",
            path=path,
        )
        # exact title
        m = is_recently_rejected("[PROPOSAL] Draft Daniel follow-up", path=path)
        assert m is not None
        assert m["task_id"] == "gt-1"
        # title without prefix
        m = is_recently_rejected("Draft Daniel follow-up", path=path)
        assert m is not None
        # case + whitespace drift
        m = is_recently_rejected("[PROPOSAL]  draft   daniel  Follow-up  ", path=path)
        assert m is not None

    def test_is_recently_rejected_no_match(self, tmp_path):
        from tasks.queue import is_recently_rejected, log_rejection, Task as T
        path = tmp_path / "rejected.jsonl"
        log_rejection(
            T(id="gt-1", title="[PROPOSAL] Reply to Bogdan", type="proposal"),
            reason="not now",
            path=path,
        )
        assert is_recently_rejected("[PROPOSAL] Draft Daniel follow-up", path=path) is None

    def test_is_recently_rejected_window_expires(self, tmp_path):
        from tasks.queue import is_recently_rejected, recent_rejections
        path = tmp_path / "rejected.jsonl"
        old_ts = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        path.write_text(
            json.dumps({
                "rejected_at": old_ts,
                "task_id": "gt-old",
                "title": "[PROPOSAL] Stale idea",
                "reason": "not interested",
            }) + "\n",
            encoding="utf-8",
        )
        # outside the default 14d window AND reason is not permanent
        assert is_recently_rejected("[PROPOSAL] Stale idea", days=14, path=path) is None
        # widening the window picks it back up
        assert is_recently_rejected("[PROPOSAL] Stale idea", days=30, path=path) is not None

    def test_permanent_reject_extends_window(self, tmp_path):
        """Reasons like 'already replied' keep the dedup live for 90 days."""
        from tasks.queue import is_recently_rejected
        path = tmp_path / "rejected.jsonl"
        old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        path.write_text(
            json.dumps({
                "rejected_at": old_ts,
                "task_id": "gt-perm",
                "title": "[PROPOSAL] Draft Daniel follow-up",
                "reason": "Already replied Apr 14",
            }) + "\n",
            encoding="utf-8",
        )
        # 14d window — but permanent-reject phrase widens to 90d
        m = is_recently_rejected("[PROPOSAL] Draft Daniel follow-up", days=14, path=path)
        assert m is not None
        assert m["task_id"] == "gt-perm"

    def test_create_proposal_skipped_when_recently_rejected(self, tmp_path, monkeypatch, capsys):
        """End-to-end: create_proposal() refuses to mint a duplicate of a
        recently-rejected idea, even if the caller (idle_research / heartbeat)
        ignores the rejection log injected into its prompt."""
        from tasks import queue as q

        log_path = tmp_path / "rejected.jsonl"
        monkeypatch.setattr(q, "REJECTED_PROPOSALS_PATH", log_path)

        q.log_rejection(
            q.Task(
                id="gt-1",
                title="[PROPOSAL] Draft Daniel follow-up",
                type="proposal",
                shape="reply",
                mode_tags="deal,xov",
                source="idle_research",
                proposal_plan="1. Open note. 2. Draft reply.",
            ),
            reason="Already replied Apr 14",
            path=log_path,
        )

        # If create_task is called, the dedup guard failed.
        called = {}
        def fake_create_task(**kwargs):
            called["title"] = kwargs.get("title")
            return "should-not-happen"
        monkeypatch.setattr(q, "create_task", fake_create_task)

        out = q.create_proposal(
            title="Draft Daniel follow-up",
            plan="1. Open note. 2. Draft reply.",
            shape="reply",
            mode_tags=["deal", "xov"],
        )
        assert out == "", "create_proposal must return empty when matching rejection"
        assert "title" not in called, "create_task must NOT be invoked for a recently-rejected title"
        err = capsys.readouterr().err
        assert "dedup-rejection" in err

    def test_create_proposal_passes_through_when_no_match(self, tmp_path, monkeypatch):
        """A genuinely new proposal still gets created — guard isn't a global mute."""
        from tasks import queue as q

        log_path = tmp_path / "rejected.jsonl"
        monkeypatch.setattr(q, "REJECTED_PROPOSALS_PATH", log_path)

        q.log_rejection(
            q.Task(id="gt-1", title="[PROPOSAL] Old thing", type="proposal"),
            reason="no",
            path=log_path,
        )

        seen = {}
        def fake_create_task(**kwargs):
            seen["title"] = kwargs.get("title")
            return "gt-new"
        monkeypatch.setattr(q, "create_task", fake_create_task)

        out = q.create_proposal(title="Brand new idea", plan="do the thing", shape="act")
        assert out == "gt-new"
        assert seen["title"] == "[PROPOSAL] Brand new idea"


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


# Topic-level dedup for [RESULT] cards. Heartbeat re-emits the same observation
# each cycle and the consumer adds another card for the same parent — the Deck
# ends up with multiple cards on one topic ("10 cards about the same thing",
# 2026-04-25). create_result() now collapses these by appending an Update
# section to the existing card or skipping when the user already acked it.
class TestResultTopicDedup:
    def _now_iso(self, hours_ago=0):
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_topic_match_pending_appends_update(self, mock_list, mock_gog):
        from tasks.queue import create_result
        existing = Task(
            id="r-old",
            title="[RESULT] Vladislav - parents aging",
            type="result",
            status="pending",
            result_status="new",
            created=self._now_iso(hours_ago=2),
            body="#result\n\nOriginal context.",
        )
        # Two list_tasks calls: one in _find_topic_match (include_completed=True),
        # one in _append_to_result (include_completed=False).
        mock_list.return_value = [existing]
        rid = create_result(
            parent_task_id=None,
            title="Reply to Vladislav - parents aging (TG)",
            body="## What was done\nDrafted reply.",
        )
        assert rid == "r-old"
        # Must NOT have created a new task (no `tasks add` call).
        add_calls = [c for c in mock_gog.call_args_list
                     if len(c.args) > 1 and c.args[1] == "add"]
        assert add_calls == []
        # Must have updated the existing task notes (one `tasks update` call).
        update_calls = [c for c in mock_gog.call_args_list
                        if len(c.args) > 1 and c.args[1] == "update"]
        assert len(update_calls) == 1
        update_args = update_calls[0].args
        notes_arg = next(a for a in update_args if a.startswith("--notes="))
        # New body appended under an Update section.
        assert "## Update" in notes_arg
        assert "Drafted reply." in notes_arg
        # Original body preserved.
        assert "Original context." in notes_arg
        # result_status bumped back to "new" so Deck re-surfaces it.
        assert "result_status: new" in notes_arg

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_topic_match_recent_completed_skips(self, mock_list, mock_gog):
        from tasks.queue import create_result
        existing = Task(
            id="r-acked",
            title="[RESULT] Eldil AI NCNDA - sign DocuSign",
            type="result",
            status="done",
            result_status="new",
            created=self._now_iso(hours_ago=10),
            completed_at=self._now_iso(hours_ago=4),
            body="#result\n\nNCNDA context.",
        )
        mock_list.return_value = [existing]
        rid = create_result(
            parent_task_id=None,
            title="Sign Eldil AI NCNDA - DocuSign link ready",
            body="## What was done\nSigned.",
        )
        assert rid == "r-acked"
        # No writes at all — user already acked the topic.
        write_calls = [c for c in mock_gog.call_args_list
                       if len(c.args[0]) > 1
                       and c.args[0][1] in ("add", "update", "done")]
        assert write_calls == []

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_no_topic_match_creates_fresh(self, mock_list, mock_gog):
        from tasks.queue import create_result
        existing = Task(
            id="r-other",
            title="[RESULT] HighTower - reschedule call with Ilya",
            type="result",
            status="pending",
            result_status="new",
            created=self._now_iso(hours_ago=1),
        )
        mock_list.return_value = [existing]
        mock_gog.return_value = json.dumps({"task": {"id": "r-fresh"}})
        rid = create_result(
            parent_task_id=None,
            title="Sign Eldil AI NCNDA - DocuSign link ready",
            body="## What was done\nSigned.",
        )
        assert rid == "r-fresh"
        add_calls = [c for c in mock_gog.call_args_list
                     if len(c.args) > 1 and c.args[1] == "add"]
        assert len(add_calls) == 1

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_dedup_topic_false_forces_fresh(self, mock_list, mock_gog):
        """Pulse and other periodic digests opt out — always want a fresh card."""
        from tasks.queue import create_result
        existing = Task(
            id="r-old-pulse",
            title="[RESULT] Pulse digest tech AI HackerNews",
            type="result",
            status="pending",
            result_status="new",
            created=self._now_iso(hours_ago=6),
        )
        mock_list.return_value = [existing]
        mock_gog.return_value = json.dumps({"task": {"id": "r-pulse-new"}})
        rid = create_result(
            parent_task_id=None,
            title="Pulse digest tech AI HackerNews",
            body="## Digest\nFresh content.",
            dedup_topic=False,
        )
        assert rid == "r-pulse-new"
        # list_tasks must not be consulted when dedup_topic=False.
        mock_list.assert_not_called()
        add_calls = [c for c in mock_gog.call_args_list
                     if len(c.args) > 1 and c.args[1] == "add"]
        assert len(add_calls) == 1

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_topic_match_via_same_parent(self, mock_list, mock_gog):
        """Same explicit parent task wins over title heuristic — guaranteed match."""
        from tasks.queue import create_result
        existing = Task(
            id="r-parent-match",
            title="[RESULT] Totally different wording",
            type="result",
            status="pending",
            result_of="gt-parent-99",
            result_status="new",
            created=self._now_iso(hours_ago=1),
            body="#result\n\nFirst report.",
        )
        mock_list.return_value = [existing]
        rid = create_result(
            parent_task_id="gt-parent-99",
            title="Another summary entirely",
            body="## What was done\nFollow-up work.",
        )
        assert rid == "r-parent-match"
        add_calls = [c for c in mock_gog.call_args_list
                     if len(c.args) > 1 and c.args[1] == "add"]
        assert add_calls == []
        update_calls = [c for c in mock_gog.call_args_list
                        if len(c.args) > 1 and c.args[1] == "update"]
        assert len(update_calls) == 1

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_topic_match_outside_window_creates_fresh(self, mock_list, mock_gog):
        """Old RESULT cards (>7 days) don't block a fresh card on the same topic."""
        from tasks.queue import create_result
        old = Task(
            id="r-stale",
            title="[RESULT] Vladislav - parents aging",
            type="result",
            status="pending",
            result_status="new",
            created=self._now_iso(hours_ago=24 * 30),  # 30 days old
        )
        mock_list.return_value = [old]
        mock_gog.return_value = json.dumps({"task": {"id": "r-renewed"}})
        rid = create_result(
            parent_task_id=None,
            title="Reply to Vladislav - parents aging again",
            body="## What was done\nNew reply.",
        )
        assert rid == "r-renewed"
        add_calls = [c for c in mock_gog.call_args_list
                     if len(c.args) > 1 and c.args[1] == "add"]
        assert len(add_calls) == 1


class TestTopicSimilarity:
    def test_real_world_match_pairs(self):
        from tasks.queue import _topic_similar
        match_pairs = [
            ("[RESULT] Eldil AI NCNDA - review + sign DocuSign",
             "[RESULT] Sign Eldil AI NCNDA - DocuSign link ready"),
            ("[RESULT] HighTower - reschedule call with Ilya",
             "[RESULT] HighTower - TG reschedule msg to Ilya"),
            ("[RESULT] Reply to Vladislav - parents aging (TG)",
             "[RESULT] Vladislav - parents aging (late night)"),
        ]
        for a, b in match_pairs:
            assert _topic_similar(a, b), f"expected match: {a!r} vs {b!r}"

    def test_real_world_non_match_pairs(self):
        from tasks.queue import _topic_similar
        non_match_pairs = [
            ("[RESULT] HighTower - reschedule call with Ilya",
             "[RESULT] Sign Eldil AI NCNDA"),
            ("[RESULT] Pulse - Apr 24, 14:00 EET",
             "[RESULT] Pulse - Apr 24, 20:00 EET"),
            ("[RESULT] Reply to Shawn Schneider on call time",
             "[RESULT] SF in-person with Shawn Schneider"),
        ]
        for a, b in non_match_pairs:
            assert not _topic_similar(a, b), f"expected NO match: {a!r} vs {b!r}"


# LLM-as-matcher: when token Jaccard misses real same-topic pairs (different
# verbs, different languages, single shared entity), the LLM picks them up.
# `_find_topic_match` calls `tasks.llm_matcher.topic_matches_llm` first and
# only falls back to token similarity when the LLM call fails or returns [].
class TestLLMMatcherIntegration:
    def _now_iso(self, hours_ago=0):
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()

    @patch("tasks.llm_matcher.topic_matches_llm")
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_llm_match_overrides_token_miss(self, mock_list, mock_gog, mock_llm):
        """LLM catches a same-topic pair that token Jaccard would miss."""
        from tasks.queue import create_result
        existing = Task(
            id="r-llm-only",
            title="[RESULT] Physical Intelligence - review pitch memo",
            type="result",
            status="pending",
            result_status="new",
            created=self._now_iso(hours_ago=2),
            body="#result\n\nPitch memo draft.",
        )
        mock_list.return_value = [existing]
        # Token matcher would fail; LLM returns the match.
        mock_llm.return_value = ["r-llm-only"]
        rid = create_result(
            parent_task_id=None,
            title="Draft Physical Intelligence XOV force sensing pitch memo",
            body="## What was done\nAdded XOV details.",
        )
        assert rid == "r-llm-only"
        # Verify LLM was consulted with the right shape.
        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args
        candidates = call_kwargs.args[1] if len(call_kwargs.args) > 1 else \
                     call_kwargs.kwargs.get("candidates")
        assert any(cid == "r-llm-only" for cid, _ in candidates)
        # Update path, not new task add.
        add_calls = [c for c in mock_gog.call_args_list
                     if len(c.args) > 1 and c.args[1] == "add"]
        assert add_calls == []

    @patch("tasks.llm_matcher.topic_matches_llm")
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_llm_returns_none_falls_back_to_token(self, mock_list, mock_gog, mock_llm):
        """When LLM says 'NONE' (returns []), token similarity still runs."""
        from tasks.queue import create_result
        existing = Task(
            id="r-token",
            title="[RESULT] Reply to Vladislav - parents aging (TG)",
            type="result",
            status="pending",
            result_status="new",
            created=self._now_iso(hours_ago=2),
            body="#result\n\nReply drafted.",
        )
        mock_list.return_value = [existing]
        mock_llm.return_value = []  # LLM said no match
        rid = create_result(
            parent_task_id=None,
            title="Vladislav - parents aging (late night follow-up)",
            body="## What was done\nFurther context.",
        )
        # Token Jaccard finds it (vladislav, parents, aging shared).
        assert rid == "r-token"

    @patch("tasks.llm_matcher.topic_matches_llm")
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_same_parent_skips_llm_call(self, mock_list, mock_gog, mock_llm):
        """Same explicit parent wins outright — no LLM call needed."""
        from tasks.queue import create_result
        existing = Task(
            id="r-parent",
            title="[RESULT] Totally different wording",
            type="result",
            status="pending",
            result_of="gt-parent-77",
            result_status="new",
            created=self._now_iso(hours_ago=1),
        )
        mock_list.return_value = [existing]
        rid = create_result(
            parent_task_id="gt-parent-77",
            title="Different title entirely",
            body="## What was done\nWork.",
        )
        assert rid == "r-parent"
        mock_llm.assert_not_called()


class TestLLMMatcherUnit:
    """Unit tests for tasks.llm_matcher — parsing, caching, no subprocess."""

    def test_parses_comma_separated_indices(self, monkeypatch, tmp_path):
        from tasks import llm_matcher

        monkeypatch.setattr(llm_matcher, "CACHE_DIR", tmp_path)

        class FakeResult:
            returncode = 0
            stdout = "1, 3"
            stderr = ""

        monkeypatch.setattr(llm_matcher.subprocess, "run",
                            lambda *a, **kw: FakeResult())
        candidates = [("a", "Apple"), ("b", "Banana"), ("c", "Cherry")]
        out = llm_matcher.topic_matches_llm("fruit basket", candidates)
        assert out == ["a", "c"]

    def test_handles_none_output(self, monkeypatch, tmp_path):
        from tasks import llm_matcher

        monkeypatch.setattr(llm_matcher, "CACHE_DIR", tmp_path)

        class FakeResult:
            returncode = 0
            stdout = "NONE"
            stderr = ""

        monkeypatch.setattr(llm_matcher.subprocess, "run",
                            lambda *a, **kw: FakeResult())
        out = llm_matcher.topic_matches_llm("foo", [("a", "x"), ("b", "y")])
        assert out == []

    def test_subprocess_failure_returns_empty(self, monkeypatch, tmp_path):
        from tasks import llm_matcher

        monkeypatch.setattr(llm_matcher, "CACHE_DIR", tmp_path)

        class FakeResult:
            returncode = 1
            stdout = ""
            stderr = "auth error"

        monkeypatch.setattr(llm_matcher.subprocess, "run",
                            lambda *a, **kw: FakeResult())
        out = llm_matcher.topic_matches_llm("foo", [("a", "x")])
        assert out == []

    def test_timeout_returns_empty(self, monkeypatch, tmp_path):
        from tasks import llm_matcher

        monkeypatch.setattr(llm_matcher, "CACHE_DIR", tmp_path)

        def boom(*a, **kw):
            raise llm_matcher.subprocess.TimeoutExpired(cmd="claude", timeout=1)

        monkeypatch.setattr(llm_matcher.subprocess, "run", boom)
        out = llm_matcher.topic_matches_llm("foo", [("a", "x")])
        assert out == []

    def test_cache_hit_avoids_subprocess(self, monkeypatch, tmp_path):
        from tasks import llm_matcher

        monkeypatch.setattr(llm_matcher, "CACHE_DIR", tmp_path)

        class FakeResult:
            returncode = 0
            stdout = "1"
            stderr = ""

        call_count = {"n": 0}

        def fake_run(*a, **kw):
            call_count["n"] += 1
            return FakeResult()

        monkeypatch.setattr(llm_matcher.subprocess, "run", fake_run)
        candidates = [("x", "first")]
        a = llm_matcher.topic_matches_llm("topic", candidates)
        b = llm_matcher.topic_matches_llm("topic", candidates)
        assert a == ["x"]
        assert b == ["x"]
        assert call_count["n"] == 1  # second call was a cache hit

    def test_empty_candidates_short_circuits(self, monkeypatch, tmp_path):
        from tasks import llm_matcher

        monkeypatch.setattr(llm_matcher, "CACHE_DIR", tmp_path)
        # subprocess.run should never be called for empty input.
        monkeypatch.setattr(llm_matcher.subprocess, "run",
                            lambda *a, **kw: pytest.fail("should not run"))
        out = llm_matcher.topic_matches_llm("topic", [])
        assert out == []


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
        fake = self._fake_task(title="[RESEARCH] Draft Sentinel deck")
        monkeypatch.setattr(q, "list_tasks", lambda *a, **kw: [fake])
        monkeypatch.setattr(q, "_list_id", lambda: "list-x")
        monkeypatch.setattr(q._snapshot, "apply_local_mutation", lambda *a, **kw: None)

        updated = q.convert_to_proposal(
            task_id="gt-action-1",
            plan="step 1\nstep 2",
            shape="review",
        )

        assert updated.title == "[PROPOSAL] Draft Sentinel deck"
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


# Regression: 2026-04-25 - the documented executor routing shape called
# `create_task(title="[PROPOSAL] ...", priority="high", source="consumer",
# body=...)` without `type="proposal"`. The row landed with default
# `type="task"`, slipped past `get_pending()`'s proposal filter, and the
# consumer re-spawned an executor on it. Concrete repro: GTask
# ZmpVa2diYlVlU0RZQXcxRw ("[PROPOSAL] TG reply to Andrew (0xwasian) -
# propose call slots") was re-executed on Apr 25 ~20:00 EEST.
class TestProposalTitleGuard:
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_create_task_forces_proposal_type_from_title(
        self, mock_list, mock_gog
    ):
        """Legacy doctrine call shape must still produce a proposal row."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "p-1"}})
        create_task(
            "[PROPOSAL] TG reply to Andrew - propose call slots",
            priority="high",
            source="consumer",
            body="## Draft\nHey Andrew, here are some slots ...",
        )
        call_args = mock_gog.call_args[0]
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert "type: proposal" in notes_arg
        assert "proposal_status: pending" in notes_arg

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_create_task_respects_explicit_non_default_type(
        self, mock_list, mock_gog
    ):
        """An explicit `type=` other than "task" must not be overridden by
        the title prefix - lets a caller emit a proposal-titled result/etc.
        if they really mean to."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "x-1"}})
        create_task(
            "[PROPOSAL] something",
            priority="low",
            source="consumer",
            type="result",
        )
        call_args = mock_gog.call_args[0]
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert "type: result" in notes_arg
        assert "proposal_status" not in notes_arg

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_create_task_respects_explicit_proposal_status(
        self, mock_list, mock_gog
    ):
        """Caller-supplied proposal_status wins over the auto default."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "p-2"}})
        create_task(
            "[PROPOSAL] already approved upstream",
            priority="high",
            source="consumer",
            proposal_status="approved",
        )
        call_args = mock_gog.call_args[0]
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert "type: proposal" in notes_arg
        assert "proposal_status: approved" in notes_arg

    def test_get_pending_excludes_proposal_titled_task(self):
        """Defense in depth: even if a row landed with default `type="task"`
        because some old skill skipped the kwarg, a `[PROPOSAL]`-titled
        task must not be picked up by the consumer."""
        tasks = [
            # Mis-typed legacy row - type="task" (default), not "proposal"
            Task(
                id="leaky",
                title="[PROPOSAL] TG reply to Andrew - propose call slots",
                status="pending",
                priority="high",
                type="task",
            ),
            Task(id="ok", title="[ACTION] real work",
                 status="pending", priority="high"),
        ]
        pending = get_pending(tasks)
        ids = [t.id for t in pending]
        assert "leaky" not in ids
        assert "ok" in ids

    def test_get_pending_still_excludes_well_formed_proposal(self):
        """The original filter still works for properly-typed proposals."""
        tasks = [
            Task(
                id="prop",
                title="[PROPOSAL] something",
                status="pending",
                priority="high",
                type="proposal",
                proposal_status="pending",
            ),
        ]
        assert get_pending(tasks) == []

    def test_get_pending_ignores_leading_whitespace(self):
        """Title with leading whitespace must still be filtered."""
        tasks = [
            Task(
                id="ws",
                title="  [PROPOSAL] padded",
                status="pending",
                priority="medium",
                type="task",
            ),
        ]
        assert get_pending(tasks) == []


# Regression: 2026-04-25 — Timur Olevskiy Signal incident. A heartbeat
# session called `create_task(title="[ACTION] Specify ships article credit
# for Timur ...", source="heartbeat", body=<signal message>)`. The executor
# read the `[ACTION]` prefix as user-typed pre-approval and ran
# `signal-cli send`. MEMORY.md autonomy boundary explicitly says "Signal:
# never send from personal accounts." The queue layer is now the chokepoint:
# only user-driven sources (manual / chat / deck-continue) or
# `proposal_status="approved"` lineage may mint an execution-tag prefix.
class TestExecutionTagGuard:
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_heartbeat_action_title_converted_to_proposal(
        self, mock_list, mock_gog
    ):
        """The exact incident: heartbeat -> [ACTION] -> Signal send."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "g-1"}})
        create_task(
            "[ACTION] Specify ships article credit for Timur",
            priority="high",
            source="heartbeat",
            body="Send signal-cli message to +420775189142 ...",
        )
        call_args = mock_gog.call_args[0]
        title_arg = next(a for a in call_args if a == "--title" or a.startswith("[")) if False else None
        # gog args: ["tasks", "add", lid, "--title", title, ...]
        idx = call_args.index("--title")
        new_title = call_args[idx + 1]
        notes_arg = next(a for a in call_args if a.startswith("--notes="))
        assert new_title.startswith("[PROPOSAL] "), f"title not rewritten: {new_title!r}"
        assert "Specify ships article credit" in new_title
        assert "type: proposal" in notes_arg
        assert "proposal_status: pending" in notes_arg

    @pytest.mark.parametrize("tag", ["[ACTION]", "[SEND]", "[PUBLISH]", "[BOOK]", "[POST]"])
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_all_execution_tags_blocked_for_automated_sources(
        self, mock_list, mock_gog, tag
    ):
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "g-x"}})
        create_task(
            f"{tag} do the irreversible thing",
            priority="high",
            source="idle_research",
        )
        call_args = mock_gog.call_args[0]
        idx = call_args.index("--title")
        assert call_args[idx + 1].startswith("[PROPOSAL] ")

    @pytest.mark.parametrize("source", ["manual", "chat", "deck-continue"])
    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_user_driven_sources_keep_action_prefix(
        self, mock_list, mock_gog, source
    ):
        """User typed [ACTION] in the CLI / chat / clicked Execute — passes through."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "u-1"}})
        create_task(
            "[ACTION] do the thing",
            priority="medium",
            source=source,
        )
        call_args = mock_gog.call_args[0]
        idx = call_args.index("--title")
        assert call_args[idx + 1] == "[ACTION] do the thing"

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_approved_proposal_status_keeps_action_prefix(
        self, mock_list, mock_gog
    ):
        """approve_proposal mutates in place but if a caller does pass the
        approved status through create_task, honor it."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "a-1"}})
        create_task(
            "[ACTION] do the thing",
            priority="medium",
            source="heartbeat",
            proposal_status="approved",
        )
        call_args = mock_gog.call_args[0]
        idx = call_args.index("--title")
        assert call_args[idx + 1] == "[ACTION] do the thing"

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_neutral_prefix_unaffected(self, mock_list, mock_gog):
        """[REPLY], [DEAL], [RESEARCH] etc must pass through unchanged."""
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "n-1"}})
        create_task(
            "[REPLY] Andrew - draft response",
            priority="medium",
            source="heartbeat",
        )
        call_args = mock_gog.call_args[0]
        idx = call_args.index("--title")
        assert call_args[idx + 1] == "[REPLY] Andrew - draft response"

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_no_prefix_unaffected(self, mock_list, mock_gog):
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "z-1"}})
        create_task(
            "Research Acme Corp founders",
            priority="medium",
            source="heartbeat",
        )
        call_args = mock_gog.call_args[0]
        idx = call_args.index("--title")
        assert call_args[idx + 1] == "Research Acme Corp founders"


class TestDigestFlag:
    """Digest cards (Pulse, Reflection, Klava self-reports) carry a
    `digest=true` frontmatter flag and auto-supersede prior digests with
    the same source so only the latest stays on the Deck.
    """

    def test_digest_field_round_trips(self):
        task = Task(
            id="x", title="[RESULT] Pulse 14:00",
            type="result", source="pulse",
            digest=True, body="",
        )
        notes = task.to_notes()
        assert "digest: true" in notes
        meta, _ = parse_frontmatter(notes)
        assert meta["digest"] == "true"

    def test_task_from_gtask_parses_digest_true(self):
        gtask = {
            "id": "abc",
            "title": "[RESULT] Reflection",
            "notes": "---\nstatus: pending\ntype: result\ndigest: true\n---\n",
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.digest is True

    def test_task_from_gtask_digest_unset_is_none(self):
        gtask = {
            "id": "abc",
            "title": "Regular task",
            "notes": "---\nstatus: pending\n---\n",
            "status": "needsAction",
        }
        task = Task.from_gtask(gtask)
        assert task.digest is None

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_create_task_digest_flag_lands_in_frontmatter(
        self, mock_list, mock_gog
    ):
        from tasks.queue import create_task
        mock_list.return_value = []
        mock_gog.return_value = json.dumps({"task": {"id": "d-1"}})
        create_task(
            "[RESULT] Pulse digest",
            type="result",
            source="pulse",
            digest=True,
        )
        notes_arg = next(
            a for a in mock_gog.call_args[0] if a.startswith("--notes=")
        )
        assert "digest: true" in notes_arg

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_supersede_closes_prior_pulse_digest(
        self, mock_list, mock_gog
    ):
        """Regression: 2026-04-27 — Pulse cards stacked one per cron tick.
        New pulse digest must close prior pending pulse digest.
        """
        from tasks.queue import create_result

        old_pulse = Task(
            id="old-pulse",
            title="[RESULT] Pulse — Apr 25 14:00",
            type="result",
            source="pulse",
            status="pending",
            digest=True,
        )
        unrelated_result = Task(
            id="unrelated",
            title="[RESULT] Reply Diana",
            type="result",
            source="consumer",
            status="pending",
        )
        other_digest = Task(
            id="other-digest",
            title="[RESULT] Reflection nightly",
            type="result",
            source="reflection",  # different source — must NOT be touched
            status="pending",
            digest=True,
        )
        mock_list.return_value = [old_pulse, unrelated_result, other_digest]
        mock_gog.return_value = json.dumps({"task": {"id": "new-pulse"}})

        create_result(
            parent_task_id=None,
            title="Pulse — Apr 25 20:00",
            body="latest digest",
            source="pulse",
            digest=True,
        )

        # Find the `tasks done` calls (gog command for completing a task).
        done_targets = []
        for call in mock_gog.call_args_list:
            args = call[0]
            if args[:2] == ("tasks", "done"):
                done_targets.append(args[3])  # gog tasks done <list_id> <task_id>

        assert "old-pulse" in done_targets, \
            "prior pulse digest must be superseded"
        assert "other-digest" not in done_targets, \
            "different-source digest must NOT be touched"
        assert "unrelated" not in done_targets, \
            "non-digest result must NOT be touched"

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_supersede_folds_prior_bodies_into_new_digest(
        self, mock_list, mock_gog
    ):
        """The newest digest must include prior digest bodies as a
        `## Prior {source} digest — ...` history section so nothing is
        dropped when older cards are superseded.
        """
        from tasks.queue import create_result

        old1 = Task(
            id="old1",
            title="[RESULT] Pulse — Apr 25 14:00",
            type="result",
            source="pulse",
            status="pending",
            digest=True,
            created="2026-04-25T14:00:00+00:00",
            body="#result\n\n## Pulse 14:00 highlights\nThing A happened.",
        )
        old2 = Task(
            id="old2",
            title="[RESULT] Pulse — Apr 25 20:00",
            type="result",
            source="pulse",
            status="pending",
            digest=True,
            created="2026-04-25T20:00:00+00:00",
            body="#result\n\n## Pulse 20:00 highlights\nThing B happened.",
        )
        mock_list.return_value = [old1, old2]
        mock_gog.return_value = json.dumps({"task": {"id": "new-pulse"}})

        create_result(
            parent_task_id=None,
            title="Pulse — Apr 26 06:00",
            body="## Pulse 06:00 highlights\nFresh content.",
            source="pulse",
            digest=True,
        )

        # The notes argument to `tasks add` should contain the new body
        # AND a history section with both old bodies folded in.
        notes_arg = next(
            a for a in mock_gog.call_args[0] if a.startswith("--notes=")
        )
        assert "Fresh content" in notes_arg
        assert "Prior pulse digest" in notes_arg
        assert "Thing A happened" in notes_arg
        assert "Thing B happened" in notes_arg
        # Both old cards still get closed.
        done_targets = [
            call[0][3] for call in mock_gog.call_args_list
            if call[0][:2] == ("tasks", "done")
        ]
        assert "old1" in done_targets
        assert "old2" in done_targets

    @patch("tasks.queue._run_gog")
    @patch("tasks.queue.list_tasks")
    def test_supersede_skipped_when_digest_false(
        self, mock_list, mock_gog
    ):
        """Non-digest create_result must NOT supersede prior digests."""
        from tasks.queue import create_result

        old_pulse = Task(
            id="old-pulse",
            title="[RESULT] Pulse — Apr 25 14:00",
            type="result",
            source="pulse",
            status="pending",
            digest=True,
        )
        mock_list.return_value = [old_pulse]
        mock_gog.return_value = json.dumps({"task": {"id": "new-result"}})

        create_result(
            parent_task_id=None,
            title="Some non-digest result",
            body="body",
            source="consumer",  # not pulse
            digest=False,
        )

        done_targets = [
            call[0][3] for call in mock_gog.call_args_list
            if call[0][:2] == ("tasks", "done")
        ]
        assert "old-pulse" not in done_targets
