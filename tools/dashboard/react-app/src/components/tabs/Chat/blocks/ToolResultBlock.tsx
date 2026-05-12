import { useState } from 'react';
import { getToolConfig, formatToolResult, getToolMeta } from '../toolRegistry';
import type { Block } from '@/context/ChatContext';

export function ToolResultBlock({ block }: { block: Block }) {
  const content = block.content || '';
  if (!content) return null;

  const toolName = block.tool || '';
  const reg = getToolConfig(toolName);
  const meta = getToolMeta(toolName);
  const richResult = formatToolResult(toolName, content, block.input);
  const [collapsed, setCollapsed] = useState(content.length > 200);

  if (richResult) {
    return (
      <div
        className="chat-tool-result"
        style={{ '--result-color': reg.color + '60' } as React.CSSProperties}
        dangerouslySetInnerHTML={{ __html: richResult }}
      />
    );
  }

  return (
    <div
      className={`chat-tool-result${collapsed ? ' collapsed' : ''}`}
      style={{ '--result-color': reg.color + '60' } as React.CSSProperties}
    >
      <div
        className="chat-tool-result-header"
        onClick={(e) => { e.stopPropagation(); setCollapsed(c => !c); }}
      >
        <span className="chat-tool-result-arrow">&#9654;</span>
        <span>{meta.category} result</span>
        <span className="chat-tool-result-count">{content.length} chars</span>
      </div>
      <div className="chat-tool-result-content">
        {content}
      </div>
    </div>
  );
}
