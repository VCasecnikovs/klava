import type { DashboardData } from '@/api/types';
import { KPIRow } from '@/components/shared/KPIRow';
import { Panel } from '@/components/shared/Panel';
import { fmtCost, fmt } from '@/lib/utils';
import { useVadimgestUrl } from '@/hooks/useVadimgestUrl';
import { ServiceStrip } from './ServiceStrip';

import { CronJobsList } from './CronJobsList';
import { ActivityFeed } from './ActivityFeed';

export function HealthTab({ data }: { data?: DashboardData }) {
  const vadimgestUrl = useVadimgestUrl();
  if (!data) return <div className="empty">Loading...</div>;

  const svcs = data.services || [];
  const healthy = svcs.filter(s => s.running).length;
  const total = svcs.length;
  const st = data.stats || { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 };
  const stAny = st as unknown as Record<string, unknown>;
  const healthScore = (stAny.health_score as number) ?? 0;

  // Scheduler info for costs panel
  const dataAny = data as unknown as Record<string, unknown>;
  const sched = (dataAny.scheduler as Record<string, unknown>) ?? {};
  const allTimeRuns = (stAny.all_time_runs as number) ?? 0;

  const scoreColor = healthScore >= 90 ? 'var(--green)' : healthScore >= 70 ? 'var(--yellow)' : 'var(--red)';

  return (
    <>
      <KPIRow kpis={[
        { val: `${healthScore}%`, label: 'Health', color: scoreColor },
        { val: `${healthy}/${total}`, label: 'Services', color: healthy === total ? 'var(--green)' : 'var(--red)' },
        { val: st.runs_24h || 0, label: 'Runs / 24h' },
        { val: st.failures_24h || 0, label: 'Failures', color: (st.failures_24h || 0) > 0 ? 'var(--red)' : 'var(--green)' },
        { val: fmtCost(st.total_cost_usd), label: 'Total Cost', color: 'var(--yellow)' },
      ]} />

      <Panel title="Services" help="macOS LaunchAgent daemons. Green = running. Auto-restart via launchd.">
        <ServiceStrip services={svcs} />
      </Panel>

      <div style={{ padding: '0 4px 8px' }}>
        <a
          href={vadimgestUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--text-secondary)', fontSize: '13px', textDecoration: 'none' }}
        >
          View data sources in vadimgest &#x2197;
        </a>
      </div>

      <Panel title="CRON Jobs" help="Scheduled tasks run by cron-scheduler.py. Modes: main = shared session, isolated = own session, bash = shell.">
        <CronJobsList jobs={data.cron_jobs || []} />
      </Panel>

      <Panel title="Activity Feed" help="Recent CRON executions. Click to expand output. Cost = API spend per run.">
        <ActivityFeed items={data.activity || []} />
      </Panel>

      <Panel title="Costs">
        <div className="kpi-row" style={{ margin: 0 }}>
          <div className="kpi">
            <div className="kpi-val" style={{ color: 'var(--yellow)' }}>{fmtCost(st.total_cost_usd)}</div>
            <div className="kpi-label">Total Cost</div>
          </div>
          <div className="kpi">
            <div className="kpi-val">{fmt(allTimeRuns)}</div>
            <div className="kpi-label">All-time Runs</div>
          </div>
          <div className="kpi">
            <div className="kpi-val" style={{ color: 'var(--text-secondary)' }}>
              {(sched.uptime_display as string) || '?'}
            </div>
            <div className="kpi-label">Uptime</div>
          </div>
        </div>
      </Panel>
    </>
  );
}
