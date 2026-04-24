"""Klava Tools MCP Server - config, tmux, and process diagnostics."""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("klava_tools_mcp")

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
