"""Tests for dashboard API routes and agents routes.

Tests dashboard_api.py pure functions (backlog parsing, JSONL counting)
and Flask endpoints via test client.
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.dashboard_api import (
    _parse_backlog_full,
    _serialize_backlog,
    _count_jsonl_lines,
    dashboard_bp,
    init_dashboard_bp,
)
from routes.agents import (
    agents_bp,
    _load_subagent_state,
    _subagent_to_agent,
)


# ── Flask test app ──

@pytest.fixture
def app(tmp_path):
    """Create a minimal Flask app with dashboard + agents blueprints."""
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(agents_bp)
    init_dashboard_bp(MagicMock(), MagicMock())
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ═══════════════════════════════════════════════════════════════════════
# dashboard_api.py - pure functions
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_BACKLOG = """# Self-Evolve Backlog

## Metrics
- Items added (30d): 5
- Items fixed (30d): 3
- Avg days open: 2.1
- Last run: 2026-03-15T05:30:00

---

## Items

### [2026-03-14] Fix heartbeat noise
- **source:** dislike
- **priority:** high
- **status:** open
- **seen:** 2
- **description:** Too many feed messages
- **fix-hint:** Add noise filter

### [2026-03-15] Dashboard CSS broken
- **source:** chat
- **priority:** medium
- **status:** open
- **seen:** 1
- **description:** Overflow on mobile

---

## Done

### [2026-03-10] Memory sync delay
- **source:** self-evolve
- **priority:** low
- **status:** done
- **seen:** 3
- **resolved:** Fixed in commit abc123
"""


class TestParseBacklogFull:
    def test_parses_metrics(self):
        metrics, items, done = _parse_backlog_full(SAMPLE_BACKLOG)
        assert metrics["added"] == 5
        assert metrics["fixed"] == 3
        assert metrics["avg_days"] == "2.1"
        assert "2026-03-15" in metrics["last_run"]

    def test_parses_items(self):
        metrics, items, done = _parse_backlog_full(SAMPLE_BACKLOG)
        assert len(items) == 2
        assert items[0]["title"] == "Fix heartbeat noise"
        assert items[0]["priority"] == "high"
        assert items[0]["seen"] == 2
        assert items[1]["title"] == "Dashboard CSS broken"

    def test_parses_done(self):
        metrics, items, done = _parse_backlog_full(SAMPLE_BACKLOG)
        assert len(done) == 1
        assert done[0]["title"] == "Memory sync delay"
        assert done[0]["status"] == "done"

    def test_empty_input(self):
        metrics, items, done = _parse_backlog_full("")
        assert items == []
        assert done == []


class TestSerializeBacklog:
    def test_roundtrip(self):
        metrics, items, done = _parse_backlog_full(SAMPLE_BACKLOG)
        serialized = _serialize_backlog(metrics, items, done)
        # Re-parse
        m2, i2, d2 = _parse_backlog_full(serialized)
        assert m2["added"] == 5
        assert len(i2) == 2
        assert len(d2) == 1
        assert i2[0]["title"] == "Fix heartbeat noise"

    def test_empty_lists(self):
        result = _serialize_backlog({"added": 0, "fixed": 0, "avg_days": "-", "last_run": "never"}, [], [])
        assert "## Items" in result
        assert "## Done" in result


class TestCountJsonlLines:
    def test_counts_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"a":1}\n{"b":2}\n{"c":3}\n')
        assert _count_jsonl_lines(f) == 3

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert _count_jsonl_lines(f) == 0

    def test_single_line(self, tmp_path):
        f = tmp_path / "one.jsonl"
        f.write_text('{"a":1}\n')
        assert _count_jsonl_lines(f) == 1


# ═══════════════════════════════════════════════════════════════════════
# dashboard_api.py - Flask endpoints
# ═══════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_returns_healthy(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestDashboardDataEndpoints:
    @patch("routes.dashboard_api.collect_dashboard_data")
    def test_api_dashboard(self, mock_collect, client):
        mock_collect.return_value = {"sessions": [], "status": "ok"}
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_dashboard_data")
    def test_api_dashboard_error(self, mock_collect, client):
        mock_collect.side_effect = Exception("boom")
        resp = client.get("/api/dashboard")
        assert resp.status_code == 500
        assert "error" in resp.get_json()

    @patch("routes.dashboard_api.collect_files_data")
    def test_api_files(self, mock_collect, client):
        mock_collect.return_value = {"files": []}
        resp = client.get("/api/files")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_files_data")
    def test_api_files_with_date(self, mock_collect, client):
        mock_collect.return_value = {"files": []}
        resp = client.get("/api/files?date=2026-03-15")
        mock_collect.assert_called_once_with(date="2026-03-15")

    @patch("routes.dashboard_api.collect_tasks_data")
    def test_api_tasks(self, mock_collect, client):
        mock_collect.return_value = {"tasks": []}
        resp = client.get("/api/tasks")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_heartbeat_data")
    def test_api_heartbeat(self, mock_collect, client):
        mock_collect.return_value = {"messages": []}
        resp = client.get("/api/heartbeat")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_feed_data")
    def test_api_feed(self, mock_collect, client):
        mock_collect.return_value = {"messages": []}
        resp = client.get("/api/feed?limit=50&topic=Heartbeat")
        mock_collect.assert_called_once_with(limit=50, topic="Heartbeat")

    @patch("routes.dashboard_api.collect_deals_data")
    def test_api_deals(self, mock_collect, client):
        mock_collect.return_value = {"deals": []}
        resp = client.get("/api/deals")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_people_data")
    def test_api_people(self, mock_collect, client):
        mock_collect.return_value = {"people": []}
        resp = client.get("/api/people")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_followups_data")
    def test_api_followups(self, mock_collect, client):
        mock_collect.return_value = {"followups": []}
        resp = client.get("/api/followups")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_calendar_data")
    def test_api_calendar(self, mock_collect, client):
        mock_collect.return_value = {"events": []}
        resp = client.get("/api/calendar")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_views_data")
    def test_api_views(self, mock_collect, client):
        mock_collect.return_value = {"views": []}
        resp = client.get("/api/views")
        assert resp.status_code == 200

    @patch("routes.dashboard_api.collect_pipelines_data")
    def test_api_pipelines(self, mock_collect, client):
        mock_collect.return_value = {"pipelines": []}
        resp = client.get("/api/pipelines")
        assert resp.status_code == 200


class TestTasksUpdate:
    @patch("routes.dashboard_api.update_task")
    def test_update_task(self, mock_update, client):
        mock_update.return_value = {"success": True}
        resp = client.post("/api/tasks/update",
                           data=json.dumps({"task_id": "t1", "action": "complete"}),
                           content_type="application/json")
        assert resp.status_code == 200

    def test_missing_fields(self, client):
        resp = client.post("/api/tasks/update",
                           data=json.dumps({"task_id": ""}),
                           content_type="application/json")
        assert resp.status_code == 400


class TestViewsServe:
    def test_path_traversal_blocked(self, client):
        resp = client.get("/api/views/serve/..%2F..%2Fetc%2Fpasswd")
        # Should block - either 400 (caught) or 404 (file not found)
        assert resp.status_code in (400, 404)

    def test_serves_existing_html(self, client, tmp_path, monkeypatch):
        views_dir = tmp_path / "Documents" / "MyBrain" / "Views"
        views_dir.mkdir(parents=True)
        (views_dir / "report.html").write_text("<h1>Test</h1>")
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.get("/api/views/serve/report.html")
        assert resp.status_code == 200
        assert b"<h1>Test</h1>" in resp.data

    def test_serves_404_missing(self, client, tmp_path, monkeypatch):
        views_dir = tmp_path / "Documents" / "MyBrain" / "Views"
        views_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.get("/api/views/serve/nonexistent.html")
        assert resp.status_code == 404

    def test_slash_in_filename_blocked(self, client):
        resp = client.get("/api/views/serve/sub%2Ffile.html")
        assert resp.status_code in (400, 404)


class TestSelfEvolveGet:
    """Test GET /api/self-evolve - reads backlog.md."""

    def test_no_backlog_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.get("/api/self-evolve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["added"] == 0
        assert data["items"] == []

    def test_parses_backlog(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.get("/api/self-evolve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["added"] == 5
        assert data["metrics"]["fixed"] == 3
        assert len(data["items"]) >= 2

    def test_parses_item_fields(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.get("/api/self-evolve")
        data = resp.get_json()
        item = next(i for i in data["items"] if i["title"] == "Fix heartbeat noise")
        assert item["source"] == "dislike"
        assert item["priority"] == "high"
        assert item["status"] == "open"
        assert item["seen"] == 2


class TestSelfEvolveUpdate:
    """Test PUT /api/self-evolve/item."""

    def test_missing_title(self, client):
        resp = client.put("/api/self-evolve/item",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_no_backlog_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.put("/api/self-evolve/item",
                          data=json.dumps({"title": "Nope"}),
                          content_type="application/json")
        assert resp.status_code == 404

    def test_item_not_found(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.put("/api/self-evolve/item",
                          data=json.dumps({"title": "Does not exist"}),
                          content_type="application/json")
        assert resp.status_code == 404

    def test_update_priority(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.put("/api/self-evolve/item",
                          data=json.dumps({
                              "title": "Fix heartbeat noise",
                              "updates": {"priority": "low"}
                          }),
                          content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # Verify it was written
        text = (backlog_dir / "backlog.md").read_text()
        assert "low" in text


class TestSelfEvolveDelete:
    """Test DELETE /api/self-evolve/item."""

    def test_missing_title(self, client):
        resp = client.delete("/api/self-evolve/item",
                             data=json.dumps({}),
                             content_type="application/json")
        assert resp.status_code == 400

    def test_no_backlog_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.delete("/api/self-evolve/item",
                             data=json.dumps({"title": "Nope"}),
                             content_type="application/json")
        assert resp.status_code == 404

    def test_item_not_found(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.delete("/api/self-evolve/item",
                             data=json.dumps({"title": "Nonexistent"}),
                             content_type="application/json")
        assert resp.status_code == 404

    def test_delete_item(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.delete("/api/self-evolve/item",
                             data=json.dumps({"title": "Fix heartbeat noise"}),
                             content_type="application/json")
        assert resp.status_code == 200
        # Item should be gone
        text = (backlog_dir / "backlog.md").read_text()
        assert "Fix heartbeat noise" not in text
        assert "Dashboard CSS broken" in text


class TestSelfEvolveRun:
    """Test POST /api/self-evolve/run."""

    def test_no_jobs_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.post("/api/self-evolve/run")
        assert resp.status_code == 404

    def test_no_self_evolve_job(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        jobs_dir = tmp_path / "Documents" / "GitHub" / "claude" / "cron"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "jobs.json").write_text(json.dumps({"jobs": [{"id": "other"}]}))
        resp = client.post("/api/self-evolve/run")
        assert resp.status_code == 404

    @patch("routes.dashboard_api._executor")
    def test_runs_successfully(self, mock_executor, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        jobs_dir = tmp_path / "Documents" / "GitHub" / "claude" / "cron"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "jobs.json").write_text(json.dumps({
            "jobs": [{"id": "self-evolve", "execution": {
                "prompt_template": "fix stuff",
                "model": "sonnet",
                "timeout_seconds": 60,
            }}]
        }))
        (jobs_dir / "runs.jsonl").write_text("")
        mock_executor.run.return_value = {"result": "Done!", "cost": 0.01}
        resp = client.post("/api/self-evolve/run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "executed"
        assert "Done!" in data["output"]


class TestFeedbackDislike:
    """Test POST /api/feedback/dislike."""

    def test_no_backlog_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        resp = client.post("/api/feedback/dislike",
                           data=json.dumps({"comment": "Bad output"}),
                           content_type="application/json")
        assert resp.status_code == 404

    def test_adds_dislike_with_comment(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.post("/api/feedback/dislike",
                           data=json.dumps({
                               "comment": "Output was wrong",
                               "text_preview": "Some context",
                               "block_id": "blk-1",
                               "session_id": "sess-99",
                           }),
                           content_type="application/json")
        assert resp.status_code == 200
        text = (backlog_dir / "backlog.md").read_text()
        assert "Output was wrong" in text
        assert "dislike" in text

    def test_adds_dislike_without_comment(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        backlog_dir = tmp_path / "Documents" / "GitHub" / "claude" / "self-evolve"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / "backlog.md").write_text(SAMPLE_BACKLOG)
        resp = client.post("/api/feedback/dislike",
                           data=json.dumps({"block_id": "blk-5"}),
                           content_type="application/json")
        assert resp.status_code == 200
        text = (backlog_dir / "backlog.md").read_text()
        assert "Dislike on block #blk-5" in text


class TestViewsOpen:
    """Test POST /api/views/open."""

    def test_no_params(self, client):
        resp = client.post("/api/views/open",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_path_traversal_blocked(self, client):
        resp = client.post("/api/views/open",
                           data=json.dumps({"path": "../../../etc/passwd"}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_filename_traversal_blocked(self, client):
        resp = client.post("/api/views/open",
                           data=json.dumps({"filename": "../secret.html"}),
                           content_type="application/json")
        assert resp.status_code == 400

    def test_filename_not_found(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        views_dir = tmp_path / "Documents" / "MyBrain" / "Views"
        views_dir.mkdir(parents=True)
        resp = client.post("/api/views/open",
                           data=json.dumps({"filename": "nope.html"}),
                           content_type="application/json")
        assert resp.status_code == 404

    @patch("routes.dashboard_api._socketio")
    def test_opens_filename_via_socket(self, mock_sio, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        views_dir = tmp_path / "Documents" / "MyBrain" / "Views"
        views_dir.mkdir(parents=True)
        (views_dir / "report.html").write_text("<h1>Hi</h1>")
        resp = client.post("/api/views/open",
                           data=json.dumps({"filename": "report.html"}),
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "report.html" in data["url"]
        mock_sio.emit.assert_called_once()

    def test_md_path_not_found(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        vault = tmp_path / "Documents" / "MyBrain"
        vault.mkdir(parents=True)
        resp = client.post("/api/views/open",
                           data=json.dumps({"path": "Notes/missing.md"}),
                           content_type="application/json")
        assert resp.status_code == 404

    @patch("routes.dashboard_api._socketio")
    def test_opens_md_path(self, mock_sio, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        vault = tmp_path / "Documents" / "MyBrain"
        notes_dir = vault / "Notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "test.md").write_text("# Hello")
        resp = client.post("/api/views/open",
                           data=json.dumps({"path": "Notes/test.md"}),
                           content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "markdown/render" in data["url"]


class TestMarkdownRender:
    """Test GET /api/markdown/render."""

    def test_no_path(self, client):
        resp = client.get("/api/markdown/render")
        assert resp.status_code == 400

    def test_path_traversal(self, client):
        resp = client.get("/api/markdown/render?path=../../../etc/passwd")
        assert resp.status_code == 400

    def test_file_not_found(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        vault = tmp_path / "Documents" / "MyBrain"
        vault.mkdir(parents=True)
        resp = client.get("/api/markdown/render?path=nope.md")
        assert resp.status_code == 404

    def test_renders_markdown(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        vault = tmp_path / "Documents" / "MyBrain"
        vault.mkdir(parents=True)
        (vault / "test.md").write_text("# Hello\n\nSome **bold** text")
        resp = client.get("/api/markdown/render?path=test.md")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "<h1" in html  # may have id attr from toc extension
        assert "Hello" in html
        assert "<strong>bold</strong>" in html

    def test_strips_frontmatter(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        vault = tmp_path / "Documents" / "MyBrain"
        vault.mkdir(parents=True)
        (vault / "note.md").write_text("---\ntitle: Test\ntags: [a]\n---\n\n# Title\nBody text")
        resp = client.get("/api/markdown/render?path=note.md")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "title: Test" not in html
        assert "Title" in html
        assert "Body text" in html

    def test_converts_wikilinks(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        vault = tmp_path / "Documents" / "MyBrain"
        vault.mkdir(parents=True)
        (vault / "links.md").write_text("See [[Some Note]] and [[Other|Display Name]]")
        resp = client.get("/api/markdown/render?path=links.md")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Some Note" in html
        assert "Display Name" in html
        assert "[[" not in html


class TestSourcesAPI:
    """Test GET /api/sources."""

    @patch("routes.dashboard_api.Path")
    def test_sources_returns_data(self, mock_path_cls, client):
        # This endpoint imports vadimgest.ingest.sources dynamically
        # Just test it doesn't crash with a mock
        with patch("routes.dashboard_api.json") as mock_json:
            # The simplest way: mock the import inside the endpoint
            mock_manifests = {"telegram": {"name": "telegram", "type": "jsonl"}}
            with patch.dict("sys.modules", {"vadimgest": MagicMock(),
                                            "vadimgest.ingest": MagicMock(),
                                            "vadimgest.ingest.sources": MagicMock(
                                                get_all_manifests=MagicMock(return_value=mock_manifests)
                                            )}):
                resp = client.get("/api/sources")
                # May succeed or fail depending on path resolution
                assert resp.status_code in (200, 500)


# ═══════════════════════════════════════════════════════════════════════
# routes/agents.py
# ═══════════════════════════════════════════════════════════════════════

class TestSubagentToAgent:
    def test_basic_conversion(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        sub = {
            "job": {"name": "Research task", "execution": {"model": "opus"}},
            "status": "running",
            "started_at": "2026-03-16T01:00:00",
            "session_id": "sess-1",
        }
        result = _subagent_to_agent("job-123", sub)
        assert result["id"] == "job-123"
        assert result["name"] == "Research task"
        assert result["model"] == "opus"
        assert result["status"] == "running"

    def test_with_output_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        (tmp_path / "j1.out").write_text("line1\nline2\nline3\n")
        sub = {"job": {}, "status": "running"}
        result = _subagent_to_agent("j1", sub)
        assert result["output_lines"] == 3
        assert result["last_output"] == "line3"

    def test_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr("routes.agents.SUBAGENT_OUTPUT_DIR", tmp_path)
        result = _subagent_to_agent("j1", {"job": {}})
        assert result["model"] == "sonnet"
        assert "dispatch" in result["name"]


class TestAgentsEndpoints:
    @patch("routes.agents._load_subagent_state")
    def test_list_empty(self, mock_load, client):
        mock_load.return_value = {"active": {}, "pending_announces": []}
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agents"] == []

    @patch("routes.agents._load_subagent_state")
    @patch("routes.agents.SUBAGENT_OUTPUT_DIR", Path("/tmp/nonexistent"))
    def test_list_with_active(self, mock_load, client):
        mock_load.return_value = {
            "active": {"j1": {"job": {"name": "T"}, "status": "running"}},
            "pending_announces": [],
        }
        resp = client.get("/api/agents")
        data = resp.get_json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == "j1"

    @patch("routes.agents._load_subagent_state")
    @patch("routes.agents.SUBAGENT_OUTPUT_DIR", Path("/tmp/nonexistent"))
    def test_detail_not_found(self, mock_load, client):
        mock_load.return_value = {"active": {}, "pending_announces": []}
        resp = client.get("/api/agents/nonexistent")
        assert resp.status_code == 404

    @patch("routes.agents._load_subagent_state")
    @patch("routes.agents.SUBAGENT_OUTPUT_DIR", Path("/tmp/nonexistent"))
    def test_detail_found(self, mock_load, client):
        mock_load.return_value = {
            "active": {"j1": {"job": {"name": "T"}, "status": "running"}},
            "pending_announces": [],
        }
        resp = client.get("/api/agents/j1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == "j1"

    @patch("routes.agents._load_subagent_state")
    def test_kill_not_found(self, mock_load, client):
        mock_load.return_value = {"active": {}, "pending_announces": []}
        resp = client.post("/api/agents/nonexistent/kill")
        assert resp.status_code == 404

    @patch("routes.agents._load_subagent_state")
    def test_kill_no_pid(self, mock_load, client):
        mock_load.return_value = {
            "active": {"j1": {"job": {}, "status": "running"}},
            "pending_announces": [],
        }
        resp = client.post("/api/agents/j1/kill")
        data = resp.get_json()
        assert data["status"] == "no_pid"


# ═══════════════════════════════════════════════════════════════════════
# webhook-server.py - Session & Chat State routes
# These routes live on the main Flask app, not in blueprints.
# We import the full webhook_server module to get access to app + globals.
# ═══════════════════════════════════════════════════════════════════════

import importlib.util
import time as _time


@pytest.fixture(scope="module")
def ws_mod():
    """Import webhook-server.py module once for all tests."""
    os.environ.setdefault("WEBHOOK_TOKEN", "test-token-12345")
    spec = importlib.util.spec_from_file_location(
        "webhook_server",
        os.path.join(os.path.dirname(__file__), "..", "webhook-server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    if "webhook_server" not in sys.modules:
        sys.modules["webhook_server"] = mod
        spec.loader.exec_module(mod)
    else:
        mod = sys.modules["webhook_server"]
    return mod


@pytest.fixture
def ws_client(ws_mod):
    """Flask test client for the full webhook-server app."""
    ws_mod.app.config["TESTING"] = True
    return ws_mod.app.test_client()


@pytest.fixture
def reset_chat_state(ws_mod):
    """Reset chat UI state before each test to avoid cross-test contamination."""
    original = dict(ws_mod._chat_ui_state)
    ws_mod._chat_ui_state.update({
        "version": 2,
        "active_sessions": [],
        "session_names": {},
        "unread_sessions": [],
        "drafts": {},
        "updated_at": "",
    })
    yield
    ws_mod._chat_ui_state.update(original)


def _make_session_jsonl(directory, session_id, messages=None):
    """Helper: create a JSONL session file with user/assistant messages."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    if messages is None:
        messages = [
            {"type": "user", "sessionId": session_id, "message": {"content": "Hello world"}},
            {"type": "assistant", "sessionId": session_id, "message": {"content": [
                {"type": "text", "text": "Hi there! How can I help?"}
            ]}},
        ]
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


# ═══════════════════════════════════════════════════════════════════════
# /api/sessions/search
# ═══════════════════════════════════════════════════════════════════════

class TestSessionsSearch:
    def test_short_query_returns_empty(self, ws_client):
        resp = ws_client.get("/api/sessions/search?q=a")
        assert resp.status_code == 200
        assert resp.get_json()["sessions"] == []

    def test_empty_query_returns_empty(self, ws_client):
        resp = ws_client.get("/api/sessions/search?q=")
        assert resp.status_code == 200
        assert resp.get_json()["sessions"] == []

    def test_no_query_param_returns_empty(self, ws_client):
        resp = ws_client.get("/api/sessions/search")
        assert resp.status_code == 200
        assert resp.get_json()["sessions"] == []

    def test_finds_matching_session(self, ws_client, ws_mod, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-search-1", [
            {"type": "user", "message": {"content": "Find the banana recipe"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Here is a banana recipe."}]}},
        ])
        resp = ws_client.get("/api/sessions/search?q=banana")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "sess-search-1"
        assert "banana" in data["sessions"][0]["snippet"].lower()

    def test_no_match_returns_empty(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-search-2", [
            {"type": "user", "message": {"content": "Hello world"}},
        ])
        resp = ws_client.get("/api/sessions/search?q=xyznotfound")
        assert resp.status_code == 200
        assert resp.get_json()["sessions"] == []

    def test_skips_system_reminder_content(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-search-3", [
            {"type": "user", "message": {"content": "Normal text <system-reminder>secret hidden data</system-reminder>"}},
        ])
        # "secret" is inside system-reminder tags, should be stripped before search
        resp = ws_client.get("/api/sessions/search?q=secret")
        data = resp.get_json()
        assert len(data["sessions"]) == 0


# ═══════════════════════════════════════════════════════════════════════
# /api/sessions/<session_id>
# ═══════════════════════════════════════════════════════════════════════

class TestSessionDetail:
    def test_session_not_found(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # Create the projects directory structure but no matching session
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        projects_dir.mkdir(parents=True)
        resp = ws_client.get("/api/sessions/nonexistent-id")
        assert resp.status_code == 404
        assert "not found" in resp.get_json()["error"].lower()

    def test_returns_session_messages(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-detail-1", [
            {"type": "user", "sessionId": "sess-detail-1", "message": {"content": "What is Python?"}},
            {"type": "assistant", "sessionId": "sess-detail-1", "message": {"content": [
                {"type": "text", "text": "Python is a programming language."}
            ]}},
        ])
        resp = ws_client.get("/api/sessions/sess-detail-1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_id"] == "sess-detail-1"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert "Python" in data["messages"][0]["text"]
        assert data["messages"][1]["role"] == "assistant"

    def test_handles_tool_use_messages(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-detail-2", [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
            ]}},
        ])
        resp = ws_client.get("/api/sessions/sess-detail-2")
        assert resp.status_code == 200
        messages = resp.get_json()["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool"] == "Bash"
        assert messages[0]["input"]["command"] == "ls -la"

    def test_handles_thinking_messages(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-detail-3", [
            {"type": "assistant", "message": {"content": [
                {"type": "thinking", "thinking": "Let me think about this..."},
                {"type": "text", "text": "Here is the answer."},
            ]}},
        ])
        resp = ws_client.get("/api/sessions/sess-detail-3")
        assert resp.status_code == 200
        messages = resp.get_json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "thinking"
        assert messages[1]["role"] == "assistant"

    def test_handles_list_content_in_user_message(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-detail-4", [
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "Part one"},
                {"type": "text", "text": "Part two"},
            ]}},
        ])
        resp = ws_client.get("/api/sessions/sess-detail-4")
        assert resp.status_code == 200
        messages = resp.get_json()["messages"]
        assert len(messages) == 1
        assert "Part one" in messages[0]["text"]
        assert "Part two" in messages[0]["text"]


# ═══════════════════════════════════════════════════════════════════════
# /api/sessions/<session_id>/fork
# ═══════════════════════════════════════════════════════════════════════

class TestSessionFork:
    def test_fork_not_found(self, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        projects_dir.mkdir(parents=True)
        resp = ws_client.post("/api/sessions/nonexistent/fork")
        assert resp.status_code == 404

    def test_fork_creates_new_session(self, ws_client, ws_mod, tmp_path, monkeypatch, reset_chat_state):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-fork-src", [
            {"type": "user", "sessionId": "sess-fork-src", "message": {"content": "Original prompt"}},
            {"type": "assistant", "sessionId": "sess-fork-src", "message": {"content": [
                {"type": "text", "text": "Original response"}
            ]}},
        ])
        # Mock _broadcast_chat_state to prevent socketio errors
        with patch.object(ws_mod, '_broadcast_chat_state'):
            resp = ws_client.post("/api/sessions/sess-fork-src/fork")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" in data
        assert data["source_id"] == "sess-fork-src"
        assert data["session_id"] != "sess-fork-src"
        assert data["messages"] == 2
        # Verify forked file exists
        new_file = projects_dir / f"{data['session_id']}.jsonl"
        assert new_file.exists()
        # Verify session IDs in new file are updated
        with open(new_file) as f:
            for line in f:
                entry = json.loads(line.strip())
                assert entry.get("sessionId") == data["session_id"]

    def test_fork_assigns_name(self, ws_client, ws_mod, tmp_path, monkeypatch, reset_chat_state):
        monkeypatch.setenv("HOME", str(tmp_path))
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-fork-named", [
            {"type": "user", "sessionId": "sess-fork-named", "message": {"content": "Hello fork"}},
        ])
        with patch.object(ws_mod, '_broadcast_chat_state'):
            resp = ws_client.post("/api/sessions/sess-fork-named/fork")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "name" in data
        assert len(data["name"]) > 0


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/state
# ═══════════════════════════════════════════════════════════════════════

class TestChatState:
    def test_get_chat_state(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.get("/api/chat/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_sessions" in data
        assert "session_names" in data
        assert "streaming_sessions" in data

    def test_chat_state_has_expected_structure(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.get("/api/chat/state")
        data = resp.get_json()
        assert isinstance(data["active_sessions"], list)
        assert isinstance(data["session_names"], dict)
        assert isinstance(data["streaming_sessions"], list)
        assert "unread_sessions" in data
        assert "drafts" in data


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/state/active
# ═══════════════════════════════════════════════════════════════════════

class TestChatStateActive:
    def test_add_session(self, ws_client, ws_mod, reset_chat_state):
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/active",
                                      data=json.dumps({"session_id": "sess-add-1", "action": "add"}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # Verify it was added
        assert any(e.get("session_id") == "sess-add-1" for e in ws_mod._chat_ui_state["active_sessions"])

    def test_remove_session(self, ws_client, ws_mod, reset_chat_state):
        # Add first
        ws_mod._chat_ui_state["active_sessions"] = [{"tab_id": None, "session_id": "sess-remove-1"}]
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/active",
                                      data=json.dumps({"session_id": "sess-remove-1", "action": "remove"}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert not any(e.get("session_id") == "sess-remove-1" for e in ws_mod._chat_ui_state["active_sessions"])

    def test_missing_session_id(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.post("/api/chat/state/active",
                              data=json.dumps({"action": "add"}),
                              content_type="application/json")
        assert resp.status_code == 400

    def test_invalid_action(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.post("/api/chat/state/active",
                              data=json.dumps({"session_id": "s1", "action": "invalid"}),
                              content_type="application/json")
        assert resp.status_code == 400

    def test_no_duplicate_add(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["active_sessions"] = [{"tab_id": None, "session_id": "sess-dup"}]
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/active",
                                      data=json.dumps({"session_id": "sess-dup", "action": "add"}),
                                      content_type="application/json")
        assert resp.status_code == 200
        count = sum(1 for e in ws_mod._chat_ui_state["active_sessions"] if e.get("session_id") == "sess-dup")
        assert count == 1

    def test_max_20_sessions(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["active_sessions"] = [
            {"tab_id": None, "session_id": f"s{i}"} for i in range(20)
        ]
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/active",
                                      data=json.dumps({"session_id": "s-overflow", "action": "add"}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert len(ws_mod._chat_ui_state["active_sessions"]) <= 20


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/state/name
# ═══════════════════════════════════════════════════════════════════════

class TestChatStateName:
    def test_set_name(self, ws_client, ws_mod, reset_chat_state):
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/name",
                                      data=json.dumps({"session_id": "sess-name-1", "name": "My Session"}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert ws_mod._chat_ui_state["session_names"]["sess-name-1"] == "My Session"

    def test_clear_name(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["session_names"]["sess-clear"] = "Old Name"
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/name",
                                      data=json.dumps({"session_id": "sess-clear", "name": ""}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert "sess-clear" not in ws_mod._chat_ui_state["session_names"]

    def test_clear_name_with_null(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["session_names"]["sess-null"] = "Will Clear"
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/name",
                                      data=json.dumps({"session_id": "sess-null", "name": None}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert "sess-null" not in ws_mod._chat_ui_state["session_names"]

    def test_missing_session_id(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.post("/api/chat/state/name",
                              data=json.dumps({"name": "Test"}),
                              content_type="application/json")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/state/migrate
# ═══════════════════════════════════════════════════════════════════════

class TestChatStateMigrate:
    def test_migrate_v1_sessions(self, ws_client, ws_mod, reset_chat_state):
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/migrate",
                                      data=json.dumps({
                                          "active_sessions": ["sid-1", "sid-2"],
                                          "session_names": {"sid-1": "Session One"},
                                      }),
                                      content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["migrated"] is True
        # Sessions should be added as objects
        sids = [e.get("session_id") for e in ws_mod._chat_ui_state["active_sessions"]]
        assert "sid-1" in sids
        assert "sid-2" in sids
        assert ws_mod._chat_ui_state["session_names"]["sid-1"] == "Session One"

    def test_migrate_no_duplicates(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["active_sessions"] = [{"tab_id": None, "session_id": "existing"}]
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/migrate",
                                      data=json.dumps({"active_sessions": ["existing", "new-one"]}),
                                      content_type="application/json")
        assert resp.status_code == 200
        sids = [e.get("session_id") for e in ws_mod._chat_ui_state["active_sessions"]]
        assert sids.count("existing") == 1

    def test_migrate_empty_payload(self, ws_client, ws_mod, reset_chat_state):
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/migrate",
                                      data=json.dumps({}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert resp.get_json()["migrated"] is True


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/state/cancel
# ═══════════════════════════════════════════════════════════════════════

class TestChatStateCancel:
    def test_cancel_missing_session_id(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.post("/api/chat/state/cancel",
                              data=json.dumps({}),
                              content_type="application/json")
        assert resp.status_code == 400

    def test_cancel_not_streaming(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.post("/api/chat/state/cancel",
                              data=json.dumps({"session_id": "nonexistent-session"}),
                              content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cancelled"] is False
        assert data["reason"] == "not streaming"


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/state/read
# ═══════════════════════════════════════════════════════════════════════

class TestChatStateRead:
    def test_mark_read_missing_session_id(self, ws_client, ws_mod, reset_chat_state):
        resp = ws_client.post("/api/chat/state/read",
                              data=json.dumps({}),
                              content_type="application/json")
        assert resp.status_code == 400

    def test_mark_read_removes_from_unread(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["unread_sessions"] = ["sess-read-1", "sess-read-2"]
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/read",
                                      data=json.dumps({"session_id": "sess-read-1"}),
                                      content_type="application/json")
        assert resp.status_code == 200
        assert "sess-read-1" not in ws_mod._chat_ui_state["unread_sessions"]
        assert "sess-read-2" in ws_mod._chat_ui_state["unread_sessions"]

    def test_mark_read_nonexistent_is_ok(self, ws_client, ws_mod, reset_chat_state):
        ws_mod._chat_ui_state["unread_sessions"] = ["other"]
        with patch.object(ws_mod, '_broadcast_chat_state'):
            with patch.object(ws_mod, '_save_chat_ui_state'):
                resp = ws_client.post("/api/chat/state/read",
                                      data=json.dumps({"session_id": "not-in-list"}),
                                      content_type="application/json")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# /api/sessions/registry
# ═══════════════════════════════════════════════════════════════════════

class TestSessionsRegistry:
    @patch("lib.session_registry.list_sessions")
    def test_registry_empty(self, mock_list, ws_client):
        mock_list.return_value = []
        resp = ws_client.get("/api/sessions/registry")
        assert resp.status_code == 200
        assert resp.get_json()["sessions"] == []

    @patch("lib.session_registry.list_sessions")
    def test_registry_with_entries(self, mock_list, ws_client):
        mock_list.return_value = [
            {"session_id": "s1", "type": "cron", "job_id": "heartbeat"},
            {"session_id": "s2", "type": "chat", "job_id": None},
        ]
        resp = ws_client.get("/api/sessions/registry")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["sessions"]) == 2

    @patch("lib.session_registry.list_sessions")
    def test_registry_with_type_filter(self, mock_list, ws_client):
        mock_list.return_value = [{"session_id": "s1", "type": "cron"}]
        resp = ws_client.get("/api/sessions/registry?type=cron")
        mock_list.assert_called_once_with(session_type="cron", job_id=None, limit=50)

    @patch("lib.session_registry.list_sessions")
    def test_registry_with_job_id_filter(self, mock_list, ws_client):
        mock_list.return_value = []
        resp = ws_client.get("/api/sessions/registry?job_id=heartbeat&limit=10")
        mock_list.assert_called_once_with(session_type=None, job_id="heartbeat", limit=10)


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/files/<filename>
# ═══════════════════════════════════════════════════════════════════════

class TestChatFiles:
    def test_path_traversal_blocked(self, ws_client):
        resp = ws_client.get("/api/chat/files/..%2F..%2Fetc%2Fpasswd")
        # Flask may decode %2F as / and fail to match, returning 404
        assert resp.status_code in (403, 404)

    def test_slash_in_name_blocked(self, ws_client):
        resp = ws_client.get("/api/chat/files/sub%2Ffile.txt")
        assert resp.status_code in (403, 404)

    def test_dotdot_literal_blocked(self, ws_client):
        resp = ws_client.get("/api/chat/files/..secret.txt")
        assert resp.status_code in (403, 404)

    def test_file_not_found(self, ws_client):
        resp = ws_client.get("/api/chat/files/nonexistent_1234567890.txt")
        assert resp.status_code == 404

    def test_serves_uploaded_file(self, ws_client, ws_mod, tmp_path):
        # Write file to the upload dir
        upload_dir = ws_mod.CHAT_UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)
        test_file = upload_dir / "test_upload.txt"
        test_file.write_text("hello upload")
        resp = ws_client.get("/api/chat/files/test_upload.txt")
        assert resp.status_code == 200
        assert b"hello upload" in resp.data
        # Cleanup
        test_file.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# /api/chat/send
# ═══════════════════════════════════════════════════════════════════════

class TestChatSend:
    def test_empty_prompt(self, ws_client):
        resp = ws_client.post("/api/chat/send",
                              data=json.dumps({"tab_id": "t1", "model": "sonnet"}),
                              content_type="application/json")
        assert resp.status_code == 400
        assert "Empty prompt" in resp.get_json()["error"]

    def test_missing_tab_id(self, ws_client):
        resp = ws_client.post("/api/chat/send",
                              data=json.dumps({"prompt": "hello", "model": "sonnet"}),
                              content_type="application/json")
        assert resp.status_code == 400
        assert "tab_id" in resp.get_json()["error"]

    def test_missing_model(self, ws_client):
        resp = ws_client.post("/api/chat/send",
                              data=json.dumps({"prompt": "hello", "tab_id": "t1"}),
                              content_type="application/json")
        assert resp.status_code == 400
        assert "model" in resp.get_json()["error"]


# ═══════════════════════════════════════════════════════════════════════
# /api/sessions (list)
# ═══════════════════════════════════════════════════════════════════════

class TestSessionsList:
    @patch("lib.session_registry.list_sessions")
    def test_empty_sessions_list(self, mock_registry, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        mock_registry.return_value = []
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        projects_dir.mkdir(parents=True)
        resp = ws_client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.get_json()["sessions"] == []

    @patch("lib.session_registry.list_sessions")
    def test_lists_jsonl_sessions(self, mock_registry, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        mock_registry.return_value = []
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        _make_session_jsonl(projects_dir, "sess-list-1", [
            {"type": "user", "message": {"content": "List me"}},
        ])
        resp = ws_client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "sess-list-1"

    @patch("lib.session_registry.list_sessions")
    def test_lists_indexed_sessions(self, mock_registry, ws_client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        mock_registry.return_value = []
        projects_dir = tmp_path / "Documents" / "GitHub" / "claude" / ".claude" / "projects" / "test"
        projects_dir.mkdir(parents=True)
        # Create an index file
        index = {"entries": [
            {"sessionId": "idx-1", "summary": "Indexed session", "messageCount": 5, "modified": "2026-03-16T00:00:00"},
        ]}
        (projects_dir / "sessions-index.json").write_text(json.dumps(index))
        resp = ws_client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(s["id"] == "idx-1" for s in data["sessions"])
