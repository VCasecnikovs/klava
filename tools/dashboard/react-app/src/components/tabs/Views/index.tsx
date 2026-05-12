import { useState, useMemo, useEffect, useRef } from 'react';
import { useViews } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { ViewsViewer } from './ViewsViewer';
import { esc } from '@/lib/utils';
import { showToast } from '@/components/shared/Toast';
import { api } from '@/api/client';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ViewsDataObj = any;

interface Props {
  pendingView?: { url?: string; filename?: string; title: string } | null;
  onPendingViewConsumed?: () => void;
}

export function ViewsTab({ pendingView, onPendingViewConsumed }: Props = {}) {
  const { data, refetch } = useViews(true);
  const [viewing, setViewing] = useState<{ filename?: string; url?: string; title: string } | null>(null);

  // Consume pending view passed down from App (set by SocketIO or CustomEvent)
  useEffect(() => {
    if (pendingView) {
      setViewing(pendingView);
      onPendingViewConsumed?.();
    }
  }, [pendingView, onPendingViewConsumed]);

  const kpis = useMemo(() => {
    if (!data) return [];
    const m = (data as ViewsDataObj).metrics || {};
    return [
      { val: m.total || 0, label: 'Total Views' },
      { val: m.today || 0, label: 'Today' },
    ];
  }, [data]);

  if (!data) return <div className="empty">Loading views...</div>;

  // Viewer mode
  if (viewing) {
    return (
      <ViewsViewer
        filename={viewing.filename}
        url={viewing.url}
        title={viewing.title}
        onBack={() => setViewing(null)}
      />
    );
  }

  // List mode
  const views: ViewsDataObj[] = (data as ViewsDataObj).views || [];

  return (
    <>
      <KPIRow kpis={kpis} />

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        HTML Views
        <button
          className="filter-btn"
          onClick={() => { refetch(); showToast('Refreshing...'); }}
          style={{ fontSize: 11, padding: '2px 8px', cursor: 'pointer' }}
        >
          Refresh
        </button>
      </div>

      {views.length === 0 ? (
        <div className="empty">No views generated yet. Use html-view skill to create views.</div>
      ) : (
        <div>
          {views.map((v: ViewsDataObj) => (
            <div
              key={v.filename}
              className="panel"
              style={{ marginBottom: 8, cursor: 'pointer', transition: 'border-color 0.15s' }}
              onClick={() => setViewing({ filename: v.filename, title: v.title })}
              onMouseOver={e => (e.currentTarget.style.borderColor = 'var(--border-hover)')}
              onMouseOut={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{
                    fontWeight: 600, color: 'var(--text)', marginBottom: 2,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {esc(v.title)}
                  </div>
                  {v.subtitle && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                      {esc(v.subtitle)}
                    </div>
                  )}
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
                    {esc(v.filename)}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <ViewScopeChip
                      filename={v.filename}
                      scope={v.scope || null}
                      explicit={!!v.scope_explicit}
                      onChanged={() => refetch()}
                    />
                  </div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {esc(v.modified_ago)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {v.size_kb}KB
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// Compact scope chip with inline picker. Explicit attachment renders solid;
// inferred renders dashed; missing renders muted "+ scope". Click toggles
// the dropdown. The picker is its own component because clicks need to NOT
// bubble up to the surrounding row (which would open the viewer).
function ViewScopeChip({
  filename, scope, explicit, onChanged,
}: { filename: string; scope: string | null; explicit: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [allScopes, setAllScopes] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [saving, setSaving] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open || allScopes.length > 0) return;
    api.scopes().then(r => setAllScopes(r.scopes)).catch(() => {});
  }, [open, allScopes.length]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const choose = async (next: string | null) => {
    setSaving(true);
    try {
      await api.setViewScope(filename, next);
      showToast(next ? `Attached to ${next}` : 'Detached');
      onChanged();
    } catch (e) {
      showToast(`Failed: ${String(e)}`);
    } finally {
      setSaving(false);
      setOpen(false);
      setFilter('');
    }
  };

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return allScopes;
    return allScopes.filter(s => s.toLowerCase().includes(q));
  }, [filter, allScopes]);

  const label = scope ? scope.replace(/\/$/, '').split('/').pop() || scope : '+ scope';
  const tooltip = scope
    ? `Scope: ${scope}\n${explicit ? '(explicit attachment)' : '(inferred — click to attach explicitly or change)'}`
    : 'No scope. Click to attach this view to a scope.';

  return (
    <span ref={wrapRef} style={{ position: 'relative', display: 'inline-block' }} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        title={tooltip}
        disabled={saving}
        style={{
          background: scope ? (explicit ? '#422006' : 'transparent') : 'transparent',
          color: scope ? '#fbbf24' : '#71717a',
          border: `1px ${explicit ? 'solid' : 'dashed'} ${scope ? '#a16207' : '#3f3f46'}`,
          fontSize: 10,
          padding: '2px 8px',
          borderRadius: 10,
          cursor: saving ? 'wait' : 'pointer',
          maxWidth: 200,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          fontWeight: explicit ? 600 : 400,
          opacity: saving ? 0.6 : 1,
        }}
      >
        {scope ? '📁 ' : ''}{label}
      </button>
      {open && (
        <div
          style={{
            position: 'absolute', top: 'calc(100% + 4px)', left: 0,
            width: 280, maxHeight: 320, background: '#18181b',
            border: '1px solid #27272a', borderRadius: 6,
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)', zIndex: 1000,
            display: 'flex', flexDirection: 'column',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ padding: 8, borderBottom: '1px solid #27272a' }}>
            <input
              type="text" autoFocus placeholder="Filter scopes..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{
                width: '100%', background: '#0a0a0c', border: '1px solid #27272a',
                color: '#fafafa', padding: '4px 8px', fontSize: 12,
                borderRadius: 4, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>
          <div style={{ overflow: 'auto', flex: 1 }}>
            <button
              type="button" onClick={() => choose(null)}
              style={chipMenuItemStyle(scope === null)}
            >
              <span style={{ color: '#71717a' }}>○</span>
              <span>(detach — fall back to inferred)</span>
            </button>
            {allScopes.length === 0 && (
              <div style={{ padding: 10, color: '#71717a', fontSize: 11 }}>Loading scopes...</div>
            )}
            {filtered.map(s => (
              <button
                key={s} type="button" onClick={() => choose(s)}
                style={chipMenuItemStyle(s === scope)}
              >
                <span style={{ color: s === scope ? '#f59e0b' : '#52525b' }}>
                  {s === scope ? '●' : '○'}
                </span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s}</span>
              </button>
            ))}
            {allScopes.length > 0 && filtered.length === 0 && (
              <div style={{ padding: 10, color: '#71717a', fontSize: 11 }}>No matches.</div>
            )}
          </div>
        </div>
      )}
    </span>
  );
}

function chipMenuItemStyle(active: boolean): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
    background: active ? '#1c1917' : 'transparent',
    border: 'none', color: active ? '#fafafa' : '#d4d4d8',
    fontSize: 12, padding: '6px 10px', cursor: 'pointer', textAlign: 'left',
  };
}
