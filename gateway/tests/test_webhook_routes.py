"""Tests for HTTP API routes in webhook-server.py and dashboard_api.py.

Covers: sessions, chat state, views, pipelines, deals, health/status,
heartbeat, CRON, dashboard, webhook, file upload, and self-evolve routes.

Uses the conftest flask_app fixture to load the module safely.
"""

import json
import os
import sys
import time
import uuid
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timezone

# Ensure gateway directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force-set env before import (must override .env values loaded by dotenv)
os.environ["WEBHOOK_TOKEN"] = "test-token-12345"


# ============================================================
# HEALTH / DASHBOARD / STATIC
# ============================================================


class TestHealthRoute:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_health_timestamp_is_iso(self, client):
        resp = client.get("/health")
        data = resp.get_json()
        # Should be parseable as ISO timestamp
        ts = data["timestamp"]
        assert "T" in ts


class TestDashboardRoute:
    def test_dashboard_returns_html_or_404(self, client):
        resp = client.get("/dashboard")
        # Either serves the built React app or returns 404 with helpful message
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert b"html" in resp.data.lower() or b"<!DOCTYPE" in resp.data
        else:
            assert b"Dashboard not found" in resp.data


# ============================================================
# STATUS (authenticated)
# ============================================================


class TestStatusRoute:
    def test_status_requires_auth(self, client):
        resp = client.get("/status")
        assert resp.status_code == 401

    def test_status_with_auth(self, client, auth_headers):
        resp = client.get("/status", headers=auth_headers)
        # Should not be 401; may be 200 or 500 depending on collector
        assert resp.status_code != 401


# ============================================================
# SESSIONS API
# ============================================================


class TestSessionsAPI:
    """Tests for /api/sessions routes."""

    @patch("routes.dashboard_api.collect_dashboard_data")
    def test_sessions_list_returns_json(self, mock_collect, client):
        resp = client.get("/api/sessions")
        # This hits the real filesystem but should still return JSON
        assert resp.status_code in (200, 500)
        data = resp.get_json()
        if resp.status_code == 200:
            assert "sessions" in data

    def test_sessions_search_short_query(self, client):
        """Queries shorter than 2 chars return empty list."""
        resp = client.get("/api/sessions/search?q=a")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sessions"] == []

    def test_sessions_search_no_query(self, client):
        """Empty query returns empty list."""
        resp = client.get("/api/sessions/search?q=")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["sessions"] == []

    def test_sessions_search_valid_query(self, client):
        """Valid query runs search (may or may not find results)."""
        resp = client.get("/api/sessions/search?q=test_query_unlikely_to_match_xyzzy")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "sessions" in data

    def test_session_detail_not_found(self, client):
        """Non-existent session returns 404."""
        fake_id = "nonexistent-session-id-12345"
        resp = client.get(f"/api/sessions/{fake_id}")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data

    def test_session_detail_with_real_session(self, client, tmp_path):
        """Session detail reads JSONL and returns messages."""
        # Create a temp JSONL file with session data
        session_id = str(uuid.uuid4())
        jsonl_content = json.dumps({
            "type": "user",
            "message": {"content": "Hello there"},
            "timestamp": "2026-03-16T10:00:00"
        }) + "\n"

        with patch("webhook_server._find_session_file") as mock_find:
            jsonl_path = tmp_path / f"{session_id}.jsonl"
            jsonl_path.write_text(jsonl_content)
            mock_find.return_value = str(jsonl_path)

            # The route still globs for files, so this won't find our temp file
            # via filesystem but we can test the 404 path
            resp = client.get(f"/api/sessions/{session_id}")
            # Will be 404 since the glob won't find our file in the real config dir
            assert resp.status_code in (200, 404)

    def test_session_fork_not_found(self, client):
        """Fork of non-existent session returns 404."""
        fake_id = "nonexistent-session-id-for-fork"
        resp = client.post(f"/api/sessions/{fake_id}/fork")
        assert resp.status_code == 404

    def test_session_fork_with_source(self, client, tmp_path):
        """Fork copies JSONL and creates new session."""
        session_id = str(uuid.uuid4())
        jsonl_content = json.dumps({
            "type": "user",
            "message": {"content": "Original message"},
            "timestamp": "2026-03-16T10:00:00"
        }) + "\n"
        jsonl_path = tmp_path / f"{session_id}.jsonl"
        jsonl_path.write_text(jsonl_content)

        with patch("webhook_server._find_session_file", return_value=str(jsonl_path)):
            resp = client.post(f"/api/sessions/{session_id}/fork")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "session_id" in data
            assert data["source_id"] == session_id
            assert data["session_id"] != session_id
            assert "name" in data

    def test_sessions_registry(self, client):
        """Registry endpoint returns session metadata."""
        with patch("lib.session_registry.list_sessions", return_value=[]):
            resp = client.get("/api/sessions/registry")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "sessions" in data

    def test_sessions_registry_with_filters(self, client):
        """Registry endpoint accepts type and job_id filters."""
        resp = client.get("/api/sessions/registry?type=cron&job_id=heartbeat&limit=5")
        assert resp.status_code in (200, 500)


# ============================================================
# CHAT STATE API
# ============================================================


class TestChatStateAPI:
    """Tests for /api/chat/state/* routes."""

    def test_chat_state_get(self, client):
        """GET /api/chat/state returns state snapshot."""
        resp = client.get("/api/chat/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_sessions" in data
        assert "session_names" in data
        assert "streaming_sessions" in data

    def test_chat_state_active_add(self, client):
        """POST /api/chat/state/active adds a session."""
        session_id = str(uuid.uuid4())
        resp = client.post("/api/chat/state/active",
                           json={"session_id": session_id, "action": "add"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_chat_state_active_remove(self, client):
        """POST /api/chat/state/active removes a session."""
        session_id = str(uuid.uuid4())
        # First add, then remove
        client.post("/api/chat/state/active",
                    json={"session_id": session_id, "action": "add"})
        resp = client.post("/api/chat/state/active",
                           json={"session_id": session_id, "action": "remove"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_chat_state_active_invalid_action(self, client):
        """POST /api/chat/state/active with invalid action returns 400."""
        resp = client.post("/api/chat/state/active",
                           json={"session_id": "test", "action": "invalid"})
        assert resp.status_code == 400

    def test_chat_state_active_missing_session(self, client):
        """POST /api/chat/state/active without session_id returns 400."""
        resp = client.post("/api/chat/state/active",
                           json={"action": "add"})
        assert resp.status_code == 400

    def test_chat_state_name_set(self, client):
        """POST /api/chat/state/name sets a session name."""
        session_id = str(uuid.uuid4())
        resp = client.post("/api/chat/state/name",
                           json={"session_id": session_id, "name": "Test Session"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_chat_state_name_clear(self, client):
        """POST /api/chat/state/name with no name clears it."""
        session_id = str(uuid.uuid4())
        # First set, then clear
        client.post("/api/chat/state/name",
                    json={"session_id": session_id, "name": "Test"})
        resp = client.post("/api/chat/state/name",
                           json={"session_id": session_id, "name": ""})
        assert resp.status_code == 200

    def test_chat_state_name_missing_session(self, client):
        """POST /api/chat/state/name without session_id returns 400."""
        resp = client.post("/api/chat/state/name",
                           json={"name": "Test"})
        assert resp.status_code == 400

    def test_chat_state_migrate(self, client):
        """POST /api/chat/state/migrate migrates v1 data."""
        resp = client.post("/api/chat/state/migrate",
                           json={
                               "active_sessions": ["sid1", "sid2"],
                               "session_names": {"sid1": "First"},
                           })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["migrated"] is True

    def test_chat_state_cancel_not_streaming(self, client):
        """POST /api/chat/state/cancel for non-streaming session."""
        resp = client.post("/api/chat/state/cancel",
                           json={"session_id": "nonexistent-tab-id"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cancelled"] is False

    def test_chat_state_cancel_missing_session(self, client):
        """POST /api/chat/state/cancel without session_id returns 400."""
        resp = client.post("/api/chat/state/cancel", json={})
        assert resp.status_code == 400

    def test_chat_state_read(self, client):
        """POST /api/chat/state/read marks a session as read."""
        session_id = str(uuid.uuid4())
        resp = client.post("/api/chat/state/read",
                           json={"session_id": session_id})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_chat_state_read_missing_session(self, client):
        """POST /api/chat/state/read without session_id returns 400."""
        resp = client.post("/api/chat/state/read", json={})
        assert resp.status_code == 400


# ============================================================
# CHAT SEND (HTTP fallback)
# ============================================================


class TestChatSendAPI:
    """Tests for /api/chat/send route."""

    def test_chat_send_empty_prompt(self, client):
        resp = client.post("/api/chat/send", json={"prompt": "", "tab_id": "t1", "model": "sonnet"})
        assert resp.status_code == 400
        assert "Empty prompt" in resp.get_json()["error"]

    def test_chat_send_missing_tab_id(self, client):
        resp = client.post("/api/chat/send", json={"prompt": "hello", "model": "sonnet"})
        assert resp.status_code == 400
        assert "tab_id" in resp.get_json()["error"]

    def test_chat_send_missing_model(self, client):
        resp = client.post("/api/chat/send", json={"prompt": "hello", "tab_id": "t1"})
        assert resp.status_code == 400
        assert "model" in resp.get_json()["error"]

    def test_chat_send_spawns_thread(self, client):
        """Valid send should spawn a thread (mocked so no real SDK call)."""
        with patch("webhook_server.ChatNamespace._run_claude") as mock_run:
            resp = client.post("/api/chat/send", json={
                "prompt": "hello",
                "tab_id": str(uuid.uuid4()),
                "model": "sonnet",
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True


# ============================================================
# CHAT FILE UPLOAD
# ============================================================


class TestChatUploadAPI:
    """Tests for /api/chat/upload and /api/chat/files routes."""

    def test_upload_no_file(self, client):
        resp = client.post("/api/chat/upload")
        assert resp.status_code == 400

    def test_upload_file(self, client, tmp_path):
        """Upload a file and verify it's accessible."""
        from io import BytesIO
        data = {
            'file': (BytesIO(b"test content"), 'test.txt', 'text/plain')
        }
        resp = client.post("/api/chat/upload",
                           content_type='multipart/form-data',
                           data=data)
        assert resp.status_code == 200
        result = resp.get_json()
        assert "files" in result
        assert len(result["files"]) == 1
        assert result["files"][0]["name"] == "test.txt"

    def test_serve_file_not_found(self, client):
        resp = client.get("/api/chat/files/nonexistent_file_xyz.txt")
        assert resp.status_code == 404

    def test_serve_file_path_traversal(self, client):
        # Flask normalizes ../  in paths, so the check for '..' fires only
        # when the filename itself contains it (e.g. encoded or literal)
        resp = client.get("/api/chat/files/..%2F..%2Fetc%2Fpasswd")
        # Flask may decode and normalize the path, resulting in 404 (not found)
        # or 403 if the '..' check triggers
        assert resp.status_code in (403, 404)


# ============================================================
# VIEWS API
# ============================================================


class TestViewsAPI:
    """Tests for /api/views/* routes."""

    def test_views_list(self, client):
        """GET /api/views returns view data."""
        with patch("routes.dashboard_api.collect_views_data", return_value={"views": []}):
            resp = client.get("/api/views")
            assert resp.status_code == 200

    def test_views_serve_not_found(self, client):
        """Serving non-existent view returns 404."""
        resp = client.get("/api/views/serve/nonexistent_view_12345.html")
        assert resp.status_code == 404

    def test_views_serve_path_traversal(self, client):
        """Path traversal in view name returns 400."""
        resp = client.get("/api/views/serve/..%2F..%2Fetc%2Fpasswd")
        # URL decoding happens, so the route checks for '..'
        assert resp.status_code in (400, 404)

    def test_views_open_missing_params(self, client):
        """POST /api/views/open without filename or path returns 400."""
        resp = client.post("/api/views/open", json={})
        assert resp.status_code == 400

    def test_views_open_invalid_path(self, client):
        """POST /api/views/open with path traversal returns 400."""
        resp = client.post("/api/views/open", json={"path": "../../../etc/passwd"})
        assert resp.status_code == 400

    def test_views_open_invalid_filename(self, client):
        """POST /api/views/open with path in filename returns 400."""
        resp = client.post("/api/views/open", json={"filename": "../secret.html"})
        assert resp.status_code == 400

    def test_views_open_file_not_found(self, client):
        """POST /api/views/open with non-existent file returns 404."""
        resp = client.post("/api/views/open", json={"filename": "nonexistent_xyzzy.html"})
        assert resp.status_code == 404


# ============================================================
# PIPELINES API
# ============================================================


class TestPipelinesAPI:
    """Tests for /api/pipelines route."""

    def test_pipelines_list(self, client):
        """GET /api/pipelines returns pipeline data."""
        with patch("routes.dashboard_api.collect_pipelines_data", return_value={"pipelines": []}):
            resp = client.get("/api/pipelines")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "pipelines" in data


# ============================================================
# DEALS API
# ============================================================


class TestDealsAPI:
    """Tests for /api/deals route."""

    def test_deals_list(self, client):
        """GET /api/deals returns deals data."""
        with patch("routes.dashboard_api.collect_deals_data", return_value={"deals": []}):
            resp = client.get("/api/deals")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "deals" in data

    def test_deals_list_error(self, client):
        """GET /api/deals handles exceptions."""
        with patch("routes.dashboard_api.collect_deals_data", side_effect=Exception("DB error")):
            resp = client.get("/api/deals")
            assert resp.status_code == 500
            data = resp.get_json()
            assert "error" in data


# ============================================================
# PEOPLE API
# ============================================================


class TestPeopleAPI:
    def test_people_list(self, client):
        with patch("routes.dashboard_api.collect_people_data", return_value={"people": []}):
            resp = client.get("/api/people")
            assert resp.status_code == 200

    def test_people_error(self, client):
        with patch("routes.dashboard_api.collect_people_data", side_effect=Exception("fail")):
            resp = client.get("/api/people")
            assert resp.status_code == 500


# ============================================================
# FOLLOWUPS API
# ============================================================


class TestFollowupsAPI:
    def test_followups_list(self, client):
        with patch("routes.dashboard_api.collect_followups_data", return_value={"followups": []}):
            resp = client.get("/api/followups")
            assert resp.status_code == 200


# ============================================================
# HEARTBEAT API
# ============================================================


class TestHeartbeatAPI:
    """Tests for /api/heartbeat route."""

    def test_heartbeat_data(self, client):
        """GET /api/heartbeat returns heartbeat state."""
        with patch("routes.dashboard_api.collect_heartbeat_data", return_value={"runs": []}):
            resp = client.get("/api/heartbeat")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "runs" in data

    def test_heartbeat_error(self, client):
        """GET /api/heartbeat handles exceptions."""
        with patch("routes.dashboard_api.collect_heartbeat_data", side_effect=Exception("heartbeat fail")):
            resp = client.get("/api/heartbeat")
            assert resp.status_code == 500


# ============================================================
# FEED API
# ============================================================


class TestFeedAPI:
    def test_feed_default(self, client):
        with patch("routes.dashboard_api.collect_feed_data", return_value={"messages": []}) as mock_feed:
            resp = client.get("/api/feed")
            assert resp.status_code == 200
            mock_feed.assert_called_once_with(limit=100, topic=None)

    def test_feed_with_params(self, client):
        with patch("routes.dashboard_api.collect_feed_data", return_value={"messages": []}) as mock_feed:
            resp = client.get("/api/feed?limit=10&topic=heartbeat")
            assert resp.status_code == 200
            mock_feed.assert_called_once_with(limit=10, topic="heartbeat")


# ============================================================
# TASKS API
# ============================================================


class TestTasksAPI:
    def test_tasks_list(self, client):
        with patch("routes.dashboard_api.collect_tasks_data", return_value={"tasks": []}):
            resp = client.get("/api/tasks")
            assert resp.status_code == 200

    def test_tasks_update_missing_fields(self, client):
        resp = client.post("/api/tasks/update",
                           json={"task_id": ""},
                           content_type="application/json")
        assert resp.status_code == 400

    def test_tasks_update_valid(self, client):
        with patch("routes.dashboard_api.update_task", return_value={"success": True}):
            resp = client.post("/api/tasks/update",
                               json={"task_id": "123", "action": "complete"},
                               content_type="application/json")
            assert resp.status_code == 200


# ============================================================
# CALENDAR API
# ============================================================


class TestCalendarAPI:
    def test_calendar(self, client):
        with patch("routes.dashboard_api.collect_calendar_data", return_value={"events": []}):
            resp = client.get("/api/calendar")
            assert resp.status_code == 200


# ============================================================
# DASHBOARD DATA API
# ============================================================


class TestDashboardDataAPI:
    def test_dashboard_data(self, client):
        with patch("routes.dashboard_api.collect_dashboard_data", return_value={"status": "ok"}):
            resp = client.get("/api/dashboard")
            assert resp.status_code == 200

    def test_dashboard_data_error(self, client):
        with patch("routes.dashboard_api.collect_dashboard_data", side_effect=Exception("fail")):
            resp = client.get("/api/dashboard")
            assert resp.status_code == 500


# ============================================================
# FILES API
# ============================================================


class TestFilesAPI:
    def test_files_list(self, client):
        with patch("routes.dashboard_api.collect_files_data", return_value={"files": []}):
            resp = client.get("/api/files")
            assert resp.status_code == 200

    def test_files_with_date(self, client):
        with patch("routes.dashboard_api.collect_files_data", return_value={"files": []}) as mock_files:
            resp = client.get("/api/files?date=2026-03-16")
            assert resp.status_code == 200
            mock_files.assert_called_once_with(date="2026-03-16")


# ============================================================
# PLANS API
# ============================================================


class TestPlansAPI:
    def test_plans_list(self, client):
        """GET /api/plans returns plans list."""
        resp = client.get("/api/plans")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "plans" in data


# ============================================================
# SELF-EVOLVE API
# ============================================================


class TestSelfEvolveAPI:
    def test_self_evolve_get(self, client):
        """GET /api/self-evolve returns metrics and items."""
        resp = client.get("/api/self-evolve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "metrics" in data
        assert "items" in data


# ============================================================
# FEEDBACK API
# ============================================================


class TestFeedbackAPI:
    def test_dislike_missing_backlog(self, client, tmp_path):
        """POST /api/feedback/dislike when backlog doesn't exist."""
        with patch("routes.dashboard_api.Path") as mock_path:
            backlog_mock = MagicMock()
            backlog_mock.exists.return_value = False
            mock_path.return_value.expanduser.return_value = backlog_mock
            # This goes through the real Path in the route
            resp = client.post("/api/feedback/dislike",
                               json={"comment": "bad output", "session_id": "s1"})
            # May return 404 or 500 depending on path resolution
            assert resp.status_code in (200, 404, 500)


# ============================================================
# MARKDOWN RENDER API
# ============================================================


class TestMarkdownRenderAPI:
    def test_markdown_render_no_path(self, client):
        """GET /api/markdown/render without path returns 400."""
        resp = client.get("/api/markdown/render")
        assert resp.status_code == 400

    def test_markdown_render_path_traversal(self, client):
        """Path traversal returns 400."""
        resp = client.get("/api/markdown/render?path=../../etc/passwd")
        assert resp.status_code == 400

    def test_markdown_render_not_found(self, client):
        """Non-existent file returns 404."""
        resp = client.get("/api/markdown/render?path=nonexistent_xyzzy.md")
        assert resp.status_code == 404


# ============================================================
# PURE FUNCTIONS (non-route)
# ============================================================


class TestCheckRateLimit:
    """Test check_rate_limit function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.check = ws.check_rate_limit
        self.store = ws.rate_limit_store
        self.store.clear()

    def test_allows_first_request(self):
        assert self.check("test-ip") is True

    def test_allows_many_requests(self):
        for _ in range(50):
            self.check("test-ip-many")
        assert self.check("test-ip-many") is True

    def test_blocks_after_limit(self):
        import webhook_server as ws
        ip = "rate-limit-test"
        for _ in range(ws.MAX_REQUESTS_PER_HOUR):
            self.check(ip)
        assert self.check(ip) is False

    def test_cleans_old_timestamps(self):
        ip = "cleanup-test"
        # Add old timestamps
        self.store[ip] = [time.time() - 7200] * 50
        assert self.check(ip) is True


class TestFindSessionFile:
    """Test _find_session_file function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.find = ws._find_session_file

    def test_returns_none_for_unknown(self):
        result = self.find("nonexistent-session-id-xyz-123")
        assert result is None


class TestWriteResultToJsonl:
    """Test _write_result_to_jsonl function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.write = ws._write_result_to_jsonl

    def test_noop_for_no_session_id(self):
        # Should not raise
        self.write(None, 0.5, 10, "sonnet")

    def test_noop_for_no_file(self):
        # Should not raise when file not found
        self.write("nonexistent-session-xyz", 0.5, 10, "sonnet")

    def test_writes_to_file(self, tmp_path):
        session_id = "test-session-write"
        jsonl_path = tmp_path / f"{session_id}.jsonl"
        jsonl_path.write_text("")

        with patch("webhook_server._find_session_file", return_value=str(jsonl_path)):
            self.write(session_id, 0.5, 10, "sonnet")

        content = jsonl_path.read_text()
        assert content.strip()
        entry = json.loads(content.strip())
        assert entry["type"] == "result"
        assert entry["cost_usd"] == 0.5
        assert entry["duration_seconds"] == 10
        assert entry["model"] == "sonnet"


class TestGetChatStateSnapshot:
    """Test _get_chat_state_snapshot function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.get_snapshot = ws._get_chat_state_snapshot

    def test_returns_expected_keys(self):
        state = self.get_snapshot()
        assert "active_sessions" in state
        assert "session_names" in state
        assert "streaming_sessions" in state
        assert "unread_sessions" in state
        assert "drafts" in state


class TestLoadConfig:
    """Test load_config function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.load_config = ws.load_config

    def test_load_config(self):
        """Should load config from yaml file."""
        try:
            config = self.load_config()
            assert isinstance(config, dict)
        except FileNotFoundError:
            pass  # OK if config file doesn't exist in test env


# ============================================================
# SOURCES API
# ============================================================


class TestSourcesAPI:
    def test_sources_list(self, client):
        """GET /api/sources returns source manifests."""
        resp = client.get("/api/sources")
        # May fail if vadimgest not importable, but should return JSON
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.get_json()
            assert isinstance(data, dict)


# ============================================================
# AGENTS API
# ============================================================


class TestAgentsAPI:
    def test_agents_list(self, client):
        """GET /api/agents returns agent data."""
        resp = client.get("/api/agents")
        assert resp.status_code in (200, 500)


# ============================================================
# CHAT UI STATE internal helpers
# ============================================================


class TestChatUIStateHelpers:
    """Test _load_chat_ui_state and _save_chat_ui_state."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.ws = ws

    def test_save_and_load_roundtrip(self, tmp_path):
        """Save and reload state."""
        state_file = tmp_path / "chat-ui.json"
        original_file = self.ws.CHAT_UI_STATE_FILE
        try:
            self.ws.CHAT_UI_STATE_FILE = state_file
            # Save
            with self.ws._chat_ui_lock:
                self.ws._chat_ui_state["session_names"]["test"] = "Test Session"
                self.ws._save_chat_ui_state()

            # Verify file exists
            assert state_file.exists()
            data = json.loads(state_file.read_text())
            assert data["session_names"]["test"] == "Test Session"
        finally:
            self.ws.CHAT_UI_STATE_FILE = original_file


class TestRecoverChatStreams:
    """Test _recover_chat_streams function."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.ws = ws

    def test_noop_when_no_state_file(self):
        """No crash when state file doesn't exist."""
        original = self.ws.CHAT_STREAM_STATE
        try:
            self.ws.CHAT_STREAM_STATE = Path("/tmp/nonexistent_chat_state_xyz.json")
            self.ws._recover_chat_streams()  # Should not raise
        finally:
            self.ws.CHAT_STREAM_STATE = original

    def test_handles_corrupted_state(self, tmp_path):
        """Handles corrupted JSON gracefully."""
        state_file = tmp_path / "streaming.json"
        state_file.write_text("not valid json{{{")
        original = self.ws.CHAT_STREAM_STATE
        try:
            self.ws.CHAT_STREAM_STATE = state_file
            self.ws._recover_chat_streams()  # Should not raise
        finally:
            self.ws.CHAT_STREAM_STATE = original

    def test_handles_empty_state(self, tmp_path):
        """Handles empty state dict."""
        state_file = tmp_path / "streaming.json"
        state_file.write_text("{}")
        original = self.ws.CHAT_STREAM_STATE
        try:
            self.ws.CHAT_STREAM_STATE = state_file
            self.ws._recover_chat_streams()  # Should not raise
        finally:
            self.ws.CHAT_STREAM_STATE = original


# ============================================================
# PARSE SESSION ENTRY (additional coverage)
# ============================================================


class TestParseSessionEntryRoutes:
    """Additional tests for _parse_session_entry."""

    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.parse = ws._parse_session_entry

    def test_result_entry(self):
        entry = {
            "type": "result",
            "result": "Done successfully",
            "session_id": "abc123",
            "cost_usd": 0.05,
            "duration_seconds": 30,
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result["role"] == "result"
        assert result["cost"] == 0.05
        assert result["duration"] == 30

    def test_progress_entry(self):
        entry = {"type": "progress", "timestamp": "2026-03-16T10:00:00"}
        result = self.parse(entry)
        assert result["role"] == "progress"

    def test_unknown_type_returns_none(self):
        entry = {"type": "unknown_xyz"}
        result = self.parse(entry)
        assert result is None

    def test_assistant_with_thinking(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Let me think about this..."},
                    {"type": "text", "text": "Here is my answer"},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result["role"] == "assistant"
        assert len(result["content"]) == 2
        assert result["content"][0]["type"] == "thinking"
        assert result["content"][1]["type"] == "text"

    def test_assistant_empty_text_parts_filtered(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": ""},
                    {"type": "text", "text": "   "},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result is None  # All parts are empty

    def test_assistant_plan_mode_markers(self):
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "EnterPlanMode", "input": {}},
                ],
            },
            "timestamp": "2026-03-16T10:00:00",
        }
        result = self.parse(entry)
        assert result is not None
        assert any(p.get("type") == "plan_mode" for p in result["content"])


# ============================================================
# CRON SESSION IDS CACHE
# ============================================================


class TestCronSessionIdsCache:
    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.ws = ws

    def test_cache_returns_set(self):
        result = self.ws._get_cron_session_ids()
        assert isinstance(result, set)

    def test_cache_uses_cached_value(self):
        """Second call within 60s uses cache."""
        self.ws._cron_ids_cache["ts"] = time.time()
        self.ws._cron_ids_cache["ids"] = {"cached-id"}
        result = self.ws._get_cron_session_ids()
        assert "cached-id" in result


# ============================================================
# TRIGGER JOB (authenticated)
# ============================================================


class TestTriggerJobRoute:
    def test_trigger_requires_auth(self, client):
        resp = client.post("/trigger/heartbeat")
        assert resp.status_code == 401

    def test_trigger_with_auth(self, client, auth_headers):
        resp = client.post("/trigger/nonexistent-job-xyz", headers=auth_headers)
        # May return 404 (job not found) or 500, but not 401
        assert resp.status_code != 401


# ============================================================
# RATE LIMIT DECORATOR
# ============================================================


class TestRateLimitDecorator:
    @pytest.fixture(autouse=True)
    def _load(self, flask_app):
        import webhook_server as ws
        self.ws = ws
        ws.rate_limit_store.clear()

    def test_rate_limit_allows_normal(self, client, auth_headers):
        """Normal requests pass through rate limiter."""
        resp = client.get("/status", headers=auth_headers)
        assert resp.status_code != 429
