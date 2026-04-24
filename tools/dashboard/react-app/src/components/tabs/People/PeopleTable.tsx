import { useState, useMemo, useCallback } from 'react';
import { esc } from '@/lib/utils';
import { MdLink } from '@/components/shared/MdLink';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PersonObj = any;

const COLS = [
  { key: 'name', label: 'Name' },
  { key: 'company', label: 'Company' },
  { key: 'role', label: 'Role' },
  { key: 'location', label: 'Location' },
  { key: 'tags', label: 'Tags' },
  { key: 'last_contact', label: 'Last Contact' },
  { key: 'days_since_contact', label: 'Days' },
];

function contactColor(days: number | null | undefined): string {
  if (days == null) return 'var(--text-muted)';
  if (days <= 7) return 'var(--green)';
  if (days <= 30) return 'var(--yellow)';
  return 'var(--red)';
}

interface Props {
  people: PersonObj[];
  filter: string;
  searchVal: string;
}

export function PeopleTable({ people: rawPeople, filter, searchVal }: Props) {
  const [sortCol, setSortCol] = useState('name');
  const [sortAsc, setSortAsc] = useState(true);

  const handleSort = useCallback((col: string) => {
    if (sortCol === col) {
      setSortAsc(prev => !prev);
    } else {
      setSortCol(col);
      setSortAsc(col === 'days_since_contact' ? false : true);
    }
  }, [sortCol]);

  const people = useMemo(() => {
    let list = rawPeople.slice();

    // Apply filter
    if (filter === 'recent') list = list.filter((p: PersonObj) => p.days_since_contact != null && p.days_since_contact <= 7);
    else if (filter === 'stale') list = list.filter((p: PersonObj) => p.days_since_contact == null || p.days_since_contact > 30);
    else if (filter === 'no-contact') list = list.filter((p: PersonObj) => p.last_contact == null);

    // Apply search
    if (searchVal) {
      const sv = searchVal.toLowerCase();
      list = list.filter((p: PersonObj) =>
        (p.name || '').toLowerCase().includes(sv) ||
        (p.company || '').toLowerCase().includes(sv) ||
        (p.role || '').toLowerCase().includes(sv) ||
        (p.tags || []).some((t: string) => t.toLowerCase().includes(sv)) ||
        (p.handle || '').toLowerCase().includes(sv) ||
        (p.location || '').toLowerCase().includes(sv)
      );
    }

    // Sort
    list.sort((a: PersonObj, b: PersonObj) => {
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
  }, [rawPeople, filter, searchVal, sortCol, sortAsc]);

  if (people.length === 0) {
    return <div className="empty">No contacts match filter</div>;
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
        {people.map((p: PersonObj, i: number) => {
          const days = p.days_since_contact;
          const dColor = contactColor(days);
          const rowStyle: React.CSSProperties = {
            borderBottom: '1px solid var(--border)',
            ...(days != null && days > 30 ? { opacity: 0.7 } : {}),
          };
          return (
            <tr key={p.name || i} style={rowStyle}>
              <td style={{ padding: 6, fontWeight: 600, whiteSpace: 'nowrap' }}>
                <MdLink path={`People/${p.name}.md`} style={{ color: 'var(--text)', textDecoration: 'none', borderBottom: '1px dashed var(--text-muted)' }}>
                  {esc(p.name)}
                </MdLink>
              </td>
              <td style={{ padding: 6, color: 'var(--text-secondary)' }}>{esc(p.company || '-')}</td>
              <td style={{ padding: 6, color: 'var(--text-secondary)', fontSize: 11 }}>{esc(p.role || '-')}</td>
              <td style={{ padding: 6, color: 'var(--text-muted)', fontSize: 11 }}>{esc(p.location || '-')}</td>
              <td style={{ padding: 6 }}>
                {(p.tags || []).length > 0
                  ? (p.tags as string[]).map((t: string, ti: number) => (
                    <span key={ti} style={{
                      background: 'var(--bg-elevated)', padding: '1px 5px',
                      borderRadius: 3, fontSize: 10, color: 'var(--text-secondary)', marginRight: 3,
                    }}>{esc(t)}</span>
                  ))
                  : '-'}
              </td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)', fontSize: 11, color: dColor }}>
                {p.last_contact || 'never'}
              </td>
              <td style={{ padding: 6, fontFamily: 'var(--mono)', fontSize: 11, color: dColor, fontWeight: 600 }}>
                {days != null ? days + 'd' : '-'}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
