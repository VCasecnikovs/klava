import { describe, it, expect, vi, beforeEach } from 'vitest';
import { chatReducer, INITIAL_STATE, useChatContext, ChatProvider } from '@/context/ChatContext';
import type { ChatState, ChatAction, Block, AttachedFile } from '@/context/ChatContext';
import { renderHook, act } from '@testing-library/react';
import React from 'react';

// Mock api client - chatReducer calls api.* for some actions
vi.mock('@/api/client', () => ({
  api: {
    chatStateName: vi.fn().mockReturnValue({ catch: vi.fn() }),
    chatStateRead: vi.fn().mockReturnValue({ catch: vi.fn() }),
  },
}));

// Mock socket.io-client for ChatProvider tests
const mockSocketHandlers: Record<string, Function> = {};
const mockSocket = {
  on: vi.fn((event: string, handler: Function) => { mockSocketHandlers[event] = handler; }),
  disconnect: vi.fn(),
  id: 'mock-socket-id',
  io: { engine: { transport: { name: 'polling' } } },
};
vi.mock('socket.io-client', () => ({
  io: vi.fn(() => mockSocket),
}));

function makeState(overrides: Partial<ChatState> = {}): ChatState {
  return {
    ...INITIAL_STATE,
    // INITIAL_STATE has Map and Set that are shared refs - create fresh ones
    streamingSessions: new Map(),
    unreadSessions: new Set(),
    ...overrides,
  };
}

// ---- Connection management ----
describe('connection management', () => {
  it('SET_CONNECTED sets socketConnected to true', () => {
    const state = makeState({ socketConnected: false });
    const result = chatReducer(state, { type: 'SET_CONNECTED', connected: true });
    expect(result.socketConnected).toBe(true);
  });

  it('SET_CONNECTED sets socketConnected to false', () => {
    const state = makeState({ socketConnected: true });
    const result = chatReducer(state, { type: 'SET_CONNECTED', connected: false });
    expect(result.socketConnected).toBe(false);
  });

  it('SET_WAS_CONNECTED updates wasConnected', () => {
    const result = chatReducer(makeState(), { type: 'SET_WAS_CONNECTED', value: true });
    expect(result.wasConnected).toBe(true);
  });

  it('INC_RECONNECT increments reconnectAttempts', () => {
    const state = makeState({ reconnectAttempts: 2 });
    const result = chatReducer(state, { type: 'INC_RECONNECT' });
    expect(result.reconnectAttempts).toBe(3);
  });

  it('RESET_RECONNECT resets reconnectAttempts to 0', () => {
    const state = makeState({ reconnectAttempts: 5 });
    const result = chatReducer(state, { type: 'RESET_RECONNECT' });
    expect(result.reconnectAttempts).toBe(0);
  });
});

// ---- Session identity ----
describe('session identity', () => {
  it('SET_TAB_ID updates tabId', () => {
    const result = chatReducer(makeState(), { type: 'SET_TAB_ID', tabId: 'tab-123' });
    expect(result.tabId).toBe('tab-123');
  });

  it('SET_TAB_ID can set null', () => {
    const state = makeState({ tabId: 'tab-123' });
    const result = chatReducer(state, { type: 'SET_TAB_ID', tabId: null });
    expect(result.tabId).toBeNull();
  });

  it('SET_CLAUDE_SESSION_ID updates claudeSessionId', () => {
    const result = chatReducer(makeState(), { type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: 'sess-456' });
    expect(result.claudeSessionId).toBe('sess-456');
  });

  it('UPDATE_SESSION_REAL_ID replaces tabId with realId in allSessions', () => {
    const state = makeState({
      allSessions: [{ id: 'tab-1', date: '', preview: '', messages: 0, is_active: true }],
      activeSessions: [{ tab_id: 'tab-1', session_id: null }],
    });
    const result = chatReducer(state, { type: 'UPDATE_SESSION_REAL_ID', tabId: 'tab-1', realId: 'real-uuid' });
    expect(result.allSessions[0].id).toBe('real-uuid');
    // activeSessions not touched - backend handles that
    expect(result.activeSessions).toEqual([{ tab_id: 'tab-1', session_id: null }]);
  });

  it('UPDATE_SESSION_REAL_ID removes tabId when realId already exists (no duplicate)', () => {
    const state = makeState({
      allSessions: [
        { id: 'tab-1', date: '', preview: '(streaming...)', messages: 1, is_active: true },
        { id: 'real-uuid', date: '2026-01-01', preview: 'real session', messages: 5, is_active: false },
      ],
    });
    const result = chatReducer(state, { type: 'UPDATE_SESSION_REAL_ID', tabId: 'tab-1', realId: 'real-uuid' });
    // tab-1 entry removed, real-uuid entry (with full data from API) kept
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].id).toBe('real-uuid');
    expect(result.allSessions[0].preview).toBe('real session');
  });
});

// ---- Session lists ----
describe('session lists', () => {
  it('SET_SESSIONS replaces allSessions', () => {
    const sessions = [{ id: 's1', date: '', preview: '', messages: 0, is_active: true }];
    const result = chatReducer(makeState(), { type: 'SET_SESSIONS', sessions });
    expect(result.allSessions).toEqual(sessions);
  });

  it('ADD_SESSION prepends to allSessions', () => {
    const state = makeState({
      allSessions: [{ id: 'existing', date: '', preview: '', messages: 0, is_active: true }],
    });
    const newSession = { id: 'new', date: '', preview: '', messages: 0, is_active: true };
    const result = chatReducer(state, { type: 'ADD_SESSION', session: newSession });
    expect(result.allSessions[0].id).toBe('new');
    expect(result.allSessions).toHaveLength(2);
  });
});

// ---- Realtime status ----
describe('realtime status', () => {
  it('SET_REALTIME_STATUS updates realtimeStatus', () => {
    const result = chatReducer(makeState(), { type: 'SET_REALTIME_STATUS', status: 'streaming' });
    expect(result.realtimeStatus).toBe('streaming');
  });

  it('SET_REALTIME_STATUS can set idle', () => {
    const state = makeState({ realtimeStatus: 'streaming' });
    const result = chatReducer(state, { type: 'SET_REALTIME_STATUS', status: 'idle' });
    expect(result.realtimeStatus).toBe('idle');
  });

  it('SET_REALTIME_STATUS can set ready', () => {
    const result = chatReducer(makeState(), { type: 'SET_REALTIME_STATUS', status: 'ready' });
    expect(result.realtimeStatus).toBe('ready');
  });

  it('SET_WATCHING updates watching flag', () => {
    const result = chatReducer(makeState(), { type: 'SET_WATCHING', watching: true });
    expect(result.watching).toBe(true);
  });

  it('SET_STREAM_START updates streamStart', () => {
    const result = chatReducer(makeState(), { type: 'SET_STREAM_START', time: 12345 });
    expect(result.streamStart).toBe(12345);
  });

  it('SET_BACKEND_QUEUE updates queue and preserves existing queueSessionId', () => {
    const state = makeState({ queueSessionId: 'existing' });
    const queue = [{ text: 'hello', index: 0 }];
    const result = chatReducer(state, { type: 'SET_BACKEND_QUEUE', queue });
    expect(result.backendQueue).toEqual(queue);
    expect(result.queueSessionId).toBe('existing');
  });

  it('SET_BACKEND_QUEUE can override queueSessionId', () => {
    const queue = [{ text: 'hello', index: 0 }];
    const result = chatReducer(makeState(), { type: 'SET_BACKEND_QUEUE', queue, sessionId: 'new-sid' });
    expect(result.queueSessionId).toBe('new-sid');
  });
});

// ---- Sidebar / UI ----
describe('sidebar and UI', () => {
  it('SET_SIDEBAR_FILTER changes sidebarFilter', () => {
    const result = chatReducer(makeState(), { type: 'SET_SIDEBAR_FILTER', filter: 'cron' });
    expect(result.sidebarFilter).toBe('cron');
  });

  it('SET_SESSION_NAME adds to sessionNames', () => {
    const result = chatReducer(makeState(), { type: 'SET_SESSION_NAME', sessionId: 's1', name: 'My Chat' });
    expect(result.sessionNames['s1']).toBe('My Chat');
  });

  it('RENAME_SESSION_KEY moves name from old to new key', () => {
    const state = makeState({ sessionNames: { old: 'Test Name' } });
    const result = chatReducer(state, { type: 'RENAME_SESSION_KEY', oldId: 'old', newId: 'new' });
    expect(result.sessionNames['new']).toBe('Test Name');
    expect(result.sessionNames['old']).toBeUndefined();
  });

  it('RENAME_SESSION_KEY is no-op if oldId not in names', () => {
    const state = makeState({ sessionNames: { other: 'X' } });
    const result = chatReducer(state, { type: 'RENAME_SESSION_KEY', oldId: 'missing', newId: 'new' });
    expect(result.sessionNames).toEqual({ other: 'X' });
  });
});

// ---- File attachments ----
describe('file attachments', () => {
  const file1: AttachedFile = { name: 'a.txt', path: '/a.txt', type: 'text/plain', size: 100 };
  const file2: AttachedFile = { name: 'b.png', path: '/b.png', type: 'image/png', size: 200, thumbUrl: 'blob:thumb' };

  it('SET_ATTACHED_FILES replaces files', () => {
    const result = chatReducer(makeState(), { type: 'SET_ATTACHED_FILES', files: [file1] });
    expect(result.attachedFiles).toEqual([file1]);
  });

  it('ADD_ATTACHED_FILE appends a file', () => {
    const state = makeState({ attachedFiles: [file1] });
    const result = chatReducer(state, { type: 'ADD_ATTACHED_FILE', file: file2 });
    expect(result.attachedFiles).toHaveLength(2);
    expect(result.attachedFiles[1]).toEqual(file2);
  });

  it('REMOVE_ATTACHED_FILE removes by index', () => {
    const state = makeState({ attachedFiles: [file1, file2] });
    const result = chatReducer(state, { type: 'REMOVE_ATTACHED_FILE', index: 0 });
    expect(result.attachedFiles).toHaveLength(1);
    expect(result.attachedFiles[0]).toEqual(file2);
  });

  it('CLEAR_ATTACHED_FILES empties the list', () => {
    const state = makeState({ attachedFiles: [file1, file2] });
    const result = chatReducer(state, { type: 'CLEAR_ATTACHED_FILES' });
    expect(result.attachedFiles).toEqual([]);
  });
});

// ---- Two-entity block management ----
describe('history blocks', () => {
  const block1: Block = { type: 'user', id: 1, text: 'hello' };
  const block2: Block = { type: 'assistant', id: 2, text: 'hi' };

  it('HISTORY_SNAPSHOT replaces all history blocks', () => {
    const result = chatReducer(makeState(), { type: 'HISTORY_SNAPSHOT', blocks: [block1, block2] });
    expect(result.historyBlocks).toEqual([block1, block2]);
  });

  it('HISTORY_BLOCK_ADD appends to history', () => {
    const state = makeState({ historyBlocks: [block1] });
    const result = chatReducer(state, { type: 'HISTORY_BLOCK_ADD', block: block2 });
    expect(result.historyBlocks).toHaveLength(2);
    expect(result.historyBlocks[1]).toEqual(block2);
  });

  it('HISTORY_BLOCK_ADD skips duplicates', () => {
    const state = makeState({ historyBlocks: [block1] });
    const result = chatReducer(state, { type: 'HISTORY_BLOCK_ADD', block: block1 });
    expect(result).toBe(state);
  });
});

describe('realtime blocks', () => {
  const block1: Block = { type: 'user', id: 0, text: 'hello' };
  const block2: Block = { type: 'assistant', id: 1, text: 'hi' };

  it('REALTIME_SNAPSHOT replaces all realtime blocks', () => {
    const result = chatReducer(makeState(), { type: 'REALTIME_SNAPSHOT', blocks: [block1, block2] });
    expect(result.realtimeBlocks).toEqual([block1, block2]);
  });

  it('REALTIME_BLOCK_ADD appends to realtime', () => {
    const state = makeState({ realtimeBlocks: [block1] });
    const result = chatReducer(state, { type: 'REALTIME_BLOCK_ADD', block: block2 });
    expect(result.realtimeBlocks).toHaveLength(2);
    expect(result.realtimeBlocks[1]).toEqual(block2);
  });

  it('REALTIME_BLOCK_ADD skips duplicates', () => {
    const state = makeState({ realtimeBlocks: [block1] });
    const result = chatReducer(state, { type: 'REALTIME_BLOCK_ADD', block: block1 });
    expect(result).toBe(state);
  });

  it('REALTIME_BLOCK_UPDATE patches an existing block by id', () => {
    const state = makeState({ realtimeBlocks: [block1, block2] });
    const result = chatReducer(state, { type: 'REALTIME_BLOCK_UPDATE', id: 1, patch: { text: 'updated' } });
    expect(result.realtimeBlocks[1].text).toBe('updated');
    expect(result.realtimeBlocks[0].text).toBe('hello');
  });

  it('REALTIME_BLOCK_UPDATE returns same state if id not found', () => {
    const state = makeState({ realtimeBlocks: [block1] });
    const result = chatReducer(state, { type: 'REALTIME_BLOCK_UPDATE', id: 999, patch: { text: 'x' } });
    expect(result).toBe(state);
  });

  it('REALTIME_BLOCK_ADD supports agent blocks with agent_blocks array', () => {
    const agentBlock: Block = {
      type: 'agent', id: 2, tool: 'Task', running: true,
      input: { description: 'Research', subagent_type: 'Explore' },
      agent_blocks: [],
    };
    const state = makeState({ realtimeBlocks: [block1] });
    const result = chatReducer(state, { type: 'REALTIME_BLOCK_ADD', block: agentBlock });
    expect(result.realtimeBlocks).toHaveLength(2);
    expect(result.realtimeBlocks[1].type).toBe('agent');
    expect(result.realtimeBlocks[1].agent_blocks).toEqual([]);
  });

  it('REALTIME_BLOCK_UPDATE patches agent_blocks on agent block', () => {
    const agentBlock: Block = {
      type: 'agent', id: 0, tool: 'Task', running: true,
      agent_blocks: [],
    };
    const state = makeState({ realtimeBlocks: [agentBlock] });
    const subBlocks: Block[] = [
      { type: 'tool_use', id: 100, tool: 'Bash', running: false },
      { type: 'assistant', id: 101, text: 'Result' },
    ];
    const result = chatReducer(state, {
      type: 'REALTIME_BLOCK_UPDATE', id: 0,
      patch: { agent_blocks: subBlocks },
    });
    expect(result.realtimeBlocks[0].agent_blocks).toHaveLength(2);
    expect(result.realtimeBlocks[0].agent_blocks![0].tool).toBe('Bash');
  });

  it('REALTIME_BLOCK_UPDATE marks agent as completed', () => {
    const agentBlock: Block = {
      type: 'agent', id: 0, tool: 'Task', running: true,
      agent_blocks: [{ type: 'assistant', id: 100, text: 'Done' }],
    };
    const state = makeState({ realtimeBlocks: [agentBlock] });
    const result = chatReducer(state, {
      type: 'REALTIME_BLOCK_UPDATE', id: 0,
      patch: { running: false, duration_ms: 5000 },
    });
    expect(result.realtimeBlocks[0].running).toBe(false);
    expect(result.realtimeBlocks[0].duration_ms).toBe(5000);
  });

  it('REALTIME_RESET clears realtime blocks', () => {
    const state = makeState({ realtimeBlocks: [block1, block2] });
    const result = chatReducer(state, { type: 'REALTIME_RESET' });
    expect(result.realtimeBlocks).toEqual([]);
  });

  it('REALTIME_RESET also resets realtimeStatus to idle and streamStart to null', () => {
    // Bug: switching sessions left realtimeStatus as 'streaming' and streamStart
    // pointing to session-start time, causing false "thinking 21m" timer.
    const state = makeState({ realtimeBlocks: [block1], realtimeStatus: 'streaming', streamStart: Date.now() - 60000 });
    const result = chatReducer(state, { type: 'REALTIME_RESET' });
    expect(result.realtimeStatus).toBe('idle');
    expect(result.streamStart).toBeNull();
  });

  it('REALTIME_RESET to idle does not break has_next flow (SET_REALTIME_STATUS follows)', () => {
    // onRealtimeDone calls REALTIME_RESET then SET_REALTIME_STATUS: streaming if has_next.
    // The explicit SET_REALTIME_STATUS must win over the reset.
    const state = makeState({ realtimeBlocks: [block1], realtimeStatus: 'streaming' });
    const afterReset = chatReducer(state, { type: 'REALTIME_RESET' });
    expect(afterReset.realtimeStatus).toBe('idle');
    const afterRestart = chatReducer(afterReset, { type: 'SET_REALTIME_STATUS', status: 'streaming' });
    expect(afterRestart.realtimeStatus).toBe('streaming');
  });
});

// ---- Chat state sync ----
describe('chat state sync', () => {
  it('CHAT_STATE_SYNC updates activeSessions, sessionNames, streamingSessions, unreadSessions', () => {
    const result = chatReducer(makeState(), {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: null, session_id: 's1' }],
      sessionNames: { s1: 'Test' },
      streamingSessions: [{ id: 's2', elapsed: 10, last_event: null }],
      unreadSessions: ['s3'],
    });
    expect(result.activeSessions).toEqual([{ tab_id: null, session_id: 's1' }]);
    expect(result.sessionNames).toEqual({ s1: 'Test' });
    expect(result.streamingSessions.get('s2')).toBeTruthy();
    expect(result.unreadSessions.has('s3')).toBe(true);
  });

  it('CHAT_STATE_SYNC removes current session from unread', () => {
    const state = makeState({ claudeSessionId: 'current' });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: ['current', 'other'],
    });
    expect(result.unreadSessions.has('current')).toBe(false);
    expect(result.unreadSessions.has('other')).toBe(true);
  });
});

// ---- Todos ----
describe('todos', () => {
  it('SET_TODOS replaces todos array', () => {
    const todos = [{ status: 'pending', content: 'Do stuff' }];
    const result = chatReducer(makeState(), { type: 'SET_TODOS', todos });
    expect(result.todos).toEqual(todos);
  });

  it('TOGGLE_TODOS_COLLAPSED flips todosCollapsed', () => {
    const state = makeState({ todosCollapsed: false });
    const result = chatReducer(state, { type: 'TOGGLE_TODOS_COLLAPSED' });
    expect(result.todosCollapsed).toBe(true);
    const result2 = chatReducer(result, { type: 'TOGGLE_TODOS_COLLAPSED' });
    expect(result2.todosCollapsed).toBe(false);
  });
});

// ---- Tool tracking ----
describe('tool tracking', () => {
  it('SET_LAST_TOOL updates lastToolName', () => {
    const result = chatReducer(makeState(), { type: 'SET_LAST_TOOL', name: 'Bash', input: { cmd: 'ls' }, startTime: 100 });
    expect(result.lastToolName).toBe('Bash');
    expect(result.lastToolInput).toEqual({ cmd: 'ls' });
    expect(result.lastToolStartTime).toBe(100);
  });

  it('SET_LAST_TOOL with null clears tool info', () => {
    const state = makeState({ lastToolName: 'Read', lastToolInput: {}, lastToolStartTime: 50 });
    const result = chatReducer(state, { type: 'SET_LAST_TOOL', name: null });
    expect(result.lastToolName).toBeNull();
    expect(result.lastToolInput).toBeNull();
    expect(result.lastToolStartTime).toBe(0);
  });

  it('SET_MODEL updates model', () => {
    const result = chatReducer(makeState(), { type: 'SET_MODEL', model: 'sonnet' });
    expect(result.model).toBe('sonnet');
  });

  it('SET_PENDING_PERMISSION updates pendingPermission', () => {
    const perm = { tool: 'Bash', description: 'Run command' };
    const result = chatReducer(makeState(), { type: 'SET_PENDING_PERMISSION', permission: perm });
    expect(result.pendingPermission).toEqual(perm);
  });

  it('SET_PENDING_PERMISSION can set null', () => {
    const state = makeState({ pendingPermission: { tool: 'X', description: 'Y' } });
    const result = chatReducer(state, { type: 'SET_PENDING_PERMISSION', permission: null });
    expect(result.pendingPermission).toBeNull();
  });
});

// ---- SET_BACKEND_QUEUE edge cases ----
describe('SET_BACKEND_QUEUE edge cases', () => {
  it('empty queue deletes session from sessionQueues', () => {
    const state = makeState({
      queueSessionId: 'sid-1',
      sessionQueues: { 'sid-1': [{ text: 'hi', index: 0 }] },
      backendQueue: [{ text: 'hi', index: 0 }],
    });
    const result = chatReducer(state, { type: 'SET_BACKEND_QUEUE', queue: [] });
    expect(result.backendQueue).toEqual([]);
    expect(result.sessionQueues['sid-1']).toBeUndefined();
  });

  it('when sid is null (no sessionId, no queueSessionId), sessionQueues unchanged', () => {
    const state = makeState({ queueSessionId: null, sessionQueues: {} });
    const queue = [{ text: 'msg', index: 0 }];
    const result = chatReducer(state, { type: 'SET_BACKEND_QUEUE', queue });
    expect(result.backendQueue).toEqual(queue);
    expect(result.queueSessionId).toBeNull();
    expect(result.sessionQueues).toEqual({});
  });

  it('sessionId in action adds queue to sessionQueues', () => {
    const state = makeState({ sessionQueues: {} });
    const queue = [{ text: 'msg', index: 0 }];
    const result = chatReducer(state, { type: 'SET_BACKEND_QUEUE', queue, sessionId: 'new-sid' });
    expect(result.sessionQueues['new-sid']).toEqual(queue);
  });
});

// ---- REMOVE_ATTACHED_FILE / CLEAR_ATTACHED_FILES edge cases ----
describe('file attachment URL revocation', () => {
  it('REMOVE_ATTACHED_FILE calls revokeObjectURL when thumbUrl exists', () => {
    const revokeSpy = vi.fn();
    globalThis.URL.revokeObjectURL = revokeSpy;
    const fileWithThumb: AttachedFile = { name: 'img.png', path: '/img.png', type: 'image/png', size: 100, thumbUrl: 'blob:thumb-1' };
    const state = makeState({ attachedFiles: [fileWithThumb] });
    chatReducer(state, { type: 'REMOVE_ATTACHED_FILE', index: 0 });
    expect(revokeSpy).toHaveBeenCalledWith('blob:thumb-1');
  });

  it('REMOVE_ATTACHED_FILE does NOT call revokeObjectURL when no thumbUrl', () => {
    const revokeSpy = vi.fn();
    globalThis.URL.revokeObjectURL = revokeSpy;
    const fileNoThumb: AttachedFile = { name: 'a.txt', path: '/a.txt', type: 'text/plain', size: 50 };
    const state = makeState({ attachedFiles: [fileNoThumb] });
    chatReducer(state, { type: 'REMOVE_ATTACHED_FILE', index: 0 });
    expect(revokeSpy).not.toHaveBeenCalled();
  });

  it('CLEAR_ATTACHED_FILES revokes only files with thumbUrl', () => {
    const revokeSpy = vi.fn();
    globalThis.URL.revokeObjectURL = revokeSpy;
    const f1: AttachedFile = { name: 'a.txt', path: '/a', type: 'text/plain', size: 10 };
    const f2: AttachedFile = { name: 'b.png', path: '/b', type: 'image/png', size: 20, thumbUrl: 'blob:t1' };
    const f3: AttachedFile = { name: 'c.png', path: '/c', type: 'image/png', size: 30, thumbUrl: 'blob:t2' };
    const state = makeState({ attachedFiles: [f1, f2, f3] });
    chatReducer(state, { type: 'CLEAR_ATTACHED_FILES' });
    expect(revokeSpy).toHaveBeenCalledTimes(2);
    expect(revokeSpy).toHaveBeenCalledWith('blob:t1');
    expect(revokeSpy).toHaveBeenCalledWith('blob:t2');
  });
});

// ---- CHAT_STATE_SYNC synthetic entries ----
describe('CHAT_STATE_SYNC synthetic entries', () => {
  it('creates synthetic session for active entry not in allSessions', () => {
    const state = makeState({ allSessions: [] });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: null, session_id: 'new-sess' }],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
    });
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].id).toBe('new-sess');
    expect(result.allSessions[0].preview).toBe('(loading...)');
    expect(result.allSessions[0].is_active).toBe(true);
  });

  it('creates synthetic session with streaming preview when active entry is streaming', () => {
    const state = makeState({ allSessions: [] });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: null, session_id: 'stream-sess' }],
      sessionNames: {},
      streamingSessions: [{ id: 'stream-sess', elapsed: 5, last_event: null }],
      unreadSessions: [],
    });
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].preview).toBe('(streaming...)');
  });

  it('creates synthetic session for streaming session not in active and not in allSessions', () => {
    const state = makeState({ allSessions: [] });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [],
      sessionNames: {},
      streamingSessions: [{ id: 'orphan-stream', elapsed: 10, last_event: null }],
      unreadSessions: [],
    });
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].id).toBe('orphan-stream');
    expect(result.allSessions[0].preview).toBe('(streaming...)');
  });

  it('does not create duplicate synthetic entries', () => {
    const existing = [{ id: 'existing', date: '2026-01-01', preview: 'hi', messages: 5, is_active: true }];
    const state = makeState({ allSessions: existing });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: null, session_id: 'existing' }],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
    });
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].preview).toBe('hi');
  });

  it('uses tab_id for synthetic entry when session_id is null', () => {
    const state = makeState({ allSessions: [] });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: 'tab-abc', session_id: null }],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
    });
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].id).toBe('tab-abc');
  });

  it('does not create synthetic if tab_id matches existing allSessions entry', () => {
    const existing = [{ id: 'tab-abc', date: '', preview: 'temp', messages: 0, is_active: true }];
    const state = makeState({ allSessions: existing });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: 'tab-abc', session_id: null }],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
    });
    expect(result.allSessions).toHaveLength(1);
  });

  it('does not create synthetic if session_id matches existing allSessions entry via session_id', () => {
    const existing = [{ id: 'real-uuid', date: '', preview: 'exists', messages: 3, is_active: true }];
    const state = makeState({ allSessions: existing });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [{ tab_id: 'tab-xyz', session_id: 'real-uuid' }],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
    });
    // session_id matches existing, no synthetic needed
    expect(result.allSessions).toHaveLength(1);
    expect(result.allSessions[0].preview).toBe('exists');
  });

  it('handles drafts parameter in CHAT_STATE_SYNC', () => {
    const state = makeState({ drafts: { old: 'text' } });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
      drafts: { s1: 'draft text' },
    });
    expect(result.drafts).toEqual({ s1: 'draft text' });
  });

  it('preserves existing drafts when drafts is undefined in CHAT_STATE_SYNC', () => {
    const state = makeState({ drafts: { s1: 'keep me' } });
    const result = chatReducer(state, {
      type: 'CHAT_STATE_SYNC',
      activeSessions: [],
      sessionNames: {},
      streamingSessions: [],
      unreadSessions: [],
    });
    expect(result.drafts).toEqual({ s1: 'keep me' });
  });
});

// ---- UPDATE_SESSION_REAL_ID localStorage ----
describe('UPDATE_SESSION_REAL_ID localStorage migration', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('migrates per-session settings from tabId to realId in localStorage', () => {
    localStorage.setItem('chat_session_settings', JSON.stringify({ 'tab-1': { model: 'opus' } }));
    const state = makeState({
      allSessions: [{ id: 'tab-1', date: '', preview: '', messages: 0, is_active: true }],
    });
    chatReducer(state, { type: 'UPDATE_SESSION_REAL_ID', tabId: 'tab-1', realId: 'real-uuid' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored['real-uuid']).toEqual({ model: 'opus' });
    expect(stored['tab-1']).toBeUndefined();
  });

  it('does nothing to localStorage when tabId not in settings', () => {
    localStorage.setItem('chat_session_settings', JSON.stringify({ other: { model: 'haiku' } }));
    const state = makeState({
      allSessions: [{ id: 'tab-1', date: '', preview: '', messages: 0, is_active: true }],
    });
    chatReducer(state, { type: 'UPDATE_SESSION_REAL_ID', tabId: 'tab-1', realId: 'real-uuid' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored).toEqual({ other: { model: 'haiku' } });
  });

  it('handles missing chat_session_settings gracefully', () => {
    const state = makeState({
      allSessions: [{ id: 'tab-1', date: '', preview: '', messages: 0, is_active: true }],
    });
    // Should not throw
    const result = chatReducer(state, { type: 'UPDATE_SESSION_REAL_ID', tabId: 'tab-1', realId: 'real-uuid' });
    expect(result.allSessions[0].id).toBe('real-uuid');
  });

  it('only renames matching tabId entry when multiple sessions exist', () => {
    const state = makeState({
      allSessions: [
        { id: 'other-sess', date: '2026-01-01', preview: 'other', messages: 2, is_active: true },
        { id: 'tab-1', date: '', preview: '', messages: 0, is_active: true },
        { id: 'another', date: '2026-01-02', preview: 'another', messages: 3, is_active: false },
      ],
    });
    const result = chatReducer(state, { type: 'UPDATE_SESSION_REAL_ID', tabId: 'tab-1', realId: 'real-uuid' });
    expect(result.allSessions).toHaveLength(3);
    expect(result.allSessions[0].id).toBe('other-sess');
    expect(result.allSessions[1].id).toBe('real-uuid');
    expect(result.allSessions[2].id).toBe('another');
  });
});

// ---- SET_MODEL / SET_EFFORT localStorage ----
describe('SET_MODEL localStorage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('saves per-session model when claudeSessionId exists', () => {
    const state = makeState({ claudeSessionId: 'sess-1', tabId: null });
    chatReducer(state, { type: 'SET_MODEL', model: 'haiku' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored['sess-1'].model).toBe('haiku');
  });

  it('saves per-session model using tabId when claudeSessionId is null', () => {
    const state = makeState({ claudeSessionId: null, tabId: 'tab-1' });
    chatReducer(state, { type: 'SET_MODEL', model: 'sonnet' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored['tab-1'].model).toBe('sonnet');
  });

  it('saves global default when no session active', () => {
    const state = makeState({ claudeSessionId: null, tabId: null });
    chatReducer(state, { type: 'SET_MODEL', model: 'opus' });
    expect(localStorage.getItem('chat_model')).toBe('opus');
  });

  it('merges with existing per-session settings', () => {
    localStorage.setItem('chat_session_settings', JSON.stringify({ 'sess-1': { effort: 'low' } }));
    const state = makeState({ claudeSessionId: 'sess-1' });
    chatReducer(state, { type: 'SET_MODEL', model: 'haiku' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored['sess-1']).toEqual({ effort: 'low', model: 'haiku' });
  });
});

describe('SET_EFFORT localStorage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('saves per-session effort when claudeSessionId exists', () => {
    const state = makeState({ claudeSessionId: 'sess-1' });
    chatReducer(state, { type: 'SET_EFFORT', effort: 'low' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored['sess-1'].effort).toBe('low');
  });

  it('saves per-session effort using tabId when claudeSessionId is null', () => {
    const state = makeState({ claudeSessionId: null, tabId: 'tab-2' });
    chatReducer(state, { type: 'SET_EFFORT', effort: 'medium' });
    const stored = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
    expect(stored['tab-2'].effort).toBe('medium');
  });

  it('saves global default when no session', () => {
    const state = makeState({ claudeSessionId: null, tabId: null });
    chatReducer(state, { type: 'SET_EFFORT', effort: 'low' });
    expect(localStorage.getItem('chat_effort')).toBe('low');
  });

  it('updates effort state', () => {
    const state = makeState({ effort: 'high' });
    const result = chatReducer(state, { type: 'SET_EFFORT', effort: 'low' });
    expect(result.effort).toBe('low');
  });
});

// ---- Permission and session mode ----
describe('permission and session mode', () => {
  it('SET_PERMISSION_MODE updates permissionMode', () => {
    const result = chatReducer(makeState(), { type: 'SET_PERMISSION_MODE', mode: 'accept_all' });
    expect(result.permissionMode).toBe('accept_all');
  });

  it('SET_PERMISSION_MODE can set deny_all', () => {
    const result = chatReducer(makeState(), { type: 'SET_PERMISSION_MODE', mode: 'deny_all' });
    expect(result.permissionMode).toBe('deny_all');
  });

  it('SET_SESSION_MODE updates sessionMode', () => {
    const result = chatReducer(makeState(), { type: 'SET_SESSION_MODE', mode: 'plan' });
    expect(result.sessionMode).toBe('plan');
  });

  it('SET_SESSION_MODE can set bypass', () => {
    const state = makeState({ sessionMode: 'plan' });
    const result = chatReducer(state, { type: 'SET_SESSION_MODE', mode: 'bypass' });
    expect(result.sessionMode).toBe('bypass');
  });
});

// ---- Artifacts ----
describe('artifacts', () => {
  it('OPEN_ARTIFACT sets activeArtifact with filename and title', () => {
    const result = chatReducer(makeState(), { type: 'OPEN_ARTIFACT', filename: 'report.html', title: 'Report' });
    expect(result.activeArtifact).toEqual({ filename: 'report.html', path: undefined, title: 'Report' });
  });

  it('OPEN_ARTIFACT sets activeArtifact with path', () => {
    const result = chatReducer(makeState(), { type: 'OPEN_ARTIFACT', filename: 'report.html', title: 'Report', path: '/views/report.html' });
    expect(result.activeArtifact).toEqual({ filename: 'report.html', path: '/views/report.html', title: 'Report' });
  });

  it('CLOSE_ARTIFACT sets activeArtifact to null', () => {
    const state = makeState({ activeArtifact: { filename: 'x.html', title: 'X' } });
    const result = chatReducer(state, { type: 'CLOSE_ARTIFACT' });
    expect(result.activeArtifact).toBeNull();
  });

  it('ADD_ARTIFACT appends to sessionArtifacts', () => {
    const artifact = { filename: 'a.html', title: 'A' };
    const result = chatReducer(makeState(), { type: 'ADD_ARTIFACT', artifact });
    expect(result.sessionArtifacts).toHaveLength(1);
    expect(result.sessionArtifacts[0]).toEqual(artifact);
  });

  it('ADD_ARTIFACT skips duplicate by filename', () => {
    const artifact = { filename: 'a.html', title: 'A' };
    const state = makeState({ sessionArtifacts: [artifact] });
    const result = chatReducer(state, { type: 'ADD_ARTIFACT', artifact });
    expect(result).toBe(state);
  });

  it('ADD_ARTIFACT allows different filenames', () => {
    const a1 = { filename: 'a.html', title: 'A' };
    const a2 = { filename: 'b.html', title: 'B' };
    const state = makeState({ sessionArtifacts: [a1] });
    const result = chatReducer(state, { type: 'ADD_ARTIFACT', artifact: a2 });
    expect(result.sessionArtifacts).toHaveLength(2);
  });

  it('RESET_ARTIFACTS clears both activeArtifact and sessionArtifacts', () => {
    const state = makeState({
      activeArtifact: { filename: 'x.html', title: 'X' },
      sessionArtifacts: [{ filename: 'x.html', title: 'X' }],
    });
    const result = chatReducer(state, { type: 'RESET_ARTIFACTS' });
    expect(result.activeArtifact).toBeNull();
    expect(result.sessionArtifacts).toEqual([]);
  });
});

// ---- Drafts ----
describe('drafts', () => {
  it('SET_DRAFTS replaces all drafts', () => {
    const state = makeState({ drafts: { old: 'text' } });
    const result = chatReducer(state, { type: 'SET_DRAFTS', drafts: { s1: 'new' } });
    expect(result.drafts).toEqual({ s1: 'new' });
  });

  it('SET_DRAFT adds a draft for a session', () => {
    const state = makeState({ drafts: {} });
    const result = chatReducer(state, { type: 'SET_DRAFT', sessionId: 's1', text: 'hello world' });
    expect(result.drafts['s1']).toBe('hello world');
  });

  it('SET_DRAFT with empty text deletes the draft', () => {
    const state = makeState({ drafts: { s1: 'some text' } });
    const result = chatReducer(state, { type: 'SET_DRAFT', sessionId: 's1', text: '' });
    expect(result.drafts['s1']).toBeUndefined();
  });

  it('SET_DRAFT preserves other drafts', () => {
    const state = makeState({ drafts: { s1: 'first', s2: 'second' } });
    const result = chatReducer(state, { type: 'SET_DRAFT', sessionId: 's1', text: 'updated' });
    expect(result.drafts).toEqual({ s1: 'updated', s2: 'second' });
  });
});

// ---- Default case ----
describe('default', () => {
  it('returns state unchanged for unknown action type', () => {
    const state = makeState();
    // @ts-expect-error - testing unknown action
    const result = chatReducer(state, { type: 'UNKNOWN_ACTION' });
    expect(result).toBe(state);
  });
});

// ---- useChatContext hook ----
describe('useChatContext', () => {
  it('throws when used outside ChatProvider', () => {
    expect(() => {
      renderHook(() => useChatContext());
    }).toThrow('useChatContext must be used within ChatProvider');
  });

  it('returns context value when used inside ChatProvider', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    expect(result.current.state).toBeDefined();
    expect(result.current.dispatch).toBeDefined();
    expect(result.current.socketRef).toBeDefined();
    expect(result.current.messagesRef).toBeDefined();
    expect(result.current.streamingTextRef).toBeDefined();
    expect(result.current.sendMessageRef).toBeDefined();
  });
});

// ---- ChatProvider ----
describe('ChatProvider', () => {
  beforeEach(() => {
    // Reset socket handler registry
    Object.keys(mockSocketHandlers).forEach(k => delete mockSocketHandlers[k]);
    vi.clearAllMocks();
  });

  it('registers socket event handlers on mount', () => {
    renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    expect(mockSocket.on).toHaveBeenCalledWith('connect', expect.any(Function));
    expect(mockSocket.on).toHaveBeenCalledWith('disconnect', expect.any(Function));
    expect(mockSocket.on).toHaveBeenCalledWith('connect_error', expect.any(Function));
    expect(mockSocket.on).toHaveBeenCalledWith('chat_state_sync', expect.any(Function));
    expect(mockSocket.on).toHaveBeenCalledWith('draft_update', expect.any(Function));
    expect(mockSocket.on).toHaveBeenCalledWith('queue_update', expect.any(Function));
  });

  it('dispatches SET_CONNECTED true on socket connect', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    act(() => { mockSocketHandlers['connect'](); });
    expect(result.current.state.socketConnected).toBe(true);
    expect(result.current.state.reconnectAttempts).toBe(0);
  });

  it('dispatches SET_CONNECTED false and INC_RECONNECT on disconnect', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    // First connect
    act(() => { mockSocketHandlers['connect'](); });
    // Then disconnect
    act(() => { mockSocketHandlers['disconnect']('io server disconnect'); });
    expect(result.current.state.socketConnected).toBe(false);
    expect(result.current.state.reconnectAttempts).toBe(1);
  });

  it('handles connect_error without crashing', () => {
    renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    // Should not throw
    expect(() => {
      act(() => { mockSocketHandlers['connect_error'](new Error('test error')); });
    }).not.toThrow();
  });

  it('handles chat_state_sync event', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    act(() => {
      mockSocketHandlers['chat_state_sync']({
        active_sessions: [{ tab_id: 't1', session_id: null }],
        session_names: { t1: 'Test' },
        streaming_sessions: [],
        unread_sessions: [],
      });
    });
    expect(result.current.state.activeSessions).toEqual([{ tab_id: 't1', session_id: null }]);
    expect(result.current.state.sessionNames).toEqual({ t1: 'Test' });
  });

  it('handles chat_state_sync with missing fields', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    act(() => {
      mockSocketHandlers['chat_state_sync']({});
    });
    expect(result.current.state.activeSessions).toEqual([]);
    expect(result.current.state.sessionNames).toEqual({});
  });

  it('handles draft_update event', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    act(() => {
      mockSocketHandlers['draft_update']({ session_id: 'sess-1', text: 'draft content' });
    });
    expect(result.current.state.drafts['sess-1']).toBe('draft content');
  });

  it('handles queue_update event', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    act(() => {
      mockSocketHandlers['queue_update']({
        queue: [{ text: 'queued msg', index: 0 }],
        tab_id: 'tab-q',
      });
    });
    expect(result.current.state.backendQueue).toEqual([{ text: 'queued msg', index: 0 }]);
  });

  it('handles queue_update with missing fields', () => {
    const { result } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    act(() => {
      mockSocketHandlers['queue_update']({});
    });
    expect(result.current.state.backendQueue).toEqual([]);
  });

  it('disconnects socket on unmount', () => {
    const { unmount } = renderHook(() => useChatContext(), {
      wrapper: ({ children }) => React.createElement(ChatProvider, null, children),
    });
    unmount();
    expect(mockSocket.disconnect).toHaveBeenCalled();
  });
});
