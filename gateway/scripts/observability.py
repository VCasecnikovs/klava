#!/usr/bin/env python3
"""System observability — publish a status report for the gateway.

Reads the LaunchAgent state of every daemon under the configured
`identity.launchd_prefix`, the last 5 entries from cron/runs.jsonl,
and (optionally) vadimgest source freshness. Renders a compact
summary and either prints it to stdout (default) or sends it to
the configured Telegram topic.

Wired into cron/jobs.json.example as the `observability` job. Reads
all paths and integration settings from gateway/config.yaml — no
hardcoded user paths.

Run manually:
  python3 gateway/scripts/observability.py             # stdout only
  python3 gateway/scripts/observability.py --telegram  # also send to TG
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Resolve gateway/lib regardless of cwd.
_HERE = Path(__file__).resolve().parent
_GATEWAY = _HERE.parent
sys.path.insert(0, str(_GATEWAY))

from lib import config as _cfg  # noqa: E402


def _run(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or "").strip()
    except FileNotFoundError:
        return False, f"binary not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def check_daemons() -> list[dict[str, Any]]:
    """Discover every plist matching identity.launchd_prefix and report state."""
    prefix = _cfg.launchd_prefix()
    la_dir = _cfg.launch_agents_dir()
    plists = sorted(la_dir.glob(f"{prefix}.*.plist")) if la_dir.exists() else []

    ok, dump = _run(["launchctl", "list"])
    loaded: dict[str, tuple[str, str]] = {}
    if ok:
        for line in dump.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3:
                pid, last_exit, label = parts[0], parts[1], parts[2]
                loaded[label] = (pid, last_exit)

    results = []
    for plist in plists:
        label = plist.stem
        pid, last_exit = loaded.get(label, ("-", "-"))
        results.append({
            "label": label,
            "name": label.removeprefix(f"{prefix}."),
            "loaded": label in loaded,
            "running": pid not in ("-", "0", "") and pid.isdigit(),
            "pid": pid,
            "last_exit": last_exit,
        })
    return results


def check_cron(limit: int = 5) -> list[dict[str, Any]]:
    """Tail the last N terminal cron runs."""
    runs_log = _cfg.cron_runs_log()
    if not runs_log.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(runs_log, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 256 * 1024))
            chunk = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return []
    for line in reversed(chunk.splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = entry.get("status")
        if status in ("started", "catch_up"):
            continue
        out.append({
            "ts": (entry.get("timestamp") or "")[:19],
            "job_id": entry.get("job_id", "?"),
            "status": status or "?",
            "error": (entry.get("error") or "")[:120],
        })
        if len(out) >= limit:
            break
    return out


def check_vadimgest() -> dict[str, dict[str, int]]:
    """Optional: run `vadimgest stats` and parse total/new per source."""
    import shutil
    if not shutil.which("vadimgest"):
        return {}
    ok, output = _run(["vadimgest", "stats"], timeout=10)
    if not ok:
        return {}
    sources: dict[str, dict[str, int]] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        rest = rest.strip()
        # Parse shapes like "12,345 total, 7 new" — be forgiving.
        total = new = 0
        for token in rest.replace(",", "").split():
            if token.isdigit():
                if total == 0:
                    total = int(token)
                else:
                    new = int(token)
                    break
        if total or new:
            sources[name.strip()] = {"total": total, "new": new}
    return sources


def render(daemons, cron_runs, vadimgest, *, html: bool = False) -> str:
    bold = (lambda s: f"<b>{s}</b>") if html else (lambda s: s)
    lines: list[str] = [bold("System Status"), ""]

    all_up = daemons and all(d["running"] for d in daemons)
    icon = "OK" if all_up else "WARN"
    lines.append(bold(f"{icon} Daemons:"))
    if not daemons:
        lines.append("  (no plists found for this launchd prefix)")
    for d in daemons:
        mark = "+" if d["running"] else ("?" if d["loaded"] else "x")
        lines.append(f"  {mark} {d['name']} (pid={d['pid']}, last_exit={d['last_exit']})")
    lines.append("")

    if vadimgest:
        new_total = sum(s["new"] for s in vadimgest.values())
        lines.append(bold(f"Vadimgest (+{new_total} new):"))
        for name, stats in sorted(vadimgest.items()):
            if stats["new"]:
                lines.append(f"  {name}: {stats['total']:,} (+{stats['new']})")
        lines.append("")

    if cron_runs:
        failed = [r for r in cron_runs if r["status"] not in ("completed", "skipped")]
        icon = "OK" if not failed else "WARN"
        lines.append(bold(f"{icon} CRON (last {len(cron_runs)}):"))
        for r in cron_runs:
            mark = {"completed": "+", "failed": "x", "skipped": "-"}.get(r["status"], "?")
            lines.append(f"  {mark} {r['job_id']} @ {r['ts']} {r['status']}")
            if r["error"]:
                lines.append(f"      err: {r['error']}")
        lines.append("")

    issues = [d for d in daemons if not d["running"]]
    if issues:
        lines.append(bold("Issues:"))
        for d in issues:
            lines.append(f"  {d['name']} not running")
    else:
        lines.append(bold("All systems operational"))
    return "\n".join(lines)


def maybe_send_telegram(report_html: str) -> bool:
    """Send to TG if configured. Returns True on send."""
    try:
        from lib.telegram_utils import send_telegram_message  # type: ignore
    except ImportError:
        return False
    tg = _cfg.telegram()
    bot_token = (tg.get("bot_token") or "").strip()
    chat_id = _cfg.telegram_chat_id()
    if not bot_token or not chat_id:
        print("telegram not configured (telegram.bot_token / chat_id) — skipping send", file=sys.stderr)
        return False
    topic_id = _cfg.telegram_topic_id("alerts")
    try:
        send_telegram_message(
            bot_token=bot_token,
            chat_id=chat_id,
            message=report_html,
            topic_id=topic_id,
            parse_mode="HTML",
            log_prefix="observability",
        )
        return True
    except Exception as e:
        print(f"telegram send failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telegram", action="store_true",
                        help="Also push the report to telegram.topics.alerts (if configured).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout when run via cron (errors still print).")
    args = parser.parse_args()

    daemons = check_daemons()
    cron_runs = check_cron(limit=5)
    vadimgest = check_vadimgest()

    text_report = render(daemons, cron_runs, vadimgest, html=False)
    if not args.quiet:
        print(text_report)

    if args.telegram:
        html_report = render(daemons, cron_runs, vadimgest, html=True)
        maybe_send_telegram(html_report)

    # Exit code reflects daemon health so cron-scheduler logs a useful status.
    failed = [d for d in daemons if not d["running"]]
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
