import { useMemo, useState } from 'react';
import type { DashboardData, LifelineEvent, LifelineGroup } from '@/api/types';
import { FilterBar } from '@/components/shared/FilterBar';
import { dateLabel } from '@/lib/utils';
import { FeedTab } from '@/components/tabs/Feed';

const GROUP_META: Record<LifelineGroup, { label: string; color: string; chip: string }> = {
  claude_md: { label: 'CLAUDE.md + MEMORY.md', color: 'var(--claude-md)', chip: 'CLAUDE' },
  daily:     { label: 'Daily notes',            color: 'var(--learning)',  chip: 'DAILY'  },
  skills:    { label: 'Skills',                 color: 'var(--skill)',     chip: 'SKILL'  },
  obsidian:  { label: 'Obsidian',               color: 'var(--knowledge)', chip: 'VAULT'  },
};

const FILTERS = [
  { value: 'feed',      label: 'Feed' },
  { value: 'all',       label: 'All' },
  { value: 'claude_md', label: 'CLAUDE.md' },
  { value: 'daily',     label: 'Daily' },
  { value: 'skills',    label: 'Skills' },
  { value: 'obsidian',  label: 'Obsidian' },
];

function EventRow({ ev }: { ev: LifelineEvent }) {
  const [open, setOpen] = useState(false);
  const meta = GROUP_META[ev.group];
  const fileList = ev.files.slice(0, 12);
  const extra = (ev.files_total || ev.files.length) - fileList.length;
  const hasDetail = ev.files.length > 0;

  return (
    <div className={`tl-event${open ? ' expanded' : ''}`}>
      <div className="tl-dot" style={{ background: meta.color }} />
      <div className="tl-card">
        <div
          className="tl-header"
          onClick={hasDetail ? () => setOpen(o => !o) : undefined}
          style={hasDetail ? { cursor: 'pointer' } : undefined}
        >
          <span
            className="cat-badge"
            style={{ background: 'transparent', border: `1px solid ${meta.color}`, color: meta.color }}
          >
            {meta.chip}
          </span>
          <span className="tl-summary">{ev.summary}</span>
          {ev.files.length > 0 && (
            <span className="tl-effect-chip">{ev.files_total || ev.files.length} file{(ev.files_total || ev.files.length) === 1 ? '' : 's'}</span>
          )}
          <span className="tl-time" title={ev.author}>
            {ev.time}
            <span style={{ opacity: 0.5, marginLeft: 8 }}>{ev.commit}</span>
          </span>
          {hasDetail && <span className="tl-chevron">&#9654;</span>}
        </div>
        {hasDetail && open && (
          <div className="tl-detail">
            <div className="tl-files">
              {fileList.map(f => <span key={f}>{f}</span>)}
              {extra > 0 && <span style={{ opacity: 0.6 }}>+{extra} more</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function LifelineTab({ data }: { data?: DashboardData }) {
  const [filter, setFilter] = useState<string>('feed');

  const events = useMemo<LifelineEvent[]>(() => data?.lifeline || [], [data]);

  const filtered = useMemo(() => {
    return filter === 'all' ? events : events.filter(e => e.group === filter);
  }, [events, filter]);

  const groups = useMemo(() => {
    const g: Record<string, LifelineEvent[]> = {};
    for (const ev of filtered) {
      if (!g[ev.date]) g[ev.date] = [];
      g[ev.date].push(ev);
    }
    return g;
  }, [filtered]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: events.length };
    for (const ev of events) c[ev.group] = (c[ev.group] || 0) + 1;
    return c;
  }, [events]);

  if (!data) return <div className="empty">Loading...</div>;

  const filtersWithCounts = FILTERS.map(f => {
    if (f.value === 'feed') return f;
    return { ...f, label: `${f.label} (${counts[f.value] || 0})` };
  });

  const stickyBar = (
    <FilterBar
      filters={filtersWithCounts}
      active={filter}
      onChange={setFilter}
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        background: 'var(--bg)',
        paddingTop: 8,
        paddingBottom: 8,
        marginBottom: 8,
      }}
    />
  );

  if (filter === 'feed') {
    return (
      <>
        {stickyBar}
        <FeedTab />
      </>
    );
  }

  return (
    <>
      {stickyBar}
      {filtered.length === 0 ? (
        <div className="timeline"><div className="empty">No system-made changes yet.</div></div>
      ) : (
        <div className="timeline">
          {Object.entries(groups).map(([day, items]) => (
            <div className="tl-day" key={day}>
              <div className="tl-day-label">{dateLabel(day)}</div>
              {items.map(ev => <EventRow key={`${ev.commit}-${ev.group}`} ev={ev} />)}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
