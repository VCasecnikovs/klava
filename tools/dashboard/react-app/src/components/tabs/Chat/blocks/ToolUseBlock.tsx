import { useState, useEffect, useRef } from 'react';
import { esc } from '@/lib/utils';
import { getToolConfig, getToolSummary, formatToolInput, getToolMeta } from '../toolRegistry';
import type { Block } from '@/context/ChatContext';

type Status = 'running' | 'ok' | 'failed' | 'asks';

function deriveStatus(block: Block): Status {
  if (block.running) return 'running';
  // Future: pipe through error status from backend. For now, treat tool blocks
  // as "ok" once they have a duration and aren't running. The merged result
  // block elsewhere carries failure context if any.
  return 'ok';
}

function formatDuration(ms?: number): string {
  if (!ms) return '';
  if (ms >= 60_000) {
    const m = Math.floor(ms / 60000);
    const s = Math.round((ms % 60000) / 1000);
    return `${m}m ${s}s`;
  }
  return ms > 1000 ? (ms / 1000).toFixed(1) + 's' : ms + 'ms';
}

const AUTO_EXPAND_TOOLS = new Set(['Task', 'Agent', 'Bash', 'BashCodeExecution', 'CodeExecution', 'TextEditorCodeExecution']);

export function ToolUseBlock({ block }: { block: Block }) {
  const toolName = block.tool || '';
  const isRunning = !!block.running;
  const [expanded, setExpanded] = useState(isRunning && AUTO_EXPAND_TOOLS.has(toolName));
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const liveTimerElRef = useRef<HTMLSpanElement>(null);

  const reg = getToolConfig(toolName);
  const meta = getToolMeta(toolName);
  const input = (typeof block.input === 'object' && block.input !== null) ? block.input : {};
  const inputStr = (typeof block.input === 'object' && block.input !== null) ? JSON.stringify(block.input, null, 2) : String(block.input || '');
  const summary = getToolSummary(toolName, input) || inputStr.substring(0, 80);
  const richInput = formatToolInput(toolName, typeof block.input === 'object' ? block.input : null);
  const status = deriveStatus(block);

  useEffect(() => {
    if (!isRunning || !liveTimerElRef.current) return;
    const start = block.start_time ? block.start_time * 1000 : Date.now();
    const tick = () => {
      if (!liveTimerElRef.current) return;
      const elapsed = Math.floor((Date.now() - start) / 1000);
      const min = Math.floor(elapsed / 60);
      const sec = elapsed % 60;
      liveTimerElRef.current.textContent = min > 0 ? `▶ ${min}:${String(sec).padStart(2, '0')}` : `▶ 0:${String(sec).padStart(2, '0')}`;
    };
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isRunning, block.start_time]);

  const durationStr = formatDuration(block.duration_ms);

  return (
    <div
      className={`chat-tool chat-tool-row chat-tool-${status}${expanded ? ' expanded' : ''}`}
      style={{
        '--tool-color': reg.color,
      } as React.CSSProperties}
    >
      <button
        type="button"
        className="chat-tool-row-head"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
        aria-label={`${toolName} · ${summary || meta.verb}`}
      >
        <span className="chat-tool-rail" aria-hidden="true" />
        <span className="chat-tool-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: reg.icon }} />
        <span className="chat-tool-category">{esc(meta.category)}</span>
        <span className="chat-tool-summary" title={summary}>{esc(summary || meta.action || meta.verb)}</span>
        <span className="chat-tool-row-meta">
          {meta.permission === 'approval' && status !== 'running' && (
            <span className="chat-tool-perm-dot" title="Tool typically asks for approval" />
          )}
          {isRunning ? (
            <span ref={liveTimerElRef} className="chat-tool-live">▶ 0:00</span>
          ) : durationStr ? (
            <span className="chat-tool-duration">{status === 'failed' ? '✗ ' : ''}{durationStr}</span>
          ) : null}
          <span className="chat-tool-chevron" aria-hidden="true">{expanded ? '⌃' : '›'}</span>
        </span>
      </button>
      {expanded && (
        <div className="chat-tool-detail">
          <div className="chat-tool-detail-meta">
            <span className="chat-tool-detail-name">{esc(toolName)}</span>
            {meta.origin && <span className="chat-tool-origin">{esc(meta.origin)}</span>}
            <span className={`chat-tool-permission ${meta.permission}`}>{meta.permission === 'approval' ? 'asks for approval' : meta.permission}</span>
          </div>
          {richInput ? (
            <div dangerouslySetInnerHTML={{ __html: richInput }} />
          ) : (
            <pre className="chat-tool-detail-raw">{esc(inputStr)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
