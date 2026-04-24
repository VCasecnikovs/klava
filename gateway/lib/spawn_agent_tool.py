"""
Spawn Agent Tool for Claude Gateway

Allows main session to spawn async sub-agents for background work.
Sub-agents run in isolation and announce results back to main session.
"""

import asyncio
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, ResultMessage, AssistantMessage, TextBlock, ToolUseBlock

from .process_reaper import kill_sdk_subprocess

from .subagent_state import (
    register_subagent, OUTPUT_DIR, init_subagent_state, set_status_message_id
)
from .subagent_status import format_spawn_notification
from .telegram_utils import send_telegram_message_with_id, get_telegram_config
from . import config as _cfg

# MCP config path
MCP_CONFIG = str(_cfg.mcp_servers_file())

# Config defaults
DEFAULT_MODEL = _cfg.default_model()
DEFAULT_TIMEOUT = 600  # 10 minutes
MAX_CONCURRENT = 3

# Will be loaded from config
_config = {}


def init_spawn_agent(config: dict):
    """Initialize spawn_agent settings from config"""
    global _config, DEFAULT_MODEL, DEFAULT_TIMEOUT, MAX_CONCURRENT

    _config = config.get("subagents", {})
    _config["_full_config"] = config  # Store full config for telegram access

    DEFAULT_MODEL = _config.get("default_model", _cfg.default_model())
    DEFAULT_TIMEOUT = _config.get("default_timeout", 600)
    MAX_CONCURRENT = _config.get("max_concurrent", 3)

    # Also initialize subagent state
    init_subagent_state(config)


def create_subagent_job(
    task: str,
    label: str = "Task",
    model: str = None,
    timeout_seconds: int = None,
    tools: list = None,
    origin_topic: int = None,
    announce_mode: str = None
) -> dict:
    """Create a sub-agent job configuration."""
    job_id = f"subagent_{uuid.uuid4().hex[:8]}"

    return {
        "id": job_id,
        "name": f"Sub-agent: {label}",
        "enabled": True,
        "type": "subagent",
        "schedule": {
            "type": "immediate"
        },
        "execution": {
            "mode": "isolated",
            "model": model or DEFAULT_MODEL,
            "prompt_template": task,
            "timeout_seconds": timeout_seconds or DEFAULT_TIMEOUT,
            "allowedTools": tools or ["*"],
        },
        "announce": {
            "enabled": True,
            "topic_id": origin_topic or _config.get("announce_topic"),
            "mode": announce_mode or _config.get("announce_mode", "agent_turn")
        },
        "created_at": datetime.now().isoformat(),
        "delete_after_run": True
    }


async def spawn_agent(
    task: str,
    label: str = "Task",
    model: str = None,
    timeout_seconds: int = None,
    tools: list = None,
    origin_topic: int = None,
    announce_mode: str = None
) -> dict:
    """
    Spawn an async sub-agent for background work.

    Uses ClaudeSDKClient (streaming mode) for full hook support.
    The main session continues without waiting.
    """
    from .subagent_state import get_active_subagents

    # Check concurrent limit
    active = get_active_subagents()
    if len(active) >= MAX_CONCURRENT:
        return {
            "status": "rejected",
            "reason": f"Max concurrent sub-agents ({MAX_CONCURRENT}) reached",
            "active_count": len(active)
        }

    # Create job config
    job = create_subagent_job(
        task=task,
        label=label,
        model=model,
        timeout_seconds=timeout_seconds,
        tools=tools,
        origin_topic=origin_topic,
        announce_mode=announce_mode
    )

    job_id = job["id"]

    # Start sub-agent process in background
    try:
        pid, session_id = await _start_subagent_process(job)

        # Register in state
        register_subagent(job_id, job, origin_topic, pid, session_id=session_id)

        # Send notification to Telegram and save message_id for live progress
        try:
            bot_token, chat_id, _ = get_telegram_config(_config.get("_full_config", {}))
            topic_id = origin_topic or _config.get("announce_topic")

            if bot_token and chat_id:
                notification = format_spawn_notification(job_id, job)
                message_id = send_telegram_message_with_id(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    message=notification,
                    topic_id=topic_id,
                    parse_mode="HTML"
                )
                if message_id:
                    set_status_message_id(job_id, message_id)
        except Exception:
            pass

        return {
            "status": "spawned",
            "job_id": job_id,
            "label": label,
            "model": job["execution"]["model"],
            "timeout": job["execution"]["timeout_seconds"],
            "message": f"Sub-agent '{label}' started. Results will be announced when complete."
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "job_id": job_id
        }


async def _start_subagent_process(job: dict) -> tuple:
    """
    Start a sub-agent via ClaudeSDKClient (streaming mode) in a background thread.

    Returns (thread_ident, session_id) tuple.
    """
    job_id = job["id"]
    execution = job["execution"]

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_file = OUTPUT_DIR / f"{job_id}.out"
    result_file = OUTPUT_DIR / f"{job_id}.result.json"

    model = execution["model"]
    timeout = execution["timeout_seconds"]
    prompt = execution["prompt_template"]

    # Build SDK options
    opts = {
        "allowed_tools": ["*"],
        "permission_mode": "bypassPermissions",
        "cwd": Path.home(),
    }
    opts["model"] = model or DEFAULT_MODEL
    if os.path.exists(MCP_CONFIG):
        opts["mcp_servers"] = MCP_CONFIG

    options = ClaudeAgentOptions(**opts)

    # Placeholder session_id - will be updated when ResultMessage arrives
    session_id = f"pending-{job_id}"

    def _run_sdk():
        """Run SDK streaming query in background thread."""
        try:
            result_msg = None
            text_parts = []
            todos = []
            client_ref = [None]

            async def _execute():
                nonlocal result_msg, text_parts, todos
                try:
                    async with asyncio.timeout(timeout):
                        async with ClaudeSDKClient(options) as client:
                            client_ref[0] = client
                            await client.connect()
                            await client.query(prompt)

                            async for message in client.receive_messages():
                                if isinstance(message, AssistantMessage):
                                    for block in message.content:
                                        if isinstance(block, TextBlock):
                                            text_parts.append(block.text)
                                        elif isinstance(block, ToolUseBlock):
                                            if block.name == "TodoWrite":
                                                # Extract todos from TodoWrite tool call
                                                if block.input and "todos" in block.input:
                                                    todos = block.input["todos"]
                                elif isinstance(message, ResultMessage):
                                    result_msg = message
                                    break  # ResultMessage is final - iterator won't terminate on its own
                finally:
                    # Force-kill SDK subprocess to prevent zombie accumulation
                    kill_sdk_subprocess(client_ref[0])

            asyncio.run(_execute())

            # Write output file
            if result_msg:
                output_file.write_text(json.dumps({
                    "type": "result",
                    "result": result_msg.result or "\n".join(text_parts),
                    "session_id": result_msg.session_id,
                    "total_cost_usd": result_msg.total_cost_usd or 0.0,
                    "duration_ms": result_msg.duration_ms or 0,
                    "num_turns": result_msg.num_turns,
                    "is_error": result_msg.is_error,
                    "usage": result_msg.usage or {},
                    "todos": todos,
                }))
                exit_code = 1 if result_msg.is_error else 0
            else:
                output_file.write_text(json.dumps({
                    "type": "result",
                    "result": "\n".join(text_parts) or "No result",
                    "is_error": True,
                    "todos": todos,
                }))
                exit_code = 1

            result_file.write_text(json.dumps({
                "status": "completed",
                "exit_code": exit_code,
            }))

        except Exception as e:
            result_file.write_text(json.dumps({
                "status": "completed",
                "exit_code": 1,
                "error": str(e),
            }))
            output_file.write_text(json.dumps({
                "type": "result",
                "result": f"Error: {e}",
                "is_error": True,
            }))

    thread = threading.Thread(target=_run_sdk, daemon=True)
    thread.start()

    # Return scheduler's PID (not thread.ident which is a memory address, not a PID).
    # If the scheduler crashes and restarts, the new PID won't match → recovery kicks in.
    return os.getpid(), session_id


def parse_spawn_request(text: str) -> Optional[dict]:
    """Parse a spawn_agent request from Claude's output."""
    import re

    pattern = r'<spawn_agent>\s*(.*?)\s*</spawn_agent>'
    match = re.search(pattern, text, re.DOTALL)

    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def format_spawn_result(result: dict) -> str:
    """Format spawn result for display to user"""
    if result["status"] == "spawned":
        return (
            f"🚀 **Sub-agent запущен**\n"
            f"├── Task: {result.get('label', 'Task')}\n"
            f"├── Model: {result.get('model', 'sonnet')}\n"
            f"├── Timeout: {result.get('timeout', 600) // 60} min\n"
            f"└── Job ID: `{result['job_id']}`\n\n"
            f"⏳ Результат придёт когда закончит..."
        )
    elif result["status"] == "rejected":
        return (
            f"❌ **Sub-agent отклонён**\n"
            f"Причина: {result.get('reason', 'Unknown')}\n"
            f"Активных: {result.get('active_count', '?')}"
        )
    else:
        return f"❌ **Ошибка**: {result.get('error', 'Unknown error')}"


def get_spawn_tool_description() -> str:
    """Get tool description for Claude's context"""
    return """
## spawn_agent Tool

You can spawn async sub-agents for background work by outputting:

<spawn_agent>
{
    "task": "Your task description here",
    "label": "Short label",
    "model": "haiku|sonnet|opus",
    "timeout_seconds": 600
}
</spawn_agent>

The sub-agent will run in the background and announce results when complete.
Use this for:
- Long-running research tasks
- Parallel investigations
- Tasks that don't need immediate results

You'll receive notifications when sub-agents complete.
"""
