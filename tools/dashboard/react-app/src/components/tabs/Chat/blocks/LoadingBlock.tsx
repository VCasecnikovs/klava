import { useEffect, useRef } from 'react';
import { useChatContext } from '@/context/ChatContext';

export function LoadingBlock() {
  const { state } = useChatContext();
  const timerRef = useRef<HTMLSpanElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const startTime = state.streamStart || Date.now();
    const update = () => {
      if (!timerRef.current) return;
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      const min = Math.floor(elapsed / 60);
      const sec = elapsed % 60;
      timerRef.current.textContent = 'Thinking... ' + (min > 0 ? min + 'm ' : '') + sec + 's';
    };
    update();
    intervalRef.current = setInterval(update, 1000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [state.streamStart]);

  return (
    <div className="chat-loading" id="chat-loading">
      <div className="chat-loading-dots"><span /><span /><span /></div>
      {' '}
      <span ref={timerRef} id="chat-stream-status">Thinking... 0s</span>
    </div>
  );
}
