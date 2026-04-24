import { useState } from 'react';
import type { Block } from '@/context/ChatContext';

interface ThinkingBubbleProps {
  blocks: Block[];
}

function getFirstSentence(blocks: Block[]): string {
  for (const b of blocks) {
    const text = b.text || '';
    if (!text) continue;
    const dotIdx = text.indexOf('.');
    if (dotIdx > 0 && dotIdx < 80) return text.substring(0, dotIdx + 1);
    return text.substring(0, 80) + (text.length > 80 ? '...' : '');
  }
  return '';
}

export function ThinkingBubble({ blocks }: ThinkingBubbleProps) {
  const [expanded, setExpanded] = useState(false);

  const totalWords = blocks.reduce((sum, b) => sum + (b.words || 0), 0);
  const preview = getFirstSentence(blocks);

  return (
    <div className={`chat-thinking-bubble${expanded ? ' expanded' : ''}`}>
      <div
        className="chat-thinking-bubble-header"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="chat-thinking-arrow">&#9654;</span>
        {expanded ? (
          <span>Thinking</span>
        ) : (
          <span className="chat-thinking-bubble-pass-preview">{preview}</span>
        )}
        <span className="chat-thinking-bubble-meta" style={{ marginLeft: 'auto' }}>
          {totalWords} words
        </span>
      </div>
      {expanded && (
        <div className="chat-thinking-bubble-body">
          {blocks.map((block, idx) => {
            const words = block.words || 0;
            return (
              <div key={block.id} className="chat-thinking-bubble-pass">
                <div className="chat-thinking-bubble-pass-header" style={{ cursor: 'default' }}>
                  <span className="chat-thinking-bubble-pass-label">
                    Pass {idx + 1}
                  </span>
                  <span className="chat-thinking-bubble-pass-meta">
                    {words} words
                  </span>
                </div>
                <div className="chat-thinking-bubble-pass-content">
                  {block.text || ''}
                </div>
                {idx < blocks.length - 1 && <div className="chat-thinking-bubble-sep" />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
