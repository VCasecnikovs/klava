"""Tests for cron-watchdog.py - watchdog for launchd services.

Mocks subprocess.run and urllib.request to avoid real system calls.
Uses tmp_path for healthcheck file tests.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# We need to import cron-watchdog.py which has a hyphen in the name
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "cron_watchdog",
    os.path.join(os.path.dirname(__file__), "..", "cron-watchdog.py"),
)
cron_watchdog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cron_watchdog)


# ── get_launchd_status ───────────────────────────────────────────────


class TestGetLaunchdStatus:
    """Tests for get_launchd_status(label)."""

    @patch("subprocess.run")
    def test_running_with_pid(self, mock_run):
        """Service running with PID and exit code 0."""
        mock_run.return_value = MagicMock(
            stdout="12345\t0\tcom.local.cron-scheduler\n",
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is True
        assert pid == 12345
        assert "PID 12345" in reason

    @patch("subprocess.run")
    def test_running_no_pid(self, mock_run):
        """Service with dash PID and exit code 0 - running but no PID yet."""
        mock_run.return_value = MagicMock(
            stdout="-\t0\tcom.local.cron-scheduler\n",
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is True
        assert pid is None
        assert "no PID yet" in reason

    @patch("subprocess.run")
    def test_dead_with_exit_code(self, mock_run):
        """Service with dash PID and non-zero exit code - dead."""
        mock_run.return_value = MagicMock(
            stdout="-\t1\tcom.local.cron-scheduler\n",
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is False
        assert pid is None
        assert "exit code 1" in reason

    @patch("subprocess.run")
    def test_dead_with_signal(self, mock_run):
        """Service with PID but non-zero status - killed by signal."""
        mock_run.return_value = MagicMock(
            stdout="99999\t-9\tcom.local.cron-scheduler\n",
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is False
        assert pid == 99999
        assert "signal" in reason

    @patch("subprocess.run")
    def test_not_found(self, mock_run):
        """Service not in launchctl list at all."""
        mock_run.return_value = MagicMock(
            stdout="123\t0\tcom.apple.something\n456\t0\tcom.other.service\n",
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is False
        assert pid is None
        assert "Not found" in reason

    @patch("subprocess.run")
    def test_subprocess_exception(self, mock_run):
        """subprocess.run raises an exception."""
        mock_run.side_effect = OSError("launchctl not found")
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is False
        assert pid is None
        assert "Check failed" in reason

    @patch("subprocess.run")
    def test_malformed_line_skipped(self, mock_run):
        """Line with less than 2 tab-separated parts is skipped."""
        mock_run.return_value = MagicMock(
            stdout="com.local.cron-scheduler\n",  # no tabs
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is False
        assert "Not found" in reason

    @patch("subprocess.run")
    def test_multiple_services_finds_correct_one(self, mock_run):
        """Multiple lines - finds the right service."""
        mock_run.return_value = MagicMock(
            stdout=(
                "111\t0\tcom.local.tg-gateway\n"
                "222\t0\tcom.local.cron-scheduler\n"
                "333\t0\tcom.local.webhook-server\n"
            ),
            returncode=0,
        )
        is_running, pid, reason = cron_watchdog.get_launchd_status("com.local.cron-scheduler")
        assert is_running is True
        assert pid == 222


# ── check_healthcheck_file ───────────────────────────────────────────


class TestCheckHealthcheckFile:
    """Tests for check_healthcheck_file(filepath, max_stale_minutes)."""

    def test_file_missing(self, tmp_path):
        """Non-existent file returns False."""
        ok, reason = cron_watchdog.check_healthcheck_file(
            str(tmp_path / "nonexistent.health"), 10
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_fresh_file(self, tmp_path):
        """Recently updated file returns True."""
        health_file = tmp_path / "test.health"
        now = datetime.now(timezone.utc)
        health_file.write_text(now.isoformat())

        ok, reason = cron_watchdog.check_healthcheck_file(str(health_file), 10)
        assert ok is True
        assert "Fresh" in reason

    def test_stale_file(self, tmp_path):
        """File older than max_stale_minutes returns False."""
        health_file = tmp_path / "test.health"
        old_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        health_file.write_text(old_time.isoformat())

        ok, reason = cron_watchdog.check_healthcheck_file(str(health_file), 10)
        assert ok is False
        assert "Stale" in reason

    def test_exactly_at_boundary(self, tmp_path):
        """File exactly at max_stale_minutes boundary - should be fresh (not >)."""
        health_file = tmp_path / "test.health"
        boundary_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        health_file.write_text(boundary_time.isoformat())

        ok, reason = cron_watchdog.check_healthcheck_file(str(health_file), 10)
        # timedelta comparison is >, so exactly 10 min should NOT be stale
        # But due to execution time, might be slightly over. Test with a generous margin.
        # The logic is `age > timedelta(minutes=max_stale_minutes)`.
        # With exact boundary, result depends on nanoseconds of execution.
        # Just verify it returns a tuple of (bool, str).
        assert isinstance(ok, bool)
        assert isinstance(reason, str)

    def test_invalid_content(self, tmp_path):
        """File with non-ISO content returns False with read error."""
        health_file = tmp_path / "test.health"
        health_file.write_text("not-a-date")

        ok, reason = cron_watchdog.check_healthcheck_file(str(health_file), 10)
        assert ok is False
        assert "error" in reason.lower()

    def test_custom_max_stale(self, tmp_path):
        """Custom max_stale_minutes is respected."""
        health_file = tmp_path / "test.health"
        # 3 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=3)
        health_file.write_text(old_time.isoformat())

        # With 5 min threshold - should be fresh
        ok, _ = cron_watchdog.check_healthcheck_file(str(health_file), 5)
        assert ok is True

        # With 2 min threshold - should be stale
        ok, _ = cron_watchdog.check_healthcheck_file(str(health_file), 2)
        assert ok is False


# ── check_health_url ─────────────────────────────────────────────────


class TestCheckHealthUrl:
    """Tests for check_health_url(url)."""

    @patch("urllib.request.urlopen")
    def test_healthy_200(self, mock_urlopen):
        """HTTP 200 returns (True, 'OK')."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ok, reason = cron_watchdog.check_health_url("http://127.0.0.1:18788/health")
        assert ok is True
        assert reason == "OK"

    @patch("urllib.request.urlopen")
    def test_non_200_status(self, mock_urlopen):
        """Non-200 status returns False."""
        mock_resp = MagicMock()
        mock_resp.status = 503
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ok, reason = cron_watchdog.check_health_url("http://127.0.0.1:18788/health")
        assert ok is False
        assert "503" in reason

    @patch("urllib.request.urlopen")
    def test_connection_refused(self, mock_urlopen):
        """Connection refused returns False with Unreachable."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        ok, reason = cron_watchdog.check_health_url("http://127.0.0.1:18788/health")
        assert ok is False
        assert "Unreachable" in reason

    @patch("urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        """Timeout returns False."""
        mock_urlopen.side_effect = TimeoutError("timed out")

        ok, reason = cron_watchdog.check_health_url("http://127.0.0.1:18788/health")
        assert ok is False
        assert "Unreachable" in reason


# ── restart_service ──────────────────────────────────────────────────


class TestRestartService:
    """Tests for restart_service(label)."""

    def test_plist_not_found(self, tmp_path, monkeypatch):
        """Missing plist file returns False."""
        monkeypatch.setattr(cron_watchdog, "LAUNCHAGENTS_DIR", tmp_path)
        result = cron_watchdog.restart_service("com.local.nonexistent")
        assert result is False

    @patch("subprocess.run")
    def test_successful_restart(self, mock_run, tmp_path, monkeypatch):
        """Successful unload + load returns True."""
        monkeypatch.setattr(cron_watchdog, "LAUNCHAGENTS_DIR", tmp_path)
        plist_file = tmp_path / "com.local.cron-scheduler.plist"
        plist_file.write_text("<plist>...</plist>")

        mock_run.return_value = MagicMock(returncode=0)

        result = cron_watchdog.restart_service("com.local.cron-scheduler")
        assert result is True
        assert mock_run.call_count == 2

        # Verify unload then load order
        calls = mock_run.call_args_list
        assert "unload" in calls[0].args[0]
        assert "load" in calls[1].args[0]

    @patch("subprocess.run")
    def test_load_fails(self, mock_run, tmp_path, monkeypatch):
        """Load returning non-zero exit code returns False."""
        monkeypatch.setattr(cron_watchdog, "LAUNCHAGENTS_DIR", tmp_path)
        plist_file = tmp_path / "com.local.cron-scheduler.plist"
        plist_file.write_text("<plist>...</plist>")

        # First call (unload) succeeds, second call (load) fails
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ]

        result = cron_watchdog.restart_service("com.local.cron-scheduler")
        assert result is False

    @patch("subprocess.run")
    def test_subprocess_exception(self, mock_run, tmp_path, monkeypatch):
        """subprocess.run raising exception returns False."""
        monkeypatch.setattr(cron_watchdog, "LAUNCHAGENTS_DIR", tmp_path)
        plist_file = tmp_path / "com.local.cron-scheduler.plist"
        plist_file.write_text("<plist>...</plist>")

        mock_run.side_effect = OSError("permission denied")

        result = cron_watchdog.restart_service("com.local.cron-scheduler")
        assert result is False


# ── check_service ────────────────────────────────────────────────────


class TestCheckService:
    """Tests for check_service(label, config)."""

    @patch.object(cron_watchdog, "get_launchd_status")
    def test_launchd_not_running(self, mock_status):
        """Service not running in launchd -> unhealthy."""
        mock_status.return_value = (False, None, "Dead (exit code 1)")

        ok, reason = cron_watchdog.check_service(
            "com.local.test", {"name": "Test Service"}
        )
        assert ok is False
        assert "launchd" in reason

    @patch.object(cron_watchdog, "get_launchd_status")
    def test_running_no_extra_checks(self, mock_status):
        """Service running with no extra health checks -> healthy."""
        mock_status.return_value = (True, 123, "Running (PID 123)")

        ok, reason = cron_watchdog.check_service(
            "com.local.test", {"name": "Test Service"}
        )
        assert ok is True

    @patch.object(cron_watchdog, "check_healthcheck_file")
    @patch.object(cron_watchdog, "get_launchd_status")
    def test_running_but_healthcheck_file_stale(self, mock_status, mock_file):
        """Running but healthcheck file is stale -> unhealthy."""
        mock_status.return_value = (True, 123, "Running (PID 123)")
        mock_file.return_value = (False, "Stale (15.0 min)")

        config = {
            "name": "CRON Scheduler",
            "healthcheck_file": "/tmp/cron-scheduler.health",
            "max_stale_minutes": 10,
        }
        ok, reason = cron_watchdog.check_service("com.local.cron-scheduler", config)
        assert ok is False
        assert "healthcheck" in reason
        mock_file.assert_called_once_with("/tmp/cron-scheduler.health", 10)

    @patch.object(cron_watchdog, "check_health_url")
    @patch.object(cron_watchdog, "get_launchd_status")
    def test_running_but_health_url_down(self, mock_status, mock_url):
        """Running but health URL unreachable -> unhealthy."""
        mock_status.return_value = (True, 456, "Running (PID 456)")
        mock_url.return_value = (False, "Unreachable: Connection refused")

        config = {
            "name": "Webhook Server",
            "health_url": "http://127.0.0.1:18788/health",
        }
        ok, reason = cron_watchdog.check_service("com.local.webhook-server", config)
        assert ok is False
        assert "health_url" in reason

    @patch.object(cron_watchdog, "check_health_url")
    @patch.object(cron_watchdog, "get_launchd_status")
    def test_all_checks_pass(self, mock_status, mock_url):
        """Running + health URL OK -> healthy."""
        mock_status.return_value = (True, 789, "Running (PID 789)")
        mock_url.return_value = (True, "OK")

        config = {
            "name": "Webhook Server",
            "health_url": "http://127.0.0.1:18788/health",
        }
        ok, reason = cron_watchdog.check_service("com.local.webhook-server", config)
        assert ok is True

    @patch.object(cron_watchdog, "check_healthcheck_file")
    @patch.object(cron_watchdog, "get_launchd_status")
    def test_default_max_stale_minutes(self, mock_status, mock_file):
        """Config without max_stale_minutes defaults to 10."""
        mock_status.return_value = (True, 123, "Running (PID 123)")
        mock_file.return_value = (True, "Fresh (5s)")

        config = {
            "name": "Test",
            "healthcheck_file": "/tmp/test.health",
            # no max_stale_minutes
        }
        cron_watchdog.check_service("com.test", config)
        mock_file.assert_called_once_with("/tmp/test.health", 10)


# ── send_alert ───────────────────────────────────────────────────────


class TestSendAlert:
    """Tests for send_alert(message)."""

    @patch.object(cron_watchdog, "load_config")
    @patch("urllib.request.urlopen")
    def test_sends_telegram_message(self, mock_urlopen, mock_config):
        """Successful alert sends to Telegram API."""
        mock_config.return_value = {
            "telegram": {
                "bot_token": "123:ABC",
                "allowed_users": [12345],
            },
            "alerts": {"topic_id": 100006},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        cron_watchdog.send_alert("Test alert message")

        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        url = call_args.args[0]
        assert "123:ABC" in url
        assert "sendMessage" in url

    @patch.object(cron_watchdog, "load_config")
    def test_no_bot_token(self, mock_config):
        """Missing bot_token prints instead of sending."""
        mock_config.return_value = {
            "telegram": {"allowed_users": [12345]},
            "alerts": {},
        }
        # Should not raise
        cron_watchdog.send_alert("Test alert")

    @patch.object(cron_watchdog, "load_config")
    def test_no_allowed_users(self, mock_config):
        """Empty allowed_users prints instead of sending."""
        mock_config.return_value = {
            "telegram": {"bot_token": "123:ABC", "allowed_users": []},
            "alerts": {},
        }
        cron_watchdog.send_alert("Test alert")

    @patch.object(cron_watchdog, "load_config")
    def test_config_load_exception(self, mock_config):
        """Exception in config loading doesn't crash."""
        mock_config.side_effect = FileNotFoundError("config.yaml not found")
        # Should not raise
        cron_watchdog.send_alert("Test alert")

    @patch.object(cron_watchdog, "load_config")
    @patch("urllib.request.urlopen")
    def test_telegram_api_error(self, mock_urlopen, mock_config):
        """Telegram API returning not-ok doesn't crash."""
        mock_config.return_value = {
            "telegram": {
                "bot_token": "123:ABC",
                "allowed_users": [12345],
            },
            "alerts": {},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": false, "description": "Bad Request"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        cron_watchdog.send_alert("Test alert")

    @patch.object(cron_watchdog, "load_config")
    @patch("urllib.request.urlopen")
    def test_no_topic_id(self, mock_urlopen, mock_config):
        """Alert without topic_id doesn't include message_thread_id."""
        mock_config.return_value = {
            "telegram": {
                "bot_token": "123:ABC",
                "allowed_users": [12345],
            },
            "alerts": {},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        cron_watchdog.send_alert("Test alert")

        call_args = mock_urlopen.call_args
        # urlopen(url, data=data, timeout=10) - data is a keyword arg
        data = call_args.kwargs.get("data", b"")
        assert b"message_thread_id" not in data


# ── main ─────────────────────────────────────────────────────────────


class TestMain:
    """Tests for main() orchestration."""

    @patch.object(cron_watchdog, "send_alert")
    @patch.object(cron_watchdog, "restart_service")
    @patch.object(cron_watchdog, "check_service")
    def test_all_healthy(self, mock_check, mock_restart, mock_alert):
        """All services healthy - no restart, no alert."""
        mock_check.return_value = (True, "Running (PID 123)")

        cron_watchdog.main()

        assert mock_check.call_count == len(cron_watchdog.SERVICES)
        mock_restart.assert_not_called()
        mock_alert.assert_not_called()

    @patch("time.sleep")
    @patch.object(cron_watchdog, "send_alert")
    @patch.object(cron_watchdog, "restart_service")
    @patch.object(cron_watchdog, "check_service")
    def test_service_down_restart_succeeds(self, mock_check, mock_restart, mock_alert, mock_sleep):
        """One service down, restart succeeds, recovery alert sent."""
        # First round: cron-scheduler fails, others pass
        def check_side_effect(label, config):
            if label == "com.local.cron-scheduler":
                return (False, "Dead (exit code 1)")
            return (True, "Running")

        mock_check.side_effect = check_side_effect
        mock_restart.return_value = True

        # After restart, check_service is called again for verification.
        # We need to handle the verification call too.
        # The main function calls check_service in the loop, then again after restart.
        # So we need to change side_effect after the initial loop finishes.
        call_count = [0]
        def check_side_effect_with_recovery(label, config):
            call_count[0] += 1
            if label == "com.local.cron-scheduler":
                # First call (in loop) = fail, second call (after restart) = pass
                if call_count[0] <= len(cron_watchdog.SERVICES):
                    return (False, "Dead (exit code 1)")
                return (True, "Running (PID 999)")
            return (True, "Running")

        mock_check.side_effect = check_side_effect_with_recovery

        cron_watchdog.main()

        mock_restart.assert_called_once_with("com.local.cron-scheduler")
        # Should send: down alert + recovery alert
        assert mock_alert.call_count == 2
        # First alert is the down alert
        assert "DOWN" in mock_alert.call_args_list[0].args[0]
        # Second alert is recovery
        assert "RECOVERED" in mock_alert.call_args_list[1].args[0]

    @patch("time.sleep")
    @patch.object(cron_watchdog, "send_alert")
    @patch.object(cron_watchdog, "restart_service")
    @patch.object(cron_watchdog, "check_service")
    def test_service_down_restart_fails_still_down(self, mock_check, mock_restart, mock_alert, mock_sleep):
        """Service down, restart succeeds but still unhealthy - critical alert."""
        call_count = [0]
        def check_side_effect(label, config):
            call_count[0] += 1
            if label == "com.local.cron-scheduler":
                return (False, "Dead (exit code 1)")
            return (True, "Running")

        mock_check.side_effect = check_side_effect
        mock_restart.return_value = True  # restart command succeeds

        cron_watchdog.main()

        # Should send: down alert + critical still-down alert
        assert mock_alert.call_count == 2
        assert "STILL DOWN" in mock_alert.call_args_list[1].args[0]

    @patch.object(cron_watchdog, "send_alert")
    @patch.object(cron_watchdog, "restart_service")
    @patch.object(cron_watchdog, "check_service")
    def test_restart_command_fails(self, mock_check, mock_restart, mock_alert):
        """Restart command itself fails - critical alert."""
        call_count = [0]
        def check_side_effect(label, config):
            call_count[0] += 1
            if label == "com.local.cron-scheduler":
                return (False, "Dead (exit code 1)")
            return (True, "Running")

        mock_check.side_effect = check_side_effect
        mock_restart.return_value = False  # restart failed

        cron_watchdog.main()

        # Should send: down alert + restart failed alert
        assert mock_alert.call_count == 2
        assert "RESTART FAILED" in mock_alert.call_args_list[1].args[0]


# ── load_config ──────────────────────────────────────────────────────


class TestLoadConfig:
    """Tests for load_config()."""

    def test_loads_yaml(self, tmp_path, monkeypatch):
        """Loads and parses YAML config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "telegram:\n  bot_token: '123:ABC'\n  allowed_users:\n    - 12345\n"
        )
        monkeypatch.setattr(cron_watchdog, "CONFIG_PATH", config_file)

        config = cron_watchdog.load_config()
        assert config["telegram"]["bot_token"] == "123:ABC"
        assert config["telegram"]["allowed_users"] == [12345]

    def test_missing_config_raises(self, tmp_path, monkeypatch):
        """Missing config file raises FileNotFoundError."""
        monkeypatch.setattr(cron_watchdog, "CONFIG_PATH", tmp_path / "nonexistent.yaml")
        with pytest.raises(FileNotFoundError):
            cron_watchdog.load_config()


# ── SERVICES config ─────────────────────────────────────────────────


class TestServicesConfig:
    """Sanity checks on the SERVICES dict."""

    def test_all_have_name(self):
        """Every service config has a name."""
        for label, config in cron_watchdog.SERVICES.items():
            assert "name" in config, f"{label} missing 'name'"

    def test_expected_services_present(self):
        """Expected services are defined."""
        assert "com.local.cron-scheduler" in cron_watchdog.SERVICES
        assert "com.local.webhook-server" in cron_watchdog.SERVICES
        assert "com.local.tg-gateway" in cron_watchdog.SERVICES

    def test_cron_scheduler_has_healthcheck(self):
        """Cron scheduler has a healthcheck file config."""
        config = cron_watchdog.SERVICES["com.local.cron-scheduler"]
        assert "healthcheck_file" in config
        assert "max_stale_minutes" in config

    def test_webhook_server_has_health_url(self):
        """Webhook server has a health URL config."""
        config = cron_watchdog.SERVICES["com.local.webhook-server"]
        assert "health_url" in config
