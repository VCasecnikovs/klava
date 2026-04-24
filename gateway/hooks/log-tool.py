#!/usr/bin/env python3
"""Claude Code PostToolUse hook - logs tool calls to JSONL for observability."""
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config as _cfg

LOG_DIR = _cfg.logs_dir()
LOG_FILE = LOG_DIR / "tool-calls.jsonl"
SKILLS_DIR = _cfg.skills_dir()
MAX_SIZE = 10 * 1024 * 1024  # 10MB rotation
SKILL_ERROR_MAX_SIZE = 1 * 1024 * 1024  # 1MB per skill errors file

def summarize_input(tool_name: str, tool_input: dict) -> str:
    """Extract a short human-readable summary from tool_input."""
    if not tool_input:
        return ""
    if tool_name == "Bash":
        return (tool_input.get("command") or "")[:200]
    if tool_name in ("Read", "Write"):
        return tool_input.get("file_path", "")
    if tool_name == "Edit":
        return tool_input.get("file_path", "")
    if tool_name == "Grep":
        path = tool_input.get("path", ".")
        return f'{tool_input.get("pattern", "")} in {path}'
    if tool_name == "Glob":
        return tool_input.get("pattern", "")
    if tool_name == "WebFetch":
        return tool_input.get("url", "")[:150]
    if tool_name == "WebSearch":
        return tool_input.get("query", "")[:150]
    if tool_name == "Task":
        return f'{tool_input.get("subagent_type", "?")} - {tool_input.get("description", "")}'
    if tool_name == "Skill":
        return tool_input.get("skill", "")
    # MCP tools
    if tool_name.startswith("mcp__"):
        # e.g. mcp__google__search_gmail_messages
        parts = tool_name.split("__")
        server = parts[1] if len(parts) > 1 else "?"
        tool = parts[2] if len(parts) > 2 else "?"
        # Try to find the most interesting param
        for key in ("query", "path", "owner", "repo", "table", "content"):
            if key in tool_input:
                return f"{server}/{tool}: {key}={str(tool_input[key])[:100]}"
        return f"{server}/{tool}"
    # Default: first key's value
    for k, v in tool_input.items():
        return f"{k}={str(v)[:100]}"
    return ""


def log_skill_error(tool_name: str, tool_input: dict, tool_response, session_id: str):
    """Append error to skill-specific errors.jsonl if a skill is active during this session.

    The skill name is detected from the CLAUDE_SKILL environment variable.
    If not set, the error is not logged to any skill (infrastructure ready for wiring later).
    """
    skill_name = os.environ.get("CLAUDE_SKILL", "")
    if not skill_name:
        return

    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists():
        return

    errors_file = skill_dir / "errors.jsonl"

    # Rotate if too large
    if errors_file.exists():
        try:
            if errors_file.stat().st_size > SKILL_ERROR_MAX_SIZE:
                rotated = errors_file.with_suffix(".1.jsonl")
                if rotated.exists():
                    rotated.unlink()
                errors_file.rename(rotated)
        except Exception:
            pass

    # Extract error details from response
    error_detail = ""
    if isinstance(tool_response, dict):
        error_detail = tool_response.get("error", "") or ""
        if not error_detail and tool_response.get("exitCode", 0) != 0:
            error_detail = f"exit_code={tool_response.get('exitCode')}"
    elif isinstance(tool_response, str):
        error_detail = tool_response[:500]

    error_record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sid": session_id[:16] if session_id else "",
        "skill": skill_name,
        "tool": tool_name,
        "summary": summarize_input(tool_name, tool_input),
        "error": error_detail[:500],
    }

    try:
        with open(errors_file, "a") as f:
            f.write(json.dumps(error_record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Don't break the hook on write failure


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Rotate if too large
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_SIZE:
        rotated = LOG_FILE.with_suffix(".1.jsonl")
        if rotated.exists():
            rotated.unlink()
        LOG_FILE.rename(rotated)

    # Read stdin
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool_name = data.get("tool_name", "?")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response")

    # Compute response status
    response_ok = True
    response_size = 0
    if tool_response is not None:
        response_str = json.dumps(tool_response)
        response_size = len(response_str)
        # Check for error indicators
        if isinstance(tool_response, dict):
            if tool_response.get("error") or tool_response.get("exitCode", 0) != 0:
                response_ok = False
        elif isinstance(tool_response, str) and "error" in tool_response.lower()[:50]:
            response_ok = False

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "sid": data.get("session_id", "")[:16],
        "tool": tool_name,
        "summary": summarize_input(tool_name, tool_input),
        "ok": response_ok,
        "size": response_size,
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Log errors to skill-specific errors.jsonl when a tool call fails
    if not response_ok:
        log_skill_error(tool_name, tool_input, tool_response, data.get("session_id", ""))


if __name__ == "__main__":
    main()
