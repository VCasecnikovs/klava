import { useState, useEffect, useRef } from 'react';
import { esc } from '@/lib/utils';
import { getToolConfig, getToolSummary, formatToolInput } from '../toolRegistry';
import type { Block } from '@/context/ChatContext';

export function ToolUseBlock({ block }: { block: Block }) {
  const [expanded, setExpanded] = useState(block.tool === 'Task' && !!block.running);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerElRef = useRef<HTMLDivElement>(null);
  const toolName = block.tool || '';
  const reg = getToolConfig(toolName);
  const input = (typeof block.input === 'object' && block.input !== null) ? block.input : {};
  const inputStr = (typeof block.input === 'object' && block.input !== null) ? JSON.stringify(block.input, null, 2) : String(block.input || '');
  const summary = getToolSummary(toolName, input) || inputStr.substring(0, 60);
  const richInput = formatToolInput(toolName, typeof block.input === 'object' ? block.input : null);
  const isRunning = !!block.running;

  // Live timer for Task tools while running
  useEffect(() => {
    if (toolName === 'Task' && isRunning && timerElRef.current) {
      const startTime = block.start_time ? block.start_time * 1000 : Date.now();
      const updateTimer = () => {
        if (!timerElRef.current) return;
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const min = Math.floor(elapsed / 60);
        const sec = elapsed % 60;
        timerElRef.current.textContent = `Running... ${min > 0 ? min + 'm ' : ''}${sec}s`;
      };
      updateTimer();
      timerRef.current = setInterval(updateTimer, 1000);
      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
      };
    }
  }, [toolName, isRunning, block.start_time]);

  // Format duration
  let durationStr = '';
  if (block.duration_ms) {
    durationStr = block.duration_ms > 1000 ? (block.duration_ms / 1000).toFixed(1) + 's' : block.duration_ms + 'ms';
  }

  return (
    <div
      className={`chat-tool${isRunning ? ' running' : ''}${expanded ? ' expanded' : ''}`}
      style={{
        '--tool-color': reg.color,
        '--tool-bg': reg.dim,
        '--tool-border': reg.border,
        '--tool-hover': reg.border,
      } as React.CSSProperties}
    >
      <div className="chat-tool-header" onClick={() => setExpanded(e => !e)}>
        <span className="chat-tool-icon" dangerouslySetInnerHTML={{ __html: reg.icon }} />
        <span className="chat-tool-name">{esc(toolName)}</span>
        <span className="chat-tool-summary">{esc(summary)}</span>
        {isRunning && <span className="chat-tool-spinner" />}
        {durationStr && <span className="chat-tool-duration">{durationStr}</span>}
      </div>
      <div className="chat-tool-detail" style={{ display: expanded ? 'block' : 'none' }}>
        {richInput ? (
          <div dangerouslySetInnerHTML={{ __html: richInput }} />
        ) : (
          <pre style={{ margin: 0, padding: '8px 12px', whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: 'var(--text-muted)', fontSize: '11px' }}>
            {esc(inputStr)}
          </pre>
        )}
        {toolName === 'Task' && isRunning && (
          <div ref={timerElRef} className="chat-task-timer" style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '6px', padding: '0 12px 8px' }} />
        )}
      </div>
    </div>
  );
}
