"""System status collector for Claude Code Gateway."""

import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

from lib import config as _cfg

# Resolved at import time. Daemon restart picks up config changes.
CLAUDE_DIR = _cfg.project_root()
CRON_DIR = _cfg.cron_dir()
VADIMGEST_DIR = _cfg.vadimgest_data_dir()
VADIMGEST_STATE_DIR = _cfg.vadimgest_state_dir()
SKILLS_DIR = _cfg.skills_dir()
SETTINGS_FILE = _cfg.settings_file()
OBSIDIAN_DIR = _cfg.obsidian_vault()
LAUNCHD_PREFIX = _cfg.launchd_prefix()

# Configurable team and deal names (override via config if needed)
TEAM_MEMBERS = os.environ.get("TEAM_MEMBERS", "").split(",") if os.environ.get("TEAM_MEMBERS") else []
PRIORITY_DEAL_SCORES = []  # list of (keyword, score) tuples, configure externally

# Dashboard cache
_dashboard_cache: Dict = {"data": None, "ts": 0}
_CACHE_TTL = 10  # seconds


def _safe_json_load(path: Path, default=None, retries: int = 2) -> any:
    """Load JSON file safely, retrying on parse errors from concurrent writes."""
    for attempt in range(retries + 1):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            if attempt < retries:
                time.sleep(0.1)
                continue
            if default is not None:
                return default
            raise


def collect_status() -> Dict:
    """
    Collect comprehensive system status.

    Returns:
        Dict with: {jobs, job_summaries, recent_runs, daemons}
    """
    status = {
        "jobs": [],
        "job_summaries": [],
        "recent_runs": [],
        "daemons": {}
    }

    # Collect daemon status
    status["daemons"] = _get_daemon_status()

    # Collect job status
    jobs_file = _cfg.cron_jobs_file()
    if jobs_file.exists():
        try:
            with open(jobs_file) as f:
                data = json.load(f)
                status["jobs"] = data.get("jobs", [])
        except (json.JSONDecodeError, OSError):
            pass

    # Collect job state
    state_file = _cfg.cron_state_file()
    if state_file.exists():
        try:
            with open(state_file) as f:
                state = json.load(f)
                status["job_summaries"] = _format_job_summaries(
                    status["jobs"], state.get("jobs_status", {})
                )
                status["daemon_start_time"] = state.get("daemon_start_time")
                status["last_check"] = state.get("last_successful_check")
        except (json.JSONDecodeError, OSError):
            pass

    # Collect recent runs
    runs_log = _cfg.cron_runs_log()
    if runs_log.exists():
        status["recent_runs"] = _get_recent_runs(runs_log, limit=10)

    return status


def _get_daemon_status() -> Dict[str, str]:
    """Get status of LaunchAgent daemons."""
    daemons = {
        "cron-scheduler": "unknown",
        "webhook-server": "unknown",
        "tg-gateway": "unknown"
    }

    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5
        )

        output = result.stdout

        for daemon_id, status_val in daemons.items():
            label = f"{LAUNCHD_PREFIX}.{daemon_id}"
            if label in output:
                # Parse PID from launchctl output
                for line in output.splitlines():
                    if label in line:
                        parts = line.split()
                        if len(parts) >= 1 and parts[0].isdigit():
                            daemons[daemon_id] = "running"
                        elif parts[0] == "-":
                            daemons[daemon_id] = "stopped"
                        break
            else:
                daemons[daemon_id] = "not loaded"

    except Exception as e:
        print(f"Failed to check daemon status: {e}")

    return daemons


def _format_job_summaries(jobs: List[Dict], jobs_status: Dict) -> List[Dict]:
    """Format job summaries with last/next run times."""
    summaries = []

    now = datetime.now(timezone.utc)

    for job in jobs:
        job_id = job["id"]
        status = jobs_status.get(job_id, {})

        last_run = status.get("last_run")
        last_run_dt = None
        if last_run:
            last_run_dt = datetime.fromisoformat(last_run)
            if last_run_dt.tzinfo is None:
                last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)

        # Calculate time since last run
        time_since = None
        if last_run_dt:
            delta = now - last_run_dt
            time_since = _format_timedelta(delta)

        # Calculate next run (approximate)
        next_run = _calculate_next_run(job, last_run_dt or now)
        time_until = None
        if next_run:
            delta = next_run - now
            time_until = _format_timedelta(delta)

        summaries.append({
            "id": job_id,
            "name": job.get("name", job_id),
            "enabled": job.get("enabled", True),
            "last_run": last_run,
            "time_since": time_since,
            "next_run": next_run.isoformat() if next_run else None,
            "time_until": time_until,
            "status": status.get("status", "pending")
        })

    return summaries


def _calculate_next_run(job: Dict, from_time: datetime) -> Optional[datetime]:
    """Calculate next run time for a job."""
    schedule = job.get("schedule", {})
    schedule_type = schedule.get("type")

    if schedule_type == "every":
        if "interval_minutes" in schedule:
            delta_seconds = schedule["interval_minutes"] * 60
        elif "interval_hours" in schedule:
            delta_seconds = schedule["interval_hours"] * 3600
        elif "interval_days" in schedule:
            delta_seconds = schedule["interval_days"] * 86400
        else:
            return None

        return datetime.fromtimestamp(
            from_time.timestamp() + delta_seconds,
            tz=timezone.utc
        )

    elif schedule_type == "cron":
        # For CRON, would need croniter - simplified here
        return None

    elif schedule_type == "at":
        dt_str = schedule.get("datetime")
        if dt_str:
            return datetime.fromisoformat(dt_str)

    return None


def _format_timedelta(delta) -> str:
    """Format timedelta as human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        # Future time
        total_seconds = abs(total_seconds)
        prefix = "in "
    else:
        # Past time
        prefix = ""

    if total_seconds < 60:
        return f"{prefix}{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{prefix}{minutes}m"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{prefix}{hours}h"
    else:
        days = total_seconds // 86400
        return f"{prefix}{days}d"


def _get_recent_runs(runs_log: Path, limit: int = 10) -> List[Dict]:
    """Get recent run entries from JSONL log."""
    runs = []

    with open(runs_log) as f:
        for line in f:
            if line.strip():
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Return most recent N completed runs
    completed = [r for r in runs if r.get("status") in ["completed", "failed"]]
    return completed[-limit:]


def collect_dashboard_data() -> Dict:
    """Collect comprehensive dashboard data. Cached for 10s."""
    now = time.time()
    if _dashboard_cache["data"] and (now - _dashboard_cache["ts"]) < _CACHE_TTL:
        return _dashboard_cache["data"]

    data = _collect_fresh_dashboard_data()
    _dashboard_cache["data"] = data
    _dashboard_cache["ts"] = now
    return data


def _time_ago(iso_str: Optional[str]) -> str:
    """Convert ISO timestamp to human-readable time ago."""
    if not iso_str or iso_str == "None":
        return "never"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        seconds = diff.total_seconds()
        if seconds < 0:
            return "just now"
        if seconds < 60:
            return f"{int(seconds)}s ago"
        if seconds < 3600:
            return f"{int(seconds/60)}m ago"
        if seconds < 86400:
            return f"{int(seconds/3600)}h ago"
        return f"{int(seconds/86400)}d ago"
    except Exception:
        return str(iso_str)


def _collect_fresh_dashboard_data() -> Dict:
    """Collect all dashboard data from files (no caching)."""
    now = datetime.now(timezone.utc)

    # 1. Services
    services = _collect_services()

    # 2. CRON state + jobs
    cron_state = {}
    state_file = CRON_DIR / "state.json"
    if state_file.exists():
        cron_state = _safe_json_load(state_file, default={})

    cron_jobs = []
    jobs_file = CRON_DIR / "jobs.json"
    if jobs_file.exists():
        cron_jobs = _safe_json_load(jobs_file, default={}).get("jobs", [])

    jobs_status = cron_state.get("jobs_status", {})

    # 3. Runs history (full file, compute stats)
    all_runs = []
    runs_file = CRON_DIR / "runs.jsonl"
    if runs_file.exists():
        with open(runs_file) as f:
            for line in f:
                if line.strip():
                    try:
                        all_runs.append(json.loads(line))
                    except Exception:
                        pass

    cutoff_24h = now - timedelta(hours=24)
    recent_runs = []
    for r in all_runs:
        try:
            ts = datetime.fromisoformat(r["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts > cutoff_24h:
                recent_runs.append(r)
        except (KeyError, ValueError):
            pass

    completed_24h = [r for r in recent_runs if r.get("status") == "completed"]
    failed_24h = [r for r in recent_runs if r.get("error")]

    # Per-job stats
    per_job = defaultdict(lambda: {"runs": 0, "durations": []})
    for r in completed_24h:
        j = per_job[r.get("job_id", "unknown")]
        j["runs"] += 1
        dur = r.get("duration_seconds", 0) or 0
        j["durations"].append(dur)

    # Per-job recent run history (last 12 runs per job, for sparkline dots)
    per_job_history: Dict[str, list] = defaultdict(list)
    per_job_last_error: Dict[str, str] = {}
    for r in all_runs:
        jid = r.get("job_id")
        if jid:
            per_job_history[jid].append({
                "ok": not bool(r.get("error")),
                "ts": r.get("timestamp", ""),
                "dur": r.get("duration_seconds", 0) or 0,
            })
            if r.get("error"):
                per_job_last_error[jid] = (r.get("error") or "")[:200]
    # Keep only last 12 per job
    for jid in per_job_history:
        per_job_history[jid] = per_job_history[jid][-12:]

    # Per-job 24h success rate
    per_job_24h_total: Dict[str, int] = defaultdict(int)
    per_job_24h_ok: Dict[str, int] = defaultdict(int)
    for r in recent_runs:
        jid = r.get("job_id")
        if jid and r.get("status") in ("completed", "failed"):
            per_job_24h_total[jid] += 1
            if not r.get("error"):
                per_job_24h_ok[jid] += 1

    total_cost = sum(r.get("cost_usd", 0) or 0 for r in all_runs)
    failure_rate = 0
    total_all_time = len([r for r in all_runs if r.get("status") in ("completed", "failed")])
    total_failures = len([r for r in all_runs if r.get("error")])
    if total_all_time > 0:
        failure_rate = total_failures / total_all_time * 100

    # 4. Uptime
    uptime_seconds = 0
    daemon_start = cron_state.get("daemon_start_time")
    if daemon_start:
        try:
            dt = datetime.fromisoformat(daemon_start)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            uptime_seconds = (now - dt).total_seconds()
        except Exception:
            pass

    # 5. Vadimgest data sources + sync stats
    # Read sync_runs.jsonl for last sync times and hourly counts
    sync_runs_file = VADIMGEST_DIR / "data" / "sync_runs.jsonl"
    last_sync_by_source = {}  # source -> last sync timestamp
    hourly_counts = defaultdict(int)  # source -> records added in last hour
    cutoff_1h = now - timedelta(hours=1)

    if sync_runs_file.exists():
        with open(sync_runs_file) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    sr = json.loads(line)
                    src = sr.get("source")
                    if not src:
                        continue
                    last_sync_by_source[src] = sr.get("ts")
                    # Hourly count
                    try:
                        sr_dt = datetime.fromisoformat(sr["ts"])
                        if sr_dt.tzinfo is None:
                            sr_dt = sr_dt.replace(tzinfo=timezone.utc)
                        if sr_dt > cutoff_1h:
                            hourly_counts[src] += sr.get("count", 0) or 0
                    except Exception:
                        pass
                except Exception:
                    pass

    data_sources = []
    total_records = 0
    total_hourly = 0

    # Pre-load check_ready results for all sources
    _deps_cache: dict = {}
    _enabled_cache: dict = {}
    try:
        import sys as _sys
        _vg_root = str(VADIMGEST_DIR)
        if _vg_root not in _sys.path:
            _sys.path.insert(0, _vg_root)
        from vadimgest.ingest.sources import get_syncer_class, all_source_names
        from vadimgest.config import load_config, get_source_config
        load_config.cache_clear()
        for _src_name in all_source_names():
            _cls = get_syncer_class(_src_name)
            if _cls:
                try:
                    _deps_cache[_src_name] = _cls.check_ready()
                except Exception:
                    _deps_cache[_src_name] = {"ok": True}
            try:
                _enabled_cache[_src_name] = bool(get_source_config(_src_name).get("enabled", False))
            except Exception:
                _enabled_cache[_src_name] = True
    except Exception:
        pass

    vg_state_file = VADIMGEST_DIR / "data" / "state.json"
    if vg_state_file.exists():
        vg_state = _safe_json_load(vg_state_file)
        for name, info in sorted(vg_state.items()):
            records = info.get("total_records", 0)
            total_records += records
            last_data_ts = info.get("last_ts")  # last content timestamp
            last_sync_ts = last_sync_by_source.get(name)  # last sync run
            sync_type = "cron"
            added_1h = hourly_counts.get(name, 0)
            total_hourly += added_1h

            # Check dependencies
            deps_ready = _deps_cache.get(name, {"ok": True})
            deps_ok = deps_ready.get("ok", True)
            missing_deps = deps_ready.get("missing", [])
            enabled = _enabled_cache.get(name, True)

            # Health: disabled sources are dormant (healthy by definition).
            # For enabled sources: deps must be ok AND sync must be fresh.
            healthy = True
            if not enabled:
                healthy = True
            elif not deps_ok:
                healthy = False
            else:
                check_ts = last_sync_ts or last_data_ts
                if check_ts:
                    try:
                        dt = datetime.fromisoformat(check_ts)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        age_hours = (now - dt).total_seconds() / 3600
                        healthy = age_hours < 2
                    except Exception:
                        pass
                else:
                    healthy = False

            data_sources.append({
                "name": name,
                "records": records,
                "last_data": last_data_ts,
                "last_data_ago": _time_ago(last_data_ts),
                "last_sync": last_sync_ts,
                "last_sync_ago": _time_ago(last_sync_ts),
                "sync_type": sync_type,
                "healthy": healthy,
                "enabled": enabled,
                "added_1h": added_1h,
                "deps_ok": deps_ok,
                "missing_deps": missing_deps,
            })

    # 6. Heartbeat backlog
    heartbeat_items = []
    hb_file = CRON_DIR / "heartbeat_state.json"
    if hb_file.exists():
        hb_data = _safe_json_load(hb_file, default={})
        for key, item in hb_data.get("tracked_items", {}).items():
            heartbeat_items.append({
                "key": key,
                "source": item.get("source", "?"),
                "summary": item.get("summary", "?"),
                "priority_score": item.get("priority_score", 0),
                "deal_value": item.get("deal_value"),
                "escalation_level": item.get("escalation_level", 0),
                "created_at": item.get("created_at"),
                "age": _time_ago(item.get("created_at")),
            })
        heartbeat_items.sort(key=lambda x: x["priority_score"], reverse=True)

    # 7. CRON jobs enriched
    cron_jobs_enriched = []
    for job in cron_jobs:
        jid = job["id"]
        state = jobs_status.get(jid, {})
        j_stats = per_job.get(jid, {"runs": 0, "durations": []})
        avg_dur = 0
        if j_stats["durations"]:
            avg_dur = sum(j_stats["durations"]) / len(j_stats["durations"])

        sched = job.get("schedule", {})
        if sched.get("type") == "every":
            sched_display = f"every {sched.get('interval_minutes', sched.get('interval_hours', '?'))}{'m' if 'interval_minutes' in sched else 'h'}"
        elif sched.get("type") == "cron":
            sched_display = sched.get("cron", "?")
        else:
            sched_display = "manual"

        # Success rate for this job in last 24h
        total_24h = per_job_24h_total.get(jid, 0)
        ok_24h = per_job_24h_ok.get(jid, 0)
        success_rate = round(ok_24h / total_24h * 100) if total_24h > 0 else None

        cron_jobs_enriched.append({
            "id": jid,
            "name": job.get("name", jid),
            "enabled": job.get("enabled", True),
            "mode": job.get("execution", {}).get("mode", "?"),
            "model": job.get("execution", {}).get("model", ""),
            "schedule_display": sched_display,
            "last_run": state.get("last_run"),
            "last_run_ago": _time_ago(state.get("last_run")),
            "status": state.get("status", "pending"),
            "runs_24h": j_stats["runs"],
            "avg_duration_s": int(avg_dur),
            "recent_runs": per_job_history.get(jid, []),
            "last_error": per_job_last_error.get(jid),
            "success_rate_24h": success_rate,
        })

    # 8. Activity feed (interesting recent events with output)
    skip_jobs = {"_healthcheck", "_jobs_reload", "_sleep_wake_detector"}
    interesting = [e for e in all_runs
                   if e.get("status") in ("completed", "failed")
                   and e.get("job_id") not in skip_jobs]

    # Load tool call log for file enrichment
    tool_call_records = _load_tool_call_records()

    # Only match tool calls for claude-mode jobs (main/isolated), not bash jobs
    claude_mode_jobs = {j["id"] for j in cron_jobs
                        if j.get("execution", {}).get("mode") in ("main", "isolated")}
    session_starts = _build_session_starts(tool_call_records) if tool_call_records else {}

    activity = []
    for evt in interesting[-30:]:
        ts = evt.get("timestamp")
        dur = evt.get("duration_seconds", 0) or 0
        # Find files touched during this run's time window (only for claude-mode jobs)
        job_id = evt.get("job_id", "?")
        files_touched = (_files_for_run(tool_call_records, ts, dur, session_starts)
                         if tool_call_records and job_id in claude_mode_jobs else [])
        activity.append({
            "job_id": evt.get("job_id", "?"),
            "timestamp": ts,
            "ago": _time_ago(ts),
            "duration_seconds": dur,
            "cost_usd": evt.get("cost_usd", 0) or 0,
            "status": evt.get("status", "?"),
            "error": evt.get("error"),
            "output": evt.get("output", ""),
            "files": files_touched,
        })
    activity.reverse()

    # Correlate CRON runs with git commits (cause -> effect)
    for item in activity:
        ts = item.get("timestamp")
        dur = item.get("duration_seconds", 0)
        if not ts:
            continue
        try:
            end_dt = datetime.fromisoformat(ts)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            start_dt = end_dt - timedelta(seconds=max(dur, 10))
            # Find git commits in this time window
            git_result = subprocess.run(
                ["git", "log", f"--since={start_dt.isoformat()}", f"--until={end_dt.isoformat()}",
                 "--format=%H|%s", "--no-merges"],
                capture_output=True, text=True, timeout=3,
                cwd=str(CLAUDE_DIR)
            )
            if git_result.returncode == 0 and git_result.stdout.strip():
                commits = []
                for line in git_result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("|", 1)
                    if len(parts) == 2:
                        commits.append({
                            "hash": parts[0].strip()[:8],
                            "message": parts[1].strip(),
                        })
                item["git_commits"] = commits
        except Exception:
            pass

    # 9. Agent activity (what the system created/changed recently)
    agent_activity = _collect_agent_activity()

    # 10. Tool call activity (from hooks JSONL)
    tool_calls = _collect_tool_calls()

    # 11. Reply queue (from gtasks)
    reply_queue = _collect_reply_queue()

    # 12. Failing jobs (only active jobs from jobs.json)
    active_job_ids = {j["id"] for j in cron_jobs}
    # Alerts are only for enabled jobs - disabling a job silences its alerts too.
    enabled_job_ids = {j["id"] for j in cron_jobs if j.get("enabled", True)}
    failing_jobs = _collect_failing_jobs(all_runs, enabled_job_ids)

    # 13. Skill inventory
    skill_inventory = _collect_skill_inventory()

    # 14. MCP servers
    mcp_servers = _collect_mcp_servers()

    # 15. QQ markers (frustration markers)
    qq_markers = _collect_qq_markers(days=7)

    # 16. Skill changes (git history)
    skill_changes = _collect_skill_changes(days=7)

    # 17. Error learning aggregation (reuse qq_markers and skill_changes)
    error_learning = _collect_error_learning(days=7, qq_markers=qq_markers, skill_changes=skill_changes)

    # Health score: weighted average of services, sources, jobs health
    healthy_svcs = len([s for s in services if s.get("running")])
    total_svcs = max(len(services), 1)
    healthy_ds = len([s for s in data_sources if s.get("healthy")])
    total_ds = max(len(data_sources), 1)
    failing_count = len(failing_jobs)
    total_cron = max(len(cron_jobs_enriched), 1)
    ok_cron = total_cron - failing_count
    health_score = round(
        (healthy_svcs / total_svcs * 40 +
         healthy_ds / total_ds * 30 +
         ok_cron / total_cron * 30)
    )

    return {
        "generated_at": now.isoformat(),
        "scheduler": {
            "uptime_seconds": int(uptime_seconds),
            "daemon_start_time": daemon_start,
            "uptime_display": _time_ago(daemon_start).replace(" ago", "") if daemon_start else "unknown",
        },
        "stats": {
            "total_records": total_records,
            "added_1h": total_hourly,
            "runs_24h": len(completed_24h),
            "failures_24h": len(failed_24h),
            "total_cost_usd": round(total_cost, 2),
            "failure_rate_pct": round(failure_rate, 1),
            "all_time_runs": total_all_time,
            "health_score": health_score,
        },
        "services": services,
        "data_sources": data_sources,
        "cron_jobs": cron_jobs_enriched,
        "heartbeat_backlog": heartbeat_items,
        "activity": activity,
        "agent_activity": agent_activity,
        "tool_calls": tool_calls,
        "reply_queue": reply_queue,
        "failing_jobs": failing_jobs,
        "skill_inventory": skill_inventory,
        "mcp_servers": mcp_servers,
        "qq_markers": qq_markers,
        "skill_changes": skill_changes,
        "error_learning": error_learning,
        "evolution_timeline": _collect_evolution_timeline(),
        "growth_metrics": _collect_growth_metrics(),
        "obsidian_metrics": _collect_obsidian_metrics(),
        "claude_md_details": _collect_claude_md_details(),
        "daily_notes": _collect_daily_notes_status(),
        "lifeline": _collect_lifeline(),
    }


# ── Evolution data collectors ─────────────────────────────────────────

# Separate cache for evolution data (expensive git operations)
_evolution_cache: Dict = {"data": None, "ts": 0}
_EVOLUTION_CACHE_TTL = 60  # seconds

_growth_cache: Dict = {"data": None, "ts": 0}
_GROWTH_CACHE_TTL = 300  # 5 minutes (expensive)

_lifeline_cache: Dict = {"data": None, "ts": 0}
_LIFELINE_CACHE_TTL = 60  # seconds


# System-authored commit detection. Either the author name is one Klava uses,
# or the message starts with a known automation prefix.
_LIFELINE_SYSTEM_AUTHORS = {"Клавдия", "Klava", "klava"}
# Klava's automation jobs commit with these message prefixes. `klava:` is not
# in the list because Klava herself never writes that - author check handles it.
_LIFELINE_PREFIX_RE = re.compile(
    r"^(heartbeat|reflection|mentor|self-evolve|intake)[:\s]",
    re.IGNORECASE,
)
# Commit separator for the custom `git log --format` parse.
_LIFELINE_COMMIT_SEP = "---KLAVA-COMMIT---"


def _lifeline_is_system(author: str, message: str) -> bool:
    if author and author.strip() in _LIFELINE_SYSTEM_AUTHORS:
        return True
    if message and _LIFELINE_PREFIX_RE.match(message.strip()):
        return True
    return False


def _lifeline_classify_claude(files: List[str]) -> Dict[str, List[str]]:
    """Bucket files from the claude repo into the 3 groups we care about.

    Files outside these buckets are ignored - we only surface changes to
    CLAUDE.md/MEMORY.md, daily notes, or skills.
    """
    groups: Dict[str, List[str]] = defaultdict(list)
    for f in files:
        if f == ".claude/CLAUDE.md" or f == ".claude/MEMORY.md":
            groups["claude_md"].append(f)
        elif f.startswith("memory/") and f.endswith(".md"):
            groups["daily"].append(f)
        elif f.startswith(".claude/skills/"):
            groups["skills"].append(f)
    return dict(groups)


def _lifeline_parse_git_log(stdout: str) -> List[Dict]:
    """Parse the custom `--format` output into [{hash, date, author, subject, files}, ...]."""
    out = []
    blocks = stdout.split(_LIFELINE_COMMIT_SEP)
    for block in blocks:
        block = block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        if len(lines) < 4:
            continue
        h = lines[0].strip()
        date_str = lines[1].strip()
        author = lines[2].strip()
        subject = lines[3].strip()
        files = [l.strip() for l in lines[4:] if l.strip()]
        out.append({
            "hash": h,
            "date_str": date_str,
            "author": author,
            "subject": subject,
            "files": files,
        })
    return out


def _lifeline_walk_repo(repo_dir: Path, limit: int = 200) -> List[Dict]:
    """Return raw parsed commits from a repo, no filtering."""
    if not repo_dir.exists() or not (repo_dir / ".git").exists():
        return []
    fmt = f"{_LIFELINE_COMMIT_SEP}%n%H%n%ai%n%an%n%s"
    try:
        res = subprocess.run(
            ["git", "log", f"--format={fmt}", "--name-only", "--no-merges", f"-{limit}"],
            capture_output=True, text=True, timeout=15, cwd=str(repo_dir),
        )
        if res.returncode != 0:
            return []
        return _lifeline_parse_git_log(res.stdout)
    except Exception:
        return []


def _lifeline_format_ts(date_str: str) -> Dict[str, str]:
    try:
        dt = datetime.fromisoformat(date_str)
        return {
            "ts": dt.isoformat(),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M"),
        }
    except Exception:
        return {"ts": date_str or "", "date": (date_str or "")[:10], "time": ""}


def _collect_lifeline(limit: int = 200) -> List[Dict]:
    """Log of system-made changes, grouped into claude_md / daily / skills / obsidian.

    Reads git history from both the claude repo and the Obsidian vault. Filters
    to commits authored by Klava or with a known automation prefix. Claude-repo
    commits may touch multiple groups - we emit one event per group touched.
    """
    now_ts = time.time()
    if _lifeline_cache["data"] is not None and (now_ts - _lifeline_cache["ts"]) < _LIFELINE_CACHE_TTL:
        return _lifeline_cache["data"]

    events: List[Dict] = []

    # Claude repo: one event per (commit, group) pair. A single reflection
    # commit often edits both CLAUDE.md and a skill - we want both rows.
    for c in _lifeline_walk_repo(CLAUDE_DIR, limit):
        if not _lifeline_is_system(c["author"], c["subject"]):
            continue
        groups = _lifeline_classify_claude(c["files"])
        if not groups:
            continue
        ts = _lifeline_format_ts(c["date_str"])
        for group, gfiles in groups.items():
            events.append({
                **ts,
                "group": group,
                "summary": c["subject"],
                "author": c["author"],
                "commit": c["hash"][:8],
                "files": gfiles,
                "repo": "claude",
            })

    # MyBrain: every system commit is one obsidian event, regardless of path.
    for c in _lifeline_walk_repo(OBSIDIAN_DIR, limit):
        if not _lifeline_is_system(c["author"], c["subject"]):
            continue
        if not c["files"]:
            continue
        ts = _lifeline_format_ts(c["date_str"])
        events.append({
            **ts,
            "group": "obsidian",
            "summary": c["subject"],
            "author": c["author"],
            "commit": c["hash"][:8],
            "files": c["files"][:12],
            "files_total": len(c["files"]),
            "repo": "mybrain",
        })

    events.sort(key=lambda e: e.get("ts") or "", reverse=True)
    events = events[:200]

    _lifeline_cache["data"] = events
    _lifeline_cache["ts"] = now_ts
    return events


def _collect_obsidian_events() -> List[Dict]:
    """Scan Obsidian vault for recently created People/Organizations notes.
    Groups by day to avoid flooding timeline."""
    events = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)

    for subdir, note_type in [("People", "people"), ("Organizations", "organizations")]:
        note_dir = OBSIDIAN_DIR / subdir
        if not note_dir.exists():
            continue

        # Group notes by creation day
        by_day: Dict[str, List[str]] = defaultdict(list)
        try:
            for f in note_dir.iterdir():
                if f.suffix != ".md":
                    continue
                try:
                    stat = f.stat()
                    # macOS st_birthtime = creation date
                    created = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc)
                    if created > cutoff:
                        day_str = created.strftime("%Y-%m-%d")
                        time_str = created.strftime("%H:%M")
                        by_day[day_str].append((f.stem, time_str))
                except Exception:
                    continue
        except Exception:
            continue

        # Create one event per day per folder
        for day, notes in sorted(by_day.items(), reverse=True):
            count = len(notes)
            # Sort notes by time, pick latest time for the event
            notes.sort(key=lambda x: x[1], reverse=True)
            latest_time = notes[0][1]
            names = [n[0] for n in notes]

            if count <= 3:
                msg = f"Created {', '.join(names)}"
            else:
                top3 = ', '.join(names[:3])
                msg = f"{count} new {note_type.capitalize()} notes ({top3}, ...)"

            events.append({
                "hash": f"obs-{note_type}-{day}",
                "date": day,
                "time": latest_time,
                "message": msg,
                "category": "knowledge",
                "files_changed": count,
                "insertions": 0,
                "deletions": 0,
                "details": {
                    "note_type": note_type,
                    "notes": names,
                },
            })

    return events


def _collect_evolution_timeline() -> List[Dict]:
    """Build evolution timeline from git history, categorized by type.

    Filters out operational noise (heartbeat daily notes) and categorizes
    each commit as claude_md / skill / fix / learning / capability / infra.
    Includes diff details for CLAUDE.md and skill changes.
    """
    now_ts = time.time()
    if _evolution_cache["data"] and (now_ts - _evolution_cache["ts"]) < _EVOLUTION_CACHE_TTL:
        return _evolution_cache["data"]

    events = []
    now = datetime.now(timezone.utc)

    try:
        # Get all non-merge commits with files changed
        result = subprocess.run(
            ["git", "log", "--format=%H|%ai|%s", "--no-merges", "-200"],
            capture_output=True, text=True, timeout=10,
            cwd=str(CLAUDE_DIR)
        )
        if result.returncode != 0:
            return events

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0].strip(),
                    "date_str": parts[1].strip(),
                    "message": parts[2].strip(),
                })

        # Filter noise
        noise_patterns = [
            "heartbeat: daily notes",
        ]

        for commit in commits:
            msg = commit["message"]

            # Skip noise
            if any(p in msg for p in noise_patterns):
                continue

            # Get files changed + stats
            try:
                stat_result = subprocess.run(
                    ["git", "diff-tree", "--no-commit-id", "-r", "--numstat", commit["hash"]],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(CLAUDE_DIR)
                )
                files = []
                insertions = 0
                deletions = 0
                for stat_line in stat_result.stdout.strip().split("\n"):
                    if not stat_line.strip():
                        continue
                    stat_parts = stat_line.split("\t")
                    if len(stat_parts) >= 3:
                        ins = int(stat_parts[0]) if stat_parts[0] != "-" else 0
                        dels = int(stat_parts[1]) if stat_parts[1] != "-" else 0
                        insertions += ins
                        deletions += dels
                        files.append(stat_parts[2])
            except Exception:
                files = []
                insertions = 0
                deletions = 0

            # Skip commits that ONLY touch memory/*.md (daily note appends)
            if files and all(f.startswith("memory/") and f.endswith(".md") for f in files):
                continue

            # Categorize
            category = _categorize_commit(msg, files)

            # Parse date
            try:
                dt = datetime.fromisoformat(commit["date_str"])
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M")
            except Exception:
                date_str = commit["date_str"][:10]
                time_str = ""

            # Build details
            details = _build_event_details(commit["hash"], category, files, msg)

            events.append({
                "hash": commit["hash"][:8],
                "date": date_str,
                "time": time_str,
                "message": msg,
                "category": category,
                "files_changed": len(files),
                "insertions": insertions,
                "deletions": deletions,
                "ago": _time_ago(commit["date_str"]),
                "details": details,
            })

    except Exception:
        pass

    # Merge Obsidian knowledge events
    obsidian_events = _collect_obsidian_events()
    events.extend(obsidian_events)

    # Sort all events by date+time descending
    events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")), reverse=True)

    # Limit to 50 most recent evolution events
    events = events[:50]

    _evolution_cache["data"] = events
    _evolution_cache["ts"] = now_ts
    return events


def _categorize_commit(message: str, files: List[str]) -> str:
    """Categorize a commit based on message and touched files."""
    msg_lower = message.lower()

    # Check files for strong signals
    touches_claude_md = any(".claude/CLAUDE.md" in f for f in files)
    touches_skills = any(".claude/skills/" in f for f in files)
    touches_scenarios = any("scenarios/" in f for f in files)

    # Fix: explicit fix markers
    if msg_lower.startswith("fix:") or msg_lower.startswith("fix ") or "qq" in msg_lower or "йй" in msg_lower:
        return "fix"

    # Learning: reflection, mentor, scenarios
    if any(kw in msg_lower for kw in ["reflection:", "reflection ", "mentor:", "scenario"]):
        return "learning"

    # CLAUDE.md changes
    if touches_claude_md and not touches_skills:
        return "claude_md"

    # Skill changes
    if touches_skills or touches_scenarios:
        return "skill"

    # Capability: new features
    if any(kw in msg_lower for kw in ["feat:", "feat(", "add ", "implement"]):
        return "capability"

    # Default
    return "infra"


def _build_event_details(commit_hash: str, category: str, files: List[str], message: str) -> Dict:
    """Build expanded details for a timeline event."""
    details = {}

    if category == "claude_md" or any(".claude/CLAUDE.md" in f for f in files):
        # Extract CLAUDE.md diff with section info
        try:
            diff_result = subprocess.run(
                ["git", "diff", f"{commit_hash}^", commit_hash, "--", ".claude/CLAUDE.md"],
                capture_output=True, text=True, timeout=5,
                cwd=str(CLAUDE_DIR)
            )
            if diff_result.returncode == 0 and diff_result.stdout:
                sections, diff_lines = _parse_diff_sections(diff_result.stdout)
                details["sections_changed"] = sections
                details["diff_preview"] = "\n".join(diff_lines[:80])
        except Exception:
            pass

    if category == "skill" or any(".claude/skills/" in f for f in files):
        # Extract affected skill names
        skills = set()
        for f in files:
            if ".claude/skills/" in f:
                parts = f.split(".claude/skills/")
                if len(parts) > 1:
                    skill_name = parts[1].split("/")[0]
                    if skill_name:
                        skills.add(skill_name)
        details["skills_affected"] = sorted(skills)

    # Generic diff for any commit (when no diff_preview already set)
    if not details.get("diff_preview") and files:
        interesting = [f for f in files if f.endswith(('.py', '.md', '.yaml', '.json', '.html'))][:3]
        if interesting:
            try:
                diff_result = subprocess.run(
                    ["git", "diff", f"{commit_hash}^", commit_hash, "--"] + interesting,
                    capture_output=True, text=True, timeout=5,
                    cwd=str(CLAUDE_DIR)
                )
                if diff_result.returncode == 0 and diff_result.stdout:
                    _, diff_lines = _parse_diff_sections(diff_result.stdout)
                    if diff_lines:
                        details["diff_preview"] = "\n".join(diff_lines[:80])
            except Exception:
                pass

    # Files summary (shortened paths)
    if files:
        shortened = []
        for f in files[:10]:
            f = f.replace(".claude/", "")
            shortened.append(f)
        details["files"] = shortened

    return details


def _parse_diff_sections(diff_text: str) -> tuple:
    """Parse unified diff to extract section names and formatted diff lines."""
    sections = set()
    diff_lines = []
    current_section = None

    for line in diff_text.split("\n"):
        # Skip diff headers
        if line.startswith("diff ") or line.startswith("index ") or line.startswith("---") or line.startswith("+++"):
            continue

        # Hunk headers often contain section context
        if line.startswith("@@"):
            # Extract function/section context from @@ line
            if "##" in line:
                # The @@ line might reference a markdown heading
                ctx = line.split("@@")
                if len(ctx) >= 3:
                    section_ctx = ctx[2].strip()
                    if section_ctx.startswith("## "):
                        current_section = section_ctx[3:].strip()
                        sections.add(current_section)
            continue

        # Added/removed lines
        if line.startswith("+") and not line.startswith("+++"):
            # Check if this line IS a section header
            clean = line[1:].strip()
            if clean.startswith("## "):
                current_section = clean[3:].strip()
                sections.add(current_section)
            diff_lines.append(line)
        elif line.startswith("-") and not line.startswith("---"):
            clean = line[1:].strip()
            if clean.startswith("## "):
                current_section = clean[3:].strip()
                sections.add(current_section)
            diff_lines.append(line)

    return sorted(sections), diff_lines


def _collect_growth_metrics() -> Dict:
    """Compute growth sparkline data from git history at key time points."""
    now_ts = time.time()
    if _growth_cache["data"] and (now_ts - _growth_cache["ts"]) < _GROWTH_CACHE_TTL:
        return _growth_cache["data"]

    metrics = {
        "skills": {"current": 0, "series": [], "labels": []},
        "people": {"current": 0, "series": [], "labels": []},
        "claude_md_lines": {"current": 0, "series": [], "labels": []},
    }

    # Current counts
    try:
        # Skills
        skills_count = sum(1 for d in (SKILLS_DIR).iterdir()
                          if d.is_dir() and (d / "SKILL.md").exists()) if SKILLS_DIR.exists() else 0
        metrics["skills"]["current"] = skills_count

        # People
        people_dir = _cfg.people_dir()
        people_count = sum(1 for f in people_dir.iterdir()
                          if f.suffix == ".md") if people_dir.exists() else 0
        metrics["people"]["current"] = people_count

        # CLAUDE.md lines
        claude_md = _cfg.claude_md_file()
        if claude_md.exists():
            metrics["claude_md_lines"]["current"] = len(claude_md.read_text().split("\n"))
    except Exception:
        pass

    # Historical data points from git (6-8 points spread across repo lifetime)
    try:
        # Get first and last commit dates
        result = subprocess.run(
            ["git", "log", "--format=%ai", "--reverse"],
            capture_output=True, text=True, timeout=5,
            cwd=str(CLAUDE_DIR)
        )
        if result.returncode == 0 and result.stdout.strip():
            dates = result.stdout.strip().split("\n")
            first_date = datetime.fromisoformat(dates[0].strip())
            last_date = datetime.fromisoformat(dates[-1].strip())

            # Generate 7 evenly spaced sample points
            total_days = max((last_date - first_date).days, 1)
            step = max(total_days // 6, 1)

            sample_dates = []
            current = first_date
            while current <= last_date:
                sample_dates.append(current)
                current += timedelta(days=step)
            if sample_dates[-1] < last_date:
                sample_dates.append(last_date)

            for sample_dt in sample_dates:
                date_str = sample_dt.strftime("%Y-%m-%d %H:%M:%S %z")
                label = sample_dt.strftime("%b %d")

                # Get commit hash at this date
                hash_result = subprocess.run(
                    ["git", "log", "--format=%H", f"--before={date_str}", "-1"],
                    capture_output=True, text=True, timeout=3,
                    cwd=str(CLAUDE_DIR)
                )
                if hash_result.returncode != 0 or not hash_result.stdout.strip():
                    continue

                commit_hash = hash_result.stdout.strip()

                # Skills count at this point
                try:
                    tree_result = subprocess.run(
                        ["git", "ls-tree", "-d", "--name-only", commit_hash, ".claude/skills/"],
                        capture_output=True, text=True, timeout=3,
                        cwd=str(CLAUDE_DIR)
                    )
                    skill_count = len([l for l in tree_result.stdout.strip().split("\n") if l.strip()])
                except Exception:
                    skill_count = 0

                # CLAUDE.md line count at this point
                try:
                    show_result = subprocess.run(
                        ["git", "show", f"{commit_hash}:.claude/CLAUDE.md"],
                        capture_output=True, text=True, timeout=3,
                        cwd=str(CLAUDE_DIR)
                    )
                    md_lines = len(show_result.stdout.split("\n")) if show_result.returncode == 0 else 0
                except Exception:
                    md_lines = 0

                metrics["skills"]["series"].append(skill_count)
                metrics["skills"]["labels"].append(label)
                metrics["claude_md_lines"]["series"].append(md_lines)
                metrics["claude_md_lines"]["labels"].append(label)

    except Exception:
        pass

    _growth_cache["data"] = metrics
    _growth_cache["ts"] = now_ts
    return metrics


def _load_tool_call_records() -> List[Dict]:
    """Load recent tool call records from hooks JSONL."""
    log_file = CLAUDE_DIR / ".claude" / "logs" / "tool-calls.jsonl"
    if not log_file.exists():
        return []
    try:
        result = subprocess.run(
            ["tail", "-3000", str(log_file)],
            capture_output=True, text=True, timeout=3
        )
        records = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass
        return records
    except Exception:
        return []


def _build_session_starts(tool_records: List[Dict]) -> Dict[str, datetime]:
    """Build a map of session_id -> earliest tool call timestamp."""
    starts = {}
    for r in tool_records:
        sid = r.get("sid", "")
        if not sid:
            continue
        try:
            dt = datetime.fromisoformat(r["ts"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if sid not in starts or dt < starts[sid]:
                starts[sid] = dt
        except Exception:
            pass
    return starts


def _files_for_run(tool_records: List[Dict], run_ts: str, duration: int,
                   session_starts: Dict[str, datetime] = None) -> List[Dict]:
    """Find files touched by tool calls during a CRON run's time window.

    Only matches tool calls from sessions that started near the run start
    (within 60s before to end of run), filtering out long-lived interactive sessions.
    """
    if not run_ts:
        return []
    try:
        # run_ts is completion time, duration is how long it ran
        end_dt = datetime.fromisoformat(run_ts)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        start = end_dt - timedelta(seconds=max(duration, 10))
        end = end_dt + timedelta(seconds=5)  # small buffer after completion
    except Exception:
        return []

    # Find sessions that likely belong to this CRON run
    # (session started within 60s before run start to end of run)
    matching_sids = set()
    if session_starts:
        session_window_start = start - timedelta(seconds=60)
        for sid, first_ts in session_starts.items():
            if session_window_start <= first_ts <= end:
                matching_sids.add(sid)

    file_tools = {"Edit", "Write", "Read"}
    files = {}  # path -> action
    for r in tool_records:
        tool = r.get("tool", "")
        if tool not in file_tools:
            continue
        # Filter by session if we have session data
        if matching_sids and r.get("sid", "") not in matching_sids:
            continue
        try:
            tc_dt = datetime.fromisoformat(r["ts"])
            if tc_dt.tzinfo is None:
                tc_dt = tc_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if start <= tc_dt <= end:
            path = r.get("summary", "")
            if not path:
                continue
            # Shorten home dir
            path = path.replace(str(Path.home()), "~")
            action = "write" if tool in ("Edit", "Write") else "read"
            # Prefer write over read if both
            if path not in files or action == "write":
                files[path] = action

    return [{"path": p, "action": a} for p, a in files.items()]



def _collect_agent_activity() -> List[Dict]:
    """Collect what the agent created/changed recently (last 24h), with content previews."""
    items = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # 1. Recent git commits by the agent - with diff stats
    try:
        author_args = []
        for author in _cfg.agent_git_authors():
            author_args.extend(["--author", author])
        if not author_args:
            author_args = ["--author", _cfg.assistant_name()]
        result = subprocess.run(
            ["git", "log", *author_args, "--since=24 hours ago",
             "--format=%H|%s|%ai", "--no-merges"],
            capture_output=True, text=True, timeout=5,
            cwd=str(CLAUDE_DIR)
        )
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) >= 3:
                commit_hash = parts[0]
                # Get diff stats for this commit
                detail = ""
                try:
                    stat_result = subprocess.run(
                        ["git", "show", commit_hash, "--stat", "--format="],
                        capture_output=True, text=True, timeout=3,
                        cwd=str(CLAUDE_DIR)
                    )
                    detail = stat_result.stdout.strip()
                except Exception:
                    detail = commit_hash[:8]
                items.append({
                    "type": "git_commit",
                    "summary": parts[1],
                    "timestamp": parts[2].strip(),
                    "detail": detail,
                })
    except Exception:
        pass

    # 2. Recently modified Obsidian People/Organizations notes - with frontmatter + sections
    obsidian_vault = OBSIDIAN_DIR
    for subdir, note_type in [("People", "person"), ("Organizations", "org")]:
        note_dir = obsidian_vault / subdir
        if not note_dir.exists():
            continue
        try:
            for f in note_dir.iterdir():
                if not f.suffix == ".md":
                    continue
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime > cutoff:
                    detail = _extract_note_preview(f)
                    items.append({
                        "type": note_type,
                        "summary": f.stem,
                        "timestamp": mtime.isoformat(),
                        "detail": detail,
                    })
        except Exception:
            pass

    # 3. Recently modified skills - with description
    skills_dir = CLAUDE_DIR / ".claude" / "skills"
    if skills_dir.exists():
        try:
            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    mtime = datetime.fromtimestamp(skill_file.stat().st_mtime, tz=timezone.utc)
                    if mtime > cutoff:
                        detail = _extract_skill_preview(skill_dir)
                        items.append({
                            "type": "skill",
                            "summary": skill_dir.name,
                            "timestamp": mtime.isoformat(),
                            "detail": detail,
                        })
        except Exception:
            pass

    # 4. Today's daily notes - with last section
    memory_dir = CLAUDE_DIR / "memory"
    if memory_dir.exists():
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        for date_str in [today, yesterday]:
            note = memory_dir / f"{date_str}.md"
            if note.exists():
                mtime = datetime.fromtimestamp(note.stat().st_mtime, tz=timezone.utc)
                if mtime > cutoff:
                    try:
                        content = note.read_text()
                        lines = content.split("\n")
                        line_count = len(lines)
                        # Extract last ~30 lines as preview
                        detail = "\n".join(lines[-30:]).strip()
                    except Exception:
                        line_count = 0
                        detail = ""
                    items.append({
                        "type": "daily_note",
                        "summary": f"{date_str} ({line_count} lines)",
                        "timestamp": mtime.isoformat(),
                        "detail": detail,
                    })

    # Sort by timestamp descending
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return items[:20]


def _extract_note_preview(filepath: Path) -> str:
    """Extract frontmatter + section headers from an Obsidian note."""
    try:
        content = filepath.read_text()
        lines = content.split("\n")
        parts = []

        # Extract YAML frontmatter key fields
        in_frontmatter = False
        keep_keys = {"company", "role", "tags", "status", "deal_size", "last_contact", "email", "website"}
        for line in lines:
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    break
            if in_frontmatter:
                key = line.split(":")[0].strip()
                if key in keep_keys:
                    parts.append(line.strip())

        # Extract section headers
        sections = [l.strip() for l in lines if l.startswith("## ")]
        if sections:
            parts.append("")
            parts.append("Sections:")
            for s in sections:
                parts.append(f"  {s}")

        return "\n".join(parts)
    except Exception:
        return ""


def _extract_skill_preview(skill_dir: Path) -> str:
    """Extract skill description and file list."""
    try:
        parts = []
        skill_file = skill_dir / "SKILL.md"
        content = skill_file.read_text()

        # Extract description from frontmatter
        in_frontmatter = False
        for line in content.split("\n"):
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    break
            if in_frontmatter and line.startswith("description:"):
                parts.append(line.strip())

        # List files in skill directory
        files = sorted(f.name for f in skill_dir.iterdir() if f.is_file() and not f.name.startswith("."))
        if files:
            parts.append(f"\nFiles: {', '.join(files)}")

        return "\n".join(parts)
    except Exception:
        return ""


def _collect_tool_calls() -> Dict:
    """Collect tool call activity from hooks JSONL."""
    log_file = CLAUDE_DIR / ".claude" / "logs" / "tool-calls.jsonl"
    if not log_file.exists():
        return {"sessions": [], "by_tool": {}, "total_24h": 0, "recent": []}

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    records = []
    try:
        # Read last 2000 lines for performance
        result = subprocess.run(
            ["tail", "-2000", str(log_file)],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                ts = r.get("ts")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > cutoff_24h:
                        records.append(r)
            except Exception:
                pass
    except Exception:
        pass

    # Group by session
    sessions = defaultdict(lambda: {"tools": defaultdict(int), "count": 0, "errors": 0, "first_ts": None, "last_ts": None})
    by_tool = defaultdict(int)

    for r in records:
        sid = r.get("sid", "?")
        tool = r.get("tool", "?")
        s = sessions[sid]
        s["tools"][tool] += 1
        s["count"] += 1
        if not r.get("ok", True):
            s["errors"] += 1
        ts = r.get("ts")
        if not s["first_ts"] or ts < s["first_ts"]:
            s["first_ts"] = ts
        if not s["last_ts"] or ts > s["last_ts"]:
            s["last_ts"] = ts
        by_tool[tool] += 1

    # Format sessions
    session_list = []
    for sid, s in sessions.items():
        top_tools = sorted(s["tools"].items(), key=lambda x: -x[1])[:5]
        session_list.append({
            "session_id": sid,
            "count": s["count"],
            "errors": s["errors"],
            "tools_summary": ", ".join(f"{c}x {t}" for t, c in top_tools),
            "first_ts": s["first_ts"],
            "ago": _time_ago(s["last_ts"]),
        })
    session_list.sort(key=lambda x: x.get("first_ts", ""), reverse=True)

    # Recent calls (last 20)
    recent = []
    for r in records[-20:]:
        recent.append({
            "ts": r.get("ts"),
            "ago": _time_ago(r.get("ts")),
            "tool": r.get("tool", "?"),
            "summary": r.get("summary", ""),
            "ok": r.get("ok", True),
        })
    recent.reverse()

    return {
        "sessions": session_list[:10],
        "by_tool": dict(sorted(by_tool.items(), key=lambda x: -x[1])),
        "total_24h": len(records),
        "recent": recent,
    }


def _collect_reply_queue() -> Dict:
    """Collect pending reply tasks from gtasks JSONL."""
    gtasks_file = VADIMGEST_DIR / "data" / "sources" / "gtasks.jsonl"
    if not gtasks_file.exists():
        return {"items": [], "total": 0, "overdue": 0, "by_type": {}}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefixes = {"[SIG]": "signal", "[REPLY]": "reply", "[DEAL]": "deal",
                "[MTG]": "meeting", "[CAL]": "calendar", "[GITHUB]": "github"}
    items = []
    by_type = defaultdict(int)

    try:
        # Deduplicate: JSONL is append-only, keep last occurrence per task ID
        tasks_by_id = {}
        with open(gtasks_file) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    task_id = r.get("id", r.get("title", ""))
                    tasks_by_id[task_id] = r  # last write wins
                except Exception:
                    pass

        for r in tasks_by_id.values():
            title = r.get("title", "")
            status = r.get("status", "")
            if status != "needsAction":
                continue

            # Check for known prefixes
            task_type = "other"
            for prefix, ttype in prefixes.items():
                if title.startswith(prefix):
                    task_type = ttype
                    title = title[len(prefix):].strip()
                    break

            due = r.get("due")
            overdue = False
            if due and due[:10] < today:
                overdue = True

            by_type[task_type] += 1
            items.append({
                "title": title[:80],
                "type": task_type,
                "due": due[:10] if due else None,
                "overdue": overdue,
            })
    except Exception:
        pass

    # Sort: overdue first, then by type priority
    type_order = {"deal": 0, "reply": 1, "signal": 2, "meeting": 3, "calendar": 4, "github": 5, "other": 6}
    items.sort(key=lambda x: (not x["overdue"], type_order.get(x["type"], 9)))

    overdue_count = sum(1 for i in items if i["overdue"])
    return {
        "items": items[:15],
        "total": len(items),
        "overdue": overdue_count,
        "by_type": dict(by_type),
    }


def _collect_failing_jobs(all_runs: List[Dict], active_job_ids: set) -> List[Dict]:
    """Find active jobs whose last run was a failure."""
    # Get last run per job
    last_run_by_job = {}
    for r in all_runs:
        jid = r.get("job_id")
        if jid:
            last_run_by_job[jid] = r

    # Find currently failing jobs (only active ones from jobs.json)
    failing = []
    skip_jobs = {"_healthcheck", "_jobs_reload", "_sleep_wake_detector"}
    for jid, last in last_run_by_job.items():
        if jid in skip_jobs or jid not in active_job_ids:
            continue
        if last.get("error"):
            # Count consecutive failures from end
            consec = 0
            for r in reversed(all_runs):
                if r.get("job_id") == jid:
                    if r.get("error"):
                        consec += 1
                    else:
                        break
            failing.append({
                "job_id": jid,
                "error": (last.get("error") or "")[:200],
                "consecutive": consec,
                "last_failure": last.get("timestamp"),
                "ago": _time_ago(last.get("timestamp")),
            })

    failing.sort(key=lambda x: x["consecutive"], reverse=True)
    return failing


def _collect_skill_inventory() -> List[Dict]:
    """Scan skills directories. Returns name, description, last_modified, error_count, scenario_count."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills

    try:
        for skill_dir in sorted(SKILLS_DIR.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            name = skill_dir.name
            description = ""
            user_invocable = False
            last_modified = None

            # Parse frontmatter for description and user_invocable
            try:
                content = skill_file.read_text()
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        frontmatter = content[3:end].strip()
                        # Simple YAML-like parse for description
                        for line in frontmatter.split("\n"):
                            if line.startswith("description:"):
                                description = line[len("description:"):].strip().strip("'\"")
                            elif line.startswith("user_invocable:"):
                                val = line[len("user_invocable:"):].strip().lower()
                                user_invocable = val in ("true", "yes", "1")
            except Exception:
                pass

            # Last modified (most recent file in skill dir)
            try:
                mtimes = [f.stat().st_mtime for f in skill_dir.rglob("*") if f.is_file()]
                if mtimes:
                    last_modified = datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()
            except Exception:
                pass

            # Error count from errors.jsonl
            error_count = 0
            errors_file = skill_dir / "errors.jsonl"
            if errors_file.exists():
                try:
                    with open(errors_file) as f:
                        error_count = sum(1 for line in f if line.strip())
                except Exception:
                    pass

            # Scenario count - look in the scenarios skill directory for subdirs matching this skill name
            scenario_count = 0
            scenarios_dir = SKILLS_DIR / "scenarios"
            if scenarios_dir.exists():
                try:
                    for scenario in scenarios_dir.iterdir():
                        if scenario.is_dir() and scenario.name.startswith(name + "-"):
                            scenario_count += 1
                except Exception:
                    pass

            skills.append({
                "name": name,
                "description": description,
                "user_invocable": user_invocable,
                "last_modified": last_modified,
                "last_modified_ago": _time_ago(last_modified),
                "error_count": error_count,
                "scenario_count": scenario_count,
            })
    except Exception:
        pass

    # Merge call stats and git history
    call_stats = _collect_skill_call_stats()
    git_history = _collect_skill_git_history()

    for skill in skills:
        name = skill["name"]
        # Call stats
        cs = call_stats.get(name, {})
        skill["call_count"] = cs.get("total_calls", 0)
        skill["last_call"] = cs.get("last_call")
        skill["last_call_ago"] = cs.get("last_call_ago", "never")
        skill["calls"] = cs.get("calls", [])

        # Git history
        gh = git_history.get(name, {})
        skill["created"] = gh.get("created")
        skill["git_commits"] = gh.get("commits", [])
        skill["total_git_commits"] = gh.get("total_commits", 0)

    return skills


def _collect_skill_call_stats() -> Dict:
    """Parse tool-calls.jsonl for Skill invocations."""
    log_file = CLAUDE_DIR / ".claude" / "logs" / "tool-calls.jsonl"
    if not log_file.exists():
        return {}

    stats = defaultdict(lambda: {"total_calls": 0, "last_call": None, "calls": []})

    try:
        result = subprocess.run(
            ["tail", "-5000", str(log_file)],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get("tool") != "Skill":
                    continue
                skill_name = r.get("summary", "").strip()
                if not skill_name:
                    continue
                ts = r.get("ts")
                s = stats[skill_name]
                s["total_calls"] += 1
                s["calls"].append({
                    "ts": ts,
                    "sid": r.get("sid", ""),
                    "ok": r.get("ok", True),
                })
                if not s["last_call"] or (ts and ts > s["last_call"]):
                    s["last_call"] = ts
            except Exception:
                pass
    except Exception:
        pass

    # Add time ago
    for name, s in stats.items():
        s["last_call_ago"] = _time_ago(s["last_call"])
        # Keep only last 20 calls per skill
        s["calls"] = s["calls"][-20:]

    return dict(stats)


def _collect_skill_git_history() -> Dict:
    """Git log per skill directory."""
    result_data = {}
    if not SKILLS_DIR.exists():
        return result_data

    try:
        for skill_dir in SKILLS_DIR.iterdir():
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
                continue

            name = skill_dir.name
            rel_path = f".claude/skills/{name}/"

            try:
                git_result = subprocess.run(
                    ["git", "log", "--format=%H|%ai|%s", "-10", "--", rel_path],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(CLAUDE_DIR)
                )
                if git_result.returncode != 0:
                    continue

                commits = []
                first_date = None
                for line in git_result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        date_str = parts[1].strip()[:10]
                        commits.append({
                            "hash": parts[0].strip()[:8],
                            "date": date_str,
                            "message": parts[2].strip(),
                        })
                        first_date = date_str  # Last in list = earliest

                if commits:
                    result_data[name] = {
                        "created": first_date,
                        "commits": commits,
                        "total_commits": len(commits),
                    }
            except Exception:
                pass
    except Exception:
        pass

    return result_data


def _collect_daily_notes_status() -> Dict:
    """Read daily notes from memory/ directory."""
    memory_dir = CLAUDE_DIR / "memory"
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    result = {
        "today": {"exists": False, "lines": 0, "entries": 0, "last_entry_time": None},
        "yesterday": {"exists": False, "lines": 0, "entries": 0},
        "week_notes": [],
    }

    def _analyze_note(filepath):
        """Analyze a daily note file."""
        if not filepath.exists():
            return {"exists": False, "lines": 0, "entries": 0}
        try:
            content = filepath.read_text()
            lines = content.split("\n")
            # Count entries (lines starting with ## or ### as entry headers)
            entries = sum(1 for l in lines if l.startswith("## ") or l.startswith("### "))
            # Find last timestamp-like pattern (HH:MM)
            last_time = None
            for l in reversed(lines):
                m = re.search(r'(\d{1,2}:\d{2})', l)
                if m:
                    last_time = m.group(1)
                    break
            return {"exists": True, "lines": len(lines), "entries": entries, "last_entry_time": last_time}
        except Exception:
            return {"exists": False, "lines": 0, "entries": 0}

    result["today"] = _analyze_note(memory_dir / f"{today}.md")
    result["yesterday"] = _analyze_note(memory_dir / f"{yesterday}.md")

    # Week notes
    for i in range(7):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        note_path = memory_dir / f"{date}.md"
        info = _analyze_note(note_path)
        if info["exists"]:
            result["week_notes"].append({
                "date": date,
                "lines": info["lines"],
                "entries": info["entries"],
            })

    return result


def _collect_mcp_servers() -> List[Dict]:
    """Parse settings.json mcpServers section. Returns name, command, tool_count."""
    servers = []
    if not SETTINGS_FILE.exists():
        return servers

    try:
        settings = _safe_json_load(SETTINGS_FILE, default={})
        mcp_servers = settings.get("mcpServers", {})

        for name, config in sorted(mcp_servers.items()):
            command = config.get("command", "")
            args = config.get("args", [])

            # Build display command
            if args:
                # Show command + first meaningful arg
                cmd_display = command
                for arg in args:
                    if not arg.startswith("-"):
                        cmd_display = f"{command} {arg}"
                        break
            else:
                cmd_display = command

            # Tool count: count permissions that reference this server
            tool_count = 0
            perms = settings.get("permissions", {}).get("allow", [])
            prefix = f"mcp__{name}__"
            for perm in perms:
                if perm.startswith(prefix):
                    tool_count += 1

            servers.append({
                "name": name,
                "command": cmd_display,
                "tool_count": tool_count,
            })
    except Exception:
        pass

    return servers


def _collect_qq_markers(days: int = 7) -> List[Dict]:
    """Search vadimgest for qq/yy markers (frustration markers). Returns timestamp, context, resolved."""
    markers = []
    try:
        result = subprocess.run(
            ["python3", "-m", "vadimgest.search", "qq йй", "-n", "20", "--raw", "--json"],
            capture_output=True, text=True, timeout=5,
            cwd=str(CLAUDE_DIR)
        )
        if result.returncode != 0:
            return markers

        # Parse JSON output - could be a JSON array or JSONL
        output = result.stdout.strip()
        if not output:
            return markers

        try:
            items = json.loads(output)
            if not isinstance(items, list):
                items = [items]
        except json.JSONDecodeError:
            # Try JSONL
            items = []
            for line in output.split("\n"):
                if line.strip():
                    try:
                        items.append(json.loads(line))
                    except Exception:
                        pass

        # Filter to recent N days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        for item in items:
            ts = item.get("ts") or item.get("timestamp") or item.get("date")
            text = item.get("text") or item.get("content") or item.get("body") or ""
            source = item.get("source") or item.get("src") or ""

            # Check if within time window
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass

            # Check if text contains qq or yy marker
            if not re.search(r'\bqq\b|йй', text, re.IGNORECASE):
                continue

            # Check resolved status - look for "qq fix" in recent commits
            resolved = False
            # Simple heuristic: not checking git log for each, will be done in _collect_error_learning

            markers.append({
                "timestamp": ts,
                "ago": _time_ago(ts),
                "context": text[:200],
                "source": source,
                "resolved": resolved,
            })

    except Exception:
        pass

    return markers


def _collect_skill_changes(days: int = 7) -> List[Dict]:
    """Git log for skill changes with diff previews."""
    changes = []
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago",
             "--stat", "--format=%H|%ai|%s", "--", ".claude/skills/"],
            capture_output=True, text=True, timeout=10,
            cwd=str(CLAUDE_DIR)
        )
        if result.returncode != 0:
            return changes

        output = result.stdout.strip()
        if not output:
            return changes

        # Parse git log --stat output
        current_commit = None

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Check if this is a commit header line
            if "|" in line and line.count("|") >= 2:
                parts = line.split("|", 2)
                if len(parts) == 3 and len(parts[0]) == 40:
                    if current_commit:
                        changes.append(current_commit)

                    current_commit = {
                        "hash": parts[0].strip(),
                        "date": parts[1].strip(),
                        "message": parts[2].strip(),
                        "files_changed": 0,
                        "insertions": 0,
                        "deletions": 0,
                        "files": [],
                    }
                    continue

            if current_commit is None:
                continue

            if "file" in line and "changed" in line:
                m = re.search(r'(\d+) files? changed', line)
                if m:
                    current_commit["files_changed"] = int(m.group(1))
                m = re.search(r'(\d+) insertions?\(\+\)', line)
                if m:
                    current_commit["insertions"] = int(m.group(1))
                m = re.search(r'(\d+) deletions?\(-\)', line)
                if m:
                    current_commit["deletions"] = int(m.group(1))
            elif "|" in line:
                file_part = line.split("|")[0].strip()
                if file_part:
                    current_commit["files"].append(file_part)

        if current_commit:
            changes.append(current_commit)

        # Fetch diff previews for each commit (max 20 commits, 80 lines per diff)
        for change in changes[:20]:
            try:
                diff_result = subprocess.run(
                    ["git", "show", change["hash"], "--format=", "--", ".claude/skills/"],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(CLAUDE_DIR)
                )
                if diff_result.returncode == 0 and diff_result.stdout.strip():
                    lines = diff_result.stdout.strip().split("\n")
                    # Keep only +/- lines and file headers, skip noise
                    filtered = []
                    for dl in lines:
                        if dl.startswith("diff --git"):
                            # Extract short filename
                            parts = dl.split(" b/", 1)
                            if len(parts) > 1:
                                filtered.append(f"--- {parts[1]} ---")
                        elif dl.startswith("+") and not dl.startswith("+++"):
                            filtered.append(dl)
                        elif dl.startswith("-") and not dl.startswith("---"):
                            filtered.append(dl)
                    change["diff_preview"] = "\n".join(filtered[:80])
            except Exception:
                pass

    except Exception:
        pass

    return changes


def _collect_obsidian_metrics() -> Dict:
    """Collect Obsidian vault metrics: note counts, folder breakdown, recent activity."""
    result = {
        "total_notes": 0,
        "people": 0,
        "organizations": 0,
        "modified_24h": 0,
        "recent_files": [],
    }
    if not OBSIDIAN_DIR.exists():
        return result

    try:
        now = time.time()
        cutoff_24h = now - 86400
        all_files = []

        for f in OBSIDIAN_DIR.rglob("*.md"):
            parts = f.relative_to(OBSIDIAN_DIR).parts
            if any(p.startswith(".") for p in parts):
                continue
            result["total_notes"] += 1
            mtime = f.stat().st_mtime
            if mtime > cutoff_24h:
                result["modified_24h"] += 1
            all_files.append((f, mtime))

            if len(parts) > 1:
                if parts[0] == "People":
                    result["people"] += 1
                elif parts[0] == "Organizations":
                    result["organizations"] += 1

        all_files.sort(key=lambda x: x[1], reverse=True)
        for f, mtime in all_files[:5]:
            parts = f.relative_to(OBSIDIAN_DIR).parts
            folder = parts[0] if len(parts) > 1 else "root"
            result["recent_files"].append({
                "name": f.stem,
                "folder": folder,
                "modified_ago": _time_ago(datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()),
            })
    except Exception:
        pass

    return result


def _collect_claude_md_details() -> Dict:
    """CLAUDE.md details: memory section size, last modified, recent changes."""
    claude_md = CLAUDE_DIR / ".claude" / "CLAUDE.md"
    result = {
        "memory_lines": 0,
        "last_modified": None,
        "last_modified_ago": "never",
        "recent_changes": [],
    }
    if not claude_md.exists():
        return result

    try:
        content = claude_md.read_text()
        in_memory = False
        for line in content.split("\n"):
            if "<MEMORY>" in line:
                in_memory = True
                continue
            if "</MEMORY>" in line:
                in_memory = False
                continue
            if in_memory:
                result["memory_lines"] += 1

        mtime = claude_md.stat().st_mtime
        result["last_modified"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        result["last_modified_ago"] = _time_ago(result["last_modified"])
    except Exception:
        pass

    try:
        git_result = subprocess.run(
            ["git", "log", "--since=7 days ago", "--format=%ai|%s", "-5",
             "--", ".claude/CLAUDE.md"],
            capture_output=True, text=True, timeout=5,
            cwd=str(CLAUDE_DIR)
        )
        if git_result.returncode == 0:
            for line in git_result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 1)
                if len(parts) == 2:
                    result["recent_changes"].append({
                        "date": parts[0].strip(),
                        "date_ago": _time_ago(parts[0].strip()),
                        "message": parts[1].strip(),
                    })
    except Exception:
        pass

    return result


def _collect_error_learning(days: int = 7, qq_markers: List = None, skill_changes: List = None) -> Dict:
    """Aggregate learning metrics from errors, qq markers, and skill changes."""
    # Collect errors from all skills
    errors_found = 0
    if SKILLS_DIR.exists():
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            for skill_dir in SKILLS_DIR.iterdir():
                if not skill_dir.is_dir():
                    continue
                errors_file = skill_dir / "errors.jsonl"
                if not errors_file.exists():
                    continue
                try:
                    with open(errors_file) as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                r = json.loads(line)
                                ts = r.get("ts") or r.get("timestamp")
                                if ts:
                                    dt = datetime.fromisoformat(ts)
                                    if dt.tzinfo is None:
                                        dt = dt.replace(tzinfo=timezone.utc)
                                    if dt > cutoff:
                                        errors_found += 1
                            except Exception:
                                errors_found += 1  # Count unparseable as recent
                except Exception:
                    pass
        except Exception:
            pass

    # QQ markers (reuse if already collected)
    if qq_markers is None:
        qq_markers = _collect_qq_markers(days)
    qq_found = len(qq_markers)

    # Skill changes from git (reuse if already collected)
    if skill_changes is None:
        skill_changes = _collect_skill_changes(days)
    skills_modified = set()
    skills_added = set()
    scenarios_created = 0

    for change in skill_changes:
        msg = change.get("message", "").lower()
        for f in change.get("files", []):
            # Extract skill name from path like .claude/skills/foo/SKILL.md
            parts = f.replace(".claude/skills/", "").split("/")
            if parts:
                skill_name = parts[0]
                if skill_name:
                    skills_modified.add(skill_name)

        # Detect new skills (heuristic: commit message contains "create" or "add" + "skill")
        if "create" in msg and "skill" in msg:
            for f in change.get("files", []):
                parts = f.replace(".claude/skills/", "").split("/")
                if parts:
                    skills_added.add(parts[0])

        # Detect new scenarios
        if "scenario" in msg:
            for f in change.get("files", []):
                if "scenarios/" in f:
                    scenarios_created += 1

    return {
        "errors_found": errors_found,
        "qq_found": qq_found,
        "skills_modified": sorted(skills_modified),
        "skills_added": sorted(skills_added),
        "scenarios_created": scenarios_created,
        "days": days,
    }


_SUPPRESSED_SERVICE_LABELS: set = {
    # Legacy/disabled daemons whose failure state is expected and shouldn't alert.
    f"{LAUNCHD_PREFIX}.telegram-daemon",
}


def _service_is_expected(label: str) -> bool:
    """Return False for services the user has opted out of, so the dashboard
    doesn't show "Services down" for daemons whose backing config is empty.

    Mapping is conservative: only flag a service as not-expected when the
    operator clearly hasn't configured it. Anything else stays expected so
    real outages still surface.
    """
    short = label.split(".")[-1]  # e.g. "tg-gateway"

    # tg-gateway: requires telegram.bot_token. The example config sets
    # `${TG_BOT_TOKEN}`; if that env var is empty (the user skipped the
    # Telegram step in the wizard), the daemon will exit immediately on
    # boot and the service appears as down. That's intentional, not a fault.
    if short == "tg-gateway":
        token = (_cfg.telegram().get("bot_token") or "").strip()
        # Treat unresolved ${...} placeholders as "not configured".
        if not token or token.startswith("${") or token == "0":
            return False
        chat = _cfg.telegram_chat_id()
        if not chat:
            return False
    return True


def _collect_services() -> List[Dict]:
    """Get service status from launchctl. Discovers services dynamically from plist files."""
    launch_agents_dir = _cfg.launch_agents_dir()

    # Discover all <prefix>.* plist files
    labels: Dict[str, str] = {}
    periodic_labels: set = set()
    if launch_agents_dir.exists():
        for plist_file in sorted(launch_agents_dir.glob(f"{LAUNCHD_PREFIX}.*.plist")):
            label = plist_file.stem  # e.g. com.local.tg-gateway
            if label in _SUPPRESSED_SERVICE_LABELS:
                continue
            # Derive display name: com.local.tg-gateway -> TG Gateway
            short = label.replace(f"{LAUNCHD_PREFIX}.", "")
            display = " ".join(
                w.upper() if len(w) <= 3 else w.capitalize()
                for w in short.replace("-", " ").split()
            )
            labels[label] = display
            # Check if periodic (StartInterval in plist)
            try:
                import plistlib
                with open(plist_file, "rb") as f:
                    pdata = plistlib.load(f)
                if pdata.get("StartInterval"):
                    periodic_labels.add(label)
            except Exception:
                pass

    services = []
    try:
        result = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=5
        )
        for label, display_name in labels.items():
            found = False
            for line in result.stdout.split("\n"):
                if label in line:
                    parts = line.split()
                    pid = parts[0] if len(parts) >= 1 and parts[0] != "-" else None
                    exit_code = parts[1] if len(parts) >= 2 else None
                    # Periodic tasks: PID="-" + exit=0 means healthy (waiting for next run)
                    is_periodic = label in periodic_labels
                    if is_periodic:
                        running = pid is not None or exit_code == "0"
                    else:
                        running = pid is not None
                    services.append({
                        "name": display_name,
                        "label": label,
                        "running": running,
                        "pid": pid or ("periodic" if is_periodic and exit_code == "0" else None),
                        "expected": _service_is_expected(label),
                    })
                    found = True
                    break
            if not found:
                services.append({
                    "name": display_name,
                    "label": label,
                    "running": False,
                    "pid": None,
                    "expected": _service_is_expected(label),
                })
    except Exception:
        for label, display_name in labels.items():
            services.append({
                "name": display_name,
                "label": label,
                "running": False,
                "pid": None,
                "expected": _service_is_expected(label),
            })
    return services


# ── Files data collector (separate cache, lazy-loaded) ────────────────

_files_cache: Dict = {"data": None, "ts": 0, "date": None}
_FILES_CACHE_TTL = 30  # seconds

# Directories whose .md files are worth surfacing in the Files tab.
# Scanned non-recursively except where noted. Daily notes, plans, pure vendored
# content, and the submodule are deliberately excluded.
_MD_LIBRARY_DIRS = [
    # (sub-path, category, recursive, max_depth)
    (".claude/skills",          "Skills",    True,  4),
    ("tasks",                   "Tasks",     True,  2),
    ("gateway",                 "Gateway",   True,  3),
    ("self-evolve",             "Docs",      True,  2),
    ("qmd",                     "Docs",      False, 1),
    ("changelog",               "Changelog", False, 1),
    ("",                        "Docs",      False, 1),  # top-level README etc.
]

# Path fragments we never want to surface even when inside an included dir.
_MD_LIBRARY_SKIP_FRAGMENTS = (
    "/node_modules/", "/.git/", "/__pycache__/", "/.pytest_cache/",
    "/.claude/plugins/", "/.claude/cache/", "/.claude/plans/",
    "/.claude/projects/", "/vadimgest/", "/qmd/test/",
    "/.claude/state/", "/memory/",
)


def _md_library_label(rel_path: str, category: str) -> str:
    """Produce a compact human label for a library entry."""
    parts = rel_path.split("/")
    if category == "Skills":
        # .claude/skills/heartbeat/SKILL.md           -> "heartbeat"
        # .claude/skills/personal/heartbeat/SKILL.md  -> "heartbeat (personal)"
        # .claude/skills/heartbeat/PERSONAL.md        -> "heartbeat / PERSONAL.md"
        # .claude/skills/personal/scenarios/x/SKILL.md-> "scenarios/x (personal)"
        tail = parts[2:] if len(parts) > 2 else parts
        is_personal = bool(tail) and tail[0] == "personal"
        if is_personal:
            tail = tail[1:]
        suffix = " (personal)" if is_personal else ""
        if len(tail) >= 2 and tail[-1] == "SKILL.md":
            return "/".join(tail[:-1]) + suffix
        if len(tail) >= 2:
            return f"{tail[0]} / {'/'.join(tail[1:])}{suffix}"
        return "/".join(tail) + suffix
    return rel_path


def _collect_md_library() -> List[Dict]:
    """Discover valuable .md files across the repo. Metadata only — no content."""
    entries: List[Dict] = []
    seen: set = set()
    root = CLAUDE_DIR

    for sub, category, recursive, max_depth in _MD_LIBRARY_DIRS:
        base = root / sub if sub else root
        if not base.exists():
            continue
        try:
            if recursive:
                iterator = base.rglob("*.md")
            else:
                iterator = base.glob("*.md")
            for path in iterator:
                try:
                    rel = path.relative_to(root).as_posix()
                except Exception:
                    continue
                if rel in seen:
                    continue
                rel_fragment = "/" + rel
                if any(skip in rel_fragment for skip in _MD_LIBRARY_SKIP_FRAGMENTS):
                    continue
                if recursive and max_depth:
                    depth = len(path.relative_to(base).parts)
                    if depth > max_depth:
                        continue
                try:
                    st = path.stat()
                except Exception:
                    continue
                seen.add(rel)
                modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                entries.append({
                    "id": rel,
                    "path": rel,
                    "label": _md_library_label(rel, category),
                    "category": category,
                    "size": st.st_size,
                    "modified": modified,
                    "modified_ago": _time_ago(modified),
                })
        except Exception:
            continue

    # Stable sort: category first, then label
    entries.sort(key=lambda e: (e["category"], e["label"].lower()))
    return entries


def read_md_library_file(rel_path: str) -> Optional[Dict]:
    """Read a single .md file listed in the library. Returns None if not allowed.

    Allowlist: path must be discovered by _collect_md_library() to prevent
    arbitrary reads via the endpoint.
    """
    if not rel_path or not rel_path.endswith(".md"):
        return None
    # Normalize to forward slashes, reject traversal
    norm = rel_path.replace("\\", "/").lstrip("/")
    if ".." in norm.split("/"):
        return None
    library = _collect_md_library()
    allowed = {e["path"] for e in library}
    if norm not in allowed:
        return None
    path = CLAUDE_DIR / norm
    try:
        content = path.read_text(errors="replace")
    except Exception:
        return None
    st = path.stat()
    modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    return {
        "path": norm,
        "content": content,
        "lines": len(content.split("\n")),
        "size": st.st_size,
        "modified": modified,
        "modified_ago": _time_ago(modified),
    }


def collect_files_data(date: str = None) -> Dict:
    """Collect file contents for the Files tab. Separate 30s cache.

    Args:
        date: Optional YYYY-MM-DD for a specific daily note.
              If None, returns today + yesterday.
    """
    now_ts = time.time()
    cache_key = date or "__default__"
    if (_files_cache["data"]
            and (now_ts - _files_cache["ts"]) < _FILES_CACHE_TTL
            and _files_cache["date"] == cache_key):
        return _files_cache["data"]

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # CLAUDE.md
    claude_md_path = CLAUDE_DIR / ".claude" / "CLAUDE.md"
    claude_md_content = ""
    claude_md_lines = 0
    claude_md_modified = None
    if claude_md_path.exists():
        try:
            claude_md_content = claude_md_path.read_text()
            claude_md_lines = len(claude_md_content.split("\n"))
            claude_md_modified = datetime.fromtimestamp(
                claude_md_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except Exception:
            pass

    # MEMORY.md - uses project_slug from config to find the right project dir
    _slug = _cfg.project_slug()
    memory_md_path = (CLAUDE_DIR / ".claude" / "projects"
                      / _slug / "memory" / "MEMORY.md") if _slug else None
    memory_md_content = ""
    memory_md_lines = 0
    if memory_md_path and memory_md_path.exists():
        try:
            memory_md_content = memory_md_path.read_text()
            memory_md_lines = len(memory_md_content.split("\n"))
        except Exception:
            pass

    # Daily notes
    memory_dir = CLAUDE_DIR / "memory"
    daily_notes = {}

    def _read_daily(date_str: str) -> Dict:
        path = memory_dir / f"{date_str}.md"
        if path.exists():
            try:
                content = path.read_text()
                return {
                    "exists": True,
                    "content": content,
                    "lines": len(content.split("\n")),
                    "modified": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            except Exception:
                pass
        return {"exists": False, "content": "", "lines": 0, "modified": None}

    if date:
        daily_notes[date] = _read_daily(date)
    else:
        daily_notes[today] = _read_daily(today)
        daily_notes[yesterday] = _read_daily(yesterday)

    # Available dates from memory/ directory
    available_dates = []
    if memory_dir.exists():
        try:
            for f in sorted(memory_dir.iterdir(), reverse=True):
                if f.suffix == ".md" and re.match(r'\d{4}-\d{2}-\d{2}', f.stem):
                    available_dates.append(f.stem)
        except Exception:
            pass

    md_library = _collect_md_library()

    result = {
        "generated_at": now.isoformat(),
        "claude_md": {
            "content": claude_md_content,
            "lines": claude_md_lines,
            "modified": claude_md_modified,
            "modified_ago": _time_ago(claude_md_modified),
        },
        "memory_md": {
            "content": memory_md_content,
            "lines": memory_md_lines,
        },
        "daily_notes": daily_notes,
        "today": today,
        "yesterday": yesterday,
        "available_dates": available_dates[:60],
        "total_notes": len(available_dates),
        "md_library": md_library,
    }

    _files_cache["data"] = result
    _files_cache["ts"] = now_ts
    _files_cache["date"] = cache_key
    return result


# ── Pipeline state collector ───────────────────────────────────────────

PIPELINE_STATE_DIR = CLAUDE_DIR / ".claude" / "state" / "sessions"
PIPELINE_COMPLETED_DIR = CLAUDE_DIR / ".claude" / "state" / "completed"
PIPELINES_DIR = CLAUDE_DIR / ".claude" / "pipelines"


def collect_pipelines_data() -> Dict:
    """Collect pipeline state machine data for dashboard."""
    now = datetime.now(timezone.utc)

    # Available pipeline definitions
    definitions = []
    if PIPELINES_DIR.exists():
        for p in sorted(PIPELINES_DIR.glob("*.yaml")):
            try:
                import yaml as _yaml
                with open(p) as f:
                    pdef = _yaml.safe_load(f)
                states = pdef.get("states", {})
                terminal_states = [k for k, v in states.items() if v.get("terminal")]
                transitions = pdef.get("transitions", [])
                settings = pdef.get("settings", {})
                definitions.append({
                    "name": pdef.get("name", p.stem),
                    "description": pdef.get("description", ""),
                    "states": list(states.keys()),
                    "terminal_states": terminal_states,
                    "transition_count": len(transitions),
                    "initial_state": settings.get("initial_state", ""),
                    "max_retries": settings.get("max_retries", 0),
                    "transitions": [
                        {
                            "from": t["from"],
                            "to": t["to"],
                            "label": t.get("label", ""),
                        }
                        for t in transitions
                    ],
                    "state_details": {
                        k: {"description": v.get("description", ""), "terminal": v.get("terminal", False)}
                        for k, v in states.items()
                    },
                })
            except Exception:
                pass

    # Active sessions
    active = []
    if PIPELINE_STATE_DIR.exists():
        for f in sorted(PIPELINE_STATE_DIR.glob("*.json")):
            try:
                with open(f) as fh:
                    s = json.load(fh)
                started = datetime.fromisoformat(s["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                state_entered = datetime.fromisoformat(s["state_entered_at"])
                if state_entered.tzinfo is None:
                    state_entered = state_entered.replace(tzinfo=timezone.utc)

                total_dur = (now - started).total_seconds()
                state_dur = (now - state_entered).total_seconds()

                active.append({
                    "session_id": s.get("session_id", "")[:16],
                    "pipeline": s.get("pipeline", ""),
                    "instance_id": s.get("instance_id", ""),
                    "current_state": s.get("current_state", ""),
                    "started_at": s.get("started_at"),
                    "started_ago": _time_ago(s.get("started_at")),
                    "state_entered_at": s.get("state_entered_at"),
                    "state_duration_s": int(state_dur),
                    "total_duration_s": int(total_dur),
                    "total_duration_display": _fmt_seconds(int(total_dur)),
                    "retry_count": s.get("retry_count", 0),
                    "context": s.get("context", {}),
                    "history": s.get("history", [])[-10:],
                })
            except (json.JSONDecodeError, OSError, KeyError):
                pass

    # Completed today
    completed_today = []
    if PIPELINE_COMPLETED_DIR.exists():
        today_str = now.strftime("%Y-%m-%d")
        for f in sorted(PIPELINE_COMPLETED_DIR.glob("*.json"), reverse=True):
            try:
                with open(f) as fh:
                    s = json.load(fh)
                if today_str in s.get("started_at", ""):
                    completed_today.append({
                        "session_id": s.get("session_id", "")[:16],
                        "pipeline": s.get("pipeline", ""),
                        "instance_id": s.get("instance_id", ""),
                        "final_state": s.get("current_state", ""),
                        "started_at": s.get("started_at"),
                        "retry_count": s.get("retry_count", 0),
                        "context": s.get("context", {}),
                        "history_length": len(s.get("history", [])),
                    })
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "generated_at": now.isoformat(),
        "definitions": definitions,
        "active": active,
        "completed_today": completed_today[:20],
        "stats": {
            "active_count": len(active),
            "completed_today_count": len(completed_today),
            "definition_count": len(definitions),
        },
    }


def _fmt_seconds(s: int) -> str:
    """Format seconds to human display."""
    if s < 60:
        return f"{s}s"
    m = s // 60
    sec = s % 60
    if m < 60:
        return f"{m}m{sec:02d}s"
    h = m // 60
    mins = m % 60
    return f"{h}h{mins:02d}m"


# ================================================================
#   TASKS TAB - Google Tasks + GitHub Projects
# ================================================================

_tasks_cache: Dict = {"data": None, "ts": 0}
# Bumped 30 -> 90 (Apr 23 2026): /api/tasks fetches every Google Tasks list
# (one subprocess per list). The Deck polls /api/tasks every 5 min anyway —
# 30s TTL was burning ~5k Google API calls/day for no UX benefit.
_TASKS_CACHE_TTL = 90  # seconds

GOG_BIN = _cfg.google_cli()
GOG_ACCOUNT = _cfg.google_account()


def _parse_klava_frontmatter(text: str) -> Dict:
    """Parse YAML frontmatter from Klava task notes. Returns flat dict with _body key."""
    if not text or not text.strip().startswith("---"):
        return {"_body": text or ""}
    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {"_body": text}
    meta = {}
    for line in lines[1:end_idx]:
        line = line.strip()
        if ": " in line:
            key, _, value = line.partition(": ")
            meta[key.strip()] = value.strip()
        elif line.endswith(":"):
            meta[line[:-1].strip()] = ""
    meta["_body"] = "\n".join(lines[end_idx + 1:]).strip()
    return meta
def _google_tasks_lists() -> List[tuple]:
    """List of (list_id, list_name) tuples from config."""
    return [(lid, name) for name, lid in _cfg.google_tasks_lists().items()]


GOOGLE_TASKS_LISTS = _google_tasks_lists()


def _gog_run(args: List[str], timeout: int = 30) -> Optional[str]:
    """Run a gog CLI command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            [GOG_BIN] + args + ["-a", GOG_ACCOUNT, "-j", "--no-input"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return None


def _fetch_google_tasks() -> List[Dict]:
    """Fetch open tasks from Google Tasks via the snapshot module.

    The snapshot bootstraps once per list, then refreshes incrementally via
    `--updated-min` deltas. The 30s `_TASKS_CACHE_TTL` above is layered on
    top to absorb burst polls inside a single dashboard tab without even
    hitting the snapshot's mtime check.
    """
    import sys
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tasks import snapshot

    tasks = []
    for list_id, list_name in GOOGLE_TASKS_LISTS:
        try:
            items = snapshot.get_all(list_id, include_completed=False)
        except Exception:
            continue
        for item in items:
            tasks.append({**item, "_list_id": list_id, "_list_name": list_name})
    return tasks


def _fetch_github_items(owner: str, project: int) -> List[Dict]:
    """Fetch open items from a GitHub Project.

    Logs (not swallows) errors so a broken `gh` subprocess or auth failure
    doesn't silently empty out the Tasks tab. Seen in the wild on 2026-04-21
    when the dashboard showed 0 GH tasks and the GH toggle did nothing.
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        result = subprocess.run(
            ["gh", "project", "item-list", str(project), "--owner", owner, "--format", "json", "--limit", "500"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("items", [])
        log.warning(
            "gh project item-list failed owner=%s project=%s rc=%s stderr=%s",
            owner, project, result.returncode, (result.stderr or "").strip()[:400],
        )
    except FileNotFoundError:
        log.warning("gh CLI not found on PATH - GitHub tasks will be empty")
    except subprocess.TimeoutExpired:
        log.warning("gh project item-list timed out owner=%s project=%s", owner, project)
    except Exception as e:
        log.warning("gh project item-list error owner=%s project=%s: %r", owner, project, e)
    return []


def _categorize_task(title: str, due: Optional[str], today: str, source: str) -> Dict:
    """Categorize a task into section and assign tags."""
    prefixes = {
        "[CRITICAL]": "critical", "[DEAL]": "deal", "[REPLY]": "reply",
        "[SIG]": "reply", "[EMAIL]": "reply",
        "[MTG]": "meeting", "[CAL]": "calendar", "[PREP]": "meeting",
        "[EVENT]": "calendar",
        "[GITHUB]": "primary-gh",
        "[DATA]": "deal", "[DOC]": "deal", "[CALL]": "deal", "[PING]": "deal",
        "[LEAD]": "deal", "[INTRO]": "deal", "[FOLLOW-UP]": "deal",
        "[PROMISE]": "personal", "[DECIDE]": "personal", "[ACTION]": "personal",
        "[READ]": "personal", "[REVIEW]": "personal",
        "[DELEGATE]": "personal", "[FINANCE]": "personal", "[ADMIN]": "personal",
        "[PAY]": "personal", "[INFRA]": "personal",
        "[DISPATCH]": "personal", "[BUG]": "personal",
        "[URGENT]": "critical",
        # Non-standard tags (legacy/auto-created) - map to closest standard
        "[FEATURE]": "personal", "[PRICING]": "deal", "[CONNECT]": "deal",
        "[RESEARCH]": "personal", "[DRAFT]": "reply", "[SYNC]": "meeting",
        "[TASK]": "personal", "[SECURITY]": "critical", "[PERSONAL]": "personal",
    }

    tags = []
    clean_title = title
    # Extract all leading [TAG] prefixes (supports [CRITICAL][DEAL] etc.)
    remaining = title
    while remaining:
        matched = False
        for prefix, _ in prefixes.items():
            if remaining.upper().startswith(prefix):
                tag_name = prefix.strip("[]")
                tags.append(tag_name)
                remaining = remaining[len(prefix):].strip()
                matched = True
                break
        if not matched:
            break
    clean_title = remaining if remaining else title

    # Determine section
    overdue = False
    is_today = False
    if due:
        due_date = due[:10]
        if due_date < today:
            overdue = True
        elif due_date == today:
            is_today = True

    if overdue:
        section = "overdue"
    elif is_today:
        section = "today"
    elif any(t in tags for t in ["DEAL", "DATA", "DOC", "CALL", "PING", "LEAD", "INTRO", "FOLLOW-UP"]):
        section = "deals"
    elif any(t in tags for t in ["REPLY", "SIG", "EMAIL"]):
        section = "replies"
    elif any(t in tags for t in ["MTG", "PREP", "EVENT", "CAL"]):
        section = "meeting"
    elif source == "github":
        section = "primary-gh"
    elif any(t in tags for t in ["CRITICAL", "URGENT"]):
        section = "overdue"  # critical = treat as urgent
    else:
        section = "personal"

    # Tag styling
    tag_colors = {
        "CRITICAL": "red", "URGENT": "red",
        "DEAL": "green", "DATA": "green", "DOC": "green", "CALL": "green",
        "PING": "green", "LEAD": "green", "INTRO": "green", "FOLLOW-UP": "green",
        "REPLY": "yellow", "SIG": "yellow", "EMAIL": "yellow",
        "MTG": "blue", "CAL": "blue", "GITHUB": "blue", "GH": "blue",
        "PREP": "blue", "EVENT": "blue",
        "BUG": "orange",
        "PROMISE": "purple", "DECIDE": "purple",
        "ACTION": "gray", "READ": "gray", "REVIEW": "gray",
        "DELEGATE": "gray", "FINANCE": "gray", "ADMIN": "gray",
        "PAY": "gray", "INFRA": "gray", "DISPATCH": "gray",
        # Non-standard (legacy) tags
        "FEATURE": "orange", "PRICING": "green", "CONNECT": "green",
        "RESEARCH": "gray", "DRAFT": "yellow", "SYNC": "blue",
        "TASK": "gray", "SECURITY": "red", "PERSONAL": "gray",
    }

    styled_tags = [{"name": t, "color": tag_colors.get(t, "gray")} for t in tags]
    bold = "CRITICAL" in tags or overdue

    return {
        "clean_title": clean_title,
        "section": section,
        "tags": styled_tags,
        "overdue": overdue,
        "is_today": is_today,
        "bold": bold,
    }


# --- Smart task classification ---

def _known_people() -> List[tuple]:
    """List of (matchers, name) tuples from config.personal.known_people."""
    return [(p.get("matchers", []), p.get("name", "")) for p in _cfg.known_people()]


def _gh_login_map() -> Dict[str, Optional[str]]:
    """GitHub login → display name mapping. None means self (skip)."""
    return _cfg.github_login_map()


_KNOWN_PEOPLE = _known_people()
_GH_LOGIN_MAP = _gh_login_map()

# Prefixes stripped for duplicate detection
_STRIP_PREFIXES_RE = re.compile(
    r"^\[(TASK|DEAL|PREP|URGENT|ACTION|FEATURE|BUG|REPLY|PING|MTG|SYNC|DECIDE|CRITICAL|SECURITY|CANCELLED|READ|REVIEW|EVENT|CAL|PROMISE|DELEGATE|DISPATCH|LEAD|INTRO|FOLLOW-UP|SIG|EMAIL|DATA|DOC|CALL|FINANCE|ADMIN|PAY|INFRA|PERSONAL|PRICING|CONNECT|RESEARCH|DRAFT|GH|GITHUB)\]\s*",
    re.IGNORECASE,
)


def _extract_person(title: str, notes: str, assignee_names: list) -> Optional[str]:
    """Extract the most relevant person name from task context. Returns None if no match or self."""
    title_lower = title.lower()
    notes_lower = notes[:200].lower() if notes else ""

    # Check title first (highest signal)
    for keywords, person_name in _KNOWN_PEOPLE:
        for kw in keywords:
            if kw in title_lower:
                return person_name

    # Check notes (first 200 chars)
    for keywords, person_name in _KNOWN_PEOPLE:
        for kw in keywords:
            if kw in notes_lower:
                return person_name

    # Check GH assignee logins
    for login in assignee_names:
        mapped = _GH_LOGIN_MAP.get(login)
        if mapped is not None:  # None = self (skip)
            return mapped
        # If login not in map, skip (unknown)

    return None


def _classify_task_smart(task: dict) -> None:
    """Add action_type, domain, person, priority_score, auto_tags, group_key to a task dict (mutates in place)."""
    title = task.get("raw_title") or task.get("title") or ""
    title_lower = title.lower()
    notes = task.get("notes") or ""
    notes_lower = notes.lower()
    combined = title_lower + " " + notes_lower
    section = task.get("section", "")
    source = task.get("source", "")
    overdue_days = task.get("overdue_days", 0)
    is_today = task.get("is_today", False)
    tag_names = [t.get("name", "") for t in task.get("tags", [])]
    tag_names_lower = [n.lower() for n in tag_names]

    # --- Domain detection ---
    # Domains and their keyword lists come from config.personal.domain_keywords.
    domain = "personal"
    domain_kw = _cfg.domain_keywords()
    for dom_name, keywords in domain_kw.items():
        if any(kw in title_lower for kw in keywords) or dom_name in tag_names_lower:
            domain = dom_name
            break

    # --- Auto-tags detection ---
    auto_tags = []
    payment_kw = ["payment", "billing", "card expired", "card failed", "subscription", "invoice"]
    if any(kw in combined for kw in payment_kw):
        auto_tags.append("payment")
    security_kw = ["phishing", "security", "hack", "fake", "malware"]
    if any(kw in combined for kw in security_kw):
        auto_tags.append("security")
    if "[bug]" in title_lower or any(kw in title_lower for kw in ["bug ", "crash", "crashing", "broken"]):
        auto_tags.append("bug")
    if "[feature]" in title_lower or "feature request" in title_lower:
        auto_tags.append("feature")
    if any(kw in combined for kw in ["infra", "migration", "deploy", "server", "clickhouse migration"]):
        auto_tags.append("infra")

    # --- Action type detection (priority order) ---
    action_type = "personal"  # default

    # 1. GitHub tasks keep their section (e.g. "primary-gh" / "secondary-gh",
    # or whatever user configured via personal.github_projects[].section).
    if source == "github":
        action_type = section
    # 1b. Non-standard tag normalization for action_type
    elif "[feature]" in title_lower:
        action_type = "personal"  # feature requests = action items
    elif "[pricing]" in title_lower:
        action_type = "deals"
    elif "[connect]" in title_lower or "[intro]" in title_lower:
        action_type = "reach-out"
    elif "[draft]" in title_lower:
        action_type = "reach-out"
    elif "[sync]" in title_lower and overdue_days <= 2:
        action_type = "personal"
    elif "[research]" in title_lower:
        action_type = "personal"
    # 2. Archive: past meeting preps/syncs
    elif any(p in title_lower for p in ["[prep]", "[sync]", "[mtg]"]) and overdue_days > 2:
        action_type = "archive"
    # 3. Fix now: payments, security, critical, urgent, bugs (non-github), broken/fix in first 20 chars
    elif "payment" in auto_tags or "security" in auto_tags:
        action_type = "fix-now"
    elif any(kw in title_lower for kw in ["[critical]", "[security]", "[urgent]"]):
        action_type = "fix-now"
    elif "[bug]" in title_lower and source != "github":
        action_type = "fix-now"
    elif any(kw in title_lower[:20] for kw in ["fix", "broken"]):
        action_type = "fix-now"
    # 4. Reach out: replies, pings, messages to send
    elif any(kw in title_lower for kw in ["[reply]", "[ping]"]):
        action_type = "reach-out"
    elif any(kw in title_lower for kw in ["написать", "пинг", "follow up", "reply to", "send ", "respond", "ping "]):
        action_type = "reach-out"
    # 5. Decide: decisions needed
    elif "[decide]" in title_lower or any(kw in title_lower for kw in ["решить", "decide"]):
        action_type = "decide"
    # 6. Delegate: team tasks
    elif any(title_lower.startswith("[task] " + name) for name in TEAM_MEMBERS):
        action_type = "delegate"
    # 7. Deals
    elif "[deal]" in title_lower or section == "deals":
        action_type = "deals"
    # 8. Waiting
    elif any(kw in combined for kw in ["ждём", "waiting", "мяч на их", "ожидаем", "pending their"]):
        action_type = "waiting"
    # 9. Graveyard: 30d+ overdue
    elif overdue_days >= 30:
        action_type = "graveyard"

    # --- Person extraction ---
    assignee_names = []
    if source == "github" and notes:
        assignee_names = [n.strip() for n in notes.split(",") if n.strip()]
    person = _extract_person(title, notes, assignee_names)

    # --- Priority score (0-100) ---
    score = 0
    text = combined

    # Deal value - scored by priority deals config
    for kw, pts in PRIORITY_DEAL_SCORES:
        if kw in text:
            score += pts
            break

    # Tags
    if "CRITICAL" in tag_names:
        score += 25
    if "payment" in auto_tags or "security" in auto_tags:
        score += 15

    # Urgency (time decay with peak at 1-7d overdue)
    if is_today:
        score += 15
    if overdue_days > 0:
        if overdue_days <= 3:
            score += 20
        elif overdue_days <= 7:
            score += 15
        elif overdue_days <= 14:
            score += 10
        elif overdue_days <= 30:
            score += 5
        else:
            score += 2  # stale != urgent

    # Type boost
    if action_type == "reach-out":
        score += 5  # fast to do
    if action_type == "decide":
        score += 8  # blocking progress
    if action_type in ("deals", "xov"):
        score += 5

    score = min(score, 100)

    # --- Group key ---
    group_key = None
    if "payment" in auto_tags:
        group_key = "billing"

    # Duplicate title detection (only set if group_key not already set)
    if group_key is None:
        normalized = _STRIP_PREFIXES_RE.sub("", title).strip().lower()[:40]
        task["_norm_title"] = normalized  # temp field for _detect_groups

    task["action_type"] = action_type
    task["domain"] = domain
    task["person"] = person
    task["priority_score"] = score
    task["auto_tags"] = auto_tags
    task["group_key"] = group_key


def _detect_groups(tasks: list) -> dict:
    """Build virtual group definitions from tasks with group_keys.

    Also detects duplicate titles and assigns group_key = "dup:{normalized}" to them.
    """
    # Phase 1: detect duplicates by normalized title
    norm_buckets = defaultdict(list)
    for t in tasks:
        norm = t.pop("_norm_title", None)
        if norm is not None and t.get("group_key") is None:
            norm_buckets[norm].append(t)

    for norm, bucket in norm_buckets.items():
        if len(bucket) >= 2:
            dup_key = f"dup:{norm}"
            for t in bucket:
                t["group_key"] = dup_key

    # Phase 2: collect all group_keys
    key_tasks = defaultdict(list)
    for t in tasks:
        gk = t.get("group_key")
        if gk:
            key_tasks[gk].append(t)

    groups = {}
    for key, gtasks in key_tasks.items():
        if len(gtasks) < 2:
            # Only 1 task in group, remove group_key
            for t in gtasks:
                t["group_key"] = None
            continue

        if key == "billing":
            # Extract service names from titles
            services = []
            for t in gtasks:
                t_title = t.get("title", "")
                for svc in ["ClickHouse", "Azure", "Google One", "Google Workspace", "Anthropic", "Mercury", "Porkbun"]:
                    if svc.lower() in t_title.lower() and svc not in services:
                        services.append(svc)
                        break
                else:
                    short = t_title[:30]
                    if short not in services:
                        services.append(short)

            groups[key] = {
                "key": key,
                "title": f"Fix billing ({len(gtasks)} services)",
                "summary": ", ".join(services[:6]) + (f" +{len(services)-6} more" if len(services) > 6 else ""),
                "count": len(gtasks),
                "task_ids": [t["id"] for t in gtasks],
            }
        elif key.startswith("dup:"):
            groups[key] = {
                "key": key,
                "title": gtasks[0].get("title", ""),
                "summary": f"{len(gtasks)} duplicate tasks from different sources",
                "count": len(gtasks),
                "task_ids": [t["id"] for t in gtasks],
            }
        else:
            groups[key] = {
                "key": key,
                "title": gtasks[0].get("title", key),
                "summary": f"{len(gtasks)} related tasks",
                "count": len(gtasks),
                "task_ids": [t["id"] for t in gtasks],
            }

    return groups


def collect_tasks_data() -> Dict:
    """Collect tasks from Google Tasks + GitHub. Cached for 15s."""
    now = time.time()
    if _tasks_cache["data"] and (now - _tasks_cache["ts"]) < _TASKS_CACHE_TTL:
        return _tasks_cache["data"]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_dt = datetime.now(timezone.utc)

    # Fetch in parallel - GitHub projects come from config.personal.github_projects
    gh_projects = _cfg.github_projects()
    primary = gh_projects[0] if gh_projects else {"owner": "", "project": 1, "default_repo": ""}
    secondary = gh_projects[1] if len(gh_projects) > 1 else None

    with ThreadPoolExecutor(max_workers=3) as pool:
        gtasks_future = pool.submit(_fetch_google_tasks)
        gh_future = pool.submit(_fetch_github_items, primary["owner"], primary["project"]) if primary["owner"] else None
        secondary_gh_future = pool.submit(_fetch_github_items, secondary["owner"], secondary["project"]) if secondary else None

    gtasks_raw = gtasks_future.result()
    gh_raw = gh_future.result() if gh_future else []
    secondary_gh_raw = secondary_gh_future.result() if secondary_gh_future else []

    primary_section = primary.get("section", "primary-gh")
    primary_tag = primary.get("tag_name", "GH")
    primary_color = primary.get("tag_color", "blue")
    secondary_section = (secondary or {}).get("section", "secondary-gh")
    secondary_tag = (secondary or {}).get("tag_name", "GH")
    secondary_color = (secondary or {}).get("tag_color", "gray")

    tasks = []
    seen_titles = set()  # dedup across sources

    # Process Google Tasks
    for item in gtasks_raw:
        title = item.get("title", "").strip()
        if not title:
            continue
        status = item.get("status", "")
        if status == "completed":
            continue

        task_id = item.get("id", "")
        list_id = item.get("_list_id", "")
        list_name = item.get("_list_name", "main")
        due = item.get("due")
        notes = item.get("notes", "")

        # Klava queue tasks: parse frontmatter for status/priority
        if list_name == "klava":
            klava_meta = _parse_klava_frontmatter(notes)
            klava_status = klava_meta.get("status", "pending")
            klava_priority = klava_meta.get("priority", "medium")

            priority_colors = {"high": "red", "medium": "yellow", "low": "gray"}
            status_labels = {"pending": "PENDING", "running": "RUNNING", "done": "DONE", "failed": "FAILED"}

            tags = [
                {"name": status_labels.get(klava_status, klava_status.upper()), "color": "blue" if klava_status == "running" else "gray"},
                {"name": klava_priority.upper(), "color": priority_colors.get(klava_priority, "gray")},
            ]
            if klava_meta.get("source"):
                tags.append({"name": klava_meta["source"], "color": "gray"})

            # Strip frontmatter from notes display
            display_notes = klava_meta.get("_body", "")

            tasks.append({
                "id": f"gtask_{list_id}_{task_id}",
                "title": title,
                "raw_title": title,
                "source": "gtasks",
                "source_label": "KL",
                "list_name": "klava",
                "due": due[:10] if due else None,
                "days_info": "",
                "overdue_days": 0,
                "notes": display_notes[:500] if display_notes else "",
                "section": "klava",
                "tags": tags,
                "overdue": False,
                "is_today": False,
                "bold": klava_status == "running" or klava_priority == "high",
                "meta": {"list_id": list_id, "task_id": task_id},
                "klava": {
                    "status": klava_status,
                    "priority": klava_priority,
                    "session_id": klava_meta.get("session_id"),
                    "started_at": klava_meta.get("started_at"),
                    "source": klava_meta.get("source", "manual"),
                    "type": klava_meta.get("type", "task"),
                    "shape": klava_meta.get("shape"),
                    "dispatch": klava_meta.get("dispatch"),
                    "criticality": int(klava_meta["criticality"]) if klava_meta.get("criticality", "").isdigit() else None,
                    "mode_tags": [t.strip() for t in klava_meta.get("mode_tags", "").split(",") if t.strip()] or None,
                    "proposal_status": klava_meta.get("proposal_status"),
                },
            })
            continue

        cat = _categorize_task(title, due, today, "gtasks")
        seen_titles.add(title.lower()[:40])

        # Days info
        days_info = ""
        overdue_days = 0
        if due:
            try:
                due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                diff = (due_dt - today_dt).days
                if diff < 0:
                    overdue_days = abs(diff)
                    days_info = f"{overdue_days}d overdue"
                elif diff == 0:
                    days_info = "today"
                elif diff <= 7:
                    days_info = f"in {diff}d"
            except Exception:
                pass

        tasks.append({
            "id": f"gtask_{list_id}_{task_id}",
            "title": cat["clean_title"],
            "raw_title": title,
            "source": "gtasks",
            "source_label": "GT",
            "list_name": list_name,
            "due": due[:10] if due else None,
            "days_info": days_info,
            "overdue_days": overdue_days,
            "notes": (notes if any(tag in title for tag in ('[REPLY]', '[PREP]')) else notes[:500]) if notes else "",
            "section": cat["section"],
            "tags": cat["tags"],
            "overdue": cat["overdue"],
            "is_today": cat["is_today"],
            "bold": cat["bold"],
            "meta": {"list_id": list_id, "task_id": task_id},
        })

    # Process GitHub items
    for item in gh_raw:
        content = item.get("content", {})
        title = content.get("title", item.get("title", "")).strip()
        if not title:
            continue

        # Dedup: skip if similar title in Google Tasks
        if title.lower()[:40] in seen_titles:
            continue

        number = content.get("number", item.get("number", ""))
        repo = content.get("repository", primary.get("default_repo", ""))
        assignees = content.get("assignees", [])
        labels = content.get("labels", [])
        state = content.get("state", item.get("status", ""))

        if isinstance(state, str) and state.upper() in ("CLOSED", "MERGED", "DONE"):
            continue

        assignee_names = []
        if isinstance(assignees, list):
            for a in assignees:
                if isinstance(a, dict):
                    assignee_names.append(a.get("login", ""))
                elif isinstance(a, str):
                    assignee_names.append(a)

        label_names = []
        if isinstance(labels, list):
            for l in labels:
                if isinstance(l, dict):
                    label_names.append(l.get("name", ""))
                elif isinstance(l, str):
                    label_names.append(l)

        _categorize_task(title, None, today, "github")

        tasks.append({
            "id": f"gh_{number}@{repo}",
            "title": title,
            "raw_title": title,
            "source": "github",
            "source_label": "GH",
            "list_name": str(repo),
            "due": None,
            "days_info": "",
            "notes": ", ".join(assignee_names) if assignee_names else "",
            "section": primary_section,
            "tags": [{"name": primary_tag, "color": primary_color}] + [{"name": ln[:10], "color": "gray"} for ln in label_names[:2]],
            "overdue": False,
            "is_today": False,
            "bold": False,
            "meta": {"number": number, "repo": repo},
        })

    # Process secondary GitHub project items
    for item in secondary_gh_raw:
        content = item.get("content", {})
        title = content.get("title", item.get("title", "")).strip()
        if not title:
            continue

        # Dedup: skip if similar title in Google Tasks
        if title.lower()[:40] in seen_titles:
            continue

        number = content.get("number", item.get("number", ""))
        repo = content.get("repository", (secondary or {}).get("default_repo", ""))
        assignees = content.get("assignees", [])
        if not assignees:
            assignees = item.get("assignees", [])
        labels = content.get("labels", [])
        state = content.get("state", item.get("status", ""))

        if isinstance(state, str) and state.upper() in ("CLOSED", "MERGED", "DONE"):
            continue

        assignee_names = []
        if isinstance(assignees, list):
            for a in assignees:
                if isinstance(a, dict):
                    assignee_names.append(a.get("login", ""))
                elif isinstance(a, str):
                    assignee_names.append(a)

        label_names = []
        if isinstance(labels, list):
            for lb in labels:
                if isinstance(lb, dict):
                    label_names.append(lb.get("name", ""))
                elif isinstance(lb, str):
                    label_names.append(lb)

        status_tag = item.get("status", "")
        extra_tags = [{"name": status_tag[:12], "color": "gray"}] if status_tag and status_tag.upper() not in ("TODO",) else []

        tasks.append({
            "id": f"gh_{number}@{repo}",
            "title": title,
            "raw_title": title,
            "source": "github",
            "source_label": "GH",
            "list_name": str(repo).split("/", 1)[-1] if "/" in str(repo) else str(repo),
            "due": None,
            "days_info": "",
            "notes": ", ".join(assignee_names) if assignee_names else "",
            "section": secondary_section,
            "tags": [{"name": secondary_tag, "color": secondary_color}] + extra_tags + [{"name": ln[:10], "color": "gray"} for ln in label_names[:2]],
            "overdue": False,
            "is_today": False,
            "bold": False,
            "meta": {"number": number, "repo": repo},
        })

    # Smart classification
    for t in tasks:
        _classify_task_smart(t)

    # Detect groups (duplicates, billing clusters)
    groups = _detect_groups(tasks)

    # Sort: overdue first, then today, then by section priority
    section_order = {"overdue": 0, "today": 1, "deals": 2, "replies": 3, "primary-gh": 4, "secondary-gh": 5, "personal": 6}
    tasks.sort(key=lambda t: (section_order.get(t["section"], 9), not t["overdue"], t.get("due") or "9999"))

    # Build sections (for Source view)
    sections = {}
    for t in tasks:
        sec = t["section"]
        if sec not in sections:
            sections[sec] = {"name": sec, "label": sec.replace("-", " ").title(), "tasks": []}
        sections[sec]["tasks"].append(t)

    # KPIs (exclude team sections from total/overdue - those are team tasks, not personal)
    _excluded_kpi_sections = _cfg.kpi_excluded_sections() or {"primary-gh", "secondary-gh"}
    personal_tasks = [t for t in tasks if t["section"] not in _excluded_kpi_sections]
    overdue_count = sum(1 for t in personal_tasks if t["overdue"])
    today_count = sum(1 for t in tasks if t["is_today"])
    deal_count = sum(1 for t in tasks if t["section"] == "deals")

    result = {
        "tasks": tasks,
        "kpis": {
            "total": len(personal_tasks),
            "overdue": overdue_count,
            "today": today_count,
            "deals": deal_count,
        },
        "sections": sections,
        "section_order": _cfg.task_section_display_order() or ["klava", "overdue", "today", "deals", "replies", "primary-gh", "secondary-gh", "personal"],
        "groups": groups,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _tasks_cache["data"] = result
    _tasks_cache["ts"] = time.time()
    return result


def update_task(task_id: str, action: str, note: str = "", days: int = 7) -> Dict:
    """Update a task (done/postpone/skip/cancel). Routes by ID prefix.

    `days` applies to `postpone` — how far forward to push the due date.
    """
    global _tasks_cache

    if action not in ("done", "postpone", "skip", "cancel"):
        return {"success": False, "message": f"Unknown action: {action}"}

    if action == "skip":
        return {"success": True, "message": "Skipped"}

    is_cancel = action == "cancel"
    if is_cancel:
        action = "done"

    try:
        if task_id.startswith("gtask_"):
            # Parse: gtask_{list_id}_{task_id}
            parts = task_id.split("_", 2)
            if len(parts) < 3:
                return {"success": False, "message": "Invalid gtask ID format"}
            list_id = parts[1]
            g_task_id = parts[2]

            if is_cancel:
                raw = _gog_run(["tasks", "get", list_id, g_task_id])
                if raw:
                    try:
                        task_data = json.loads(raw)
                        current_title = task_data.get("title", "")
                        if not current_title.startswith("[CANCELLED]"):
                            _gog_run(["tasks", "update", list_id, g_task_id,
                                      "--title", f"[CANCELLED] {current_title}", "-y"])
                    except (json.JSONDecodeError, TypeError):
                        pass

            if action == "done":
                result = _gog_run(["tasks", "done", list_id, g_task_id])
                if result is None:
                    return {"success": False, "message": "gog tasks done failed"}
            elif action == "postpone":
                new_due = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
                args = ["tasks", "update", list_id, g_task_id, "--due", new_due, "-y"]
                if note:
                    args += ["--notes", note]
                result = _gog_run(args)
                if result is None:
                    return {"success": False, "message": "gog tasks update failed"}

        elif task_id.startswith("gh_"):
            # Parse: gh_{number}@{owner/repo} or legacy gh_{number}
            gh_part = task_id[3:]
            if "@" in gh_part:
                number, repo = gh_part.split("@", 1)
            else:
                gh_projects = _cfg.github_projects()
                number = gh_part
                repo = gh_projects[0]["default_repo"] if gh_projects else ""
            if action == "done":
                subprocess.run(
                    ["gh", "issue", "close", number, "--repo", repo],
                    capture_output=True, text=True, timeout=15,
                )
            elif action == "postpone":
                # Add a comment for postponed GH issues
                if note:
                    subprocess.run(
                        ["gh", "issue", "comment", number, "--repo", repo, "--body", f"Postponed: {note}"],
                        capture_output=True, text=True, timeout=15,
                    )
        else:
            return {"success": False, "message": f"Unknown task ID prefix: {task_id}"}

        # Invalidate cache
        _tasks_cache = {"data": None, "ts": 0}
        return {"success": True, "message": f"Task {action}: {task_id}"}

    except Exception as e:
        return {"success": False, "message": str(e)}


# ================================================================
# HEARTBEAT HISTORY
# ================================================================

_hb_cache: Dict = {"data": None, "ts": 0}
_HB_CACHE_TTL = 30

def _load_proactive_jobs() -> set:
    """Load proactive job IDs from jobs.json (mode: main or isolated)."""
    try:
        jobs_file = _cfg.cron_jobs_file()
        jobs = json.loads(jobs_file.read_text()).get("jobs", [])
        return {j["id"] for j in jobs if j.get("execution", {}).get("mode") in ("main", "isolated")}
    except Exception:
        return _cfg.default_proactive_jobs() or {"heartbeat", "mentor", "reflection"}

PROACTIVE_JOBS = _load_proactive_jobs()


def collect_heartbeat_data() -> Dict:
    """Collect heartbeat/mentor/friend run history for observability."""
    now = time.time()
    if _hb_cache["data"] and now - _hb_cache["ts"] < _HB_CACHE_TTL:
        return _hb_cache["data"]

    runs_file = _cfg.cron_runs_log()
    state_file = _cfg.heartbeat_state_file()

    # Read all runs from last 7 days for proactive jobs
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    runs = []
    if runs_file.exists():
        for line in runs_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("job_id") not in PROACTIVE_JOBS:
                continue
            if r.get("status") not in ("completed", "failed"):
                continue
            ts = r.get("timestamp", "")
            if ts < cutoff.isoformat():
                continue
            runs.append(r)

    # Parse each run
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parsed_runs = []
    intake_re = re.compile(r"INTAKE:\s*(.+)")
    for r in runs:
        output = r.get("output") or ""
        is_ok = bool(re.search(r"HEARTBEAT[_\s-]*OK", output, re.IGNORECASE))
        is_failed = r.get("status") == "failed"

        # Parse intake from structured field (new format) or output line (old format)
        intake_data = r.get("intake")  # structured: {stats, total_new, details, consumed}
        intake_line = ""
        intake_details_obj = None
        if intake_data and isinstance(intake_data, dict):
            # New structured format from cron-scheduler
            details = intake_data.get("details") or {}
            intake_details_obj = details
            # Build rich summary with chat names
            parts = []
            for src, groups in details.items():
                group_parts = [f"{g}:{n}" for g, n in groups.items()]
                parts.append(f"{src}({', '.join(group_parts)})")
            if parts:
                total = intake_data.get("total_new", 0)
                intake_line = f"{' '.join(parts)} - {total} msgs"
            else:
                stats = intake_data.get("stats", {})
                total = intake_data.get("total_new", 0)
                src_parts = [f"{src}={n}" for src, n in stats.items()]
                intake_line = f"{', '.join(src_parts)} ({total} total new)" if src_parts else f"({total} new records)"
        else:
            # Old format: parse INTAKE: line from output
            intake_match = intake_re.search(output)
            if intake_match:
                intake_line = intake_match.group(1).strip()

        # Parse actions from output (skip INTAKE and HEARTBEAT_OK lines)
        actions = []
        if not is_failed and output.strip():
            for line in output.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("INTAKE:") or re.match(r"HEARTBEAT[_\s-]*OK", line, re.IGNORECASE):
                    continue
                actions.append(line)

        # Extract deltas (new structured format or parse from output)
        deltas = r.get("deltas")
        if deltas is None and output and '---DELTAS---' in output:
            try:
                deltas = json.loads(output.split('---DELTAS---', 1)[1].strip())
            except (json.JSONDecodeError, IndexError):
                deltas = None

        # Strip ---DELTAS--- block from output for display
        display_output = output
        if '---DELTAS---' in display_output:
            display_output = display_output.split('---DELTAS---', 1)[0].rstrip()

        parsed_runs.append({
            "timestamp": r.get("timestamp", ""),
            "job_id": r.get("job_id", ""),
            "status": "failed" if is_failed else ("idle" if is_ok and not actions else "acted" if actions else "idle"),
            "intake": intake_line,
            "intake_details": intake_data.get("details") if isinstance(intake_data, dict) else None,
            "duration": r.get("duration_seconds", 0),
            "error": r.get("error"),
            "output": display_output[:2000],
            "actions": actions,
            "action_count": len(actions),
            "deltas": deltas,
            "todos": r.get("todos", []),
        })

    # Sort by timestamp desc
    parsed_runs.sort(key=lambda x: x["timestamp"], reverse=True)

    # Compute KPIs
    today_runs = [r for r in parsed_runs if r["timestamp"][:10] == today]
    acted_today = [r for r in today_runs if r["status"] == "acted"]
    failed_today = [r for r in today_runs if r["status"] == "failed"]

    # Per-job breakdown
    job_stats = {}
    for jid in PROACTIVE_JOBS:
        job_runs = [r for r in parsed_runs if r["job_id"] == jid]
        today_job = [r for r in job_runs if r["timestamp"][:10] == today]
        job_stats[jid] = {
            "total_7d": len(job_runs),
            "today": len(today_job),
            "acted_today": sum(1 for r in today_job if r["status"] == "acted"),
            "failed_today": sum(1 for r in today_job if r["status"] == "failed"),
            "avg_duration": round(sum(r["duration"] for r in job_runs) / max(len(job_runs), 1)),
            "last_run": job_runs[0]["timestamp"] if job_runs else None,
            "last_status": job_runs[0]["status"] if job_runs else None,
        }

    # Read heartbeat state
    reported_items = {}
    if state_file.exists():
        try:
            st = json.loads(state_file.read_text())
            reported_items = st.get("reported", {})
        except (json.JSONDecodeError, OSError):
            pass

    # Job metadata for frontend (name + order from jobs.json)
    job_meta = {}
    try:
        jobs_file = _cfg.cron_jobs_file()
        all_jobs = json.loads(jobs_file.read_text()).get("jobs", [])
        for idx, j in enumerate(all_jobs):
            if j["id"] in PROACTIVE_JOBS:
                job_meta[j["id"]] = {"label": j.get("name", j["id"]), "order": idx}
    except Exception:
        pass

    # Consumer source queues: checkpoint positions vs total records
    consumer_sources = {}
    vadimgest_dir = VADIMGEST_STATE_DIR
    checkpoints_dir = vadimgest_dir / "checkpoints"
    state_totals = {}
    try:
        state_totals = json.loads((vadimgest_dir / "state.json").read_text())
    except Exception:
        pass
    if checkpoints_dir.exists():
        for cp_file in checkpoints_dir.glob("*.json"):
            consumer = cp_file.stem
            try:
                cp = json.loads(cp_file.read_text())
                positions = cp.get("positions", {})
                updated_at = cp.get("updated_at", "")
                sources = {}
                for src, pos in positions.items():
                    line = pos.get("line", 0) if isinstance(pos, dict) else 0
                    total = state_totals.get(src, {}).get("total_records", 0) if isinstance(state_totals.get(src), dict) else 0
                    new_count = max(0, total - line)
                    sources[src] = {"position": line, "total": total, "new": new_count}
                consumer_sources[consumer] = {
                    "sources": sources,
                    "updated_at": updated_at,
                    "total_new": sum(s["new"] for s in sources.values()),
                }
            except Exception:
                continue

    # Aggregate today's deltas across all runs (dynamic categories)
    # Category aliases: map special delta types to canonical category names
    _DELTA_CATEGORY_ALIAS = {"observation": "obsidian", "state_tracked": "state"}
    today_deltas: Dict = {"skipped": 0}
    for r in today_runs:
        if not r.get("deltas"):
            continue
        for d in r["deltas"]:
            dtype = d.get("type", "")
            if dtype == "skipped":
                today_deltas["skipped"] += d.get("count", 1)
                continue
            # Derive category from type prefix or alias
            cat = _DELTA_CATEGORY_ALIAS.get(dtype, dtype.split("_")[0] if "_" in dtype else dtype)
            if cat not in today_deltas:
                today_deltas[cat] = []
            # Extract meaningful label from delta
            label = d.get("title") or d.get("path") or d.get("subject") or d.get("deal") or d.get("target") or d.get("key") or ""
            if "gtask" in dtype:
                action = dtype.split("_")[-1] if "_" in dtype else ""
                label = f"{action}: {label}" if action else label
            today_deltas[cat].append(label)

    result = {
        "runs": parsed_runs[:100],  # last 100 runs
        "kpis": {
            "runs_today": len(today_runs),
            "acted_today": len(acted_today),
            "failed_today": len(failed_today),
            "idle_today": len(today_runs) - len(acted_today) - len(failed_today),
            "total_actions_today": sum(r["action_count"] for r in acted_today),
            "tracked_items": len(reported_items),
        },
        "job_stats": job_stats,
        "job_meta": job_meta,
        "reported_items": {k: v for k, v in sorted(reported_items.items(), key=lambda x: x[1], reverse=True)[:20]},
        "consumer_sources": consumer_sources,
        "today_deltas": today_deltas,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _hb_cache["data"] = result
    _hb_cache["ts"] = now
    return result


# ── Deals data collector ──────────────────────────────────────────────

_deals_cache: Dict = {"data": None, "ts": 0}
_DEALS_CACHE_TTL = 30  # seconds

# Stage number -> canonical name mapping
_STAGE_NAMES = {
    1: "prospecting", 2: "outreach", 3: "meeting", 4: "qualified",
    5: "proposal", 6: "negotiation", 7: "pilot", 8: "legal",
    9: "contract", 10: "procurement", 11: "signed", 12: "onboarding",
    13: "delivery", 14: "renewal", 15: "expansion", 16: "stalled", 17: "lost",
}

_WEIGHT_BRACKETS = {
    (1, 3): 0.10, (4, 6): 0.25, (7, 9): 0.50,
    (10, 12): 0.75, (13, 15): 0.90,
}

def _priority_deals() -> List[str]:
    """Lowercase keys from config.personal.priority_deals."""
    return [k.lower() for k in _cfg.priority_deals().keys()]


_PRIORITY_DEALS = _priority_deals()


def _parse_deal_frontmatter(filepath: Path) -> Optional[Dict]:
    """Parse YAML frontmatter from a deal markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None

    fm = {}
    raw = match.group(1)
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("#") or not line or line.startswith("- "):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            if val in ("null", "~", ""):
                val = None
            fm[key] = val
    return fm


def _parse_deal_stage(stage_str: str) -> tuple:
    """Parse stage string like '13-delivery' into (num, name)."""
    if not stage_str:
        return (0, "unknown")
    m = re.match(r"(\d+)-?(.*)", str(stage_str))
    if m:
        num = int(m.group(1))
        name = m.group(2).strip() if m.group(2) else _STAGE_NAMES.get(num, "unknown")
        return (num, name)
    return (0, str(stage_str))


def _parse_deal_date(date_str: Optional[str]):
    """Parse date string to date object."""
    if not date_str:
        return None
    try:
        from datetime import date as _date
        return datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_deal_value(val_str: Optional[str]) -> Optional[float]:
    """Parse numeric value."""
    if val_str is None:
        return None
    try:
        return float(str(val_str).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _clean_lead(lead_str: Optional[str]) -> str:
    """Clean lead name from wikilink format [[Name]]."""
    if not lead_str:
        return "Unknown"
    return re.sub(r"\[{1,2}|\]{1,2}", "", str(lead_str)).strip()


def _get_deal_weight(stage_num: int) -> float:
    """Get pipeline weight for a stage number."""
    for (lo, hi), weight in _WEIGHT_BRACKETS.items():
        if lo <= stage_num <= hi:
            return weight
    return 0.0


def collect_deals_data() -> Dict:
    """Collect deals pipeline data from Obsidian vault. Cached for 30s."""
    now = time.time()
    if _deals_cache["data"] and (now - _deals_cache["ts"]) < _DEALS_CACHE_TTL:
        return _deals_cache["data"]

    deals_dir = _cfg.deals_dir()
    today = datetime.now().date()
    deals = []

    if deals_dir.exists():
        for filepath in sorted(deals_dir.glob("*.md")):
            fm = _parse_deal_frontmatter(filepath)
            if not fm or "stage" not in fm:
                continue

            stage_num, stage_name = _parse_deal_stage(fm.get("stage"))
            value = _parse_deal_value(fm.get("value"))
            mrr = _parse_deal_value(fm.get("mrr"))
            last_contact_date = _parse_deal_date(fm.get("last_contact"))
            follow_up_date = _parse_deal_date(fm.get("follow_up"))

            days_in_stage = None
            if last_contact_date:
                days_in_stage = (today - last_contact_date).days

            days_until_follow_up = None
            overdue = False
            if follow_up_date:
                days_until_follow_up = (follow_up_date - today).days
                overdue = days_until_follow_up < 0

            deal_name = filepath.stem
            is_active = 1 <= stage_num <= 15

            deals.append({
                "name": deal_name,
                "stage": f"{stage_num}-{stage_name}",
                "stage_num": stage_num,
                "value": value,
                "mrr": mrr,
                "deal_size": fm.get("deal_size"),
                "deal_type": fm.get("deal_type"),
                "owner": fm.get("owner"),
                "product": fm.get("product"),
                "last_contact": str(last_contact_date) if last_contact_date else None,
                "follow_up": str(follow_up_date) if follow_up_date else None,
                "days_in_stage": days_in_stage,
                "days_until_follow_up": days_until_follow_up,
                "overdue": overdue,
                "is_priority": any(p in deal_name.lower() for p in _PRIORITY_DEALS),
                "is_active": is_active,
                "next_action": fm.get("next_action"),
                "decision_maker": _clean_lead(fm.get("decision_maker")),
                "lead": fm.get("lead"),
                "lead_clean": _clean_lead(fm.get("lead")),
                "referrer": fm.get("referrer"),
                "referrer_clean": _clean_lead(fm.get("referrer")),
                "telegram_chat": fm.get("telegram_chat"),
                "payment_type": fm.get("payment_type"),
                "file_path": f"{_cfg.load().get('paths', {}).get('deals_subpath', 'Deals')}/{deal_name}",
            })

    # Compute metrics
    active_deals = [d for d in deals if d["is_active"]]
    overdue_deals = [d for d in active_deals if d["overdue"]]
    total_pipeline = sum(d["value"] or 0 for d in active_deals)
    weighted_pipeline = sum(
        (d["value"] or 0) * _get_deal_weight(d["stage_num"]) for d in active_deals
    )

    # Pipeline stages
    stage_map: Dict[int, Dict] = {}
    for d in active_deals:
        sn = d["stage_num"]
        if sn not in stage_map:
            stage_map[sn] = {
                "stage_num": sn,
                "stage": d["stage"],
                "count": 0,
                "total_value": 0,
                "deals": [],
            }
        stage_map[sn]["count"] += 1
        stage_map[sn]["total_value"] += d["value"] or 0
        stage_map[sn]["deals"].append(d["name"])
    pipeline_stages = sorted(stage_map.values(), key=lambda s: s["stage_num"])

    result = {
        "metrics": {
            "total_pipeline": total_pipeline,
            "weighted_pipeline": weighted_pipeline,
            "active_count": len(active_deals),
            "overdue_count": len(overdue_deals),
        },
        "deals": deals,
        "pipeline_stages": pipeline_stages,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _deals_cache["data"] = result
    _deals_cache["ts"] = now
    return result


# ── People data collector ─────────────────────────────────────────────

_people_cache: Dict = {"data": None, "ts": 0}
_PEOPLE_CACHE_TTL = 30  # seconds


def _parse_people_frontmatter(filepath: Path) -> Optional[Dict]:
    """Parse YAML frontmatter from a people markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None

    fm = {}
    raw = match.group(1)
    in_list = False
    list_key = None
    list_values = []

    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue

        # Handle YAML list items
        if stripped.startswith("- ") and in_list:
            list_values.append(stripped[2:].strip())
            continue
        elif in_list:
            # End of list
            fm[list_key] = list_values
            in_list = False
            list_values = []

        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "" or val is None:
                # Could be start of a list
                in_list = True
                list_key = key
                list_values = []
                continue
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            # Handle inline list like [tag1, tag2]
            if val.startswith("[") and val.endswith("]"):
                items = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                fm[key] = items
                continue
            if val in ("null", "~", ""):
                val = None
            fm[key] = val

    if in_list:
        fm[list_key] = list_values

    return fm


def collect_people_data() -> Dict:
    """Collect people/contacts data from Obsidian vault. Cached for 30s."""
    now = time.time()
    if _people_cache["data"] and (now - _people_cache["ts"]) < _PEOPLE_CACHE_TTL:
        return _people_cache["data"]

    people_dir = _cfg.people_dir()
    today = datetime.now().date()
    people = []
    companies = set()
    recent_7d = 0
    stale_30d = 0

    if people_dir.exists():
        for filepath in sorted(people_dir.glob("*.md")):
            fm = _parse_people_frontmatter(filepath)
            if not fm:
                continue

            name = filepath.stem
            company = fm.get("company")
            if isinstance(company, list):
                company = ", ".join(str(c) for c in company) if company else None
            if company and company not in ("null", "~"):
                companies.add(company)
            else:
                company = None

            # Parse tags
            tags = fm.get("tags")
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            elif not isinstance(tags, list):
                tags = []

            # Parse last_contact
            last_contact = None
            days_since = None
            last_contact_str = fm.get("last_contact")
            if last_contact_str and last_contact_str not in ("null", "~"):
                try:
                    last_contact = datetime.strptime(str(last_contact_str).strip(), "%Y-%m-%d").date()
                    days_since = (today - last_contact).days
                    if days_since <= 7:
                        recent_7d += 1
                    if days_since > 30:
                        stale_30d += 1
                except ValueError:
                    pass

            # No last_contact = stale
            if last_contact is None:
                stale_30d += 1

            people.append({
                "name": name,
                "company": company,
                "role": fm.get("role") if fm.get("role") not in (None, "null", "~") else None,
                "handle": fm.get("handle") if fm.get("handle") not in (None, "null", "~") else None,
                "email": fm.get("email") if fm.get("email") not in (None, "null", "~") else None,
                "location": fm.get("location") if fm.get("location") not in (None, "null", "~") else None,
                "met": fm.get("met") if fm.get("met") not in (None, "null", "~") else None,
                "tags": tags,
                "last_contact": str(last_contact) if last_contact else None,
                "days_since_contact": days_since,
            })

    result = {
        "metrics": {
            "total_contacts": len(people),
            "companies": len(companies),
            "recent_7d": recent_7d,
            "stale_30d": stale_30d,
        },
        "people": people,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _people_cache["data"] = result
    _people_cache["ts"] = now
    return result


# ── Follow-ups data collector ────────────────────────────────────────

_followups_cache: Dict = {"data": None, "ts": 0}
_FOLLOWUPS_CACHE_TTL = 30  # seconds


def collect_followups_data() -> Dict:
    """Collect follow-up data from deal notes. Cached for 30s."""
    now = time.time()
    if _followups_cache["data"] and (now - _followups_cache["ts"]) < _FOLLOWUPS_CACHE_TTL:
        return _followups_cache["data"]

    deals_dir = _cfg.deals_dir()
    today = datetime.now().date()
    followups = []

    if deals_dir.exists():
        for filepath in sorted(deals_dir.glob("*.md")):
            fm = _parse_deal_frontmatter(filepath)
            if not fm:
                continue

            follow_up_date = _parse_deal_date(fm.get("follow_up"))
            if not follow_up_date:
                continue

            days_until = (follow_up_date - today).days
            value = _parse_deal_value(fm.get("value"))
            stage_num, stage_name = _parse_deal_stage(fm.get("stage"))
            is_active = 1 <= stage_num <= 15

            if not is_active:
                continue

            # Only show overdue or upcoming 7 days
            if days_until > 7:
                continue

            followups.append({
                "deal": filepath.stem,
                "follow_up": str(follow_up_date),
                "days_until": days_until,
                "overdue": days_until < 0,
                "value": value,
                "stage": f"{stage_num}-{stage_name}",
                "stage_num": stage_num,
                "deal_size": fm.get("deal_size"),
                "owner": fm.get("owner"),
                "next_action": fm.get("next_action"),
                "decision_maker": _clean_lead(fm.get("decision_maker")),
                "is_priority": any(p in filepath.stem.lower() for p in _PRIORITY_DEALS),
            })

    # Sort: overdue first (most overdue at top), then upcoming
    followups.sort(key=lambda f: f["days_until"])

    overdue = [f for f in followups if f["overdue"]]
    upcoming = [f for f in followups if not f["overdue"]]
    total_overdue_value = sum(f["value"] or 0 for f in overdue)
    total_upcoming_value = sum(f["value"] or 0 for f in upcoming)

    result = {
        "metrics": {
            "overdue_count": len(overdue),
            "upcoming_count": len(upcoming),
            "total_overdue_value": total_overdue_value,
            "total_upcoming_value": total_upcoming_value,
        },
        "overdue": overdue,
        "upcoming": upcoming,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _followups_cache["data"] = result
    _followups_cache["ts"] = now
    return result


# ── Calendar data collector ──────────────────────────────────────────

_calendar_cache: Dict = {"data": None, "ts": 0}
_CALENDAR_CACHE_TTL = 30  # seconds


def collect_calendar_data() -> Dict:
    """Collect calendar events from vadimgest. Cached for 30s."""
    now = time.time()
    if _calendar_cache["data"] and (now - _calendar_cache["ts"]) < _CALENDAR_CACHE_TTL:
        return _calendar_cache["data"]

    calendar_file = VADIMGEST_DIR / "data" / "sources" / "calendar.jsonl"
    today = datetime.now().date()
    week_end = today + timedelta(days=7)
    events = []

    if not calendar_file.exists():
        result = {
            "status": "sync_pending",
            "message": "Calendar sync not yet configured. No calendar.jsonl found.",
            "events": [],
            "today_events": [],
            "week_events": [],
            "metrics": {
                "today_count": 0,
                "week_count": 0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        _calendar_cache["data"] = result
        _calendar_cache["ts"] = now
        return result

    try:
        with open(calendar_file) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                    events.append(evt)
                except Exception:
                    continue
    except Exception:
        pass

    # Parse events and categorize
    today_events = []
    week_events = []

    for evt in events:
        start_str = evt.get("start") or evt.get("start_time") or evt.get("date")
        if not start_str:
            continue

        try:
            if "T" in str(start_str):
                start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
                event_date = start_dt.date()
            else:
                event_date = datetime.strptime(str(start_str)[:10], "%Y-%m-%d").date()
                start_dt = datetime(event_date.year, event_date.month, event_date.day)
        except Exception:
            continue

        parsed_event = {
            "title": evt.get("title") or evt.get("summary") or evt.get("name") or "Untitled",
            "start": str(start_str),
            "end": evt.get("end") or evt.get("end_time"),
            "date": str(event_date),
            "location": evt.get("location"),
            "description": (evt.get("description") or "")[:200],
            "is_today": event_date == today,
            "is_this_week": today <= event_date <= week_end,
        }

        if event_date == today:
            today_events.append(parsed_event)
        if today <= event_date <= week_end:
            week_events.append(parsed_event)

    # Sort by start time
    today_events.sort(key=lambda e: e["start"])
    week_events.sort(key=lambda e: e["start"])

    result = {
        "status": "ok" if events else "empty",
        "events": events[-50:],  # last 50 raw events
        "today_events": today_events,
        "week_events": week_events,
        "metrics": {
            "today_count": len(today_events),
            "week_count": len(week_events),
            "total_events": len(events),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _calendar_cache["data"] = result
    _calendar_cache["ts"] = now
    return result


VIEWS_DIR = _cfg.views_dir()

_views_cache: Dict = {"data": None, "ts": 0}
_VIEWS_CACHE_TTL = 15  # seconds


def collect_views_data() -> Dict:
    """Collect HTML views from .claude/views/ directory. Cached for 15s."""
    now = time.time()
    if _views_cache["data"] and (now - _views_cache["ts"]) < _VIEWS_CACHE_TTL:
        return _views_cache["data"]

    views = []
    if VIEWS_DIR.exists():
        for filepath in sorted(VIEWS_DIR.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True):
            if filepath.name == "dashboard.html":
                continue
            try:
                stat = filepath.stat()
                # Extract title from <title> tag
                title = filepath.stem
                content = filepath.read_text(errors="ignore")[:2000]
                title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1)

                # Extract subtitle/date from .subtitle div
                subtitle = ""
                sub_match = re.search(r'class="subtitle"[^>]*>(.*?)</div>', content, re.IGNORECASE)
                if sub_match:
                    subtitle = re.sub(r"<[^>]+>", "", sub_match.group(1)).strip()

                # Count annotation marks (feedback module)
                annotation_count = content.count('class="annotation-mark')

                views.append({
                    "filename": filepath.name,
                    "title": title,
                    "subtitle": subtitle,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "modified_ago": _time_ago(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()),
                    "annotations": annotation_count,
                    "path": str(filepath),
                })
            except Exception:
                continue

    result = {
        "status": "ok" if views else "empty",
        "views": views,
        "metrics": {
            "total": len(views),
            "today": sum(1 for v in views if v["modified"][:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    _views_cache["data"] = result
    _views_cache["ts"] = now
    return result


FEED_LOG = _cfg.feed_log()


def collect_feed_data(limit: int = 100, topic: str = None) -> Dict:
    """Collect outgoing TG messages from feed log."""
    messages = []
    if FEED_LOG.exists():
        try:
            lines = FEED_LOG.read_text().strip().split("\n")
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if topic and entry.get("topic") != topic:
                    continue
                entry["ago"] = _time_ago(entry.get("timestamp", ""))
                messages.append(entry)
                if len(messages) >= limit:
                    break
        except Exception:
            pass

    for m in messages:
        t = m.get("topic")
        if not isinstance(t, str):
            m["topic"] = "General" if t is None else str(t)
    topics = sorted({m["topic"] for m in messages})
    return {
        "messages": messages,
        "topics": topics,
        "total": len(messages),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    # Test status collector
    status = collect_status()
    print(json.dumps(status, indent=2))
