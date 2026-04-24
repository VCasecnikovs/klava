import type {
  DashboardData, FilesData, PipelinesData, TasksData,
  DealsData, PeopleData,
  HeartbeatData, FeedData, ViewsData, Session, SessionDetail,
  Agent, SelfEvolveData, SourcesData,
} from './types';

export interface KlavaTask {
  id: string;
  title: string;
  status: string;
  priority: string;
  source: string;
  body: string;
  result: string;
  created: string | null;
  started_at: string | null;
  completed_at: string | null;
  session_id: string | null;
  tab_id: string | null;
  has_question: boolean;
  questions?: Array<{ question: string; options?: Array<{ value: string; label: string }> }>;
  // v2 unified-schema fields (plan: nifty-dreaming-lighthouse)
  type?: 'task' | 'proposal' | 'signal' | 'brief' | 'result';
  shape?: 'reply' | 'approve' | 'review' | 'decide' | 'act' | 'read' | null;
  dispatch?: 'chat' | 'session' | 'self' | null;
  criticality?: number | null;
  mode_tags?: string[] | null;
  proposal_status?: 'pending' | 'approved' | 'rejected' | null;
  proposal_plan?: string | null;
  result_of?: string | null;
}

export interface StreamingSession {
  id: string;
  tab_id?: string;
  elapsed: number;
  last_event: { type: string; tool?: string } | null;
}

export interface ActiveEntry {
  tab_id: string | null;
  session_id: string | null;
}

export interface ChatStateData {
  active_sessions: ActiveEntry[];
  session_names: Record<string, string>;
  streaming_sessions: StreamingSession[];
  unread_sessions: string[];
  drafts?: Record<string, string>;
}

const BASE = '';

async function apiFetch<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function apiPost(path: string, body: unknown): Promise<unknown> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  // Happy path: return parsed JSON.
  if (resp.ok) return resp.json();
  // Error path: if the body parses as {ok: false, error, ...} (our wizard
  // convention), return it so callers can surface error / needs_install /
  // hint. Otherwise throw an opaque HTTP error.
  let parsed: Record<string, unknown> | null = null;
  try {
    const raw = await resp.json();
    if (raw && typeof raw === 'object' && 'ok' in raw && raw.ok === false) {
      parsed = raw as Record<string, unknown>;
    }
  } catch { /* not JSON */ }
  if (parsed) return parsed;
  throw new Error(`HTTP ${resp.status}`);
}

export interface WizardAuthSnapshot {
  id: string;
  source: string;
  done: boolean;
  exit_code: number | null;
  lines: string[];
  device_code: string | null;
  verification_url: string | null;
  qr_text: string | null;
  prompt: string | null;
  summary: string | null;
  started_at: number;
}

export const api = {
  dashboard: () => apiFetch<DashboardData>('/api/dashboard'),
  files: (date?: string) => apiFetch<FilesData>(`/api/files${date ? `?date=${date}` : ''}`),
  fileMd: (path: string) =>
    apiFetch<{ path: string; content: string; lines: number; size: number; modified?: string; modified_ago?: string }>(
      `/api/files/md?path=${encodeURIComponent(path)}`
    ),
  pipelines: () => apiFetch<PipelinesData>('/api/pipelines'),
  tasks: () => apiFetch<TasksData>('/api/tasks'),
  deals: () => apiFetch<DealsData>('/api/deals'),
  people: () => apiFetch<PeopleData>('/api/people'),
  heartbeat: () => apiFetch<HeartbeatData>('/api/heartbeat'),
  feed: () => apiFetch<FeedData>('/api/feed'),
  views: () => apiFetch<ViewsData>('/api/views'),
  sources: () => apiFetch<SourcesData>('/api/sources'),
  habits: () => apiFetch<{
    habits: Array<{ id: string; title: string; subtitle: string; category: string; frequency: string; icon: string; streak: number; done_today: boolean }>;
    today: string;
    today_done: string[];
    heatmap: Record<string, string[]>;
    total_habits: number;
    done_count: number;
  }>('/api/habits'),
  habitsToggle: (habitId: string) =>
    apiPost('/api/habits/toggle', { habit_id: habitId }) as Promise<{ ok: boolean; habit_id: string; done: boolean; date: string }>,
  plans: () => apiFetch<{ plans: Array<{ name: string; content: string; modified: string; size: number }> }>('/api/plans'),
  sessions: () => apiFetch<{ sessions: Session[] }>('/api/sessions'),
  sessionsSearch: (q: string) => apiFetch<{ sessions: Session[] }>(`/api/sessions/search?q=${encodeURIComponent(q)}`),
  session: (id: string) => apiFetch<SessionDetail>(`/api/sessions/${id}`),
  uploadFile: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch('/api/chat/upload', { method: 'POST', body: form });
    if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);
    return resp.json() as Promise<{ files: { name: string; path: string; url: string; size: number; type: string }[] }>;
  },
  updateTask: async (taskId: string, action: string, note?: string, days?: number) => {
    const resp = await fetch('/api/tasks/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId, action, note, days }),
    });
    if (!resp.ok) throw new Error(`Task update failed: ${resp.status}`);
    return resp.json();
  },
  openView: async (filename: string, browser = false) => {
    const resp = await fetch('/api/views/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, browser }),
    });
    return resp.json();
  },
  chatState: () => apiFetch<ChatStateData>('/api/chat/state'),
  chatStateName: (sessionId: string, name: string) =>
    apiPost('/api/chat/state/name', { session_id: sessionId, name }),
  chatStateRead: (sessionId: string) =>
    apiPost('/api/chat/state/read', { session_id: sessionId }),
  chatStateCancel: (sessionId: string) =>
    apiPost('/api/chat/state/cancel', { session_id: sessionId }),
  chatSendHttp: (payload: { prompt: string; tab_id: string; model: string; resume_session_id?: string; files?: Array<{ name: string; path: string; type: string }> }) =>
    apiPost('/api/chat/send', payload) as Promise<{ ok: boolean; queued?: boolean }>,
  chatFork: (payload: { source_tab_id: string; from_block_id: number; model: string; effort?: string; session_mode?: string }) =>
    apiPost('/api/chat/fork', payload) as Promise<{ ok: boolean; tab_id: string; parent_session_id: string | null }>,
  chatContextUsage: (tabId: string) =>
    apiFetch<{ ok: boolean; tokens: number; limit: number; percent: number | null; model: string; raw?: Record<string, unknown> }>(
      `/api/chat/context-usage?tab_id=${encodeURIComponent(tabId)}`
    ),
  sessionFork: (sessionId: string) =>
    apiPost(`/api/sessions/${sessionId}/fork`, {}) as Promise<{ session_id: string; source_id: string; name: string; messages: number }>,

  // Self-Evolve
  selfEvolve: () => apiFetch<SelfEvolveData>('/api/self-evolve'),
  selfEvolveUpdate: (title: string, updates: Record<string, unknown>) =>
    apiPost('/api/self-evolve/item', { title, updates }) as Promise<{ ok: boolean }>,
  selfEvolveDelete: (title: string) =>
    fetch('/api/self-evolve/item', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
  selfEvolveRun: () =>
    apiPost('/api/self-evolve/run', {}) as Promise<{ status: string; output?: string; error?: string }>,
  dislike: (blockId: number, textPreview: string, comment: string, sessionId?: string) =>
    apiPost('/api/feedback/dislike', { block_id: blockId, text_preview: textPreview, comment, session_id: sessionId }),

  // Klava task queue
  klavaTasks: () => apiFetch<{ tasks: KlavaTask[] }>('/api/klava/tasks'),
  klavaCreate: (title: string, body: string, priority: string, autoLaunch = true) =>
    apiPost('/api/klava/tasks', { title, body, priority, auto_launch: autoLaunch }) as Promise<{ task_id: string; launched: boolean; tab_id?: string }>,
  klavaLaunch: (taskId: string, model = 'sonnet') =>
    apiPost(`/api/klava/tasks/${taskId}/launch`, { model }) as Promise<{ tab_id: string; task_id: string }>,
  klavaAnswer: (taskId: string, answers: Record<string, string>) =>
    apiPost(`/api/klava/tasks/${taskId}/answer`, { answers }) as Promise<{ ok: boolean }>,
  klavaApprove: (taskId: string) =>
    apiPost(`/api/klava/tasks/${taskId}/approve`, {}) as Promise<{ ok: boolean; id: string; title: string; status: string; proposal_status: string }>,
  klavaReject: (taskId: string, reason = '') =>
    apiPost(`/api/klava/tasks/${taskId}/reject`, { reason }) as Promise<{ ok: boolean; id: string; status: string; proposal_status: string }>,
  klavaComplete: (taskId: string) =>
    apiPost(`/api/klava/tasks/${taskId}/complete`, {}) as Promise<{ ok: boolean; id: string }>,
  klavaCancel: (taskId: string) =>
    apiPost(`/api/klava/tasks/${taskId}/cancel`, {}) as Promise<{ ok: boolean; id: string }>,
  klavaPostpone: (taskId: string, days: number) =>
    apiPost(`/api/klava/tasks/${taskId}/postpone`, { days }) as Promise<{ ok: boolean; id: string; days: number }>,
  klavaRejectResult: (taskId: string, reason = '') =>
    apiPost(`/api/klava/tasks/${taskId}/reject-result`, { reason }) as Promise<{ ok: boolean; id: string; title: string; status: string }>,
  klavaContinue: (cardId: string, mode: 'execute' | 'research-more' | 'follow-up', comment = '') =>
    apiPost('/api/klava/continue', { card_id: cardId, mode, comment }) as Promise<{ ok: boolean; parent_id: string; new_task_id: string; mode: string }>,

  // Agent Hub (dispatch agents)
  agents: () => apiFetch<{ agents: Agent[]; max_concurrent?: number }>('/api/agents'),
  agentDetail: (id: string) => apiFetch<Agent & { output: string[] }>(`/api/agents/${id}`),
  agentKill: (id: string) =>
    apiPost(`/api/agents/${id}/kill`, {}) as Promise<{ status: string }>,

  // Settings (config.yaml)
  settings: () => apiFetch<{
    schema: SettingsGroup[];
    config: Record<string, unknown>;
    secret_paths: string[];
    config_path: string;
  }>('/api/settings'),
  settingsUpdate: async (updates: Record<string, unknown>) => {
    const resp = await fetch('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ updates }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json() as Promise<{
      ok: boolean;
      applied: string[];
      skipped_redacted: string[];
      config: Record<string, unknown>;
    }>;
  },
  settingsBrowse: (path?: string) =>
    apiFetch<{
      path: string;
      parent: string | null;
      entries: { name: string; path: string }[];
    }>(`/api/settings/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`),

  // First-run wizard
  setupStatus: () =>
    apiFetch<{
      configured: boolean;
      missing_required: string[];
      missing_optional: string[];
      config_path: string;
      wizard_completed_at: string | null;
    }>('/api/setup/status'),
  wizardTestTelegram: (bot_token: string, chat_id: number) =>
    apiPost('/api/wizard/test-telegram', { bot_token, chat_id }) as Promise<{
      ok: boolean;
      bot_username?: string;
      stage?: string;
      error?: string;
      hint?: string;
    }>,
  wizardTestClaude: (claude_cli?: string) =>
    apiPost('/api/wizard/test-claude', { claude_cli: claude_cli || 'claude' }) as Promise<{
      ok: boolean;
      version?: string;
      cli?: string;
      error?: string;
      hint?: string;
    }>,
  wizardClaudeAuthStatus: (claude_cli?: string) =>
    apiPost('/api/wizard/claude-auth-status', { claude_cli: claude_cli || 'claude' }) as Promise<{
      cli: string;
      installed: boolean;
      logged_in: boolean;
      raw?: Record<string, unknown> | null;
      error?: string | null;
    }>,
  wizardClaudeAuthStart: (claude_cli?: string) =>
    apiPost('/api/wizard/claude-auth-start', { claude_cli: claude_cli || 'claude' }) as Promise<{
      ok: boolean;
      session?: WizardAuthSnapshot;
      error?: string;
      hint?: string;
    }>,
  wizardClaudeAuthSnapshot: (sid: string) =>
    apiFetch<WizardAuthSnapshot>(`/api/wizard/claude-auth-snapshot/${encodeURIComponent(sid)}`),
  wizardClaudeAuthStop: (sid: string) =>
    apiPost(`/api/wizard/claude-auth-stop/${encodeURIComponent(sid)}`, {}) as Promise<{ ok: boolean }>,
  // Generic CLI auth (gh, gog, wacli, etc.) — delegates to vadimgest's AUTH_COMMANDS.
  wizardCliAuthStatus: (method: string, account?: string) =>
    apiPost('/api/wizard/cli-auth-status', { method, account }) as Promise<{
      method: string;
      signed_in: boolean;
      detail?: string;
      account?: string | null;
      accounts?: string[];
      error?: string;
    }>,
  wizardCliAuthStart: (method: string, account?: string) =>
    apiPost('/api/wizard/cli-auth-start', { method, account }) as Promise<{
      ok: boolean;
      session?: WizardAuthSnapshot;
      error?: string;
      needs_install?: string;
      hint?: string;
    }>,
  wizardCliAuthSnapshot: (sid: string) =>
    apiFetch<WizardAuthSnapshot>(`/api/wizard/cli-auth-snapshot/${encodeURIComponent(sid)}`),
  wizardCliAuthStop: (sid: string) =>
    apiPost(`/api/wizard/cli-auth-stop/${encodeURIComponent(sid)}`, {}) as Promise<{ ok: boolean }>,
  // Gog credentials override — paste your own Google OAuth Desktop client JSON.
  wizardGogCredentials: (content: string) =>
    apiPost('/api/wizard/gog-credentials', { content }) as Promise<{
      ok: boolean;
      client_id?: string;
      error?: string;
    }>,
  // .env writer — upsert API keys.
  wizardEnvWrite: (updates: Record<string, string>) =>
    apiPost('/api/wizard/env-write', { updates }) as Promise<{
      ok: boolean;
      written?: string[];
      error?: string;
    }>,
  wizardTestObsidian: (vault_path: string, create = false) =>
    apiPost('/api/wizard/test-obsidian', { vault_path, create }) as Promise<{
      ok: boolean;
      path?: string;
      has_obsidian_marker?: boolean;
      md_count?: number;
      can_create?: boolean;
      error?: string;
    }>,
  wizardListPlists: () =>
    apiFetch<{
      plists: Array<{ label: string; path: string; loaded: boolean; name: string }>;
      launch_agents_dir: string;
      prefix?: string;
    }>('/api/wizard/plists'),
  wizardEnableCrons: (labels: string[]) =>
    apiPost('/api/wizard/enable-crons', { labels }) as Promise<{
      ok: boolean;
      results: Array<{ label: string; ok: boolean; error?: string }>;
    }>,
  wizardComplete: () =>
    apiPost('/api/wizard/complete', {}) as Promise<{
      ok: boolean;
      completed_at?: string;
      error?: string;
    }>,
  wizardReset: () =>
    apiPost('/api/wizard/reset', {}) as Promise<{ ok: boolean; error?: string }>,

  // Daemon control (launchd)
  daemons: () =>
    apiFetch<{
      daemons: Array<{
        label: string;
        name: string;
        path: string;
        loaded: boolean;
        pid: number | null;
        last_exit: number | null;
        running: boolean;
      }>;
      prefix: string;
      launch_agents_dir: string;
    }>('/api/daemons'),
  daemonRestart: (label: string) =>
    apiPost(`/api/daemons/${encodeURIComponent(label)}/restart`, {}) as Promise<{
      ok: boolean;
      label: string;
      detached?: boolean;
      error?: string;
      note?: string;
    }>,
};

export type SettingsFieldType = 'text' | 'number' | 'toggle' | 'select' | 'secret' | 'path';

export interface SettingsField {
  path: string;
  label: string;
  type: SettingsFieldType;
  description?: string;
  options?: { value: string | number; label: string }[];
}

export interface SettingsGroup {
  key: string;
  label: string;
  description?: string;
  collapsed?: boolean;
  fields: SettingsField[];
}
