"""
Sub-agent Status Display for Claude Gateway

Provides visual feedback for sub-agent operations in Telegram.
"""

import time
from datetime import datetime
from typing import Optional

from .subagent_state import get_active_subagents, get_pending_announces


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def format_spawn_notification(job_id: str, job: dict) -> str:
    """
    Format notification message when sub-agent is spawned.

    Returns HTML-formatted message for Telegram.
    """
    execution = job.get("execution", {})
    name = job.get("name", "Sub-agent")
    model = execution.get("model", "sonnet")
    timeout = execution.get("timeout_seconds", 600)

    return (
        f"🚀 <b>Sub-agent запущен</b>\n"
        f"├── Task: {name}\n"
        f"├── Model: {model}\n"
        f"├── Timeout: {timeout // 60} min\n"
        f"└── Job ID: <code>{job_id}</code>\n\n"
        f"⏳ Starting..."
    )


def parse_current_activity(output: str) -> str:
    """Parse current activity from sub-agent output file.

    Looks for spinner characters or tool indicators in recent output.
    """
    if not output:
        return "Working..."

    lines = output.strip().split('\n')

    # Look at last 30 lines for recent activity
    for line in reversed(lines[-30:]):
        line = line.strip()

        # Skip empty lines
        if not line:
            continue

        # Spinner characters indicate active tool
        spinners = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        for spinner in spinners:
            if spinner in line:
                # Extract tool name after spinner
                clean = line.replace(spinner, '').strip()
                if clean:
                    return clean[:50]

        # Tool emojis
        tool_indicators = ['📂', '✏️', '⚙️', '🔍', '🌐', '🔎', '🤖', '🎯', '❓']
        for indicator in tool_indicators:
            if indicator in line:
                return line[:50]

    return "Working..."


def format_progress_message(job_id: str, job: dict, age_str: str, activity: str) -> str:
    """Format progress message for live updates.

    Returns HTML-formatted message with current status.
    """
    execution = job.get("execution", {})
    name = job.get("name", "Sub-agent")
    model = execution.get("model", "sonnet")
    timeout = execution.get("timeout_seconds", 600)

    return (
        f"🚀 <b>Sub-agent запущен</b>\n"
        f"├── Task: {name}\n"
        f"├── Model: {model}\n"
        f"├── Timeout: {timeout // 60} min\n"
        f"└── Job ID: <code>{job_id}</code>\n\n"
        f"🔄 Working... {age_str}\n"
        f"   └── {activity}"
    )


def format_completion_notification(job_id: str, result: dict, subagent: dict = None) -> str:
    """
    Format notification message when sub-agent completes.

    Returns HTML-formatted message for Telegram.
    """
    status = result.get("status", "unknown")
    is_success = status == "completed"
    status_emoji = "✅" if is_success else "❌"

    job = subagent.get("job", {}) if subagent else {}
    name = job.get("name", "Sub-agent")

    # Calculate duration if we have timestamps
    duration_str = "N/A"
    if subagent:
        started_at = subagent.get("started_at")
        completed_at = subagent.get("completed_at") or datetime.now().isoformat()
        if started_at:
            try:
                start = datetime.fromisoformat(started_at)
                end = datetime.fromisoformat(completed_at)
                duration_str = format_duration((end - start).total_seconds())
            except (ValueError, TypeError):
                pass

    # Get cost/tokens from result if available
    tokens = result.get("tokens", "N/A")
    cost = result.get("cost", result.get("cost_usd"))
    cost_str = f"${cost:.3f}" if isinstance(cost, (int, float)) else "N/A"

    lines = [
        f"{status_emoji} <b>Sub-agent завершён</b>",
        f"├── Task: {name}",
        f"├── Status: {status_emoji} {status}",
        f"├── Duration: {duration_str}",
    ]

    if tokens != "N/A":
        lines.append(f"├── Tokens: {tokens}")
    if cost_str != "N/A":
        lines.append(f"└── Cost: {cost_str}")
    else:
        lines[-1] = lines[-1].replace("├──", "└──")

    # Add error message for failures
    if not is_success and result.get("error"):
        error_msg = str(result.get("error"))[:200]
        lines.append(f"\n⚠️ Error: {error_msg}")

    return "\n".join(lines)


def format_active_subagents_status() -> Optional[str]:
    """
    Format active sub-agents for /status display.

    Returns HTML-formatted string or None if no active agents.
    """
    active = get_active_subagents()

    if not active:
        return None

    lines = ["🤖 <b>Active Sub-agents:</b>"]
    now = datetime.now()

    for job_id, subagent in active.items():
        job = subagent.get("job", {})
        name = job.get("name", "Sub-agent")
        status = subagent.get("status", "running")

        # Calculate age
        started_at = subagent.get("started_at")
        age_str = "?"
        if started_at:
            try:
                start = datetime.fromisoformat(started_at)
                age_str = format_duration((now - start).total_seconds())
            except (ValueError, TypeError):
                pass

        # Status emoji
        if status == "running":
            emoji = "🔄"
        elif status == "pending_retry":
            emoji = "🔁"
        else:
            emoji = "⏳"

        lines.append(f"  {emoji} <i>{name}</i> ({age_str})")

        # Limit to 5 for status display
        if len(lines) > 6:
            remaining = len(active) - 5
            lines.append(f"  ... and {remaining} more")
            break

    return "\n".join(lines)


def format_pending_announces_status() -> Optional[str]:
    """
    Format pending announces for /status display.

    Returns HTML-formatted string or None if no pending.
    """
    pending = get_pending_announces()

    if not pending:
        return None

    lines = ["📢 <b>Pending Announces:</b>"]

    for item in pending[:3]:
        job_id = item.get("job_id", "unknown")
        result = item.get("result", {})
        status = result.get("status", "?")
        retries = item.get("retries", 0)

        emoji = "✅" if status == "completed" else "❌"
        retry_str = f" (retry #{retries})" if retries > 0 else ""

        lines.append(f"  {emoji} {job_id[:12]}... {status}{retry_str}")

    if len(pending) > 3:
        lines.append(f"  ... and {len(pending) - 3} more")

    return "\n".join(lines)


def get_subagent_status_section() -> Optional[str]:
    """
    Get full sub-agent status section for /status command.

    Returns HTML-formatted string or None if nothing to show.
    """
    parts = []

    active_status = format_active_subagents_status()
    if active_status:
        parts.append(active_status)

    pending_status = format_pending_announces_status()
    if pending_status:
        parts.append(pending_status)

    if not parts:
        return None

    return "\n\n".join(parts)
