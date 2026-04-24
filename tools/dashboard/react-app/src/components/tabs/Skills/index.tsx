import { useState } from 'react';
import type { DashboardData, Skill, SkillChange } from '@/api/types';
import { KPIRow } from '@/components/shared/KPIRow';
import { dateLabel } from '@/lib/utils';

type SortMode = 'calls' | 'last' | 'modified';

// The API may return additional fields not on the base Skill type
type SkillRow = Skill & {
  call_count?: number;
  last_call?: string;
  last_call_ago?: string;
  last_modified?: string;
  last_modified_ago?: string;
  calls?: { timestamp?: string; time?: string; status?: string; result?: string }[];
  git_commits?: { hash?: string; message?: string }[];
};

// The API may return additional fields on SkillChange
type SkillChangeRow = SkillChange & {
  hash?: string;
  message?: string;
  files?: string[];
  insertions?: number;
  deletions?: number;
  diff_preview?: string;
};

function SkillCard({ s, expanded, onToggle }: { s: SkillRow; expanded: boolean; onToggle: () => void }) {
  const dotColor = s.error_count > 0 ? 'var(--red)' : 'var(--green)';
  const callsStr = (s.call_count || s.calls_30d) ? `${s.call_count || s.calls_30d} calls` : 'no calls';
  const lastCall = s.last_call_ago ? `last: ${s.last_call_ago}` : (s.last_used ? `last: ${s.last_used}` : '');
  const lastMod = s.last_modified_ago ? `mod: ${s.last_modified_ago}` : (s.modified ? `mod: ${s.modified}` : '');

  const hasDetail = !!(s.description || (s.calls && s.calls.length > 0) || (s.git_commits && s.git_commits.length > 0));

  return (
    <div className={`skill-card${expanded ? ' expanded' : ''}`}>
      <div className="skill-header" onClick={hasDetail ? onToggle : undefined}>
        <div className="skill-dot" style={{ background: dotColor }} />
        <span className="skill-name">{s.name}</span>
        <span className="skill-meta">
          <span>{callsStr}</span>
          {lastCall && <span>{lastCall}</span>}
          {lastMod && <span>{lastMod}</span>}
        </span>
        {hasDetail && <span className="skill-chevron">&#9654;</span>}
      </div>
      {hasDetail && expanded && (
        <div className="skill-detail" style={{ display: 'block' }}>
          {s.description && (
            <div className="skill-detail-section">
              <div className="skill-detail-section-title">Description</div>
              {s.description}
            </div>
          )}
          {s.calls && s.calls.length > 0 && (
            <div className="skill-detail-section">
              <div className="skill-detail-section-title">Recent Calls</div>
              {s.calls.slice(0, 5).map((c, i) => (
                <div className="skill-call-item" key={i}>
                  <span>{c.timestamp || c.time || ''}</span> - <span>{c.status || c.result || ''}</span>
                </div>
              ))}
            </div>
          )}
          {s.git_commits && s.git_commits.length > 0 && (
            <div className="skill-detail-section">
              <div className="skill-detail-section-title">Git History</div>
              {s.git_commits.slice(0, 5).map((c, i) => (
                <div className="skill-commit-item" key={i}>
                  <code style={{ color: 'var(--text-muted)' }}>{(c.hash || '').substring(0, 7)}</code>
                  <span>{c.message || ''}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SkillChangesTimeline({ changes }: { changes: SkillChangeRow[] }) {
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  if (!changes || changes.length === 0) return null;

  // Group by day
  const groups: Record<string, SkillChangeRow[]> = {};
  for (const c of changes.slice(0, 20)) {
    const day = c.date ? c.date.substring(0, 10) : 'unknown';
    if (!groups[day]) groups[day] = [];
    groups[day].push(c);
  }

  const toggleKey = (key: string) => {
    setExpandedKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  return (
    <>
      <div className="section-heading">Skill Changes (7d)</div>
      <div className="timeline">
        {Object.entries(groups).map(([day, items]) => (
          <div className="tl-day" key={day}>
            <div className="tl-day-label">{dateLabel(day)}</div>
            {items.map((c, i) => {
              const key = `sc-${c.hash || c.date}-${i}`;
              const time = c.date ? c.date.substring(11, 16) : '';

              // Detect skill names from files
              const skillNames = [...new Set((c.files || []).map(f => {
                const m = f.match(/skills\/([^/]+)/);
                return m ? m[1] : null;
              }).filter(Boolean))];

              const hasFiles = c.files && c.files.length > 0;
              const hasDiff = !!c.diff_preview;
              const hasDetail = hasFiles || hasDiff;
              const isExpanded = expandedKeys.has(key);

              return (
                <div className={`tl-event${isExpanded ? ' expanded' : ''}`} key={key}>
                  <div className="tl-dot svc-dot on" style={{ background: 'var(--skill)' }} />
                  <div className="tl-card">
                    <div className="tl-header" onClick={hasDetail ? () => toggleKey(key) : undefined}>
                      <span className="tl-summary" style={{ whiteSpace: 'normal' }}>{c.message || c.summary || ''}</span>
                      <span className="tl-effects">
                        {skillNames.map(s => (
                          <span key={s} className="tl-effect-chip" style={{ background: 'var(--skill-dim)', color: 'var(--skill)' }}>{s}</span>
                        ))}
                        <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                          <span style={{ color: 'var(--green)' }}>+{c.insertions || 0}</span>{' '}
                          <span style={{ color: 'var(--red)' }}>-{c.deletions || 0}</span>
                        </span>
                      </span>
                      <span className="tl-time">{time}</span>
                      {hasDetail && <span className="tl-chevron">&#9654;</span>}
                    </div>
                    {hasDetail && isExpanded && (
                      <div className="tl-detail" style={{ display: 'block' }}>
                        {hasFiles && (
                          <div className="tl-files">
                            {(c.files || []).map((f, fi) => (
                              <span key={fi}>{f}{fi < (c.files || []).length - 1 ? ' \u00b7 ' : ''}</span>
                            ))}
                          </div>
                        )}
                        {hasDiff && (
                          <div className="diff-block">
                            {c.diff_preview!.split('\n').map((l, li) => {
                              if (l.startsWith('---') && l.endsWith('---'))
                                return <span key={li} style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{l}</span>;
                              if (l.startsWith('+'))
                                return <span key={li} className="diff-add">{l}</span>;
                              if (l.startsWith('-'))
                                return <span key={li} className="diff-del">{l}</span>;
                              return <span key={li}>{l}</span>;
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </>
  );
}

export function SkillsTab({ data }: { data?: DashboardData }) {
  const [sortMode, setSortMode] = useState<SortMode>('calls');
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set());

  if (!data) return <div className="empty">Loading...</div>;

  const skills = (data.skill_inventory || []) as SkillRow[];
  const changes = (data.skill_changes || []) as SkillChangeRow[];

  const total = skills.length;
  const totalCalls = skills.reduce((s, sk) => s + (sk.call_count || sk.calls_30d || 0), 0);
  const modified7d = changes.length;
  const created7d = changes.filter(c =>
    (c.message && (c.message.includes('create') || c.message.includes('new skill') || c.message.includes('add skill')))
  ).length;
  const withErrors = skills.filter(s => s.error_count > 0).length;

  // Sort skills
  const sorted = [...skills].sort((a, b) => {
    if (sortMode === 'calls') {
      return (b.call_count || b.calls_30d || 0) - (a.call_count || a.calls_30d || 0);
    } else if (sortMode === 'last') {
      const aVal = a.last_call || a.last_used || '';
      const bVal = b.last_call || b.last_used || '';
      if (!aVal) return 1;
      if (!bVal) return -1;
      return bVal.localeCompare(aVal);
    } else {
      const aVal = a.last_modified || a.modified || '';
      const bVal = b.last_modified || b.modified || '';
      if (!aVal) return 1;
      if (!bVal) return -1;
      return bVal.localeCompare(aVal);
    }
  });

  const toggleSkill = (name: string) => {
    setExpandedSkills(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  return (
    <>
      <KPIRow kpis={[
        { val: total, label: 'Total Skills', color: 'var(--skill)' },
        { val: totalCalls, label: 'Total Calls' },
        { val: modified7d, label: 'Modified / 7d', color: modified7d > 0 ? 'var(--learning)' : 'var(--text-muted)' },
        { val: created7d, label: 'Created / 7d', color: created7d > 0 ? 'var(--green)' : 'var(--text-muted)' },
        { val: withErrors, label: 'With Errors', color: withErrors > 0 ? 'var(--red)' : 'var(--green)' },
      ]} />

      <SkillChangesTimeline changes={changes} />

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        All Skills
        <div className="filter-bar" style={{ margin: 0 }}>
          {([
            { value: 'calls', label: 'By Calls' },
            { value: 'last', label: 'By Last Used' },
            { value: 'modified', label: 'By Modified' },
          ] as const).map(f => (
            <button
              key={f.value}
              className={`filter-btn${sortMode === f.value ? ' active' : ''}`}
              onClick={() => setSortMode(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        {sorted.length === 0 ? (
          <div className="empty">No skills found</div>
        ) : (
          sorted.map(s => (
            <SkillCard
              key={s.name}
              s={s}
              expanded={expandedSkills.has(s.name)}
              onToggle={() => toggleSkill(s.name)}
            />
          ))
        )}
      </div>
    </>
  );
}
