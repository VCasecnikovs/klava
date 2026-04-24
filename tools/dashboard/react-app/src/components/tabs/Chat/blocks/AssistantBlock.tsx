import { useState, useCallback, useMemo } from 'react';
import { renderChatMD } from '../ChatMarkdown';
import { hasArtifact, parseArtifactContent } from '../artifacts/parseArtifact';
import { ArtifactCard } from '../artifacts/ArtifactCard';
import { api } from '@/api/client';
import type { Block } from '@/context/ChatContext';

export function AssistantBlock({ block }: { block: Block }) {
  const text = block.text || '';
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedbackText, setFeedbackText] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (submitted) return;
    setSubmitted(true);
    setShowFeedback(false);
    try {
      await api.dislike(block.id, (text).substring(0, 300), feedbackText);
    } catch (e) {
      console.error('Failed to submit dislike:', e);
    }
  }, [block.id, text, feedbackText, submitted]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === 'Escape') setShowFeedback(false);
  }, [handleSubmit]);

  // Render message content
  let content: JSX.Element;

  if (!hasArtifact(text) && !text.includes('```a2ui')) {
    content = (
      <div
        className="chat-msg chat-msg-assistant"
        dangerouslySetInnerHTML={{ __html: renderChatMD(text) }}
      />
    );
  } else if (text.includes('```a2ui') && !hasArtifact(text)) {
    content = (
      <div
        className="chat-msg chat-msg-assistant"
        dangerouslySetInnerHTML={{ __html: renderChatMD(text) }}
      />
    );
  } else {
    const segments = parseArtifactContent(text);
    content = (
      <div className="chat-msg chat-msg-assistant">
        {segments.map((seg, i) =>
          seg.type === 'markdown' ? (
            <span key={i} dangerouslySetInnerHTML={{ __html: seg.html }} />
          ) : (
            <ArtifactCard key={i} artifact={seg.ref} />
          )
        )}
      </div>
    );
  }

  return (
    <div className="chat-msg-with-actions">
      {content}
      <button
        className={`chat-dislike-btn${submitted ? ' submitted' : ''}`}
        onClick={() => {
          if (submitted) return;
          setShowFeedback(s => !s);
        }}
        title={submitted ? 'Feedback sent' : 'Mark as bad'}
      >
        {submitted ? '✓' : '👎'}
      </button>
      {showFeedback && (
        <div className="chat-feedback-form">
          <input
            autoFocus
            value={feedbackText}
            onChange={e => setFeedbackText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="What went wrong?"
          />
          <button className="chat-feedback-submit" onClick={handleSubmit}>
            Send
          </button>
        </div>
      )}
    </div>
  );
}
