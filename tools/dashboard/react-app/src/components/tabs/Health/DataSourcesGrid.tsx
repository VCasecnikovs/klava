import type { DataSource } from '@/api/types';
import { fmt } from '@/lib/utils';

// The API may return extra fields
type DSRow = DataSource & {
  sync_type?: string;
  last_sync_ago?: string;
  added_1h?: number;
};

export function DataSourcesGrid({ sources, totalRecords }: { sources: DataSource[]; totalRecords: number }) {
  return (
    <div className="ds-grid">
      {(sources as DSRow[]).map((s, i) => {
        const pct = Math.max(3, Math.min(100, s.records / (totalRecords || 1) * 100));
        const hasMissingDeps = s.deps_ok === false;
        const isStale = !s.healthy;
        const freshness = s.sync_type === 'daemon'
          ? (s.last_data_ago || 'never')
          : (s.last_sync_ago && s.last_sync_ago !== 'never' ? s.last_sync_ago : (s.last_data_ago || 'never'));
        const addedStr = s.added_1h && s.added_1h > 0 ? `+${s.added_1h}/1h` : '';

        return (
          <div className={`ds-card${isStale ? ' stale' : ''}`} key={i} title={hasMissingDeps ? (s.missing_deps || []).join(', ') : undefined}>
            <div className="ds-header">
              <div className={`svc-dot ${hasMissingDeps ? 'warn' : isStale ? 'off' : 'on'}`} />
              <span className="ds-name">{s.name}</span>
              {s.sync_type && <span className={`ds-type ${s.sync_type}`}>{s.sync_type}</span>}
            </div>
            <div className="ds-bar">
              <div className={`ds-bar-fill ${isStale ? 'bad' : 'ok'}`} style={{ width: `${pct}%` }} />
            </div>
            <div className="ds-stats">
              <span>{fmt(s.records)} records</span>
              <span>{hasMissingDeps ? 'deps missing' : (addedStr || freshness)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
