"""Tests for gateway/routes/a2a.py - A2A webhook routes."""

import json
import os
import sys
import time
import types
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Pure function tests (no Flask needed) ──

class TestBuildWebhookHeartbeatReport:
    """Test _build_webhook_heartbeat_report pure function."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from routes.a2a import _build_webhook_heartbeat_report
        self.build = _build_webhook_heartbeat_report

    def test_basic_report(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 45,
            "output": "Did something useful",
        }
        result = self.build(entry)
        assert result is not None
        assert "Heartbeat" in result
        assert "45s" in result
        assert "Did something useful" in result

    def test_with_action_deltas(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 30,
            "output": "Processed items",
            "deltas": [
                {"type": "gtask", "title": "Follow up AcmeCorp"},
                {"type": "obsidian", "path": "People/John.md", "change": "updated"},
                {"type": "gmail", "subject": "Re: Proposal"},
                {"type": "calendar", "title": "Sync call"},
                {"type": "deal", "deal": "AcmeCorp", "change": "stage updated"},
                {"type": "other_type", "title": "Random item"},
            ],
        }
        result = self.build(entry)
        assert "ACTIONS" in result
        assert "6" in result  # 6 action deltas
        assert "GTask" in result
        assert "Gmail draft" in result
        assert "Calendar" in result
        assert "Deal" in result

    def test_skipped_deltas_ignored(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 10,
            "output": "OK",
            "deltas": [
                {"type": "skipped", "reason": "duplicate"},
                {"type": "gtask", "title": "Real task"},
            ],
        }
        result = self.build(entry)
        assert "1" in result  # only 1 action delta

    def test_heartbeat_ok_filtered(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 5,
            "output": "HEARTBEAT_OK\nINTAKE: nothing new",
        }
        result = self.build(entry)
        # Both HEARTBEAT_OK and INTAKE: lines are filtered
        assert result is None  # nothing left after filtering

    def test_empty_output_returns_none(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 5,
            "output": "",
        }
        result = self.build(entry)
        assert result is None

    def test_no_output_key(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 0,
        }
        result = self.build(entry)
        assert result is None

    def test_webhook_tag_present(self):
        entry = {
            "timestamp": "2026-03-16T10:30:00+00:00",
            "duration_seconds": 120,
            "output": "Some real content here with data",
        }
        result = self.build(entry)
        assert "[webhook]" in result

    def test_invalid_timestamp_graceful(self):
        entry = {
            "timestamp": "not-a-date",
            "duration_seconds": 10,
            "output": "Some output text",
        }
        # Should not crash
        result = self.build(entry)
        assert result is not None


class TestCheckAuth:
    """Test _check_auth helper."""

    @pytest.fixture
    def app(self):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp
        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={"webhook": {"token": "test-token"}},
            executor=MagicMock(),
            sessions_dir=Path("/tmp"),
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app

    def test_missing_auth_header(self, app):
        """Endpoints reject requests without auth."""
        # Use sessions/list as a test endpoint since it's simple
        # But we need to mock _check_rate_limit to avoid webhook_server import
        with patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list")
                assert resp.status_code == 401
                assert "Missing Authorization" in resp.get_json()["error"]

    def test_invalid_auth_format(self, app):
        with patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list", headers={"Authorization": "Basic abc"})
                assert resp.status_code == 401
                assert "Invalid Authorization" in resp.get_json()["error"]

    def test_wrong_token(self, app, monkeypatch):
        monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
        with patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list", headers={"Authorization": "Bearer wrong-token"})
                assert resp.status_code == 401

    def test_valid_token(self, app, monkeypatch):
        monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
        with patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list", headers={"Authorization": "Bearer test-token"})
                # Should not be 401 (may be other status depending on sessions_dir)
                assert resp.status_code != 401


class TestSessionsListRoute:
    """Test /sessions/list endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path

    def test_empty_sessions(self, setup):
        app, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list")
                data = resp.get_json()
                assert data["total_count"] == 0
                assert data["sessions"] == []

    def test_lists_sessions(self, setup):
        app, tmp_path = setup
        # Create session files
        (tmp_path / "tg_12345_claude_session.txt").write_text("sess-abc-123-full-id")
        (tmp_path / "main_claude_session.txt").write_text("short")

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list")
                data = resp.get_json()
                assert data["total_count"] == 2
                keys = [s["key"] for s in data["sessions"]]
                assert "tg_12345" in keys
                assert "main" in keys

    def test_session_id_truncated(self, setup):
        app, tmp_path = setup
        long_id = "a" * 50
        (tmp_path / "test_claude_session.txt").write_text(long_id)

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list")
                data = resp.get_json()
                sess = data["sessions"][0]
                assert sess["session_id"].endswith("...")
                assert len(sess["session_id"]) == 19  # 16 + "..."


class TestSessionsHistoryRoute:
    """Test /sessions/<key>/history endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path

    def test_missing_log_returns_empty(self, setup):
        app, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/nonexistent/history")
                data = resp.get_json()
                assert data["messages"] == []
                assert data["total_count"] == 0

    def test_reads_jsonl_log(self, setup):
        app, tmp_path = setup
        log = tmp_path / "mykey_log.jsonl"
        entries = [
            {"role": "user", "text": "hello"},
            {"role": "assistant", "text": "hi there"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/mykey/history")
                data = resp.get_json()
                assert data["total_count"] == 2
                assert data["messages"][0]["role"] == "user"

    def test_limit_param(self, setup):
        app, tmp_path = setup
        log = tmp_path / "big_log.jsonl"
        entries = [{"id": i} for i in range(100)]
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/big/history?limit=5")
                data = resp.get_json()
                assert data["total_count"] == 5

    def test_skips_bad_json(self, setup):
        app, tmp_path = setup
        log = tmp_path / "bad_log.jsonl"
        log.write_text('{"ok": true}\nnot json\n{"also": "ok"}\n')

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/bad/history")
                data = resp.get_json()
                assert data["total_count"] == 2


class TestMessageRoute:
    """Test /message/<session> endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Done",
            "cost": 0.01,
            "duration": 5,
        }

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, mock_executor

    def test_missing_prompt(self, setup):
        app, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/message/sess-123", json={})
                assert resp.status_code == 400
                assert "Missing" in resp.get_json()["error"]

    def test_send_message(self, setup):
        app, mock_executor = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/message/sess-123", json={"prompt": "Hello"})
                data = resp.get_json()
                assert data["status"] == "sent"
                assert data["result"]["success"] is True
                assert data["result"]["cost"] == 0.01
                mock_executor.run.assert_called_once()

    def test_passes_model_and_timeout(self, setup):
        app, mock_executor = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/message/sess-123", json={
                    "prompt": "Test", "model": "opus", "timeout": 600
                })
                call_kwargs = mock_executor.run.call_args
                assert call_kwargs.kwargs.get("model") == "opus" or call_kwargs[1].get("model") == "opus"


class TestSessionsSendRoute:
    """Test /sessions/<key>/send endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Executed",
            "cost": 0.02,
            "error": None,
        }

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path, mock_executor

    def test_session_not_found(self, setup):
        app, tmp_path, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/nonexistent/send", json={"prompt": "hi"})
                assert resp.status_code == 404

    def test_missing_prompt(self, setup):
        app, tmp_path, _ = setup
        (tmp_path / "mykey_claude_session.txt").write_text("sess-id")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/mykey/send", json={})
                assert resp.status_code == 400

    def test_successful_send(self, setup):
        app, tmp_path, mock_executor = setup
        (tmp_path / "mykey_claude_session.txt").write_text("sess-full-id")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/mykey/send", json={"prompt": "do stuff"})
                data = resp.get_json()
                assert data["status"] == "completed"
                assert data["session_key"] == "mykey"
                mock_executor.run.assert_called_once()


class TestSessionsSpawnRoute:
    """Test /sessions/spawn endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Spawned result",
            "session_id": "new-sess-id-12345",
            "cost": 0.03,
            "error": None,
        }

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path, mock_executor

    def test_missing_prompt(self, setup):
        app, _, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/spawn", json={})
                assert resp.status_code == 400

    def test_spawn_creates_session_file(self, setup):
        app, tmp_path, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/spawn", json={"prompt": "do task"})
                data = resp.get_json()
                assert data["status"] == "completed"
                assert data["subagent_key"].startswith("subagent_")
                # Session file should be created
                session_files = list(tmp_path.glob("subagent_*_claude_session.txt"))
                assert len(session_files) == 1
                assert session_files[0].read_text() == "new-sess-id-12345"

    def test_spawn_no_session_id(self, setup):
        app, tmp_path, mock_executor = setup
        mock_executor.run.return_value = {"result": "OK", "cost": 0.0, "error": None}
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/spawn", json={"prompt": "quick task"})
                data = resp.get_json()
                assert data["status"] == "completed"
                # No session file created
                session_files = list(tmp_path.glob("subagent_*_claude_session.txt"))
                assert len(session_files) == 0


class TestStatusRoute:
    """Test /status endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app

    def test_status_success(self, setup):
        app = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.status_collector.collect_status", return_value={"status": "ok"}):
            with app.test_client() as client:
                resp = client.get("/status")
                assert resp.status_code == 200
                assert resp.get_json()["status"] == "ok"

    def test_status_auth_failure(self, setup):
        app = setup
        with patch("routes.a2a._check_auth", return_value=(json.dumps({"error": "no auth"}), 401)), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/status")
                assert resp.status_code == 401

    def test_status_rate_limit(self, setup):
        app = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=(json.dumps({"error": "rate limited"}), 429)):
            with app.test_client() as client:
                resp = client.get("/status")
                assert resp.status_code == 429

    def test_status_exception(self, setup):
        app = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.status_collector.collect_status", side_effect=Exception("boom")):
            with app.test_client() as client:
                resp = client.get("/status")
                assert resp.status_code == 500


class TestTriggerRoute:
    """Test /trigger/<job_id> endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Job output",
            "session_id": "job-sess-123",
            "cost": 0.05,
            "duration": 30,
            "error": None,
        }

        jobs_file = tmp_path / "jobs.json"
        jobs_data = {
            "jobs": [
                {
                    "id": "heartbeat",
                    "name": "Heartbeat",
                    "enabled": True,
                    "execution": {
                        "prompt_template": "Run heartbeat at {{now}}",
                        "mode": "isolated",
                        "model": "sonnet",
                        "timeout_seconds": 120,
                    },
                    "telegram_topic": 100001,
                },
                {
                    "id": "disabled-job",
                    "name": "Disabled",
                    "enabled": False,
                    "execution": {"prompt_template": "Do nothing"},
                },
            ]
        }
        jobs_file.write_text(json.dumps(jobs_data))

        runs_log = tmp_path / "runs.jsonl"
        runs_log.touch()

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={"cron": {"jobs_file": str(jobs_file), "runs_log": str(runs_log)}},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path, mock_executor

    def test_job_not_found(self, setup):
        app, _, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/trigger/nonexistent")
                assert resp.status_code == 404

    def test_disabled_job(self, setup):
        app, _, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/trigger/disabled-job")
                assert resp.status_code == 400
                assert "disabled" in resp.get_json()["error"]

    def test_trigger_executes_job(self, setup):
        app, tmp_path, mock_executor = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.feed.send_feed"):  # don't send real TG messages
            with app.test_client() as client:
                resp = client.post("/trigger/heartbeat")
                data = resp.get_json()
                assert data["status"] == "executed"
                assert data["job_id"] == "heartbeat"
                assert data["result"]["success"] is True
                mock_executor.run.assert_called_once()

    def test_trigger_logs_run(self, setup):
        app, tmp_path, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.feed.send_feed"):
            with app.test_client() as client:
                client.post("/trigger/heartbeat")
                runs_log = tmp_path / "runs.jsonl"
                content = runs_log.read_text()
                assert "heartbeat" in content
                entry = json.loads(content.strip())
                assert entry["trigger"] == "webhook"

    def test_trigger_replaces_now_template(self, setup):
        app, _, mock_executor = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.feed.send_feed"):
            with app.test_client() as client:
                client.post("/trigger/heartbeat")
                call_kwargs = mock_executor.run.call_args
                prompt = call_kwargs.kwargs.get("prompt", call_kwargs[1].get("prompt", ""))
                # {{now}} should be replaced with ISO timestamp
                assert "{{now}}" not in prompt

    def test_deltas_parsing(self, setup):
        app, tmp_path, mock_executor = setup
        mock_executor.run.return_value = {
            "result": 'Some output---DELTAS---[{"type":"gtask","title":"test"}]',
            "session_id": "sess",
            "cost": 0.01,
            "duration": 5,
            "error": None,
        }
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.feed.send_feed"):
            with app.test_client() as client:
                client.post("/trigger/heartbeat")
                runs_log = tmp_path / "runs.jsonl"
                entry = json.loads(runs_log.read_text().strip())
                assert entry["output"] == "Some output"
                assert entry["deltas"] == [{"type": "gtask", "title": "test"}]

    def test_deltas_bad_json(self, setup):
        """Malformed deltas JSON should be stored as None."""
        app, tmp_path, mock_executor = setup
        mock_executor.run.return_value = {
            "result": "output---DELTAS---not-json",
            "session_id": "sess",
            "cost": 0.01,
            "duration": 5,
            "error": None,
        }
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.feed.send_feed"):
            with app.test_client() as client:
                client.post("/trigger/heartbeat")
                runs_log = tmp_path / "runs.jsonl"
                entry = json.loads(runs_log.read_text().strip())
                assert entry["deltas"] is None
                assert entry["output"] == "output"

    def test_trigger_with_main_session(self, tmp_path):
        """Test trigger with $main session_id."""
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "output",
            "session_id": "new-sess-id",
            "cost": 0.01,
            "duration": 5,
            "error": None,
        }

        jobs_file = tmp_path / "jobs.json"
        jobs_data = {
            "jobs": [{
                "id": "main-job",
                "name": "Main Job",
                "enabled": True,
                "execution": {
                    "prompt_template": "Do main thing at {{now_eet}}",
                    "mode": "main",
                    "session_id": "$main",
                    "model": "sonnet",
                    "timeout_seconds": 120,
                },
            }]
        }
        jobs_file.write_text(json.dumps(jobs_data))
        runs_log = tmp_path / "runs.jsonl"
        runs_log.touch()

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={"cron": {"jobs_file": str(jobs_file), "runs_log": str(runs_log)}},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.main_session.get_main_session_id", return_value="main-sess-123"), \
             patch("lib.main_session.save_main_session_id") as mock_save:
            with app.test_client() as client:
                resp = client.post("/trigger/main-job")
                data = resp.get_json()
                assert data["status"] == "executed"
                mock_save.assert_called_once_with("new-sess-id")
                # Verify {{now_eet}} was replaced
                call_kwargs = mock_executor.run.call_args
                prompt = call_kwargs.kwargs.get("prompt", call_kwargs[1].get("prompt", ""))
                assert "{{now_eet}}" not in prompt

    def test_trigger_main_session_not_found(self, tmp_path):
        """When $main session_id is set but no main session exists, fallback to isolated."""
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "output",
            "session_id": None,
            "cost": 0.01,
            "duration": 5,
            "error": None,
        }

        jobs_file = tmp_path / "jobs.json"
        jobs_data = {
            "jobs": [{
                "id": "main-job",
                "name": "Main Job",
                "enabled": True,
                "execution": {
                    "prompt_template": "Do thing",
                    "mode": "main",
                    "session_id": "$main",
                    "model": "sonnet",
                    "timeout_seconds": 120,
                },
            }]
        }
        jobs_file.write_text(json.dumps(jobs_data))
        runs_log = tmp_path / "runs.jsonl"
        runs_log.touch()

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={"cron": {"jobs_file": str(jobs_file), "runs_log": str(runs_log)}},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.main_session.get_main_session_id", return_value=None):
            with app.test_client() as client:
                resp = client.post("/trigger/main-job")
                assert resp.status_code == 200
                # Mode should have been changed to "isolated"
                call_kwargs = mock_executor.run.call_args
                mode = call_kwargs.kwargs.get("mode", call_kwargs[1].get("mode", ""))
                assert mode == "isolated"

    def test_trigger_non_heartbeat_feed(self, setup):
        """Non-heartbeat jobs with telegram_topic should call send_feed differently."""
        app, tmp_path, mock_executor = setup
        # Add a non-heartbeat job with telegram_topic
        jobs_file = tmp_path / "jobs.json"
        jobs_data = json.loads(jobs_file.read_text())
        jobs_data["jobs"].append({
            "id": "reflection",
            "name": "Reflection",
            "enabled": True,
            "execution": {"prompt_template": "Reflect", "mode": "isolated"},
            "telegram_topic": 100005,
        })
        jobs_file.write_text(json.dumps(jobs_data))

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("lib.feed.send_feed") as mock_feed, \
             patch("lib.feed.TOPIC_NAMES", {100005: "Mentor"}):
            with app.test_client() as client:
                resp = client.post("/trigger/reflection")
                assert resp.status_code == 200
                mock_feed.assert_called_once()
                call_kwargs = mock_feed.call_args
                assert call_kwargs.kwargs.get("job_id") == "reflection"

    def test_trigger_error_result(self, setup):
        """Test trigger when executor returns an error."""
        app, tmp_path, mock_executor = setup
        mock_executor.run.return_value = {
            "result": "",
            "session_id": None,
            "cost": 0.0,
            "duration": 0,
            "error": "timeout",
        }
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/trigger/heartbeat")
                data = resp.get_json()
                assert data["status"] == "executed"
                assert data["result"]["success"] is False

    def test_trigger_exception(self, setup):
        """Test trigger when an exception occurs."""
        app, tmp_path, mock_executor = setup
        mock_executor.run.side_effect = Exception("executor crash")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/trigger/heartbeat")
                assert resp.status_code == 500

    def test_trigger_jobs_file_not_found(self, tmp_path):
        """Test trigger when jobs file doesn't exist."""
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={"cron": {"jobs_file": str(tmp_path / "nonexistent.json")}},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/trigger/some-job")
                assert resp.status_code == 404

    def test_trigger_auth_and_rate_limit(self, setup):
        """Test that auth failure and rate limit are checked."""
        app, _, _ = setup
        with patch("routes.a2a._check_auth", return_value=(json.dumps({"error": "no auth"}), 401)):
            with app.test_client() as client:
                resp = client.post("/trigger/heartbeat")
                assert resp.status_code == 401

        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=(json.dumps({"error": "rate limited"}), 429)):
            with app.test_client() as client:
                resp = client.post("/trigger/heartbeat")
                assert resp.status_code == 429


class TestCheckRateLimit:
    """Test _check_rate_limit helper function."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={"webhook": {"token": "test-token"}},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app

    def test_rate_limit_allows_request(self, setup):
        app = setup
        # Create a mock webhook_server module
        mock_ws = types.ModuleType("webhook_server")
        from collections import defaultdict
        mock_ws.rate_limit_store = defaultdict(list)
        mock_ws.MAX_REQUESTS_PER_HOUR = 100

        with patch("routes.a2a._check_auth", return_value=None), \
             patch.dict("sys.modules", {"webhook_server": mock_ws}), \
             patch("lib.status_collector.collect_status", return_value={"ok": True}):
            with app.test_client() as client:
                resp = client.get("/status")
                assert resp.status_code == 200

    def test_rate_limit_blocks_request(self, setup):
        app = setup
        mock_ws = types.ModuleType("webhook_server")
        from collections import defaultdict
        mock_ws.rate_limit_store = defaultdict(list)
        mock_ws.MAX_REQUESTS_PER_HOUR = 2

        with patch("routes.a2a._check_auth", return_value=None), \
             patch.dict("sys.modules", {"webhook_server": mock_ws}), \
             patch("lib.status_collector.collect_status", return_value={"ok": True}):
            with app.test_client() as client:
                # First 2 requests should be fine
                resp1 = client.get("/status")
                assert resp1.status_code == 200
                resp2 = client.get("/status")
                assert resp2.status_code == 200
                # 3rd should be rate limited
                resp3 = client.get("/status")
                assert resp3.status_code == 429


class TestMessageRouteEdgeCases:
    """Test edge cases for /message/<session> endpoint."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Done",
            "cost": 0.01,
            "duration": 5,
            "error": "some error",
        }

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, mock_executor

    def test_message_with_error_result(self, setup):
        app, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/message/sess-123", json={"prompt": "Test"})
                data = resp.get_json()
                assert data["status"] == "sent"
                assert data["result"]["success"] is False

    def test_message_exception(self, setup):
        app, mock_executor = setup
        mock_executor.run.side_effect = Exception("crash")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/message/sess-123", json={"prompt": "Test"})
                assert resp.status_code == 500

    def test_message_no_body(self, setup):
        app, _ = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/message/sess-123",
                                 data="not json",
                                 content_type="text/plain")
                # get_json() returns None for non-JSON -> caught by error handler
                assert resp.status_code in (400, 500)


class TestSessionsSendEdgeCases:
    """Additional edge cases for /sessions/<key>/send."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Done",
            "cost": 0.01,
            "error": "timeout",
        }

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path

    def test_send_with_error(self, setup):
        app, tmp_path = setup
        (tmp_path / "mykey_claude_session.txt").write_text("sess-id")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/mykey/send", json={"prompt": "test"})
                data = resp.get_json()
                assert data["status"] == "failed"
                assert data["error"] == "timeout"

    def test_send_exception(self, setup):
        app, tmp_path = setup
        (tmp_path / "mykey_claude_session.txt").write_text("sess-id")
        from routes.a2a import _executor
        _executor.run.side_effect = Exception("crash")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/mykey/send", json={"prompt": "test"})
                assert resp.status_code == 500


class TestSessionsSpawnEdgeCases:
    """Additional edge cases for /sessions/spawn."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        mock_executor = MagicMock()
        mock_executor.run.return_value = {
            "result": "Error",
            "session_id": None,
            "cost": 0.0,
            "error": "something failed",
        }

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=mock_executor,
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path

    def test_spawn_with_error(self, setup):
        app, tmp_path = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/spawn",
                                 json={"prompt": "do task", "description": "My sub-agent"})
                data = resp.get_json()
                assert data["status"] == "failed"
                assert data["description"] == "My sub-agent"
                # No session file created since there was an error
                session_files = list(tmp_path.glob("subagent_*_claude_session.txt"))
                assert len(session_files) == 0

    def test_spawn_exception(self, setup):
        app, tmp_path = setup
        from routes.a2a import _executor
        _executor.run.side_effect = Exception("crash")
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.post("/sessions/spawn", json={"prompt": "test"})
                assert resp.status_code == 500


class TestSessionsHistoryEdgeCases:
    """Additional edge cases for /sessions/<key>/history."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app, tmp_path

    def test_history_exception(self, setup):
        app, tmp_path = setup
        # Create a log file that will cause an error
        log = tmp_path / "err_log.jsonl"
        log.write_text('{"ok": true}\n')
        # Patch open to raise on the log file
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("builtins.open", side_effect=Exception("read error")):
            with app.test_client() as client:
                resp = client.get("/sessions/err/history")
                assert resp.status_code == 500


class TestSessionsListEdgeCases:
    """Additional edge cases for /sessions/list."""

    @pytest.fixture
    def setup(self, tmp_path):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},
            executor=MagicMock(),
            sessions_dir=tmp_path,
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app

    def test_list_exception(self, setup):
        app = setup
        with patch("routes.a2a._check_auth", return_value=None), \
             patch("routes.a2a._check_rate_limit", return_value=None), \
             patch("routes.a2a._sessions_dir") as mock_dir:
            mock_dir.exists.side_effect = Exception("crash")
            with app.test_client() as client:
                resp = client.get("/sessions/list")
                assert resp.status_code == 500


class TestCheckAuthEdgeCases:
    """Additional edge cases for _check_auth."""

    @pytest.fixture
    def app(self):
        from flask import Flask
        from routes.a2a import a2a_bp, init_a2a_bp

        app = Flask(__name__)
        app.config["TESTING"] = True
        init_a2a_bp(
            config={},  # no token in config
            executor=MagicMock(),
            sessions_dir=Path("/tmp"),
            require_auth_fn=lambda: None,
            rate_limit_fn=lambda: None,
        )
        app.register_blueprint(a2a_bp)
        return app

    def test_no_token_configured(self, app, monkeypatch):
        """When no token is configured, all bearer tokens should be rejected."""
        monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
        with patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list",
                                headers={"Authorization": "Bearer any-token"})
                assert resp.status_code == 401

    def test_token_from_env(self, app, monkeypatch):
        """WEBHOOK_TOKEN env var should be used for auth."""
        monkeypatch.setenv("WEBHOOK_TOKEN", "env-token")
        with patch("routes.a2a._check_rate_limit", return_value=None):
            with app.test_client() as client:
                resp = client.get("/sessions/list",
                                headers={"Authorization": "Bearer env-token"})
                assert resp.status_code != 401
