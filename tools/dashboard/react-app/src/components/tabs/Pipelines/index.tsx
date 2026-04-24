import { usePipelines } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import type { PipelineDefinition, PipelineSession } from '@/api/types';

// Extended types for API fields not in base types
type PipelineDefExt = PipelineDefinition & {
  terminal_states?: string[];
  transition_count?: number;
  max_retries?: number;
};

type PipelineSessionExt = PipelineSession & {
  history?: { from?: string; to: string; at: string; label?: string }[];
  context?: { task?: string };
  total_duration_display?: string;
  retry_count?: number;
  final_state?: string;
  history_length?: number;
};

type PipelinesDataExt = {
  definitions: PipelineDefExt[];
  sessions: PipelineSessionExt[];
  active?: PipelineSessionExt[];
  completed_today?: PipelineSessionExt[];
  stats?: {
    active_count?: number;
    completed_today_count?: number;
    definition_count?: number;
  };
};

function FlowVisualization({ states, terminalStates, currentState, visitedStates }: {
  states: string[];
  terminalStates?: string[];
  currentState?: string;
  visitedStates?: string[];
}) {
  const nonTerminal = states.filter(st => !(terminalStates || []).includes(st));
  return (
    <div className="pipeline-flow">
      {nonTerminal.map((st, i) => {
        let cls = 'pipeline-flow-node';
        if (st === currentState) cls += ' current';
        else if (visitedStates && visitedStates.includes(st)) cls += ' done';
        return (
          <span key={st}>
            {i > 0 && <span className="pipeline-flow-arrow">&rarr;</span>}
            <div className={cls}>{st}</div>
          </span>
        );
      })}
    </div>
  );
}

function ActiveSession({ sess, definitions }: { sess: PipelineSessionExt; definitions: PipelineDefExt[] }) {
  const pdef = definitions.find(d => d.name === sess.pipeline);
  const allStates = pdef ? pdef.states : [];
  const terminalStates = pdef ? pdef.terminal_states : [];
  const visitedStates = (sess.history || []).map(h => h.to);
  const currentState = sess.current_state;
  const isFailed = currentState === 'failed';
  const badgeCls = isFailed ? 'failed' : 'active';
  const task = (sess.context || {}).task || '';

  return (
    <div className="pipeline-session">
      <div className="pipeline-session-header">
        <span className="pipeline-session-name">{sess.pipeline}</span>
        <span className={`pipeline-state-badge ${badgeCls}`}>{currentState}</span>
        <span className="pipeline-session-meta">
          {sess.total_duration_display || ''} | retries: {sess.retry_count ?? sess.retries}
        </span>
        <span className="pipeline-session-meta" style={{ marginLeft: 'auto' }}>
          sid: {sess.session_id}
        </span>
      </div>
      {task && (
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>Task: {task}</div>
      )}
      <FlowVisualization
        states={allStates}
        terminalStates={terminalStates}
        currentState={currentState}
        visitedStates={visitedStates}
      />
      {sess.history && sess.history.length > 0 && (
        <div className="pipeline-history">
          {sess.history.map((h, i) => {
            let t = '';
            try { t = h.at.substring(11, 19); } catch { /* empty */ }
            const from = h.from || '(start)';
            return (
              <div className="pipeline-history-entry" key={i}>
                <span className="time">{t}</span>
                <span className="transition">{from} &rarr; {h.to}</span>
                {h.label && <span className="label">[{h.label}]</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function PipelinesTab() {
  const { data: rawData } = usePipelines(true);
  if (!rawData) return <div className="empty">Loading pipelines...</div>;

  const data = rawData as unknown as PipelinesDataExt;
  const s = data.stats || {};
  const active = data.active || [];
  const completedToday = data.completed_today || [];
  const definitions = data.definitions || [];

  return (
    <>
      <KPIRow kpis={[
        { val: s.active_count || 0, label: 'Active' },
        { val: s.completed_today_count || 0, label: 'Completed Today' },
        { val: s.definition_count || definitions.length, label: 'Definitions' },
      ]} />

      {/* Active Sessions */}
      {active.length > 0 ? (
        <>
          <div className="section-heading">Active Sessions</div>
          <div>
            {active.map(sess => (
              <ActiveSession key={sess.session_id} sess={sess} definitions={definitions} />
            ))}
          </div>
        </>
      ) : (
        <div className="empty" style={{ padding: 12, color: 'var(--text-muted)', fontSize: 12 }}>
          No active pipelines
        </div>
      )}

      {/* Completed Today */}
      {completedToday.length > 0 && (
        <>
          <div className="section-heading">Completed Today</div>
          <div>
            {completedToday.map((sess, i) => (
              <div key={i} style={{
                display: 'flex', gap: 12, padding: '6px 0', fontSize: 12,
                borderBottom: '1px solid var(--border)'
              }}>
                <span style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>{sess.pipeline}</span>
                <span className={`pipeline-state-badge ${sess.final_state === 'failed' ? 'failed' : 'terminal'}`}>
                  {sess.final_state || sess.current_state}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  {sess.history_length || (sess.history || []).length} steps | retries: {sess.retry_count ?? sess.retries}
                </span>
                {(sess.context || {}).task && (
                  <span style={{ color: 'var(--text-secondary)', marginLeft: 'auto' }}>
                    {(sess.context || {}).task}
                  </span>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Pipeline Definitions */}
      <div className="section-heading">Pipeline Definitions</div>
      <div>
        {definitions.map(def => (
          <div className="pipeline-def" key={def.name}>
            <div className="pipeline-def-header">
              <span className="pipeline-def-name">{def.name}</span>
              <span className="pipeline-def-stats">
                {def.states.length} states | {def.transition_count ?? 0} transitions | max retries: {def.max_retries ?? 0}
              </span>
            </div>
            {def.description && <div className="pipeline-def-desc">{def.description}</div>}
            <FlowVisualization states={def.states} terminalStates={def.terminal_states} />
          </div>
        ))}
      </div>
    </>
  );
}
