import { useState, useCallback, useMemo } from 'react';
import { useTasks } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { TaskCard } from './TaskCard';
import { TaskGroupCard } from './TaskGroupCard';
import { TCPanel } from './TCPanel';
import { showToast } from '@/components/shared/Toast';
import { extractHashtags } from '@/lib/hashtags';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TasksDataObj = any;

interface TaskMark {
  action: 'done' | 'postpone' | 'cancel' | null;
  title: string;
  note: string;
}

/* ── View Modes ── */

type ViewMode = 'action' | 'project' | 'priority' | 'person' | 'source';
type SubGroupBy = 'none' | 'project' | 'action' | 'priority' | 'person';

const VIEW_MODES: { value: ViewMode; label: string; icon: string }[] = [
  { value: 'action', label: 'Action', icon: '⚡' },
  { value: 'project', label: 'Project', icon: '📁' },
  { value: 'priority', label: 'Priority', icon: '🎯' },
  { value: 'person', label: 'Person', icon: '👤' },
  { value: 'source', label: 'Source', icon: '📋' },
];

const SUB_GROUP_OPTIONS: { value: SubGroupBy; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'project', label: 'Project' },
  { value: 'action', label: 'Action' },
  { value: 'priority', label: 'Priority' },
  { value: 'person', label: 'Person' },
];

// Default sub-group for each main view
const DEFAULT_SUB: Record<ViewMode, SubGroupBy> = {
  action: 'project',
  project: 'action',
  priority: 'project',
  person: 'action',
  source: 'none',
};

/* ── Section Configs ──
 *
 * Generic sections live here. Project-specific sections (e.g. your companies,
 * deals, or side projects) go in USER_PROJECT_SECTIONS below — they get merged
 * into both ACTION_SECTIONS and PROJECT_SECTIONS at module load time. Edit
 * USER_PROJECT_SECTIONS to match your own projects, or leave it empty to fall
 * back to auto-labels (key capitalized, neutral color).
 */

const GENERIC_ACTION_SECTIONS: Record<string, { label: string; order: number; color: string }> = {
  'fix-now':   { label: '🔥 Fix Now',    order: 0, color: '#f87171' },
  'reach-out': { label: '✉️ Reach Out',  order: 1, color: '#fbbf24' },
  'deals':     { label: '🤝 Deals',      order: 2, color: '#4ade80' },
  'decide':    { label: '📋 Decide',     order: 3, color: '#60a5fa' },
  'delegate':  { label: '👥 Delegate',   order: 4, color: '#94a3b8' },
  'waiting':   { label: '⏳ Waiting',    order: 6, color: '#64748b' },
  'personal':  { label: 'Personal',      order: 9, color: '#94a3b8' },
  'graveyard': { label: '🪦 Graveyard',  order: 10, color: '#475569' },
  'archive':   { label: '📦 Archive',    order: 11, color: '#475569' },
};

// Customize for your projects. Keys must match `action_type` / `domain` values
// emitted by the backend. Order numbers slot between the generics above.
const USER_PROJECT_SECTIONS: Record<string, { label: string; order: number; color: string }> = {
  // Example:
  // 'acme': { label: '🚀 Acme', order: 5, color: '#c084fc' },
};

const ACTION_SECTIONS: Record<string, { label: string; order: number; color: string }> = {
  ...GENERIC_ACTION_SECTIONS,
  ...USER_PROJECT_SECTIONS,
};

const PROJECT_SECTIONS: Record<string, { label: string; order: number; color: string }> = {
  ...USER_PROJECT_SECTIONS,
  'personal': { label: 'Personal', order: 99, color: '#94a3b8' },
};

const PRIORITY_SECTIONS: Record<string, { label: string; order: number; min: number; max: number; color: string }> = {
  'critical': { label: '🔴 Critical', order: 0, min: 70, max: 101, color: '#f87171' },
  'high':     { label: '🟡 High',     order: 1, min: 40, max: 70, color: '#fbbf24' },
  'medium':   { label: '🔵 Medium',   order: 2, min: 15, max: 40, color: '#60a5fa' },
  'low':      { label: '⚪ Low',      order: 3, min: 0,  max: 15, color: '#64748b' },
};

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  overdue:    { label: 'Overdue',            color: '#f87171' },
  today:      { label: 'Today',              color: '#fbbf24' },
  deals:      { label: 'Deals & Follow-ups', color: '#4ade80' },
  replies:    { label: 'Replies',            color: '#fbbf24' },
  personal:   { label: 'Personal',           color: '#94a3b8' },
};

/* ── Client-side grouping ── */

interface SubGroup {
  key: string;
  label: string;
  color?: string;
  tasks: TasksDataObj[];
}

interface GroupedSection {
  key: string;
  label: string;
  color?: string;
  tasks: TasksDataObj[];
  subGroups?: SubGroup[];
}

/** Compute sub-groups for each section based on chosen sub-group dimension */
function addSubGroups(sections: GroupedSection[], subGroupBy: SubGroupBy): void {
  if (subGroupBy === 'none') return;

  let getKey: (t: TasksDataObj) => string;
  let config: Record<string, { label: string; order: number; color?: string }>;

  switch (subGroupBy) {
    case 'project':
      getKey = t => t.domain || 'personal';
      config = PROJECT_SECTIONS;
      break;
    case 'action':
      getKey = t => t.action_type || 'personal';
      config = ACTION_SECTIONS;
      break;
    case 'priority':
      getKey = t => {
        const s = t.priority_score || 0;
        if (s >= 70) return 'critical';
        if (s >= 40) return 'high';
        if (s >= 15) return 'medium';
        return 'low';
      };
      config = PRIORITY_SECTIONS;
      break;
    case 'person':
      getKey = t => t.person || '_none';
      config = {};
      break;
    default:
      return;
  }

  for (const section of sections) {
    const byKey: Record<string, TasksDataObj[]> = {};
    for (const t of section.tasks) {
      const k = getKey(t);
      (byKey[k] = byKey[k] || []).push(t);
    }

    const subs = Object.entries(byKey)
      .filter(([, tasks]) => tasks.length > 0)
      .sort(([a], [b]) => {
        const ao = (config[a] as any)?.order ?? 999;
        const bo = (config[b] as any)?.order ?? 999;
        return ao - bo || a.localeCompare(b);
      })
      .map(([k, tasks]) => ({
        key: k,
        label: (config[k] as any)?.label || (k === '_none' ? 'Unassigned' : k.charAt(0).toUpperCase() + k.slice(1)),
        color: (config[k] as any)?.color,
        tasks,
      }));

    if (subs.length > 1) {
      section.subGroups = subs;
    }
  }
}

function groupTasks(
  tasks: TasksDataObj[],
  viewMode: ViewMode,
  subGroupBy: SubGroupBy,
  sourceSections: Record<string, { label?: string; tasks?: TasksDataObj[] }>,
  sourceOrder: string[],
): { sections: GroupedSection[]; filterOptions: { value: string; label: string }[] } {

  if (viewMode === 'source') {
    const result: GroupedSection[] = [];
    for (const key of sourceOrder) {
      if (key === 'klava') continue;
      const sec = sourceSections[key];
      if (sec?.tasks?.length) {
        const cfg = SOURCE_LABELS[key];
        result.push({ key, label: cfg?.label || key.charAt(0).toUpperCase() + key.slice(1), color: cfg?.color, tasks: sec.tasks });
      }
    }
    return {
      sections: result,
      filterOptions: result.map(s => ({ value: s.key, label: s.label.replace(/^[^\w]+ /, '') })),
    };
  }

  const grouped: Record<string, TasksDataObj[]> = {};

  if (viewMode === 'action') {
    for (const t of tasks) {
      const key = t.action_type || 'personal';
      (grouped[key] = grouped[key] || []).push(t);
    }
    const sections: GroupedSection[] = Object.entries(ACTION_SECTIONS)
      .filter(([k]) => grouped[k]?.length)
      .sort(([, a], [, b]) => a.order - b.order)
      .map(([k, v]) => ({ key: k, label: v.label, color: v.color, tasks: grouped[k] }));
    addSubGroups(sections, subGroupBy);
    return {
      sections,
      filterOptions: sections.map(s => ({ value: s.key, label: s.label.replace(/^[^\w]+ /, '') })),
    };
  }

  if (viewMode === 'project') {
    for (const t of tasks) {
      const key = t.domain || 'personal';
      (grouped[key] = grouped[key] || []).push(t);
    }
    for (const arr of Object.values(grouped)) {
      arr.sort((a: TasksDataObj, b: TasksDataObj) => (b.priority_score || 0) - (a.priority_score || 0));
    }
    const sections: GroupedSection[] = Object.entries(PROJECT_SECTIONS)
      .filter(([k]) => grouped[k]?.length)
      .sort(([, a], [, b]) => a.order - b.order)
      .map(([k, v]) => ({ key: k, label: v.label, color: v.color, tasks: grouped[k] }));
    addSubGroups(sections, subGroupBy);
    return {
      sections,
      filterOptions: sections.map(s => ({ value: s.key, label: s.label })),
    };
  }

  if (viewMode === 'priority') {
    const tiers = Object.entries(PRIORITY_SECTIONS).sort(([, a], [, b]) => a.order - b.order);
    const sections: GroupedSection[] = tiers
      .map(([k, v]) => ({
        key: k,
        label: v.label,
        color: v.color,
        tasks: tasks
          .filter(t => (t.priority_score || 0) >= v.min && (t.priority_score || 0) < v.max)
          .sort((a: TasksDataObj, b: TasksDataObj) => (b.priority_score || 0) - (a.priority_score || 0)),
      }))
      .filter(s => s.tasks.length > 0);
    addSubGroups(sections, subGroupBy);
    return {
      sections,
      filterOptions: sections.map(s => ({ value: s.key, label: s.label.replace(/^[^\w]+ /, '') })),
    };
  }

  if (viewMode === 'person') {
    for (const t of tasks) {
      const key = t.person || '_none';
      (grouped[key] = grouped[key] || []).push(t);
    }
    const sections: GroupedSection[] = Object.entries(grouped)
      .sort(([a, at], [b, bt]) => {
        if (a === '_none') return 1;
        if (b === '_none') return -1;
        return bt.length - at.length;
      })
      .map(([k, sectionTasks]) => ({
        key: k,
        label: k === '_none' ? 'Unassigned' : k,
        tasks: sectionTasks.sort((a: TasksDataObj, b: TasksDataObj) => (b.priority_score || 0) - (a.priority_score || 0)),
      }));
    addSubGroups(sections, subGroupBy);
    return {
      sections,
      filterOptions: sections.map(s => ({ value: s.key, label: s.label })),
    };
  }

  return { sections: [], filterOptions: [] };
}

/* ── Build mixed list of individual tasks and virtual groups ── */

type SectionItem =
  | { type: 'task'; task: TasksDataObj }
  | { type: 'group'; group: { key: string; title: string; summary: string; count: number; task_ids: string[] }; tasks: TasksDataObj[] };

function buildSectionItems(
  sectionTasks: TasksDataObj[],
  groups: Record<string, { key: string; title: string; summary: string; count: number; task_ids: string[] }>,
  allTasks: TasksDataObj[],
): SectionItem[] {
  const items: SectionItem[] = [];
  const usedIds = new Set<string>();

  const sectionGroupKeys = new Set<string>();
  for (const t of sectionTasks) {
    if (t.group_key && groups[t.group_key]) {
      sectionGroupKeys.add(t.group_key);
    }
  }

  const allTasksById = new Map(allTasks.map(t => [t.id, t]));
  for (const gk of sectionGroupKeys) {
    const groupDef = groups[gk];
    if (!groupDef) continue;
    const groupTasks = groupDef.task_ids
      .map(id => allTasksById.get(id))
      .filter((t): t is TasksDataObj => !!t);
    if (groupTasks.length < 2) continue;
    items.push({ type: 'group', group: groupDef, tasks: groupTasks });
    for (const t of groupTasks) usedIds.add(t.id);
  }

  for (const t of sectionTasks) {
    if (!usedIds.has(t.id)) {
      items.push({ type: 'task', task: t });
    }
  }

  return items;
}

/* ── Render helpers ── */

function renderItems(
  items: SectionItem[],
  marks: Record<string, TaskMark>,
  markTask: (id: string, action: 'done' | 'postpone' | 'cancel', title: string) => void,
  updateNote: (id: string, note: string, title: string) => void,
) {
  return items.map((item) =>
    item.type === 'group' ? (
      <TaskGroupCard
        key={item.group.key}
        group={item.group}
        tasks={item.tasks}
        marks={marks}
        onMark={markTask}
        onNoteChange={updateNote}
      />
    ) : (
      <TaskCard
        key={item.task.id}
        task={item.task}
        mark={marks[item.task.id]}
        onMark={markTask}
        onNoteChange={updateNote}
      />
    )
  );
}

/* ── Main Component ── */

export function TasksTab() {
  const { data, refetch } = useTasks(true);
  // Multi-select: empty set = show all
  const [activeFilters, setActiveFilters] = useState<Set<string>>(new Set());
  const [activeSubFilters, setActiveSubFilters] = useState<Set<string>>(new Set());
  const [activeHashtags, setActiveHashtags] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem('tasks-hashtag-filters');
      return saved ? new Set(JSON.parse(saved)) : new Set();
    } catch { return new Set(); }
  });
  const [hideStaleOverdue, setHideStaleOverdue] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    try { return (localStorage.getItem('tasks-view-mode') as ViewMode) || 'action'; }
    catch { return 'action'; }
  });
  const [subGroupBy, setSubGroupBy] = useState<SubGroupBy>(() => {
    try {
      const saved = localStorage.getItem('tasks-sub-group');
      return (saved as SubGroupBy) || DEFAULT_SUB['action'];
    } catch { return 'project'; }
  });
  const [showGH, setShowGH] = useState<boolean>(() => {
    try { return localStorage.getItem('tasks-show-gh') !== 'false'; }
    catch { return true; }
  });
  const [marks, setMarks] = useState<Record<string, TaskMark>>({});
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem('tasks-collapsed') || '{}');
    } catch { return {}; }
  });

  const toggleFilter = useCallback((key: string) => {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const toggleSubFilter = useCallback((key: string) => {
    setActiveSubFilters(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    setActiveFilters(new Set());
    setActiveSubFilters(new Set());
    setActiveHashtags(new Set());
    try { localStorage.removeItem('tasks-hashtag-filters'); } catch { /* ignore */ }
  }, []);

  const toggleHashtag = useCallback((tag: string) => {
    setActiveHashtags(prev => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      try { localStorage.setItem('tasks-hashtag-filters', JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  }, []);

  const toggleSection = useCallback((secKey: string) => {
    setCollapsedSections(prev => {
      const next = { ...prev };
      if (next[secKey]) delete next[secKey];
      else next[secKey] = true;
      localStorage.setItem('tasks-collapsed', JSON.stringify(next));
      return next;
    });
  }, []);

  const markTask = useCallback((taskId: string, action: 'done' | 'postpone' | 'cancel', title: string) => {
    setMarks(prev => {
      const existing = prev[taskId];
      if (existing && existing.action === action) {
        const next = { ...prev };
        delete next[taskId];
        return next;
      }
      return { ...prev, [taskId]: { action, title, note: existing?.note || '' } };
    });
  }, []);

  const updateNote = useCallback((taskId: string, note: string, title: string) => {
    setMarks(prev => {
      if (prev[taskId]) {
        const next = { ...prev, [taskId]: { ...prev[taskId], note } };
        if (!note && !next[taskId].action) delete next[taskId];
        return next;
      } else if (note) {
        return { ...prev, [taskId]: { action: null, title: title || '', note } };
      }
      return prev;
    });
  }, []);

  const removeMark = useCallback((id: string) => {
    setMarks(prev => { const next = { ...prev }; delete next[id]; return next; });
  }, []);

  const clearAllMarks = useCallback(() => setMarks({}), []);

  const setAction = useCallback((id: string, action: 'done' | 'postpone' | 'cancel') => {
    setMarks(prev => {
      const m = prev[id];
      if (!m) return prev;
      if (m.action === action) {
        if (!m.note) { const next = { ...prev }; delete next[id]; return next; }
        return { ...prev, [id]: { ...m, action: null } };
      }
      return { ...prev, [id]: { ...m, action } };
    });
  }, []);

  const setNote = useCallback((id: string, note: string) => {
    setMarks(prev => {
      if (!prev[id]) return prev;
      return { ...prev, [id]: { ...prev[id], note } };
    });
  }, []);

  const handleRefresh = useCallback(() => {
    setMarks({});
    refetch();
    showToast('Refreshing...');
  }, [refetch]);

  const kpis = useMemo(() => {
    if (!data) return [];
    const k = (data as TasksDataObj).kpis || {};
    return [
      { val: k.total || 0, label: 'Personal', color: (k.overdue || 0) > 0 ? 'var(--red)' : 'var(--text)' },
      { val: k.overdue || 0, label: 'Overdue', color: 'var(--red)' },
      { val: k.today || 0, label: 'Today', color: 'var(--yellow)' },
      { val: k.deals || 0, label: 'Deals', color: 'var(--green)' },
    ];
  }, [data]);

  /* ── Derived data ── */

  const rawTasks: TasksDataObj[] = (data as TasksDataObj)?.tasks || [];
  const ghFilteredTasks = useMemo(
    () => showGH ? rawTasks : rawTasks.filter((t: TasksDataObj) => t.source !== 'github'),
    [rawTasks, showGH],
  );

  // Hashtag universe — computed from GH-filtered pool (not hashtag-filtered)
  // so chips keep their counts visible as you narrow down.
  const { hashtagOptions, hashtagCounts } = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of ghFilteredTasks) {
      const tags = new Set<string>();
      extractHashtags(t.title).forEach(x => tags.add(x));
      extractHashtags(t.raw_title).forEach(x => tags.add(x));
      extractHashtags(t.notes).forEach(x => tags.add(x));
      tags.forEach(tag => { counts[tag] = (counts[tag] || 0) + 1; });
    }
    const opts = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    return { hashtagOptions: opts, hashtagCounts: counts };
  }, [ghFilteredTasks]);

  const allTasks = useMemo(() => {
    if (activeHashtags.size === 0) return ghFilteredTasks;
    return ghFilteredTasks.filter((t: TasksDataObj) => {
      const tags = new Set<string>();
      extractHashtags(t.title).forEach(x => tags.add(x));
      extractHashtags(t.raw_title).forEach(x => tags.add(x));
      extractHashtags(t.notes).forEach(x => tags.add(x));
      for (const h of activeHashtags) if (tags.has(h)) return true;
      return false;
    });
  }, [ghFilteredTasks, activeHashtags]);
  const sourceSections = useMemo(() => {
    return (data as TasksDataObj)?.sections || {};
  }, [data]);
  const sourceOrder: string[] = (data as TasksDataObj)?.section_order || Object.keys(sourceSections);
  const groups: Record<string, { key: string; title: string; summary: string; count: number; task_ids: string[] }> =
    (data as TasksDataObj)?.groups || {};

  const { sections: computedSections, filterOptions } = useMemo(
    () => groupTasks(allTasks, viewMode, subGroupBy, sourceSections, sourceOrder),
    [allTasks, viewMode, subGroupBy, sourceSections, sourceOrder],
  );

  // Sub-group config lookup for filtering
  const SUB_CFG_LOOKUP: Record<SubGroupBy, { field: string; config: Record<string, { label: string; order: number; color?: string }> } | null> = {
    none:     null,
    project:  { field: 'domain',         config: PROJECT_SECTIONS },
    action:   { field: 'action_type',    config: ACTION_SECTIONS },
    priority: { field: 'priority_score', config: PRIORITY_SECTIONS },
    person:   { field: 'person',         config: {} },
  };

  // Available sub-group options (exclude current main view dimension)
  const availableSubOptions = useMemo(() => {
    if (viewMode === 'source') return [];
    return SUB_GROUP_OPTIONS.filter(o => {
      if (o.value === 'none') return true;
      if (viewMode === 'action' && o.value === 'action') return false;
      if (viewMode === 'project' && o.value === 'project') return false;
      if (viewMode === 'priority' && o.value === 'priority') return false;
      if (viewMode === 'person' && o.value === 'person') return false;
      return true;
    });
  }, [viewMode]);

  // Sub-category filter pill options
  const subFilterOptions = useMemo(() => {
    if (subGroupBy === 'none') return [];
    // Collect sub-keys from computed sections
    const seen = new Set<string>();
    for (const sec of computedSections) {
      if (sec.subGroups) {
        for (const sg of sec.subGroups) seen.add(sg.key);
      }
    }
    if (seen.size < 2) return [];
    const cfg = SUB_CFG_LOOKUP[subGroupBy];
    const config = cfg?.config || {};
    return Array.from(seen)
      .map(k => ({
        value: k,
        label: (config[k] as any)?.label?.replace(/^[^\w]+ /, '') || (k === '_none' ? 'Unassigned' : k.charAt(0).toUpperCase() + k.slice(1)),
        order: (config[k] as any)?.order ?? 999,
      }))
      .sort((a, b) => a.order - b.order);
  }, [computedSections, subGroupBy]);

  let hiddenStale = 0;
  const subCfg = SUB_CFG_LOOKUP[subGroupBy];
  const visibleSections = computedSections
    .filter(s => activeFilters.size === 0 || activeFilters.has(s.key))
    .map(s => {
      // Apply both stale filter and sub-category filter
      const filterTask = (t: TasksDataObj) => {
        if (viewMode === 'source' && hideStaleOverdue && (t.overdue_days || 0) >= 30) {
          hiddenStale++;
          return false;
        }
        if (activeSubFilters.size > 0 && subGroupBy !== 'none') {
          let k: string;
          if (subGroupBy === 'priority') {
            const s = t.priority_score || 0;
            k = s >= 70 ? 'critical' : s >= 40 ? 'high' : s >= 15 ? 'medium' : 'low';
          } else if (subGroupBy === 'person') {
            k = t.person || '_none';
          } else if (subGroupBy === 'project') {
            k = t.domain || 'personal';
          } else {
            k = t.action_type || 'personal';
          }
          if (!activeSubFilters.has(k)) return false;
        }
        return true;
      };
      const tasks = s.tasks.filter(filterTask);
      const subGroups = s.subGroups
        ?.filter(sg => activeSubFilters.size === 0 || activeSubFilters.has(sg.key))
        .map(sg => ({
          ...sg,
          tasks: sg.tasks.filter(filterTask),
        }))
        .filter(sg => sg.tasks.length > 0);
      return { ...s, tasks, subGroups };
    })
    .filter(s => s.tasks.length > 0);

  const marksCount = Object.keys(marks).length;

  if (!data) return <div className="empty">Loading tasks...</div>;

  return (
    <>
      <KPIRow kpis={kpis} />
      <div className="tasks-toolbar">
        <div className="tasks-view-toggle">
          {VIEW_MODES.map(vm => (
            <button
              key={vm.value}
              className={`tasks-view-btn${viewMode === vm.value ? ' active' : ''}`}
              onClick={() => {
                setViewMode(vm.value);
                localStorage.setItem('tasks-view-mode', vm.value);
                const newSub = DEFAULT_SUB[vm.value];
                setSubGroupBy(newSub);
                localStorage.setItem('tasks-sub-group', newSub);
                clearFilters();
              }}
            >
              <span className="tasks-view-icon">{vm.icon}</span>
              {vm.label}
            </button>
          ))}
        </div>

        {/* Sub-group selector */}
        {availableSubOptions.length > 0 && (
          <select
            className="tasks-subgroup-select"
            value={subGroupBy}
            onChange={e => {
              const val = e.target.value as SubGroupBy;
              setSubGroupBy(val);
              localStorage.setItem('tasks-sub-group', val);
              setActiveSubFilters(new Set());
            }}
          >
            {availableSubOptions.map(o => (
              <option key={o.value} value={o.value}>
                {o.value === 'none' ? '— no sub-group —' : `↳ ${o.label}`}
              </option>
            ))}
          </select>
        )}

        {/* Multi-select filter pills - main categories */}
        <div className="tasks-filter-row">
          <button
            className={`tasks-filter-pill all-pill${activeFilters.size === 0 && activeSubFilters.size === 0 && activeHashtags.size === 0 ? ' active' : ''}`}
            onClick={clearFilters}
          >
            All
          </button>
          {filterOptions.map(f => (
            <button
              key={f.value}
              className={`tasks-filter-pill${activeFilters.has(f.value) ? ' active' : ''}`}
              onClick={() => toggleFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
          {/* Sub-category pills (cross-dimension) */}
          {subFilterOptions.length > 1 && (
            <>
              <span className="tasks-filter-sep">|</span>
              {subFilterOptions.map(f => (
                <button
                  key={`sub-${f.value}`}
                  className={`tasks-filter-pill tasks-filter-sub${activeSubFilters.has(f.value) ? ' active' : ''}`}
                  onClick={() => toggleSubFilter(f.value)}
                >
                  {f.label}
                </button>
              ))}
            </>
          )}
        </div>

        {/* Hashtag pills - user #tags extracted from task titles/notes */}
        {hashtagOptions.length > 0 && (
          <div className="tasks-filter-row tasks-hashtag-row">
            {hashtagOptions.map(tag => {
              const active = activeHashtags.has(tag);
              return (
                <button
                  key={`tag-${tag}`}
                  className={`tasks-filter-pill tasks-filter-hashtag${active ? ' active' : ''}`}
                  onClick={() => toggleHashtag(tag)}
                  title="Hashtag extracted from task title/notes"
                >
                  #{tag} <span className="tasks-hashtag-count">{hashtagCounts[tag]}</span>
                </button>
              );
            })}
          </div>
        )}

        <div className="tasks-toolbar-btns">
          <label className="tasks-gh-toggle" title="Include GitHub issues in task list">
            <input
              type="checkbox"
              checked={showGH}
              onChange={e => {
                setShowGH(e.target.checked);
                localStorage.setItem('tasks-show-gh', String(e.target.checked));
              }}
            />
            <span>GH</span>
          </label>
          {viewMode === 'source' && (
            <button
              className="tasks-action-btn"
              onClick={() => setHideStaleOverdue(prev => !prev)}
              style={{ fontSize: 11, opacity: hideStaleOverdue ? 0.6 : 1 }}
            >
              {hideStaleOverdue ? `Show 30d+ (${hiddenStale})` : 'Hide 30d+'}
            </button>
          )}
          {marksCount > 0 && (
            <button
              className="tasks-action-btn copy-btn"
              onClick={() => {
                const today = new Date().toISOString().slice(0, 10);
                const actionMap: Record<string, string> = { done: 'DONE', postpone: 'POSTPONE', cancel: 'CANCEL' };
                let text = `/tasks\nTASK UPDATES (${today}):\n\n`;
                for (const [taskId, m] of Object.entries(marks)) {
                  if (m.action) text += `- ${m.title} [${actionMap[m.action]}] (id:${taskId})\n`;
                  else text += `- ${m.title} (id:${taskId})\n`;
                  if (m.note) text += `  Note: ${m.note}\n`;
                }
                window.dispatchEvent(new CustomEvent('chat:open'));
                window.dispatchEvent(new CustomEvent('chat:new-session', { detail: { text } }));
                showToast(`Sending ${marksCount} changes to new session...`);
              }}
            >
              Send to Session <span className="change-count">{marksCount}</span>
            </button>
          )}
          <button className="tasks-action-btn refresh-btn-tasks" onClick={handleRefresh}>
            Refresh
          </button>
        </div>
      </div>

      <div className="tasks-sections">
        {visibleSections.length === 0 ? (
          <div className="empty">No tasks in this category</div>
        ) : (
          visibleSections.map(({ key: secKey, label, color, tasks, subGroups }) => {
            const isCollapsed = collapsedSections[secKey];
            return (
              <div
                key={secKey}
                className={`task-section${isCollapsed ? ' collapsed' : ''}`}
                data-section={secKey}
                style={{ '--section-color': color || '#64748b' } as React.CSSProperties}
              >
                <div className="task-section-heading" onClick={() => toggleSection(secKey)}>
                  <span className="task-section-chevron">{'\u25BC'}</span>
                  <span className="task-section-label">{label}</span>
                  <span className="task-section-count">{tasks.length}</span>
                </div>

                <div className="task-section-cards">
                  {subGroups && subGroups.length > 1 ? (
                    subGroups.map(sub => {
                      const subKey = `${secKey}/${sub.key}`;
                      const isSubCollapsed = collapsedSections[subKey];
                      const subItems = buildSectionItems(sub.tasks, groups, allTasks);
                      return (
                        <div
                          key={sub.key}
                          className={`task-subsection${isSubCollapsed ? ' collapsed' : ''}`}
                          data-subsection={sub.key}
                          style={{ '--sub-color': sub.color || '#64748b' } as React.CSSProperties}
                        >
                          <div
                            className="task-subsection-heading"
                            onClick={(e) => { e.stopPropagation(); toggleSection(subKey); }}
                          >
                            <span className="task-subsection-chevron">{'\u25B8'}</span>
                            <span className="task-subsection-label">{sub.label}</span>
                            <span className="task-subsection-count">{sub.tasks.length}</span>
                          </div>
                          <div className="task-subsection-cards">
                            {renderItems(subItems, marks, markTask, updateNote)}
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    renderItems(buildSectionItems(tasks, groups, allTasks), marks, markTask, updateNote)
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <TCPanel
        marks={marks}
        onRemove={removeMark}
        onClearAll={clearAllMarks}
        onSetAction={setAction}
        onSetNote={setNote}
      />
    </>
  );
}
