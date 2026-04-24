import { useEffect, useState, useCallback, useRef } from 'react';

interface QuotePopoverProps {
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export function QuotePopover({ containerRef }: QuotePopoverProps) {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const selectedTextRef = useRef('');
  const popoverRef = useRef<HTMLDivElement>(null);

  const handleMouseUp = useCallback(() => {
    // Small delay to let selection finalize
    requestAnimationFrame(() => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) {
        setVisible(false);
        return;
      }

      const text = selection.toString().trim();
      if (!text) {
        setVisible(false);
        return;
      }

      // Check if selection is inside chat messages
      const range = selection.getRangeAt(0);
      const container = containerRef.current;
      if (!container) return;

      const ancestor = range.commonAncestorContainer;
      const el = ancestor instanceof Element ? ancestor : ancestor.parentElement;
      if (!el) return;

      // Must be inside a .chat-msg within our container
      const msgEl = el.closest('.chat-msg');
      if (!msgEl || !container.contains(msgEl)) {
        setVisible(false);
        return;
      }

      selectedTextRef.current = text;

      const rect = range.getBoundingClientRect();
      setPosition({
        top: rect.top - 36,
        left: rect.left + rect.width / 2,
      });
      setVisible(true);
    });
  }, [containerRef]);

  const handleQuote = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const text = selectedTextRef.current;
    if (!text) return;

    window.dispatchEvent(new CustomEvent('chat:quote', { detail: { text } }));
    window.getSelection()?.removeAllRanges();
    setVisible(false);
  }, []);

  // Hide on mousedown outside popover
  const handleMouseDown = useCallback((e: MouseEvent) => {
    if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
      setVisible(false);
    }
  }, []);

  // Hide on scroll
  const handleScroll = useCallback(() => {
    setVisible(false);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.addEventListener('mouseup', handleMouseUp);
    container.addEventListener('scroll', handleScroll);
    document.addEventListener('mousedown', handleMouseDown);

    return () => {
      container.removeEventListener('mouseup', handleMouseUp);
      container.removeEventListener('scroll', handleScroll);
      document.removeEventListener('mousedown', handleMouseDown);
    };
  }, [containerRef, handleMouseUp, handleMouseDown, handleScroll]);

  if (!visible) return null;

  return (
    <div
      ref={popoverRef}
      className="quote-popover"
      style={{ top: position.top, left: position.left }}
      onMouseDown={(e) => e.preventDefault()}
      onClick={handleQuote}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
        <path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z" />
      </svg>
      Quote
    </div>
  );
}
