import { useEffect, useState } from 'react';
import type { Block } from '@/context/ChatContext';

const DOT = ' \u00b7 ';

function fmtResetsIn(resetsAt: number | null | undefined, now: number): string | null {
  if (!resetsAt) return null;
  const delta = resetsAt - now;
  if (delta <= 0) return 'now';
  if (delta < 60) return `${Math.floor(delta)}s`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m`;
  const h = Math.floor(delta / 3600);
  const m = Math.floor((delta % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export function RateLimitBlock({ block }: { block: Block }) {
  const status = block.status || 'unknown';
  const rlType = block.rate_limit_type || '';
  const util = block.utilization;
  const resetsAt = block.resets_at ?? null;
  const overageStatus = block.overage_status || '';
  const overageResets = block.overage_resets_at ?? null;
  const overageReason = block.overage_disabled_reason || null;

  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 15_000);
    return () => clearInterval(id);
  }, []);

  const severity =
    status === 'rejected' ? 'rejected' : status === 'allowed_warning' ? 'warning' : 'info';

  const label =
    status === 'rejected'
      ? 'Rate limit reached'
      : status === 'allowed_warning'
      ? 'Rate limit warning'
      : `Rate limit: ${status}`;

  const resetsIn = fmtResetsIn(resetsAt, now);
  const overageIn = fmtResetsIn(overageResets, now);
  const utilPct = typeof util === 'number' ? Math.round(util * 100) : null;

  const parts: string[] = [];
  if (rlType) parts.push(rlType);
  if (utilPct != null) parts.push(`${utilPct}% used`);
  if (resetsIn) parts.push(`resets in ${resetsIn}`);
  if (overageStatus && overageStatus !== 'allowed') {
    let s = `overage: ${overageStatus}`;
    if (overageIn) s += ` (resets ${overageIn})`;
    if (overageReason) s += ` - ${overageReason}`;
    parts.push(s);
  }

  return (
    <div className={`chat-ratelimit chat-ratelimit-${severity}`}>
      <div className="chat-ratelimit-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div className="chat-ratelimit-text">
        <span className="chat-ratelimit-label">{label}</span>
        {parts.length > 0 && <span className="chat-ratelimit-dim">{DOT + parts.join(DOT)}</span>}
      </div>
    </div>
  );
}
