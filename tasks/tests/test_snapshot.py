"""Tests for tasks/snapshot.py - in-memory + file-persisted GT snapshot."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks import snapshot


LID = "TEST_LIST"


@pytest.fixture(autouse=True)
def _clean_between_tests(tmp_path, monkeypatch):
    """Redirect snapshot files into a tmp dir and reset in-memory state."""
    monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
    snapshot.reset_for_tests()
    yield
    snapshot.reset_for_tests()


def _fake_gog(responses):
    """Yield stdout strings from `responses` on each _gog_call."""
    it = iter(responses)

    def _impl(*args, **kwargs):
        return next(it)

    return _impl


class TestBootstrap:
    def test_cold_start_bootstraps(self):
        items = [
            {"id": "a", "title": "task A", "status": "needsAction"},
            {"id": "b", "title": "task B", "status": "needsAction"},
        ]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            result = snapshot.get_all(LID)

        assert len(result) == 2
        ids = sorted(i["id"] for i in result)
        assert ids == ["a", "b"]

    def test_bootstrap_persists_to_disk(self):
        items = [{"id": "a", "title": "A", "status": "needsAction"}]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            snapshot.get_all(LID)

        path = snapshot._snapshot_path(LID)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["list_id"] == LID
        assert data["last_sync"]
        assert data["bootstrapped_at"]
        assert "a" in data["items"]

    def test_filters_completed_by_default(self):
        items = [
            {"id": "a", "title": "A", "status": "needsAction"},
            {"id": "b", "title": "B", "status": "completed"},
        ]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            result = snapshot.get_all(LID, include_completed=False)

        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_include_completed_returns_all(self):
        items = [
            {"id": "a", "title": "A", "status": "needsAction"},
            {"id": "b", "title": "B", "status": "completed"},
        ]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            result = snapshot.get_all(LID, include_completed=True)

        assert len(result) == 2


class TestCacheHit:
    def test_second_read_does_not_call_gog(self):
        items = [{"id": "a", "title": "A", "status": "needsAction"}]

        call_count = {"n": 0}

        def _tracking_gog(*args, **kwargs):
            call_count["n"] += 1
            return json.dumps(items)

        with patch.object(snapshot, "_gog_call", _tracking_gog):
            snapshot.get_all(LID)
            snapshot.get_all(LID)
            snapshot.get_all(LID)

        assert call_count["n"] == 1  # only bootstrap, no delta within MAX_AGE


class TestDeltaRefresh:
    def test_stale_snapshot_triggers_delta(self, monkeypatch):
        # Short MAX_AGE so second read triggers delta
        monkeypatch.setattr(snapshot, "SNAPSHOT_MAX_AGE", 0)

        bootstrap_items = [{"id": "a", "title": "A", "status": "needsAction"}]
        delta_items = [{"id": "a", "title": "A UPDATED", "status": "needsAction"}]

        with patch.object(snapshot, "_gog_call", _fake_gog([
            json.dumps(bootstrap_items),
            json.dumps(delta_items),
        ])):
            first = snapshot.get_all(LID)
            assert first[0]["title"] == "A"
            second = snapshot.get_all(LID)

        titles = {i["id"]: i["title"] for i in second}
        assert titles["a"] == "A UPDATED"

    def test_delta_drops_deleted(self, monkeypatch):
        monkeypatch.setattr(snapshot, "SNAPSHOT_MAX_AGE", 0)

        bootstrap_items = [
            {"id": "a", "title": "A", "status": "needsAction"},
            {"id": "b", "title": "B", "status": "needsAction"},
        ]
        delta_items = [{"id": "b", "title": "B", "status": "needsAction", "deleted": True}]

        with patch.object(snapshot, "_gog_call", _fake_gog([
            json.dumps(bootstrap_items),
            json.dumps(delta_items),
        ])):
            snapshot.get_all(LID)
            result = snapshot.get_all(LID)

        ids = {i["id"] for i in result}
        assert ids == {"a"}

    def test_delta_drops_hidden(self, monkeypatch):
        monkeypatch.setattr(snapshot, "SNAPSHOT_MAX_AGE", 0)

        bootstrap_items = [{"id": "a", "title": "A", "status": "needsAction"}]
        delta_items = [{"id": "a", "title": "A", "status": "completed", "hidden": True}]

        with patch.object(snapshot, "_gog_call", _fake_gog([
            json.dumps(bootstrap_items),
            json.dumps(delta_items),
        ])):
            snapshot.get_all(LID)
            result = snapshot.get_all(LID, include_completed=True)

        assert result == []

    def test_delta_null_response_keeps_snapshot(self, monkeypatch):
        monkeypatch.setattr(snapshot, "SNAPSHOT_MAX_AGE", 0)

        bootstrap_items = [{"id": "a", "title": "A", "status": "needsAction"}]

        # Delta returns "null" (no updates)
        with patch.object(snapshot, "_gog_call", _fake_gog([
            json.dumps(bootstrap_items),
            "null",
        ])):
            snapshot.get_all(LID)
            result = snapshot.get_all(LID)

        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_delta_failure_returns_stale_data(self, monkeypatch):
        monkeypatch.setattr(snapshot, "SNAPSHOT_MAX_AGE", 0)

        bootstrap_items = [{"id": "a", "title": "A", "status": "needsAction"}]

        def _fail_on_delta(*args, **kwargs):
            if any("--updated-min" in str(a) for a in args):
                raise RuntimeError("network down")
            return json.dumps(bootstrap_items)

        with patch.object(snapshot, "_gog_call", _fail_on_delta):
            snapshot.get_all(LID)
            result = snapshot.get_all(LID)

        assert len(result) == 1  # stale snapshot still serves


class TestInlineMutation:
    def test_apply_local_mutation_patches_field(self):
        items = [{"id": "a", "title": "A", "status": "needsAction", "notes": "old"}]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            snapshot.get_all(LID)
            snapshot.apply_local_mutation(LID, "a", notes="new")
            result = snapshot.get_all(LID)

        assert result[0]["notes"] == "new"
        assert result[0]["title"] == "A"  # untouched fields preserved

    def test_apply_local_insert(self):
        items = [{"id": "a", "title": "A", "status": "needsAction"}]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            snapshot.get_all(LID)
            snapshot.apply_local_insert(LID, {"id": "b", "title": "B", "status": "needsAction"})
            result = snapshot.get_all(LID)

        ids = {i["id"] for i in result}
        assert ids == {"a", "b"}

    def test_apply_local_delete(self):
        items = [
            {"id": "a", "title": "A", "status": "needsAction"},
            {"id": "b", "title": "B", "status": "needsAction"},
        ]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            snapshot.get_all(LID)
            snapshot.apply_local_delete(LID, "b")
            result = snapshot.get_all(LID)

        assert {i["id"] for i in result} == {"a"}

    def test_apply_local_complete(self):
        items = [{"id": "a", "title": "A", "status": "needsAction"}]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            snapshot.get_all(LID)
            snapshot.apply_local_complete(LID, "a")
            active = snapshot.get_all(LID, include_completed=False)
            all_items = snapshot.get_all(LID, include_completed=True)

        assert active == []
        assert len(all_items) == 1
        assert all_items[0]["status"] == "completed"
        assert "completed" in all_items[0]

    def test_mutation_persists_to_disk(self):
        items = [{"id": "a", "title": "A", "status": "needsAction"}]
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items)])):
            snapshot.get_all(LID)
            snapshot.apply_local_mutation(LID, "a", title="UPDATED")

        path = snapshot._snapshot_path(LID)
        data = json.loads(path.read_text())
        assert data["items"]["a"]["title"] == "UPDATED"


class TestCrossProcess:
    def test_file_mtime_invalidates_memory_cache(self):
        """Simulate another process updating the file between reads."""
        items_v1 = [{"id": "a", "title": "V1", "status": "needsAction"}]
        items_v2 = [
            {"id": "a", "title": "V1", "status": "needsAction"},
            {"id": "b", "title": "V2", "status": "needsAction"},
        ]

        # Bootstrap with v1
        with patch.object(snapshot, "_gog_call", _fake_gog([json.dumps(items_v1)])):
            result = snapshot.get_all(LID)
        assert len(result) == 1

        # Simulate another process writing v2 to the file
        path = snapshot._snapshot_path(LID)
        existing = json.loads(path.read_text())
        existing["items"]["b"] = {"id": "b", "title": "V2", "status": "needsAction"}
        import time
        time.sleep(0.05)  # ensure distinct mtime
        path.write_text(json.dumps(existing))

        # No gog call should happen (data fresh by last_sync), but mem should reload
        with patch.object(snapshot, "_gog_call", lambda *a, **kw: pytest.fail("unexpected gog call")):
            result = snapshot.get_all(LID)

        assert {i["id"] for i in result} == {"a", "b"}


class TestBootstrapRebuild:
    def test_bootstrap_refreshed_when_older_than_bootstrap_max_age(self, monkeypatch):
        # BOOTSTRAP_MAX_AGE=0 forces re-bootstrap on every read
        monkeypatch.setattr(snapshot, "BOOTSTRAP_MAX_AGE", 0)

        items_v1 = [{"id": "a", "title": "V1", "status": "needsAction"}]
        items_v2 = [{"id": "a", "title": "V2", "status": "needsAction"}]

        with patch.object(snapshot, "_gog_call", _fake_gog([
            json.dumps(items_v1),
            json.dumps(items_v2),
        ])):
            first = snapshot.get_all(LID)
            second = snapshot.get_all(LID)

        assert first[0]["title"] == "V1"
        assert second[0]["title"] == "V2"
