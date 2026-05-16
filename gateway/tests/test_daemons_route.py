"""Regression tests for the daemons route's dedup logic.

When the gateway has been migrated between launchd prefixes (e.g. com.vadims
to com.local) without a clean bootout, both plists exist on disk. Before the
fix, the route only listed plists matching the configured prefix, which often
pointed at the broken duplicate while the real running daemon lived under the
other prefix. Pressing Restart in the UI then targeted the corpse and the
real process kept running. These tests pin the new behavior: scan all allowed
prefixes, group by canonical daemon name, prefer the instance with a live
PID.
"""

import importlib.util
import os
import sys
from unittest.mock import patch


def _load_daemons_route(tmp_path):
    """Load the daemons blueprint module in isolation against tmp config."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, repo)
    spec = importlib.util.spec_from_file_location(
        "daemons_route_test",
        os.path.join(repo, "routes", "daemons.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_plist(la_dir, label):
    la_dir.mkdir(parents=True, exist_ok=True)
    (la_dir / f"{label}.plist").write_text(
        "<?xml version='1.0'?><plist><dict></dict></plist>"
    )


def test_prefers_running_instance_when_duplicate_exists(tmp_path):
    """com.local.webhook-server with PID wins over dead com.vadims duplicate."""
    daemons = _load_daemons_route(tmp_path)

    la_dir = tmp_path / "LaunchAgents"
    _make_plist(la_dir, "com.local.webhook-server")
    _make_plist(la_dir, "com.vadims.webhook-server")

    # Simulated `launchctl list` output: com.local has PID 859, com.vadims is dead
    fake_dump = (
        "PID\tStatus\tLabel\n"
        "859\t0\tcom.local.webhook-server\n"
        "-\t1\tcom.vadims.webhook-server\n"
    )

    with patch.object(daemons, "_launchagents_dir", return_value=la_dir):
        with patch.object(daemons, "_launchctl_list", return_value=fake_dump):
            with patch.object(daemons, "_allowed_prefixes",
                              return_value=["com.vadims", "com.local"]):
                from flask import Flask
                app = Flask(__name__)
                app.register_blueprint(daemons.daemons_bp)
                client = app.test_client()
                resp = client.get("/api/daemons")
                data = resp.get_json()

    primary = next(d for d in data["daemons"] if d["name"] == "webhook-server")
    assert primary["label"] == "com.local.webhook-server"
    assert primary["pid"] == 859
    assert primary["running"] is True

    # The com.vadims dead one is surfaced as a duplicate, not the primary.
    dups = [d for d in data["duplicates"] if d["name"] == "webhook-server"]
    assert len(dups) == 1
    assert dups[0]["label"] == "com.vadims.webhook-server"
    assert dups[0]["running"] is False


def test_single_prefix_install_works(tmp_path):
    """No duplicates → daemons list contains the one entry, duplicates is empty."""
    daemons = _load_daemons_route(tmp_path)

    la_dir = tmp_path / "LaunchAgents"
    _make_plist(la_dir, "com.local.tg-gateway")

    fake_dump = "PID\tStatus\tLabel\n42\t0\tcom.local.tg-gateway\n"

    with patch.object(daemons, "_launchagents_dir", return_value=la_dir):
        with patch.object(daemons, "_launchctl_list", return_value=fake_dump):
            with patch.object(daemons, "_allowed_prefixes",
                              return_value=["com.vadims", "com.local"]):
                from flask import Flask
                app = Flask(__name__)
                app.register_blueprint(daemons.daemons_bp)
                client = app.test_client()
                resp = client.get("/api/daemons")
                data = resp.get_json()

    assert len(data["daemons"]) == 1
    assert data["daemons"][0]["label"] == "com.local.tg-gateway"
    assert data["duplicates"] == []


def test_restart_accepts_alternative_prefix_label(tmp_path):
    """Restart endpoint accepts a com.local label even when config says com.vadims."""
    daemons = _load_daemons_route(tmp_path)

    la_dir = tmp_path / "LaunchAgents"
    _make_plist(la_dir, "com.local.cron-watchdog")

    with patch.object(daemons, "_launchagents_dir", return_value=la_dir):
        with patch.object(daemons, "_allowed_prefixes",
                          return_value=["com.vadims", "com.local"]):
            class _CompletedProc:
                returncode = 0
                stdout = ""
                stderr = ""
            with patch("subprocess.run", return_value=_CompletedProc()):
                from flask import Flask
                app = Flask(__name__)
                app.register_blueprint(daemons.daemons_bp)
                client = app.test_client()
                resp = client.post("/api/daemons/com.local.cron-watchdog/restart")
                data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["label"] == "com.local.cron-watchdog"


def test_strip_prefix_handles_known_prefixes(tmp_path):
    daemons = _load_daemons_route(tmp_path)
    with patch.object(daemons, "_allowed_prefixes",
                      return_value=["com.vadims", "com.local"]):
        assert daemons._strip_prefix("com.local.webhook-server") == "webhook-server"
        assert daemons._strip_prefix("com.vadims.cron-scheduler") == "cron-scheduler"
        # Unknown prefix: returned verbatim (caller will fall through to 404).
        assert daemons._strip_prefix("com.other.foo") == "com.other.foo"


def test_self_detection_recognizes_either_prefix(tmp_path):
    """is_self routing must trigger for webhook-server under any allowed prefix."""
    daemons = _load_daemons_route(tmp_path)
    with patch.object(daemons, "_allowed_prefixes",
                      return_value=["com.vadims", "com.local"]):
        assert daemons._strip_prefix("com.local.webhook-server") == "webhook-server"
        assert daemons._strip_prefix("com.vadims.webhook-server") == "webhook-server"
