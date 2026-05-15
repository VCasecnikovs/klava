import { esc } from '@/lib/utils';

interface ToolConfig {
  icon: string;
  color: string;
  dim: string;
  border: string;
  category: string;
  verb: string;
  permission: 'auto' | 'approval' | 'mixed';
  weight: 'read' | 'write' | 'exec' | 'agent' | 'web' | 'question' | 'system';
}

export interface ToolMeta {
  category: string;
  verb: string;
  permission: ToolConfig['permission'];
  weight: ToolConfig['weight'];
  origin?: string;
  action?: string;
}

const PALETTE = {
  blue: { color: '#60a5fa', dim: 'rgba(96,165,250,0.08)', border: 'rgba(96,165,250,0.18)' },
  green: { color: '#4ade80', dim: 'rgba(74,222,128,0.08)', border: 'rgba(74,222,128,0.18)' },
  emerald: { color: '#34d399', dim: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.18)' },
  violet: { color: '#a78bfa', dim: 'rgba(167,139,250,0.08)', border: 'rgba(167,139,250,0.18)' },
  purple: { color: '#c084fc', dim: 'rgba(192,132,252,0.08)', border: 'rgba(192,132,252,0.18)' },
  orange: { color: '#f97316', dim: 'rgba(249,115,22,0.08)', border: 'rgba(249,115,22,0.18)' },
  lightOrange: { color: '#fb923c', dim: 'rgba(251,146,60,0.08)', border: 'rgba(251,146,60,0.18)' },
  yellow: { color: '#facc15', dim: 'rgba(250,204,21,0.08)', border: 'rgba(250,204,21,0.18)' },
  amber: { color: '#fbbf24', dim: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.18)' },
  cyan: { color: '#38bdf8', dim: 'rgba(56,189,248,0.08)', border: 'rgba(56,189,248,0.18)' },
  teal: { color: '#2dd4bf', dim: 'rgba(45,212,191,0.08)', border: 'rgba(45,212,191,0.18)' },
  pink: { color: '#e879f9', dim: 'rgba(232,121,249,0.08)', border: 'rgba(232,121,249,0.18)' },
  zinc: { color: '#a1a1aa', dim: 'rgba(161,161,170,0.08)', border: 'rgba(161,161,170,0.18)' },
  dark: { color: '#71717a', dim: 'rgba(113,113,122,0.08)', border: 'rgba(113,113,122,0.18)' },
  red: { color: '#f87171', dim: 'rgba(248,113,113,0.08)', border: 'rgba(248,113,113,0.18)' },
};

function cfg(icon: string, palette: keyof typeof PALETTE, category: string, verb: string, permission: ToolConfig['permission'], weight: ToolConfig['weight']): ToolConfig {
  return { icon, ...PALETTE[palette], category, verb, permission, weight };
}

const TOOL_REGISTRY: Record<string, ToolConfig> = {
  Read: cfg('&#128196;', 'blue', 'Files', 'read', 'auto', 'read'),
  Write: cfg('&#9999;', 'green', 'Files', 'write', 'approval', 'write'),
  Edit: cfg('&#8596;', 'purple', 'Files', 'patch', 'approval', 'write'),
  NotebookEdit: cfg('&#9638;', 'purple', 'Notebook', 'edit cell', 'approval', 'write'),
  Glob: cfg('&#128193;', 'zinc', 'Search', 'find files', 'auto', 'read'),
  Grep: cfg('&#128269;', 'yellow', 'Search', 'grep', 'auto', 'read'),
  LSP: cfg('&#8984;', 'cyan', 'Code intel', 'inspect', 'auto', 'read'),
  Bash: cfg('&#9654;', 'orange', 'Shell', 'run', 'approval', 'exec'),
  exec_command: cfg('&#9654;', 'orange', 'Shell', 'run', 'approval', 'exec'),
  shell: cfg('&#9654;', 'orange', 'Shell', 'run', 'approval', 'exec'),
  write_stdin: cfg('&#8629;', 'orange', 'Shell', 'write stdin', 'approval', 'exec'),
  PowerShell: cfg('PS', 'orange', 'Shell', 'run', 'approval', 'exec'),
  Monitor: cfg('&#128250;', 'orange', 'Shell', 'watch', 'approval', 'exec'),
  WebSearch: cfg('&#127760;', 'cyan', 'Web', 'search', 'approval', 'web'),
  'web.run': cfg('&#127760;', 'cyan', 'Web', 'use web', 'approval', 'web'),
  search_query: cfg('&#127760;', 'cyan', 'Web', 'search', 'approval', 'web'),
  image_query: cfg('&#128247;', 'cyan', 'Web', 'image search', 'approval', 'web'),
  open: cfg('&#128279;', 'teal', 'Web', 'open', 'approval', 'web'),
  click: cfg('&#128433;', 'teal', 'Web', 'click', 'approval', 'web'),
  find: cfg('&#128269;', 'teal', 'Web', 'find', 'approval', 'web'),
  finance: cfg('&#128200;', 'teal', 'Web', 'finance', 'approval', 'web'),
  weather: cfg('&#9729;', 'teal', 'Web', 'weather', 'approval', 'web'),
  sports: cfg('&#127942;', 'teal', 'Web', 'sports', 'approval', 'web'),
  time: cfg('&#9201;', 'teal', 'Web', 'time', 'approval', 'web'),
  WebFetch: cfg('&#128279;', 'teal', 'Web', 'fetch', 'approval', 'web'),
  Agent: cfg('&#129302;', 'violet', 'Agents', 'delegate', 'auto', 'agent'),
  Task: cfg('&#129302;', 'amber', 'Agents', 'delegate', 'auto', 'agent'),
  spawn_agent: cfg('&#129302;', 'violet', 'Agents', 'spawn', 'auto', 'agent'),
  send_input: cfg('&#9993;', 'violet', 'Agents', 'message', 'auto', 'agent'),
  wait_agent: cfg('&#9203;', 'violet', 'Agents', 'wait', 'auto', 'agent'),
  close_agent: cfg('&#9632;', 'violet', 'Agents', 'close', 'auto', 'agent'),
  resume_agent: cfg('&#8635;', 'violet', 'Agents', 'resume', 'auto', 'agent'),
  TeamCreate: cfg('&#8756;', 'violet', 'Teams', 'create team', 'auto', 'agent'),
  TeamDelete: cfg('&#8756;', 'violet', 'Teams', 'delete team', 'auto', 'agent'),
  SendMessage: cfg('&#9993;', 'violet', 'Teams', 'message', 'auto', 'agent'),
  TaskCreate: cfg('&#10133;', 'emerald', 'Tasks', 'create', 'auto', 'system'),
  TaskUpdate: cfg('&#9745;', 'emerald', 'Tasks', 'update', 'auto', 'system'),
  TaskList: cfg('&#128203;', 'emerald', 'Tasks', 'list', 'auto', 'read'),
  TaskGet: cfg('&#128203;', 'emerald', 'Tasks', 'open', 'auto', 'read'),
  TodoWrite: cfg('&#9745;', 'emerald', 'Todos', 'sync', 'auto', 'system'),
  update_plan: cfg('&#9745;', 'emerald', 'Todos', 'sync', 'auto', 'system'),
  TaskOutput: cfg('&#8617;', 'dark', 'Background', 'read output', 'auto', 'read'),
  TaskStop: cfg('&#9632;', 'red', 'Background', 'stop', 'auto', 'system'),
  CronCreate: cfg('&#9202;', 'teal', 'Schedule', 'schedule', 'auto', 'system'),
  CronDelete: cfg('&#9202;', 'red', 'Schedule', 'cancel', 'auto', 'system'),
  CronList: cfg('&#9202;', 'teal', 'Schedule', 'list', 'auto', 'read'),
  EnterPlanMode: cfg('&#9874;', 'purple', 'Plan', 'enter', 'auto', 'system'),
  ExitPlanMode: cfg('&#9874;', 'purple', 'Plan', 'request approval', 'approval', 'question'),
  EnterWorktree: cfg('&#9176;', 'teal', 'Worktree', 'enter', 'auto', 'system'),
  ExitWorktree: cfg('&#9176;', 'teal', 'Worktree', 'exit', 'auto', 'system'),
  AskUserQuestion: cfg('&#10067;', 'lightOrange', 'Question', 'ask', 'auto', 'question'),
  request_user_input: cfg('&#10067;', 'lightOrange', 'Question', 'ask', 'auto', 'question'),
  Skill: cfg('&#9889;', 'pink', 'Skills', 'invoke', 'approval', 'system'),
  ToolSearch: cfg('&#128268;', 'dark', 'Tools', 'discover', 'auto', 'read'),
  ToolSearchRegex: cfg('&#128268;', 'dark', 'Tools', 'discover', 'auto', 'read'),
  ToolSearchBM25: cfg('&#128268;', 'dark', 'Tools', 'discover', 'auto', 'read'),
  ListMcpResourcesTool: cfg('MCP', 'teal', 'MCP', 'list resources', 'auto', 'read'),
  ReadMcpResourceTool: cfg('MCP', 'teal', 'MCP', 'read resource', 'auto', 'read'),
  list_mcp_resources: cfg('MCP', 'teal', 'MCP', 'list resources', 'auto', 'read'),
  list_mcp_resource_templates: cfg('MCP', 'teal', 'MCP', 'list templates', 'auto', 'read'),
  read_mcp_resource: cfg('MCP', 'teal', 'MCP', 'read resource', 'auto', 'read'),
  view_image: cfg('&#128247;', 'pink', 'Images', 'view image', 'auto', 'read'),
  imagegen: cfg('&#127912;', 'pink', 'Images', 'generate', 'approval', 'write'),
  'image_gen.imagegen': cfg('&#127912;', 'pink', 'Images', 'generate', 'approval', 'write'),
  ShareOnboardingGuide: cfg('&#128218;', 'pink', 'Onboarding', 'share', 'approval', 'web'),
  CodeExecution: cfg('&#128013;', 'green', 'Execution', 'run code', 'approval', 'exec'),
  BashCodeExecution: cfg('&#9654;', 'green', 'Execution', 'run shell', 'approval', 'exec'),
  TextEditorCodeExecution: cfg('&#128221;', 'green', 'Execution', 'edit', 'approval', 'write'),
  apply_patch: cfg('&#8596;', 'purple', 'Files', 'patch', 'approval', 'write'),
  _default: cfg('&#9881;', 'amber', 'Tool', 'call', 'mixed', 'system'),
};

function mcpConfig(name: string): ToolConfig | null {
  const lower = name.toLowerCase();
  if (lower.startsWith('mcp__browser__')) return cfg('&#128433;', 'pink', 'Browser', 'drive UI', 'approval', 'web');
  if (lower.startsWith('mcp__grafana__')) return cfg('&#128202;', 'orange', 'Grafana', 'observe', 'auto', 'read');
  if (lower.startsWith('mcp__claude_ai_gmail__')) return cfg('&#9993;', 'blue', 'Gmail', 'mail', 'approval', 'web');
  if (lower.startsWith('mcp__claude_ai_google_calendar__')) return cfg('&#128197;', 'blue', 'Calendar', 'calendar', 'approval', 'web');
  if (lower.startsWith('mcp__claude_ai_google_drive__')) return cfg('&#128194;', 'blue', 'Drive', 'drive', 'approval', 'web');
  if (lower.startsWith('mcp__github__')) return { ...cfg('&#128025;', 'violet', 'GitHub', 'github', 'approval', 'web'), color: '#8b5cf6' };
  if (lower.startsWith('mcp__google__')) return cfg('&#128231;', 'blue', 'Google', 'google', 'approval', 'web');
  if (lower.startsWith('mcp__playwright__') || lower.startsWith('mcp__claude-in-chrome__')) return cfg('&#127916;', 'pink', 'Browser', 'drive UI', 'approval', 'web');
  if (lower.startsWith('mcp__obsidian__')) return cfg('&#128218;', 'violet', 'Obsidian', 'notes', 'approval', 'web');
  if (lower.startsWith('mcp__ch')) return cfg('&#128202;', 'orange', 'ClickHouse', 'query', 'approval', 'read');
  if (lower.startsWith('mcp__whatsapp__')) return cfg('&#128172;', 'green', 'WhatsApp', 'message', 'approval', 'web');
  if (lower.startsWith('mcp__')) return cfg('MCP', 'teal', 'MCP', 'external', 'mixed', 'web');
  if (lower.startsWith('multi_tool_use.')) return cfg('&#8759;', 'zinc', 'Parallel', 'batch', 'mixed', 'system');
  return null;
}

export function getToolConfig(name: string): ToolConfig {
  if (TOOL_REGISTRY[name]) return TOOL_REGISTRY[name];
  return mcpConfig(name || '') || TOOL_REGISTRY._default;
}

export function getToolMeta(name: string): ToolMeta {
  const reg = getToolConfig(name);
  const meta: ToolMeta = {
    category: reg.category,
    verb: reg.verb,
    permission: reg.permission,
    weight: reg.weight,
  };
  if (name?.startsWith('mcp__')) {
    const parsed = parseMcpName(name);
    meta.origin = parsed.server;
    meta.action = parsed.action;
  } else if (name?.startsWith('multi_tool_use.')) {
    meta.origin = 'multi_tool_use';
    meta.action = name.split('.').pop();
  }
  return meta;
}

function parseMcpName(name: string): { server: string; action: string } {
  const parts = name.split('__');
  if (parts.length >= 3) return { server: parts[1].replace(/_/g, ' '), action: parts.slice(2).join('__').replace(/_/g, ' ') };
  return { server: 'mcp', action: name.replace(/^mcp__/, '').replace(/_/g, ' ') };
}

function fileName(path = ''): string {
  return path.split('/').pop() || '';
}

function dirname(path = ''): string {
  const fn = fileName(path);
  return fn ? path.substring(0, path.length - fn.length) : path;
}

function truncate(value: string, limit: number, ellipsis = true): string {
  if (!value) return '';
  return value.length > limit ? value.substring(0, limit) + (ellipsis ? '...' : '') : value;
}

function firstString(input: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = input[key];
    if (typeof value === 'string' && value.trim()) return value;
    if (typeof value === 'number') return String(value);
  }
  return '';
}

function renderChip(label: string, tone = 'neutral'): string {
  return `<span class="tool-chip ${tone}">${esc(label)}</span>`;
}

function renderKV(label: string, value: unknown): string {
  if (value === undefined || value === null || value === '') return '';
  const rendered = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
  return `<div class="tool-kv"><span>${esc(label)}</span><code>${esc(truncate(rendered, 280))}</code></div>`;
}

function renderGenericPanel(input: Record<string, unknown>, preferred: string[] = []): string {
  const keys = [...preferred, ...Object.keys(input).filter(k => !preferred.includes(k))].filter((v, i, arr) => arr.indexOf(v) === i);
  const rows = keys.map(k => renderKV(k, input[k])).filter(Boolean).slice(0, 10).join('');
  return rows ? `<div class="tool-param-grid">${rows}</div>` : '';
}

function renderPromptPreview(prompt: string, limit = 360): string {
  if (!prompt) return '';
  return `<div class="tool-prompt-preview">${esc(truncate(prompt, limit))}</div>`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getToolSummary(tool: string, input: any): string {
  if (!input) return '';
  if (tool === 'Read' && input.file_path) return fileName(input.file_path);
  if (tool === 'Bash' || tool === 'exec_command' || tool === 'shell' || tool === 'PowerShell' || tool === 'Monitor') return truncate(input.description || input.command || input.cmd || '', 80, false);
  if (tool === 'write_stdin') return input.chars ? truncate(input.chars, 80, false) : `session ${input.session_id || ''}`.trim();
  if (tool === 'web.run') return summarizeWebRun(input);
  if (tool === 'Edit' && input.file_path) return fileName(input.file_path);
  if ((tool === 'Edit' || tool === 'apply_patch') && input.patch) return 'apply patch';
  if (tool === 'NotebookEdit' && input.notebook_path) return `${fileName(input.notebook_path)} cell ${input.cell_number ?? ''}`.trim();
  if (tool === 'Grep' && input.pattern) return `/${input.pattern}/` + (input.path ? ' in ' + fileName(input.path) : '');
  if (tool === 'Write' && input.file_path) return fileName(input.file_path);
  if (tool === 'Glob' && input.pattern) return input.pattern;
  if (tool === 'LSP') return [input.operation, fileName(input.filePath || input.file_path)].filter(Boolean).join(' ');
  if ((tool === 'WebSearch' || tool === 'search_query') && input.query) return input.query;
  if (tool === 'search_query' && Array.isArray(input.search_query)) return input.search_query.map((q: { q?: string }) => q.q).filter(Boolean).join(', ');
  if (tool === 'image_query' && Array.isArray(input.image_query)) return input.image_query.map((q: { q?: string }) => q.q).filter(Boolean).join(', ');
  if ((tool === 'open' || tool === 'click' || tool === 'find') && input.open) return JSON.stringify(input.open);
  if (tool === 'WebFetch' && input.url) {
    try { return new URL(input.url).hostname; } catch { return truncate(input.url, 40); }
  }
  if (tool === 'Agent' || tool === 'Task' || tool === 'spawn_agent') {
    const parts: string[] = [];
    if (input.subagent_type || input.agent_type) parts.push(`[${input.subagent_type || input.agent_type}]`);
    if (input.description) parts.push(input.description);
    if (input.message) parts.push(input.message);
    return parts.join(' ') || '';
  }
  if (tool === 'send_input') return input.target || truncate(input.message || '', 80);
  if (tool === 'wait_agent') return Array.isArray(input.targets) ? input.targets.join(', ') : '';
  if (tool === 'close_agent' || tool === 'resume_agent') return input.target || input.id || '';
  if (tool === 'TodoWrite') {
    const t = Array.isArray(input.todos) ? input.todos : [];
    const d = t.filter((x: { status: string }) => x.status === 'completed').length;
    return `${d}/${t.length} done`;
  }
  if (tool === 'TaskCreate') return input.subject || input.content || '';
  if (tool === 'TaskUpdate') {
    const parts: string[] = [];
    if (input.taskId) parts.push(`#${input.taskId}`);
    if (input.status) parts.push(input.status);
    if (input.subject) parts.push(input.subject);
    return parts.join(' ') || '';
  }
  if (tool === 'TaskList') return 'listing tasks';
  if (tool === 'TaskGet') return input.taskId ? `#${input.taskId}` : '';
  if (tool === 'TaskOutput') return input.task_id || '';
  if (tool === 'TaskStop') return input.task_id || input.shell_id || '';
  if (tool === 'ToolSearch' || tool === 'ToolSearchRegex' || tool === 'ToolSearchBM25') return input.query || input.pattern || '';
  if (tool === 'CodeExecution' || tool === 'BashCodeExecution') return truncate(input.command || input.code || '', 80);
  if (tool === 'TextEditorCodeExecution') return input.command || input.path || input.file_path || '';
  if (tool === 'AskUserQuestion') return (input.questions || [])[0]?.question?.substring(0, 60) || '';
  if (tool === 'request_user_input') return (input.questions || [])[0]?.question?.substring(0, 60) || '';
  if (tool === 'update_plan') return Array.isArray(input.plan) ? `${input.plan.length} steps` : '';
  if (tool === 'Skill') return input.skill || '';
  if (tool === 'view_image') return fileName(input.path || '');
  if (tool === 'imagegen' || tool === 'image_gen.imagegen') return truncate(input.prompt || '', 80);
  if (tool === 'CronCreate') return `${input.cron || ''} ${input.recurring === false ? 'once' : 'recurring'}`.trim();
  if (tool === 'CronDelete') return input.id || '';
  if (tool === 'CronList') return 'scheduled prompts';
  if (tool === 'EnterWorktree') return input.name || input.path || 'new worktree';
  if (tool === 'ExitWorktree') return input.action || '';
  if (tool === 'TeamCreate') return input.team_name || '';
  if (tool === 'SendMessage') return input.to || '';
  if (tool === 'TeamDelete') return 'delete team';
  if (tool?.startsWith('mcp__')) return getMcpSummary(tool, input);
  if (tool?.startsWith('multi_tool_use.')) return Array.isArray(input.tool_uses) ? `${input.tool_uses.length} tool uses` : '';
  return firstString(input, ['cmd', 'command', 'chars', 'query', 'q', 'url', 'ref_id', 'path', 'file_path', 'name', 'id', 'text', 'input', 'patch']) || '';
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function summarizeWebRun(input: any): string {
  const keys = ['search_query', 'image_query', 'open', 'click', 'find', 'finance', 'weather', 'sports', 'time'];
  const active = keys.filter(k => Array.isArray(input?.[k]) && input[k].length);
  if (!active.length) return '';
  if (active.includes('search_query')) return input.search_query.map((q: { q?: string }) => q.q).filter(Boolean).join(', ');
  if (active.includes('image_query')) return input.image_query.map((q: { q?: string }) => q.q).filter(Boolean).join(', ');
  return active.join(', ');
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getMcpSummary(tool: string, input: any): string {
  const lower = tool.toLowerCase();
  if (lower.startsWith('mcp__browser__')) {
    return firstString(input, ['url', 'query', 'action', 'text', 'pattern', 'ref', 'shortcutId', 'command']) || (input.tabId ? `tab ${input.tabId}` : 'browser');
  }
  if (lower.startsWith('mcp__grafana__')) {
    return firstString(input, ['operation', 'query', 'expr', 'logql', 'uid', 'dashboardUid', 'datasourceUid', 'rule_uid', 'name', 'entityName']) || parseMcpName(tool).action;
  }
  if (lower.includes('gmail') || lower.includes('calendar') || lower.includes('drive')) return firstString(input, ['query', 'id', 'name', 'callback_url']) || parseMcpName(tool).action;
  return firstString(input, ['query', 'operation', 'path', 'url', 'name', 'id', 'title', 'text']) || parseMcpName(tool).action;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function formatToolInput(toolName: string, input: any): string | null {
  if (!input || typeof input !== 'object') return null;
  switch (toolName) {
    case 'Read': {
      const p = input.file_path || '';
      let info = '';
      if (input.offset) info += 'L' + input.offset;
      if (input.limit) info += (info ? '-' : 'L0-') + ((input.offset || 0) + input.limit);
      return `<div class="tool-file-path"><span style="opacity:0.6">&#128196;</span><span style="color:var(--text-muted)">${esc(dirname(p))}</span><span style="color:var(--text)">${esc(fileName(p))}</span>${info ? `<span class="tool-mini-stat">${esc(info)}</span>` : ''}</div>`;
    }
    case 'Write': {
      const p = input.file_path || '';
      const c = input.content || '';
      const lines = c.split('\n').length;
      return `<div class="tool-file-path"><span style="opacity:0.6">&#9999;</span><span style="color:var(--text-muted)">${esc(dirname(p))}</span><span style="color:#4ade80">${esc(fileName(p))}</span><span class="tool-mini-stat">${lines} lines</span></div><pre class="tool-code-preview">${esc(truncate(c, 500))}</pre>`;
    }
    case 'Edit': {
      const p = input.file_path || '';
      const old_s = input.old_string || '';
      const new_s = input.new_string || '';
      let h = `<div class="tool-diff-header">${esc(p)}${input.replace_all ? ' · replace all' : ''}</div>`;
      for (const line of old_s.split('\n')) h += `<div class="tool-diff-line tool-diff-del">- ${esc(line)}</div>`;
      for (const line of new_s.split('\n')) h += `<div class="tool-diff-line tool-diff-add">+ ${esc(line)}</div>`;
      return h;
    }
    case 'NotebookEdit':
      return `<div class="tool-file-path"><span style="opacity:0.6">&#9638;</span><span style="color:var(--text-muted)">${esc(dirname(input.notebook_path || ''))}</span><span style="color:var(--text)">${esc(fileName(input.notebook_path || ''))}</span><span class="tool-mini-stat">cell ${esc(String(input.cell_number ?? '?'))} · ${esc(input.edit_mode || 'replace')}</span></div>${renderPromptPreview(input.new_source || '', 500)}`;
    case 'Bash':
    case 'exec_command':
    case 'shell':
    case 'PowerShell':
    case 'Monitor':
    case 'BashCodeExecution': {
      const cmd = input.command || input.cmd || input.code || '';
      const desc = input.description || '';
      let h = '';
      if (desc) h += `<div class="tool-human-desc">${esc(desc)}</div>`;
      h += `<div class="tool-bash-cmd"><span class="tool-bash-prompt">${toolName === 'PowerShell' ? 'PS>' : '$'}</span><span>${esc(cmd)}</span></div>`;
      if (input.workdir || input.cwd) h += `<div class="tool-muted small">${esc(input.workdir || input.cwd)}</div>`;
      if (input.timeout || input.run_in_background || input.dangerouslyDisableSandbox) {
        h += `<div class="tool-chip-row">${input.timeout ? renderChip(`${input.timeout}ms`, 'neutral') : ''}${input.run_in_background ? renderChip('background', 'good') : ''}${input.dangerouslyDisableSandbox ? renderChip('unsandboxed', 'danger') : ''}</div>`;
      }
      return h;
    }
    case 'write_stdin':
      return `<div class="tool-bash-cmd"><span class="tool-bash-prompt">stdin</span><span>${esc(input.chars || '')}</span></div>${renderGenericPanel(input, ['session_id', 'yield_time_ms', 'max_output_tokens'])}`;
    case 'Grep': {
      let h = `<div class="tool-search-panel"><span class="tool-search-pattern">/${esc(input.pattern || '')}/</span>`;
      if (input.path) h += ` <span class="tool-muted">in</span> <span>${esc(input.path)}</span>`;
      if (input.glob) h += ` <span class="tool-muted">glob</span> <span>${esc(input.glob)}</span>`;
      if (input.output_mode) h += ` <span class="tool-output-mode">[${esc(input.output_mode)}]</span> ${renderChip(input.output_mode)}`;
      h += `</div>`;
      return h;
    }
    case 'Glob':
      return `<div class="tool-search-panel"><span>${esc(input.pattern || '')}</span>${input.path ? ` <span class="tool-muted">in</span> <span>${esc(input.path)}</span>` : ''}</div>`;
    case 'LSP':
      return renderGenericPanel(input, ['operation', 'filePath', 'line', 'character']);
    case 'WebSearch':
    case 'search_query':
      return `<div class="tool-query-card"><span class="tool-quote-mark">search</span><span>${esc(input.query || '')}</span></div>`;
    case 'web.run':
      return renderGenericPanel(input, ['search_query', 'image_query', 'open', 'click', 'find', 'finance', 'weather', 'sports', 'time', 'response_length']);
    case 'image_query':
      return `<div class="tool-query-card"><span class="tool-quote-mark">image</span><span>${esc(JSON.stringify(input.image_query || input.query || input.q || ''))}</span></div>`;
    case 'open':
    case 'click':
    case 'find':
      return renderGenericPanel(input, ['open', 'click', 'find', 'ref_id', 'id', 'pattern', 'url']);
    case 'ToolSearch':
    case 'ToolSearchRegex':
    case 'ToolSearchBM25':
      return `<div class="tool-query-card"><span class="tool-quote-mark">tools</span><span>${esc(input.query || input.pattern || '')}</span></div>`;
    case 'CodeExecution': {
      const code = input.code || input.command || '';
      return `<pre class="tool-code-preview tall">${esc(code || JSON.stringify(input, null, 2))}</pre>`;
    }
    case 'TextEditorCodeExecution':
      return renderGenericPanel(input, ['command', 'path', 'file_path']);
    case 'WebFetch': {
      let domain = '';
      try { domain = new URL(input.url || '').hostname; } catch { domain = input.url || ''; }
      return `<div class="tool-url-card"><span>${esc(domain)}</span><code>${esc(input.url || '')}</code></div>${renderPromptPreview(input.prompt || '', 180)}`;
    }
    case 'Agent':
    case 'Task': {
      const badges: string[] = [];
      if (input.subagent_type) badges.push(renderChip(input.subagent_type, 'agent'));
      if (input.model) badges.push(renderChip(input.model, 'warm'));
      if (input.run_in_background) badges.push(renderChip('bg background', 'good'));
      if (input.isolation) badges.push(renderChip(input.isolation, 'warn'));
      if (input.mode) badges.push(renderChip(input.mode, 'neutral'));
      let h = `<div class="tool-agent-card">`;
      if (badges.length) h += `<div class="tool-chip-row">${badges.join('')}</div>`;
      if (input.description) h += `<div class="tool-agent-title">${esc(input.description)}</div>`;
      h += renderPromptPreview(input.prompt || '', 300);
      h += `<div class="chat-task-timer"></div></div>`;
      return h;
    }
    case 'spawn_agent':
    case 'send_input':
    case 'wait_agent':
    case 'close_agent':
    case 'resume_agent':
      return renderGenericPanel(input, ['agent_type', 'target', 'targets', 'id', 'message', 'items', 'timeout_ms']);
    case 'TaskCreate': {
      let h = `<div class="tool-task-card">`;
      if (input.subject || input.content) h += `<div class="tool-agent-title">${esc(input.subject || input.content)}</div>`;
      if (input.activeForm) h += `<div class="tool-muted small">Active: ${esc(input.activeForm)}</div>`;
      if (input.description) h += renderPromptPreview(input.description, 300);
      h += `</div>`;
      return h;
    }
    case 'TaskUpdate': {
      const statusColors: Record<string, string> = { in_progress: 'warn', completed: 'good', pending: 'neutral', deleted: 'danger' };
      let h = `<div class="tool-task-card"><div class="tool-chip-row">`;
      if (input.taskId) h += renderChip(`Task #${input.taskId}`);
      if (input.status) {
        const legacyColors: Record<string, string> = { in_progress: '#fbbf24', completed: '#4ade80', pending: '#a1a1aa', deleted: '#ef4444' };
        h += renderChip(input.status, statusColors[input.status] || 'neutral');
        h += `<span style="display:none;color:${legacyColors[input.status] || 'var(--text-muted)'}">${esc(input.status)}</span>`;
      }
      h += `</div>`;
      if (input.subject) h += `<div class="tool-agent-title">${esc(input.subject)}</div>`;
      if (input.activeForm) h += `<div class="tool-muted small">Active: ${esc(input.activeForm)}</div>`;
      h += `</div>`;
      return h;
    }
    case 'TaskList':
    case 'TaskGet':
    case 'TaskOutput':
    case 'TaskStop':
      return renderGenericPanel(input, ['taskId', 'task_id', 'shell_id', 'block', 'timeout']);
    case 'TodoWrite':
      return renderTodoHtml(Array.isArray(input.todos) ? input.todos : []);
    case 'AskUserQuestion':
    case 'request_user_input':
      return renderQuestionsHtml(Array.isArray(input.questions) ? input.questions : []);
    case 'update_plan':
      return renderTodoHtml(Array.isArray(input.plan) ? input.plan.map((p: { status?: string; step?: string }) => ({ status: p.status, content: p.step })) : []);
    case 'Skill':
      return `<div class="tool-query-card"><span class="tool-quote-mark">skill</span><span style="color:#e879f9">/${esc(input.skill || '')}</span>${input.args ? `<code>${esc(input.args)}</code>` : ''}</div>`;
    case 'view_image':
      return `<div class="tool-file-path"><span style="opacity:0.6">&#128247;</span><span style="color:var(--text-muted)">${esc(dirname(input.path || ''))}</span><span style="color:var(--text)">${esc(fileName(input.path || ''))}</span></div>`;
    case 'imagegen':
    case 'image_gen.imagegen':
      return renderPromptPreview(input.prompt || '', 500);
    case 'apply_patch':
      return `<pre class="tool-code-preview tall">${esc(input.patch || input.input || JSON.stringify(input, null, 2))}</pre>`;
    case 'CronCreate':
    case 'CronDelete':
    case 'CronList':
      return renderGenericPanel(input, ['cron', 'prompt', 'recurring', 'durable', 'id']);
    case 'EnterPlanMode':
    case 'ExitPlanMode':
    case 'EnterWorktree':
    case 'ExitWorktree':
    case 'TeamCreate':
    case 'TeamDelete':
    case 'SendMessage':
    case 'ListMcpResourcesTool':
    case 'ReadMcpResourceTool':
    case 'list_mcp_resources':
    case 'list_mcp_resource_templates':
    case 'read_mcp_resource':
    case 'ShareOnboardingGuide':
      return renderGenericPanel(input, ['team_name', 'description', 'to', 'summary', 'message', 'name', 'path', 'action', 'uri']);
    default:
      if (toolName?.startsWith('mcp__')) return renderMcpInput(toolName, input);
      if (toolName?.startsWith('multi_tool_use.')) return renderGenericPanel(input, ['tool_uses']);
      return renderGenericPanel(input);
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function renderMcpInput(toolName: string, input: any): string {
  const parsed = parseMcpName(toolName);
  const headline = getMcpSummary(toolName, input);
  let h = `<div class="tool-mcp-card"><div class="tool-mcp-head"><span>${esc(parsed.server)}</span><code>${esc(parsed.action)}</code></div>`;
  if (headline) h += `<div class="tool-mcp-summary">${esc(headline)}</div>`;
  h += renderGenericPanel(input, ['operation', 'query', 'expr', 'logql', 'url', 'action', 'text', 'tabId', 'datasourceUid', 'dashboardUid', 'uid', 'name']);
  h += `</div>`;
  return h;
}

interface TodoItem {
  status?: string;
  content?: string;
}

export function renderTodoHtml(todos: TodoItem[]): string {
  if (!todos || !todos.length) return '';
  const done = todos.filter(t => t.status === 'completed').length;
  let h = `<div class="tool-todo-list"><div class="tool-todo-progress"><span>${done}/${todos.length}</span><div><i style="width:${todos.length ? Math.round(done / todos.length * 100) : 0}%"></i></div></div>`;
  for (const t of todos) {
    const st = t.status || 'pending';
    const chk = st === 'completed' ? 'done' : (st === 'in_progress' ? 'progress' : '');
    const ico = st === 'completed' ? '&#10003;' : (st === 'in_progress' ? '&#9654;' : '');
    const txt = st === 'completed' ? 'done' : '';
    h += `<div class="tool-todo-item"><span class="tool-todo-check ${chk}">${ico}</span><span class="tool-todo-text ${txt}">${esc(t.content || '')}</span></div>`;
  }
  h += '</div>';
  return h;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function renderQuestionsHtml(questions: any[]): string {
  if (!questions.length) return '';
  let h = '<div class="tool-question-list">';
  for (const q of questions) {
    h += `<div class="tool-question-item"><div class="tool-agent-title">${esc(q.question || '')}</div>`;
    if (Array.isArray(q.options)) {
      h += '<div class="tool-chip-row">';
      for (const opt of q.options.slice(0, 4)) h += renderChip(opt.label || String(opt), 'warm');
      h += '</div>';
    }
    h += '</div>';
  }
  h += '</div>';
  return h;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function formatToolResult(toolName: string, content: string, input?: any): string | null {
  if (!content) return null;
  switch (toolName) {
    case 'Read': {
      const lines = content.split('\n');
      const fn = input?.file_path ? fileName(input.file_path) : 'file';
      let h = `<div class="tool-file-path"><span style="color:var(--text-secondary)">${esc(fn)}</span><span class="tool-mini-stat">${lines.length} lines</span></div>`;
      h += '<div class="tool-read-result">';
      for (let i = 0; i < lines.length; i++) {
        h += `<div class="tool-read-line"><span class="tool-grep-line-num">${i + 1}</span><span>${esc(lines[i])}</span></div>`;
      }
      h += '</div>';
      return h;
    }
    case 'Bash':
    case 'PowerShell':
    case 'Monitor':
    case 'BashCodeExecution':
    case 'CodeExecution':
    case 'TextEditorCodeExecution':
      return `<div class="tool-terminal-result" style="white-space:pre-wrap">${esc(content)}</div>`;
    case 'Edit':
      if (content.length < 80) return `<div class="tool-success-line">&#10003; ${esc(content)}</div>`;
      return null;
    case 'Grep': {
      const pat = input?.pattern || '';
      const lines = content.split('\n').filter(Boolean);
      if (!lines.length) return `<div class="tool-empty-line">No matches</div>`;
      let re: RegExp | null = null;
      try { re = new RegExp('(' + pat.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'); } catch { /* ignore */ }
      let h = '<div class="tool-grep-result">';
      let lastFile = '';
      for (const line of lines) {
        const m = line.match(/^([^:]+):(\d+):(.*)$/);
        if (m) {
          if (m[1] !== lastFile) { h += `<div class="tool-grep-file">${esc(m[1])}</div>`; lastFile = m[1]; }
          let dt = esc(m[3]);
          if (re) dt = dt.replace(re, '<span class="tool-grep-highlight">$1</span>');
          h += `<div class="tool-grep-match"><span class="tool-grep-line-num">${m[2]}</span>${dt}</div>`;
        } else {
          h += `<div class="tool-glob-item"><span style="opacity:0.5">&#128196;</span>${esc(line)}</div>`;
        }
      }
      h += '</div>';
      return h;
    }
    case 'Glob': {
      const files = content.split('\n').filter(Boolean);
      if (!files.length) return `<div class="tool-empty-line">No matches</div>`;
      const extIcons: Record<string, string> = { '.ts': '&#128311;', '.tsx': '&#128311;', '.js': '&#128311;', '.py': '&#128013;', '.md': '&#128203;', '.json': '&#128295;', '.yaml': '&#128295;', '.yml': '&#128295;', '.html': '&#127760;', '.css': '&#127912;', '.sh': '&#9654;' };
      let h = '<div class="tool-glob-list">';
      for (const f of files) {
        const name = fileName(f);
        const ext = name.includes('.') ? '.' + name.split('.').pop() : '';
        h += `<div class="tool-glob-item"><span style="font-size:10px">${extIcons[ext] || '&#128196;'}</span><span>${esc(f)}</span></div>`;
      }
      h += '</div>';
      return h;
    }
    case 'Agent':
    case 'Task':
      return `<div class="tool-agent-result"><div class="tool-success-line">&#10003; Agent completed</div><div class="tool-prompt-preview open">${esc(content)}</div></div>`;
    case 'TodoWrite':
      return `<div class="tool-success-line">&#10003; Tasks updated</div>`;
    case 'Write':
      return `<div class="tool-success-line">&#10003; ${esc(content)}</div>`;
    default:
      return null;
  }
}
