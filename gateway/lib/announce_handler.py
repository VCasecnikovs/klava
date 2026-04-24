"""
Announce Handler for Claude Gateway

Handles announcing sub-agent results to users and triggering agent turns.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .subagent_state import (
    get_pending_announces, pop_pending_announce, requeue_announce,
    get_subagent_output, get_subagent_result, cleanup_subagent_files
)
from .subagent_status import format_completion_notification

logger = logging.getLogger(__name__)

# Config - loaded from gateway config
_config = {}


def init_announce_handler(config: dict):
    """Initialize announce handler with config"""
    global _config
    _config = config


def process_pending_announces(max_batch: int = 5) -> list:
    """
    Process pending announces from the queue.

    Returns list of processed announces with their status.
    """
    results = []

    for _ in range(max_batch):
        announce = pop_pending_announce()
        if not announce:
            break

        job_id = announce.get("job_id", "unknown")
        logger.info(f"Processing announce for {job_id}")

        try:
            success = _process_single_announce(announce)
            results.append({
                "job_id": job_id,
                "status": "sent" if success else "failed"
            })
        except Exception as e:
            logger.exception(f"Failed to announce {job_id}: {e}")
            # Requeue for retry (up to 3 retries)
            if announce.get("retries", 0) < 3:
                requeue_announce(announce)
                results.append({
                    "job_id": job_id,
                    "status": "requeued",
                    "error": str(e)
                })
            else:
                results.append({
                    "job_id": job_id,
                    "status": "max_retries_exceeded",
                    "error": str(e)
                })

    return results


def _process_single_announce(announce: dict) -> bool:
    """
    Process a single announce item.

    Returns True if successful.
    """
    job_id = announce.get("job_id")
    subagent = announce.get("subagent", {})
    result = announce.get("result", {})

    # Get announce settings from job config
    job = subagent.get("job", {})
    announce_config = job.get("announce", {})

    topic_id = announce_config.get("topic_id") or subagent.get("origin_topic")
    mode = announce_config.get("mode", "message")

    if not topic_id:
        logger.warning(f"No topic_id for announce {job_id}, skipping")
        return False

    # Format the notification message
    notification = format_completion_notification(job_id, result, subagent)

    # Get result output for agent_turn mode
    output = result.get("output") or get_subagent_output(job_id) or ""

    if mode == "direct":
        # Send full output directly to topic (used by Tasks topic)
        success = _send_direct_output(topic_id, notification, output)
    elif mode == "agent_turn":
        # Trigger agent turn with result as context
        success = _trigger_agent_turn(topic_id, job_id, result, output, notification)
    else:
        # Just send notification message
        success = _send_notification(topic_id, notification)

    # Cleanup temp files on success
    if success:
        cleanup_subagent_files(job_id)

    return success


def _send_direct_output(topic_id: int, notification: str, output: str) -> bool:
    """Send full output directly to topic. Used by Tasks topic."""
    from .telegram_utils import send_telegram_message, get_telegram_config

    try:
        bot_token, chat_id, _ = get_telegram_config(_config)

        # Extract the text result from Claude's JSON output
        result_text = output
        if output:
            try:
                import json
                parsed = json.loads(output)
                result_text = parsed.get("result", output)
            except (json.JSONDecodeError, TypeError):
                pass

        # Truncate if too long for Telegram
        if len(result_text) > 3800:
            result_text = result_text[:3800] + "\n\n... (truncated)"

        # Send notification + result
        full_message = f"{notification}\n\n{result_text}" if result_text else notification
        send_telegram_message(
            bot_token,
            chat_id,
            full_message,
            topic_id=topic_id,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.exception(f"Failed to send direct output: {e}")
        return False


def _send_notification(topic_id: int, message: str) -> bool:
    """Send notification message to Telegram topic"""
    from .telegram_utils import send_telegram_message, get_telegram_config

    try:
        bot_token, chat_id, _ = get_telegram_config(_config)
        send_telegram_message(
            bot_token,
            chat_id,
            message,
            topic_id=topic_id,
            parse_mode="HTML"
        )
        return True
    except Exception as e:
        logger.exception(f"Failed to send notification: {e}")
        return False


def _trigger_agent_turn(
    topic_id: int,
    job_id: str,
    result: dict,
    output: str,
    notification: str
) -> bool:
    """
    Trigger an agent turn in the main session with sub-agent result.

    Runs Claude with the sub-agent result as context and sends the response.
    """
    from .telegram_utils import send_telegram_message, get_telegram_config
    from .main_session import get_main_session_id
    from .claude_executor import ClaudeExecutor

    # Build prompt for main session to process
    status = result.get("status", "completed")
    job_name = result.get("job_name", job_id)

    # Truncate output if too long
    output_truncated = output[:4000] if len(output) > 4000 else output

    prompt = f"""<sub-agent-result>
Job: {job_name} ({job_id})
Status: {"✅ success" if status == "completed" else "❌ " + status}
Duration: {result.get('duration', 'N/A')}
Cost: {result.get('cost', 'N/A')}

Result:
{output_truncated}
</sub-agent-result>

Проанализируй результат sub-agent'а и реши что делать:
- Если результат полезен - используй его
- Если нужна дополнительная работа - можешь запустить ещё sub-agent
- Если готово - сообщи пользователю итог"""

    try:
        bot_token, chat_id, _ = get_telegram_config(_config)

        # First send the completion notification
        send_telegram_message(
            bot_token,
            chat_id,
            notification,
            topic_id=topic_id,
            parse_mode="HTML"
        )

        # Run Claude with main session context
        session_id = get_main_session_id()
        executor = ClaudeExecutor(log_callback=logger.info)

        response = executor.run(
            prompt=prompt,
            mode="main",
            session_id=session_id,
            model="sonnet",  # Use sonnet for main session
            timeout=300,
            allowed_tools=["*"],
            skip_permissions=True
        )

        # Send Claude's response to Telegram
        if response.get("result"):
            response_text = response["result"]
            # Truncate if needed
            if len(response_text) > 4000:
                response_text = response_text[:3997] + "..."

            send_telegram_message(
                bot_token,
                chat_id,
                f"🧠 <b>Main Agent Response:</b>\n\n{response_text}",
                topic_id=topic_id,
                parse_mode="HTML"
            )

        return True
    except Exception as e:
        logger.exception(f"Failed to trigger agent turn: {e}")
        return False


def check_and_announce_completed():
    """
    Check for completed sub-agents and process announces.

    Called periodically by cron-scheduler.
    """
    from .subagent_state import (
        get_active_subagents, complete_subagent, fail_subagent,
        is_process_alive, get_subagent_result
    )

    active = get_active_subagents()

    for job_id, subagent in list(active.items()):
        pid = subagent.get("pid")
        status = subagent.get("status", "running")

        if status == "running" and pid:
            if not is_process_alive(pid):
                # Process died - check for result
                result = get_subagent_result(job_id)
                output = get_subagent_output(job_id)

                if result or output:
                    # Completed (success or with output)
                    final_result = result or {"status": "completed", "output": output}
                    complete_subagent(job_id, final_result)
                    logger.info(f"Sub-agent {job_id} completed")
                else:
                    # Died without output
                    fail_subagent(job_id, "Process died without output")
                    logger.warning(f"Sub-agent {job_id} died without output")

    # Process any pending announces
    results = process_pending_announces()
    for r in results:
        logger.info(f"Announce {r['job_id']}: {r['status']}")

    return results
