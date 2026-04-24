import { useState, useMemo, useCallback } from 'react';
import { useDeals } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { FilterBar } from '@/components/shared/FilterBar';
import { showToast } from '@/components/shared/Toast';
import { DealsTable } from './DealsTable';
import { DealDetail } from './DealDetail';
import { PipelineChart } from './PipelineChart';
import { esc } from '@/lib/utils';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DealObj = any;

function fmtCurrency(val: number | null | undefined): string {
  if (val == null) return '-';
  if (val >= 1000000) return '$' + (val / 1000000).toFixed(1) + 'M';
  if (val >= 1000) return '$' + val.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return '$' + val.toFixed(0);
}

const DEALS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'priority', label: 'Priority' },
  { value: 'stalled', label: 'Stalled' },
  { value: 'lost', label: 'Lost' },
];

export function DealsTab() {
  const { data, refetch } = useDeals(true);
  const [filter, setFilter] = useState('all');
  const handleRefresh = useCallback(() => { refetch(); showToast('Refreshing...'); }, [refetch]);
  const [searchVal, setSearchVal] = useState('');
  const [detailDeal, setDetailDeal] = useState<string | null>(null);

  const kpis = useMemo(() => {
    if (!data) return [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const m = (data as any).metrics || {};
    return [
      { val: fmtCurrency(m.total_pipeline), label: 'Total Pipeline' },
      { val: fmtCurrency(m.weighted_pipeline), label: 'Weighted Pipeline' },
      { val: m.active_count || 0, label: 'Active Deals' },
      { val: m.overdue_count || 0, label: 'Overdue Follow-ups', color: (m.overdue_count || 0) > 0 ? 'var(--red)' : 'var(--text)' },
    ];
  }, [data]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const deals: DealObj[] = (data as any)?.deals || [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pipelineStages = (data as any)?.pipeline_stages || [];

  const priorityDeals = useMemo(() =>
    deals.filter((d: DealObj) => d.is_priority && d.is_active),
    [deals]
  );

  const overdueDeals = useMemo(() =>
    deals
      .filter((d: DealObj) => d.overdue && d.is_active)
      .sort((a: DealObj, b: DealObj) => (a.days_until_follow_up || 0) - (b.days_until_follow_up || 0))
      .slice(0, 10),
    [deals]
  );

  if (!data) return <div className="empty">Loading deals...</div>;

  // Detail view
  if (detailDeal) {
    const d = deals.find((x: DealObj) => x.name === detailDeal);
    if (d) {
      return <DealDetail deal={d} onBack={() => setDetailDeal(null)} />;
    }
    // Deal not found - fall through to list view (button click will clear detailDeal)
  }

  // List mode
  return (
    <>
      <KPIRow kpis={kpis} />

      {/* Priority Deals */}
      {priorityDeals.length > 0 && (
        <>
          <div className="section-heading">Priority Deals</div>
          <div>
            {priorityDeals.map((d: DealObj) => {
              const followStatus = d.overdue
                ? <span style={{ color: 'var(--red)', fontWeight: 600 }}>OVERDUE {Math.abs(d.days_until_follow_up)}d</span>
                : d.days_until_follow_up === 0
                  ? <span style={{ color: 'var(--yellow)', fontWeight: 600 }}>DUE TODAY</span>
                  : d.follow_up
                    ? <span style={{ color: 'var(--text-secondary)' }}>{d.days_until_follow_up}d</span>
                    : null;
              return (
                <div key={d.name} style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
                  background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderLeft: '3px solid var(--blue)', borderRadius: 'var(--radius-sm)', marginBottom: 6,
                }}>
                  <a className="deal-name-link" onClick={() => setDetailDeal(d.name)} style={{ fontWeight: 600, minWidth: 200 }}>
                    {esc(d.name)}
                  </a>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-secondary)', minWidth: 120 }}>
                    {esc(d.stage)}
                  </span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 12, minWidth: 90 }}>
                    {fmtCurrency(d.value)}
                  </span>
                  {followStatus}
                  {d.next_action && (
                    <span style={{
                      color: 'var(--text-muted)', fontSize: 11, marginLeft: 'auto',
                      maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }} title={d.next_action}>
                      {esc(d.next_action)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Overdue Follow-ups */}
      {overdueDeals.length > 0 && (
        <>
          <div className="section-heading">Overdue Follow-ups</div>
          <div>
            {overdueDeals.map((d: DealObj) => {
              const days = Math.abs(d.days_until_follow_up || 0);
              return (
                <div key={d.name} style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '8px 14px',
                  background: 'var(--red-dim)', border: '1px solid rgba(248,113,113,0.2)',
                  borderRadius: 'var(--radius-sm)', marginBottom: 4, fontSize: 12,
                }}>
                  <span style={{ color: 'var(--red)', fontWeight: 600, minWidth: 60 }}>{days}d late</span>
                  <a className="deal-name-link" onClick={() => setDetailDeal(d.name)} style={{ fontWeight: 600, minWidth: 200 }}>
                    {esc(d.name)}
                  </a>
                  <span style={{ color: 'var(--text-secondary)' }}>{esc(d.stage)}</span>
                  <span style={{ fontFamily: 'var(--mono)' }}>{fmtCurrency(d.value)}</span>
                  <span style={{ color: 'var(--text-muted)', marginLeft: 'auto' }}>{d.follow_up || ''}</span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Pipeline heading + filter + search */}
      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        Pipeline
        <FilterBar filters={DEALS_FILTERS} active={filter} onChange={setFilter} onRefresh={handleRefresh} style={{ margin: 0 }} />
        <input
          type="text"
          placeholder="Search deals..."
          value={searchVal}
          onChange={e => setSearchVal(e.target.value)}
          style={{
            marginLeft: 'auto', background: 'var(--bg-elevated)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-xs)',
            color: 'var(--text)', padding: '4px 10px', fontSize: 12, width: 180, outline: 'none',
          }}
        />
      </div>

      <DealsTable
        deals={deals}
        filter={filter}
        searchVal={searchVal}
        onOpenDeal={setDetailDeal}
      />

      <div className="section-heading">Stage Pipeline</div>
      <PipelineChart stages={pipelineStages} />
    </>
  );
}
