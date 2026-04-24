import { useState } from 'react';
import type { ActivityEntry } from '@/api/types';
import { FilterBar } from '@/components/shared/FilterBar';
import { fmtCost } from '@/lib/utils';

/** Build activity filters dynamically from the job_ids present in the data. */
function buildActivityFilters(items: ActivityEntry[]) {
  const jobIds = [...new Set(items.map(i => i.job_id).filter(Boolean))].sort();
  const hasErrors = items.some(i => i.error || i.status === 'failed');
  return [
    { value: 'all', label: 'All' },
    ...jobIds.map(id => ({
      value: id,
      label: id.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
    })),
    ...(hasErrors ? [{ value: 'errors', label: 'Errors' }] : []),
  ];
}

export function ActivityFeed({ items }: { items: ActivityEntry[] }) {
  const [filter, setFilter] = useState('all');
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  const filters = buildActivityFilters(items);

  const filtered = items.filter(item => {
    if (filter === 'all') return true;
    if (filter === 'errors') return item.error || item.status === 'failed';
    return item.job_id === filter;
  });

  const toggleKey = (key: string) => {
    setExpandedKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  return (
    <>
      <FilterBar filters={filters} active={filter} onChange={setFilter} />
      <div>
        {filtered.length === 0 ? (
          <div className="empty">No activity matching filter</div>
        ) : (
          filtered.map((item, i) => {
            const costStr = item.cost_usd && item.cost_usd > 0 ? fmtCost(item.cost_usd) : '';
            const hasExpand = !!(item.output || item.error);
            const content = item.error || item.output || '';
            const key = `health-act-${item.job_id}-${item.timestamp || i}`;
            const isExpanded = expandedKeys.has(key);

            return (
              <div className={`act-item${isExpanded ? ' expanded' : ''}`} key={key}>
                <div
                  className="act-header"
                  onClick={hasExpand ? () => toggleKey(key) : undefined}
                >
                  <div className={`svc-dot ${item.error ? 'off' : 'on'}`} />
                  <span className="act-time">{item.ago || ''}</span>
                  <span className="act-job">{item.job_id}</span>
                  <span className="act-dur">{item.duration_seconds}s</span>
                  <span className="act-cost">{costStr}</span>
                  {hasExpand && <span className="act-chevron">&#9654;</span>}
                </div>
                {hasExpand && isExpanded && (
                  <div className={`act-output${item.error ? ' error' : ''}`} style={{ display: 'block' }}>
                    {content}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </>
  );
}
