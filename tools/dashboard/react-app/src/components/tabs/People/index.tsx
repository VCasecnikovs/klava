import { useState, useMemo, useCallback } from 'react';
import { usePeople } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { FilterBar } from '@/components/shared/FilterBar';
import { showToast } from '@/components/shared/Toast';
import { PeopleTable } from './PeopleTable';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PeopleDataObj = any;

const PEOPLE_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'recent', label: 'Recent (7d)' },
  { value: 'stale', label: 'Stale (30d+)' },
  { value: 'no-contact', label: 'Never Contacted' },
];

export function PeopleTab() {
  const { data, refetch } = usePeople(true);
  const [filter, setFilter] = useState('all');
  const handleRefresh = useCallback(() => { refetch(); showToast('Refreshing...'); }, [refetch]);
  const [searchVal, setSearchVal] = useState('');

  const kpis = useMemo(() => {
    if (!data) return [];
    const m = (data as PeopleDataObj).metrics || {};
    return [
      { val: m.total_contacts || 0, label: 'Total Contacts' },
      { val: m.companies || 0, label: 'Companies' },
      { val: m.recent_7d || 0, label: 'Contacted (7d)', color: 'var(--green)' },
      { val: m.stale_30d || 0, label: 'Stale (30d+)', color: (m.stale_30d || 0) > 0 ? 'var(--red)' : 'var(--text)' },
    ];
  }, [data]);

  if (!data) return <div className="empty">Loading contacts...</div>;

  const people = (data as PeopleDataObj).people || [];

  return (
    <>
      <KPIRow kpis={kpis} />

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        Contacts
        <FilterBar filters={PEOPLE_FILTERS} active={filter} onChange={setFilter} onRefresh={handleRefresh} style={{ margin: 0 }} />
        <input
          type="text"
          placeholder="Search name, company, tag..."
          value={searchVal}
          onChange={e => setSearchVal(e.target.value)}
          style={{
            marginLeft: 'auto', background: 'var(--bg-elevated)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-xs)',
            color: 'var(--text)', padding: '4px 10px', fontSize: 12, width: 220, outline: 'none',
          }}
        />
      </div>

      <PeopleTable people={people} filter={filter} searchVal={searchVal} />
    </>
  );
}
