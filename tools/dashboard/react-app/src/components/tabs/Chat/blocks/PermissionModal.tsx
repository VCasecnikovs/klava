import { useChatContext } from '@/context/ChatContext';

export function PermissionModal() {
  const { state, dispatch, socketRef } = useChatContext();
  const { pendingPermission } = state;

  if (!pendingPermission) return null;

  const handleRespond = (allow: boolean) => {
    if (socketRef.current) socketRef.current.emit('permission_response', { allow });
    dispatch({ type: 'SET_PENDING_PERMISSION', permission: null });
  };

  return (
    <div className="chat-permission" style={{ display: 'flex' }}>
      <div className="chat-permission-inner">
        <div className="chat-permission-title">Permission Required</div>
        <div className="chat-permission-tool">{pendingPermission.tool}</div>
        <div className="chat-permission-desc">{pendingPermission.description}</div>
        <div className="chat-permission-btns">
          <button className="chat-btn chat-btn-deny" onClick={() => handleRespond(false)}>Deny</button>
          <button className="chat-btn chat-btn-allow" onClick={() => handleRespond(true)}>Allow</button>
        </div>
      </div>
    </div>
  );
}
