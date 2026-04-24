import { fmtCost } from '@/lib/utils';
import type { DashboardData } from '@/api/types';
import { useVadimgestUrl } from '@/hooks/useVadimgestUrl';

interface PulseProps {
  data: DashboardData | undefined;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export function Pulse({ data, onRefresh, isRefreshing }: PulseProps) {
  const vadimgestUrl = useVadimgestUrl();
  const svcs = data?.services || [];
  const healthy = svcs.filter(s => s.running).length;
  const total = svcs.length;
  const st = data?.stats;
  const stAny = st as unknown as Record<string, unknown>;
  const healthScore = (stAny?.health_score as number) ?? null;

  const scoreColor = healthScore === null ? 'var(--text-muted)'
    : healthScore >= 90 ? 'var(--green)'
    : healthScore >= 70 ? 'var(--yellow)'
    : 'var(--red)';

  const dotClass = healthScore !== null && healthScore < 70 ? 'health-dot error'
    : healthScore !== null && healthScore < 90 ? 'health-dot warn'
    : 'health-dot';

  return (
    <div className="pulse">
      <div className="pulse-inner">
        <div className="pulse-title"><em>Klava</em> mission control</div>
        <div className="pulse-stats">
          <div className={dotClass} />
          {healthScore !== null && (
            <div className="pulse-stat">
              Health <span className="pulse-stat-val" style={{ color: scoreColor }}>{healthScore}%</span>
            </div>
          )}
          <div className="pulse-stat">Services <span className="pulse-stat-val">{data ? `${healthy}/${total}` : '-'}</span></div>
          <div className="pulse-stat">Runs/24h <span className="pulse-stat-val">{st?.runs_24h ?? '-'}</span></div>
          <div className="pulse-stat">Failures <span className="pulse-stat-val">{st?.failures_24h ?? '-'}</span></div>
          <div className="pulse-stat">Cost <span className="pulse-stat-val">{st ? fmtCost(st.total_cost_usd) : '-'}</span></div>
          <button className="refresh-btn" onClick={onRefresh}>
            {isRefreshing ? '...' : 'refresh'}
          </button>
          <a
            href={vadimgestUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="refresh-btn"
            style={{ textDecoration: 'none' }}
          >
            vadimgest &#x2197;
          </a>
        </div>
      </div>
    </div>
  );
}
