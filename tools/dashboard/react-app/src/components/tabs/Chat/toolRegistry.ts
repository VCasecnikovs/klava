import { esc } from '@/lib/utils';

// --- Tool Registry: icons, colors, per-tool formatters ---

interface ToolConfig {
  icon: string;
  color: string;
  dim: string;
  border: string;
}

const TOOL_REGISTRY: Record<string, ToolConfig> = {
  Read: { icon: '&#128196;', color: '#60a5fa', dim: 'rgba(96,165,250,0.08)', border: 'rgba(96,165,250,0.15)' },
  Write: { icon: '&#9999;', color: '#4ade80', dim: 'rgba(74,222,128,0.08)', border: 'rgba(74,222,128,0.15)' },
  Edit: { icon: '&#8596;', color: '#c084fc', dim: 'rgba(192,132,252,0.08)', border: 'rgba(192,132,252,0.15)' },
  Bash: { icon: '&#9654;', color: '#f97316', dim: 'rgba(249,115,22,0.08)', border: 'rgba(249,115,22,0.15)' },
  Grep: { icon: '&#128269;', color: '#facc15', dim: 'rgba(250,204,21,0.08)', border: 'rgba(250,204,21,0.15)' },
  Glob: { icon: '&#128193;', color: '#a1a1aa', dim: 'rgba(161,161,170,0.08)', border: 'rgba(161,161,170,0.15)' },
  WebSearch: { icon: '&#127760;', color: '#38bdf8', dim: 'rgba(56,189,248,0.08)', border: 'rgba(56,189,248,0.15)' },
  WebFetch: { icon: '&#128279;', color: '#2dd4bf', dim: 'rgba(45,212,191,0.08)', border: 'rgba(45,212,191,0.15)' },
  Agent: { icon: '&#129302;', color: '#a78bfa', dim: 'rgba(167,139,250,0.08)', border: 'rgba(167,139,250,0.15)' },
  Task: { icon: '&#129302;', color: '#fbbf24', dim: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.15)' },
  TaskCreate: { icon: '&#10133;', color: '#34d399', dim: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.15)' },
  TaskUpdate: { icon: '&#9745;', color: '#34d399', dim: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.15)' },
  TaskList: { icon: '&#128203;', color: '#34d399', dim: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.15)' },
  TaskGet: { icon: '&#128203;', color: '#34d399', dim: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.15)' },
  TodoWrite: { icon: '&#9745;', color: '#34d399', dim: 'rgba(52,211,153,0.08)', border: 'rgba(52,211,153,0.15)' },
  ToolSearch: { icon: '&#128268;', color: '#71717a', dim: 'rgba(113,113,122,0.08)', border: 'rgba(113,113,122,0.15)' },
  AskUserQuestion: { icon: '&#10067;', color: '#fb923c', dim: 'rgba(251,146,60,0.08)', border: 'rgba(251,146,60,0.15)' },
  Skill: { icon: '&#9889;', color: '#e879f9', dim: 'rgba(232,121,249,0.08)', border: 'rgba(232,121,249,0.15)' },
  _default: { icon: '&#9881;', color: '#fbbf24', dim: 'rgba(251,191,36,0.04)', border: 'rgba(251,191,36,0.12)' },
};

export function getToolConfig(name: string): ToolConfig {
  if (TOOL_REGISTRY[name]) return TOOL_REGISTRY[name];
  if (name?.startsWith('mcp__github__')) return { icon: '&#128025;', color: '#8b5cf6', dim: 'rgba(139,92,246,0.08)', border: 'rgba(139,92,246,0.15)' };
  if (name?.startsWith('mcp__google__')) return { icon: '&#128231;', color: '#60a5fa', dim: 'rgba(96,165,250,0.08)', border: 'rgba(96,165,250,0.15)' };
  if (name?.startsWith('mcp__playwright__') || name?.startsWith('mcp__claude-in-chrome__')) return { icon: '&#127916;', color: '#e879f9', dim: 'rgba(232,121,249,0.08)', border: 'rgba(232,121,249,0.15)' };
  if (name?.startsWith('mcp__obsidian__')) return { icon: '&#128218;', color: '#a78bfa', dim: 'rgba(167,139,250,0.08)', border: 'rgba(167,139,250,0.15)' };
  if (name?.startsWith('mcp__ch')) return { icon: '&#128202;', color: '#f97316', dim: 'rgba(249,115,22,0.08)', border: 'rgba(249,115,22,0.15)' };
  if (name?.startsWith('mcp__whatsapp__')) return { icon: '&#128172;', color: '#4ade80', dim: 'rgba(74,222,128,0.08)', border: 'rgba(74,222,128,0.15)' };
  return TOOL_REGISTRY._default;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getToolSummary(tool: string, input: any): string {
  if (!input) return '';
  if (tool === 'Read' && input.file_path) return input.file_path.split('/').pop() || '';
  if (tool === 'Bash') return (input.description || input.command || '').substring(0, 80);
  if (tool === 'Edit' && input.file_path) return input.file_path.split('/').pop() || '';
  if (tool === 'Grep' && input.pattern) return `/${input.pattern}/` + (input.path ? ' in ' + input.path.split('/').pop() : '');
  if (tool === 'Write' && input.file_path) return input.file_path.split('/').pop() || '';
  if (tool === 'Glob' && input.pattern) return input.pattern;
  if (tool === 'WebSearch' && input.query) return input.query;
  if (tool === 'WebFetch' && input.url) {
    try { return new URL(input.url).hostname; } catch { return input.url.substring(0, 40); }
  }
  if (tool === 'Task') {
    const parts: string[] = [];
    if (input.subagent_type) parts.push(`[${input.subagent_type}]`);
    if (input.description) parts.push(input.description);
    return parts.join(' ') || '';
  }
  if (tool === 'TodoWrite') {
    const t = Array.isArray(input.todos) ? input.todos : [];
    const d = t.filter((x: { status: string }) => x.status === 'completed').length;
    return `${d}/${t.length} done`;
  }
  if (tool === 'TaskCreate') return input.subject || '';
  if (tool === 'TaskUpdate') {
    const parts: string[] = [];
    if (input.taskId) parts.push(`#${input.taskId}`);
    if (input.status) parts.push(input.status);
    if (input.subject) parts.push(input.subject);
    return parts.join(' ') || '';
  }
  if (tool === 'TaskList') return 'listing tasks';
  if (tool === 'TaskGet') return input.taskId ? `#${input.taskId}` : '';
  if (tool === 'ToolSearch') return input.query || '';
  if (tool === 'AskUserQuestion') return (input.questions || [])[0]?.question?.substring(0, 60) || '';
  if (tool === 'Skill') return input.skill || '';
  return '';
}

// --- Per-tool formatInput ---
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function formatToolInput(toolName: string, input: any): string | null {
  if (!input || typeof input !== 'object') return null;
  switch (toolName) {
    case 'Read': {
      const p = input.file_path || '';
      const fn = p.split('/').pop() || '';
      const dir = p.substring(0, p.length - fn.length);
      let info = '';
      if (input.offset) info += 'L' + input.offset;
      if (input.limit) info += (info ? '-' : 'L0-') + ((input.offset || 0) + input.limit);
      return `<div class="tool-file-path"><span style="opacity:0.6">&#128196;</span><span style="color:var(--text-muted)">${esc(dir)}</span><span style="color:var(--text)">${esc(fn)}</span>${info ? `<span style="margin-left:auto;color:var(--text-muted);font-size:10px">${esc(info)}</span>` : ''}</div>`;
    }
    case 'Write': {
      const p = input.file_path || '';
      const fn = p.split('/').pop() || '';
      const dir = p.substring(0, p.length - fn.length);
      const c = input.content || '';
      const lines = c.split('\n').length;
      return `<div class="tool-file-path"><span style="opacity:0.6">&#9999;</span><span style="color:var(--text-muted)">${esc(dir)}</span><span style="color:#4ade80">${esc(fn)}</span><span style="margin-left:auto;color:var(--text-muted);font-size:10px">${lines} lines</span></div><pre style="margin:0;padding:6px 12px;font-size:11px;max-height:150px;overflow-y:auto;color:var(--text-muted);white-space:pre-wrap">${esc(c.substring(0, 500))}${c.length > 500 ? '...' : ''}</pre>`;
    }
    case 'Edit': {
      const p = input.file_path || '';
      const old_s = input.old_string || '';
      const new_s = input.new_string || '';
      let h = `<div class="tool-diff-header">${esc(p)}</div>`;
      for (const line of old_s.split('\n')) h += `<div class="tool-diff-line tool-diff-del">- ${esc(line)}</div>`;
      for (const line of new_s.split('\n')) h += `<div class="tool-diff-line tool-diff-add">+ ${esc(line)}</div>`;
      return h;
    }
    case 'Bash': {
      const cmd = input.command || '';
      const desc = input.description || '';
      let h = '';
      if (desc) h += `<div style="padding:6px 12px;font-size:12px;color:var(--text)">${esc(desc)}</div>`;
      h += `<div class="tool-bash-cmd"><span class="tool-bash-prompt">$</span><span style="white-space:pre-wrap;word-break:break-all;${desc ? 'font-size:10px;color:var(--text-muted)' : ''}">${esc(cmd)}</span></div>`;
      return h;
    }
    case 'Grep': {
      let h = `<div style="padding:6px 12px;font-family:var(--mono);font-size:11px">`;
      h += `<span style="color:var(--yellow)">/${esc(input.pattern || '')}/</span>`;
      if (input.path) h += ` <span style="color:var(--text-muted)">in</span> <span style="color:var(--text-secondary)">${esc(input.path)}</span>`;
      if (input.glob) h += ` <span style="color:var(--text-muted)">glob:</span><span style="color:var(--text-secondary)">${esc(input.glob)}</span>`;
      if (input.output_mode) h += ` <span style="color:var(--text-muted)">[${esc(input.output_mode)}]</span>`;
      h += `</div>`;
      return h;
    }
    case 'Glob': {
      let h = `<div style="padding:6px 12px;font-family:var(--mono);font-size:11px">`;
      h += `<span style="color:var(--text-secondary)">${esc(input.pattern || '')}</span>`;
      if (input.path) h += ` <span style="color:var(--text-muted)">in</span> <span style="color:var(--text-secondary)">${esc(input.path)}</span>`;
      h += `</div>`;
      return h;
    }
    case 'WebSearch':
      return `<div style="padding:6px 12px;font-size:12px"><span style="color:var(--text)">"${esc(input.query || '')}"</span></div>`;
    case 'WebFetch': {
      let domain = '';
      try { domain = new URL(input.url || '').hostname; } catch { domain = input.url || ''; }
      return `<div style="padding:6px 12px;font-size:11px"><span style="color:var(--blue)">${esc(domain)}</span><div style="color:var(--text-muted);font-size:10px;margin-top:2px">${esc((input.prompt || '').substring(0, 100))}</div></div>`;
    }
    case 'Task': {
      const badges: string[] = [];
      if (input.subagent_type) badges.push(`<span style="font-size:9px;padding:1px 6px;border-radius:4px;background:rgba(167,139,250,0.12);color:#a78bfa">${esc(input.subagent_type)}</span>`);
      if (input.model) badges.push(`<span style="font-size:9px;padding:1px 6px;border-radius:4px;background:rgba(251,191,36,0.12);color:#fbbf24">${esc(input.model)}</span>`);
      if (input.run_in_background) badges.push(`<span style="font-size:9px;padding:1px 6px;border-radius:4px;background:rgba(74,222,128,0.12);color:#4ade80">bg</span>`);
      if (input.isolation) badges.push(`<span style="font-size:9px;padding:1px 6px;border-radius:4px;background:rgba(249,115,22,0.12);color:#f97316">${esc(input.isolation)}</span>`);
      const desc = input.description || '';
      const prompt = input.prompt || '';
      const promptPreview = prompt.length > 300 ? prompt.substring(0, 300) + '...' : prompt;
      let h = `<div style="padding:8px 12px">`;
      h += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">${badges.join('')}</div>`;
      if (desc) h += `<div style="color:var(--text);font-size:12px;font-weight:500;margin-bottom:4px">${esc(desc)}</div>`;
      if (promptPreview) h += `<div style="color:var(--text-muted);font-size:11px;line-height:1.4;white-space:pre-wrap;max-height:120px;overflow-y:auto">${esc(promptPreview)}</div>`;
      h += `<div class="chat-task-timer" style="color:var(--text-muted);font-size:10px;margin-top:6px"></div>`;
      h += `</div>`;
      return h;
    }
    case 'TaskCreate': {
      let h = `<div style="padding:6px 12px">`;
      if (input.subject) h += `<div style="color:var(--text);font-size:12px;font-weight:500">${esc(input.subject)}</div>`;
      if (input.activeForm) h += `<div style="color:var(--text-muted);font-size:10px;margin-top:2px">Active: ${esc(input.activeForm)}</div>`;
      if (input.description) h += `<div style="color:var(--text-muted);font-size:11px;margin-top:4px;line-height:1.4;max-height:80px;overflow-y:auto">${esc(input.description.substring(0, 300))}</div>`;
      h += `</div>`;
      return h;
    }
    case 'TaskUpdate': {
      const parts: string[] = [];
      if (input.taskId) parts.push(`Task #${input.taskId}`);
      if (input.status) {
        const statusColors: Record<string, string> = { in_progress: '#fbbf24', completed: '#4ade80', pending: '#a1a1aa', deleted: '#ef4444' };
        const col = statusColors[input.status] || 'var(--text-muted)';
        parts.push(`<span style="color:${col}">${esc(input.status)}</span>`);
      }
      let h = `<div style="padding:6px 12px">`;
      if (parts.length) h += `<div style="font-size:12px">${parts.join(' → ')}</div>`;
      if (input.subject) h += `<div style="color:var(--text);font-size:11px;margin-top:2px">${esc(input.subject)}</div>`;
      if (input.activeForm) h += `<div style="color:var(--text-muted);font-size:10px;margin-top:2px">Active: ${esc(input.activeForm)}</div>`;
      h += `</div>`;
      return h;
    }
    case 'TodoWrite':
      return renderTodoHtml(Array.isArray(input.todos) ? input.todos : []);
    case 'Skill':
      return `<div style="padding:6px 12px;font-size:12px"><span style="color:#e879f9">/${esc(input.skill || '')}</span>${input.args ? ` <span style="color:var(--text-muted)">${esc(input.args)}</span>` : ''}</div>`;
    default:
      return null;
  }
}

interface TodoItem {
  status?: string;
  content?: string;
}

export function renderTodoHtml(todos: TodoItem[]): string {
  if (!todos || !todos.length) return '';
  let h = '<div class="tool-todo-list">';
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

// --- Per-tool formatResult ---
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function formatToolResult(toolName: string, content: string, input?: any): string | null {
  if (!content) return null;
  switch (toolName) {
    case 'Read': {
      const lines = content.split('\n');
      const fn = input?.file_path ? input.file_path.split('/').pop() : 'file';
      let h = `<div class="tool-file-path"><span style="color:var(--text-secondary)">${esc(fn)}</span><span style="margin-left:auto;color:var(--text-muted);font-size:10px">${lines.length} lines</span></div>`;
      h += '<div style="padding:4px 0;overflow-y:auto">';
      for (let i = 0; i < lines.length; i++) {
        h += `<div style="display:flex;font-family:var(--mono);font-size:11px;line-height:1.5"><span class="tool-grep-line-num">${i + 1}</span><span style="color:var(--text-muted);white-space:pre-wrap">${esc(lines[i])}</span></div>`;
      }
      h += '</div>';
      return h;
    }
    case 'Bash': {
      let h = '<div style="background:rgba(0,0,0,0.3);padding:6px 12px;overflow-y:auto;font-family:var(--mono);font-size:11px;color:var(--text-muted);white-space:pre-wrap;line-height:1.5">';
      h += esc(content);
      h += '</div>';
      return h;
    }
    case 'Edit': {
      if (content.length < 80) return `<div style="padding:6px 12px;color:var(--green);font-size:11px">&#10003; ${esc(content)}</div>`;
      return null;
    }
    case 'Grep': {
      const pat = input?.pattern || '';
      const lines = content.split('\n').filter(Boolean);
      if (!lines.length) return `<div style="padding:6px 12px;color:var(--text-muted);font-size:11px">No matches</div>`;
      let re: RegExp | null = null;
      try { re = new RegExp('(' + pat.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'); } catch { /* ignore */ }
      let h = '<div style="overflow-y:auto">';
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
      if (!files.length) return `<div style="padding:6px 12px;color:var(--text-muted);font-size:11px">No matches</div>`;
      const extIcons: Record<string, string> = { '.ts': '&#128311;', '.tsx': '&#128311;', '.js': '&#128311;', '.py': '&#128013;', '.md': '&#128203;', '.json': '&#128295;', '.yaml': '&#128295;', '.yml': '&#128295;', '.html': '&#127760;', '.css': '&#127912;', '.sh': '&#9654;' };
      let h = '<div class="tool-glob-list">';
      for (const f of files) {
        const name = f.split('/').pop() || '';
        const ext = name.includes('.') ? '.' + name.split('.').pop() : '';
        h += `<div class="tool-glob-item"><span style="font-size:10px">${extIcons[ext] || '&#128196;'}</span><span>${esc(f)}</span></div>`;
      }
      h += '</div>';
      return h;
    }
    case 'Task': {
      // Agent result - show the response nicely
      let h = '<div style="padding:8px 12px;overflow-y:auto">';
      h += `<div style="color:var(--green);font-size:10px;margin-bottom:4px">&#10003; Agent completed</div>`;
      h += `<div style="color:var(--text-muted);font-size:11px;line-height:1.5;white-space:pre-wrap">${esc(content)}</div>`;
      h += '</div>';
      return h;
    }
    case 'TodoWrite':
      return `<div style="padding:6px 12px;color:var(--green);font-size:11px">&#10003; Tasks updated</div>`;
    case 'Write':
      return `<div style="padding:6px 12px;color:var(--green);font-size:11px">&#10003; ${esc(content)}</div>`;
    default:
      return null;
  }
}
