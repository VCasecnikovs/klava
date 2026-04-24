import { useState, useCallback } from 'react';
import { useHeartbeat } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { FilterBar } from '@/components/shared/FilterBar';
import { showToast } from '@/components/shared/Toast';
import { timeAgo } from '@/lib/utils';

// Extended types for API fields
type TodoItem = {
  id?: string;
  content: string;
  status: 'pending' | 'in_progress' | 'completed';
  priority?: string;
};

type HBRunExt = {
  timestamp: string;
  job_id: string;
  status: string;
  duration?: number;
  duration_seconds?: number;
  cost_usd?: number;
  output?: string;
  error?: string;
  ago?: string;
  intake?: string;
  actions?: string[];
  intake_details?: Record<string, Record<string, number>>;
  todos?: TodoItem[];
  deltas?: {
    type: string;
    title?: string;
    path?: string;
    subject?: string;
    deal?: string;
    deal_name?: string;
    key?: string;
    source?: string;
    target?: string;
    change?: string;
    reason?: string;
    due?: string;
    trigger?: string;
    count?: number;
    summary?: string;
    category?: string;
    hint?: string;
    facts?: string[];
    label?: string;
    expected?: string;
    lens?: string;
    tag?: string;
    trajectory?: string;
    stage?: string;
    next_action?: string;
    commit?: string;
    item?: string;
  }[];
};

type HBJobStatsExt = Record<string, {
  today: number;
  acted_today: number;
  last_status?: string;
  last_run?: string;
  avg_duration: number;
  total_7d: number;
}>;

type JobMeta = { label: string; order: number };

type ConsumerSource = { position: number; total: number; new: number };
type ConsumerData = { sources: Record<string, ConsumerSource>; updated_at: string; total_new: number };
type TodayDeltas = Record<string, string[] | number>;

type HeartbeatDataExt = {
  runs: HBRunExt[];
  job_stats: HBJobStatsExt;
  job_meta?: Record<string, JobMeta>;
  kpis?: {
    runs_today?: number;
    acted_today?: number;
    idle_today?: number;
    failed_today?: number;
    total_actions_today?: number;
    tracked_items?: number;
  };
  stats?: {
    total_runs?: number;
    runs_today?: number;
    failures_today?: number;
    total_cost?: number;
  };
  reported_items?: Record<string, string>;
  consumer_sources?: Record<string, ConsumerData>;
  today_deltas?: TodayDeltas;
};

/** Derive short column header from consumer name (max 4 chars). */
function consumerShort(name: string): string {
  // Known abbreviations for common consumers
  const KNOWN: Record<string, string> = {
    heartbeat: 'hb', reflection: 'refl', 'sales-mentor': 'sale',
  };
  if (KNOWN[name]) return KNOWN[name];
  return name.length <= 4 ? name : name.slice(0, 4);
}

function SourcesPanel({ data }: { data: Record<string, ConsumerData> }) {
  // Sort consumers: most pending items first, then alphabetically
  const consumers = Object.keys(data).sort((a, b) =>
    (data[b].total_new || 0) - (data[a].total_new || 0) || a.localeCompare(b)
  );
  if (consumers.length === 0) return null;

  // Collect all sources that appear in any consumer
  const allSources = new Set<string>();
  for (const c of consumers) {
    for (const src of Object.keys(data[c].sources)) allSources.add(src);
  }

  // Filter: only show sources where at least one consumer has new > 0 or position > 0
  const activeSources = [...allSources].filter(src =>
    consumers.some(c => {
      const s = data[c].sources[src];
      return s && (s.new > 0 || s.position > 0);
    })
  ).sort();

  if (activeSources.length === 0) return null;

  return (
    <table className="hb-sources-table">
      <thead>
        <tr>
          <th>Source</th>
          {consumers.map(c => <th key={c}>{consumerShort(c)}</th>)}
        </tr>
      </thead>
      <tbody>
        {activeSources.map(src => (
          <tr key={src}>
            <td>{src}</td>
            {consumers.map(c => {
              const s = data[c].sources[src];
              if (!s) return <td key={c} style={{ color: 'var(--text-muted)', opacity: 0.3 }}>-</td>;
              const cls = s.new > 100 ? 'high-new' : s.new > 0 ? 'has-new' : '';
              return <td key={c} className={cls}>{s.new.toLocaleString()}</td>;
            })}
          </tr>
        ))}
        <tr className="total-row">
          <td>TOTAL</td>
          {consumers.map(c => (
            <td key={c} className={data[c].total_new > 0 ? 'has-new' : ''}>
              {data[c].total_new.toLocaleString()}
            </td>
          ))}
        </tr>
        <tr className="updated-row">
          <td>Updated</td>
          {consumers.map(c => (
            <td key={c}>{data[c].updated_at ? timeAgo(data[c].updated_at) : '-'}</td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

/** Default icons per delta category. Falls back to bullet for unknown categories. */
const CATEGORY_ICONS: Record<string, string> = {
  obsidian: '~', gtask: '+', gmail: '\u2709', calendar: '\ud83d\udcc5',
  deal: '$', state: '\u2295',
};

/** Capitalize category key into a display label. */
function categoryLabel(key: string): string {
  const KNOWN: Record<string, string> = { gtask: 'G Tasks', gmail: 'Gmail' };
  if (KNOWN[key]) return KNOWN[key];
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function TodayOutputPanel({ deltas }: { deltas: TodayDeltas }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  // Derive categories dynamically from the data (exclude 'skipped')
  const categories = Object.keys(deltas).filter(k => k !== 'skipped' && Array.isArray(deltas[k]) && (deltas[k] as string[]).length > 0);
  const skipped = typeof deltas.skipped === 'number' ? deltas.skipped : 0;

  if (categories.length === 0 && skipped === 0) {
    return <div className="hb-today-output" style={{ color: 'var(--text-muted)', fontSize: 12 }}>No outputs today</div>;
  }

  return (
    <div className="hb-today-output">
      {categories.map(cat => {
        const items = deltas[cat] as string[];
        const unique = [...new Set(items.filter(Boolean))];
        const show = expanded === cat ? unique : unique.slice(0, 3);
        const more = unique.length - 3;
        return (
          <div className="hb-output-category" key={cat}>
            <span className="hb-output-icon">{CATEGORY_ICONS[cat] || '\u2022'}</span>
            <span className="hb-output-type">{categoryLabel(cat)}</span>
            <span className="hb-output-count">{unique.length}</span>
            <span className="hb-output-items">
              {show.map((item, i) => (
                <span key={i} className="hb-output-item">{item}</span>
              ))}
              {more > 0 && expanded !== cat && (
                <span className="hb-output-more" onClick={(e) => { e.stopPropagation(); setExpanded(cat); }}>
                  +{more} more
                </span>
              )}
            </span>
          </div>
        );
      })}
      {skipped > 0 && (
        <div className="hb-output-category">
          <span className="hb-output-icon" style={{ opacity: 0.4 }}>{'\u2298'}</span>
          <span className="hb-output-type" style={{ opacity: 0.5 }}>Skipped</span>
          <span className="hb-output-count" style={{ color: 'var(--text-muted)' }}>{skipped}</span>
          <span className="hb-output-items" />
        </div>
      )}
    </div>
  );
}

function buildJobList(data: HeartbeatDataExt) {
  const meta = data.job_meta || {};
  const ids = Object.keys(data.job_stats || {});
  ids.sort((a, b) => (meta[a]?.order ?? 999) - (meta[b]?.order ?? 999));
  const labels: Record<string, string> = {};
  for (const id of ids) {
    labels[id] = meta[id]?.label || id.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
  }
  const filters = [{ value: 'all', label: 'All' }, ...ids.map(id => ({ value: id, label: labels[id] }))];
  return { order: ids, labels, filters };
}

function JobStatsPanel({ stats, order, labels }: { stats: HBJobStatsExt; order: string[]; labels: Record<string, string> }) {
  return (
    <div>
      {order.filter(j => stats[j]).map(j => {
        const s = stats[j];
        const statusCls = s.last_status || 'idle';
        const statusLabel = s.last_status === 'acted' ? 'ACTED' : s.last_status === 'failed' ? 'FAILED' : 'IDLE';
        const lastRun = s.last_run
          ? new Date(s.last_run).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
          : 'never';
        return (
          <div className="hb-job-card" key={j}>
            <span className="hb-job-name">{labels[j] || j}</span>
            <span className="hb-job-meta">
              <span>today: {s.today}</span>
              <span>acted: {s.acted_today}</span>
              <span>avg: {s.avg_duration}s</span>
              <span>last: {lastRun}</span>
              <span>7d: {s.total_7d}</span>
            </span>
            <span className={`hb-job-status ${statusCls}`}>{statusLabel}</span>
          </div>
        );
      })}
    </div>
  );
}

const DELTA_ICONS: Record<string, string> = {
  gtask_created: '✅', gtask_updated: '✅', gtask_completed: '✅',
  obsidian_created: '📝', obsidian_updated: '📝', observation: '👁',
  gmail_drafted: '📧', calendar_created: '📅',
  deal_updated: '💰', state_tracked: '⊕', dispatched: '🔍',
  inbox_created: '📥', inbox_routed: '📥',
  topic_created: '📝', topic_updated: '📝',
  crosslink_added: '🔗', obsidian_groomed: '🧹', duplicate_merged: '🧹',
  silence_alert: '⚠', feedback_learned: '📊', memory_updated: '🧠',
  code_fixed: '🔧', skill_created: '⚙', skill_updated: '⚙',
  prompt_optimized: '✏', backlog_resolved: '✓', infra_improved: '🔧',
  cron_stats: '📊',
  skipped: '⏭',
};

function RunCard({ r }: { r: HBRunExt }) {
  const [expanded, setExpanded] = useState(false);

  const ts = new Date(r.timestamp);
  const dateStr = ts.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
  const timeStr = ts.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const intakeStr = r.intake || '';

  let summary: string;
  if (r.status === 'failed') {
    summary = (r.error || 'Failed').substring(0, 100);
  } else if (r.actions && r.actions.length > 0) {
    summary = r.actions[0].substring(0, 120);
  } else if (intakeStr) {
    summary = intakeStr;
  } else {
    summary = 'No new data';
  }

  const dur = r.duration ? `${r.duration}s` : (r.duration_seconds ? `${r.duration_seconds}s` : '');
  const realDeltas = r.deltas?.filter(d => d.type !== 'skipped') || [];
  const deltaCount = realDeltas.length;

  // Intake details section
  let detailsHtml: React.ReactNode = null;
  if (r.intake_details) {
    const parts = Object.entries(r.intake_details).map(([src, groups]) => {
      const groupParts = Object.entries(groups).map(([g, n]) => `${g}: ${n}`).join(', ');
      return (
        <div key={src} style={{ margin: '2px 0' }}>
          <span style={{ color: 'var(--blue)', fontWeight: 600 }}>{src}</span> {groupParts}
        </div>
      );
    });
    if (parts.length > 0) {
      detailsHtml = (
        <div style={{
          fontFamily: 'var(--mono)', fontSize: 11, marginBottom: 8, padding: '8px 10px',
          background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)', color: 'var(--text-secondary)'
        }}>
          {parts}
        </div>
      );
    }
  }

  // Deltas section
  let deltasHtml: React.ReactNode = null;
  if (r.deltas && r.deltas.length > 0) {
    const acts = realDeltas.length;
    const skips = r.deltas.filter(d => d.type === 'skipped').length;

    const actionDeltas = r.deltas.filter(d => d.type !== 'skipped');
    const skipDeltas = r.deltas.filter(d => d.type === 'skipped');
    const totalSkipCount = skipDeltas.reduce((sum, d) => sum + (d.count || 1), 0);

    deltasHtml = (
      <div style={{
        marginBottom: 8, padding: '8px 10px',
        background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)'
      }}>
        <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>
          {acts} action{acts !== 1 ? 's' : ''}{totalSkipCount > 0 ? `, ${totalSkipCount} skipped` : ''}
        </div>
        {actionDeltas.map((d, di) => {
          const icon = DELTA_ICONS[d.type] || '\u2022';
          const mainText = d.summary
            || [d.deal_name || d.label || d.title || d.path || d.subject || d.deal || d.item || d.key || d.target, d.change || d.reason].filter(Boolean).join(' - ')
            || d.type;
          const subParts: string[] = [];
          if (d.stage) subParts.push(`Stage: ${d.stage}`);
          if (d.next_action) subParts.push(`Next: ${d.next_action}`);
          if (d.facts && d.facts.length > 0) subParts.push(d.facts.join(', '));
          if (d.expected) subParts.push(`→ ${d.expected}`);
          if (d.lens && d.tag) subParts.push(`${d.lens}/${d.tag}`);
          else if (d.lens) subParts.push(d.lens);
          if (d.commit) subParts.push(d.commit.slice(0, 7));
          const sub = subParts.length > 0 ? subParts.join(' | ') : '';
          return (
            <div key={di} style={{ padding: '3px 0', fontFamily: 'var(--mono)', fontSize: 11 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                <span style={{ width: 18, textAlign: 'center', flexShrink: 0 }}>{icon}</span>
                <span style={{ color: 'var(--text-primary)', flex: 1, minWidth: 0, wordBreak: 'break-word' }}>{mainText}</span>
                {d.trigger && <span style={{ color: 'var(--text-muted)', fontSize: 10, flexShrink: 0, whiteSpace: 'nowrap', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>← {d.trigger}</span>}
              </div>
              {sub && (
                <div style={{ paddingLeft: 24, fontSize: 10, color: 'var(--text-muted)', opacity: 0.8 }}>
                  {sub}
                  {d.trajectory && (
                    <span style={{
                      marginLeft: 6, padding: '0 5px', borderRadius: 6, fontSize: 9, fontWeight: 500,
                      color: d.trajectory === 'escalating' ? '#f87171' : d.trajectory === 'new' ? '#60a5fa' : d.trajectory === 'declining' ? '#34d399' : 'var(--text-muted)',
                      background: d.trajectory === 'escalating' ? 'rgba(248,113,113,0.15)' : d.trajectory === 'new' ? 'rgba(96,165,250,0.15)' : d.trajectory === 'declining' ? 'rgba(52,211,153,0.15)' : 'rgba(255,255,255,0.06)',
                    }}>{d.trajectory}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {skipDeltas.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4, paddingTop: 4, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginRight: 4 }}>Noise ({totalSkipCount}):</span>
            {skipDeltas.map((d, i) => {
              const src = (d.source || '?').replace(/^(telegram|signal)\//, '');
              const hint = d.hint || d.reason || '';
              const cnt = d.count && d.count > 1 ? ` x${d.count}` : '';
              return (
                <span key={i} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }} title={hint}>
                  {src}{cnt}{hint ? `: ${hint}` : ''}
                </span>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // Strip ---DELTAS--- from output display
  let displayOutput = r.output || r.error || 'No output';
  if (displayOutput.includes('---DELTAS---')) {
    displayOutput = displayOutput.split('---DELTAS---')[0].trimEnd();
  }

  // Todos section
  let todosHtml: React.ReactNode = null;
  const todos = r.todos || [];
  if (todos.length > 0) {
    const done = todos.filter(t => t.status === 'completed').length;
    const inProgress = todos.filter(t => t.status === 'in_progress').length;
    const pending = todos.filter(t => t.status === 'pending').length;
    todosHtml = (
      <div style={{
        marginBottom: 8, padding: '8px 10px',
        background: 'var(--bg-elevated)', borderRadius: 'var(--radius-sm)'
      }}>
        <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4, display: 'flex', gap: 8 }}>
          <span>Tasks {done}/{todos.length}</span>
          {inProgress > 0 && <span style={{ color: 'var(--blue)' }}>&#x1F504; {inProgress} active</span>}
          {pending > 0 && <span style={{ color: 'var(--text-muted)' }}>&#x23F3; {pending} pending</span>}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {todos.map((t, i) => {
            const st = t.status || 'pending';
            const icon = st === 'completed' ? '\u2705' : st === 'in_progress' ? '\u25B6' : '\u25CB';
            return (
              <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'baseline', fontFamily: 'var(--mono)', fontSize: 11 }}>
                <span style={{ flexShrink: 0, width: 18, textAlign: 'center', color: st === 'in_progress' ? 'var(--blue)' : st === 'completed' ? 'var(--green)' : 'var(--text-muted)' }}>{icon}</span>
                <span style={{
                  color: st === 'completed' ? 'var(--text-muted)' : st === 'in_progress' ? 'var(--blue)' : 'var(--text-primary)',
                  textDecoration: st === 'completed' ? 'line-through' : 'none',
                  opacity: st === 'completed' ? 0.6 : 1,
                }}>{t.content}</span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className={`hb-run ${r.status}${expanded ? ' expanded' : ''}`} onClick={() => setExpanded(!expanded)}>
      <div className="hb-run-header">
        <span className="hb-run-time">{dateStr} {timeStr}</span>
        <span className={`hb-run-job ${r.job_id}`}>{r.job_id}</span>
        <span className="hb-run-summary">{summary}</span>
        {deltaCount > 0 && (
          <span className="hb-run-delta-count">{deltaCount} {deltaCount === 1 ? 'change' : 'changes'}</span>
        )}
        {todos.length > 0 && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'rgba(96,165,250,0.12)', color: 'var(--blue)', marginLeft: 4 }}>
            {todos.filter(t => t.status === 'completed').length}/{todos.length} tasks
          </span>
        )}
        <span className="hb-run-duration">{dur}</span>
      </div>
      {!expanded && r.status === 'acted' && realDeltas.length > 0 && (
        <div className="hb-run-mini-report">
          {realDeltas.slice(0, 2).map((d, i) => (
            <span key={i}>
              {DELTA_ICONS[d.type] || '\u2022'} {d.summary || d.deal_name || d.label || d.title || d.path || d.deal || d.target || d.subject || d.item || ''}
            </span>
          ))}
        </div>
      )}
      {expanded && (
        <div className="hb-run-body" style={{ display: 'block' }}>
          {detailsHtml}
          {deltasHtml}
          {todosHtml}
          <div className="hb-run-output" dangerouslySetInnerHTML={{ __html: displayOutput }} />
        </div>
      )}
    </div>
  );
}

function TrackedItems({ items }: { items: Record<string, string> }) {
  const keys = Object.keys(items);
  if (keys.length === 0) return null;

  return (
    <>
      <div className="section-heading">Tracked Items (dedup)</div>
      <div>
        {keys.map(k => {
          const ts = items[k];
          const ago = ts ? timeAgo(ts) : '';
          return (
            <div className="hb-tracked-item" key={k}>
              <span className="hb-tracked-key">{k}</span>
              <span className="hb-tracked-time">{ago}</span>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function HeartbeatTab() {
  const [filter, setFilter] = useState('all');
  const { data: rawData, refetch } = useHeartbeat(true);
  const handleRefresh = useCallback(() => { refetch(); showToast('Refreshing...'); }, [refetch]);

  if (!rawData) return <div className="empty">Loading heartbeat...</div>;

  const data = rawData as unknown as HeartbeatDataExt;
  const k = data.kpis || data.stats || {};
  const { order, labels, filters } = buildJobList(data);

  // Filter runs
  const runs = (data.runs || []).filter(r =>
    filter === 'all' || r.job_id === filter
  );

  return (
    <>
      <KPIRow kpis={[
        { val: (k as Record<string, number>).runs_today || 0, label: 'Runs Today' },
        { val: (k as Record<string, number>).acted_today || 0, label: 'Acted', color: 'var(--green)' },
        { val: (k as Record<string, number>).idle_today || 0, label: 'Idle' },
        {
          val: (k as Record<string, number>).failed_today || 0,
          label: 'Failed',
          color: ((k as Record<string, number>).failed_today || 0) > 0 ? 'var(--red)' : 'var(--text-muted)'
        },
        { val: (k as Record<string, number>).total_actions_today || 0, label: 'Actions', color: 'var(--blue)' },
        { val: (k as Record<string, number>).tracked_items || 0, label: 'Tracked' },
      ]} />

      {data.consumer_sources && Object.keys(data.consumer_sources).length > 0 && (
        <>
          <div className="section-heading">Source Queues</div>
          <SourcesPanel data={data.consumer_sources} />
        </>
      )}

      {data.today_deltas && (
        <>
          <div className="section-heading">Today's Output</div>
          <TodayOutputPanel deltas={data.today_deltas} />
        </>
      )}

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        Job Overview
      </div>
      <JobStatsPanel stats={data.job_stats || {}} order={order} labels={labels} />

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        Run History
        <FilterBar filters={filters} active={filter} onChange={setFilter} onRefresh={handleRefresh} style={{ margin: 0 }} />
      </div>

      <div>
        {runs.length === 0 ? (
          <div className="empty">No runs found</div>
        ) : (
          runs.slice(0, 50).map((r, i) => <RunCard key={`${r.timestamp}-${i}`} r={r} />)
        )}
      </div>

      {data.reported_items && <TrackedItems items={data.reported_items} />}
    </>
  );
}
