import { useState } from 'react';
import type { CronJob, CronRunDot } from '@/api/types';

type CronJobRow = CronJob & {
  name?: string;
  status?: string;
  schedule_display?: string;
  last_run_ago?: string;
  runs_24h?: number;
  avg_duration_s?: number;
};

function RunDots({ runs }: { runs: CronRunDot[] }) {
  if (!runs || runs.length === 0) return null;
  return (
    <div className="run-dots" title="Recent runs (oldest → newest)">
      {runs.map((r, i) => (
        <span
          key={i}
          className={`run-dot ${r.ok ? 'ok' : 'fail'}`}
          title={`${r.ok ? 'OK' : 'FAIL'} · ${r.dur}s · ${r.ts?.slice(11, 16) || '?'}`}
        />
      ))}
    </div>
  );
}

function SuccessRate({ rate }: { rate: number | null | undefined }) {
  if (rate === null || rate === undefined) return null;
  const color = rate >= 95 ? 'var(--green)' : rate >= 70 ? 'var(--yellow)' : 'var(--red)';
  return (
    <span className="cron-badge" style={{ background: `${color}22`, color }}>
      {rate}%
    </span>
  );
}

export function CronJobsList({ jobs }: { jobs: CronJob[] }) {
  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    setExpandedJobs(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div>
      {(jobs as CronJobRow[]).map((j, i) => {
        let dotColor = '--text-muted';
        let cls = '';
        if (!j.enabled) {
          cls = 'disabled';
        } else if (j.status === 'completed') dotColor = '--green';
        else if (j.status === 'failed') dotColor = '--red';
        else if (j.status === 'running') dotColor = '--yellow';

        const hasError = !!j.last_error;
        const isExpanded = expandedJobs.has(j.id);

        return (
          <div className={`cron-row ${cls}${hasError ? ' has-error' : ''}`} key={i}>
            <div
              className="cron-main"
              onClick={hasError ? () => toggleExpand(j.id) : undefined}
              style={hasError ? { cursor: 'pointer' } : undefined}
            >
              <div className="cron-dot" style={{ background: `var(${dotColor})` }} />
              <span className="cron-name">{j.name || j.id}</span>
              <span className="cron-badge cron-badge-mode">{j.mode}</span>
              {j.model && <span className="cron-badge cron-badge-model">{j.model}</span>}
              <SuccessRate rate={j.success_rate_24h} />
              <RunDots runs={j.recent_runs || []} />
              {hasError && (
                <span className="cron-error-chevron" style={{ transform: isExpanded ? 'rotate(90deg)' : undefined }}>
                  &#9654;
                </span>
              )}
            </div>
            <div className="cron-meta">
              <span>{j.schedule_display || j.schedule}</span>
              <span>{j.last_run_ago || (j.last_run || 'never')}</span>
              <span>{j.runs_24h ?? 0} runs/24h</span>
              <span>{j.avg_duration_s ?? 0}s avg</span>
            </div>
            {hasError && isExpanded && (
              <div className="cron-error-detail">{j.last_error}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
