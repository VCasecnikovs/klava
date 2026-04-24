import { useEffect, useRef } from 'react';
import { renderChatMD } from '../ChatMarkdown';
import { useChatContext } from '@/context/ChatContext';
import type { Block } from '@/context/ChatContext';

export function StreamingBlock({ block }: { block: Block }) {
  const elRef = useRef<HTMLDivElement>(null);
  const { streamingTextRef } = useChatContext();

  // Register ref so socket handler can update innerHTML directly
  useEffect(() => {
    streamingTextRef.current = elRef.current;
    return () => {
      if (streamingTextRef.current === elRef.current) {
        streamingTextRef.current = null;
      }
    };
  }, [streamingTextRef]);

  // Initial render with current text
  useEffect(() => {
    if (elRef.current) {
      elRef.current.innerHTML = renderChatMD(block.text || '');
    }
  }, []); // Only on mount - subsequent updates go through ref

  return (
    <div
      ref={elRef}
      className="chat-msg chat-msg-assistant chat-streaming-cursor"
    />
  );
}
