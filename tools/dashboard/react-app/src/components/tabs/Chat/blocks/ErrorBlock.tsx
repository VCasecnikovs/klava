import { useState } from 'react';
import { renderChatMD } from '../ChatMarkdown';
import type { Block } from '@/context/ChatContext';

export function ErrorBlock({ block }: { block: Block }) {
  const [open, setOpen] = useState(false);

  const msg = block.message || 'Unknown error';
  const subtype = block.subtype || null;
  const stop = block.stop_reason || null;
  const errors = block.errors || [];

  const hasDetail = !!subtype || !!stop || errors.length > 0;

  return (
    <div className="chat-error">
      <div
        className="chat-msg chat-msg-assistant chat-error-body"
        dangerouslySetInnerHTML={{ __html: renderChatMD('Error: ' + msg) }}
      />
      {hasDetail && (
        <div className="chat-error-meta">
          <span
            className="chat-error-meta-toggle"
            role="button"
            onClick={() => setOpen((v) => !v)}
          >
            {subtype ? `[${subtype}]` : '[details]'} {open ? '\u25be' : '\u25b8'}
          </span>
          {open && (
            <div className="chat-error-detail">
              {subtype && <div>subtype: {subtype}</div>}
              {stop && <div>stop_reason: {stop}</div>}
              {errors.length > 0 && (
                <div>
                  <div>errors:</div>
                  {errors.map((e, i) => (
                    <pre key={i} className="chat-error-raw">{e}</pre>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
