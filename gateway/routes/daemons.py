"""Daemon control — /api/daemons/* endpoints.

Exposes the launchd-managed gateway daemons (cron-scheduler, tg-gateway,
webhook-server, vadimgest-dashboard, cron-watchdog) as a list with
load/pid status, plus a restart button per daemon. Saves the user from
memorizing `launchctl kickstart -k gui/$UID/<label>` incantations.

Security model: only plists that already exist under
~/Library/LaunchAgents and that match the configured identity.launchd_prefix
are addressable. Label goes through argv (never shell), prefix-validated,
and cross-checked against the installed file. No start / stop — restart
is the 95% use case and keeping the surface narrow eliminates "user can
lock themselves out by stopping webhook-server from the UI".

The one subtlety: restarting webhook-server means this very process is
about to die. We detach the `launchctl kickstart` behind a short sleep
in a fresh session so the HTTP response returns before the kill lands.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

from lib import config as _cfg

log = logging.getLogger("daemons")

daemons_bp = Blueprint("daemons", __name__)


def _prefix() -> str:
    cfg = _cfg.load()
    return cfg.get("identity", {}).get("launchd_prefix", "com.local")


def _allowed_prefixes() -> list[str]:
    """Prefixes the daemons route is allowed to scan and address.

    Some installs end up with both `com.vadims.*` and `com.local.*` plists side
    by side (e.g. when the config was retroactively changed but the old
    LaunchAgents never got booted-out). Restarting the prefix from config
    alone in that situation targets the broken duplicate while the real
    running process under the other prefix is untouched. Always include both
    the configured prefix and the gateway's historical defaults so the UI
    shows what's actually running.
    """
    cfg = _cfg.load()
    extra = cfg.get("identity", {}).get("launchd_extra_prefixes", []) or []
    seen: list[str] = []
    for p in [_prefix(), "com.local", "com.vadims", *extra]:
        if isinstance(p, str) and p and p not in seen:
            seen.append(p)
    return seen


def _launchagents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _strip_prefix(label: str) -> str:
    """Return the daemon's canonical name (label without its launchd prefix)."""
    for p in _allowed_prefixes():
        head = f"{p}."
        if label.startswith(head):
            return label[len(head):]
    return label


def _launchctl_list() -> str:
    """Return raw `launchctl list` stdout, or '' on failure."""
    try:
        return subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception:
        return ""


def _parse_status(dump: str, label: str) -> tuple[bool, int | None, int | None]:
    """Return (loaded, pid, last_exit_status) for a label in `launchctl list` output.

    Lines look like:  PID\tStatus\tLabel
    PID is '-' when loaded but not running (e.g. watchpath-triggered agents
    between invocations).
    """
    for line in dump.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[-1] != label:
            continue
        pid_raw, status_raw = parts[0], parts[1]
        pid = int(pid_raw) if pid_raw.isdigit() else None
        try:
            last_exit = int(status_raw)
        except ValueError:
            last_exit = None
        return True, pid, last_exit
    return False, None, None


def _installed_plist(label: str) -> Path | None:
    """Return the resolved plist path if it's a valid installed daemon.

    Guards against path traversal and against labels that don't match an
    allowed prefix. Returns None on any failure so callers can 404.
    """
    if not isinstance(label, str):
        return None
    if not any(label.startswith(f"{p}.") for p in _allowed_prefixes()):
        return None
    la_dir = _launchagents_dir().resolve()
    plist = (la_dir / f"{label}.plist").resolve()
    if not str(plist).startswith(str(la_dir) + os.sep):
        return None
    if not plist.exists():
        return None
    return plist


@daemons_bp.route("/api/daemons", methods=["GET"])
def list_daemons() -> Any:
    """Return each installed daemon with its current load/pid state.

    Scans every plist under every allowed prefix and dedups by canonical
    daemon name (label minus prefix). When the same daemon exists under
    two prefixes (a common drift scenario), the one with a live PID wins.
    The non-running duplicate is surfaced separately as `duplicates` so the
    UI can show a "stop / unload" hint without polluting the main list.
    """
    prefixes = _allowed_prefixes()
    la_dir = _launchagents_dir()
    if not la_dir.exists():
        return jsonify({"daemons": [], "prefix": _prefix(),
                        "prefixes": prefixes,
                        "duplicates": [],
                        "launch_agents_dir": str(la_dir)})

    dump = _launchctl_list()
    by_name: dict[str, list[dict[str, Any]]] = {}
    for prefix in prefixes:
        for plist in sorted(la_dir.glob(f"{prefix}.*.plist")):
            label = plist.stem
            name = _strip_prefix(label)
            loaded, pid, last_exit = _parse_status(dump, label)
            entry = {
                "label": label,
                "name": name,
                "prefix": prefix,
                "path": str(plist),
                "loaded": loaded,
                "pid": pid,
                "last_exit": last_exit,
                "running": loaded and pid is not None,
            }
            by_name.setdefault(name, []).append(entry)

    daemons: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for name in sorted(by_name):
        entries = by_name[name]
        # Prefer the entry with a live PID; ties broken by allowed-prefix order.
        entries.sort(key=lambda e: (
            0 if e["running"] else 1,
            prefixes.index(e["prefix"]) if e["prefix"] in prefixes else 99,
        ))
        primary = entries[0]
        daemons.append(primary)
        for dup in entries[1:]:
            duplicates.append(dup)
    return jsonify({
        "daemons": daemons,
        "duplicates": duplicates,
        "prefix": _prefix(),
        "prefixes": prefixes,
        "launch_agents_dir": str(la_dir),
    })


@daemons_bp.route("/api/daemons/<label>/restart", methods=["POST"])
def restart_daemon(label: str) -> Any:
    """Run `launchctl kickstart -k` on a daemon by label.

    For daemons other than webhook-server we run the kickstart synchronously
    and wait for its exit code. For webhook-server we detach the command so
    this process's HTTP response returns before the kickstart kills us.
    """
    plist = _installed_plist(label)
    if plist is None:
        return jsonify({"ok": False,
                        "error": f"daemon {label!r} not installed"}), 404

    service = f"gui/{os.getuid()}/{label}"
    is_self = _strip_prefix(label) == "webhook-server"

    if is_self:
        # Detach: new session, no stdio, small sleep so the 200 returns first.
        # Using /bin/sh -c because subprocess.Popen of `sleep` + pipe is the
        # usual deadlock trap.
        subprocess.Popen(
            ["/bin/sh", "-c",
             f"sleep 0.5 && launchctl kickstart -k {service}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        return jsonify({
            "ok": True,
            "label": label,
            "detached": True,
            "note": "webhook-server restart scheduled — this tab will lose the"
                    " socket for a few seconds, then reconnect.",
        })

    proc = subprocess.run(
        ["launchctl", "kickstart", "-k", service],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        return jsonify({
            "ok": False,
            "label": label,
            "error": (proc.stderr or proc.stdout or "launchctl failed").strip(),
        }), 500

    return jsonify({
        "ok": True,
        "label": label,
        "detached": False,
    })
