import { esc } from '@/lib/utils';

interface PipelineStage {
  stage: string;
  stage_num: number;
  count: number;
  total_value: number;
}

function fmtCurrency(val: number | null | undefined): string {
  if (val == null) return '-';
  if (val >= 1000000) return '$' + (val / 1000000).toFixed(1) + 'M';
  if (val >= 1000) return '$' + val.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return '$' + val.toFixed(0);
}

function stageColor(num: number): string {
  if (num <= 3) return 'var(--text-muted)';
  if (num <= 6) return 'var(--yellow)';
  if (num <= 9) return 'var(--blue)';
  if (num <= 12) return 'var(--green)';
  return 'var(--claude-md)';
}

export function PipelineChart({ stages }: { stages?: PipelineStage[] }) {
  if (!stages || stages.length === 0) {
    return <div className="empty">No active deals</div>;
  }

  const maxCount = Math.max(...stages.map(s => s.count), 1);

  return (
    <div>
      {stages.map((s, i) => {
        const pct = Math.max((s.count / maxCount) * 100, 8);
        const color = stageColor(s.stage_num);
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <span style={{ minWidth: 120, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-secondary)', textAlign: 'right' }}>
              {esc(s.stage)}
            </span>
            <div style={{ flex: 1, height: 22, background: 'var(--bg-elevated)', borderRadius: 'var(--radius-xs)', overflow: 'hidden', position: 'relative' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 'var(--radius-xs)', opacity: 0.7, transition: 'width 0.3s' }} />
            </div>
            <span style={{ minWidth: 30, fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 600, textAlign: 'right' }}>{s.count}</span>
            <span style={{ minWidth: 70, fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--text-muted)', textAlign: 'right' }}>{fmtCurrency(s.total_value)}</span>
          </div>
        );
      })}
    </div>
  );
}
