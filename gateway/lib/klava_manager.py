"""Klava task session manager.

Bridges the task queue (GTasks) with the webhook-server session system.
Tasks launch as real Claude SDK sessions with streaming, AskUserQuestion, etc.
"""

import logging
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Module-level state: maps tab_id -> klava metadata for running sessions.
# Separate from CHAT_SESSIONS to avoid coupling. Checked in webhook-server
# finally block for post-completion GTasks updates.
KLAVA_TASKS = {}  # tab_id -> {"task_id", "title", "priority", "source", "body"}
_klava_lock = threading.Lock()


def register_task(tab_id: str, task_id: str, title: str,
                  priority: str = "medium", source: str = "dashboard",
                  body: str = ""):
    """Register a klava task for tracking."""
    with _klava_lock:
        KLAVA_TASKS[tab_id] = {
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "source": source,
            "body": body,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }


def pop_task(tab_id: str) -> dict | None:
    """Remove and return klava task metadata (called on session completion)."""
    with _klava_lock:
        return KLAVA_TASKS.pop(tab_id, None)


def get_task(tab_id: str) -> dict | None:
    """Get klava task metadata without removing."""
    with _klava_lock:
        return KLAVA_TASKS.get(tab_id)


def list_running() -> dict:
    """Return all currently running klava tasks."""
    with _klava_lock:
        return dict(KLAVA_TASKS)


def build_klava_prompt(title: str, body: str, priority: str) -> str:
    """Build the Claude prompt for a Klava task."""
    parts = [
        "You are executing a task from the Klava queue.",
        "",
        f"**Task:** {title}",
        f"**Priority:** {priority}",
    ]
    if body:
        parts.append("")
        parts.append("**Details:**")
        parts.append(body)

    parts.extend([
        "",
        "You have access to all tools, Obsidian vault, files, and MCP servers.",
        "Execute the task fully.",
        "",
        f"If you need clarification or a decision from the user, use AskUserQuestion.",
        "They will see your question in the dashboard and can answer it.",
        "",
        "When done, output a clear summary of what was accomplished.",
        "If the task produces files or artifacts, mention their paths.",
    ])
    return "\n".join(parts)


def complete_task(task_id: str, result_data: dict | None, error: str | None = None):
    """Update GTasks after klava task completion. Runs in background thread."""
    try:
        import sys
        from pathlib import Path
        root = Path(__file__).parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        if str(root / "gateway") not in sys.path:
            sys.path.insert(0, str(root / "gateway"))

        from tasks.queue import update_task_notes, complete_task as gtask_complete, list_tasks, Task
        from lib.feed import send_feed

        # Find the task
        tasks = list_tasks()
        task = None
        for t in tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            log.warning(f"Klava task {task_id} not found in GTasks")
            return

        now = datetime.now(timezone.utc).isoformat()

        if error:
            task.status = "failed"
            task.completed_at = now
            task.body = (task.body + f"\n\n## Error\n{error}").strip()
            update_task_notes(task.id, task.to_notes())
            send_feed(
                f"<b>Klava task failed:</b> {task.title}\n{error[:200]}",
                topic="Alerts", parse_mode="HTML", job_id="klava",
            )
        else:
            task.status = "done"
            task.completed_at = now
            task.session_id = result_data.get("session_id") if result_data else None
            cost = result_data.get("cost_usd", 0) if result_data else 0
            # Append result text to task body (extracted from session blocks)
            result_text = result_data.get("result_text", "") if result_data else ""
            if result_text:
                # GTasks notes cap around 8 KB; leave room for the existing
                # body to avoid the Deck's Result card getting chopped at 2 KB.
                if len(result_text) > 7500:
                    result_text = result_text[:7500] + "\n...(truncated)"
                task.body = (task.body + f"\n\n## Result\n{result_text}").strip()
            update_task_notes(task.id, task.to_notes())
            gtask_complete(task.id)
            send_feed(
                f"<b>Klava task done:</b> {task.title}\nCost: ${cost:.2f}",
                topic="Tasks", parse_mode="HTML", job_id="klava",
            )

    except Exception as e:
        log.error(f"Failed to complete klava task {task_id}: {e}", exc_info=True)
