import { useState } from 'react';
import { esc } from '@/lib/utils';
import type { Block } from '@/context/ChatContext';

export function ThinkingBlock({ block }: { block: Block }) {
  const [expanded, setExpanded] = useState(false);
  const words = block.words || 0;
  const preview = block.preview || '';

  return (
    <div className={`chat-thinking${expanded ? ' expanded' : ''}`}>
      <div
        className="chat-thinking-header"
        onClick={() => setExpanded(e => !e)}
        dangerouslySetInnerHTML={{
          __html: `<span class="chat-thinking-arrow">&#9654;</span>Thinking<span class="chat-thinking-meta">${words} words</span><span class="chat-thinking-preview">${esc(preview)}${preview.length >= 60 ? '...' : ''}</span>`
        }}
      />
      <div
        className="chat-thinking-content"
        style={{ display: expanded ? 'block' : 'none' }}
      >
        {block.text || ''}
      </div>
    </div>
  );
}
