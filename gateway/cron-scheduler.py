#!/usr/bin/env python3
"""CRON Scheduler daemon for Claude Code automation.

Features:
- APScheduler for robust job scheduling
- Catch-up logic for missed jobs
- State persistence across restarts
- File locking for single-instance
- Comprehensive execution logging
"""

import json
import os
import sys
import time
import threading
import fcntl
import logging
import html
import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import yaml
from lib.telegram_utils import send_telegram_message, get_telegram_config, edit_telegram_message
from lib.feed import send_feed
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from croniter import croniter

# Priority order for catch-up execution (lower = higher priority)
JOB_PRIORITY = {
    'mentor': 1,
    'heartbeat': 2,
    'friend': 3,
    'reflection': 4,
    # everything else defaults to 10
}

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))
from lib.claude_executor import ClaudeExecutor
from lib.announce_handler import init_announce_handler, check_and_announce_completed
from lib.subagent_state import (
    recover_crashed_subagents, init_subagent_state,
    get_active_subagents, get_subagent_output, update_progress_timestamp
)
from lib.subagent_status import parse_current_activity, format_progress_message, format_duration
from lib.main_session import init_main_session, get_main_session_id, save_main_session_id
from lib.session_registry import register_session
from lib import config as _cfg


class JobManager:
    """Manage scheduled jobs with catch-up logic."""

    def __init__(self, config_path: str):
        """Initialize job manager."""
        self.config_path = Path(config_path).expanduser()
        self.config = self._load_config()

        # Paths from config — fall back to repo-relative defaults when the
        # cron.* keys are absent so config.yaml.example stays minimal.
        _cfg.load(self.config_path, reload=True)
        self.jobs_file = _cfg.cron_jobs_file()
        self.state_file = _cfg.cron_state_file()
        self.runs_log = _cfg.cron_runs_log()

        # Ensure directories exist
        self.jobs_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.runs_log.parent.mkdir(parents=True, exist_ok=True)

        # Setup logging
        self.log_file = Path("/tmp/cron-scheduler.log")
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        # Initialize executor
        self.executor = ClaudeExecutor(log_callback=self.logger.info)

        self._caffeinate_proc = None

        # Scheduler - parallel execution to prevent job starvation
        self.scheduler = BlockingScheduler(
            executors={
                'default': ThreadPoolExecutor(max_workers=4),
            },
            job_defaults={
                'misfire_grace_time': 300,   # 5 min grace window
                'coalesce': True,            # Merge missed runs into one
                'max_instances': 1,          # No overlapping runs of same job
            }
        )

        # Base directory (for vadimgest and other CLI tools)
        self.base_dir = self.config_path.resolve().parent.parent  # gateway/config.yaml -> claude/

        # State
        self._state_lock = threading.Lock()  # Prevent concurrent _save_state() race condition
        self.state = self._load_state()
        self.jobs = []
        self.jobs_file_mtime = 0  # Track file modification time for hot-reload
        self._last_wake_check = time.monotonic()  # For sleep/wake detection
        self._internet_available = True
        self._internet_lost_at = None

    def _load_config(self) -> Dict:
        """Load gateway config."""
        with open(self.config_path) as f:
            return yaml.safe_load(f)

    def _load_state(self) -> Dict:
        """Load or initialize state."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError):
                self.logger.warning("Corrupt state file, reinitializing")

        return {
            "daemon_start_time": datetime.now(timezone.utc).isoformat(),
            "last_successful_check": datetime.now(timezone.utc).isoformat(),
            "jobs_status": {}
        }

    def _save_state(self):
        """Persist state to disk (atomic write, thread-safe)."""
        with self._state_lock:
            tmp_file = self.state_file.with_suffix('.tmp')
            with open(tmp_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            os.replace(tmp_file, self.state_file)

    def _get_vadimgest_stats(self, consumer: str = "heartbeat") -> Optional[Dict]:
        """Get vadimgest checkpoint stats for a consumer. Returns {source: {total, checkpoint}} or None."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "vadimgest", "read", "-c", consumer, "--stats"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.base_dir)
            )
            if result.returncode != 0:
                return None
            stats = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                # Parse: "  telegram: 384441 total, 304 new (checkpoint at 384137)"
                m = re.match(r'(\w+):\s+(\d+)\s+total,\s+(\d+)\s+new', line)
                if m:
                    stats[m.group(1)] = {"total": int(m.group(2)), "new": int(m.group(3))}
            return stats if stats else None
        except Exception:
            return None

    def _get_vadimgest_details(self, consumer: str = "heartbeat") -> Optional[Dict]:
        """Get group-level breakdown of new records from vadimgest."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "vadimgest", "read", "-c", consumer,
                 "-f", "json"],
                capture_output=True, text=True, timeout=30,
                cwd=str(self.base_dir)
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            try:
                data = json.loads(result.stdout)
            except (json.JSONDecodeError, ValueError):
                return None
            # data is {source: [records...]}
            details = {}
            for source, records in data.items():
                if not isinstance(records, list):
                    continue
                groups = {}
                for r in records:
                    # chat is a top-level field in vadimgest records
                    group = r.get("chat", "unknown")
                    if group == "unknown" and source == "signal":
                        group = r.get("meta", {}).get("contact_name", "unknown")
                    groups[group] = groups.get(group, 0) + 1
                details[source] = groups
            return details if details else None
        except Exception:
            return None

    def _log_run(self, entry: Dict):
        """Append run entry to JSONL log."""
        with open(self.runs_log, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    # Alert-dedup cadence: after the first alert for a given (job_id, error-key),
    # suppress further alerts until one of these escalation steps elapses.
    # Keeps a silent-loop heartbeat from spamming Telegram every tick.
    _ALERT_ESCALATION_SECONDS = (3600, 21600, 86400)  # 1h, 6h, 24h

    def _alert_key(self, job_id: str, error: str) -> str:
        """Short canonical key for alert dedup: first line of error, truncated."""
        first = (error or "").strip().splitlines()[0] if error else ""
        return f"{job_id}:{first[:120]}"

    def _should_alert(self, job_id: str, error: str) -> bool:
        """Return True if this alert should fire now; record the send time if so."""
        key = self._alert_key(job_id, error)
        alerts = self.state.setdefault("alert_history", {})
        entry = alerts.get(key, {})
        last_sent = entry.get("last_sent")
        count = entry.get("count", 0)
        now = time.time()
        if last_sent is not None:
            idx = min(count - 1, len(self._ALERT_ESCALATION_SECONDS) - 1)
            if idx < 0:
                idx = 0
            cooldown = self._ALERT_ESCALATION_SECONDS[idx]
            if now - last_sent < cooldown:
                return False
        alerts[key] = {"last_sent": now, "count": count + 1}
        # Trim to avoid unbounded growth
        if len(alerts) > 64:
            for k in sorted(alerts, key=lambda k: alerts[k].get("last_sent", 0))[:16]:
                alerts.pop(k, None)
        self._save_state()
        return True

    def _send_failure_alert(self, job_id: str, error: str, duration: float):
        """Send failure alert via feed (logs + Telegram), with dedup / escalation."""
        if not self._should_alert(job_id, error):
            self.logger.info(f"Job {job_id}: alert suppressed by dedup ({self._alert_key(job_id, error)})")
            return
        message = f"CRON Job Failed: {job_id}\nError: {error}\nDuration: {duration:.1f}s"
        send_feed(message, topic="Alerts", job_id=job_id)

    def _consecutive_failures(self, job_id: str, limit: int = 3) -> int:
        """Count trailing consecutive failures for job_id in runs.jsonl.

        Scans the runs log tail, ignoring 'started' / 'catch_up' / 'skipped'
        markers, returning the number of most-recent terminal runs that were
        'failed'. Stops at the first terminal success or at `limit`.
        """
        if not self.runs_log.exists():
            return 0
        try:
            with open(self.runs_log, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                tail_bytes = min(size, 256 * 1024)
                f.seek(size - tail_bytes)
                chunk = f.read().decode('utf-8', errors='ignore')
        except OSError:
            return 0
        failures = 0
        for line in reversed(chunk.splitlines()):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("job_id") != job_id:
                continue
            status = entry.get("status")
            if status in ("started", "catch_up", "skipped"):
                continue
            if status == "failed":
                failures += 1
                if failures >= limit:
                    return failures
                continue
            # Terminal non-failure (e.g. completed, crashed-but-recovered success)
            return failures
        return failures

    def _build_heartbeat_report(self, run_entry: Dict) -> Optional[str]:
        """Build structured heartbeat report for Telegram.

        Takes programmatic intake data + LLM deltas and builds a clean report.
        Returns formatted message or None if nothing to report (intake=0).
        """
        intake = run_entry.get("intake", {})
        total_new = intake.get("total_new", 0)

        # No intake at all -> suppress
        if total_new == 0:
            return None

        # Build timestamp header
        from zoneinfo import ZoneInfo
        tz_name = _cfg.timezone()
        ts = datetime.fromisoformat(run_entry["timestamp"])
        ts_local = ts.astimezone(ZoneInfo(tz_name))
        duration = run_entry.get("duration_seconds", 0)

        lines = [f"<b>Heartbeat {ts_local.strftime('%H:%M')} {tz_name}</b> ({duration}s)"]
        lines.append("")

        # INTAKE section - programmatic per-chat breakdown
        stats = intake.get("stats", {})
        details = intake.get("details", {})

        lines.append(f"<b>INTAKE:</b> {total_new} records")

        for source, count in sorted(stats.items(), key=lambda x: -x[1]):
            source_details = details.get(source, {}) if details else {}
            if source_details:
                # Sort by count descending, show top 5 chats
                top_chats = sorted(source_details.items(), key=lambda x: -x[1])[:5]
                chat_parts = [f"{name}: {n}" for name, n in top_chats]
                remaining = count - sum(n for _, n in top_chats)
                if remaining > 0:
                    chat_parts.append(f"...+{remaining}")
                lines.append(f"  {source}: {count} ({', '.join(chat_parts)})")
            else:
                lines.append(f"  {source}: {count}")

        # ACTIONS section from deltas
        deltas = run_entry.get("deltas")
        action_deltas = [d for d in (deltas or []) if d.get("type") != "skipped"]
        skipped_deltas = [d for d in (deltas or []) if d.get("type") == "skipped"]

        if action_deltas:
            lines.append("")
            lines.append(f"<b>ACTIONS:</b> {len(action_deltas)}")
            for d in action_deltas:
                delta_type = d.get("type", "unknown")
                icon = self._delta_icon(delta_type)

                # Enriched delta with summary - preferred path
                if d.get("summary"):
                    lines.append(f"  {icon} {d['summary']}")
                    sub_parts = []
                    if d.get("stage"):
                        sub_parts.append(f"stage: {d['stage']}")
                    if d.get("next_action"):
                        sub_parts.append(f"next: {d['next_action']}")
                    if d.get("trajectory"):
                        sub_parts.append(d["trajectory"])
                    if sub_parts:
                        lines.append(f"     <i>{' | '.join(sub_parts)}</i>")
                    continue

                # Fallback for old-format deltas
                if "gtask" in delta_type:
                    lines.append(f"  {icon} GTask: {d.get('title', '?')}")
                elif "obsidian" in delta_type or delta_type == "observation":
                    path = d.get("path", "?")
                    short = path.rsplit("/", 1)[-1].replace(".md", "")
                    change = d.get("change", "updated")
                    lines.append(f"  {icon} {short}: {change}")
                elif "gmail" in delta_type:
                    lines.append(f"  {icon} Draft: {d.get('subject', '?')}")
                elif "calendar" in delta_type:
                    lines.append(f"  {icon} Event: {d.get('title', '?')}")
                elif "deal" in delta_type:
                    name = d.get("deal_name") or self._deal_name_from_path(d.get("path", ""))
                    lines.append(f"  {icon} {name} - {d.get('change', '?')}")
                elif delta_type == "dispatched":
                    lines.append(f"  {icon} {d.get('label', '?')} → {d.get('expected', '?')}")
                else:
                    label = d.get("title", d.get("path", d.get("deal", "?")))
                    lines.append(f"  {icon} {delta_type}: {label}")

        # Skipped summary with hints
        if skipped_deltas:
            total_skip = sum(d.get("count", 1) for d in skipped_deltas)
            hints = []
            for d in skipped_deltas[:4]:
                src = (d.get("source") or "?").split("/")[-1]
                hint = d.get("hint", "")
                count = d.get("count", 1)
                part = src
                if count > 1:
                    part += f" x{count}"
                if hint and hint != src:
                    part += f" ({hint})"
                hints.append(part)
            if hints:
                lines.append(f"  <i>Noise {total_skip}: {', '.join(hints)}</i>")

        # TODOS section - show in-progress and pending tasks
        todos = run_entry.get("todos", [])
        if todos:
            lines.append("")
            lines.append(f"<b>TODOS:</b>")
            completed_count = 0
            in_progress_count = 0
            pending_count = 0
            for todo in todos:
                if isinstance(todo, dict):
                    status = todo.get("status", "pending")
                    content = todo.get("content", "?")
                else:
                    # Handle string format if needed
                    content = str(todo)
                    status = "pending"

                if status == "completed":
                    lines.append(f"  ✅ {content}")
                    completed_count += 1
                elif status == "in_progress":
                    lines.append(f"  🔄 {content}")
                    in_progress_count += 1
                else:  # pending
                    lines.append(f"  ⏳ {content}")
                    pending_count += 1

            # Summary line if there are many todos
            if len(todos) > 8:
                summary_parts = []
                if completed_count > 0:
                    summary_parts.append(f"{completed_count}✅")
                if in_progress_count > 0:
                    summary_parts.append(f"{in_progress_count}🔄")
                if pending_count > 0:
                    summary_parts.append(f"{pending_count}⏳")
                if summary_parts:
                    lines.append(f"  <i>Total: {' | '.join(summary_parts)}</i>")

        # LLM context - only meaningful non-boilerplate text
        clean_output = run_entry.get("output", "")
        if clean_output:
            # Strip INTAKE line and HEARTBEAT_OK (cron now builds these)
            filtered = []
            for line in clean_output.split('\n'):
                stripped = line.strip()
                if stripped.startswith('INTAKE:'):
                    continue
                if re.match(r'HEARTBEAT[_\s-]*OK', stripped, re.IGNORECASE):
                    continue
                if stripped:
                    filtered.append(line)

            llm_text = '\n'.join(filtered).strip()
            if llm_text and len(llm_text) > 10:
                lines.append("")
                # Escape HTML special chars before embedding in HTML message
                lines.append(html.escape(llm_text))

        return '\n'.join(lines)

    @staticmethod
    def _delta_icon(delta_type: str) -> str:
        """Emoji prefix for delta type in TG messages."""
        if "gtask" in delta_type:
            return "\u2705" if "completed" in delta_type else "\u2611\ufe0f"
        if "deal" in delta_type:
            return "\U0001f4b0"
        if "obsidian" in delta_type:
            return "\U0001f4dd"
        if "gmail" in delta_type:
            return "\u2709\ufe0f"
        if "calendar" in delta_type:
            return "\U0001f4c5"
        if delta_type == "observation":
            return "\U0001f441"
        if delta_type == "dispatched":
            return "\U0001f50d"
        if "inbox" in delta_type:
            return "\U0001f4e5"
        return "\u2022"

    @staticmethod
    def _deal_name_from_path(path: str) -> str:
        """Extract clean deal name from Obsidian path.

        'Deals/Acme — OSINT.md' -> 'Acme OSINT'
        'Deals/Globex — Ad Targeting API.md' -> 'Globex Ad Targeting API'
        """
        if not path:
            return "?"
        basename = path.rsplit("/", 1)[-1].replace(".md", "")
        if " — " in basename:
            parts = basename.split(" — ", 1)
            return f"{parts[0]} {parts[1]}".strip()
        return basename.strip() or "?"

    def _resolve_topic(self, job: Dict) -> str:
        """Resolve feed topic label for a job. feed_topic is the only source now."""
        return job.get("feed_topic") or "General"

    def _check_internet(self, timeout: float = 3.0) -> bool:
        """Quick TCP connectivity check via DNS (8.8.8.8:53)."""
        import socket
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout)
            sock.close()
            return True
        except OSError:
            return False

    def _wait_for_api(self, max_wait: int = 60, interval: int = 10) -> bool:
        """Wait for API to become reachable after sleep/connectivity restore.

        After long sleep, Claude API gets ConnectionRefused for ~30-60s.
        This prevents wasting catch-up attempts on a cold API.
        """
        import urllib.request
        api_url = "https://api.anthropic.com/"
        for attempt in range(max_wait // interval):
            try:
                req = urllib.request.Request(api_url, method="HEAD")
                urllib.request.urlopen(req, timeout=5)
                self.logger.info(f"API warmup: reachable after {attempt * interval}s")
                return True
            except Exception:
                pass
            self.logger.info(f"API warmup: attempt {attempt + 1}/{max_wait // interval}, waiting {interval}s...")
            time.sleep(interval)
        return False

    def _monitor_connectivity(self):
        """Monitor internet connectivity and trigger catch-up on restore."""
        online = self._check_internet()

        if self._internet_available and not online:
            # Was online, now offline
            self._internet_available = False
            self._internet_lost_at = datetime.now(timezone.utc)
            self.logger.warning("Internet connectivity lost")
        elif not self._internet_available and online:
            # Was offline, now online
            lost_duration = ""
            if self._internet_lost_at:
                elapsed = (datetime.now(timezone.utc) - self._internet_lost_at).total_seconds()
                lost_duration = f" after {elapsed:.0f}s"
            self._internet_available = True
            self._internet_lost_at = None
            self.logger.info(f"Internet connectivity restored{lost_duration}, warming up API...")
            self.load_jobs()
            if not self._wait_for_api(max_wait=90, interval=10):
                self.logger.warning("API not available after connectivity restore, catch-up deferred")
                return
            self.detect_missed_jobs()

    def load_jobs(self):
        """Load job definitions from jobs.json."""
        if not self.jobs_file.exists():
            self.logger.warning(f"Jobs file not found: {self.jobs_file}")
            return []

        with open(self.jobs_file) as f:
            data = json.load(f)

        jobs = data.get("jobs", [])
        self.logger.info(f"Loaded {len(jobs)} jobs from {self.jobs_file}")
        self.jobs = jobs
        return jobs

    def detect_missed_jobs(self):
        """Detect and execute missed jobs with catch-up logic.

        Jobs are sorted by priority so important ones (mentor, heartbeat)
        run before heavy background jobs (vadimgest-sync).
        Catch-up timeout can be specified per-job to prevent starvation.
        """
        now = datetime.now(timezone.utc)

        self.logger.info("Checking for missed jobs...")

        # Collect all missed jobs first, then sort by priority
        missed_jobs = []

        for job in self.jobs:
            if not job.get("enabled", True):
                continue

            catch_up = job.get("catch_up", {})
            if not catch_up.get("enabled", False):
                continue

            max_catch_up = catch_up.get("max_catch_up", 1)
            if max_catch_up == 0:
                continue

            # Use per-job last_run instead of global last_check
            job_id = job["id"]
            job_status = self.state.get("jobs_status", {}).get(job_id, {})
            last_run_str = job_status.get("last_run")
            if last_run_str:
                last_check = datetime.fromisoformat(last_run_str)
            else:
                # Fallback to global check if no per-job status
                last_check = datetime.fromisoformat(self.state["last_successful_check"])

            # Calculate missed runs
            missed_times = self._calculate_missed_runs(job, last_check, now)

            if not missed_times:
                continue

            missed_jobs.append((job, missed_times, max_catch_up))

        # Sort by priority (mentor first, syncs last)
        missed_jobs.sort(key=lambda x: JOB_PRIORITY.get(x[0]['id'], 10))

        for job, missed_times, max_catch_up in missed_jobs:
            # Skip internet-dependent jobs when offline
            if job.get("requires_internet", True) and not self._internet_available:
                self.logger.info(
                    f"Job {job['id']}: {len(missed_times)} missed, "
                    f"skipping catch-up (no internet)"
                )
                continue

            # Limit by max_catch_up (run most recent N)
            runs_to_execute = missed_times[-max_catch_up:]

            self.logger.info(
                f"Job {job['id']}: {len(missed_times)} missed, "
                f"executing {len(runs_to_execute)} catch-up runs"
            )

            for missed_time in runs_to_execute:
                self._log_run({
                    "timestamp": now.isoformat(),
                    "job_id": job["id"],
                    "status": "missed",
                    "scheduled_time": missed_time.isoformat()
                })

                # Update state BEFORE execution to prevent infinite catch-up
                # loop if the process crashes (e.g., OOM) during execution.
                # Without this, a crash means state never updates, and the
                # next restart detects the same missed run again.
                self.state["jobs_status"][job["id"]] = {
                    "last_run": now.isoformat(),
                    "status": "catching_up",
                    "session_id": None
                }
                self._save_state()

                # Execute as catch-up (protected to prevent scheduler crash)
                try:
                    self._execute_job_internal(job, is_catch_up=True)
                except Exception as e:
                    self.logger.error(
                        f"CRITICAL: Catch-up for {job['id']} crashed: {e}"
                    )
                    self.state["jobs_status"][job["id"]] = {
                        "last_run": now.isoformat(),
                        "status": "crashed",
                        "session_id": None
                    }
                    self._save_state()
                    self._send_failure_alert(
                        job["id"], f"Catch-up crashed: {e}", 0
                    )

    def _calculate_missed_runs(
        self, job: Dict, start: datetime, end: datetime
    ) -> List[datetime]:
        """Calculate missed run times for a job."""
        schedule = job.get("schedule", {})
        schedule_type = schedule.get("type")

        missed = []

        if schedule_type == "every":
            # Interval-based schedule
            if "interval_minutes" in schedule:
                interval = schedule["interval_minutes"] * 60
            elif "interval_hours" in schedule:
                interval = schedule["interval_hours"] * 3600
            elif "interval_days" in schedule:
                interval = schedule["interval_days"] * 86400
            else:
                return []

            current = start
            while current < end:
                current = datetime.fromtimestamp(
                    current.timestamp() + interval, tz=timezone.utc
                )
                if current < end:
                    missed.append(current)

        elif schedule_type == "cron":
            # CRON expression - interpreted in local time (configured timezone).
            # APScheduler CronTrigger uses local time by default, so catch-up
            # must match by converting UTC start/end to local time for croniter
            cron_expr = schedule.get("cron")
            if not cron_expr:
                return []

            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(_cfg.timezone())
            start_local = start.astimezone(local_tz)
            end_local = end.astimezone(local_tz)

            cron = croniter(cron_expr, start_local)
            while True:
                next_time = cron.get_next(datetime)
                if next_time.tzinfo is None:
                    next_time = next_time.replace(tzinfo=local_tz)
                if next_time >= end_local:
                    break
                # Store as UTC for consistency
                missed.append(next_time.astimezone(timezone.utc))

        elif schedule_type == "at":
            # One-shot datetime
            dt_str = schedule.get("datetime")
            if not dt_str:
                return []

            try:
                scheduled = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                return []
            if start <= scheduled < end:
                missed.append(scheduled)

        return missed

    def schedule_jobs(self):
        """Add jobs to APScheduler."""
        for job in self.jobs:
            if not job.get("enabled", True):
                self.logger.info(f"Skipping disabled job: {job['id']}")
                continue

            schedule = job.get("schedule", {})
            schedule_type = schedule.get("type")

            trigger = None

            if schedule_type == "every":
                # Interval trigger
                kwargs = {}
                if "interval_minutes" in schedule:
                    kwargs["minutes"] = schedule["interval_minutes"]
                elif "interval_hours" in schedule:
                    kwargs["hours"] = schedule["interval_hours"]
                elif "interval_days" in schedule:
                    kwargs["days"] = schedule["interval_days"]
                trigger = IntervalTrigger(**kwargs)

            elif schedule_type == "cron":
                # CRON trigger
                cron_expr = schedule.get("cron")
                if cron_expr:
                    trigger = CronTrigger.from_crontab(cron_expr)

            elif schedule_type == "at":
                # Date trigger (one-shot)
                dt_str = schedule.get("datetime")
                if dt_str:
                    try:
                        run_date = datetime.fromisoformat(dt_str)
                        trigger = DateTrigger(run_date=run_date)
                    except (ValueError, TypeError):
                        self.logger.warning(f"Invalid datetime for job {job['id']}: {dt_str}")

            if trigger:
                self.scheduler.add_job(
                    func=self._execute_job,
                    trigger=trigger,
                    args=[job],
                    id=job["id"],
                    name=job.get("name", job["id"]),
                    replace_existing=True
                )
                self.logger.info(f"Scheduled job: {job['id']} ({schedule_type})")
            else:
                self.logger.warning(f"Invalid schedule for job: {job['id']}")

    def _is_network_error(self, error: str) -> bool:
        """Check if error is due to no network connectivity (should wait for internet)."""
        network_patterns = [
            "FailedToOpenSocket",
            "Unable to connect",
            "ConnectionRefusedError",
            "ConnectionResetError",
            "ECONNREFUSED",
            "Network is unreachable",
            "Connection error",
        ]
        return any(p.lower() in error.lower() for p in network_patterns)

    def _is_retryable_error(self, error: str) -> bool:
        """Check if an error is transient and worth retrying (non-network).

        Timeouts from claude_executor (``Timeout after Ns``) are NOT retryable:
        a session that exhausted its wall-clock budget once will almost always
        exhaust it again, and each retry costs another session launch + context
        load. Let the scheduled cadence pick up the next run instead.
        """
        err = (error or "").lower()
        if "timeout after" in err:
            return False
        retryable_patterns = [
            "TimeoutError",
            "ETIMEDOUT",
            "authentication_error",
            "token has expired",
            "Failed to authenticate",
            "500",
            "503",
            # Exit 143 = SIGTERM. Two common causes: claude.ai Max usage-limit kill
            # (needs hours to clear) and macOS App Nap / upstream SIGTERM (transient).
            # Job config must use a 60+ min delay and max_attempts=1 so one retry
            # gives the usage window a chance to roll without burning cycles.
            "exit code 143",
        ]
        return any(p.lower() in err for p in retryable_patterns)

    def _schedule_retry(self, job: Dict, attempt: int):
        """Schedule a one-shot retry for a failed job."""
        retry_config = job.get("retry", {})
        delay_minutes = retry_config.get("delay_minutes", 15)
        max_attempts = retry_config.get("max_attempts", 3)

        if attempt >= max_attempts:
            self.logger.warning(f"Job {job['id']}: Max retry attempts ({max_attempts}) reached, giving up")
            return

        from datetime import timedelta
        retry_time = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
        retry_id = f"{job['id']}_retry_{attempt + 1}"

        self.logger.info(f"Job {job['id']}: Scheduling retry {attempt + 1}/{max_attempts} at {retry_time.isoformat()}")

        self.scheduler.add_job(
            func=self._execute_retry,
            trigger=DateTrigger(run_date=retry_time),
            args=[job, attempt + 1],
            id=retry_id,
            name=f"{job.get('name', job['id'])} (retry {attempt + 1})",
            replace_existing=True
        )

    def _execute_retry(self, job: Dict, attempt: int):
        """Execute a retry attempt for a failed job."""
        # Skip internet-dependent jobs when offline
        if job.get("requires_internet", True) and not self._internet_available:
            job_id = job.get("id", "unknown")
            self.logger.info(f"Skipping retry {attempt} for {job_id}: no internet")
            # Re-schedule retry for later
            self._schedule_retry(job, attempt - 1)
            return
        job_id = job.get("id", "unknown")
        self.logger.info(f"Executing retry {attempt} for job {job_id}")
        try:
            self._execute_job_internal(job, is_catch_up=False, retry_attempt=attempt)
        except Exception as e:
            self.logger.error(f"CRITICAL: Job {job_id} retry {attempt} crashed: {e}")
            self._send_failure_alert(job_id, f"Retry {attempt} crashed: {e}", 0)

    def _execute_job(self, job: Dict):
        """Execute a scheduled job with exception protection."""
        # Reap stale child processes before launching new ones (safety net)
        try:
            from lib.claude_executor import ClaudeExecutor
            ClaudeExecutor.reap_stale_children(os.getpid(), max_age_seconds=5400, log=self.logger.info)
        except Exception:
            pass
        # Skip internet-dependent jobs when offline
        if job.get("requires_internet", True) and not self._internet_available:
            job_id = job.get("id", "unknown")
            self.logger.info(f"Skipping {job_id}: no internet (offline since {self._internet_lost_at})")
            return
        # Circuit breaker: if the last N runs of this job all failed, don't
        # launch another session - cost stays bounded until someone looks.
        job_id = job.get("id", "unknown")
        breaker_threshold = int(job.get("circuit_breaker", {}).get("threshold", 3)) if isinstance(job.get("circuit_breaker"), dict) else 3
        failures = self._consecutive_failures(job_id, limit=breaker_threshold)
        if failures >= breaker_threshold:
            self.logger.warning(
                f"Job {job_id}: circuit breaker open ({failures} consecutive failures), skipping run"
            )
            self._log_run({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": job_id,
                "status": "skipped",
                "run_id": f"{job_id}_{int(time.time())}_breaker",
                "error": f"Circuit breaker open: {failures} consecutive failures",
            })
            self._send_failure_alert(
                job_id,
                f"Circuit breaker OPEN: {failures} consecutive failures. "
                f"Job is skipped until a run succeeds. Investigate and re-trigger manually.",
                0.0,
            )
            return
        try:
            self._execute_job_internal(job, is_catch_up=False, retry_attempt=0)
        except Exception as e:
            # Catch ANY exception to prevent scheduler crash
            job_id = job.get("id", "unknown")
            self.logger.error(f"CRITICAL: Job {job_id} crashed with unhandled exception: {e}")
            self._send_failure_alert(job_id, f"Unhandled exception: {e}", 0)
            # Update state to mark as failed
            self.state["jobs_status"][job_id] = {
                "last_run": datetime.now(timezone.utc).isoformat(),
                "status": "crashed",
                "session_id": None
            }
            self._save_state()

    def _execute_job_internal(self, job: Dict, is_catch_up: bool, retry_attempt: int = 0):
        """Internal job execution with logging."""
        job_id = job["id"]
        run_id = f"{job_id}_{int(time.time())}"
        if is_catch_up:
            run_id += "_catchup"

        now = datetime.now(timezone.utc)

        # Log start
        self._log_run({
            "timestamp": now.isoformat(),
            "job_id": job_id,
            "status": "catch_up" if is_catch_up else "started",
            "run_id": run_id
        })

        self.logger.info(f"Executing job: {job_id} (catch_up={is_catch_up})")

        # Skip if another instance of same job is already running (detached overlap guard)
        running_jobs = self.state.get("running_foreground_jobs", {})
        for rid, rinfo in running_jobs.items():
            if rinfo.get("job_id") == job_id and rid != run_id:
                from lib.subagent_state import is_process_alive
                if is_process_alive(rinfo.get("pid")):
                    self.logger.warning(f"Job {job_id}: Skipping - another instance {rid} still running (PID {rinfo.get('pid')})")
                    self._log_run({
                        "timestamp": now.isoformat(),
                        "job_id": job_id,
                        "status": "skipped",
                        "run_id": run_id,
                        "error": f"Another instance {rid} still running",
                    })
                    return

        # Capture vadimgest stats before execution (for heartbeat/proactive jobs)
        intake_before = None
        intake_details = None
        if job_id in ("heartbeat", "heartbeat-mini"):
            intake_before = self._get_vadimgest_stats("intake")
            intake_details = self._get_vadimgest_details("intake")
            self.logger.info(f"Intake captured: stats={intake_before is not None}, details={intake_details}")

        # Get execution config
        exec_config = job.get("execution", {})
        mode = exec_config.get("mode", "isolated")
        timeout = exec_config.get("timeout_seconds", 300)

        start_time = time.time()

        # Handle bash mode - direct command execution
        if mode == "bash":
            command = exec_config.get("command", "")
            if not command:
                result = {"error": "No command specified for bash mode"}
            else:
                try:
                    import subprocess
                    proc = subprocess.run(
                        ["bash", "-c", command],
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        env=os.environ.copy(),
                        cwd=os.path.expanduser("~"),
                    )
                    result = {
                        "result": proc.stdout + proc.stderr,
                        "error": None if proc.returncode == 0 else f"Exit code {proc.returncode}: {proc.stderr}",
                        "exit_code": proc.returncode,
                        "cost": 0.0
                    }
                except subprocess.TimeoutExpired:
                    result = {"error": f"Timeout after {timeout}s", "cost": 0.0}
                except Exception as e:
                    result = {"error": str(e), "cost": 0.0}
            self.logger.info(f"Job {job_id}: bash completed, exit={result.get('exit_code')}, error={result.get('error')}")
        else:
            # Execute via Claude CLI (skip permissions for automation)
            prompt = exec_config.get("prompt_template", "")

            # Replace template variables
            prompt = prompt.replace("{{now}}", now.isoformat())
            from zoneinfo import ZoneInfo
            tz_name = _cfg.timezone()
            now_local = now.astimezone(ZoneInfo(tz_name))
            prompt = prompt.replace("{{now_eet}}", now_local.strftime(f"%Y-%m-%d %H:%M {tz_name}"))

            allowed_tools = exec_config.get("allowedTools", ["*"])
            add_dirs = exec_config.get("add_dirs", [])
            session_id = exec_config.get("session_id")
            model = exec_config.get("model", _cfg.default_model())
            max_turns = exec_config.get("max_turns")
            fallback_model = exec_config.get("fallback_model")
            thinking = exec_config.get("thinking")

            # Resolve special session_id values
            if session_id == "$main":
                session_id = get_main_session_id()
                if not session_id:
                    self.logger.warning(f"Job {job_id}: No main session exists yet, running isolated")
                    mode = "isolated"

            self.logger.info(f"Job {job_id}: mode={mode}, session_id={session_id}, model={model}")

            result = self._run_claude_detached(
                prompt, run_id, job, mode, session_id, model,
                timeout, allowed_tools, add_dirs, is_catch_up,
                intake_before, intake_details, retry_attempt,
                max_turns=max_turns, fallback_model=fallback_model,
                thinking=thinking,
            )

            # Auto-recovery: if session expired or init failed, clear it and retry isolated
            error_str = str(result.get("error", ""))
            recoverable = "No conversation found" in error_str or "Control request timeout" in error_str
            if result.get("error") and recoverable and mode == "main":
                self.logger.warning(f"Job {job_id}: Session expired, clearing and retrying isolated...")

                # Clear stale session from state
                if job_id in self.state.get("jobs_status", {}):
                    self.state["jobs_status"][job_id]["session_id"] = None

                # If this was a main session job, clear the main session file too
                if exec_config.get("session_id") == "$main":
                    from lib.main_session import clear_main_session_id
                    clear_main_session_id()
                    self.logger.info(f"Job {job_id}: Cleared main session ID")

                # Retry in isolated mode (no session)
                result = self._run_claude_detached(
                    prompt, f"{run_id}_retry", job, "isolated", None, model,
                    timeout, allowed_tools, add_dirs, is_catch_up,
                    intake_before, intake_details, retry_attempt,
                    max_turns=max_turns, fallback_model=fallback_model,
                    thinking=thinking,
                )
                self.logger.info(f"Job {job_id}: Retry completed, error={result.get('error')}")

        duration = time.time() - start_time
        try:
            self._process_job_result(
                job, run_id, result, now, duration,
                exec_config, intake_before, intake_details, retry_attempt
            )
        except Exception as e:
            self.logger.error(f"CRITICAL: _process_job_result crashed for {job_id}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            # Still try to log the run
            self._log_run({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": job_id,
                "status": "completed" if not result.get("error") else "failed",
                "duration_seconds": int(duration),
                "cost_usd": result.get("cost", 0.0),
                "error": result.get("error"),
            })

    def _run_claude_detached(self, prompt, run_id, job, mode, session_id, model,
                             timeout, allowed_tools, add_dirs, is_catch_up,
                             intake_before, intake_details, retry_attempt,
                             max_turns=None, fallback_model=None, thinking=None):
        """Run Claude CLI as detached process with state tracking for restart recovery.

        The detached process writes output to files instead of pipes, so it
        survives daemon restart (no SIGPIPE). State is tracked in running_foreground_jobs
        for recovery on next startup.
        """
        launch = self.executor.run_detached(
            prompt=prompt, run_id=run_id, mode=mode, session_id=session_id,
            model=model, timeout=timeout, allowed_tools=allowed_tools,
            add_dirs=add_dirs, skip_permissions=True,
            max_turns=max_turns, fallback_model=fallback_model,
            thinking=thinking,
        )

        if launch.get("error"):
            return {"error": launch["error"], "cost": 0.0, "exit_code": -1}

        # Register for restart recovery
        self.state.setdefault("running_foreground_jobs", {})[run_id] = {
            "job_id": job["id"],
            "run_id": run_id,
            "pid": launch["pid"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "timeout": timeout,
            "output_dir": launch["output_dir"],
            "job_config": job,
            "is_catch_up": is_catch_up,
            "intake_before": intake_before,
            "intake_details": intake_details,
            "retry_attempt": retry_attempt,
        }
        self._save_state()

        result = self.executor.wait_for_result(
            run_id=run_id, timeout=timeout + 30, session_id=session_id,
        )

        # Cleanup state
        self.state.get("running_foreground_jobs", {}).pop(run_id, None)
        self._save_state()

        return result

    def _process_job_result(self, job, run_id, result, now, duration,
                            exec_config, intake_before, intake_details, retry_attempt):
        """Process a completed job result: log, state update, TG alert, retry logic."""
        job_id = job["id"]

        # Update main session ID if this was a main session job AND it succeeded
        # Don't save session from failed jobs - they leave corrupted sessions
        if exec_config.get("session_id") == "$main" and result.get("session_id") and not result.get("error"):
            save_main_session_id(result.get("session_id"))
            self.logger.info(f"Job {job_id}: Updated main session ID")

        # Save previous state for retry rollback
        if "_prev_job_status" not in self.state:
            self.state["_prev_job_status"] = {}
        if job_id in self.state.get("jobs_status", {}):
            self.state["_prev_job_status"][job_id] = self.state["jobs_status"][job_id].copy()

        # Capture vadimgest stats after execution to compute delta
        intake_after = None
        intake_consumed = None
        if intake_before is not None:
            intake_after = self._get_vadimgest_stats("intake")
            if intake_after:
                intake_consumed = {}
                for src, after in intake_after.items():
                    before = intake_before.get(src, {})
                    new_before = before.get("new", 0)
                    new_after = after.get("new", 0)
                    consumed = max(0, new_before - new_after)
                    if consumed > 0 or new_before > 0:
                        # pending_before/after = records past checkpoint at start/end of run.
                        # (Same as new_before/new_after; renamed for clarity - previous
                        # 'had' looked like 'total in file' and alarmed readers.)
                        intake_consumed[src] = {
                            "pending_before": new_before,
                            "consumed": consumed,
                            "pending_after": new_after,
                            # Legacy aliases - remove after one release cycle:
                            "had": new_before,
                            "remaining": new_after,
                        }

        # Log completion with output
        output = result.get("result", "")
        has_error = bool(result.get("error"))

        # Parse deltas from output (heartbeat structured action log)
        deltas = None
        clean_output = output
        if output and '---DELTAS---' in output:
            parts = output.split('---DELTAS---', 1)
            clean_output = parts[0].rstrip()
            try:
                deltas = json.loads(parts[1].strip())
            except (json.JSONDecodeError, IndexError):
                deltas = None

        # Strip wrapping code fences models add (```\n...\n```)
        if clean_output:
            stripped = clean_output.strip()
            if stripped.startswith('```') and stripped.endswith('```'):
                first_nl = stripped.find('\n')
                if first_nl >= 0:
                    clean_output = stripped[first_nl + 1:stripped.rfind('```')].strip()

        session_id = result.get("session_id")

        run_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": job_id,
            "status": "completed" if not has_error else "failed",
            "run_id": run_id,
            "session_id": session_id,
            "duration_seconds": int(duration),
            "cost_usd": result.get("cost", 0.0),
            "error": result.get("error"),
            "output": clean_output[:5000] if clean_output else None,
            "deltas": deltas,
            "todos": result.get("todos", []),
        }

        # Register session in registry for categorization/search
        if session_id:
            register_session(
                session_id=session_id,
                session_type="cron",
                job_id=job_id,
                model=exec_config.get("model", "sonnet"),
                run_id=run_id,
            )
        # Add intake data for heartbeat jobs
        if intake_before is not None:
            run_entry["intake"] = {
                "stats": {src: v.get("new", 0) for src, v in intake_before.items() if v.get("new", 0) > 0},
                "total_new": sum(v.get("new", 0) for v in intake_before.values()),
                "consumed": intake_consumed,
                "details": intake_details,
            }

        # Update state
        self.state["jobs_status"][job_id] = {
            "last_run": now.isoformat(),
            "status": "completed" if not has_error else "failed",
            "session_id": result.get("session_id")
        }
        self.state["last_successful_check"] = now.isoformat()
        self._save_state()

        self._log_run(run_entry)

        if has_error:
            error_msg = result.get("error", "")
            self.logger.error(f"Job {job_id} failed: {error_msg}")

            if self._is_network_error(error_msg):
                self.logger.info(f"Job {job_id}: Network error - reverting last_run, waiting for connectivity")
                prev_status = self.state.get("_prev_job_status", {}).get(job_id)
                if prev_status:
                    self.state["jobs_status"][job_id] = prev_status
                    self._save_state()
                return

            # Auth error - don't retry, alert immediately with fix instructions
            if "Not logged in" in error_msg or "authentication_failed" in error_msg:
                self.logger.error(f"Job {job_id}: AUTH FAILED - Claude not logged in")
                self._send_failure_alert(
                    job_id,
                    "AUTH FAILED: Claude not logged in.\n"
                    "Fix: run in terminal:\n"
                    f"env -u CLAUDECODE CLAUDE_CONFIG_DIR={_cfg.claude_config_dir()} claude login",
                    duration,
                )
                return

            # Non-network error - retry only if transient (timeouts excluded)
            retry_config = job.get("retry", {})
            max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3
            if not self._is_retryable_error(error_msg):
                self.logger.warning(f"Job {job_id}: non-retryable error, not scheduling retry. Error: {error_msg[:200]}")
                self._send_failure_alert(job_id, f"Non-retryable error: {error_msg}", duration)
                return
            if retry_attempt < max_attempts:
                self.logger.info(f"Job {job_id}: Retryable error, attempt {retry_attempt + 1}/{max_attempts}")
                prev_status = self.state.get("_prev_job_status", {}).get(job_id)
                if prev_status:
                    self.state["jobs_status"][job_id] = prev_status
                    self._save_state()
                self._schedule_retry(job, retry_attempt)
                return

            # All retries exhausted
            self.logger.error(f"Job {job_id}: FAILED after {max_attempts} attempts, giving up")
            self._send_failure_alert(job_id, f"FAILED after {max_attempts} attempts. Last error: {error_msg}", duration)
        else:
            self.logger.info(f"Job {job_id} completed in {duration:.1f}s")

            topic = self._resolve_topic(job)
            sid = run_entry.get("session_id")
            if job_id == "heartbeat":
                report = self._build_heartbeat_report(run_entry)
                if report:
                    send_feed(report, topic=topic, parse_mode="HTML", job_id=job_id, session_id=sid, deltas=run_entry.get("deltas"))
                else:
                    self.logger.info(f"Job {job_id}: No intake - no TG message")
            elif clean_output and topic != "General":
                send_feed(clean_output, topic=topic, parse_mode="HTML", job_id=job_id, session_id=sid, deltas=run_entry.get("deltas"))

            self._handle_on_complete(job, output)

    def _recover_foreground_jobs(self):
        """Recover foreground jobs orphaned by daemon restart.

        Checks running_foreground_jobs state for processes that were in-flight
        when the previous daemon instance died. For still-alive processes,
        waits for completion in background threads. For dead processes, reads
        whatever output files exist.
        """
        from lib.subagent_state import is_process_alive

        running = dict(self.state.get("running_foreground_jobs", {}))
        if not running:
            return

        self.logger.info(f"Recovering {len(running)} orphaned foreground jobs...")

        for run_id, info in running.items():
            pid = info.get("pid")
            job_id = info.get("job_id", "unknown")
            timeout = info.get("timeout", 600)
            started_at = info.get("started_at")

            # Calculate how long this job has been running
            elapsed = 0
            try:
                start = datetime.fromisoformat(started_at)
                elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            except (ValueError, TypeError):
                pass

            remaining_timeout = max(timeout - elapsed + 30, 30)

            if is_process_alive(pid):
                if elapsed > timeout + 60:
                    # Way past timeout - kill it
                    self.logger.warning(
                        f"Recovery: {run_id} (PID {pid}) exceeded timeout by {elapsed - timeout:.0f}s, killing"
                    )
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except (OSError, ProcessLookupError):
                            pass
                    time.sleep(1)
                    self._recover_single_job(run_id, info, timeout=5)
                else:
                    # Still running within timeout - wait in background thread
                    self.logger.info(
                        f"Recovery: {run_id} (PID {pid}) still alive "
                        f"({elapsed:.0f}s elapsed), waiting up to {remaining_timeout:.0f}s..."
                    )
                    t = threading.Thread(
                        target=self._recover_single_job,
                        args=(run_id, info, remaining_timeout),
                        daemon=True,
                    )
                    t.start()
            else:
                # Process dead - read whatever output exists
                self.logger.info(f"Recovery: {run_id} (PID {pid}) is dead, reading output...")
                self._recover_single_job(run_id, info, timeout=5)

    def _recover_single_job(self, run_id, info, timeout=30):
        """Recover a single foreground job - wait for process and process result."""
        job_id = info.get("job_id", "unknown")
        job = info.get("job_config", {"id": job_id})
        output_dir = info.get("output_dir", "/tmp/claude_jobs")
        is_catch_up = info.get("is_catch_up", False)
        intake_before = info.get("intake_before")
        intake_details = info.get("intake_details")
        retry_attempt = info.get("retry_attempt", 0)
        started_at = info.get("started_at", datetime.now(timezone.utc).isoformat())

        try:
            result = self.executor.wait_for_result(
                run_id=run_id, timeout=timeout, output_dir=output_dir,
            )
        except Exception as e:
            self.logger.error(f"Recovery failed for {run_id}: {e}")
            result = {"error": f"Recovery failed: {e}", "cost": 0.0, "exit_code": -1}

        # Cleanup state
        self.state.get("running_foreground_jobs", {}).pop(run_id, None)
        self._save_state()

        # Estimate duration
        try:
            start = datetime.fromisoformat(started_at)
            duration = (datetime.now(timezone.utc) - start).total_seconds()
        except (ValueError, TypeError):
            duration = 0

        now = datetime.now(timezone.utc)
        exec_config = job.get("execution", {})

        self.logger.info(f"Recovery: processing result for {run_id} (error={bool(result.get('error'))})")
        self._process_job_result(
            job, run_id, result, now, duration,
            exec_config, intake_before, intake_details, retry_attempt
        )

    def _handle_on_complete(self, job, output):
        """Trigger downstream job after successful completion (job chaining)."""
        on_complete = job.get("on_complete")
        if not on_complete:
            return

        target_id = on_complete.get("trigger")
        condition = on_complete.get("condition", "always")

        # Check condition
        if condition == "on_output" and not output:
            return
        if condition == "on_new_data":
            # Look for data markers in output
            if not output or not re.search(r'(?:synced|new|updated)\s+\d+', output, re.IGNORECASE):
                return

        # Find target job
        target_job = next((j for j in self.jobs if j["id"] == target_id), None)
        if not target_job:
            self.logger.warning(f"on_complete: target job '{target_id}' not found")
            return

        if not target_job.get("enabled", True):
            self.logger.info(f"on_complete: target job '{target_id}' is disabled, skipping")
            return

        self.logger.info(f"on_complete: {job['id']} -> triggering {target_id} (condition: {condition})")
        threading.Thread(target=self._execute_job, args=(target_job,), daemon=True).start()

    def _write_healthcheck(self):
        """Write healthcheck timestamp for external monitoring."""
        healthcheck_file = Path("/tmp/cron-scheduler.health")
        try:
            healthcheck_file.write_text(datetime.now(timezone.utc).isoformat())
        except Exception as e:
            self.logger.error(f"Failed to write healthcheck: {e}")

    def _start_healthcheck_thread(self):
        """Start background thread that writes healthcheck every 2 min.

        This keeps the healthcheck file fresh even during long blocking
        operations (catch-up), preventing the external watchdog from
        killing the process.
        """
        def _healthcheck_loop():
            while True:
                time.sleep(120)  # Every 2 min
                self._write_healthcheck()

        t = threading.Thread(target=_healthcheck_loop, daemon=True, name="healthcheck")
        t.start()
        self.logger.info("Healthcheck background thread started")

    def _check_sleep_wake(self):
        """Detect wake from sleep by checking elapsed wall-clock time.

        Runs every 60s. If actual elapsed time is >3 min, system was asleep.
        Triggers catch-up for missed jobs.
        """
        now = time.monotonic()
        elapsed = now - self._last_wake_check
        self._last_wake_check = now

        if elapsed > 180:  # 3 minutes = definitely was asleep
            sleep_duration = elapsed - 60  # subtract expected interval
            self.logger.info(
                f"Sleep/wake detected: {sleep_duration:.0f}s gap. "
                f"Warming up API before catch-up..."
            )
            # Reload jobs in case file changed during sleep
            self.load_jobs()
            # Wait for Claude API to become available before running catch-ups.
            # After long sleep, API connections get ConnectionRefused for ~30-60s.
            if not self._wait_for_api(max_wait=90, interval=10):
                self.logger.warning("API not available after warmup, catch-up will retry on next cycle")
                return
            self.detect_missed_jobs()

    def _check_jobs_reload(self):
        """Check if jobs.json was modified and reload if needed."""
        try:
            current_mtime = self.jobs_file.stat().st_mtime
            if current_mtime > self.jobs_file_mtime:
                self.logger.info("Detected jobs.json change, reloading...")
                self._reload_jobs()
                self.jobs_file_mtime = current_mtime
        except Exception as e:
            self.logger.error(f"Error checking jobs file: {e}")

    def _check_subagent_announces(self):
        """Check for completed sub-agents and process announces."""
        from lib.subagent_state import get_stale_subagents, fail_subagent

        try:
            # Check for completed sub-agents and process announces
            results = check_and_announce_completed()
            if results:
                for r in results:
                    status = r.get("status", "unknown")
                    job_id = r.get("job_id", "?")
                    if status == "sent":
                        self.logger.info(f"Sub-agent {job_id} announced successfully")
                    elif status == "requeued":
                        self.logger.warning(f"Sub-agent {job_id} announce requeued: {r.get('error')}")
                    elif status == "max_retries_exceeded":
                        self.logger.error(f"Sub-agent {job_id} announce failed: max retries")

            # Update progress for running sub-agents
            self._update_running_subagents_progress()

            # Check for stale sub-agents (running > 30 minutes)
            stale = get_stale_subagents(max_age_minutes=30)
            for s in stale:
                job_id = s["job_id"]
                age = s["age_minutes"]
                self.logger.warning(f"Sub-agent {job_id} is stale ({age:.0f} min), marking as failed")
                fail_subagent(job_id, f"Exceeded timeout (running for {age:.0f} minutes)")

        except Exception as e:
            self.logger.error(f"Error checking sub-agent announces: {e}")

    def _update_running_subagents_progress(self):
        """Update progress messages for running sub-agents."""
        try:
            active = get_active_subagents()
            if not active:
                return

            bot_token, chat_id, _ = get_telegram_config(self.config)
            if not bot_token or not chat_id:
                return

            now = datetime.now(timezone.utc)

            for job_id, subagent in active.items():
                if subagent.get("status") != "running":
                    continue

                message_id = subagent.get("status_message_id")
                if not message_id:
                    continue

                # Calculate age
                started_at = subagent.get("started_at")
                if not started_at:
                    continue

                try:
                    start = datetime.fromisoformat(started_at)
                    age_seconds = (now - start).total_seconds()
                    age_str = format_duration(age_seconds)
                except (ValueError, TypeError):
                    age_str = "?"

                # Read output and parse activity
                output = get_subagent_output(job_id)
                activity = parse_current_activity(output) if output else "Starting..."

                # Format new message
                job = subagent.get("job", {})
                new_text = format_progress_message(job_id, job, age_str, activity)

                # Edit message
                success = edit_telegram_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=new_text,
                    parse_mode="HTML"
                )

                if success:
                    update_progress_timestamp(job_id)

        except Exception as e:
            self.logger.error(f"Error updating sub-agent progress: {e}")

    def _reload_jobs(self):
        """Reload jobs from file and update scheduler."""
        old_job_ids = {job["id"] for job in self.jobs if job.get("enabled", True)}

        # Load new jobs
        self.load_jobs()
        new_job_ids = {job["id"] for job in self.jobs if job.get("enabled", True)}

        # Find added, removed, and existing jobs
        added = new_job_ids - old_job_ids
        removed = old_job_ids - new_job_ids

        # Remove jobs that are no longer in config or disabled
        for job_id in removed:
            try:
                self.scheduler.remove_job(job_id)
                self.logger.info(f"Removed job: {job_id}")
            except Exception:
                pass

        # Re-schedule all jobs (replace_existing=True handles updates)
        for job in self.jobs:
            if not job.get("enabled", True):
                # Remove if it exists and is now disabled
                try:
                    self.scheduler.remove_job(job["id"])
                    self.logger.info(f"Disabled job: {job['id']}")
                except Exception:
                    pass
                continue

            schedule = job.get("schedule", {})
            schedule_type = schedule.get("type")
            trigger = None

            if schedule_type == "every":
                kwargs = {}
                if "interval_minutes" in schedule:
                    kwargs["minutes"] = schedule["interval_minutes"]
                elif "interval_hours" in schedule:
                    kwargs["hours"] = schedule["interval_hours"]
                elif "interval_days" in schedule:
                    kwargs["days"] = schedule["interval_days"]
                trigger = IntervalTrigger(**kwargs)
            elif schedule_type == "cron":
                cron_expr = schedule.get("cron")
                if cron_expr:
                    trigger = CronTrigger.from_crontab(cron_expr)
            elif schedule_type == "at":
                dt_str = schedule.get("datetime")
                if dt_str:
                    try:
                        run_date = datetime.fromisoformat(dt_str)
                        trigger = DateTrigger(run_date=run_date)
                    except (ValueError, TypeError):
                        self.logger.warning(f"Invalid datetime for job: {dt_str}")

            if trigger:
                self.scheduler.add_job(
                    func=self._execute_job,
                    trigger=trigger,
                    args=[job],
                    id=job["id"],
                    name=job.get("name", job["id"]),
                    replace_existing=True
                )
                if job["id"] in added:
                    self.logger.info(f"Added new job: {job['id']}")

        self.logger.info(f"Jobs reloaded: {len(new_job_ids)} active")

    def _detect_and_alert_crash(self):
        """Detect if previous instance crashed (no graceful shutdown) and alert."""
        try:
            last_start = self.state.get("daemon_start_time")
            last_shutdown = self.state.get("last_shutdown")

            if not last_start:
                return

            start_dt = datetime.fromisoformat(last_start)

            # If no shutdown recorded, or shutdown is before start = crash
            crashed = False
            if not last_shutdown:
                crashed = True
            else:
                shutdown_dt = datetime.fromisoformat(last_shutdown)
                if shutdown_dt < start_dt:
                    crashed = True

            if not crashed:
                return

            # Find which jobs were running when crash happened
            running_jobs = []
            for job_id, status in self.state.get("jobs_status", {}).items():
                if status.get("status") in ("catching_up", "started"):
                    running_jobs.append(job_id)

            crash_info = f"Jobs running at crash: {', '.join(running_jobs)}" if running_jobs else "No jobs were tracked as running"

            self.logger.warning(f"CRASH DETECTED: Previous instance started at {last_start} but never shut down gracefully. {crash_info}")

            msg = f"CRON Scheduler crash detected\n\nPrevious start: {last_start}\n{crash_info}\nRestarting now..."
            send_feed(msg, topic="Alerts")
        except Exception as e:
            self.logger.warning(f"Error in crash detection: {e}")

    def _send_startup_notification(self):
        """Send startup notification via feed (rate-limited to once per 10 min)."""
        try:
            # Rate-limit: skip if last startup was < 10 min ago
            last_start = self.state.get("daemon_start_time")
            if last_start:
                last_dt = datetime.fromisoformat(last_start)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed < 600:
                    self.logger.info(f"Startup notification suppressed (last start {elapsed:.0f}s ago)")
                    return

            msg = f"CRON Scheduler started\n{len(self.jobs)} jobs loaded"
            send_feed(msg, topic="Alerts")
            self.logger.info("Startup notification sent")
        except Exception as e:
            self.logger.warning(f"Failed to send startup notification: {e}")

    def start(self):
        """Start the scheduler daemon."""
        self.logger.info("CRON Scheduler starting...")

        # Setup signal handlers FIRST - before any blocking operations
        # Previously these were set up AFTER catch-up, so SIGTERM during
        # catch-up would use default handler (SystemExit with no logging).
        import signal
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        # Trap additional signals for debugging mysterious crashes
        for sig in (signal.SIGHUP, signal.SIGPIPE, signal.SIGALRM,
                     signal.SIGUSR1, signal.SIGUSR2, signal.SIGXCPU,
                     signal.SIGXFSZ, signal.SIGVTALRM, signal.SIGPROF):
            try:
                signal.signal(sig, self._handle_debug_signal)
            except (OSError, ValueError):
                pass

        # Register atexit handler for crash debugging
        import atexit
        atexit.register(self._atexit_handler)

        # Start permanent caffeinate BEFORE any subprocesses.
        # macOS App Nap / power management sends SIGTERM to background processes.
        # Previously caffeinate was per-job with -w PID, but there was a race window:
        # SDK spawns claude subprocess immediately inside the thread, while caffeinate
        # only started after run_detached() returned. A 7-second kill was observed.
        try:
            self._caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-i", "-s"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.logger.info(f"Permanent caffeinate started (PID {self._caffeinate_proc.pid})")
        except Exception as e:
            self.logger.warning(f"Failed to start permanent caffeinate: {e}")

        # Load jobs
        self.load_jobs()

        # Initialize main session
        if self.config.get("main_session", {}).get("enabled", False):
            self.logger.info("Initializing main session...")
            init_main_session(self.config)

        # Initialize sub-agent system if enabled
        if self.config.get("subagents", {}).get("enabled", False):
            self.logger.info("Initializing sub-agent system...")
            init_subagent_state(self.config)
            init_announce_handler(self.config)
            # Recover any crashed sub-agents
            recoveries = recover_crashed_subagents()
            if recoveries:
                self.logger.info(f"Recovered {len(recoveries)} crashed sub-agents")

        # Recover orphaned foreground jobs from previous daemon instance
        self._recover_foreground_jobs()

        # Detect crash: if previous daemon_start_time > last_shutdown, process was killed
        self._detect_and_alert_crash()

        # Update daemon_start_time BEFORE notification (for rate-limiting)
        self.state["daemon_start_time"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        # Send startup notification (rate-limited)
        self._send_startup_notification()

        # Write healthcheck BEFORE catch-up and start background refresh thread.
        # The external watchdog (cron-watchdog.py) checks /tmp/cron-scheduler.health
        # every 5 min and kills the scheduler if it's stale (>10 min).
        # Without this, long catch-up ops cause the watchdog to kill us.
        self._write_healthcheck()
        self._start_healthcheck_thread()

        # Detect and execute missed jobs
        self.detect_missed_jobs()

        # Schedule jobs
        self.schedule_jobs()

        # Add internal healthcheck job (every 5 min)
        self.scheduler.add_job(
            func=self._write_healthcheck,
            trigger=IntervalTrigger(minutes=5),
            id="_healthcheck",
            name="Internal Healthcheck",
            replace_existing=True
        )
        self._write_healthcheck()  # Initial write

        # Add sleep/wake detector (every 60s, detects gaps > 3 min)
        self.scheduler.add_job(
            func=self._check_sleep_wake,
            trigger=IntervalTrigger(seconds=60),
            id="_sleep_wake_detector",
            name="Sleep/Wake Detector",
            replace_existing=True
        )

        # Add connectivity monitor (every 60s, detects offline/online transitions)
        self.scheduler.add_job(
            func=self._monitor_connectivity,
            trigger=IntervalTrigger(seconds=60),
            id="_connectivity_monitor",
            name="Connectivity Monitor",
            replace_existing=True
        )

        # Add jobs.json hot-reload check (every 1 min)
        self.scheduler.add_job(
            func=self._check_jobs_reload,
            trigger=IntervalTrigger(minutes=1),
            id="_jobs_reload",
            name="Jobs Hot-Reload Check",
            replace_existing=True
        )
        self.jobs_file_mtime = self.jobs_file.stat().st_mtime  # Initial mtime

        # Add sub-agent announce checker (every 30 sec) if enabled
        if self.config.get("subagents", {}).get("enabled", False):
            self.scheduler.add_job(
                func=self._check_subagent_announces,
                trigger=IntervalTrigger(seconds=30),
                id="_subagent_checker",
                name="Sub-agent Announce Checker",
                replace_existing=True
            )

        self.logger.info("CRON Scheduler running...")

        # Start scheduler (blocking)
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self._graceful_shutdown()

    def _handle_debug_signal(self, signum, frame):
        """Log unexpected signals for debugging mysterious crashes."""
        import traceback
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        self.logger.warning(f"UNEXPECTED SIGNAL: {sig_name} ({signum})")
        self.logger.warning(f"Stack trace:\n{''.join(traceback.format_stack(frame))}")

    def _atexit_handler(self):
        """Log when process exits for any reason (debugging crashes)."""
        # This won't fire on SIGKILL but will fire on normal exit, SystemExit, etc.
        self.logger.warning(f"ATEXIT: Process exiting. PID={os.getpid()}")

    def _handle_shutdown(self, signum, frame):
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._graceful_shutdown()
        sys.exit(0)

    def _graceful_shutdown(self):
        """Perform graceful shutdown tasks."""
        self.logger.info("CRON Scheduler stopping...")

        # Save current state
        self.state["last_shutdown"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        # Sub-agents will continue running - their state is persisted
        # They will be recovered on next startup

        # Foreground jobs (detached Claude CLI processes) will also continue
        # running - they write output to files, not pipes. Recovered on restart.
        running = self.state.get("running_foreground_jobs", {})
        if running:
            self.logger.info(
                f"Shutdown with {len(running)} foreground jobs still running: "
                f"{list(running.keys())}. Will recover on restart."
            )

        # Stop permanent caffeinate
        if self._caffeinate_proc and self._caffeinate_proc.poll() is None:
            self._caffeinate_proc.terminate()
            try:
                self._caffeinate_proc.wait(timeout=5)
            except Exception:
                self._caffeinate_proc.kill()
            self.logger.info("Permanent caffeinate stopped")

        # Shutdown scheduler
        try:
            self.scheduler.shutdown(wait=False)
        except Exception as e:
            self.logger.error(f"Error during scheduler shutdown: {e}")

        self.logger.info("CRON Scheduler stopped")


def acquire_lock():
    """Acquire file lock to ensure single instance."""
    lock_file = Path("/tmp/cron-scheduler.lock")

    try:
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd
    except IOError:
        print("Another instance is already running", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point."""
    # Ensure single instance
    lock_fd = acquire_lock()

    # Load config
    config_path = _cfg.DEFAULT_CONFIG_PATH

    # Start scheduler
    manager = JobManager(str(config_path))
    manager.start()

    # Release lock on exit
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()


if __name__ == "__main__":
    main()
