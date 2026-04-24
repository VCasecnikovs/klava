import { useState } from 'react';
import { esc } from '@/lib/utils';
import type { Block } from '@/context/ChatContext';

export function UserBlock({ block }: { block: Block }) {
  const [forking, setForking] = useState(false);

  const onFork = () => {
    if (forking) return;
    setForking(true);
    window.dispatchEvent(
      new CustomEvent('chat:fork-from-block', {
        detail: { block_id: block.id },
      })
    );
    // Reset spinner shortly after — the parent handler takes over.
    setTimeout(() => setForking(false), 4000);
  };

  return (
    <div className={`chat-msg chat-msg-user${block.pending ? ' chat-msg-pending' : ''}`}>
      <button
        className="chat-msg-fork-btn"
        onClick={onFork}
        disabled={forking}
        title="Fork: branch a new conversation from this message"
      >
        {forking ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" opacity="0.3" />
            <path d="M22 12a10 10 0 00-10-10" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="18" cy="6" r="3" />
            <circle cx="6" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M18 9v2a4 4 0 01-4 4H6" />
            <path d="M6 9v9" />
          </svg>
        )}
        <span className="chat-msg-fork-label">Fork</span>
      </button>
      {block.text && <div style={{ whiteSpace: 'pre-wrap' }}>{block.text}</div>}
      {block.files && block.files.length > 0 && block.files.map((f, i) => {
        if (f.type?.startsWith('image/') && (f.url || f.thumbUrl)) {
          return (
            <img
              key={i}
              className="chat-msg-image"
              src={(f.url || f.thumbUrl) as string}
              alt={f.name}
              title={f.name}
              onClick={() => window.open(f.url || f.thumbUrl, '_blank')}
            />
          );
        }
        return (
          <div key={i} className="chat-msg-file" dangerouslySetInnerHTML={{
            __html: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>${esc(f.name)}`
          }} />
        );
      })}
    </div>
  );
}
