import { useState } from 'react';
import { useChatContext } from '@/context/ChatContext';

const CHANNEL_BADGES: Record<string, { icon: string; color: string }> = {
  'Telegram': { icon: '✈️', color: '#2AABEE' },
  'Signal': { icon: '🔒', color: '#3A76F0' },
  'Gmail': { icon: '📧', color: '#EA4335' },
  'WhatsApp': { icon: '💬', color: '#25D366' },
};

export function CommsApprovalModal() {
  const { state, dispatch, socketRef } = useChatContext();
  const { pendingComms } = state;
  const [editing, setEditing] = useState(false);
  const [editedMessage, setEditedMessage] = useState('');

  if (!pendingComms) return null;

  const badge = CHANNEL_BADGES[pendingComms.channel] || { icon: '📤', color: '#888' };

  const handleApprove = () => {
    if (socketRef.current) {
      socketRef.current.emit('comms_approval', {
        approved: true,
        edited_message: editing ? editedMessage : '',
        tab_id: state.tabId,
      });
    }
    dispatch({ type: 'SET_PENDING_COMMS', comms: null });
  };

  const handleReject = () => {
    if (socketRef.current) {
      socketRef.current.emit('comms_approval', {
        approved: false,
        tab_id: state.tabId,
      });
    }
    dispatch({ type: 'SET_PENDING_COMMS', comms: null });
  };

  const handleEdit = () => {
    setEditedMessage(pendingComms.message);
    setEditing(true);
  };

  return (
    <div className="comms-approval-overlay">
      <div className="comms-approval-modal">
        <div className="comms-approval-header">
          <span className="comms-approval-badge" style={{ background: badge.color }}>
            {badge.icon} {pendingComms.channel}
          </span>
          <span className="comms-approval-title">Outbound Message</span>
        </div>
        {pendingComms.recipient && (
          <div className="comms-approval-recipient">
            To: <strong>{pendingComms.recipient}</strong>
          </div>
        )}
        <div className="comms-approval-body">
          {!editing ? (
            <div className="comms-approval-message">{pendingComms.message}</div>
          ) : (
            <textarea
              className="comms-approval-edit"
              value={editedMessage}
              onChange={(e) => setEditedMessage(e.target.value)}
              autoFocus
              rows={Math.min(12, Math.max(3, editedMessage.split('\n').length + 1))}
            />
          )}
        </div>
        <div className="comms-approval-actions">
          <button className="comms-approval-btn comms-btn-reject" onClick={handleReject}>
            Block
          </button>
          {!editing && (
            <button className="comms-approval-btn comms-btn-edit" onClick={handleEdit}>
              Edit
            </button>
          )}
          <button className="comms-approval-btn comms-btn-approve" onClick={handleApprove}>
            {editing ? 'Send Edited' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  );
}
