import { useState } from 'react';
import { getToolConfig, formatToolResult, getToolMeta } from '../toolRegistry';
import type { Block } from '@/context/ChatContext';

/**
 * UX policy:
 * - Tool results that are short (<= 140 chars after trimming) render as a
 *   compact chip that visually attaches under the tool-use row. No expand/
 *   collapse, no extra chrome. Most successful "OK", "✓ wrote N bytes",
 *   "No matches" land here.
 * - Long results render the full panel with a header showing category +
 *   character count and a click-to-expand body. The rail color matches the
 *   tool's category so the connection is obvious at a glance.
 * - We do *not* render anything when the content is empty.
 */

function looksLikeError(content: string): boolean {
  const head = content.slice(0, 200).toLowerCase();
  return (
    /\b(error|traceback|failed|failure|exception|denied|forbidden|unauthorized|fatal|cannot|could not|couldn't)\b/.test(head)
    || /\b(not found|no such (file|directory|host)|does not exist|permission denied|connection refused|timed out|timeout)\b/.test(head)
    || /^✗ /.test(head)
  );
}

export function ToolResultBlock({ block }: { block: Block }) {
  const content = block.content || '';
  if (!content) return null;

  const toolName = block.tool || '';
  const reg = getToolConfig(toolName);
  const meta = getToolMeta(toolName);
  const richResult = formatToolResult(toolName, content, block.input);
  const trimmed = content.trim();
  const isShort = trimmed.length <= 140 && !trimmed.includes('\n');
  const isError = looksLikeError(content);
  const [collapsed, setCollapsed] = useState(content.length > 200);

  if (isShort && !richResult) {
    return (
      <div
        className={`chat-tool-result-chip${isError ? ' err' : ''}`}
        style={{ '--result-color': reg.color } as React.CSSProperties}
      >
        <span className="chat-tool-result-chip-mark">{isError ? '✗' : '✓'}</span>
        <span className="chat-tool-result-chip-text">{trimmed}</span>
      </div>
    );
  }

  if (richResult) {
    return (
      <div
        className={`chat-tool-result${isError ? ' err' : ''}`}
        style={{ '--result-color': reg.color + '60' } as React.CSSProperties}
        dangerouslySetInnerHTML={{ __html: richResult }}
      />
    );
  }

  return (
    <div
      className={`chat-tool-result${collapsed ? ' collapsed' : ''}${isError ? ' err' : ''}`}
      style={{ '--result-color': reg.color + '60' } as React.CSSProperties}
    >
      <button
        type="button"
        className="chat-tool-result-header"
        onClick={(e) => { e.stopPropagation(); setCollapsed(c => !c); }}
      >
        <span className="chat-tool-result-arrow">{collapsed ? '›' : '⌃'}</span>
        <span>{meta.category} result</span>
        <span className="chat-tool-result-count">{content.length} chars</span>
      </button>
      <div className="chat-tool-result-content">
        {content}
      </div>
    </div>
  );
}
