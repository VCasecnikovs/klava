import { useSources } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { Panel } from '@/components/shared/Panel';
import { useVadimgestUrl } from '@/hooks/useVadimgestUrl';
import type { SourceManifest } from '@/api/types';
import { useState } from 'react';

const CATEGORY_ORDER = [
  'messaging', 'email', 'calendar', 'dev', 'files',
  'activity', 'meetings', 'social', 'knowledge',
];

const CATEGORY_LABELS: Record<string, string> = {
  messaging: 'Messaging',
  email: 'Email',
  calendar: 'Calendar & Tasks',
  dev: 'Development',
  files: 'Files & Storage',
  activity: 'Activity Tracking',
  meetings: 'Meetings',
  social: 'Social',
  knowledge: 'Knowledge Base',
};

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function fmtNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

function SourceCard({
  name,
  source,
  maxRecords,
}: {
  name: string;
  source: SourceManifest;
  maxRecords: number;
}) {
  const [expanded, setExpanded] = useState(false);

  const isActive = source.enabled && source.ready?.ok;
  const isWarn = source.enabled && !source.ready?.ok;
  const dotClass = isActive ? 'active' : isWarn ? 'warn' : 'off';
  const badgeLabel = isActive ? 'Active' : isWarn ? 'Missing' : 'Off';
  const cardClass = `src-card${!source.enabled ? ' disabled' : ''}${isWarn ? ' warn' : ''}`;

  const deps = source.dependencies;
  const hasDeps =
    deps.python.length + deps.cli.length + deps.credentials.length + deps.os.length > 0;

  const barPct = source.stats
    ? Math.max(3, Math.min(100, (source.stats.record_count / (maxRecords || 1)) * 100))
    : 0;

  return (
    <div className={cardClass} onClick={() => setExpanded(!expanded)}>
      <div className="src-header">
        <span className={`src-dot ${dotClass}`} />
        <span className="src-name">{source.display_name}</span>
        <span className={`src-badge ${dotClass}`}>{badgeLabel}</span>
      </div>

      <div className="src-desc">{source.description}</div>

      {source.stats && (
        <>
          <div className="src-bar">
            <div className="src-bar-fill" style={{ width: `${barPct}%` }} />
          </div>
          <div className="src-stats">
            <span className="highlight">{fmtNumber(source.stats.record_count)} records</span>
            <span>{fmtBytes(source.stats.file_size)}</span>
            <span>{fmtAgo(source.stats.last_modified)}</span>
          </div>
        </>
      )}

      {!source.stats && !source.enabled && (
        <div className="src-stats">
          <span>No data</span>
        </div>
      )}

      {isWarn && source.ready?.missing && (
        <div className="src-missing">
          {source.ready.missing.map((m, i) => (
            <span key={i}>{m}</span>
          ))}
        </div>
      )}

      {expanded && hasDeps && (
        <div className="src-deps">
          {deps.python.length > 0 && (
            <div><strong>Python:</strong> {deps.python.join(', ')}</div>
          )}
          {deps.cli.length > 0 && (
            <div><strong>CLI:</strong> {deps.cli.join(', ')}</div>
          )}
          {deps.credentials.length > 0 && (
            <div><strong>Env:</strong> {deps.credentials.join(', ')}</div>
          )}
          {deps.os.length > 0 && (
            <div><strong>OS:</strong> {deps.os.join(', ')}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function SourcesTab() {
  const { data, isFetching } = useSources(true);
  const vadimgestUrl = useVadimgestUrl();

  if (!data) return <div className="empty">{isFetching ? 'Loading...' : 'No data'}</div>;

  const entries = Object.entries(data);
  const total = entries.length;
  const enabled = entries.filter(([, s]) => s.enabled).length;
  const ready = entries.filter(([, s]) => s.ready?.ok).length;
  const totalRecords = entries.reduce((sum, [, s]) => sum + (s.stats?.record_count || 0), 0);
  const maxRecords = Math.max(...entries.map(([, s]) => s.stats?.record_count || 0));

  // Group by category
  const grouped = new Map<string, [string, SourceManifest][]>();
  for (const entry of entries) {
    const cat = entry[1].category || 'other';
    if (!grouped.has(cat)) grouped.set(cat, []);
    grouped.get(cat)!.push(entry);
  }

  // Sort categories, within each: enabled first, then by record count
  const sortedCategories = [...grouped.keys()].sort(
    (a, b) => (CATEGORY_ORDER.indexOf(a) ?? 99) - (CATEGORY_ORDER.indexOf(b) ?? 99),
  );
  for (const cat of sortedCategories) {
    grouped.get(cat)!.sort(([, a], [, b]) => {
      if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
      return (b.stats?.record_count || 0) - (a.stats?.record_count || 0);
    });
  }

  return (
    <>
      <KPIRow
        kpis={[
          { val: total, label: 'Total Sources' },
          { val: enabled, label: 'Enabled', color: 'var(--green)' },
          { val: ready, label: 'Ready', color: ready === enabled ? 'var(--green)' : 'var(--yellow)' },
          { val: fmtNumber(totalRecords), label: 'Total Records', color: 'var(--claude-md)' },
        ]}
      />

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <a
          href={vadimgestUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '6px 14px',
            borderRadius: 8,
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
            fontSize: 12,
            textDecoration: 'none',
            transition: 'border-color 0.15s',
          }}
        >
          Manage sources in vadimgest &#x2197;
        </a>
      </div>

      {sortedCategories.map((cat) => (
        <Panel key={cat} title={CATEGORY_LABELS[cat] || cat}>
          <div className="src-grid">
            {grouped.get(cat)!.map(([name, source]) => (
              <SourceCard key={name} name={name} source={source} maxRecords={maxRecords} />
            ))}
          </div>
        </Panel>
      ))}
    </>
  );
}
