import { useChatContext } from '@/context/ChatContext';

export type SessionMode = 'bypass' | 'plan';

const modes: { value: SessionMode; label: string }[] = [
  { value: 'bypass', label: 'Bypass' },
  { value: 'plan', label: 'Plan' },
];

export function PermissionToggle() {
  const { state, dispatch } = useChatContext();
  const { sessionMode } = state;

  return (
    <div className="chat-permission-toggle">
      <span className="chat-permission-toggle-label">Mode:</span>
      <div className="chat-permission-toggle-btns">
        {modes.map(m => (
          <button
            key={m.value}
            className={`chat-permission-toggle-btn${sessionMode === m.value ? ' active' : ''}`}
            onClick={() => dispatch({ type: 'SET_SESSION_MODE', mode: m.value })}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  );
}
