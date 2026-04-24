import { useState, useEffect, useCallback, useRef } from 'react';
import type { Agent } from '@/api/types';
import { useAgents } from '@/api/queries';
import { api } from '@/api/client';
import { KPIRow } from '@/components/shared/KPIRow';

const STATUS_META: Record<string, { color: string; icon: string; label: string }> = {
  running:       { color: 'var(--blue)',     icon: '\u25B6', label: 'Running' },
  completed:     { color: 'var(--green)',    icon: '\u2713', label: 'Done' },
  failed:        { color: 'var(--red)',      icon: '\u2717', label: 'Failed' },
  killed:        { color: 'var(--red)',      icon: '\u25A0', label: 'Killed' },
  pending_retry: { color: 'var(--yellow)',   icon: '\u21BB', label: 'Retry' },
};

function elapsed(ts?: number): string {
  if (!ts) return '';
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

function isAlive(a: Agent): boolean {
  return a.status === 'running' || a.status === 'pending_retry';
}

export function AgentsTab() {
  const { data: rawData, refetch } = useAgents(true);
  const agents = rawData?.agents ?? [];
  const maxConcurrent = rawData?.max_concurrent ?? agents.length;
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  void tick;

  // Tick for elapsed timers
  const hasRunning = agents.some(isAlive);
  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [hasRunning]);

  const running = agents.filter(isAlive);
  const done = agents.filter(a => !isAlive(a));

  return (
    <div className="agents-page">
      <KPIRow kpis={[
        { val: running.length, label: 'Running', color: running.length > 0 ? 'var(--blue)' : 'var(--text-dim)' },
        { val: done.length, label: 'Finished' },
        { val: `${running.length}/${maxConcurrent}`, label: 'Capacity' },
      ]} />

      <div className="agents-toolbar">
        <button className="agents-refresh-btn" onClick={() => refetch()}>
          Refresh
        </button>
      </div>

      {agents.length === 0 ? (
        <div className="agents-empty">
          <div className="agents-empty-icon">{'\u2699'}</div>
          <div>No dispatch agents</div>
          <div style={{ fontSize: 12, opacity: 0.5, marginTop: 4 }}>Agents spawned via dispatch/heartbeat/TG will appear here</div>
        </div>
      ) : (
        <>
          {running.length > 0 && (
            <div className="agents-section">
              <div className="agents-section-label">Active</div>
              <div className="agents-grid">
                {running.map(a => (
                  <AgentCard
                    key={a.id}
                    agent={a}
                    expanded={expandedId === a.id}
                    onToggle={() => setExpandedId(expandedId === a.id ? null : a.id)}
                    onRefresh={refetch}
                  />
                ))}
              </div>
            </div>
          )}
          {done.length > 0 && (
            <div className="agents-section">
              <div className="agents-section-label">History</div>
              <div className="agents-grid">
                {done.map(a => (
                  <AgentCard
                    key={a.id}
                    agent={a}
                    expanded={expandedId === a.id}
                    onToggle={() => setExpandedId(expandedId === a.id ? null : a.id)}
                    onRefresh={refetch}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ---- Agent Card ---- */

function AgentCard({ agent, expanded, onToggle, onRefresh }: {
  agent: Agent; expanded: boolean; onToggle: () => void; onRefresh: () => void;
}) {
  const meta = STATUS_META[agent.status] || { color: 'var(--text-dim)', icon: '?', label: agent.status };
  const alive = isAlive(agent);

  const handleKill = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.agentKill(agent.id).catch(console.error);
    onRefresh();
  }, [agent.id, onRefresh]);

  return (
    <div className={`agent-card${alive ? ' alive' : ''}${expanded ? ' expanded' : ''}`} onClick={onToggle}>
      <div className="agent-card-strip" style={{ background: meta.color }} />

      <div className="agent-card-body">
        <div className="agent-card-header">
          <div className="agent-card-status">
            <span className={`agent-card-dot${alive ? ' pulse' : ''}`} style={{ color: meta.color }}>
              {meta.icon}
            </span>
            <span className="agent-card-name">{agent.name}</span>
          </div>
          <div className="agent-card-actions">
            {alive && (
              <button className="agent-card-kill" onClick={handleKill} title="Kill">
                {'\u25A0'}
              </button>
            )}
          </div>
        </div>

        <div className="agent-card-pills">
          <span className="agents-model-pill">{agent.model}</span>
          <span className="agents-type-pill">{agent.type}</span>
          {alive && <span className="agents-elapsed-pill">{elapsed(agent.started)}</span>}
        </div>

        <div className="agent-card-stats">
          {agent.output_lines > 0 && (
            <span style={{ opacity: 0.5 }}>{agent.output_lines} lines</span>
          )}
          {agent.error && (
            <span style={{ color: 'var(--red)' }}>error</span>
          )}
        </div>
      </div>

      {expanded && <AgentDetailInline agentId={agent.id} />}
    </div>
  );
}

/* ---- Inline Agent Detail ---- */

type TodoItem = { id?: string; content: string; status: 'pending' | 'in_progress' | 'completed'; priority?: string };

function AgentDetailInline({ agentId }: { agentId: string }) {
  const [detail, setDetail] = useState<(Agent & { output: string[]; todos?: TodoItem[] }) | null>(null);
  const outputRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.agentDetail(agentId).then(setDetail).catch(console.error);
    const interval = setInterval(() => {
      api.agentDetail(agentId).then(setDetail).catch(console.error);
    }, 2000);
    return () => clearInterval(interval);
  }, [agentId]);

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [detail?.output]);

  if (!detail) return <div className="agent-detail-loading">Loading...</div>;

  const todos = detail.todos || [];

  return (
    <div className="agent-detail-inline" onClick={e => e.stopPropagation()}>
      {todos.length > 0 && (
        <div style={{ padding: '8px 10px', borderBottom: '1px solid rgba(255,255,255,0.06)', marginBottom: 4 }}>
          <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
            Tasks {todos.filter(t => t.status === 'completed').length}/{todos.length}
          </div>
          {todos.map((t, i) => {
            const st = t.status || 'pending';
            const icon = st === 'completed' ? '\u2705' : st === 'in_progress' ? '\u25B6' : '\u25CB';
            return (
              <div key={i} style={{ display: 'flex', gap: 6, fontFamily: 'var(--mono)', fontSize: 11, padding: '2px 0' }}>
                <span style={{ color: st === 'in_progress' ? 'var(--blue)' : st === 'completed' ? 'var(--green)' : 'var(--text-muted)', flexShrink: 0 }}>{icon}</span>
                <span style={{
                  color: st === 'completed' ? 'var(--text-muted)' : st === 'in_progress' ? 'var(--blue)' : 'var(--text-primary)',
                  textDecoration: st === 'completed' ? 'line-through' : 'none',
                  opacity: st === 'completed' ? 0.6 : 1,
                }}>{t.content}</span>
              </div>
            );
          })}
        </div>
      )}
      <div ref={outputRef} className="agent-detail-output">
        {detail.output.length === 0 ? (
          <span style={{ opacity: 0.3 }}>No output yet...</span>
        ) : (
          detail.output.map((line, i) => <div key={i}>{line}</div>)
        )}
      </div>

      {detail.error && (
        <div className="agent-detail-error">Error: {detail.error}</div>
      )}
    </div>
  );
}
