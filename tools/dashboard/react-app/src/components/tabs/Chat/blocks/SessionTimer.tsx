import { useState, useEffect, useRef } from 'react';
import { useChatContext } from '@/context/ChatContext';

function fmt(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return (ms / 1000).toFixed(1) + 's';
}

export function SessionTimer() {
  const { state } = useChatContext();
  const { realtimeStatus, streamStart, realtimeBlocks } = state;
  const [now, setNow] = useState(Date.now());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isStreaming = realtimeStatus === 'streaming';

  useEffect(() => {
    if (!isStreaming) return;
    intervalRef.current = setInterval(() => setNow(Date.now()), 1000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isStreaming]);

  if (!isStreaming) return null;

  const totalMs = streamStart ? now - streamStart : 0;

  // Determine current activity: tool_use running, or thinking, or writing
  let activity = 'thinking';
  let activityDetail = '';
  let symbol = '\u273B'; // ✻ default for thinking

  for (let i = realtimeBlocks.length - 1; i >= 0; i--) {
    const b = realtimeBlocks[i];
    if (b.type === 'tool_use' && b.running) {
      activity = b.tool || 'tool';
      symbol = '\u2736'; // ✶ for tools
      if (b.start_time) {
        activityDetail = fmtMs(now - b.start_time * 1000);
      }
      break;
    }
    if (b.type === 'tool_group' && b.tools) {
      const running = b.tools.find(t => t.running);
      if (running) {
        activity = running.tool || 'tool';
        symbol = '\u2736'; // ✶
        if (running.start_time) {
          activityDetail = fmtMs(now - running.start_time * 1000);
        }
        break;
      }
    }
    // If last block is assistant and streaming, it's writing
    if (b.type === 'assistant' && i === realtimeBlocks.length - 1) {
      activity = 'writing';
      symbol = '\u00b7'; // ·
      break;
    }
  }

  return (
    <div className="chat-session-timer">
      <span className="chat-session-timer-symbol">{symbol}</span>
      <span className="chat-session-timer-activity">{activity}</span>
      {activityDetail && <span className="chat-session-timer-detail">{activityDetail}</span>}
      <span className="chat-session-timer-total">{fmt(totalMs)}</span>
    </div>
  );
}
