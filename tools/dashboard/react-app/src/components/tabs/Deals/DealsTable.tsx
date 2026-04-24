import { useState, useMemo, useCallback } from 'react';
import { esc } from '@/lib/utils';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DealObj = any;

function fmtCurrency(val: number | null | undefined): string {
  if (val == null) return '-';
  if (val >= 1000000) return '$' + (val / 1000000).toFixed(1) + 'M';
  if (val >= 1000) return '$' + val.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return '$' + val.toFixed(0);
}

const COLS = [
  { key: 'name', label: 'Deal' },
  { key: 'stage_num', label: 'Stage' },
  { key: 'value', label: 'Value ($)' },
  { key: 'mrr', label: 'MRR ($)' },
  { key: 'owner', label: 'Owner' },
  { key: 'last_contact', label: 'Last Contact' },
  { key: 'follow_up', label: 'Follow-up' },
  { key: 'days_in_stage', label: 'Status (days)' },
  { key: 'product', label: 'Product' },
];

interface Props {
  deals: DealObj[];
  filter: string;
  searchVal: string;
  onOpenDeal: (name: string) => void;
}

export function DealsTable({ deals: rawDeals, filter, searchVal, onOpenDeal }: Props) {
  const [sortCol, setSortCol] = useState('stage_num');
  const [sortAsc, setSortAsc] = useState(true);

  const handleSort = useCallback((col: string) => {
    if (sortCol === col) {
      setSortAsc(prev => !prev);
    } else {
      setSortCol(col);
      setSortAsc(true);
    }
  }, [sortCol]);

  const deals = useMemo(() => {
    let list = rawDeals.slice();

    // Apply filter
    if (filter === 'active') list = list.filter((d: DealObj) => d.is_active);
    else if (filter === 'overdue') list = list.filter((d: DealObj) => d.overdue && d.is_active);
    else if (filter === 'priority') list = list.filter((d: DealObj) => d.is_priority);
    else if (filter === 'stalled') list = list.filter((d: DealObj) => d.stage_num === 16);
    else if (filter === 'lost') list = list.filter((d: DealObj) => d.stage_num === 17);

    // Apply search
    if (searchVal) {
      const sv = searchVal.toLowerCase();
      list = list.filter((d: DealObj) =>
        (d.name || '').toLowerCase().includes(sv) ||
        (d.owner || '').toLowerCase().includes(sv) ||
        (d.product || '').toLowerCase().includes(sv) ||
        (d.stage || '').toLowerCase().includes(sv)
      );
    }

    // Sort
    list.sort((a: DealObj, b: DealObj) => {
      let av = a[sortCol], bv = b[sortCol];
      if (av == null) av = sortAsc ? Infinity : -Infinity;
      if (bv == null) bv = sortAsc ? Infinity : -Infinity;
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });

    return list;
  }, [rawDeals, filter, searchVal, sortCol, sortAsc]);

  if (deals.length === 0) {
    return <div className="empty">No deals match filter</div>;
  }

  const sortIcon = (col: string) => sortCol === col ? (sortAsc ? ' \u2191' : ' \u2193') : '';

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr>
          {COLS.map(col => (
            <th
              key={col.key}
              onClick={() => handleSort(col.key)}
              style={{
                textAlign: 'left', padding: '8px 6px',
                borderBottom: '2px solid var(--border)',
                color: 'var(--text-muted)', fontSize: 10,
                textTransform: 'uppercase', letterSpacing: '0.5px',
                cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none',
              }}
            >
              {col.label}{sortIcon(col.key)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {deals.map((d: DealObj, i: number) => {
          let rowStyle: React.CSSProperties = { borderBottom: '1px solid var(--border)' };
          if (d.overdue && d.is_active) rowStyle = { ...rowStyle, background: 'var(--red-dim)' };
          else if (d.days_until_follow_up === 0 && d.is_active) rowStyle = { ...rowStyle, background: 'var(--yellow-dim)' };
          if (d.is_priority) rowStyle = { ...rowStyle, borderLeft: '3px solid var(--blue)' };

          const stageColor = d.stage_num >= 16 ? 'var(--text-muted)' : d.stage_num >= 10 ? 'var(--green)' : d.stage_num >= 7 ? 'var(--blue)' : d.stage_num >= 4 ? 'var(--yellow)' : 'var(--text-secondary)';
          const fuColor = d.overdue ? 'var(--red)' : d.days_until_follow_up === 0 ? 'var(--yellow)' : 'var(--text-secondary)';
          const daysDisplay = d.days_in_stage != null ? d.days_in_stage + 'd' : '-';

          return (
            <tr key={d.name || i} style={rowStyle}>
              <td style={{ padding: 6, fontWeight: 600, whiteSpace: 'nowrap' }}>
                <a className="deal-name-link" onClick={() => onOpenDeal(d.name)}>{esc(d.name)}</a>
              </td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)', fontSize: 11, color: stageColor }}>{esc(d.stage)}</td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)' }}>{fmtCurrency(d.value)}</td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)' }}>{fmtCurrency(d.mrr)}</td>
              <td style={{ padding: 6, color: 'var(--text-secondary)' }}>{esc(d.owner || '-')}</td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)', fontSize: 11 }}>{d.last_contact || '-'}</td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)', fontSize: 11, color: fuColor }}>{d.follow_up || '-'}</td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)', fontSize: 11 }}>{daysDisplay}</td>
              <td style={{ padding: 6, color: 'var(--text-secondary)', fontSize: 11 }}>{esc(d.product || '-')}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
