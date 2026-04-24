import { useEffect, useMemo, useRef, useState } from 'react';
import { useChatContext, type Block } from '@/context/ChatContext';
import { api } from '@/api/client';

// Context window (tokens) per UI model key — used as fallback if the live
// backend response doesn't carry `limit`. When unsure, assume 1M: better to
// underestimate usage % than to spook the user with a false "90% full".
const MODEL_WINDOW: Record<string, number> = {
  opus: 1_000_000,
  'opus[1m]': 1_000_000,
  sonnet: 1_000_000,
  'sonnet[1m]': 1_000_000,
  haiku: 1_000_000,
};

function lastUsage(blocks: Block[]): Block['usage'] | null {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.type === 'cost' && b.usage) return b.usage;
  }
  return null;
}

export function ContextUsage() {
  const { state } = useChatContext();
  const { realtimeBlocks, historyBlocks, model, tabId, realtimeStatus } = state;

  // Live snapshot from backend SDK client
  const [live, setLive] = useState<{ tokens: number; limit: number; percent: number | null } | null>(null);
  const inflightRef = useRef(false);

  useEffect(() => {
    if (!tabId) { setLive(null); return; }
    let cancelled = false;

    const poll = async () => {
      if (inflightRef.current) return;
      inflightRef.current = true;
      try {
        const res = await api.chatContextUsage(tabId);
        if (cancelled) return;
        if (res.ok && res.tokens > 0) {
          setLive({ tokens: res.tokens, limit: res.limit || 0, percent: res.percent });
        }
      } catch {
        // Backend returns 404 when no active SDK client — silently fall back
      } finally {
        inflightRef.current = false;
      }
    };

    poll();
    // Faster during streaming; slow idle poll
    const interval = realtimeStatus === 'streaming' ? 5000 : 30000;
    const id = setInterval(poll, interval);
    return () => { cancelled = true; clearInterval(id); };
  }, [tabId, realtimeStatus]);

  // Derived fallback from last cost block's usage
  const fallback = useMemo(() => {
    const usage = lastUsage(realtimeBlocks) || lastUsage(historyBlocks);
    if (!usage) return null;
    const input = Number(usage.input_tokens || 0);
    const cacheRead = Number(usage.cache_read_input_tokens || 0);
    const cacheCreate = Number(usage.cache_creation_input_tokens || 0);
    const used = input + cacheRead + cacheCreate;
    if (!used) return null;
    const window = MODEL_WINDOW[model] ?? 1_000_000;
    return { tokens: used, limit: window, percent: Math.min(100, Math.round((used / window) * 100)) };
  }, [realtimeBlocks, historyBlocks, model]);

  const info = live || fallback;
  if (!info) return null;

  const limit = info.limit || MODEL_WINDOW[model] || 1_000_000;
  const pct = info.percent != null
    ? Math.min(100, info.percent)
    : Math.min(100, Math.round((info.tokens / limit) * 100));
  const tone = pct >= 90 ? 'danger' : pct >= 80 ? 'warn' : 'info';

  const title = `${info.tokens.toLocaleString()} / ${limit.toLocaleString()} tokens · ${pct}%${live ? ' (live)' : ' (from last turn)'}`;

  return (
    <span
      className={`chat-context-usage chat-context-usage-${tone}`}
      title={title}
    >
      {pct}%
    </span>
  );
}
