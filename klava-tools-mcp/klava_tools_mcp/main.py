"""Klava Tools MCP Server - config, tmux, and process diagnostics."""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("klava_tools_mcp")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
GATEWAY_ROOT = REPO_ROOT / "gateway"
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

GLOBAL_CONFIG_PATH = Path.home() / ".claude" / "config.json"
PROJECT_SETTINGS_PATH = Path(".claude") / "settings.json"
SUPPORTED_CONFIG_KEYS = {
    "model", "theme", "autoCompactEnabled", "autoMemoryEnabled",
    "verbose", "preferredNotifChannel",
}
TMUX_PREFIX = "klava-"


def _run(cmd: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout,
    )


def _read_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _task_to_dict(task) -> dict:
    data = asdict(task)
    body = data.get("body") or ""
    if len(body) > 4000:
        data["body"] = body[:4000] + "\n...(truncated)"
    return data


def _priority_sort(task) -> tuple:
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return (
        priority_order.get(getattr(task, "priority", "medium"), 1),
        getattr(task, "created", "") or "",
    )


def _load_queue():
    try:
        from tasks import queue
        return queue
    except Exception as e:
        raise RuntimeError(
            f"Could not import Klava task queue from {REPO_ROOT}: {e}. "
            "Run from the claude repo or check Python environment dependencies."
        ) from e


# ---------- config tools ----------

@mcp.tool(
    name="config_get",
    annotations={
        "title": "Read Claude Code Configuration",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def config_get(key: Optional[str] = None) -> str:
    """Read Claude Code configuration.

    Reads from ~/.claude/config.json (global) and .claude/settings.json (project).
    If key is provided, returns that specific setting; otherwise returns all settings.
    """
    global_cfg = _read_json(GLOBAL_CONFIG_PATH)
    project_cfg = _read_json(PROJECT_SETTINGS_PATH)

    merged = {**global_cfg, **project_cfg}

    if key:
        if key in merged:
            return json.dumps({key: merged[key]}, indent=2)
        return f"Key '{key}' not found in configuration."

    return json.dumps(merged, indent=2)


@mcp.tool(
    name="config_set",
    annotations={
        "title": "Write Claude Code Configuration",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def config_set(key: str, value: str) -> str:
    """Write a setting to ~/.claude/config.json.

    Supported keys: model, theme, autoCompactEnabled, autoMemoryEnabled,
    verbose, preferredNotifChannel.
    Value is auto-parsed: "true"/"false" become booleans, numeric strings become numbers.
    """
    if key not in SUPPORTED_CONFIG_KEYS:
        return f"Error: key '{key}' not supported. Supported: {', '.join(sorted(SUPPORTED_CONFIG_KEYS))}"

    parsed_value: object = value
    if value.lower() == "true":
        parsed_value = True
    elif value.lower() == "false":
        parsed_value = False
    else:
        try:
            parsed_value = int(value)
        except ValueError:
            try:
                parsed_value = float(value)
            except ValueError:
                pass

    cfg = _read_json(GLOBAL_CONFIG_PATH)
    old = cfg.get(key, "<not set>")
    cfg[key] = parsed_value

    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")

    return f"Set '{key}': {old} -> {parsed_value}"


# ---------- Klava deck / queue tools ----------

@mcp.tool(
    name="klava_deck_list",
    annotations={
        "title": "List Klava Deck Cards",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def klava_deck_list(
    limit: int = 20,
    include_completed: bool = False,
    card_type: Optional[str] = None,
) -> str:
    """List Klava Deck cards from the Google Tasks-backed queue.

    Args:
        limit: Maximum cards to return.
        include_completed: Include completed/acked cards.
        card_type: Optional filter: task, proposal, result, signal, or brief.
    """
    queue = _load_queue()
    tasks = queue.list_tasks(include_completed=include_completed)
    if card_type:
        tasks = [t for t in tasks if t.type == card_type]
    else:
        tasks = [
            t for t in tasks
            if include_completed or (
                t.gtask_status != "completed"
                and t.status not in {"done", "skipped"}
            )
        ]
    tasks.sort(key=_priority_sort)
    return _json({
        "count": min(len(tasks), max(limit, 0)),
        "total_matching": len(tasks),
        "cards": [_task_to_dict(t) for t in tasks[:max(limit, 0)]],
    })


@mcp.tool(
    name="klava_task_create",
    annotations={
        "title": "Create Klava Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def klava_task_create(
    title: str,
    body: str = "",
    priority: str = "medium",
    scope: Optional[str] = None,
    dedup: bool = True,
) -> str:
    """Create a task on the Klava Deck/queue.

    Use this when the user wants Klava to remember or asynchronously execute
    follow-up work. priority must be high, medium, or low.
    """
    if priority not in {"high", "medium", "low"}:
        return "Error: priority must be one of high, medium, low."
    queue = _load_queue()
    task_id = queue.create_task(
        title=title,
        body=body,
        priority=priority,
        source="codex",
        scope=scope,
        dedup=dedup,
    )
    return _json({"ok": bool(task_id), "task_id": task_id, "title": title})


@mcp.tool(
    name="klava_result_create",
    annotations={
        "title": "Create Klava Result Card",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def klava_result_create(
    title: str,
    body: str,
    parent_task_id: Optional[str] = None,
    priority: str = "low",
    scope: Optional[str] = None,
    dedup_topic: bool = True,
) -> str:
    """Create a Klava [RESULT] card on the Deck.

    Use this for outcomes the user should see in Klava's Deck after work done
    from Codex. Include what was done and what was or was not verified.
    """
    if priority not in {"high", "medium", "low"}:
        return "Error: priority must be one of high, medium, low."
    queue = _load_queue()
    task_id = queue.create_result(
        parent_task_id=parent_task_id,
        title=title,
        body=body,
        priority=priority,
        source="codex",
        scope=scope,
        dedup_topic=dedup_topic,
    )
    return _json({"ok": bool(task_id), "task_id": task_id, "title": title})


@mcp.tool(
    name="klava_task_complete",
    annotations={
        "title": "Complete Klava Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def klava_task_complete(task_id: str) -> str:
    """Mark a Klava task/card complete in Google Tasks."""
    queue = _load_queue()
    queue.complete_task(task_id)
    return _json({"ok": True, "task_id": task_id})


@mcp.tool(
    name="klava_health_summary",
    annotations={
        "title": "Read Klava Health Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def klava_health_summary() -> str:
    """Return a compact health summary for Klava services, jobs, and sources."""
    try:
        from gateway.lib.status_collector import collect_dashboard_data
    except Exception:
        from lib.status_collector import collect_dashboard_data

    data = collect_dashboard_data()
    summary = {
        "assistant_name": data.get("assistant_name"),
        "stats": data.get("stats"),
        "services": data.get("services", []),
        "failing_jobs": data.get("failing_jobs", [])[:20],
        "data_sources": data.get("data_sources", [])[:30],
        "reply_queue": data.get("reply_queue"),
    }
    return _json(summary)


@mcp.tool(
    name="klava_vadimgest_search",
    annotations={
        "title": "Search Klava Memory With Vadimgest",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def klava_vadimgest_search(
    query: str,
    source: Optional[str] = None,
    markdown: bool = False,
    limit_chars: int = 12000,
) -> str:
    """Search personal data through vadimgest.

    Args:
        query: FTS query. Supports phrases and boolean operators.
        source: Optional vadimgest source, e.g. telegram, gmail, hlopya.
        markdown: Search markdown/Obsidian/skills with --md.
        limit_chars: Maximum output characters to return.
    """
    cmd = ["vadimgest", "search", query]
    if markdown:
        cmd.append("--md")
    if source:
        cmd.extend(["-s", source])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        return _json({
            "ok": False,
            "error": result.stderr.strip() or result.stdout.strip(),
            "command": cmd,
        })
    output = result.stdout.strip()
    limit = max(1000, min(limit_chars, 50000))
    if len(output) > limit:
        output = output[:limit] + "\n...(truncated)"
    return output or "(no results)"


# ---------- tmux tools ----------

@mcp.tool(
    name="tmux_create",
    annotations={
        "title": "Create Tmux Session",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def tmux_create(name: str, command: Optional[str] = None) -> str:
    """Create a persistent tmux session with klava- prefix.

    If command is provided, it runs immediately in the new session.
    """
    session = f"{TMUX_PREFIX}{name}"

    check = _run(f"tmux has-session -t {session} 2>/dev/null")
    if check.returncode == 0:
        return f"Session '{session}' already exists."

    cmd = f"tmux new-session -d -s {session}"
    result = _run(cmd)
    if result.returncode != 0:
        return f"Error creating session: {result.stderr.strip()}"

    if command:
        _run(f'tmux send-keys -t {session} "{command}" Enter')

    return f"Created session '{session}'" + (f" and ran: {command}" if command else "")


@mcp.tool(
    name="tmux_send",
    annotations={
        "title": "Send Command to Tmux Session",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def tmux_send(name: str, command: str) -> str:
    """Send a command to a klava- tmux session."""
    session = f"{TMUX_PREFIX}{name}"

    check = _run(f"tmux has-session -t {session} 2>/dev/null")
    if check.returncode != 0:
        return f"Error: session '{session}' does not exist."

    result = _run(f'tmux send-keys -t {session} "{command}" Enter')
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"

    return f"Sent to '{session}': {command}"


@mcp.tool(
    name="tmux_capture",
    annotations={
        "title": "Capture Tmux Session Output",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def tmux_capture(name: str, lines: int = 50) -> str:
    """Capture visible output from a klava- tmux session.

    Returns the last N lines from the tmux pane.
    """
    session = f"{TMUX_PREFIX}{name}"

    check = _run(f"tmux has-session -t {session} 2>/dev/null")
    if check.returncode != 0:
        return f"Error: session '{session}' does not exist."

    result = _run(f"tmux capture-pane -t {session} -p -S -{lines}")
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"

    output = result.stdout.rstrip()
    return output if output else "(empty - no output captured)"


@mcp.tool(
    name="tmux_list",
    annotations={
        "title": "List Klava Tmux Sessions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def tmux_list() -> str:
    """List all active klava- tmux sessions."""
    result = _run("tmux list-sessions 2>/dev/null")

    if result.returncode != 0:
        return "No tmux sessions running."

    sessions = [
        line for line in result.stdout.strip().splitlines()
        if line.startswith(TMUX_PREFIX)
    ]

    if not sessions:
        return "No klava- tmux sessions found."

    return "\n".join(sessions)


@mcp.tool(
    name="tmux_kill",
    annotations={
        "title": "Kill Tmux Session",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def tmux_kill(name: str) -> str:
    """Kill a klava- tmux session."""
    session = f"{TMUX_PREFIX}{name}"

    result = _run(f"tmux kill-session -t {session}")
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"

    return f"Killed session '{session}'."


# ---------- process diagnostics ----------

@mcp.tool(
    name="process_check",
    annotations={
        "title": "Check for Stuck Processes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def process_check() -> str:
    """Check for stuck or hung claude/python/node processes.

    Reports CPU usage, memory, runtime, and state for potentially problematic processes.
    """
    targets = ["claude", "python", "python3", "node"]
    pattern = "|".join(targets)

    result = _run(f'ps aux | head -1 && ps aux | grep -E "{pattern}" | grep -v grep')

    if result.returncode != 0 or not result.stdout.strip():
        return "No matching processes found."

    lines = result.stdout.strip().splitlines()
    if len(lines) <= 1:
        return "No matching processes found."

    header = lines[0]
    procs = lines[1:]

    report = [f"Found {len(procs)} matching process(es):\n", header]

    suspects = []
    for line in procs:
        parts = line.split(None, 10)
        if len(parts) >= 11:
            cpu = float(parts[2])
            mem = float(parts[3])
            state = parts[7] if len(parts) > 7 else "?"

            flags = []
            if cpu > 90:
                flags.append("HIGH CPU")
            if mem > 10:
                flags.append("HIGH MEM")
            if "Z" in state:
                flags.append("ZOMBIE")
            if "T" in state:
                flags.append("STOPPED")

            if flags:
                suspects.append(f"  ** {' | '.join(flags)}: {line}")
            else:
                report.append(line)

    if suspects:
        report.append("\n== SUSPECTS ==")
        report.extend(suspects)
    else:
        report.extend(procs)
        report.append("\nAll processes look healthy.")

    return "\n".join(report)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
