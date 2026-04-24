import { useState } from 'react';
import { useChatContext, type Block } from '@/context/ChatContext';
import { renderChatMD } from '../ChatMarkdown';

interface PlanReviewBlockProps {
  assistantBlock?: Block;
  planBlock: Block;
}

export function PlanReviewBlock({ assistantBlock, planBlock }: PlanReviewBlockProps) {
  const { socketRef, state } = useChatContext();
  const [responded, setResponded] = useState(!!planBlock.answered);
  const [showChangesInput, setShowChangesInput] = useState(false);
  const [changesText, setChangesText] = useState('');

  const planContent = planBlock.content || assistantBlock?.text || '';

  const handleApprove = () => {
    if (socketRef.current) {
      socketRef.current.emit('plan_approval', {
        approved: true,
        tab_id: state.tabId,
      });
      setResponded(true);
    }
  };

  const handleRequestChanges = () => {
    setShowChangesInput(true);
  };

  const handleSubmitChanges = () => {
    if (socketRef.current && changesText.trim()) {
      socketRef.current.emit('plan_approval', {
        approved: false,
        changes: changesText.trim(),
        tab_id: state.tabId,
      });
      setResponded(true);
    }
  };

  return (
    <div className={`chat-plan-review${responded ? ' chat-plan-review-responded' : ''}`}>
      <div className="chat-plan-review-header">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        <span>Plan Ready for Review</span>
      </div>
      <div
        className="chat-plan-review-content"
        dangerouslySetInnerHTML={{ __html: renderChatMD(planContent) }}
      />
      {!responded && !showChangesInput && (
        <div className="chat-plan-review-actions">
          <button className="chat-plan-review-btn chat-plan-review-btn-changes" onClick={handleRequestChanges}>
            Request Changes
          </button>
          <button className="chat-plan-review-btn chat-plan-review-btn-approve" onClick={handleApprove}>
            Approve Plan
          </button>
        </div>
      )}
      {!responded && showChangesInput && (
        <div className="chat-plan-review-changes">
          <input
            type="text"
            className="chat-plan-review-changes-input"
            placeholder="What would you like to change?"
            value={changesText}
            onChange={(e) => setChangesText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmitChanges(); }}
            autoFocus
          />
          <div className="chat-plan-review-actions">
            <button className="chat-plan-review-btn chat-plan-review-btn-changes" onClick={() => setShowChangesInput(false)}>
              Cancel
            </button>
            <button
              className="chat-plan-review-btn chat-plan-review-btn-approve"
              onClick={handleSubmitChanges}
              disabled={!changesText.trim()}
            >
              Send Feedback
            </button>
          </div>
        </div>
      )}
      {responded && (
        <div className="chat-plan-review-responded-label">
          {planBlock.answered !== false ? 'Plan approved' : 'Changes requested'}
        </div>
      )}
    </div>
  );
}
