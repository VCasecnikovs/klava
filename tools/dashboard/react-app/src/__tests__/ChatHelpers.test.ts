/**
 * Tests for Chat helper functions: groupBlocks and extractTaskTools.
 * These are exported from Chat/index.tsx for testability.
 */
import { describe, it, expect, vi } from 'vitest';
import { groupBlocks, extractTaskTools } from '@/components/tabs/Chat/index';
import type { Block } from '@/context/ChatContext';

// Mock socket.io-client to prevent import errors from ChatContext
vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

// Mock the API client
vi.mock('@/api/client', () => ({
  api: {
    dashboard: vi.fn().mockResolvedValue({ skill_inventory: [] }),
    sessions: vi.fn().mockResolvedValue({ sessions: [] }),
    session: vi.fn().mockResolvedValue({ session_id: '', messages: [] }),
    chatState: vi.fn().mockResolvedValue({
      active_sessions: [],
      session_names: {},
      streaming_sessions: [],
      unread_sessions: [],
    }),
    chatStateName: vi.fn().mockResolvedValue({}),
    chatStateRead: vi.fn().mockResolvedValue({}),
    chatStateCancel: vi.fn().mockResolvedValue({}),
    uploadFile: vi.fn().mockResolvedValue({ files: [] }),
  },
}));

function block(overrides: Partial<Block> & { type: string }): Block {
  return { id: Math.floor(Math.random() * 10000), ...overrides } as Block;
}

describe('groupBlocks', () => {
  it('returns empty array for empty input', () => {
    expect(groupBlocks([])).toEqual([]);
  });

  it('groups a single assistant block as single', () => {
    const blocks = [block({ type: 'assistant', text: 'hello' })];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('single');
  });

  it('groups consecutive tool blocks into a tool_run', () => {
    const blocks = [
      block({ type: 'tool_use', tool: 'Read' }),
      block({ type: 'tool_result', content: 'result' }),
      block({ type: 'tool_use', tool: 'Grep' }),
      block({ type: 'tool_result', content: 'result2' }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('tool_run');
    if (result[0].type === 'tool_run') {
      expect(result[0].blocks).toHaveLength(4);
    }
  });

  it('groups consecutive thinking blocks into a thinking_group', () => {
    const blocks = [
      block({ type: 'thinking', text: 'thought 1' }),
      block({ type: 'thinking', text: 'thought 2' }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('thinking_group');
    if (result[0].type === 'thinking_group') {
      expect(result[0].blocks).toHaveLength(2);
    }
  });

  it('separates tool blocks from thinking blocks', () => {
    const blocks = [
      block({ type: 'tool_use', tool: 'Bash' }),
      block({ type: 'tool_result', content: 'ok' }),
      block({ type: 'thinking', text: 'hmm' }),
      block({ type: 'tool_use', tool: 'Read' }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(3);
    expect(result[0].type).toBe('tool_run');
    expect(result[1].type).toBe('thinking_group');
    expect(result[2].type).toBe('tool_run');
  });

  it('detects plan_review: plan(active:false) with content', () => {
    const blocks = [
      block({ type: 'plan', active: false, content: 'The plan is...' }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('plan_review');
  });

  it('detects legacy plan_review: assistant + plan(active:false)', () => {
    const assistantBlock = block({ type: 'assistant', text: 'Here is my plan' });
    const planBlock = block({ type: 'plan', active: false });
    const blocks = [assistantBlock, planBlock];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('plan_review');
    if (result[0].type === 'plan_review') {
      expect(result[0].assistantBlock).toBeDefined();
      expect(result[0].planBlock).toBeDefined();
    }
  });

  it('does NOT create plan_review for assistant + plan(active:true)', () => {
    const blocks = [
      block({ type: 'assistant', text: 'Starting plan mode' }),
      block({ type: 'plan', active: true }),
    ];
    const result = groupBlocks(blocks);
    // assistant is single, plan is single
    expect(result).toHaveLength(2);
    expect(result[0].type).toBe('single');
    expect(result[1].type).toBe('single');
  });

  it('handles tool_group blocks', () => {
    const blocks = [
      block({ type: 'tool_group', tools: [] }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('tool_run');
  });

  it('handles mixed sequence: user, tool, thinking, assistant, cost', () => {
    const blocks = [
      block({ type: 'user', text: 'hello' }),
      block({ type: 'tool_use', tool: 'Bash' }),
      block({ type: 'tool_result', content: 'ok' }),
      block({ type: 'thinking', text: 'let me think' }),
      block({ type: 'assistant', text: 'done' }),
      block({ type: 'cost', seconds: 5, cost: 0.01 }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(5);
    expect(result[0].type).toBe('single');       // user
    expect(result[1].type).toBe('tool_run');      // tool_use + tool_result
    expect(result[2].type).toBe('thinking_group');// thinking
    expect(result[3].type).toBe('single');        // assistant
    expect(result[4].type).toBe('single');        // cost
  });

  it('flushes trailing tool blocks', () => {
    const blocks = [
      block({ type: 'tool_use', tool: 'Read' }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('tool_run');
  });

  it('flushes trailing thinking blocks', () => {
    const blocks = [
      block({ type: 'thinking', text: 'pending' }),
    ];
    const result = groupBlocks(blocks);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('thinking_group');
  });
});

describe('extractTaskTools', () => {
  it('extracts TaskCreate from tool_use block', () => {
    const handler = vi.fn();
    const blocks = [
      block({ type: 'tool_use', tool: 'TaskCreate', input: { subject: 'Fix bug' } }),
    ];
    extractTaskTools(blocks, handler);
    expect(handler).toHaveBeenCalledWith('TaskCreate', { subject: 'Fix bug' });
  });

  it('extracts TaskUpdate from tool_use block', () => {
    const handler = vi.fn();
    const blocks = [
      block({ type: 'tool_use', tool: 'TaskUpdate', input: { taskId: '1', status: 'completed' } }),
    ];
    extractTaskTools(blocks, handler);
    expect(handler).toHaveBeenCalledWith('TaskUpdate', { taskId: '1', status: 'completed' });
  });

  it('extracts task tools from tool_group', () => {
    const handler = vi.fn();
    const blocks = [
      block({
        type: 'tool_group',
        tools: [
          { type: 'tool_use', id: 1, tool: 'TaskCreate', input: { subject: 'A' } },
          { type: 'tool_use', id: 2, tool: 'Bash', input: { command: 'ls' } },
          { type: 'tool_use', id: 3, tool: 'TaskUpdate', input: { taskId: '1', status: 'done' } },
        ] as Block[],
      }),
    ];
    extractTaskTools(blocks, handler);
    expect(handler).toHaveBeenCalledTimes(2);
    expect(handler).toHaveBeenCalledWith('TaskCreate', { subject: 'A' });
    expect(handler).toHaveBeenCalledWith('TaskUpdate', { taskId: '1', status: 'done' });
  });

  it('ignores non-task tool_use blocks', () => {
    const handler = vi.fn();
    const blocks = [
      block({ type: 'tool_use', tool: 'Bash', input: { command: 'ls' } }),
      block({ type: 'tool_use', tool: 'Read', input: { file_path: '/a.ts' } }),
    ];
    extractTaskTools(blocks, handler);
    expect(handler).not.toHaveBeenCalled();
  });

  it('ignores non-tool block types', () => {
    const handler = vi.fn();
    const blocks = [
      block({ type: 'assistant', text: 'hello' }),
      block({ type: 'user', text: 'hi' }),
      block({ type: 'thinking', text: 'hmm' }),
    ];
    extractTaskTools(blocks, handler);
    expect(handler).not.toHaveBeenCalled();
  });

  it('handles blocks with missing input gracefully', () => {
    const handler = vi.fn();
    const blocks = [
      block({ type: 'tool_use', tool: 'TaskCreate' }),
    ];
    extractTaskTools(blocks, handler);
    expect(handler).toHaveBeenCalledWith('TaskCreate', {});
  });
});
