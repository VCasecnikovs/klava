import { useEffect, useState } from 'react';
import type { Block } from '@/context/ChatContext';

export function CompactionBlock({ block }: { block: Block }) {
  const state = (block as unknown as { state?: string }).state || 'running';
  const trigger = (block as unknown as { trigger?: string }).trigger || 'auto';
  const startTime = (block as unknown as { start_time?: number }).start_time;
  const durationSec = (block as unknown as { duration_sec?: number }).duration_sec;

  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (state !== 'running' || !startTime) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, [state, startTime]);

  const running = state === 'running';
  const elapsed = running && startTime ? Math.max(0, Math.floor(now - startTime)) : null;
  const doneSecs = typeof durationSec === 'number' ? Math.round(durationSec) : null;

  const triggerLabel = trigger === 'manual' ? 'manual' : 'auto';

  return (
    <div className={`chat-compaction${running ? ' chat-compaction-running' : ''}`}>
      <div className="chat-compaction-icon">
        {running ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2v4" />
            <path d="M12 18v4" />
            <path d="M4.93 4.93l2.83 2.83" />
            <path d="M16.24 16.24l2.83 2.83" />
            <path d="M2 12h4" />
            <path d="M18 12h4" />
            <path d="M4.93 19.07l2.83-2.83" />
            <path d="M16.24 7.76l2.83-2.83" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
      </div>
      <div className="chat-compaction-text">
        {running ? (
          <>Compacting context ({triggerLabel}){elapsed !== null ? ` - ${elapsed}s` : ''}...</>
        ) : (
          <>Context compacted ({triggerLabel}){doneSecs !== null ? ` - ${doneSecs}s` : ''}</>
        )}
      </div>
    </div>
  );
}
