import { useState, useMemo, useCallback, useEffect } from 'react';
import { useScopes, useScopeItems } from '@/api/queries';
import { Panel } from '@/components/shared/Panel';
import { ScopeTree } from './ScopeTree';
import { uuid } from '../Chat/uuid';
import type { ScopeTaskRow, ScopeSessionRow, ScopeNoteRow, ScopeViewRow } from '@/api/types';

const PANEL_BG = '#18181b';
const BORDER = '#27272a';
const MUTED = '#71717a';
const ACCENT = '#f59e0b';
const HOVER = '#1c1917';

export function ScopesTab() {
  const [selected, setSelected] = useState<string | null>(null);
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set());
  const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set());
  const { data: scopes, isLoading: scopesLoading, error: scopesError } = useScopes(true);
  const { data: items, isFetching: itemsFetching } = useScopeItems(selected);

  const scopeList = useMemo(() => scopes || [], [scopes]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.scope) setSelected(detail.scope);
    };
    window.addEventListener('scopes:open', handler);
    return () => window.removeEventListener('scopes:open', handler);
  }, []);

  const toggleTask = useCallback((id: string) => {
    setExpandedTasks(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);
  const toggleResult = useCallback((id: string) => {
    setExpandedResults(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleNewChat = useCallback(async (scope: string) => {
    const tabId = uuid();
    try {
      await fetch('/api/chat/scope', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tab_id: tabId, scope }),
      });
    } catch (e) {
      console.warn('Failed to pre-set scope on new tab', e);
    }
    window.dispatchEvent(new CustomEvent('chat:open'));
    window.dispatchEvent(new CustomEvent('chat:open-new-tab', { detail: { tab_id: tabId, scope } }));
  }, []);

  const handleOpenSession = useCallback((session: ScopeSessionRow) => {
    if (!session.sid) return;
    window.dispatchEvent(new CustomEvent('chat:open'));
    window.dispatchEvent(
      new CustomEvent('chat:resume-session', { detail: { session_id: session.sid } })
    );
  }, []);

  const handleOpenView = useCallback((view: ScopeViewRow) => {
    window.dispatchEvent(
      new CustomEvent('views:open', { detail: { filename: view.filename, title: view.title } })
    );
  }, []);

  return (
    <div style={{ display: 'flex', gap: 16, padding: 16, height: 'calc(100vh - 120px)' }}>
      <div
        style={{
          width: 280,
          flex: '0 0 280px',
          background: PANEL_BG,
          border: `1px solid ${BORDER}`,
          borderRadius: 6,
          overflow: 'auto',
        }}
      >
        <div
          style={{
            padding: '10px 14px',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: 1,
            color: MUTED,
            borderBottom: `1px solid ${BORDER}`,
          }}
        >
          SCOPES {scopeList.length > 0 && <span style={{ marginLeft: 8, color: '#52525b' }}>{scopeList.length}</span>}
        </div>
        {scopesLoading && <div style={{ padding: 12, color: MUTED, fontSize: 12 }}>Loading...</div>}
        {scopesError && (
          <div style={{ padding: 12, color: '#f87171', fontSize: 12 }}>
            Failed to load scopes. Webhook server may need restart.
          </div>
        )}
        {!scopesLoading && !scopesError && (
          <ScopeTree scopes={scopeList} selected={selected} onSelect={setSelected} />
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {!selected && (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: MUTED,
              fontSize: 13,
            }}
          >
            Pick a scope on the left to see its tasks, results, sessions, and views.
          </div>
        )}

        {selected && (
          <>
            <Header
              scope={selected}
              hub={items?.hub || null}
              counts={items?.counts || { open_tasks: 0, results: 0, sessions: 0, views: 0 }}
              loading={itemsFetching && !items}
              onNewChat={() => handleNewChat(selected)}
            />

            <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
              {(items?.views.length ?? 0) > 0 && (
                <Panel title={`Views (${items?.views.length ?? 0})`}>
                  <ViewsGallery views={items?.views || []} onOpen={handleOpenView} />
                </Panel>
              )}

              <Panel title={`Open tasks${items ? ` (${items.counts.open_tasks})` : ''}`}>
                <TaskList
                  tasks={items?.tasks || []}
                  placeholder="(no open tasks in this scope)"
                  expanded={expandedTasks}
                  onToggle={toggleTask}
                  onOpenSession={handleOpenSession}
                  onNewChatWithBody={(t) => {
                    if (selected) handleNewChat(selected);
                    void t;
                  }}
                />
              </Panel>

              <Panel title={`Recent results${items ? ` (${items.counts.results})` : ''}`}>
                <TaskList
                  tasks={items?.results || []}
                  placeholder="(no recent results)"
                  expanded={expandedResults}
                  onToggle={toggleResult}
                  onOpenSession={handleOpenSession}
                  showTimestamp
                />
              </Panel>

              <Panel title={`Recent sessions${items ? ` (${items.counts.sessions})` : ''}`}>
                <SessionList sessions={items?.sessions || []} onOpen={handleOpenSession} />
              </Panel>

              {items && items.notes.length > 0 && (
                <Panel title="Recent notes">
                  <NoteList notes={items.notes} />
                </Panel>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Header({
  scope, hub, counts, loading, onNewChat,
}: {
  scope: string;
  hub: Record<string, unknown> | null;
  counts: { open_tasks: number; results: number; sessions: number; views: number };
  loading: boolean;
  onNewChat: () => void;
}) {
  const status = hub && typeof hub.status === 'string' ? (hub.status as string) : null;
  const stage = hub && typeof hub.stage === 'string' ? (hub.stage as string) : null;
  const next = hub && typeof hub.next_milestone === 'string' ? (hub.next_milestone as string) : null;
  const owner = hub && typeof hub.owner === 'string' ? (hub.owner as string) : null;
  const deadline = hub && typeof hub.deadline === 'string' ? (hub.deadline as string) : null;

  return (
    <div
      style={{
        background: PANEL_BG,
        border: `1px solid ${BORDER}`,
        borderRadius: 6,
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#fafafa' }}>{scope}</div>
        {status && <Pill text={status} bg="#0c4a6e" border="#0369a1" fg="#7dd3fc" />}
        {stage && <Pill text={stage} bg="#422006" border="#a16207" fg="#fbbf24" />}
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={onNewChat}
          style={{
            background: '#422006',
            color: '#fbbf24',
            border: '1px solid #a16207',
            borderRadius: 4,
            padding: '4px 10px',
            fontSize: 12,
            cursor: 'pointer',
          }}
          title="Spawn a new chat tab pre-scoped to this project"
        >
          + New chat in scope
        </button>
      </div>
      {(next || owner || deadline) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, color: MUTED, fontSize: 12 }}>
          {next && <span>next: <span style={{ color: '#d4d4d8' }}>{next}</span></span>}
          {owner && <span>owner: <span style={{ color: '#d4d4d8' }}>{owner}</span></span>}
          {deadline && <span>deadline: <span style={{ color: '#d4d4d8' }}>{deadline}</span></span>}
        </div>
      )}
      <div style={{ color: '#52525b', fontSize: 11 }}>
        {loading
          ? 'Loading…'
          : `${counts.open_tasks} tasks · ${counts.results} results · ${counts.sessions} sessions · ${counts.views} views`}
      </div>
    </div>
  );
}

function Pill({ text, bg, border, fg }: { text: string; bg: string; border: string; fg: string }) {
  return (
    <span style={{ background: bg, border: `1px solid ${border}`, color: fg, fontSize: 11, padding: '2px 8px', borderRadius: 10 }}>
      {text}
    </span>
  );
}

function TaskList({
  tasks, placeholder, expanded, onToggle, onOpenSession, onNewChatWithBody, showTimestamp,
}: {
  tasks: ScopeTaskRow[];
  placeholder: string;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onOpenSession: (s: ScopeSessionRow) => void;
  onNewChatWithBody?: (t: ScopeTaskRow) => void;
  showTimestamp?: boolean;
}) {
  if (!tasks.length) return <div style={{ color: MUTED, fontSize: 12 }}>{placeholder}</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {tasks.map(t => {
        const isOpen = expanded.has(t.id);
        return (
          <div
            key={t.id}
            style={{
              background: '#0a0a0c',
              border: `1px solid ${BORDER}`,
              borderRadius: 4,
              borderLeft: `3px solid ${priorityColor(t.priority)}`,
              overflow: 'hidden',
            }}
          >
            <div
              onClick={() => onToggle(t.id)}
              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', cursor: 'pointer' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = HOVER; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ color: '#52525b', fontSize: 10, width: 8 }}>{isOpen ? '▾' : '▸'}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#fafafa', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t.title}
                </div>
                <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>
                  {t.priority?.toUpperCase()}
                  {t.source && ` · ${t.source}`}
                  {showTimestamp && t.completed_at && ` · ${t.completed_at.slice(0, 10)}`}
                  {!showTimestamp && t.created && ` · ${age(t.created)}`}
                </div>
              </div>
            </div>
            {isOpen && (
              <div style={{ padding: '10px 14px 12px 26px', borderTop: `1px solid ${BORDER}` }}>
                {t.body ? (
                  <pre
                    style={{
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      fontSize: 12, color: '#d4d4d8',
                      margin: 0, fontFamily: 'inherit',
                    }}
                  >
                    {t.body.length > 4000 ? t.body.slice(0, 4000) + '\n…(truncated)' : t.body}
                  </pre>
                ) : (
                  <div style={{ color: MUTED, fontSize: 12, fontStyle: 'italic' }}>(no body)</div>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  {t.session_id && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenSession({ sid: t.session_id!, ts: '', scope: '', trigger: '', summary: '' });
                      }}
                      style={btnStyle()}
                    >
                      Resume session
                    </button>
                  )}
                  {onNewChatWithBody && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); onNewChatWithBody(t); }}
                      style={btnStyle()}
                    >
                      Open in new chat
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SessionList({ sessions, onOpen }: { sessions: ScopeSessionRow[]; onOpen: (s: ScopeSessionRow) => void }) {
  if (!sessions.length) return <div style={{ color: MUTED, fontSize: 12 }}>(no recorded sessions in this scope yet)</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {sessions.map(s => (
        <div
          key={(s.sid || '') + s.ts}
          onClick={() => onOpen(s)}
          style={{
            display: 'flex', gap: 10, fontSize: 12, alignItems: 'center',
            padding: '6px 10px', borderBottom: `1px solid ${BORDER}`,
            cursor: s.sid ? 'pointer' : 'default',
          }}
          onMouseEnter={(e) => { if (s.sid) e.currentTarget.style.background = HOVER; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          <div style={{ color: MUTED, width: 110, flexShrink: 0 }}>{s.ts.slice(0, 16).replace('T', ' ')}</div>
          <div style={{
            background: triggerBg(s.trigger), color: triggerFg(s.trigger),
            fontSize: 10, padding: '2px 6px', borderRadius: 3,
            height: 'min-content', flexShrink: 0,
          }}>
            {s.trigger}
          </div>
          <div style={{ color: '#d4d4d8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
            {s.summary || '(no summary)'}
          </div>
          {s.duration_s !== undefined && (
            <div style={{ color: '#52525b', flexShrink: 0 }}>{Math.round(s.duration_s)}s</div>
          )}
        </div>
      ))}
    </div>
  );
}

function NoteList({ notes }: { notes: ScopeNoteRow[] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {notes.map(n => (
        <div key={n.path} style={{ fontSize: 12, padding: '4px 0' }}>
          <div style={{ color: '#d4d4d8' }}>{n.path}</div>
          {n.preview && <div style={{ color: MUTED, marginTop: 2 }}>{n.preview}</div>}
        </div>
      ))}
    </div>
  );
}

function ViewsGallery({ views, onOpen }: { views: ScopeViewRow[]; onOpen: (v: ScopeViewRow) => void }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
        gap: 10,
      }}
    >
      {views.map(v => (
        <div
          key={v.filename}
          onClick={() => onOpen(v)}
          style={{
            background: '#0a0a0c', border: `1px solid ${BORDER}`, borderRadius: 4,
            padding: '10px 12px', cursor: 'pointer',
            display: 'flex', flexDirection: 'column', gap: 4, minHeight: 70,
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = ACCENT; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = BORDER; }}
        >
          <div style={{ fontSize: 13, color: '#fafafa', fontWeight: 500, lineHeight: 1.3 }}>
            {v.title}
          </div>
          <div style={{ fontSize: 11, color: MUTED, marginTop: 'auto' }}>
            {new Date(v.mtime * 1000).toISOString().slice(0, 10)}
            {' · '}
            <span style={{ color: '#52525b' }}>{v.filename}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function btnStyle(): React.CSSProperties {
  return {
    background: '#27272a', color: '#d4d4d8', border: `1px solid ${BORDER}`,
    fontSize: 11, padding: '4px 10px', borderRadius: 4, cursor: 'pointer',
  };
}

function priorityColor(p: string): string {
  if (p === 'high') return '#ef4444';
  if (p === 'medium') return '#f59e0b';
  return '#52525b';
}

function age(iso: string): string {
  try {
    const d = new Date(iso);
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days <= 0) return 'today';
    if (days === 1) return '1d';
    return `${days}d`;
  } catch {
    return '';
  }
}

function triggerBg(t: string): string {
  if (t.startsWith('chat')) return '#1e3a8a';
  if (t.startsWith('heartbeat')) return '#422006';
  if (t.startsWith('consumer') || t.startsWith('queue')) return '#14532d';
  if (t.startsWith('backfill')) return '#3f3f46';
  return '#27272a';
}
function triggerFg(t: string): string {
  if (t.startsWith('chat')) return '#93c5fd';
  if (t.startsWith('heartbeat')) return '#fbbf24';
  if (t.startsWith('consumer') || t.startsWith('queue')) return '#86efac';
  if (t.startsWith('backfill')) return '#a1a1aa';
  return '#a1a1aa';
}
