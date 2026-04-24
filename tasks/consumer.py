#!/usr/bin/env python3
"""Klava task consumer - processes tasks from GTasks queue.

Runs as a CRON job. Checks the Klava GTasks list for pending tasks,
spawns Claude sessions to execute them, and reports results.

Usage:
    cd ~/Documents/GitHub/claude && python3 -m tasks.consumer
"""

import sys
import os
import fcntl
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone, timedelta

# Add project paths
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT))

from tasks.queue import (
    list_tasks, get_pending, get_running,
    update_task_notes, complete_task, Task,
    find_pending_proposal,
    create_result,
    convert_to_result, convert_to_proposal,
    STALE_TIMEOUT_MINUTES,
)
from lib.claude_executor import ClaudeExecutor
from lib.feed import send_feed
from lib import subagent_state

from tasks import idle_research

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Task execution config
DEFAULT_MODEL = "opus"
TASK_TIMEOUT = 3600  # 1 hour for all tasks

# Process-level lock: pins the critical section (list/claim/execute) to one
# consumer at a time. Two overlapping cron invocations would otherwise both
# call list_tasks(), see the same top-pending row, and race to mark_running()
# — producing duplicate [RESULT] cards and duplicate downstream artifacts.
# The dashboard's _launch_klava() takes the same lock to close the
# dashboard-vs-cron race that the pure cron-vs-cron flock missed.
# Regression: 2026-04-19 Milan Czerny + ENGY dex_pay duplicate executions.
CONSUMER_LOCK_PATH = Path("/tmp/klava-consumer.lock")


class KlavaLaunchContention(RuntimeError):
    """Raised when a dashboard-side Klava launch cannot take the consumer lock.

    Callers (dashboard routes) should translate this into a 409 so the UI can
    surface a retry toast instead of silently double-spawning.
    """


@contextmanager
def consumer_lock(path: Optional[Path] = None):
    """Non-blocking exclusive flock on a lock file.

    Yields True if this process acquired the lock, False if another consumer
    holds it. Always releases the lock on exit. The lock is advisory (flock),
    kernel-scoped to the file's inode, so it works across subprocesses on the
    same machine but not across NFS.

    Resolves `path` from the module-level `CONSUMER_LOCK_PATH` at call time
    (not as a default arg) so tests monkeypatching that constant work.
    """
    if path is None:
        path = CONSUMER_LOCK_PATH
    lock_fd = None
    acquired = False
    try:
        lock_fd = os.open(str(path), os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        if acquired:
            try:
                os.ftruncate(lock_fd, 0)
                os.write(lock_fd, f"{os.getpid()}\n".encode())
            except OSError:
                pass
        yield acquired
    finally:
        if lock_fd is not None:
            if acquired:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                os.close(lock_fd)
            except OSError:
                pass


def is_stale(task: Task, timeout_minutes: int = STALE_TIMEOUT_MINUTES) -> bool:
    """Check if a running task has been running too long."""
    if not task.started_at:
        return True
    try:
        started = datetime.fromisoformat(task.started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - started
        return elapsed > timedelta(minutes=timeout_minutes)
    except (ValueError, TypeError):
        return True


EXECUTOR_SKILL_PATH = ROOT / ".claude" / "skills" / "executor" / "SKILL.md"

_EXECUTOR_FALLBACK = """\
You are a spawned Klava consumer session. Execute the task below autonomously \
and emit a FINAL message shaped as a `[RESULT]` card on the user's Deck.

Structure: `## What was done` / `## Key findings` / `## Artifacts` / \
`## Suggested next step`. Start directly with `## What was done`. No preamble, \
no questions, no permission-seeking. ~800-1500 chars of signal.
"""


def _load_executor_doctrine() -> str:
    """Load the executor skill body (doctrine), stripped of YAML frontmatter.

    Tier-1 hot-reload: edits to the SKILL.md land on the next run. Falls back
    to a compact inline prompt if the file is missing or unreadable so a
    broken skill file never bricks the consumer.
    """
    try:
        raw = EXECUTOR_SKILL_PATH.read_text(encoding="utf-8")
    except OSError as e:
        log.warning(f"executor skill unreadable ({e}); using fallback doctrine")
        return _EXECUTOR_FALLBACK

    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return raw


def build_task_prompt(task: Task) -> str:
    """Build the Claude prompt for executing a task.

    Format: doctrine (from executor SKILL.md) + concrete task payload.
    The doctrine lives in a skill file so it's hot-reloadable and
    co-edited with the rest of the skill library.
    """
    doctrine = _load_executor_doctrine()

    payload = [f"**Task:** {task.title}", f"**Priority:** {task.priority}"]
    if task.parent_id:
        payload.append("**Note:** subtask of a larger task.")
    if task.body:
        payload.append("")
        payload.append("**Details:**")
        payload.append(task.body)

    return (
        doctrine.rstrip()
        + "\n\n---\n\n## This task\n\n"
        + "\n".join(payload)
        + "\n"
    )


def execute_task(task: Task) -> dict:
    """Spawn a Claude session to execute the task."""
    executor = ClaudeExecutor(log_callback=log.info)

    prompt = build_task_prompt(task)
    timeout = TASK_TIMEOUT

    resume_sid = task.resume_session_id
    if resume_sid:
        log.info(f"Resuming session {resume_sid[:12]}… for continuation ({task.continue_mode})")

    result = executor.run(
        prompt=prompt,
        mode="isolated",
        model=DEFAULT_MODEL,
        timeout=timeout,
        skip_permissions=True,
        resume_session_id=resume_sid,
        add_dirs=[
            p.strip() for p in os.environ.get(
                "EXECUTOR_ADD_DIRS",
                f"{os.environ.get('OBSIDIAN_VAULT', '~/Documents/MyBrain')}:~/Documents/GitHub/claude",
            ).split(":") if p.strip()
        ],
    )

    return result


def mark_running(task: Task) -> None:
    """Update task status to running."""
    task.status = "running"
    task.started_at = datetime.now(timezone.utc).isoformat()
    update_task_notes(task.id, task.to_notes())


def mark_done(task: Task, result: dict) -> None:
    """Convert the finished task into a [RESULT] or [PROPOSAL] card in place.

    The Deck UX is "one card evolves" — the source disappears when the
    Delegate/Proposal button is clicked, the dispatched `[ACTION]` /
    `[RESEARCH]` row takes its spot, and on completion that same GTask id
    morphs into the result or proposal. No second card is emitted.

    Routing by title prefix:
      - `[RESEARCH] ...` -> convert_to_proposal (Deck's Proposal button)
      - everything else  -> convert_to_result   (Deck's Delegate + all
                                                 other consumer-run tasks)

    Failures fall back to the old create_result + complete_task flow so a
    transient GTasks hiccup can't leave a finished task permanently stuck
    in `running`.
    """
    session_id = result.get("session_id")
    output = result.get("result", "") or ""

    if not output:
        # Nothing to publish — just close the task.
        task.status = "done"
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.session_id = session_id
        update_task_notes(task.id, task.to_notes())
        complete_task(task.id)
        return

    # GTasks notes cap around 8 KB. Give the card most of that budget.
    card_body = output if len(output) <= 7500 else output[:7500] + "\n...(truncated)"
    mode_tags = [t.strip() for t in (task.mode_tags or "").split(",") if t.strip()]
    is_proposal_dispatch = task.title.startswith("[RESEARCH]")

    try:
        if is_proposal_dispatch:
            convert_to_proposal(
                task_id=task.id,
                title=task.title,
                plan=card_body,
                shape=task.shape,
                mode_tags=mode_tags or None,
                session_id=session_id,
            )
        else:
            convert_to_result(
                task_id=task.id,
                title=task.title,
                body=card_body,
                mode_tags=mode_tags or None,
                session_id=session_id,
            )
        return
    except Exception as e:
        log.warning(
            f"convert_to_{'proposal' if is_proposal_dispatch else 'result'} "
            f"failed for {task.id}: {e} — falling back to legacy flow"
        )

    # Legacy fallback: complete the task and emit a separate [RESULT] card.
    task.status = "done"
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.session_id = session_id
    parent_body = output if len(output) <= 2000 else output[:2000] + "\n...(truncated)"
    task.body = (task.body + f"\n\n## Result\n{parent_body}").strip()
    update_task_notes(task.id, task.to_notes())
    complete_task(task.id)
    try:
        create_result(
            parent_task_id=task.id,
            title=task.title,
            body=card_body,
            shape=task.shape,
            mode_tags=mode_tags or None,
            priority="low",
            source="consumer",
            session_id=session_id,
        )
    except Exception as e:
        log.warning(f"Failed to emit [RESULT] card for {task.id}: {e}")


def mark_failed(task: Task, error: str) -> None:
    """Update task status to failed."""
    task.status = "failed"
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.body = (task.body + f"\n\n## Error\n{error}").strip()
    try:
        update_task_notes(task.id, task.to_notes())
    except Exception as e:
        log.warning(f"Failed to persist mark_failed for {task.id} (will retry next run): {e}")


def _idle_branch(tasks: list) -> dict:
    """Handle an empty-queue tick.

    Decision tree:
      1. Active subagents running?            → skip (don't pile on).
      2. A [PROPOSAL] already pending?        → skip (wait for the user).
      3. Rate limit (1/hour) hit?             → skip.
      4. Otherwise spawn idle-research.

    Returns an action dict matching the main loop's contract.
    """
    # (1) active subagents
    try:
        active = subagent_state.get_active_subagents()
        if active:
            log.info(f"idle: subagents active ({len(active)}), skipping idle-research")
            return {"action": "idle", "reason": "subagents_active"}
    except Exception as e:
        # Non-fatal: if we can't read state, err on the side of not spawning
        log.warning(f"idle: could not read subagent state: {e} — skipping idle-research")
        return {"action": "idle", "reason": "subagent_state_unreadable"}

    # (2) existing pending proposal
    pending_proposal = find_pending_proposal(tasks)
    if pending_proposal is not None:
        log.info(f"idle: proposal already pending ({pending_proposal.id}) — skipping")
        return {"action": "idle", "reason": "proposal_pending", "proposal_id": pending_proposal.id}

    # (3) rate limit
    if idle_research.rate_limited():
        log.info("idle: rate-limited (1/hour), skipping idle-research")
        return {"action": "idle", "reason": "rate_limited"}

    # (4) fire idle-research
    log.info("idle: spawning idle-research session")
    try:
        result = idle_research.run_idle_research()
    except Exception as e:
        log.error(f"idle-research failed to start: {e}")
        return {"action": "idle", "reason": "idle_research_error", "error": str(e)}

    if result.get("error"):
        log.error(f"idle-research errored: {result['error']}")
        return {"action": "idle", "reason": "idle_research_errored", "error": result["error"]}

    return {
        "action": "proposed",
        "session_id": result.get("session_id"),
        "cost": result.get("cost", 0),
        "duration": result.get("duration", 0),
    }


def _find_source_duplicate(task: Task, tasks: list) -> Task | None:
    """Return the first OTHER non-terminal task sharing task.source_gtask_id.

    Used to guard against duplicate Klava rows pointing at the same origin
    (heartbeat retry, dashboard double-submit, agent-SDK reconnect). If the
    candidate has no source_gtask_id set, there's nothing to dedup against
    and this returns None.
    """
    src = task.source_gtask_id
    if not src:
        return None
    for t in tasks:
        if t.id == task.id:
            continue
        if t.source_gtask_id != src:
            continue
        if t.status in ("done", "failed", "skipped"):
            continue
        if t.gtask_status == "completed":
            continue
        return t
    return None


def _pick_next_task(pending: list, all_tasks: list) -> tuple[Task | None, Task | None]:
    """Pick the highest-priority pending task that isn't a duplicate.

    Returns (task_to_run, blocking_duplicate_if_any). If every candidate has
    a non-terminal peer sharing source_gtask_id, returns (None, last_blocker)
    so the caller can log which source is blocking this tick.
    """
    blocker = None
    for candidate in pending:
        dup = _find_source_duplicate(candidate, all_tasks)
        if dup is None:
            return candidate, None
        blocker = dup
    return None, blocker


def check_and_execute() -> dict:
    """Main consumer loop. Check queue and execute one task.

    Wrapped in a process-level flock so overlapping cron invocations cannot
    both enter the list/claim/execute critical section. Returns dict
    describing action taken.
    """
    with consumer_lock() as acquired:
        if not acquired:
            log.info("Another consumer holds the lock; skipping this tick")
            return {"action": "locked_by_peer"}
        return _check_and_execute_locked()


def _check_and_execute_locked() -> dict:
    """Inner loop, only reached while holding `consumer_lock()`."""
    try:
        tasks = list_tasks()
    except Exception as e:
        log.error(f"Failed to read queue: {e}")
        return {"action": "error", "error": str(e)}

    if not tasks:
        log.info("Queue empty — considering idle-research")
        return _idle_branch(tasks)

    # Check for running task (lock)
    running = get_running(tasks)
    if running:
        if is_stale(running):
            log.warning(f"Stale task: {running.title} (started {running.started_at})")
            mark_failed(running, f"Timed out after {STALE_TIMEOUT_MINUTES} minutes")
            send_feed(
                f"<b>Task timed out:</b> {running.title}\nStarted: {running.started_at}",
                topic="Alerts", parse_mode="HTML", job_id="task-consumer",
            )
            return {"action": "stale_recovered", "task_id": running.id}
        else:
            log.info(f"Task running: {running.title} (started {running.started_at})")
            return {"action": "locked", "task_id": running.id}

    # Get pending tasks
    pending = get_pending(tasks)
    if not pending:
        log.info("No pending tasks")
        return _idle_branch(tasks)

    # Source-GTask dedup: walk pending in priority order, skip any task whose
    # source_gtask_id is already claimed by a non-terminal peer.
    task, blocker = _pick_next_task(pending, tasks)
    if task is None:
        src = blocker.source_gtask_id if blocker else "?"
        peer = blocker.id if blocker else "?"
        log.info(f"All pending tasks deduped against non-terminal peers (source={src}, peer={peer})")
        return {
            "action": "dup_source",
            "source_gtask_id": src,
            "blocking_task_id": peer,
        }
    log.info(f"Executing: {task.title} (priority: {task.priority})")

    # Mark as running
    try:
        mark_running(task)
    except Exception as e:
        log.error(f"Failed to mark running: {e}")
        return {"action": "error", "error": str(e)}

    # Execute
    try:
        result = execute_task(task)
    except Exception as e:
        log.error(f"Execution failed: {e}")
        mark_failed(task, str(e))
        return {"action": "error", "task_id": task.id, "error": str(e)}

    # Check result
    if result.get("error"):
        log.error(f"Task failed: {result['error']}")
        mark_failed(task, result["error"])
        return {"action": "failed", "task_id": task.id, "error": result["error"]}

    # Success — result lands on the Deck as a [RESULT] card via mark_done().
    # Feed/TG notification skipped by design: the user reads the Deck, not the Lifeline.
    log.info(f"Completed: {task.title}")
    mark_done(task, result)

    return {
        "action": "executed",
        "task_id": task.id,
        "session_id": result.get("session_id"),
        "cost": result.get("cost", 0),
        "duration": result.get("duration", 0),
    }


def main():
    """Entry point for CRON execution."""
    os.environ.pop("CLAUDECODE", None)

    result = check_and_execute()

    action = result.get("action", "unknown")
    if action == "idle":
        reason = result.get("reason", "empty")
        print(f"TASK_CONSUMER_OK: idle ({reason})")
    elif action == "proposed":
        print(
            f"TASK_CONSUMER_OK: proposal generated | "
            f"cost=${result.get('cost', 0):.2f} | {result.get('duration', 0):.0f}s"
        )
    elif action == "locked":
        print(f"TASK_CONSUMER_OK: task running ({result.get('task_id', '?')})")
    elif action == "locked_by_peer":
        print("TASK_CONSUMER_OK: peer consumer holds lock")
    elif action == "dup_source":
        src = result.get("source_gtask_id", "?")
        peer = result.get("blocking_task_id", "?")
        print(f"TASK_CONSUMER_OK: skipped duplicate source {src} (peer={peer})")
    elif action == "executed":
        print(f"Task completed: {result.get('task_id')} | cost=${result.get('cost', 0):.2f} | {result.get('duration', 0):.0f}s")
    elif action == "stale_recovered":
        print(f"Recovered stale task: {result.get('task_id')}")
    elif action in ("failed", "error"):
        error_msg = result.get("error", "?")
        # Usage limit is transient — treat as no-work-available to avoid tripping circuit breaker
        if "hit your limit" in error_msg or "You've hit your limit" in error_msg:
            print(f"TASK_CONSUMER_OK: paused (usage limit — {error_msg})")
        else:
            print(f"Task {action}: {error_msg}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
