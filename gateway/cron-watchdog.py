#!/usr/bin/env python3
"""Watchdog for Claude automation services - monitors all launchd agents."""

import json
import os
import sys
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as _cfg

CONFIG_PATH = _cfg.DEFAULT_CONFIG_PATH
LAUNCHAGENTS_DIR = _cfg.launch_agents_dir()
_PREFIX = _cfg.launchd_prefix()

# Services to monitor (labels derived from launchd_prefix)
SERVICES = {
    f"{_PREFIX}.cron-scheduler": {
        "name": "CRON Scheduler",
        "healthcheck_file": "/tmp/cron-scheduler.health",
        "max_stale_minutes": 10,
        "critical": True,  # Always alert
    },
    f"{_PREFIX}.webhook-server": {
        "name": "Webhook Server",
        "health_url": f"http://127.0.0.1:{_cfg.load().get('webhook', {}).get('port', 18788)}/health",
        "critical": True,
    },
    f"{_PREFIX}.tg-gateway": {
        "name": "TG Gateway",
        "critical": True,
    },
}


def load_config():
    """Load gateway config."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def send_alert(message: str):
    """Send alert to Telegram."""
    try:
        config = load_config()
        tg_config = config.get("telegram", {})
        bot_token = tg_config.get("bot_token")
        allowed_users = tg_config.get("allowed_users", [])

        if not bot_token or not allowed_users:
            print(f"Telegram not configured: {message}")
            return

        chat_id = allowed_users[0]
        alerts_config = config.get("alerts", {})
        topic_id = alerts_config.get("topic_id")

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        params = {'chat_id': chat_id, 'text': message}
        if topic_id:
            params['message_thread_id'] = topic_id

        data = urllib.parse.urlencode(params).encode('utf-8')
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('ok'):
                print(f"Alert sent: {message[:50]}...")
            else:
                print(f"Telegram error: {result}")
    except Exception as e:
        print(f"Failed to send alert: {e}")


def get_launchd_status(label: str) -> tuple[bool, int | None, str]:
    """Get launchd service status. Returns (is_running, pid, reason)."""
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True
        )

        for line in result.stdout.strip().split('\n'):
            if label in line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    pid_str = parts[0]
                    status = int(parts[1])

                    if pid_str == '-':
                        # Not running or just launched
                        if status == 0:
                            return True, None, "Running (no PID yet)"
                        else:
                            return False, None, f"Dead (exit code {status})"
                    else:
                        pid = int(pid_str)
                        if status == 0:
                            return True, pid, f"Running (PID {pid})"
                        else:
                            # Has PID but non-zero status usually means signal
                            return False, pid, f"Dead (signal {-status})"

        return False, None, "Not found in launchctl"
    except Exception as e:
        return False, None, f"Check failed: {e}"


def check_healthcheck_file(filepath: str, max_stale_minutes: int) -> tuple[bool, str]:
    """Check if healthcheck file is fresh."""
    path = Path(filepath)
    if not path.exists():
        return False, "Healthcheck file missing"

    try:
        last_check = datetime.fromisoformat(path.read_text().strip())
        age = datetime.now(timezone.utc) - last_check

        if age > timedelta(minutes=max_stale_minutes):
            return False, f"Stale ({age.total_seconds()/60:.1f} min)"

        return True, f"Fresh ({age.total_seconds():.0f}s)"
    except Exception as e:
        return False, f"Read error: {e}"


def check_health_url(url: str) -> tuple[bool, str]:
    """Check if health endpoint responds."""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status == 200:
                return True, "OK"
            return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, f"Unreachable: {e}"


def restart_service(label: str) -> bool:
    """Restart a launchd service."""
    plist_path = LAUNCHAGENTS_DIR / f"{label}.plist"

    if not plist_path.exists():
        print(f"Plist not found: {plist_path}")
        return False

    try:
        # Unload
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True
        )
        # Load
        result = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Restart failed: {e}")
        return False


def check_service(label: str, config: dict) -> tuple[bool, str]:
    """Check a single service health."""
    name = config["name"]

    # First check launchd status
    is_running, pid, launchd_reason = get_launchd_status(label)

    if not is_running:
        return False, f"launchd: {launchd_reason}"

    # Additional health checks
    if "healthcheck_file" in config:
        file_ok, file_reason = check_healthcheck_file(
            config["healthcheck_file"],
            config.get("max_stale_minutes", 10)
        )
        if not file_ok:
            return False, f"healthcheck: {file_reason}"

    if "health_url" in config:
        url_ok, url_reason = check_health_url(config["health_url"])
        if not url_ok:
            return False, f"health_url: {url_reason}"

    return True, launchd_reason


def main():
    """Main watchdog check."""
    now = datetime.now()
    print(f"\n[{now}] Watchdog check")
    print("=" * 50)

    issues = []

    for label, config in SERVICES.items():
        name = config["name"]
        healthy, reason = check_service(label, config)

        status = "OK" if healthy else "FAIL"
        print(f"  {name}: {status} - {reason}")

        if not healthy:
            issues.append((label, config, reason))

    print("=" * 50)

    if not issues:
        print("All services healthy")
        return

    # Handle issues
    for label, config, reason in issues:
        name = config["name"]
        is_critical = config.get("critical", True)

        print(f"\nHandling issue: {name} - {reason}")

        # Send LOUD alert with emoji
        alert_msg = f"🔴 SERVICE DOWN: {name}\n\n❌ Reason: {reason}\n\n⚙️ Attempting auto-restart..."
        send_alert(alert_msg)

        # Attempt restart
        if restart_service(label):
            # Verify it came back
            import time
            time.sleep(3)
            healthy, new_reason = check_service(label, config)

            if healthy:
                send_alert(f"🟢 Service RECOVERED: {name}\n\n✅ Auto-restart successful")
                print(f"  Restarted successfully: {new_reason}")
            else:
                send_alert(f"🔴🔴🔴 CRITICAL: {name} STILL DOWN!\n\n❌ Auto-restart FAILED\n\n⚠️ MANUAL INTERVENTION NEEDED!")
                print(f"  Still unhealthy after restart: {new_reason}")
        else:
            send_alert(f"🔴🔴🔴 CRITICAL: {name} RESTART FAILED!\n\n⚠️ MANUAL INTERVENTION NEEDED!")
            print(f"  Restart failed")


if __name__ == "__main__":
    main()
