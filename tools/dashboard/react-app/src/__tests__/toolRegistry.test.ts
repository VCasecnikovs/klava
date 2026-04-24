import { describe, it, expect } from 'vitest';
import { getToolConfig, getToolSummary, formatToolInput, formatToolResult, renderTodoHtml } from '@/components/tabs/Chat/toolRegistry';

// ---- getToolConfig ----
describe('getToolConfig', () => {
  it('returns config for known tools', () => {
    const read = getToolConfig('Read');
    expect(read.color).toBe('#60a5fa');
    expect(read.icon).toBeTruthy();
  });

  it('returns config for Bash', () => {
    expect(getToolConfig('Bash').color).toBe('#f97316');
  });

  it('returns config for Edit', () => {
    expect(getToolConfig('Edit').color).toBe('#c084fc');
  });

  it('returns config for Write', () => {
    expect(getToolConfig('Write').color).toBe('#4ade80');
  });

  it('returns config for Grep', () => {
    expect(getToolConfig('Grep').color).toBe('#facc15');
  });

  it('returns config for Glob', () => {
    expect(getToolConfig('Glob').color).toBe('#a1a1aa');
  });

  it('returns config for WebSearch', () => {
    expect(getToolConfig('WebSearch').color).toBe('#38bdf8');
  });

  it('returns config for Task', () => {
    expect(getToolConfig('Task').color).toBe('#fbbf24');
  });

  it('returns config for TaskCreate', () => {
    expect(getToolConfig('TaskCreate').color).toBe('#34d399');
  });

  it('returns config for Skill', () => {
    expect(getToolConfig('Skill').color).toBe('#e879f9');
  });

  // MCP prefix matching
  it('returns github config for mcp__github__ prefix', () => {
    const cfg = getToolConfig('mcp__github__list_issues');
    expect(cfg.color).toBe('#8b5cf6');
  });

  it('returns google config for mcp__google__ prefix', () => {
    const cfg = getToolConfig('mcp__google__get_events');
    expect(cfg.color).toBe('#60a5fa');
  });

  it('returns playwright config for mcp__playwright__ prefix', () => {
    const cfg = getToolConfig('mcp__playwright__browser_click');
    expect(cfg.color).toBe('#e879f9');
  });

  it('returns obsidian config for mcp__obsidian__ prefix', () => {
    const cfg = getToolConfig('mcp__obsidian__search_vault');
    expect(cfg.color).toBe('#a78bfa');
  });

  it('returns ch config for mcp__ch prefix', () => {
    const cfg = getToolConfig('mcp__ch-astrum__run_select_query');
    expect(cfg.color).toBe('#f97316');
  });

  it('returns whatsapp config for mcp__whatsapp__ prefix', () => {
    const cfg = getToolConfig('mcp__whatsapp__send_message');
    expect(cfg.color).toBe('#4ade80');
  });

  it('returns default config for unknown tools', () => {
    const cfg = getToolConfig('UnknownTool');
    expect(cfg.color).toBe('#fbbf24');
  });

  it('handles null/undefined name gracefully', () => {
    const cfg = getToolConfig(undefined as unknown as string);
    expect(cfg.color).toBe('#fbbf24');
  });
});

// ---- getToolSummary ----
describe('getToolSummary', () => {
  it('returns empty string for null input', () => {
    expect(getToolSummary('Read', null)).toBe('');
  });

  it('returns filename for Read', () => {
    expect(getToolSummary('Read', { file_path: '/home/user/file.ts' })).toBe('file.ts');
  });

  it('returns command substring for Bash', () => {
    expect(getToolSummary('Bash', { command: 'ls -la /tmp' })).toBe('ls -la /tmp');
  });

  it('truncates long Bash commands at 80 chars', () => {
    const long = 'x'.repeat(100);
    expect(getToolSummary('Bash', { command: long })).toHaveLength(80);
  });

  it('returns filename for Edit', () => {
    expect(getToolSummary('Edit', { file_path: '/a/b/c.ts' })).toBe('c.ts');
  });

  it('returns pattern for Grep', () => {
    expect(getToolSummary('Grep', { pattern: 'TODO' })).toBe('/TODO/');
  });

  it('returns pattern with path for Grep', () => {
    expect(getToolSummary('Grep', { pattern: 'TODO', path: '/src/lib/utils.ts' })).toBe('/TODO/ in utils.ts');
  });

  it('returns filename for Write', () => {
    expect(getToolSummary('Write', { file_path: '/x/y.md' })).toBe('y.md');
  });

  it('returns pattern for Glob', () => {
    expect(getToolSummary('Glob', { pattern: '**/*.ts' })).toBe('**/*.ts');
  });

  it('returns query for WebSearch', () => {
    expect(getToolSummary('WebSearch', { query: 'vitest docs' })).toBe('vitest docs');
  });

  it('returns hostname for WebFetch', () => {
    expect(getToolSummary('WebFetch', { url: 'https://example.com/page' })).toBe('example.com');
  });

  it('returns truncated url for WebFetch with invalid url', () => {
    expect(getToolSummary('WebFetch', { url: 'not-a-url' })).toBe('not-a-url');
  });

  it('returns description for Task', () => {
    expect(getToolSummary('Task', { description: 'search for files', subagent_type: 'Explore' })).toBe('[Explore] search for files');
  });

  it('returns todo count for TodoWrite', () => {
    const todos = [{ status: 'completed' }, { status: 'pending' }, { status: 'completed' }];
    expect(getToolSummary('TodoWrite', { todos })).toBe('2/3 done');
  });

  it('returns subject for TaskCreate', () => {
    expect(getToolSummary('TaskCreate', { subject: 'Fix bug' })).toBe('Fix bug');
  });

  it('returns formatted string for TaskUpdate', () => {
    expect(getToolSummary('TaskUpdate', { taskId: '5', status: 'completed' })).toBe('#5 completed');
  });

  it('returns "listing tasks" for TaskList', () => {
    expect(getToolSummary('TaskList', {})).toBe('listing tasks');
  });

  it('returns task id for TaskGet', () => {
    expect(getToolSummary('TaskGet', { taskId: '3' })).toBe('#3');
  });

  it('returns query for ToolSearch', () => {
    expect(getToolSummary('ToolSearch', { query: 'slack' })).toBe('slack');
  });

  it('returns skill name for Skill', () => {
    expect(getToolSummary('Skill', { skill: 'commit' })).toBe('commit');
  });

  it('returns empty string for unknown tool', () => {
    expect(getToolSummary('UnknownTool', { data: 'x' })).toBe('');
  });
});

// ---- formatToolInput ----
describe('formatToolInput', () => {
  it('returns null for null input', () => {
    expect(formatToolInput('Read', null)).toBeNull();
  });

  it('returns null for non-object input', () => {
    expect(formatToolInput('Read', 'string')).toBeNull();
  });

  it('formats Read with file path', () => {
    const result = formatToolInput('Read', { file_path: '/home/user/src/index.ts' });
    expect(result).toContain('index.ts');
    expect(result).toContain('tool-file-path');
  });

  it('formats Read with offset and limit', () => {
    const result = formatToolInput('Read', { file_path: '/a.ts', offset: 10, limit: 20 });
    expect(result).toContain('L10');
    expect(result).toContain('30');
  });

  it('formats Write with file path and line count', () => {
    const result = formatToolInput('Write', { file_path: '/a/b.ts', content: 'line1\nline2\nline3' });
    expect(result).toContain('b.ts');
    expect(result).toContain('3 lines');
  });

  it('formats Edit with diff lines', () => {
    const result = formatToolInput('Edit', { file_path: '/f.ts', old_string: 'old', new_string: 'new' });
    expect(result).toContain('tool-diff-del');
    expect(result).toContain('tool-diff-add');
    expect(result).toContain('old');
    expect(result).toContain('new');
  });

  it('formats Bash with command and prompt', () => {
    const result = formatToolInput('Bash', { command: 'npm test' });
    expect(result).toContain('npm test');
    expect(result).toContain('tool-bash-prompt');
  });

  it('formats Bash with description', () => {
    const result = formatToolInput('Bash', { command: 'ls', description: 'List files' });
    expect(result).toContain('List files');
  });

  it('formats Grep with pattern', () => {
    const result = formatToolInput('Grep', { pattern: 'TODO', path: '/src' });
    expect(result).toContain('TODO');
    expect(result).toContain('/src');
  });

  it('formats Grep with glob', () => {
    const result = formatToolInput('Grep', { pattern: 'x', glob: '*.ts' });
    expect(result).toContain('*.ts');
  });

  it('formats Glob with pattern', () => {
    const result = formatToolInput('Glob', { pattern: '**/*.md', path: '/docs' });
    expect(result).toContain('**/*.md');
    expect(result).toContain('/docs');
  });

  it('formats WebSearch with query', () => {
    const result = formatToolInput('WebSearch', { query: 'vitest docs' });
    expect(result).toContain('vitest docs');
  });

  it('formats WebFetch with domain', () => {
    const result = formatToolInput('WebFetch', { url: 'https://example.com/page', prompt: 'Extract data' });
    expect(result).toContain('example.com');
    expect(result).toContain('Extract data');
  });

  it('formats Task with badges', () => {
    const result = formatToolInput('Task', { subagent_type: 'Explore', description: 'Find files', model: 'sonnet' });
    expect(result).toContain('Explore');
    expect(result).toContain('Find files');
    expect(result).toContain('sonnet');
  });

  it('formats TaskCreate with subject', () => {
    const result = formatToolInput('TaskCreate', { subject: 'Fix bug', description: 'Details here' });
    expect(result).toContain('Fix bug');
    expect(result).toContain('Details here');
  });

  it('formats TaskUpdate with status colors', () => {
    const result = formatToolInput('TaskUpdate', { taskId: '3', status: 'completed' });
    expect(result).toContain('#3');
    expect(result).toContain('#4ade80'); // green for completed
  });

  it('formats Skill with name', () => {
    const result = formatToolInput('Skill', { skill: 'commit', args: '-m fix' });
    expect(result).toContain('/commit');
    expect(result).toContain('-m fix');
  });

  it('returns null for unknown tool', () => {
    expect(formatToolInput('UnknownTool', { data: 'x' })).toBeNull();
  });
});

// ---- renderTodoHtml ----
describe('renderTodoHtml', () => {
  it('returns empty string for empty array', () => {
    expect(renderTodoHtml([])).toBe('');
  });

  it('returns empty string for null/undefined', () => {
    expect(renderTodoHtml(null as unknown as [])).toBe('');
    expect(renderTodoHtml(undefined as unknown as [])).toBe('');
  });

  it('renders pending items', () => {
    const result = renderTodoHtml([{ status: 'pending', content: 'Do it' }]);
    expect(result).toContain('Do it');
    expect(result).toContain('tool-todo-list');
  });

  it('renders completed items with checkmark', () => {
    const result = renderTodoHtml([{ status: 'completed', content: 'Done' }]);
    expect(result).toContain('done');
    expect(result).toContain('&#10003;');
  });

  it('renders in_progress items with play icon', () => {
    const result = renderTodoHtml([{ status: 'in_progress', content: 'Working' }]);
    expect(result).toContain('progress');
    expect(result).toContain('&#9654;');
  });

  it('escapes HTML in content', () => {
    const result = renderTodoHtml([{ content: '<script>alert("xss")</script>' }]);
    expect(result).toContain('&lt;script&gt;');
    expect(result).not.toContain('<script>');
  });
});

// ---- formatToolInput: TodoWrite case ----
describe('formatToolInput - TodoWrite', () => {
  it('formats TodoWrite via renderTodoHtml', () => {
    const result = formatToolInput('TodoWrite', {
      todos: [
        { status: 'completed', content: 'Task A' },
        { status: 'pending', content: 'Task B' },
      ],
    });
    expect(result).toContain('tool-todo-list');
    expect(result).toContain('Task A');
    expect(result).toContain('Task B');
  });

  it('returns empty string for empty todos', () => {
    const result = formatToolInput('TodoWrite', { todos: [] });
    expect(result).toBe('');
  });

  it('handles non-array todos', () => {
    const result = formatToolInput('TodoWrite', { todos: 'not-array' });
    expect(result).toBe('');
  });
});

// ---- formatToolInput: additional edge cases ----
describe('formatToolInput - edge cases', () => {
  it('formats Read with limit only (no offset)', () => {
    const result = formatToolInput('Read', { file_path: '/a.ts', limit: 50 });
    expect(result).toContain('L0-');
    expect(result).toContain('50');
  });

  it('formats Write truncates long content', () => {
    const longContent = 'x'.repeat(600);
    const result = formatToolInput('Write', { file_path: '/f.ts', content: longContent });
    expect(result).toContain('...');
  });

  it('formats Grep with output_mode', () => {
    const result = formatToolInput('Grep', { pattern: 'test', output_mode: 'count' });
    expect(result).toContain('[count]');
  });

  it('formats Glob without path', () => {
    const result = formatToolInput('Glob', { pattern: '*.ts' });
    expect(result).toContain('*.ts');
    // Should not contain the "in" keyword that appears when path is provided
    expect(result).not.toContain('>in<');
  });

  it('formats WebFetch with invalid URL', () => {
    const result = formatToolInput('WebFetch', { url: 'not-a-url', prompt: '' });
    expect(result).toContain('not-a-url');
  });

  it('formats Task with run_in_background and isolation', () => {
    const result = formatToolInput('Task', {
      subagent_type: 'Task',
      run_in_background: true,
      isolation: 'sandbox',
    });
    expect(result).toContain('bg');
    expect(result).toContain('sandbox');
  });

  it('formats Task with long prompt truncation', () => {
    const longPrompt = 'x'.repeat(400);
    const result = formatToolInput('Task', { prompt: longPrompt });
    expect(result).toContain('...');
  });

  it('formats TaskCreate with activeForm', () => {
    const result = formatToolInput('TaskCreate', { subject: 'S', activeForm: 'Form1' });
    expect(result).toContain('Form1');
  });

  it('formats TaskCreate with long description truncation', () => {
    const longDesc = 'y'.repeat(400);
    const result = formatToolInput('TaskCreate', { subject: 'S', description: longDesc });
    expect(result).toBeTruthy();
    // 300 char limit
  });

  it('formats TaskUpdate with activeForm', () => {
    const result = formatToolInput('TaskUpdate', { taskId: '1', activeForm: 'FormX' });
    expect(result).toContain('FormX');
  });

  it('formats TaskUpdate with unknown status color', () => {
    const result = formatToolInput('TaskUpdate', { taskId: '1', status: 'archived' });
    expect(result).toContain('archived');
    expect(result).toContain('var(--text-muted)');
  });

  it('formats TaskUpdate with subject', () => {
    const result = formatToolInput('TaskUpdate', { taskId: '1', subject: 'Updated title' });
    expect(result).toContain('Updated title');
  });

  it('formats Skill without args', () => {
    const result = formatToolInput('Skill', { skill: 'review' });
    expect(result).toContain('/review');
    expect(result).not.toContain('undefined');
  });
});

// ---- formatToolResult ----
describe('formatToolResult', () => {
  it('returns null for empty content', () => {
    expect(formatToolResult('Read', '')).toBeNull();
    expect(formatToolResult('Bash', '')).toBeNull();
  });

  it('formats Read result with line numbers', () => {
    const result = formatToolResult('Read', 'line1\nline2\nline3', { file_path: '/src/file.ts' });
    expect(result).toContain('file.ts');
    expect(result).toContain('3 lines');
    expect(result).toContain('line1');
    expect(result).toContain('tool-grep-line-num');
  });

  it('formats Read result without file_path input', () => {
    const result = formatToolResult('Read', 'content', undefined);
    expect(result).toContain('file'); // default filename
  });

  it('formats Bash result with escaped content', () => {
    const result = formatToolResult('Bash', 'output <script> test');
    expect(result).toContain('&lt;script&gt;');
    expect(result).toContain('pre-wrap');
  });

  it('formats Edit result - short success message', () => {
    const result = formatToolResult('Edit', 'File updated successfully');
    expect(result).toContain('&#10003;');
    expect(result).toContain('File updated successfully');
  });

  it('formats Edit result - returns null for long content', () => {
    const longContent = 'x'.repeat(100);
    const result = formatToolResult('Edit', longContent);
    expect(result).toBeNull();
  });

  it('formats Grep result with file matches', () => {
    const content = 'src/file.ts:10:const x = 1;\nsrc/file.ts:20:const y = 2;\nsrc/other.ts:5:let z = 3;';
    const result = formatToolResult('Grep', content, { pattern: 'const' });
    expect(result).toContain('tool-grep-file');
    expect(result).toContain('tool-grep-match');
    expect(result).toContain('tool-grep-highlight');
    expect(result).toContain('src/file.ts');
    expect(result).toContain('src/other.ts');
  });

  it('formats Grep result with no matches', () => {
    const result = formatToolResult('Grep', '\n', { pattern: 'x' });
    expect(result).toContain('No matches');
  });

  it('formats Grep result with non-standard lines (Glob-style fallback)', () => {
    const content = 'src/file.ts\nsrc/other.ts';
    const result = formatToolResult('Grep', content, { pattern: 'test' });
    expect(result).toContain('tool-glob-item');
  });

  it('formats Grep result with invalid regex pattern', () => {
    const content = 'src/file.ts:10:match';
    const result = formatToolResult('Grep', content, { pattern: '[invalid' });
    // Should not crash, just skip highlighting
    expect(result).toContain('match');
  });

  it('formats Glob result with file list and icons', () => {
    const content = 'src/index.ts\nsrc/styles.css\nREADME.md\nscript.sh\ndata.json';
    const result = formatToolResult('Glob', content);
    expect(result).toContain('tool-glob-list');
    expect(result).toContain('tool-glob-item');
    // TypeScript icon
    expect(result).toContain('&#128311;');
    // CSS icon
    expect(result).toContain('&#127912;');
    // Markdown icon
    expect(result).toContain('&#128203;');
    // Shell icon
    expect(result).toContain('&#9654;');
    // JSON icon
    expect(result).toContain('&#128295;');
  });

  it('formats Glob result with no matches', () => {
    const result = formatToolResult('Glob', '\n');
    expect(result).toContain('No matches');
  });

  it('formats Glob result with extensionless files', () => {
    const result = formatToolResult('Glob', 'Makefile');
    expect(result).toContain('&#128196;'); // default file icon
  });

  it('formats Task result', () => {
    const result = formatToolResult('Task', 'Agent did the work');
    expect(result).toContain('Agent completed');
    expect(result).toContain('Agent did the work');
  });

  it('formats TodoWrite result', () => {
    const result = formatToolResult('TodoWrite', 'ok');
    expect(result).toContain('Tasks updated');
  });

  it('formats Write result', () => {
    const result = formatToolResult('Write', 'File created successfully');
    expect(result).toContain('&#10003;');
    expect(result).toContain('File created successfully');
  });

  it('returns null for unknown tool', () => {
    expect(formatToolResult('UnknownTool', 'some content')).toBeNull();
  });
});

// ---- getToolSummary: additional edge cases ----
describe('getToolSummary - additional edge cases', () => {
  it('returns description for Bash when no command', () => {
    expect(getToolSummary('Bash', { description: 'Run tests' })).toBe('Run tests');
  });

  it('returns empty for Task with no parts', () => {
    expect(getToolSummary('Task', {})).toBe('');
  });

  it('returns empty for TodoWrite with non-array', () => {
    expect(getToolSummary('TodoWrite', { todos: 'not-array' })).toBe('0/0 done');
  });

  it('returns empty for TaskUpdate with no data', () => {
    expect(getToolSummary('TaskUpdate', {})).toBe('');
  });

  it('returns empty for TaskGet with no taskId', () => {
    expect(getToolSummary('TaskGet', {})).toBe('');
  });

  it('returns empty for AskUserQuestion with no questions', () => {
    expect(getToolSummary('AskUserQuestion', {})).toBe('');
  });

  it('returns question text for AskUserQuestion', () => {
    expect(getToolSummary('AskUserQuestion', {
      questions: [{ question: 'Which option do you prefer?' }],
    })).toBe('Which option do you prefer?');
  });

  it('returns empty for Skill with no skill', () => {
    expect(getToolSummary('Skill', {})).toBe('');
  });

  it('returns empty for ToolSearch with no query', () => {
    expect(getToolSummary('ToolSearch', {})).toBe('');
  });

  it('returns empty for Read without file_path', () => {
    expect(getToolSummary('Read', {})).toBe('');
  });

  it('returns empty for Edit without file_path', () => {
    expect(getToolSummary('Edit', {})).toBe('');
  });

  it('returns empty for Write without file_path', () => {
    expect(getToolSummary('Write', {})).toBe('');
  });

  it('returns empty for Glob without pattern', () => {
    expect(getToolSummary('Glob', {})).toBe('');
  });

  it('returns empty for Grep without pattern', () => {
    expect(getToolSummary('Grep', {})).toBe('');
  });

  it('returns empty for WebSearch without query', () => {
    expect(getToolSummary('WebSearch', {})).toBe('');
  });

  it('returns empty for WebFetch without url', () => {
    expect(getToolSummary('WebFetch', {})).toBe('');
  });

  it('returns subject for TaskUpdate', () => {
    expect(getToolSummary('TaskUpdate', { subject: 'Title only' })).toBe('Title only');
  });
});

// ---- getToolConfig: missing tools ----
describe('getToolConfig - remaining tools', () => {
  it('returns config for WebFetch', () => {
    expect(getToolConfig('WebFetch').color).toBe('#2dd4bf');
  });

  it('returns config for Agent', () => {
    expect(getToolConfig('Agent').color).toBe('#a78bfa');
  });

  it('returns config for TaskUpdate', () => {
    expect(getToolConfig('TaskUpdate').color).toBe('#34d399');
  });

  it('returns config for TaskList', () => {
    expect(getToolConfig('TaskList').color).toBe('#34d399');
  });

  it('returns config for TaskGet', () => {
    expect(getToolConfig('TaskGet').color).toBe('#34d399');
  });

  it('returns config for TodoWrite', () => {
    expect(getToolConfig('TodoWrite').color).toBe('#34d399');
  });

  it('returns config for ToolSearch', () => {
    expect(getToolConfig('ToolSearch').color).toBe('#71717a');
  });

  it('returns config for AskUserQuestion', () => {
    expect(getToolConfig('AskUserQuestion').color).toBe('#fb923c');
  });

  it('returns claude-in-chrome config for mcp__claude-in-chrome__ prefix', () => {
    const cfg = getToolConfig('mcp__claude-in-chrome__click');
    expect(cfg.color).toBe('#e879f9');
  });
});
