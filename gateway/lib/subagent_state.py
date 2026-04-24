"""
Sub-agent State Management for Claude Gateway

Manages persistent state for async sub-agents:
- Active sub-agents tracking
- Pending announce queue
- Recovery after crashes
"""

import json
import os
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

from . import config as _cfg

# Default paths - will be loaded from config (init_subagent_state can override)
STATE_FILE: Path = _cfg.cron_dir() / "subagents_state.json"
OUTPUT_DIR: Path = Path("/tmp/claude_subagents")


def init_subagent_state(config: dict):
    """Initialize sub-agent state settings from config"""
    global STATE_FILE, OUTPUT_DIR

    subagents_config = config.get("subagents", {})

    state_file = subagents_config.get("state_file")
    if state_file:
        STATE_FILE = Path(os.path.expanduser(state_file))

    output_dir = subagents_config.get("output_dir")
    if output_dir:
        OUTPUT_DIR = Path(output_dir)

    # Ensure directories exist
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    """Load sub-agent state from file"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "active": {},
        "pending_announces": [],
        "last_updated": None
    }


def save_state(state: dict):
    """Save sub-agent state to file (atomic via tmp + rename)"""
    state["last_updated"] = datetime.now().isoformat()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(str(tmp), str(STATE_FILE))


def register_subagent(job_id: str, job: dict, origin_topic: int, pid: int = None, session_id: str = None) -> dict:
    """Register a new sub-agent as active"""
    state = load_state()

    output_file = OUTPUT_DIR / f"{job_id}.out"
    result_file = OUTPUT_DIR / f"{job_id}.result.json"

    subagent = {
        "job_id": job_id,
        "job": job,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "origin_topic": origin_topic,
        "pid": pid,
        "session_id": session_id,
        "output_file": str(output_file),
        "result_file": str(result_file),
        "retries": 0,
        "status_message_id": None,  # For live progress updates
        "last_progress_update": None
    }

    state["active"][job_id] = subagent
    save_state(state)

    return subagent


def update_subagent_status(job_id: str, status: str, pid: int = None):
    """Update sub-agent status"""
    state = load_state()

    if job_id in state["active"]:
        state["active"][job_id]["status"] = status
        if pid:
            state["active"][job_id]["pid"] = pid
        state["active"][job_id]["updated_at"] = datetime.now().isoformat()
        save_state(state)


def set_status_message_id(job_id: str, message_id: int):
    """Set the Telegram message ID for live progress updates"""
    state = load_state()

    if job_id in state["active"]:
        state["active"][job_id]["status_message_id"] = message_id
        save_state(state)


def update_progress_timestamp(job_id: str):
    """Update last progress timestamp"""
    state = load_state()

    if job_id in state["active"]:
        state["active"][job_id]["last_progress_update"] = datetime.now().isoformat()
        save_state(state)


def complete_subagent(job_id: str, result: dict) -> dict:
    """Mark sub-agent as complete and move to pending announces"""
    state = load_state()

    if job_id not in state["active"]:
        return None

    subagent = state["active"].pop(job_id)
    subagent["status"] = "completed"
    subagent["completed_at"] = datetime.now().isoformat()
    subagent["result"] = result

    # Add to pending announces
    state["pending_announces"].append({
        "job_id": job_id,
        "subagent": subagent,
        "result": result,
        "announce_at": datetime.now().isoformat(),
        "retries": 0
    })

    save_state(state)
    return subagent


def fail_subagent(job_id: str, reason: str) -> dict:
    """Mark sub-agent as failed"""
    state = load_state()

    if job_id not in state["active"]:
        return None

    subagent = state["active"].pop(job_id)
    subagent["status"] = "failed"
    subagent["failed_at"] = datetime.now().isoformat()
    subagent["failure_reason"] = reason

    # Add failure to pending announces so user knows
    state["pending_announces"].append({
        "job_id": job_id,
        "subagent": subagent,
        "result": {"status": "failed", "error": reason},
        "announce_at": datetime.now().isoformat(),
        "retries": 0
    })

    save_state(state)
    return subagent


def get_active_subagents() -> dict:
    """Get all active sub-agents"""
    state = load_state()
    return state.get("active", {})


def get_pending_announces() -> list:
    """Get pending announce queue"""
    state = load_state()
    return state.get("pending_announces", [])


def pop_pending_announce() -> Optional[dict]:
    """Pop next pending announce from queue"""
    state = load_state()

    if state["pending_announces"]:
        announce = state["pending_announces"].pop(0)
        save_state(state)
        return announce

    return None


def requeue_announce(announce: dict):
    """Re-queue a failed announce for retry"""
    state = load_state()
    announce["retries"] = announce.get("retries", 0) + 1
    announce["retry_at"] = datetime.now().isoformat()
    state["pending_announces"].append(announce)
    save_state(state)


def is_process_alive(pid: int) -> bool:
    """Check if a process is still running"""
    if not pid:
        return False
    # Guard against corrupt PIDs (e.g. memory addresses stored instead of PIDs)
    if not isinstance(pid, int) or pid <= 0 or pid > 2**22:  # macOS max PID ~99999
        return False
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks
        return True
    except (OSError, ProcessLookupError, OverflowError):
        return False


def get_subagent_output(job_id: str) -> Optional[str]:
    """Read output from sub-agent output file"""
    output_file = OUTPUT_DIR / f"{job_id}.out"
    if output_file.exists():
        try:
            return output_file.read_text()
        except IOError:
            pass
    return None


def get_subagent_result(job_id: str) -> Optional[dict]:
    """Read structured result from sub-agent"""
    result_file = OUTPUT_DIR / f"{job_id}.result.json"
    if result_file.exists():
        try:
            return json.loads(result_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return None


def cleanup_subagent_files(job_id: str):
    """Clean up all temporary files for a sub-agent"""
    for suffix in [".out", ".result.json", ".sh", ".pid", ".prompt"]:
        f = OUTPUT_DIR / f"{job_id}{suffix}"
        if f.exists():
            try:
                f.unlink()
            except IOError:
                pass


def get_stale_subagents(max_age_minutes: int = 30) -> list:
    """Get sub-agents that have been running too long"""
    state = load_state()
    stale = []

    for job_id, subagent in state.get("active", {}).items():
        try:
            started_at = datetime.fromisoformat(subagent.get("started_at", ""))
            age_minutes = (datetime.now() - started_at).total_seconds() / 60
        except (ValueError, TypeError):
            age_minutes = max_age_minutes + 1  # Treat unparseable as stale

        if age_minutes > max_age_minutes:
            stale.append({
                "job_id": job_id,
                "subagent": subagent,
                "age_minutes": age_minutes
            })

    return stale


def recover_crashed_subagents() -> list:
    """
    Check for crashed sub-agents and handle recovery.

    All mutations happen on one state object to avoid clobbering
    (complete_subagent/fail_subagent load their own state internally).

    Returns list of recovery actions taken.
    """
    state = load_state()
    recoveries = []

    for job_id, subagent in list(state.get("active", {}).items()):
        pid = subagent.get("pid")

        # Check if process is dead
        if pid and not is_process_alive(pid):
            output = get_subagent_output(job_id)
            result = get_subagent_result(job_id)

            if result:
                # Has result - move from active to pending announces
                completed = state["active"].pop(job_id)
                completed["status"] = "completed"
                completed["completed_at"] = datetime.now().isoformat()
                completed["result"] = result
                state["pending_announces"].append({
                    "job_id": job_id,
                    "subagent": completed,
                    "result": result,
                    "announce_at": datetime.now().isoformat(),
                    "retries": 0
                })
                recoveries.append({
                    "job_id": job_id,
                    "action": "completed_from_result",
                    "result": result
                })
            elif output:
                # Has partial output - mark as failed
                reason = f"Process died. Partial output:\n{output[:2000]}"
                failed = state["active"].pop(job_id)
                failed["status"] = "failed"
                failed["failed_at"] = datetime.now().isoformat()
                failed["failure_reason"] = reason
                state["pending_announces"].append({
                    "job_id": job_id,
                    "subagent": failed,
                    "result": {"status": "failed", "error": reason},
                    "announce_at": datetime.now().isoformat(),
                    "retries": 0
                })
                recoveries.append({
                    "job_id": job_id,
                    "action": "failed_with_output",
                    "output_length": len(output)
                })
            else:
                # No output - check retry count
                retries = subagent.get("retries", 0)
                if retries < 2:
                    state["active"][job_id]["status"] = "pending_retry"
                    state["active"][job_id]["retries"] = retries + 1
                    recoveries.append({
                        "job_id": job_id,
                        "action": "pending_retry",
                        "retry_count": retries + 1
                    })
                else:
                    # Max retries - mark failed
                    reason = "Process died without output, max retries exceeded"
                    failed = state["active"].pop(job_id)
                    failed["status"] = "failed"
                    failed["failed_at"] = datetime.now().isoformat()
                    failed["failure_reason"] = reason
                    state["pending_announces"].append({
                        "job_id": job_id,
                        "subagent": failed,
                        "result": {"status": "failed", "error": reason},
                        "announce_at": datetime.now().isoformat(),
                        "retries": 0
                    })
                    recoveries.append({
                        "job_id": job_id,
                        "action": "failed_max_retries"
                    })

    save_state(state)
    return recoveries
