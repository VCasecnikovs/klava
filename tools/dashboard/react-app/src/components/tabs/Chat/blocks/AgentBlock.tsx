import { useState, useEffect, useRef, useMemo } from 'react';
import { esc } from '@/lib/utils';
import { ToolRunBlock } from './ToolRunBlock';
import { ThinkingBubble } from './ThinkingBubble';
import { AssistantBlock } from './AssistantBlock';
import type { Block } from '@/context/ChatContext';

const TOOL_TYPES = new Set(['tool_use', 'tool_group', 'tool_result']);

/** Group agent sub-blocks into ToolRunBlock / ThinkingBubble / single blocks */
function groupAgentBlocks(blocks: Block[]) {
  const groups: Array<{ type: 'tool_run' | 'thinking' | 'assistant'; blocks: Block[] }> = [];
  let toolBuf: Block[] = [];
  let thinkBuf: Block[] = [];

  const flushTools = () => {
    if (toolBuf.length) { groups.push({ type: 'tool_run', blocks: toolBuf }); toolBuf = []; }
  };
  const flushThinking = () => {
    if (thinkBuf.length) { groups.push({ type: 'thinking', blocks: thinkBuf }); thinkBuf = []; }
  };

  for (const b of blocks) {
    if (TOOL_TYPES.has(b.type)) {
      flushThinking();
      toolBuf.push(b);
    } else if (b.type === 'thinking') {
      flushTools();
      thinkBuf.push(b);
    } else {
      flushTools();
      flushThinking();
      if (b.type === 'assistant') {
        groups.push({ type: 'assistant', blocks: [b] });
      }
    }
  }
  flushTools();
  flushThinking();
  return groups;
}

export function AgentBlock({ block }: { block: Block }) {
  const [expanded, setExpanded] = useState(!!block.running);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerElRef = useRef<HTMLSpanElement>(null);
  const input = (typeof block.input === 'object' && block.input !== null) ? block.input as Record<string, unknown> : {};
  const isRunning = !!block.running;
  const agentBlocks: Block[] = block.agent_blocks || [];

  // Auto-expand when running
  useEffect(() => {
    if (isRunning) setExpanded(true);
  }, [isRunning]);

  // Live timer while running
  useEffect(() => {
    if (isRunning && timerElRef.current) {
      const startTime = block.start_time ? block.start_time * 1000 : Date.now();
      const update = () => {
        if (!timerElRef.current) return;
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const min = Math.floor(elapsed / 60);
        const sec = elapsed % 60;
        timerElRef.current.textContent = `${min > 0 ? min + 'm ' : ''}${sec}s`;
      };
      update();
      timerRef.current = setInterval(update, 1000);
      return () => { if (timerRef.current) clearInterval(timerRef.current); };
    }
  }, [isRunning, block.start_time]);

  // Duration
  let durationStr = '';
  if (block.duration_ms) {
    durationStr = block.duration_ms > 1000
      ? (block.duration_ms / 1000).toFixed(1) + 's'
      : block.duration_ms + 'ms';
  }

  const subagentType = input.subagent_type as string || '';
  const description = (input.description as string || input.prompt as string || '').substring(0, 100);
  const toolCount = agentBlocks.filter((b: Block) => TOOL_TYPES.has(b.type) && b.type === 'tool_use').length;
  const hasContent = agentBlocks.length > 0;

  const grouped = useMemo(() => groupAgentBlocks(agentBlocks), [agentBlocks]);

  // Build summary
  const summary = useMemo(() => {
    if (!hasContent && !isRunning) return '';
    const parts: string[] = [];
    if (toolCount > 0) parts.push(`${toolCount} tool${toolCount !== 1 ? 's' : ''}`);
    const textCount = agentBlocks.filter((b: Block) => b.type === 'assistant').length;
    if (textCount > 0) parts.push(`${textCount} response${textCount !== 1 ? 's' : ''}`);
    return parts.join(', ');
  }, [hasContent, isRunning, toolCount, agentBlocks]);

  return (
    <div className={`chat-agent${isRunning ? ' running' : ''}${expanded ? ' expanded' : ''}`}>
      <div className="chat-agent-header" onClick={() => setExpanded(e => !e)}>
        <span className="chat-agent-arrow">&#9654;</span>
        <span className="chat-agent-label">
          {subagentType || 'Agent'}
        </span>
        {description && (
          <span className="chat-agent-desc">{esc(description)}</span>
        )}
        <span className="chat-agent-meta">
          {isRunning && <span className="agent-spinner" />}
          {isRunning && <span ref={timerElRef} className="chat-agent-timer" />}
          {!isRunning && summary && (
            <span className="chat-agent-summary">{summary}</span>
          )}
          {!isRunning && durationStr && (
            <span className="chat-agent-duration">{durationStr}</span>
          )}
        </span>
      </div>

      {expanded && (
        <div className="chat-agent-body">
          {hasContent ? (
            grouped.map((g, i) => {
              if (g.type === 'tool_run') {
                return <ToolRunBlock key={`ag-tr-${i}`} blocks={g.blocks} isStreaming={isRunning} />;
              }
              if (g.type === 'thinking') {
                return <ThinkingBubble key={`ag-th-${i}`} blocks={g.blocks} />;
              }
              // assistant
              return <AssistantBlock key={`ag-as-${i}`} block={g.blocks[0]} />;
            })
          ) : isRunning ? (
            <div className="chat-agent-waiting">Starting agent...</div>
          ) : (
            <div className="chat-agent-waiting">Completed</div>
          )}
        </div>
      )}
    </div>
  );
}
