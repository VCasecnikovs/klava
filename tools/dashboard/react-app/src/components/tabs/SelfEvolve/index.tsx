import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSelfEvolve } from '@/api/queries';
import { api } from '@/api/client';
import { KPIRow } from '@/components/shared/KPIRow';
import { FilterBar } from '@/components/shared/FilterBar';
import type { BacklogItem } from '@/api/types';

const PRIORITY_COLOR: Record<string, string> = {
  high: 'var(--red)', medium: 'var(--yellow)', low: 'var(--text-muted)',
};
const STATUS_COLOR: Record<string, string> = {
  open: 'var(--blue)', 'in-progress': 'var(--yellow)',
  done: 'var(--green)', wontfix: 'var(--text-muted)',
};
const SOURCE_COLOR_OVERRIDES: Record<string, string> = {
  reflection: '#7c3aed', heartbeat: '#dc2626', session: '#3b82f6',
  'self-evolve': '#22c55e', dislike: '#ef4444',
};
/** Generate deterministic color for unknown source names. */
function sourceColor(name: string): string {
  if (SOURCE_COLOR_OVERRIDES[name]) return SOURCE_COLOR_OVERRIDES[name];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return `hsl(${Math.abs(hash) % 360}, 55%, 55%)`;
}

const FILTERS = [
  { value: 'open', label: 'Open' },
  { value: 'all', label: 'All' },
  { value: 'done', label: 'Done' },
];

export function SelfEvolveTab() {
  const [filter, setFilter] = useState('open');
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);
  const { data, isLoading } = useSelfEvolve(true);
  const qc = useQueryClient();

  if (isLoading) return <div className="empty">Loading...</div>;
  if (!data) return <div className="empty">No data</div>;

  const { metrics, items } = data;
  const openCount = items.filter(i => i.status === 'open' || i.status === 'in-progress').length;
  const fixRate = metrics.added > 0 ? Math.round((metrics.fixed / metrics.added) * 100) : 0;

  const filtered = items.filter(i =>
    filter === 'all' ? true
    : filter === 'open' ? (i.status === 'open' || i.status === 'in-progress')
    : filter === 'done' ? (i.status === 'done' || i.status === 'wontfix')
    : i.status === filter
  );

  const handleRun = async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const res = await api.selfEvolveRun();
      setRunResult(res.error ? `Error: ${res.error}` : 'Completed');
      qc.invalidateQueries({ queryKey: ['self-evolve'] });
    } catch (e) {
      setRunResult(`Failed: ${e}`);
    } finally {
      setRunning(false);
    }
  };

  const refresh = () => qc.invalidateQueries({ queryKey: ['self-evolve'] });

  return (
    <>
      <KPIRow kpis={[
        { val: openCount, label: 'Open', color: openCount > 0 ? 'var(--yellow)' : 'var(--green)' },
        { val: metrics.fixed, label: 'Fixed (30d)', color: 'var(--green)' },
        { val: `${fixRate}%`, label: 'Fix Rate', color: fixRate > 50 ? 'var(--green)' : 'var(--red)' },
        { val: metrics.avg_days || '-', label: 'Avg Days', color: 'var(--blue)' },
      ]} />

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        Backlog
        <FilterBar filters={FILTERS} active={filter} onChange={setFilter} style={{ margin: 0 }} />
        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          Last run: {metrics.last_run || 'never'}
        </span>
        <button
          onClick={handleRun}
          disabled={running}
          style={{
            padding: '4px 12px', fontSize: 11, fontWeight: 600,
            background: running ? 'var(--text-muted)' : 'var(--green)',
            color: '#fff', border: 'none', borderRadius: 4,
            cursor: running ? 'wait' : 'pointer',
          }}
        >
          {running ? 'Running...' : 'Run Now'}
        </button>
      </div>

      {runResult && (
        <div style={{
          padding: '6px 12px', marginBottom: 8, fontSize: 12,
          background: runResult.startsWith('Error') || runResult.startsWith('Failed')
            ? 'rgba(239, 68, 68, 0.15)' : 'rgba(34, 197, 94, 0.15)',
          borderRadius: 4,
          color: runResult.startsWith('Error') || runResult.startsWith('Failed')
            ? 'var(--red)' : 'var(--green)',
        }}>
          {runResult}
        </div>
      )}

      {filtered.length === 0
        ? <div className="empty">{filter === 'open' ? 'All clear - nothing to fix' : 'No items'}</div>
        : filtered.map((item, i) => (
          <BacklogCard key={`${item.date}-${item.title}`} item={item} onMutate={refresh} />
        ))
      }
    </>
  );
}

function BacklogCard({ item, onMutate }: { item: BacklogItem; onMutate: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);

  // Edit form state
  const [editTitle, setEditTitle] = useState(item.title);
  const [editPriority, setEditPriority] = useState(item.priority);
  const [editStatus, setEditStatus] = useState(item.status);
  const [editDesc, setEditDesc] = useState(item.description);
  const [editHint, setEditHint] = useState(item.fix_hint);

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Delete "${item.title}"?`)) return;
    setDeleting(true);
    try {
      await api.selfEvolveDelete(item.title);
      onMutate();
    } catch (err) {
      alert(`Delete failed: ${err}`);
    } finally {
      setDeleting(false);
    }
  };

  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditing(true);
    setExpanded(true);
    setEditTitle(item.title);
    setEditPriority(item.priority);
    setEditStatus(item.status);
    setEditDesc(item.description);
    setEditHint(item.fix_hint);
  };

  const handleSave = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setSaving(true);
    try {
      await api.selfEvolveUpdate(item.title, {
        title: editTitle,
        priority: editPriority,
        status: editStatus,
        description: editDesc,
        fix_hint: editHint,
      });
      setEditing(false);
      onMutate();
    } catch (err) {
      alert(`Save failed: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditing(false);
  };

  const sessionUrl = item.session_id
    ? `/dashboard#chat?session=${item.session_id}`
    : null;

  return (
    <div
      style={{
        padding: '10px 14px', marginBottom: 4,
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderLeft: `3px solid ${PRIORITY_COLOR[item.priority] || 'var(--border)'}`,
        borderRadius: 'var(--radius-sm)', cursor: 'pointer',
        opacity: item.status === 'done' || item.status === 'wontfix' ? 0.5 : 1,
      }}
      onClick={() => !editing && setExpanded(e => !e)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-muted)', minWidth: 72,
        }}>{item.date}</span>
        <span style={{ fontWeight: 600, flex: 1, fontSize: 13 }}>{item.title}</span>
        {sessionUrl && (
          <a
            href={sessionUrl}
            onClick={e => e.stopPropagation()}
            title="Open source session"
            style={{
              fontSize: 11, color: 'var(--blue)', textDecoration: 'none',
              opacity: 0.7, cursor: 'pointer',
            }}
          >
            session
          </a>
        )}
        <SourceBadge source={item.source} />
        <PriorityDot priority={item.priority} />
        <StatusBadge status={item.status} />
        {item.seen > 1 && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>x{item.seen}</span>
        )}
        <button
          onClick={handleEdit}
          title="Edit"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 13, padding: '0 2px', color: 'var(--text-muted)',
            opacity: 0.6,
          }}
        >
          &#9998;
        </button>
        <button
          onClick={handleDelete}
          disabled={deleting}
          title="Delete"
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 13, padding: '0 2px', color: 'var(--red)',
            opacity: deleting ? 0.3 : 0.6,
          }}
        >
          &#10005;
        </button>
      </div>

      {expanded && !editing && (
        <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.5 }}>
          <div style={{ color: 'var(--text-secondary)' }}>{item.description}</div>
          {item.fix_hint && (
            <div style={{ marginTop: 4, color: 'var(--text-muted)', fontStyle: 'italic' }}>
              Hint: {item.fix_hint}
            </div>
          )}
          {item.resolved && (
            <div style={{ marginTop: 4, color: 'var(--green)' }}>
              Resolved: {item.resolved}
            </div>
          )}
          {item.session_id && (
            <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
              Session: <a
                href={sessionUrl!}
                style={{ color: 'var(--blue)', textDecoration: 'none' }}
              >{item.session_id}</a>
            </div>
          )}
        </div>
      )}

      {editing && (
        <div
          style={{ marginTop: 8, fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}
          onClick={e => e.stopPropagation()}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ minWidth: 60, color: 'var(--text-muted)' }}>Title</label>
            <input
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              style={{
                flex: 1, padding: '3px 6px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 3, color: 'var(--text)',
              }}
            />
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ minWidth: 60, color: 'var(--text-muted)' }}>Priority</label>
            <select
              value={editPriority}
              onChange={e => setEditPriority(e.target.value as BacklogItem['priority'])}
              style={{
                padding: '3px 6px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 3, color: 'var(--text)',
              }}
            >
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
            <label style={{ minWidth: 50, color: 'var(--text-muted)', marginLeft: 8 }}>Status</label>
            <select
              value={editStatus}
              onChange={e => setEditStatus(e.target.value as BacklogItem['status'])}
              style={{
                padding: '3px 6px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 3, color: 'var(--text)',
              }}
            >
              <option value="open">open</option>
              <option value="in-progress">in-progress</option>
              <option value="done">done</option>
              <option value="wontfix">wontfix</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <label style={{ minWidth: 60, color: 'var(--text-muted)', paddingTop: 4 }}>Desc</label>
            <textarea
              value={editDesc}
              onChange={e => setEditDesc(e.target.value)}
              rows={3}
              style={{
                flex: 1, padding: '3px 6px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 3, color: 'var(--text)', resize: 'vertical',
              }}
            />
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ minWidth: 60, color: 'var(--text-muted)' }}>Hint</label>
            <input
              value={editHint}
              onChange={e => setEditHint(e.target.value)}
              style={{
                flex: 1, padding: '3px 6px', fontSize: 12,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 3, color: 'var(--text)',
              }}
            />
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
            <button
              onClick={handleCancel}
              style={{
                padding: '4px 12px', fontSize: 11,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 4, cursor: 'pointer', color: 'var(--text)',
              }}
            >Cancel</button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '4px 12px', fontSize: 11, fontWeight: 600,
                background: 'var(--blue)', color: '#fff',
                border: 'none', borderRadius: 4,
                cursor: saving ? 'wait' : 'pointer',
              }}
            >{saving ? 'Saving...' : 'Save'}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const color = sourceColor(source);
  return (
    <span style={{
      fontSize: 9, padding: '1px 6px', borderRadius: 3,
      border: `1px solid ${color}`, color, textTransform: 'uppercase',
      fontWeight: 600, letterSpacing: '0.03em',
    }}>{source}</span>
  );
}

function PriorityDot({ priority }: { priority: string }) {
  return (
    <span style={{
      width: 8, height: 8, borderRadius: '50%',
      background: PRIORITY_COLOR[priority] || 'var(--text-muted)',
      display: 'inline-block', flexShrink: 0,
    }} title={priority} />
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLOR[status] || 'var(--text-muted)';
  return (
    <span style={{
      fontSize: 9, padding: '1px 6px', borderRadius: 3,
      background: color, color: '#fff', textTransform: 'uppercase',
      fontWeight: 600,
    }}>{status}</span>
  );
}
