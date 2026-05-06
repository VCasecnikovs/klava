import { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '@/api/client';

interface Props {
  tabId: string | null;
}

const PANEL_BG = '#18181b';
const BORDER = '#27272a';
const HOVER = '#1c1917';
const ACCENT = '#f59e0b';

export function ScopePicker({ tabId }: Props) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<string | null>(null);
  const [scopes, setScopes] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Load current scope for tab
  useEffect(() => {
    if (!tabId) { setScope(null); return; }
    let cancelled = false;
    api.chatScopeGet(tabId)
      .then(r => { if (!cancelled) setScope(r.scope); })
      .catch(() => { if (!cancelled) setScope(null); });
    return () => { cancelled = true; };
  }, [tabId]);

  // Lazy-load scope list when opened
  useEffect(() => {
    if (!open || scopes.length > 0) return;
    api.scopes()
      .then(r => setScopes(r.scopes))
      .catch(e => setLoadError(String(e)));
  }, [open, scopes.length]);

  // Click-outside to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return scopes;
    return scopes.filter(s => s.toLowerCase().includes(q));
  }, [filter, scopes]);

  const choose = async (next: string | null) => {
    if (!tabId) return;
    try {
      await api.chatScopeSet(tabId, next);
      setScope(next);
    } catch (e) {
      console.error('Failed to set scope', e);
    }
    setOpen(false);
    setFilter('');
  };

  const label = scope ? scope.replace(/\/$/, '').split('/').pop() || scope : 'no scope';
  const tooltip = scope
    ? `Scope: ${scope}\nClick to change. Shift-click to open project page.`
    : 'No scope. Pick one to give Klava project context for this chat.';

  const handleClick = (e: React.MouseEvent) => {
    if (scope && (e.shiftKey || e.metaKey)) {
      // Jump to Scopes tab and select this scope.
      e.preventDefault();
      window.dispatchEvent(
        new CustomEvent('scopes:open', { detail: { scope } })
      );
      window.location.hash = 'scopes';
      return;
    }
    setOpen(o => !o);
  };

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        ref={buttonRef}
        type="button"
        onClick={handleClick}
        title={tooltip}
        disabled={!tabId}
        style={{
          background: scope ? '#422006' : 'transparent',
          color: scope ? '#fbbf24' : '#a1a1aa',
          border: `1px solid ${scope ? '#a16207' : BORDER}`,
          fontSize: 11,
          padding: '3px 10px',
          borderRadius: 10,
          cursor: tabId ? 'pointer' : 'not-allowed',
          opacity: tabId ? 1 : 0.5,
          maxWidth: 240,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontWeight: scope ? 600 : 400,
        }}
      >
        {scope ? '📁 ' : ''}{label}
      </button>

      {open && (
        <div
          ref={menuRef}
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 6px)',
            left: 0,
            width: 280,
            maxHeight: 320,
            background: PANEL_BG,
            border: `1px solid ${BORDER}`,
            borderRadius: 6,
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
            zIndex: 1000,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ padding: 8, borderBottom: `1px solid ${BORDER}` }}>
            <input
              type="text"
              autoFocus
              placeholder="Filter scopes..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{
                width: '100%',
                background: '#0a0a0c',
                border: `1px solid ${BORDER}`,
                color: '#fafafa',
                padding: '4px 8px',
                fontSize: 12,
                borderRadius: 4,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ overflow: 'auto', flex: 1 }}>
            <button
              type="button"
              onClick={() => choose(null)}
              style={menuItemStyle(scope === null)}
            >
              <span style={{ color: '#71717a' }}>○</span>
              <span>(no scope)</span>
            </button>

            {loadError && (
              <div style={{ padding: 10, color: '#f87171', fontSize: 11 }}>
                Failed to load: {loadError}
              </div>
            )}
            {!loadError && scopes.length === 0 && (
              <div style={{ padding: 10, color: '#71717a', fontSize: 11 }}>
                Loading scopes...
              </div>
            )}
            {filtered.map(s => (
              <button
                key={s}
                type="button"
                onClick={() => choose(s)}
                style={menuItemStyle(s === scope)}
              >
                <span style={{ color: s === scope ? ACCENT : '#52525b' }}>
                  {s === scope ? '●' : '○'}
                </span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s}</span>
              </button>
            ))}
            {!loadError && scopes.length > 0 && filtered.length === 0 && (
              <div style={{ padding: 10, color: '#71717a', fontSize: 11 }}>
                No matches.
              </div>
            )}
          </div>

          <div style={{
            padding: '6px 10px', borderTop: `1px solid ${BORDER}`,
            color: '#52525b', fontSize: 10,
          }}>
            Affects next cold start. Already-running session keeps current context.
          </div>
        </div>
      )}
    </div>
  );
}

function menuItemStyle(active: boolean): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    background: active ? HOVER : 'transparent',
    border: 'none',
    color: active ? '#fafafa' : '#d4d4d8',
    fontSize: 12,
    padding: '6px 10px',
    cursor: 'pointer',
    textAlign: 'left',
  };
}
