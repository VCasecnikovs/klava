// === Dashboard API Types ===

export interface Service {
  name: string;
  running: boolean;
  label?: string;
  pid?: number;
}

export interface Stats {
  runs_24h: number;
  failures_24h: number;
  total_cost_usd: number;
  sessions_active: number;
}

export interface FailingJob {
  job_id: string;
  consecutive: number;
  last_error?: string;
  error?: string;
  last_failure?: string;
  ago?: string;
}

export interface DataSource {
  name: string;
  healthy: boolean;
  records: number;
  last_data_ago?: string;
  type?: string;
  deps_ok?: boolean;
  missing_deps?: string[];
}

export interface ActivityEntry {
  job_id: string;
  status: string;
  timestamp: string;
  ago?: string;
  duration_seconds?: number;
  cost_usd?: number;
  output?: string;
  error?: string;
  files?: FileChange[];
  git_commits?: GitCommit[];
}

export interface FileChange {
  path: string;
  type: string;
}

export interface GitCommit {
  hash: string;
  message: string;
  date: string;
}

export interface Skill {
  name: string;
  description?: string;
  calls_30d: number;
  last_used?: string;
  error_count: number;
  modified?: string;
  user_invocable?: boolean;
  path?: string;
}

export interface SkillChange {
  date: string;
  type: string;
  skill: string;
  summary?: string;
  diff?: string;
}

export interface GrowthMetric {
  label: string;
  current: number;
  prev?: number;
  series?: number[];
  color?: string;
}

export interface ErrorLearning {
  pattern: string;
  count: number;
  last_seen: string;
  fix?: string;
}

export interface DailyNote {
  exists: boolean;
  lines: number;
  entries: number;
  last_entry_time?: string;
}

export interface DailyNotes {
  today: DailyNote;
  yesterday: DailyNote;
}

export interface ObsidianMetrics {
  modified_24h: number;
  total_notes?: number;
}

export interface ClaudeMdDetails {
  recent_changes?: { date: string; summary: string }[];
  lines?: number;
}

export interface CostData {
  today: number;
  week: number;
  month: number;
  by_job?: Record<string, number>;
}

export interface ReplyQueue {
  overdue: number;
}

export interface AgentActivity {
  timestamp: string;
  type: string;
  summary: string;
  detail?: string;
}

export interface EvolutionEvent {
  date: string;
  type: string;
  summary: string;
  detail?: string;
  category?: string;
  diff?: string;
}

export interface DashboardData {
  assistant_name?: string;
  services: Service[];
  stats: Stats;
  heartbeat_backlog: unknown[];
  reply_queue: ReplyQueue;
  failing_jobs: FailingJob[];
  data_sources: DataSource[];
  activity: ActivityEntry[];
  agent_activity: AgentActivity[];
  evolution_timeline: EvolutionEvent[];
  skill_inventory: Skill[];
  skill_changes: SkillChange[];
  growth_metrics: GrowthMetric[];
  error_learning: ErrorLearning[];
  daily_notes: DailyNotes;
  obsidian_metrics: ObsidianMetrics;
  claude_md_details: ClaudeMdDetails;
  costs: CostData;
  cron_jobs?: CronJob[];
  lifeline?: LifelineEvent[];
}

export type LifelineGroup = 'claude_md' | 'daily' | 'skills' | 'obsidian';

export interface LifelineEvent {
  ts: string;
  date: string;
  time: string;
  group: LifelineGroup;
  summary: string;
  author: string;
  commit: string;
  files: string[];
  files_total?: number;
  repo: 'claude' | 'mybrain';
}

// === Files API ===

export interface MdLibraryEntry {
  id: string;
  path: string;
  label: string;
  category: string;
  size: number;
  modified?: string;
  modified_ago?: string;
}

export interface FilesData {
  claude_md: { content: string; lines: number; modified?: string };
  memory_md: { content: string; lines: number; modified?: string };
  today: { content: string; lines: number; date: string; exists: boolean };
  yesterday: { content: string; lines: number; date: string; exists: boolean };
  custom?: { content: string; lines: number; date: string; exists: boolean };
  md_library?: MdLibraryEntry[];
}

// === Pipelines API ===

export interface PipelineDefinition {
  name: string;
  states: string[];
  description?: string;
}

export interface PipelineSession {
  session_id: string;
  pipeline: string;
  current_state: string;
  started: string;
  last_transition: string;
  retries: number;
  completed?: boolean;
}

export interface PipelinesData {
  definitions: PipelineDefinition[];
  sessions: PipelineSession[];
}

// === Tasks API ===

export interface TaskItem {
  id: string;
  title: string;
  status: string;
  due?: string;
  notes?: string;
  list_name?: string;
  updated?: string;
  completed?: string;
  links?: string[];
  overdue?: boolean;
  days_overdue?: number;
  days_until_due?: number;
  source?: string;
}

export interface TaskSection {
  name: string;
  tasks: TaskItem[];
}

export interface TasksData {
  sections: TaskSection[];
  total: number;
  overdue: number;
  today: number;
  completed_today: number;
}

// === Deals API ===

export interface Deal {
  name: string;
  stage: string;
  stage_num: number;
  company?: string;
  contact?: string;
  deal_size?: string;
  deal_type?: string;
  follow_up_date?: string;
  last_contact?: string;
  days_since_contact?: number;
  priority?: boolean;
  telegram_chat_id?: string;
  notes?: string;
  overdue?: boolean;
  status?: string;
  value_usd?: number;
}

export interface DealsData {
  deals: Deal[];
  stats: {
    total: number;
    active: number;
    pipeline_value: number;
    overdue_followups: number;
    avg_days_since_contact: number;
  };
}

// === People API ===

export interface Person {
  name: string;
  company?: string;
  role?: string;
  email?: string;
  phone?: string;
  location?: string;
  tags?: string[];
  last_contact?: string;
  days_since_contact?: number;
  deals?: string[];
  handle?: string;
  met?: string;
  source?: string;
}

export interface PeopleData {
  people: Person[];
  stats: {
    total: number;
    contacted_7d: number;
    contacted_30d: number;
    never_contacted: number;
  };
}

// === Heartbeat API ===

export interface HBRun {
  timestamp: string;
  job_id: string;
  status: string;
  duration_seconds?: number;
  cost_usd?: number;
  output?: string;
  error?: string;
  ago?: string;
}

export interface HBJobStats {
  total_runs: number;
  success_rate: number;
  avg_duration: number;
  total_cost: number;
}

export interface HeartbeatData {
  runs: HBRun[];
  job_stats: HBJobStats;
  stats: {
    total_runs: number;
    runs_today: number;
    failures_today: number;
    total_cost: number;
  };
}

// === Views API ===

export interface ViewItem {
  filename: string;
  name: string;
  modified: string;
  size?: number;
}

export interface ViewsData {
  views: ViewItem[];
}

// === Sessions/Chat API ===

export interface Session {
  id: string;
  project?: string;
  date: string;
  preview: string;
  messages: number;
  is_active: boolean;
  is_human?: boolean;
  is_cron?: boolean;
  snippet?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  tool_use?: { name: string; input: unknown };
  tool_result?: { content: string; is_error?: boolean };
  thinking?: string;
  timestamp?: string;
}

export interface SessionDetail {
  session_id: string;
  messages: ChatMessage[];
}

// === CRON Jobs ===

export interface CronRunDot {
  ok: boolean;
  ts: string;
  dur: number;
}

export interface CronJob {
  id: string;
  schedule: string;
  enabled: boolean;
  mode: string;
  last_run?: string;
  next_run?: string;
  consecutive_failures?: number;
  model?: string;
  recent_runs?: CronRunDot[];
  last_error?: string;
  success_rate_24h?: number | null;
}

// === Agent Hub (dispatch agents from subagents_state.json) ===

export interface Agent {
  id: string;
  name: string;
  type: string;
  status: 'running' | 'completed' | 'failed' | 'killed' | 'pending_retry';
  session_id?: string;
  started?: number;
  parent?: string;
  model: string;
  output_lines: number;
  inbox_size: number;
  last_output: string;
  cost_usd: number;
  error?: string;
  output?: string[];
}

// === Feed ===

export interface FeedDelta {
  type: string;
  path?: string;
  change?: string;
  trigger?: string;
  title?: string;
  subject?: string;
  deal?: string;
  target?: string;
  key?: string;
  source?: string;
  count?: number;
  reason?: string;
  // Enriched fields
  summary?: string;
  deal_name?: string;
  stage?: string;
  next_action?: string;
  category?: string;
  hint?: string;
  facts?: string[];
  label?: string;
  expected?: string;
  // Observation fields
  lens?: string;
  tag?: string;
  trajectory?: string;
  due?: string;
}

export interface FeedMessage {
  timestamp: string;
  topic_id: number | null;
  topic: string;
  message: string;
  parse_mode: string | null;
  ago?: string;
  job_id?: string;
  session_id?: string;
  deltas?: FeedDelta[];
}

export interface FeedData {
  messages: FeedMessage[];
  topics: string[];
  total: number;
  generated_at: string;
}

// === Tab config ===

export type TabId =
  | 'feed' | 'tasks' | 'klava' | 'deck' | 'views' | 'lifeline'
  | 'skills' | 'health' | 'files' | 'heartbeat'
  | 'people' | 'habits' | 'settings';

export interface TabConfig {
  id: TabId;
  label: string;
  badgeId?: string;
  badgeStyle?: 'subtle' | 'danger' | '';
}

export const TABS: TabConfig[] = [
  { id: 'deck', label: 'Deck', badgeId: 'deck', badgeStyle: 'subtle' },
  { id: 'lifeline', label: 'Lifeline', badgeId: 'lifeline', badgeStyle: 'subtle' },
  { id: 'tasks', label: 'Tasks', badgeId: 'tasks' },
  { id: 'habits', label: 'Habits', badgeId: 'habits', badgeStyle: 'subtle' },
  { id: 'klava', label: 'Assistant', badgeId: 'klava', badgeStyle: 'subtle' },
  { id: 'views', label: 'Views', badgeId: 'views', badgeStyle: 'subtle' },
  { id: 'health', label: 'Health', badgeId: 'health' },
  { id: 'heartbeat', label: 'Heartbeat', badgeId: 'heartbeat' },
  { id: 'skills', label: 'Skills', badgeId: 'skills' },

  { id: 'files', label: 'Files' },
  { id: 'people', label: 'People', badgeId: 'people', badgeStyle: 'subtle' },
  { id: 'settings', label: 'Settings' },
];

// === Self-Evolve ===

export interface BacklogItem {
  date: string;
  title: string;
  source: string;
  priority: 'high' | 'medium' | 'low';
  status: 'open' | 'in-progress' | 'done' | 'wontfix';
  seen: number;
  description: string;
  fix_hint: string;
  resolved: string;
  session_id?: string;
}

export interface SelfEvolveData {
  metrics: { added: number; fixed: number; avg_days: string; last_run: string };
  items: BacklogItem[];
}

// === Sources (vadimgest manifests) ===

export interface SourceManifest {
  display_name: string;
  description: string;
  category: string;
  dependencies: {
    python: string[];
    cli: string[];
    credentials: string[];
    os: string[];
  };
  config_schema: Record<string, { type: string; default?: unknown; description?: string }>;
  loadable: boolean;
  enabled: boolean;
  ready: { ok: boolean; missing?: string[] } | null;
  stats: { file_size: number; last_modified: string; record_count: number } | null;
  load_error?: string;
}

export type SourcesData = Record<string, SourceManifest>;
