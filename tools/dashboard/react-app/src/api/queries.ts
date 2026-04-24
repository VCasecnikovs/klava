import { useQuery } from '@tanstack/react-query';
import { api, type KlavaTask } from './client';

// ─── Deck: unified attention surface ────────────────────────────
// Merges Klava list (proposals + agent queue, full v2 schema) with
// the main GT list from /api/tasks (169+ user tasks). Normalizes the
// flat /api/tasks shape into KlavaTask so Deck renders every card
// through the same UniversalCard.

interface FlatGTask {
  id: string;
  title: string;
  raw_title?: string;
  notes?: string;
  due?: string | null;
  overdue?: boolean;
  overdue_days?: number;
  is_today?: boolean;
  priority_score?: number;
  section?: string;
  list_name?: string;
  action_type?: string;
  domain?: string;
  source?: string;
  auto_tags?: string[];
  tags?: Array<{ color: string; name: string }>;
}

function inferShapeFromTitle(title: string): KlavaTask['shape'] {
  const m = title.match(/^\[([A-Z]+)\]/);
  if (!m) return 'act';
  const tag = m[1];
  if (tag === 'REPLY') return 'reply';
  if (tag === 'APPROVE' || tag === 'PROPOSAL') return 'approve';
  if (tag === 'REVIEW') return 'review';
  if (tag === 'DECIDE') return 'decide';
  if (tag === 'READ') return 'read';
  return 'act';
}

function flatToKlavaTask(t: FlatGTask): KlavaTask {
  const title = t.raw_title || t.title;
  const priority: 'high' | 'medium' | 'low' =
    (t.priority_score ?? 0) >= 30 ? 'high'
      : (t.priority_score ?? 0) >= 5 ? 'medium'
      : 'low';
  return {
    id: t.id,
    title,
    status: 'pending',
    priority,
    source: t.source || 'gtasks',
    body: t.notes || '',
    result: '',
    created: null,
    started_at: null,
    completed_at: null,
    session_id: null,
    tab_id: null,
    has_question: false,
    type: 'task',
    shape: inferShapeFromTitle(title),
    dispatch: null,
    criticality: t.priority_score ?? null,
    mode_tags: t.auto_tags && t.auto_tags.length ? t.auto_tags : null,
    proposal_status: null,
    proposal_plan: null,
  };
}

export interface DeckCard extends KlavaTask {
  _overdue?: boolean;
  _overdue_days?: number;
  _is_today?: boolean;
  _priority_score?: number;
  _section?: string;
  _list_name?: string;
  _due?: string | null;
}

function sortForDeck(cards: DeckCard[]): DeckCard[] {
  const rank = (c: DeckCard): number => {
    if (c.type === 'proposal' && c.proposal_status === 'pending') return 0;
    if (c._overdue) return 1;
    if (c._is_today) return 2;
    if (c._section === 'deals' || c._section === 'replies') return 3;
    return 4;
  };
  return [...cards].sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    if (ra !== rb) return ra - rb;
    // within rank: higher overdue_days first, then higher priority_score
    const od = (b._overdue_days ?? 0) - (a._overdue_days ?? 0);
    if (od !== 0) return od;
    return (b._priority_score ?? 0) - (a._priority_score ?? 0);
  });
}

export function useDeckCards(enabled = false) {
  return useQuery({
    queryKey: ['deck-cards'],
    enabled,
    queryFn: async () => {
      const [klavaResp, flatResp] = await Promise.all([
        api.klavaTasks(),
        fetch('/api/tasks').then(r => r.json()) as Promise<{ tasks: FlatGTask[] }>,
      ]);
      const klava = klavaResp.tasks || [];
      const klavaIds = new Set(klava.map(t => t.id));
      const klavaCards: DeckCard[] = klava.map(t => ({ ...t }));
      const otherCards: DeckCard[] = (flatResp.tasks || [])
        .filter(t => !klavaIds.has(t.id) && t.list_name !== 'klava')
        .map(t => {
          const k = flatToKlavaTask(t);
          return {
            ...k,
            _overdue: t.overdue,
            _overdue_days: t.overdue_days,
            _is_today: t.is_today,
            _priority_score: t.priority_score,
            _section: t.section,
            _list_name: t.list_name,
            _due: t.due ?? null,
          };
        });
      return sortForDeck([...klavaCards, ...otherCards]);
    },
    // Google Tasks has a per-project daily query quota; leaving the Deck open
    // on the old 15 s/3 s poll was burning ~12 k queries/day by itself. The
    // Deck is a human surface, not a live feed — focus refetch + a 5 min
    // safety net + the manual refresh button in the filterbar cover every
    // realistic staleness window.
    refetchInterval: 5 * 60 * 1000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });
}

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
    refetchInterval: 30000,
    staleTime: 25000,
  });
}

export function useFiles(date?: string, enabled = false) {
  return useQuery({
    queryKey: ['files', date ?? 'default'],
    queryFn: () => api.files(date),
    enabled,
    staleTime: 60000,
  });
}

export function useFileMd(path: string | null, enabled = false) {
  return useQuery({
    queryKey: ['fileMd', path ?? ''],
    queryFn: () => api.fileMd(path as string),
    enabled: enabled && !!path,
    staleTime: 60000,
  });
}

export function usePipelines(enabled = false) {
  return useQuery({
    queryKey: ['pipelines'],
    queryFn: api.pipelines,
    enabled,
    staleTime: 30000,
  });
}

export function useTasks(enabled = false) {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: api.tasks,
    enabled,
    staleTime: Infinity, // manual refresh only - auto-refresh resets user marks
  });
}

export function useDeals(enabled = false) {
  return useQuery({
    queryKey: ['deals'],
    queryFn: api.deals,
    enabled,
    staleTime: 120000,
  });
}

export function usePeople(enabled = false) {
  return useQuery({
    queryKey: ['people'],
    queryFn: api.people,
    enabled,
    staleTime: 120000,
  });
}

export function useHeartbeat(enabled = false) {
  return useQuery({
    queryKey: ['heartbeat'],
    queryFn: api.heartbeat,
    enabled,
    staleTime: 60000,
  });
}

export function useFeed(enabled = false) {
  return useQuery({
    queryKey: ['feed'],
    queryFn: api.feed,
    enabled,
    staleTime: 30000,
  });
}

export function useViews(enabled = false) {
  return useQuery({
    queryKey: ['views'],
    queryFn: api.views,
    enabled,
    staleTime: 60000,
  });
}

export function useSessions(enabled = false) {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.sessions().then(r => r.sessions),
    enabled,
    staleTime: 10000,
  });
}

export function useSelfEvolve(enabled = false) {
  return useQuery({
    queryKey: ['self-evolve'],
    queryFn: api.selfEvolve,
    enabled,
    staleTime: 60000,
  });
}

export function usePlans(enabled = false) {
  return useQuery({
    queryKey: ['plans'],
    queryFn: api.plans,
    enabled,
    staleTime: 30000,
  });
}

export function useAgents(enabled = false) {
  return useQuery({
    queryKey: ['agents'],
    queryFn: () => api.agents(),
    enabled,
    refetchInterval: 3000,
    staleTime: 2000,
  });
}

export function useKlavaTasks(enabled = false) {
  return useQuery({
    queryKey: ['klava-tasks'],
    queryFn: () => api.klavaTasks().then(r => r.tasks),
    enabled,
    // Backend now reads through tasks/snapshot.py: one bootstrap fetch +
    // incremental --updated-min deltas. Polling cost on the GT API has
    // collapsed (delta is ~free when nothing changed), so the only real
    // constraint is UI freshness. Hot 15s while a task is running or has
    // a question, idle 60s otherwise. Mutations call refetch() explicitly
    // so we never have to wait for the next tick after an action.
    refetchInterval: (query) => {
      const tasks = query.state.data;
      const hasActive = tasks?.some((t: KlavaTask) => t.status === 'running' || t.has_question);
      return hasActive ? 15000 : 60000;
    },
    refetchIntervalInBackground: false,
    staleTime: 10000,
  });
}

export function useSources(enabled = false) {
  return useQuery({
    queryKey: ['sources'],
    queryFn: api.sources,
    enabled,
    staleTime: 120000,
  });
}

export function useHabits(enabled = false) {
  return useQuery({
    queryKey: ['habits'],
    queryFn: api.habits,
    enabled,
    staleTime: 30000,
  });
}
