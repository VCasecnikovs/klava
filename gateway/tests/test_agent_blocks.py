"""Tests for agent block routing in dashboard chat.

Validates that:
1. Task tool creates "agent" type block (not "tool_use")
2. Messages with parent_tool_use_id route into agent's agent_blocks
3. Normal messages (no parent_tool_use_id) are unaffected
4. Agent completion marks block as done
"""

import pytest


class FakeBlock:
    """Minimal content block for testing."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeToolUseBlock(FakeBlock):
    pass


class FakeTextBlock(FakeBlock):
    pass


class FakeToolResultBlock(FakeBlock):
    pass


class FakeThinkingBlock(FakeBlock):
    pass


class FakeStreamEvent:
    def __init__(self, event, parent_tool_use_id=None):
        self.event = event
        self.parent_tool_use_id = parent_tool_use_id
        self.uuid = "test-uuid"
        self.session_id = "test-session"


class FakeAssistantMessage:
    def __init__(self, content, parent_tool_use_id=None):
        self.content = content
        self.parent_tool_use_id = parent_tool_use_id
        self.model = "sonnet"


class FakeUserMessage:
    def __init__(self, content, parent_tool_use_id=None):
        self.content = content
        self.parent_tool_use_id = parent_tool_use_id


# ---- AgentBlockTracker tests ----

from gateway.lib.agent_blocks import AgentBlockTracker


class TestAgentBlockTracker:

    def setup_method(self):
        self.blocks = []
        self.updates = []

        def on_add(block):
            block["id"] = len(self.blocks)
            self.blocks.append(block)
            return block["id"]

        def on_update(block_id, patch):
            for b in self.blocks:
                if b["id"] == block_id:
                    b.update(patch)
            self.updates.append((block_id, patch))

        self.tracker = AgentBlockTracker(on_add=on_add, on_update=on_update)

    # --- Agent creation ---

    def test_task_tool_creates_agent_block(self):
        """ToolUseBlock with name='Task' should create type='agent' block."""
        tool_block = FakeToolUseBlock(
            id="tool_123", name="Task",
            input={"description": "Check notes", "subagent_type": "Explore", "prompt": "..."}
        )
        result = self.tracker.handle_tool_use(tool_block)

        assert result is True  # handled
        assert len(self.blocks) == 1
        assert self.blocks[0]["type"] == "agent"
        assert self.blocks[0]["tool"] == "Task"
        assert self.blocks[0]["running"] is True
        assert self.blocks[0]["agent_blocks"] == []
        assert "tool_123" in self.tracker.active_agents

    def test_agent_name_creates_agent_block(self):
        """ToolUseBlock with name='Agent' should also create type='agent' block.

        The SDK sends 'Agent' (not 'Task') as the tool name in practice.
        """
        tool_block = FakeToolUseBlock(
            id="tool_789", name="Agent",
            input={"description": "Explore code", "subagent_type": "Explore", "prompt": "..."}
        )
        result = self.tracker.handle_tool_use(tool_block)

        assert result is True
        assert len(self.blocks) == 1
        assert self.blocks[0]["type"] == "agent"
        assert self.blocks[0]["running"] is True
        assert "tool_789" in self.tracker.active_agents

    def test_non_task_tool_not_handled(self):
        """Non-Task tools should not be handled by tracker."""
        tool_block = FakeToolUseBlock(id="tool_456", name="Bash", input={"command": "ls"})
        result = self.tracker.handle_tool_use(tool_block)

        assert result is False
        assert len(self.blocks) == 0
        assert "tool_456" not in self.tracker.active_agents

    # --- Subagent message routing ---

    def test_subagent_text_routed_to_agent_blocks(self):
        """AssistantMessage with parent_tool_use_id matching agent goes into agent_blocks."""
        # First create agent
        tool_block = FakeToolUseBlock(
            id="agent_1", name="Task",
            input={"description": "Research", "prompt": "..."}
        )
        self.tracker.handle_tool_use(tool_block)

        # Then send subagent text message
        msg = FakeAssistantMessage(
            content=[FakeTextBlock(text="Found results")],
            parent_tool_use_id="agent_1"
        )
        result = self.tracker.handle_message(msg)

        assert result is True  # handled (routed to agent)
        assert len(self.blocks[0]["agent_blocks"]) == 1
        assert self.blocks[0]["agent_blocks"][0]["type"] == "assistant"
        assert self.blocks[0]["agent_blocks"][0]["text"] == "Found results"

    def test_subagent_tool_use_routed_to_agent_blocks(self):
        """Subagent tool calls appear inside agent_blocks."""
        tool_block = FakeToolUseBlock(
            id="agent_1", name="Task",
            input={"description": "Research", "prompt": "..."}
        )
        self.tracker.handle_tool_use(tool_block)

        msg = FakeAssistantMessage(
            content=[FakeToolUseBlock(id="sub_tool_1", name="Bash", input={"command": "ls"})],
            parent_tool_use_id="agent_1"
        )
        result = self.tracker.handle_message(msg)

        assert result is True
        assert len(self.blocks[0]["agent_blocks"]) == 1
        assert self.blocks[0]["agent_blocks"][0]["type"] == "tool_use"
        assert self.blocks[0]["agent_blocks"][0]["tool"] == "Bash"

    def test_subagent_tool_result_routed(self):
        """Subagent tool results route into agent_blocks."""
        tool_block = FakeToolUseBlock(
            id="agent_1", name="Task",
            input={"description": "Research", "prompt": "..."}
        )
        self.tracker.handle_tool_use(tool_block)

        # Tool call
        msg1 = FakeAssistantMessage(
            content=[FakeToolUseBlock(id="sub_tool_1", name="Read", input={"file_path": "/a.txt"})],
            parent_tool_use_id="agent_1"
        )
        self.tracker.handle_message(msg1)

        # Tool result
        msg2 = FakeUserMessage(
            content=[FakeToolResultBlock(tool_use_id="sub_tool_1", content="file contents", is_error=False)],
            parent_tool_use_id="agent_1"
        )
        result = self.tracker.handle_message(msg2)

        assert result is True
        assert len(self.blocks[0]["agent_blocks"]) == 2
        assert self.blocks[0]["agent_blocks"][1]["type"] == "tool_result"

    def test_subagent_thinking_routed(self):
        """Subagent thinking blocks go into agent_blocks."""
        tool_block = FakeToolUseBlock(
            id="agent_1", name="Task",
            input={"description": "Research", "prompt": "..."}
        )
        self.tracker.handle_tool_use(tool_block)

        msg = FakeAssistantMessage(
            content=[FakeThinkingBlock(thinking="Let me think...", signature="sig")],
            parent_tool_use_id="agent_1"
        )
        result = self.tracker.handle_message(msg)

        assert result is True
        assert len(self.blocks[0]["agent_blocks"]) == 1
        assert self.blocks[0]["agent_blocks"][0]["type"] == "thinking"

    def test_normal_message_not_routed(self):
        """Messages without parent_tool_use_id are not handled."""
        tool_block = FakeToolUseBlock(
            id="agent_1", name="Task",
            input={"description": "Research", "prompt": "..."}
        )
        self.tracker.handle_tool_use(tool_block)

        msg = FakeAssistantMessage(
            content=[FakeTextBlock(text="Normal response")],
            parent_tool_use_id=None
        )
        result = self.tracker.handle_message(msg)

        assert result is False  # not handled
        assert len(self.blocks[0]["agent_blocks"]) == 0

    def test_unknown_parent_not_routed(self):
        """Messages with unknown parent_tool_use_id are not handled."""
        msg = FakeAssistantMessage(
            content=[FakeTextBlock(text="Orphan message")],
            parent_tool_use_id="unknown_id"
        )
        result = self.tracker.handle_message(msg)

        assert result is False

    # --- Agent completion ---

    def test_agent_completion(self):
        """ToolResultBlock for agent marks it complete."""
        tool_block = FakeToolUseBlock(
            id="agent_1", name="Task",
            input={"description": "Research", "prompt": "..."}
        )
        self.tracker.handle_tool_use(tool_block)

        result_block = FakeToolResultBlock(
            tool_use_id="agent_1",
            content="Agent completed successfully",
            is_error=False
        )
        result = self.tracker.handle_tool_result(result_block)

        assert result is True
        assert self.blocks[0]["running"] is False
        assert "agent_1" not in self.tracker.active_agents
        # Should have been updated
        assert any(
            patch.get("running") is False
            for _, patch in self.updates
        )

    def test_non_agent_result_not_handled(self):
        """ToolResultBlock for non-agent tool is not handled."""
        result_block = FakeToolResultBlock(
            tool_use_id="regular_tool_1",
            content="Done",
            is_error=False
        )
        result = self.tracker.handle_tool_result(result_block)
        assert result is False

    # --- Multiple agents ---

    def test_multiple_agents_tracked_independently(self):
        """Multiple concurrent agents have separate agent_blocks."""
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_1", name="Task", input={"description": "Task 1", "prompt": "..."}
        ))
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_2", name="Task", input={"description": "Task 2", "prompt": "..."}
        ))

        # Send message to agent_1
        self.tracker.handle_message(FakeAssistantMessage(
            content=[FakeTextBlock(text="Result 1")],
            parent_tool_use_id="agent_1"
        ))
        # Send message to agent_2
        self.tracker.handle_message(FakeAssistantMessage(
            content=[FakeTextBlock(text="Result 2")],
            parent_tool_use_id="agent_2"
        ))

        assert len(self.blocks[0]["agent_blocks"]) == 1
        assert self.blocks[0]["agent_blocks"][0]["text"] == "Result 1"
        assert len(self.blocks[1]["agent_blocks"]) == 1
        assert self.blocks[1]["agent_blocks"][0]["text"] == "Result 2"

    # --- Text accumulation ---

    def test_subagent_text_accumulates(self):
        """Multiple text blocks from subagent accumulate correctly."""
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_1", name="Task", input={"description": "Research", "prompt": "..."}
        ))

        # First text
        self.tracker.handle_message(FakeAssistantMessage(
            content=[FakeTextBlock(text="Hello")],
            parent_tool_use_id="agent_1"
        ))
        # Updated text (SDK sends full text each time)
        self.tracker.handle_message(FakeAssistantMessage(
            content=[FakeTextBlock(text="Hello world")],
            parent_tool_use_id="agent_1"
        ))

        # Should update existing text block, not create new one
        agent_blocks = self.blocks[0]["agent_blocks"]
        text_blocks = [b for b in agent_blocks if b["type"] == "assistant"]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "Hello world"

    # --- StreamEvent routing ---

    def test_stream_event_from_subagent_is_handled(self):
        """StreamEvent with parent_tool_use_id matching agent should be handled."""
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_1", name="Agent", input={"description": "Research", "prompt": "..."}
        ))

        event = FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
            parent_tool_use_id="agent_1"
        )
        result = self.tracker.handle_stream_event(event)
        assert result is True
        # Text should appear in agent_blocks
        assert len(self.blocks[0]["agent_blocks"]) == 1
        assert self.blocks[0]["agent_blocks"][0]["type"] == "assistant"
        assert self.blocks[0]["agent_blocks"][0]["text"] == "Hello"

    def test_stream_event_without_parent_not_handled(self):
        """StreamEvent without parent_tool_use_id should not be handled."""
        event = FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
            parent_tool_use_id=None
        )
        result = self.tracker.handle_stream_event(event)
        assert result is False

    def test_stream_event_unknown_parent_not_handled(self):
        """StreamEvent with unknown parent_tool_use_id should not be handled."""
        event = FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
            parent_tool_use_id="unknown_id"
        )
        result = self.tracker.handle_stream_event(event)
        assert result is False

    def test_stream_event_text_accumulates(self):
        """Multiple StreamEvents accumulate text in a single assistant block."""
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_1", name="Agent", input={"description": "Research", "prompt": "..."}
        ))

        # First chunk
        self.tracker.handle_stream_event(FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}},
            parent_tool_use_id="agent_1"
        ))
        # Second chunk
        self.tracker.handle_stream_event(FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}},
            parent_tool_use_id="agent_1"
        ))

        agent_blocks = self.blocks[0]["agent_blocks"]
        text_blocks = [b for b in agent_blocks if b["type"] == "assistant"]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "Hello world"

    def test_stream_event_then_full_message_no_duplicate(self):
        """After StreamEvent text, full AssistantMessage should update (not duplicate)."""
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_1", name="Agent", input={"description": "Research", "prompt": "..."}
        ))

        # Stream events accumulate text
        self.tracker.handle_stream_event(FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}},
            parent_tool_use_id="agent_1"
        ))
        self.tracker.handle_stream_event(FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}},
            parent_tool_use_id="agent_1"
        ))

        # Full message arrives - same length, should be skipped
        self.tracker.handle_message(FakeAssistantMessage(
            content=[FakeTextBlock(text="Hello world")],
            parent_tool_use_id="agent_1"
        ))

        agent_blocks = self.blocks[0]["agent_blocks"]
        text_blocks = [b for b in agent_blocks if b["type"] == "assistant"]
        assert len(text_blocks) == 1
        assert text_blocks[0]["text"] == "Hello world"

    def test_stream_event_thinking_suppressed(self):
        """Thinking StreamEvent from subagent should be suppressed (handled=True)."""
        self.tracker.handle_tool_use(FakeToolUseBlock(
            id="agent_1", name="Agent", input={"description": "Research", "prompt": "..."}
        ))

        event = FakeStreamEvent(
            event={"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Let me think..."}},
            parent_tool_use_id="agent_1"
        )
        result = self.tracker.handle_stream_event(event)
        assert result is True  # handled (suppressed from main chat)
