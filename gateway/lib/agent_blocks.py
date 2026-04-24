"""Agent block tracking for dashboard chat.

Routes subagent messages into nested agent blocks for proper rendering.
When a Task tool is called, its intermediate messages (text, tool calls,
results) are collected into an `agent_blocks` array on the agent block.
"""

import logging as _logging
import time as _time
from typing import Any, Callable, Optional

_log = _logging.getLogger("agent_blocks")


class AgentBlockTracker:
    """Tracks active agent (Task) tool calls and routes subagent messages.

    Usage in webhook-server message processing loop:
        tracker = AgentBlockTracker(on_add=..., on_update=...)

        # When ToolUseBlock arrives:
        if tracker.handle_tool_use(block):
            continue  # was an agent, handled

        # Before processing AssistantMessage/UserMessage:
        if tracker.handle_message(message):
            continue  # was a subagent message, routed to agent block

        # When ToolResultBlock arrives:
        if tracker.handle_tool_result(block):
            continue  # was agent completion, handled
    """

    def __init__(
        self,
        on_add: Callable[[dict], int],
        on_update: Callable[[int, dict], None],
    ):
        """
        Args:
            on_add: Callback to add a block. Returns the block's dashboard id.
            on_update: Callback to update a block by id with a patch dict.
        """
        self._on_add = on_add
        self._on_update = on_update

        # SDK tool_use_id -> dashboard block_id
        self.active_agents: dict[str, int] = {}

        # SDK tool_use_id -> per-agent sub-state for text accumulation
        self._sub_states: dict[str, dict] = {}

    def handle_tool_use(self, block: Any) -> bool:
        """Handle a ToolUseBlock. Returns True if it was an agent (Task) tool."""
        name = getattr(block, "name", "")
        _log.info(f"handle_tool_use: name={name!r} id={getattr(block, 'id', '?')}")
        if name not in ("Task", "Agent"):
            return False

        tool_id = getattr(block, "id", "")
        tool_input = getattr(block, "input", {})

        agent_block = {
            "type": "agent",
            "tool": name,
            "input": tool_input,
            "running": True,
            "start_time": _time.time(),
            "agent_blocks": [],
        }

        block_id = self._on_add(agent_block)
        self.active_agents[tool_id] = block_id
        _log.info(f"handle_tool_use: CREATED agent block id={block_id} for tool_id={tool_id}")
        self._sub_states[tool_id] = {
            "last_text_len": 0,
            "current_text_idx": None,
        }

        return True

    def handle_stream_event(self, event_msg: Any) -> bool:
        """Handle a StreamEvent. Returns True if it belongs to a subagent.

        StreamEvents carry token-by-token streaming data. If parent_tool_use_id
        matches an active agent, we suppress it (the full AssistantMessage will
        be handled by handle_message later).
        """
        parent_id = getattr(event_msg, "parent_tool_use_id", None)
        if not parent_id or parent_id not in self.active_agents:
            return False
        # Subagent StreamEvent - suppress from main chat, route to agent block
        event = getattr(event_msg, "event", {})
        block_id = self.active_agents[parent_id]
        delta = event.get("delta", {}) if event.get("type") == "content_block_delta" else {}
        if delta.get("type") == "text_delta":
            text_chunk = delta.get("text", "")
            sub_state = self._sub_states.get(parent_id, {})
            if sub_state.get("current_text_idx") is not None:
                # Append to existing text block
                cache = self._agent_blocks_cache.get(block_id, [])
                idx = sub_state["current_text_idx"]
                if idx < len(cache):
                    cache[idx]["text"] = cache[idx].get("text", "") + text_chunk
                    self._on_update(block_id, {"agent_blocks": list(cache)})
            else:
                # Create new text block
                sub_block = {"type": "assistant", "text": text_chunk}
                idx = self._append_agent_sub_block(parent_id, block_id, sub_block)
                sub_state["current_text_idx"] = idx
            sub_state["last_text_len"] = sub_state.get("last_text_len", 0) + len(text_chunk)
        elif delta.get("type") == "thinking_delta":
            thinking_chunk = delta.get("thinking", "")
            sub_state = self._sub_states.get(parent_id, {})
            # For thinking, just accumulate - full block comes with AssistantMessage
            # But we need to suppress the StreamEvent from main chat
            pass
        return True

    def handle_message(self, message: Any) -> bool:
        """Handle a message (AssistantMessage or UserMessage).

        Returns True if the message was routed to an agent block.
        """
        parent_id = getattr(message, "parent_tool_use_id", None)
        _log.info(f"handle_message: type={type(message).__name__} parent_id={parent_id} active={list(self.active_agents.keys())}")
        if not parent_id or parent_id not in self.active_agents:
            return False

        block_id = self.active_agents[parent_id]
        sub_state = self._sub_states.get(parent_id, {})
        content = getattr(message, "content", [])

        for item in content:
            item_type = type(item).__name__

            if "TextBlock" in item_type:
                text = getattr(item, "text", "")
                if len(text) <= sub_state.get("last_text_len", 0):
                    continue

                if sub_state.get("current_text_idx") is not None:
                    # Update existing text block
                    self._update_agent_sub_block(
                        parent_id, block_id,
                        sub_state["current_text_idx"],
                        {"text": text}
                    )
                else:
                    # Create new text block
                    sub_block = {"type": "assistant", "text": text}
                    idx = self._append_agent_sub_block(parent_id, block_id, sub_block)
                    sub_state["current_text_idx"] = idx

                sub_state["last_text_len"] = len(text)

            elif "ThinkingBlock" in item_type:
                sub_block = {
                    "type": "thinking",
                    "text": getattr(item, "thinking", ""),
                }
                self._append_agent_sub_block(parent_id, block_id, sub_block)
                # Reset text tracking for new content after thinking
                sub_state["current_text_idx"] = None
                sub_state["last_text_len"] = 0

            elif "ToolUseBlock" in item_type:
                sub_block = {
                    "type": "tool_use",
                    "tool": getattr(item, "name", ""),
                    "input": getattr(item, "input", {}),
                    "running": True,
                    "start_time": _time.time(),
                }
                self._append_agent_sub_block(parent_id, block_id, sub_block)
                # Reset text tracking
                sub_state["current_text_idx"] = None
                sub_state["last_text_len"] = 0

            elif "ToolResultBlock" in item_type:
                content_val = getattr(item, "content", "")
                if isinstance(content_val, list):
                    content_val = "\n".join(
                        c.get("text", "") for c in content_val
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                sub_block = {
                    "type": "tool_result",
                    "content": str(content_val or ""),
                }
                self._append_agent_sub_block(parent_id, block_id, sub_block)
                # Mark last running tool as done
                self._mark_last_sub_tool_done(parent_id, block_id)

        return True

    def handle_tool_result(self, block: Any) -> bool:
        """Handle a ToolResultBlock for agent completion.

        Returns True if this was an agent's final result.
        """
        tool_use_id = getattr(block, "tool_use_id", "")
        if tool_use_id not in self.active_agents:
            return False

        block_id = self.active_agents[tool_use_id]

        self._on_update(block_id, {
            "running": False,
            "duration_ms": int((_time.time() - self._get_start_time(block_id)) * 1000),
        })

        del self.active_agents[tool_use_id]
        self._sub_states.pop(tool_use_id, None)

        return True

    # -----------------------------------------------------------------
    # Native SDK Task* message handlers (SDK 0.1.55+).
    #
    # TaskStartedMessage/TaskProgressMessage/TaskNotificationMessage are
    # typed lifecycle signals with task_id + tool_use_id + usage + status.
    # They don't replace the stream-event routing above (which is what
    # delivers actual subagent text/tool calls for live rendering); they
    # annotate the agent block with authoritative status and usage data
    # so the UI can show "3 tools, 14s, 42k tokens" without parsing it
    # out of free-form text.
    # -----------------------------------------------------------------

    def handle_task_started(self, msg: Any) -> bool:
        """TaskStartedMessage. Some runtimes emit this *before* the
        ToolUseBlock for the Task tool; others after. Either way we want
        to stamp task_id on the existing agent block if we can find it.
        """
        tool_use_id = getattr(msg, "tool_use_id", None)
        task_id     = getattr(msg, "task_id", None)
        if not tool_use_id or tool_use_id not in self.active_agents:
            return False
        block_id = self.active_agents[tool_use_id]
        patch: dict = {"task_id": task_id} if task_id else {}
        description = getattr(msg, "description", None)
        if description:
            patch["description"] = description
        task_type = getattr(msg, "task_type", None)
        if task_type:
            patch["task_type"] = task_type
        if patch:
            self._on_update(block_id, patch)
        return True

    def handle_task_progress(self, msg: Any) -> bool:
        """TaskProgressMessage. Emitted periodically with usage stats and
        the last tool name. Surface as a small usage badge."""
        tool_use_id = getattr(msg, "tool_use_id", None)
        if not tool_use_id or tool_use_id not in self.active_agents:
            return False
        block_id = self.active_agents[tool_use_id]
        usage = getattr(msg, "usage", None)
        patch: dict = {}
        if usage:
            patch["usage"] = {
                "total_tokens":  usage.get("total_tokens") if isinstance(usage, dict) else getattr(usage, "total_tokens", None),
                "tool_uses":     usage.get("tool_uses")    if isinstance(usage, dict) else getattr(usage, "tool_uses", None),
                "duration_ms":   usage.get("duration_ms")  if isinstance(usage, dict) else getattr(usage, "duration_ms", None),
            }
        last_tool = getattr(msg, "last_tool_name", None)
        if last_tool:
            patch["last_tool_name"] = last_tool
        if patch:
            self._on_update(block_id, patch)
        return True

    def handle_task_notification(self, msg: Any) -> bool:
        """TaskNotificationMessage. Terminal signal — status is one of
        completed / failed / stopped. Marks the agent block as no longer
        running and records the final status + summary + total usage.

        Returns True if the notification was routed (agent_blocks cleanup
        happens here OR in handle_tool_result — whichever arrives first).
        """
        tool_use_id = getattr(msg, "tool_use_id", None)
        if not tool_use_id or tool_use_id not in self.active_agents:
            return False
        block_id = self.active_agents[tool_use_id]
        status  = getattr(msg, "status", None)
        summary = getattr(msg, "summary", None)
        usage   = getattr(msg, "usage", None)
        patch: dict = {"running": False}
        if status:
            patch["status"] = status
        if summary:
            patch["summary"] = summary
        if usage:
            patch["usage"] = {
                "total_tokens":  usage.get("total_tokens") if isinstance(usage, dict) else getattr(usage, "total_tokens", None),
                "tool_uses":     usage.get("tool_uses")    if isinstance(usage, dict) else getattr(usage, "tool_uses", None),
                "duration_ms":   usage.get("duration_ms")  if isinstance(usage, dict) else getattr(usage, "duration_ms", None),
            }
        self._on_update(block_id, patch)
        return True

    def _append_agent_sub_block(self, agent_tool_id: str, block_id: int, sub_block: dict) -> int:
        """Append a sub-block to agent's agent_blocks and emit update."""
        # We need to get current agent_blocks from the block data
        # The on_add callback stores the block, so we track locally too
        if not hasattr(self, "_agent_blocks_cache"):
            self._agent_blocks_cache: dict[int, list] = {}

        if block_id not in self._agent_blocks_cache:
            self._agent_blocks_cache[block_id] = []

        cache = self._agent_blocks_cache[block_id]
        idx = len(cache)
        cache.append(sub_block)

        self._on_update(block_id, {"agent_blocks": list(cache)})
        return idx

    def _update_agent_sub_block(self, agent_tool_id: str, block_id: int, idx: int, patch: dict):
        """Update an existing sub-block in agent's agent_blocks."""
        if not hasattr(self, "_agent_blocks_cache"):
            return

        cache = self._agent_blocks_cache.get(block_id, [])
        if idx < len(cache):
            cache[idx].update(patch)
            self._on_update(block_id, {"agent_blocks": list(cache)})

    def _mark_last_sub_tool_done(self, agent_tool_id: str, block_id: int):
        """Mark the last running tool_use sub-block as done."""
        if not hasattr(self, "_agent_blocks_cache"):
            return

        cache = self._agent_blocks_cache.get(block_id, [])
        for sub in reversed(cache):
            if sub.get("type") == "tool_use" and sub.get("running"):
                sub["running"] = False
                sub["duration_ms"] = int((_time.time() - sub.get("start_time", _time.time())) * 1000)
                break

        self._on_update(block_id, {"agent_blocks": list(cache)})

    def _get_start_time(self, block_id: int) -> float:
        """Get agent block start time from cache or fallback."""
        # The block data is stored by the on_add callback
        # We can't access it directly, so we use the on_update to track
        # For now, use a reasonable fallback
        if hasattr(self, "_start_times"):
            return self._start_times.get(block_id, _time.time())
        return _time.time()
