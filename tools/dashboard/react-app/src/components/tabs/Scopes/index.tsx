import { useState, useMemo } from 'react';
import { useScopes, useScopeItems } from '@/api/queries';
import { Panel } from '@/components/shared/Panel';
import { ScopeTree } from './ScopeTree';
import type { ScopeTaskRow, ScopeSessionRow, ScopeNoteRow } from '@/api/types';

const PANEL_BG = '#18181b';
const BORDER = '#27272a';
const MUTED = '#71717a';
const ACCENT = '#f59e0b';

export function ScopesTab() {
  const [selected, setSelected] = useState<string | null>(null);
  const { data: scopes, isLoading: scopesLoading, error: scopesError } = useScopes(true);
  const { data: items, isFetching: itemsFetching } = useScopeItems(selected);

  const scopeList = useMemo(() => scopes || [], [scopes]);

  return (
    <div style={{ display: 'flex', gap: 16, padding: 16, height: 'calc(100vh - 120px)' }}>
      {/* Left: folder tree */}
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

      {/* Right: workspace */}
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
            Pick a scope on the left to see its tasks, results, and recent sessions.
          </div>
        )}

        {selected && (
          <>
            <Header
              scope={selected}
              hub={items?.hub || null}
              counts={items?.counts || { open_tasks: 0, results: 0, sessions: 0 }}
              loading={itemsFetching && !items}
            />

            <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
              <Panel title={`Open tasks${items ? ` (${items.counts.open_tasks})` : ''}`}>
                <TaskList tasks={items?.tasks || []} placeholder="(no open tasks in this scope)" />
              </Panel>

              <Panel title={`Recent results${items ? ` (${items.counts.results})` : ''}`}>
                <TaskList tasks={items?.results || []} placeholder="(no recent results)" showTimestamp />
              </Panel>

              <Panel title={`Recent sessions${items ? ` (${items.counts.sessions})` : ''}`}>
                <SessionList sessions={items?.sessions || []} />
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
  scope, hub, counts, loading,
}: {
  scope: string;
  hub: Record<string, unknown> | null;
  counts: { open_tasks: number; results: number; sessions: number };
  loading: boolean;
}) {
  const status = hub && typeof hub.status === 'string' ? hub.status : null;
  const stage = hub && typeof hub.stage === 'string' ? hub.stage : null;
  const next = hub && typeof hub.next_milestone === 'string' ? hub.next_milestone : null;

  return (
    <div
      style={{
        background: PANEL_BG,
        border: `1px solid ${BORDER}`,
        borderRadius: 6,
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 10,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600, color: '#fafafa' }}>{scope}</div>
      {status && (
        <Pill text={status} bg="#0c4a6e" border="#0369a1" fg="#7dd3fc" />
      )}
      {stage && (
        <Pill text={stage} bg="#422006" border="#a16207" fg="#fbbf24" />
      )}
      {next && (
        <div style={{ color: MUTED, fontSize: 12, marginLeft: 'auto' }}>
          next: <span style={{ color: '#d4d4d8' }}>{next}</span>
        </div>
      )}
      <div style={{ color: '#52525b', fontSize: 11, marginLeft: next ? 0 : 'auto' }}>
        {loading ? 'Loading…' : `${counts.open_tasks} tasks · ${counts.results} results · ${counts.sessions} sessions`}
      </div>
    </div>
  );
}

function Pill({ text, bg, border, fg }: { text: string; bg: string; border: string; fg: string }) {
  return (
    <span
      style={{
        background: bg, border: `1px solid ${border}`, color: fg,
        fontSize: 11, padding: '2px 8px', borderRadius: 10,
      }}
    >
      {text}
    </span>
  );
}

function TaskList({ tasks, placeholder, showTimestamp }: { tasks: ScopeTaskRow[]; placeholder: string; showTimestamp?: boolean }) {
  if (!tasks.length) return <div style={{ color: MUTED, fontSize: 12 }}>{placeholder}</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {tasks.map(t => (
        <div
          key={t.id}
          style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 10px',
            background: '#0a0a0c', border: `1px solid ${BORDER}`, borderRadius: 4,
            borderLeft: `3px solid ${priorityColor(t.priority)}`,
          }}
        >
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
      ))}
    </div>
  );
}

function SessionList({ sessions }: { sessions: ScopeSessionRow[] }) {
  if (!sessions.length) return <div style={{ color: MUTED, fontSize: 12 }}>(no recorded sessions in this scope yet)</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {sessions.map(s => (
        <div
          key={s.sid + s.ts}
          style={{
            display: 'flex', gap: 10, fontSize: 12,
            padding: '6px 10px', borderBottom: `1px solid ${BORDER}`,
          }}
        >
          <div style={{ color: MUTED, width: 110, flexShrink: 0 }}>{s.ts.slice(0, 16).replace('T', ' ')}</div>
          <div style={{
            background: triggerBg(s.trigger), color: triggerFg(s.trigger),
            fontSize: 10, padding: '2px 6px', borderRadius: 3,
            height: 'min-content', flexShrink: 0,
          }}>
            {s.trigger}
          </div>
          <div style={{ color: '#d4d4d8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
  return '#27272a';
}
function triggerFg(t: string): string {
  if (t.startsWith('chat')) return '#93c5fd';
  if (t.startsWith('heartbeat')) return '#fbbf24';
  if (t.startsWith('consumer') || t.startsWith('queue')) return '#86efac';
  return '#a1a1aa';
}

// ACCENT used for selection in ScopeTree but referenced here to avoid lint warning.
void ACCENT;
