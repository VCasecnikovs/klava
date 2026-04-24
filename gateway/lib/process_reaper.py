"""Process reaper - kills orphaned Claude SDK child processes.

The Claude Agent SDK spawns subprocess trees (claude binary + MCP servers).
These can survive after the SDK session completes because:
1. receive_messages() may not terminate after ResultMessage
2. transport.close() sends SIGTERM but process ignores it
3. anyio task group cleanup can hang

This module provides:
- kill_sdk_subprocess(): Force-kill the subprocess behind a ClaudeSDKClient
- reap_orphaned_children(): Find and kill zombie claude children of a parent PID
- start_reaper_thread(): Periodic background reaper (every 60s)
"""

import logging
import os
import signal
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# Patterns that identify SDK-spawned claude processes in ps output
SDK_PROCESS_PATTERNS = (
    "claude_agent_sdk/_bundled/claude",
    ".local/bin/claude",
    "/claude",  # Catch various install paths
)


def kill_sdk_subprocess(client, timeout=3.0):
    """Force-kill the OS subprocess behind a ClaudeSDKClient instance.

    This reaches into the SDK internals to find and SIGKILL the actual
    process, since SIGTERM via transport.close() is unreliable.

    Args:
        client: ClaudeSDKClient instance
        timeout: seconds to wait for process to die after SIGKILL
    """
    if client is None:
        return

    proc = None
    # Navigate SDK internals: client._query.transport._process
    query_obj = getattr(client, "_query", None)
    if query_obj:
        transport = getattr(query_obj, "transport", None)
        if transport:
            proc = getattr(transport, "_process", None)

    if proc is None:
        return

    pid = getattr(proc, "pid", None)
    returncode = getattr(proc, "returncode", None)

    if pid and returncode is None:
        try:
            # Kill the entire process group to take out MCP servers too
            pgid = os.getpgid(pid)
            my_pgid = os.getpgid(os.getpid())
            if pgid != my_pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
            logger.info(f"Killed SDK subprocess PID {pid}")
        except (ProcessLookupError, PermissionError, OSError) as e:
            logger.debug(f"SDK subprocess PID {pid} already dead or inaccessible: {e}")


def reap_orphaned_children(parent_pid=None, max_age_seconds=1800):
    """Find and kill orphaned claude child processes.

    Single `ps` call to find all claude processes whose PPID matches
    parent_pid and that exceed max_age_seconds. Replaces unreliable
    pgrep -P approach that missed processes on macOS.

    Args:
        parent_pid: PID to scan children of (default: os.getpid())
        max_age_seconds: kill processes older than this (default: 30min)

    Returns:
        int: number of processes killed
    """
    if parent_pid is None:
        parent_pid = os.getpid()

    killed = 0
    my_pid = os.getpid()
    my_pgid = os.getpgid(my_pid)

    try:
        # Single ps call - get all processes with PID, PPID, elapsed time, command
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,etime=,comm="],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0

        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Parse: PID PPID ETIME COMMAND
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue

            try:
                pid = int(parts[0])
                ppid = int(parts[1])
                etime_str = parts[2]
                comm = parts[3]
            except (ValueError, IndexError):
                continue

            # Skip non-children and non-claude processes
            if ppid != parent_pid:
                continue
            if pid == my_pid:
                continue
            if not any(pat in comm for pat in SDK_PROCESS_PATTERNS):
                continue

            elapsed = _parse_etime(etime_str)
            if elapsed is None or elapsed <= max_age_seconds:
                continue

            # Kill it
            try:
                try:
                    pgid = os.getpgid(pid)
                    if pgid != my_pgid:
                        os.killpg(pgid, signal.SIGKILL)
                    else:
                        os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
                killed += 1
                logger.warning(
                    f"Reaped orphaned claude process PID {pid} "
                    f"(age: {elapsed}s, max: {max_age_seconds}s)"
                )
            except (OSError, ProcessLookupError):
                pass

    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Reaper scan failed: {e}")

    return killed


def _parse_etime(etime_str):
    """Parse ps etime format ([[DD-]HH:]MM:SS) to seconds.

    Examples: "00:05" -> 5, "01:30" -> 90, "01:01:30" -> 3690, "1-00:00:00" -> 86400
    """
    try:
        days = 0
        if "-" in etime_str:
            day_part, etime_str = etime_str.split("-", 1)
            days = int(day_part)

        parts = etime_str.split(":")
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            h, m, s = 0, int(parts[0]), int(parts[1])
        else:
            return None

        return days * 86400 + h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None


def start_reaper_thread(parent_pid=None, interval=60, max_age_seconds=1800):
    """Start a background daemon thread that periodically reaps orphaned children.

    Args:
        parent_pid: PID to scan (default: os.getpid())
        interval: seconds between scans (default: 60)
        max_age_seconds: kill processes older than this (default: 30min)
    """
    if parent_pid is None:
        parent_pid = os.getpid()

    def _reaper_loop():
        while True:
            time.sleep(interval)
            try:
                killed = reap_orphaned_children(parent_pid, max_age_seconds)
                if killed:
                    logger.info(f"Reaper: killed {killed} orphaned claude process(es)")
            except Exception as e:
                logger.debug(f"Reaper error: {e}")

    thread = threading.Thread(target=_reaper_loop, daemon=True, name="process-reaper")
    thread.start()
    logger.info(f"Process reaper started (interval={interval}s, max_age={max_age_seconds}s)")
    return thread
