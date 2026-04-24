"""Tests for API endpoints (now in Blueprint modules).

Tests key endpoints with mocked collector functions to avoid real I/O.
Verifies HTTP status codes, JSON structure, and path traversal protection.

Mock targets point to the Blueprint module where the function reference lives:
- routes.dashboard_api for dashboard/data routes
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("WEBHOOK_TOKEN", "test-token-12345")


class TestApiDashboard:
    @patch("routes.dashboard_api.collect_dashboard_data")
    def test_returns_json(self, mock_collect, client):
        mock_collect.return_value = {"generated_at": "2026-02-23T12:00:00", "stats": {}}
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.get_json()
        assert "generated_at" in data

    @patch("routes.dashboard_api.collect_dashboard_data")
    def test_no_auth_required(self, mock_collect, client):
        mock_collect.return_value = {}
        response = client.get("/api/dashboard")
        assert response.status_code == 200

    @patch("routes.dashboard_api.collect_dashboard_data")
    def test_error_returns_500(self, mock_collect, client):
        mock_collect.side_effect = RuntimeError("database error")
        response = client.get("/api/dashboard")
        assert response.status_code == 500
        data = response.get_json()
        assert "error" in data


class TestApiFiles:
    @patch("routes.dashboard_api.collect_files_data")
    def test_returns_json(self, mock_collect, client):
        mock_collect.return_value = {"commits": [], "date": "2026-02-23"}
        response = client.get("/api/files")
        assert response.status_code == 200

    @patch("routes.dashboard_api.collect_files_data")
    def test_accepts_date_param(self, mock_collect, client):
        mock_collect.return_value = {"commits": []}
        response = client.get("/api/files?date=2026-02-20")
        assert response.status_code == 200
        mock_collect.assert_called_with(date="2026-02-20")

    @patch("routes.dashboard_api.collect_files_data")
    def test_error_returns_500(self, mock_collect, client):
        mock_collect.side_effect = RuntimeError("fail")
        response = client.get("/api/files")
        assert response.status_code == 500


class TestApiTasks:
    @patch("routes.dashboard_api.collect_tasks_data")
    def test_returns_json(self, mock_collect, client):
        mock_collect.return_value = {"google_tasks": [], "github_issues": []}
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @patch("routes.dashboard_api.collect_tasks_data")
    def test_error_returns_500(self, mock_collect, client):
        mock_collect.side_effect = RuntimeError("fail")
        response = client.get("/api/tasks")
        assert response.status_code == 500


class TestApiDeals:
    @patch("routes.dashboard_api.collect_deals_data")
    def test_returns_json(self, mock_collect, client):
        mock_collect.return_value = {
            "metrics": {"total_pipeline": 100000},
            "deals": [],
            "pipeline_stages": [],
        }
        response = client.get("/api/deals")
        assert response.status_code == 200
        data = response.get_json()
        assert "metrics" in data
        assert "deals" in data

    @patch("routes.dashboard_api.collect_deals_data")
    def test_error_returns_500(self, mock_collect, client):
        mock_collect.side_effect = RuntimeError("fail")
        response = client.get("/api/deals")
        assert response.status_code == 500


class TestApiPeople:
    @patch("routes.dashboard_api.collect_people_data")
    def test_returns_json(self, mock_collect, client):
        mock_collect.return_value = {"people": [], "total": 0}
        response = client.get("/api/people")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)

    @patch("routes.dashboard_api.collect_people_data")
    def test_error_returns_500(self, mock_collect, client):
        mock_collect.side_effect = RuntimeError("fail")
        response = client.get("/api/people")
        assert response.status_code == 500


class TestApiViewsServe:
    def test_path_traversal_blocked(self, client):
        response = client.get("/api/views/serve/..%2F..%2Fetc%2Fpasswd")
        assert response.status_code in (400, 404)

    def test_slash_in_filename_blocked(self, client):
        response = client.get("/api/views/serve/sub/file.html")
        assert response.status_code in (400, 404)

    def test_nonexistent_file_404(self, client):
        response = client.get("/api/views/serve/nonexistent-file-12345.html")
        assert response.status_code == 404


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
