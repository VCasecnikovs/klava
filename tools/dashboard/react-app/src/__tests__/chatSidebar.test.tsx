/**
 * Tests for Chat sub-components:
 * - ChatSidebar (session list, filters, search, agents, rename, fork)
 * - ChangesPanel (diff display, filters, todos, extract changes)
 * - QuotePopover (text selection popover)
 * - ArtifactViewer (iframe artifact display)
 * - ArtifactSidebar (artifact list)
 */
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import type { ChatState } from '@/context/ChatContext';
import type { Session, Agent } from '@/api/types';
import type { StreamingSession } from '@/api/client';

// ---- Hoisted mocks (accessible in vi.mock factories) ----

const { mockApi, mockAgentsRef, mockStateRef, mockDispatchRef, mockSocketRefObj, mockSendMessageRefObj } = vi.hoisted(() => {
  const mockApi = {
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
    sessionsSearch: vi.fn().mockResolvedValue({ sessions: [] }),
    sessionFork: vi.fn().mockResolvedValue({ session_id: 'fork-123', source_id: 'src', name: 'Fork', messages: 5 }),
    agents: vi.fn().mockResolvedValue({ agents: [] }),
    agentKill: vi.fn().mockResolvedValue({}),
    chatSendHttp: vi.fn().mockResolvedValue({}),
  };

  const mockAgentsRef = { current: [] as Agent[] };
  const mockStateRef = { current: null as ChatState | null };
  const mockDispatchRef = { current: vi.fn() };
  const mockSocketRefObj = { current: { on: vi.fn(), off: vi.fn(), emit: vi.fn() } as { on: ReturnType<typeof vi.fn>; off: ReturnType<typeof vi.fn>; emit: ReturnType<typeof vi.fn> } | null };
  const mockSendMessageRefObj = { current: vi.fn() as ((text: string) => void) | null };

  return { mockApi, mockAgentsRef, mockStateRef, mockDispatchRef, mockSocketRefObj, mockSendMessageRefObj };
});

vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

vi.mock('@/api/client', () => ({
  api: mockApi,
}));

vi.mock('@/api/queries', () => ({
  useAgents: () => ({
    data: { agents: mockAgentsRef.current },
    isLoading: false,
    error: null,
  }),
}));

vi.mock('@/context/ChatContext', () => ({
  useChatContext: () => ({
    state: mockStateRef.current,
    dispatch: mockDispatchRef.current,
    socketRef: { current: mockSocketRefObj.current },
    messagesRef: { current: null },
    streamingTextRef: { current: null },
    sendMessageRef: { current: mockSendMessageRefObj.current },
  }),
}));

// Import components AFTER mocks are set up
import { ChatSidebar } from '@/components/tabs/Chat/ChatSidebar';
import { ChangesPanel, extractChanges } from '@/components/tabs/Chat/ChangesPanel';
import { QuotePopover } from '@/components/tabs/Chat/QuotePopover';
import { ArtifactViewer } from '@/components/tabs/Chat/artifacts/ArtifactViewer';
import { ArtifactSidebar } from '@/components/tabs/Chat/artifacts/ArtifactSidebar';
import type { Block } from '@/context/ChatContext';

// ---- Test Helpers ----

function createMockState(overrides: Partial<ChatState> = {}): ChatState {
  return {
    socketConnected: true,
    tabId: null,
    claudeSessionId: null,
    watching: false,
    allSessions: [],
    activeSessions: [],
    sessionNames: {},
    backendQueue: [],
    queueSessionId: null,
    sessionQueues: {},
    streamStart: null,
    sidebarFilter: 'active' as const,
    wasConnected: true,
    reconnectAttempts: 0,
    attachedFiles: [],
    lastToolName: null,
    lastToolInput: null,
    lastToolStartTime: 0,
    streamingSessions: new Map<string, StreamingSession>(),
    unreadSessions: new Set<string>(),
    todos: [],
    todosCollapsed: false,
    historyBlocks: [],
    realtimeBlocks: [],
    realtimeStatus: 'idle' as const,
    model: 'opus',
    effort: 'high',
    pendingPermission: null,
    permissionMode: 'ask' as const,
    sessionMode: 'bypass' as const,
    activeArtifact: null,
    sessionArtifacts: [],
    drafts: {},
    ...overrides,
  };
}

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithQuery(ui: React.ReactElement) {
  const qc = createQueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// ---- Setup ----

beforeEach(() => {
  mockAgentsRef.current = [];
  mockDispatchRef.current = vi.fn();
  mockSocketRefObj.current = { on: vi.fn(), off: vi.fn(), emit: vi.fn() };
  mockSendMessageRefObj.current = vi.fn();
  mockStateRef.current = createMockState();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// =====================================================
// ChatSidebar Tests
// =====================================================

describe('ChatSidebar', () => {
  const onResumeSession = vi.fn();
  const onNewSession = vi.fn();

  function renderSidebar(stateOverrides: Partial<ChatState> = {}) {
    mockStateRef.current = createMockState(stateOverrides);
    return renderWithQuery(
      <ChatSidebar onResumeSession={onResumeSession} onNewSession={onNewSession} />
    );
  }

  beforeEach(() => {
    onResumeSession.mockReset();
    onNewSession.mockReset();
  });

  describe('Filter bar', () => {
    test('renders all four filter buttons', () => {
      renderSidebar();
      const btns = document.querySelectorAll('.chat-filter-btn');
      expect(btns).toHaveLength(4);
      const labels = Array.from(btns).map(b => b.textContent);
      expect(labels).toEqual(['Active', 'All', 'Human', 'Cron']);
    });

    test('active filter is selected by default', () => {
      renderSidebar();
      const activeBtn = document.querySelector('.chat-filter-btn.active');
      expect(activeBtn).toBeTruthy();
      expect(activeBtn!.textContent).toBe('Active');
    });

    test('clicking a filter button dispatches SET_SIDEBAR_FILTER', () => {
      renderSidebar();
      const allBtn = Array.from(document.querySelectorAll('.chat-filter-btn')).find(b => b.textContent === 'All')!;
      fireEvent.click(allBtn);
      expect(mockDispatchRef.current).toHaveBeenCalledWith({ type: 'SET_SIDEBAR_FILTER', filter: 'all' });
    });

    test('clicking Human filter dispatches correct action', () => {
      renderSidebar();
      const humanBtn = Array.from(document.querySelectorAll('.chat-filter-btn')).find(b => b.textContent === 'Human')!;
      fireEvent.click(humanBtn);
      expect(mockDispatchRef.current).toHaveBeenCalledWith({ type: 'SET_SIDEBAR_FILTER', filter: 'human' });
    });

    test('clicking Cron filter dispatches correct action', () => {
      renderSidebar();
      const cronBtn = Array.from(document.querySelectorAll('.chat-filter-btn')).find(b => b.textContent === 'Cron')!;
      fireEvent.click(cronBtn);
      expect(mockDispatchRef.current).toHaveBeenCalledWith({ type: 'SET_SIDEBAR_FILTER', filter: 'cron' });
    });
  });

  describe('Search', () => {
    test('search input renders with placeholder', () => {
      renderSidebar();
      const input = document.querySelector('input[placeholder="Search sessions..."]') as HTMLInputElement;
      expect(input).toBeTruthy();
    });

    test('typing in search updates the input value', () => {
      renderSidebar();
      const input = document.querySelector('input[placeholder="Search sessions..."]') as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'hello' } });
      expect(input.value).toBe('hello');
    });

    test('search with 2+ chars triggers API call after debounce', async () => {
      renderSidebar();
      const input = document.querySelector('input[placeholder="Search sessions..."]') as HTMLInputElement;

      mockApi.sessionsSearch.mockResolvedValue({
        sessions: [
          { id: 'search-1', date: '2026-03-01', preview: 'Found session', messages: 2, is_active: false },
        ],
      });

      await act(async () => {
        fireEvent.change(input, { target: { value: 'he' } });
      });

      // Advance timers past debounce (300ms)
      await act(async () => {
        vi.advanceTimersByTime(400);
      });

      // Wait for the API promise to resolve
      await act(async () => {
        await vi.runAllTimersAsync();
      });

      expect(mockApi.sessionsSearch).toHaveBeenCalledWith('he');
    });

    test('search with < 2 chars does not trigger API call', async () => {
      mockApi.sessionsSearch.mockClear();
      renderSidebar();
      const input = document.querySelector('input[placeholder="Search sessions..."]') as HTMLInputElement;

      await act(async () => {
        fireEvent.change(input, { target: { value: 'h' } });
      });

      await act(async () => {
        vi.advanceTimersByTime(400);
      });

      expect(mockApi.sessionsSearch).not.toHaveBeenCalled();
    });

    test('search input focus changes border color', () => {
      renderSidebar();
      const input = document.querySelector('input[placeholder="Search sessions..."]') as HTMLInputElement;
      fireEvent.focus(input);
      expect(input.style.borderColor).toBe('var(--blue)');
    });

    test('search input blur restores border color', () => {
      renderSidebar();
      const input = document.querySelector('input[placeholder="Search sessions..."]') as HTMLInputElement;
      fireEvent.focus(input);
      fireEvent.blur(input);
      expect(input.style.borderColor).toBe('var(--border)');
    });
  });

  describe('Empty states', () => {
    test('shows empty message for active filter with no sessions', () => {
      renderSidebar({ sidebarFilter: 'active', allSessions: [], activeSessions: [] });
      const empty = document.querySelector('.chat-sidebar-empty');
      expect(empty).toBeTruthy();
      expect(empty!.textContent).toContain('No active chats');
    });

    test('shows "No sessions found" for non-active filters with no sessions', () => {
      renderSidebar({ sidebarFilter: 'all', allSessions: [] });
      const empty = document.querySelector('.chat-sidebar-empty');
      expect(empty).toBeTruthy();
      expect(empty!.textContent).toContain('No sessions found');
    });
  });

  describe('Session list', () => {
    const sessions: Session[] = [
      { id: 'sess-1', date: new Date().toISOString(), preview: 'First chat', messages: 5, is_active: true },
      { id: 'sess-2', date: new Date().toISOString(), preview: 'Second chat', messages: 3, is_active: false },
      { id: 'sess-3', date: new Date().toISOString(), preview: '[heartbeat] Check-in', messages: 1, is_active: false },
    ];

    test('renders sessions in "all" filter', () => {
      renderSidebar({ sidebarFilter: 'all', allSessions: sessions });
      const items = document.querySelectorAll('.chat-sidebar-item');
      expect(items).toHaveLength(3);
    });

    test('human filter only shows human sessions', () => {
      renderSidebar({ sidebarFilter: 'human', allSessions: sessions });
      const items = document.querySelectorAll('.chat-sidebar-item');
      expect(items).toHaveLength(2);
    });

    test('cron filter only shows cron sessions', () => {
      renderSidebar({ sidebarFilter: 'cron', allSessions: sessions });
      const items = document.querySelectorAll('.chat-sidebar-item');
      expect(items).toHaveLength(1);
    });

    test('active filter shows only active sessions', () => {
      renderSidebar({
        sidebarFilter: 'active',
        allSessions: sessions,
        activeSessions: [{ tab_id: null, session_id: 'sess-1' }],
      });
      const items = document.querySelectorAll('.chat-sidebar-item');
      expect(items).toHaveLength(1);
    });

    test('clicking a session calls onResumeSession', () => {
      renderSidebar({ sidebarFilter: 'all', allSessions: sessions });
      const items = document.querySelectorAll('.chat-sidebar-item');
      fireEvent.click(items[0]);
      expect(onResumeSession).toHaveBeenCalledWith('sess-1');
    });

    test('current session has active class', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: sessions,
        claudeSessionId: 'sess-2',
      });
      const items = document.querySelectorAll('.chat-sidebar-item');
      expect(items[1].classList.contains('active')).toBe(true);
      expect(items[0].classList.contains('active')).toBe(false);
    });

    test('session displays custom name from sessionNames', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: sessions,
        sessionNames: { 'sess-1': 'My Custom Name' },
      });
      const title = document.querySelector('.chat-sidebar-item-title');
      expect(title!.textContent).toContain('My Custom Name');
    });

    test('session without custom name shows preview', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-x', date: new Date().toISOString(), preview: 'Original preview', messages: 1, is_active: false }],
      });
      const title = document.querySelector('.chat-sidebar-item-title');
      expect(title!.textContent).toContain('Original preview');
    });

    test('session without preview or name shows "New chat"', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-empty', date: new Date().toISOString(), preview: '', messages: 0, is_active: false }],
      });
      const title = document.querySelector('.chat-sidebar-item-title');
      expect(title!.textContent).toContain('New chat');
    });

    test('session with snippet renders snippet text', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-snip', date: new Date().toISOString(), preview: 'Test', messages: 1, is_active: false, snippet: 'This is a snippet' }],
      });
      const container = document.querySelector('.chat-sidebar-item');
      expect(container!.textContent).toContain('This is a snippet');
    });

    test('meta shows message count', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-msg', date: new Date().toISOString(), preview: 'Test', messages: 42, is_active: false }],
      });
      const meta = document.querySelector('.chat-sidebar-item-meta');
      expect(meta!.textContent).toContain('42 msgs');
    });

    test('cron sessions show yellow indicator dot', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'cron-1', date: new Date().toISOString(), preview: '[heartbeat] test', messages: 1, is_active: false }],
      });
      const title = document.querySelector('.chat-sidebar-item-title');
      const dots = title!.querySelectorAll('span');
      const yellowDot = Array.from(dots).find(s => s.style.color === 'var(--yellow)');
      expect(yellowDot).toBeTruthy();
    });
  });

  describe('Fork session', () => {
    test('fork button exists on each session', () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-fork', date: new Date().toISOString(), preview: 'Forkable', messages: 3, is_active: false }],
      });
      const forkBtn = document.querySelector('.chat-sidebar-fork');
      expect(forkBtn).toBeTruthy();
    });

    test('clicking fork calls api.sessionFork and onResumeSession', async () => {
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-fork', date: new Date().toISOString(), preview: 'Forkable', messages: 3, is_active: false }],
      });
      const forkBtn = document.querySelector('.chat-sidebar-fork')!;

      await act(async () => {
        fireEvent.click(forkBtn);
        // Flush the promise
        await mockApi.sessionFork();
      });

      expect(mockApi.sessionFork).toHaveBeenCalledWith('sess-fork');
      await waitFor(() => {
        expect(onResumeSession).toHaveBeenCalledWith('fork-123');
      });
    });
  });

  describe('Cancel streaming session', () => {
    test('cancel button appears for streaming sessions', () => {
      const streamMap = new Map<string, StreamingSession>();
      streamMap.set('sess-stream', { id: 'sess-stream', elapsed: 10, last_event: null });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-stream', date: new Date().toISOString(), preview: 'Streaming', messages: 1, is_active: true }],
        streamingSessions: streamMap,
      });

      const cancelBtn = document.querySelector('.chat-sidebar-cancel');
      expect(cancelBtn).toBeTruthy();
    });

    test('clicking cancel calls api.chatStateCancel', async () => {
      const streamMap = new Map<string, StreamingSession>();
      streamMap.set('sess-cancel', { id: 'sess-cancel', elapsed: 5, last_event: null });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-cancel', date: new Date().toISOString(), preview: 'Cancel me', messages: 1, is_active: true }],
        streamingSessions: streamMap,
      });

      const cancelBtn = document.querySelector('.chat-sidebar-cancel')!;
      await act(async () => {
        fireEvent.click(cancelBtn);
      });

      expect(mockApi.chatStateCancel).toHaveBeenCalledWith('sess-cancel');
    });
  });

  describe('Remove active session', () => {
    test('remove button appears in active filter for non-streaming sessions', () => {
      renderSidebar({
        sidebarFilter: 'active',
        allSessions: [{ id: 'sess-rm', date: new Date().toISOString(), preview: 'Removable', messages: 2, is_active: true }],
        activeSessions: [{ tab_id: 'tab-rm', session_id: 'sess-rm' }],
      });

      const removeBtn = document.querySelector('.chat-sidebar-remove');
      expect(removeBtn).toBeTruthy();
    });

    test('clicking remove emits socket event', () => {
      renderSidebar({
        sidebarFilter: 'active',
        allSessions: [{ id: 'sess-rm', date: new Date().toISOString(), preview: 'Removable', messages: 2, is_active: true }],
        activeSessions: [{ tab_id: 'tab-rm', session_id: 'sess-rm' }],
      });

      const removeBtn = document.querySelector('.chat-sidebar-remove')!;
      fireEvent.click(removeBtn);

      expect(mockSocketRefObj.current!.emit).toHaveBeenCalledWith('remove_active', {
        tab_id: 'tab-rm',
        session_id: 'sess-rm',
      });
    });

    test('removing current session calls onNewSession', () => {
      renderSidebar({
        sidebarFilter: 'active',
        claudeSessionId: 'sess-rm',
        allSessions: [{ id: 'sess-rm', date: new Date().toISOString(), preview: 'Current', messages: 2, is_active: true }],
        activeSessions: [{ tab_id: 'tab-rm', session_id: 'sess-rm' }],
      });

      const removeBtn = document.querySelector('.chat-sidebar-remove')!;
      fireEvent.click(removeBtn);
      expect(onNewSession).toHaveBeenCalled();
    });
  });

  describe('Session rename', () => {
    test('double-clicking title starts rename', () => {
      Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-rename', date: new Date().toISOString(), preview: 'Rename me', messages: 1, is_active: false }],
      });

      const title = document.querySelector('.chat-sidebar-item-title')!;
      fireEvent.doubleClick(title);

      const input = document.querySelector('.chat-sidebar-item-title input') as HTMLInputElement;
      expect(input).toBeTruthy();
    });

    test('blurring rename input saves the name', () => {
      Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-rename', date: new Date().toISOString(), preview: 'Old name', messages: 1, is_active: false }],
      });

      const title = document.querySelector('.chat-sidebar-item-title')!;
      fireEvent.doubleClick(title);

      const input = document.querySelector('.chat-sidebar-item-title input') as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'New name' } });
      fireEvent.blur(input);

      expect(mockDispatchRef.current).toHaveBeenCalledWith({
        type: 'SET_SESSION_NAME',
        sessionId: 'sess-rename',
        name: 'New name',
      });
    });

    test('pressing Escape cancels rename', () => {
      Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-esc', date: new Date().toISOString(), preview: 'Escape name', messages: 1, is_active: false }],
      });

      const title = document.querySelector('.chat-sidebar-item-title')!;
      fireEvent.doubleClick(title);

      const input = document.querySelector('.chat-sidebar-item-title input') as HTMLInputElement;
      fireEvent.keyDown(input, { key: 'Escape' });

      const inputAfter = document.querySelector('.chat-sidebar-item-title input');
      expect(inputAfter).toBeNull();
    });
  });

  describe('Unread indicator', () => {
    test('unread sessions show unread dot', () => {
      const unread = new Set(['sess-unread']);
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-unread', date: new Date().toISOString(), preview: 'Unread', messages: 3, is_active: false }],
        unreadSessions: unread,
      });

      const dot = document.querySelector('.chat-unread-dot');
      expect(dot).toBeTruthy();
    });

    test('current session does not show unread dot', () => {
      const unread = new Set(['sess-current']);
      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-current', date: new Date().toISOString(), preview: 'Current', messages: 3, is_active: false }],
        unreadSessions: unread,
        claudeSessionId: 'sess-current',
      });

      const dot = document.querySelector('.chat-unread-dot');
      expect(dot).toBeNull();
    });
  });

  describe('Streaming indicator', () => {
    test('streaming session shows streaming dot', () => {
      const streamMap = new Map<string, StreamingSession>();
      streamMap.set('sess-s', { id: 'sess-s', elapsed: 5, last_event: { type: 'thinking_delta' } });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-s', date: new Date().toISOString(), preview: 'Streaming', messages: 1, is_active: true }],
        streamingSessions: streamMap,
      });

      const dot = document.querySelector('.chat-streaming-dot');
      expect(dot).toBeTruthy();
    });

    test('streaming info shows elapsed time and tool label', () => {
      const streamMap = new Map<string, StreamingSession>();
      streamMap.set('sess-info', { id: 'sess-info', elapsed: 65, last_event: { type: 'tool_use', tool: 'Edit' } });

      renderSidebar({
        sidebarFilter: 'all',
        allSessions: [{ id: 'sess-info', date: new Date().toISOString(), preview: 'Streaming info', messages: 1, is_active: true }],
        streamingSessions: streamMap,
      });

      const meta = document.querySelector('.chat-sidebar-item-meta');
      expect(meta!.textContent).toContain('Edit');
      expect(meta!.textContent).toMatch(/1m/);
    });
  });

  describe('Agents section', () => {
    test('agents section renders when agents exist', () => {
      mockAgentsRef.current = [
        { id: 'agent-1', name: 'Test Agent', type: 'background', status: 'running', model: 'sonnet', output_lines: 10, inbox_size: 0, last_output: '', cost_usd: 0.123, started: Math.floor(Date.now() / 1000) - 60 },
      ];

      renderSidebar();
      const header = document.querySelector('.chat-sidebar-agents-header');
      expect(header).toBeTruthy();
      expect(header!.textContent).toContain('Agents');
    });

    test('agents section shows running agent count badge', () => {
      mockAgentsRef.current = [
        { id: 'agent-1', name: 'Running Agent', type: 'background', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0.05, started: Math.floor(Date.now() / 1000) },
      ];

      renderSidebar();
      const badge = document.querySelector('.chat-sidebar-agents-badge');
      expect(badge).toBeTruthy();
      expect(badge!.textContent).toBe('1');
    });

    test('agents section shows total count when no running agents', () => {
      mockAgentsRef.current = [
        { id: 'agent-done', name: 'Done Agent', type: 'background', status: 'completed', model: 'opus', output_lines: 5, inbox_size: 0, last_output: '', cost_usd: 0.5 },
      ];

      renderSidebar();
      const count = document.querySelector('.chat-sidebar-agents-count');
      expect(count).toBeTruthy();
      expect(count!.textContent).toBe('1');
    });

    test('clicking agent header toggles collapse', () => {
      mockAgentsRef.current = [
        { id: 'agent-toggle', name: 'Toggleable', type: 'background', status: 'completed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0 },
      ];

      renderSidebar();
      const header = document.querySelector('.chat-sidebar-agents-header')!;
      let list = document.querySelector('.chat-sidebar-agents-list');
      expect(list).toBeTruthy();

      fireEvent.click(header);
      list = document.querySelector('.chat-sidebar-agents-list');
      expect(list).toBeNull();

      fireEvent.click(header);
      list = document.querySelector('.chat-sidebar-agents-list');
      expect(list).toBeTruthy();
    });

    test('agent item shows name and model', () => {
      mockAgentsRef.current = [
        { id: 'agent-nm', name: 'My Agent', type: 'background', status: 'running', model: 'opus', output_lines: 3, inbox_size: 0, last_output: '', cost_usd: 1.234, started: Math.floor(Date.now() / 1000) - 30 },
      ];

      renderSidebar();
      const agentItem = document.querySelector('.chat-sidebar-agent-item');
      expect(agentItem).toBeTruthy();
      expect(agentItem!.textContent).toContain('My Agent');
      expect(agentItem!.textContent).toContain('opus');
    });

    test('agent item shows cost in dollars', () => {
      mockAgentsRef.current = [
        { id: 'agent-cost', name: 'Costly Agent', type: 'background', status: 'completed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 2.567 },
      ];

      renderSidebar();
      const agentItem = document.querySelector('.chat-sidebar-agent-item');
      expect(agentItem!.textContent).toContain('$2.567');
    });

    test('running agent shows kill button', () => {
      mockAgentsRef.current = [
        { id: 'agent-kill', name: 'Killable', type: 'background', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Math.floor(Date.now() / 1000) },
      ];

      renderSidebar();
      const killBtn = document.querySelector('.chat-sidebar-agent-item .chat-sidebar-remove');
      expect(killBtn).toBeTruthy();
    });

    test('clicking kill button calls api.agentKill', async () => {
      mockAgentsRef.current = [
        { id: 'agent-kill-click', name: 'Kill Me', type: 'background', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Math.floor(Date.now() / 1000) },
      ];

      renderSidebar();
      const killBtn = document.querySelector('.chat-sidebar-agent-item .chat-sidebar-remove')!;

      await act(async () => {
        fireEvent.click(killBtn);
      });

      expect(mockApi.agentKill).toHaveBeenCalledWith('agent-kill-click');
    });

    test('completed agent shows delete button', () => {
      mockAgentsRef.current = [
        { id: 'agent-del', name: 'Deletable', type: 'background', status: 'completed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0 },
      ];

      renderSidebar();
      const delBtn = document.querySelector('.chat-sidebar-agent-item .chat-sidebar-remove');
      expect(delBtn).toBeTruthy();
    });

    test('agent with session_id is clickable', () => {
      mockAgentsRef.current = [
        { id: 'agent-click', name: 'Clickable', type: 'background', status: 'running', session_id: 'sess-agent', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Math.floor(Date.now() / 1000) },
      ];

      renderSidebar();
      const agentItem = document.querySelector('.chat-sidebar-agent-item')!;
      expect(agentItem.classList.contains('clickable')).toBe(true);

      fireEvent.click(agentItem);
      expect(onResumeSession).toHaveBeenCalledWith('sess-agent');
    });

    test('agents section not shown when no agents', () => {
      mockAgentsRef.current = [];
      renderSidebar();
      const section = document.querySelector('.chat-sidebar-agents');
      expect(section).toBeNull();
    });

    test('running agent shows output lines', () => {
      mockAgentsRef.current = [
        { id: 'agent-lines', name: 'With Output', type: 'background', status: 'running', model: 'sonnet', output_lines: 42, inbox_size: 0, last_output: '', cost_usd: 0.1, started: Math.floor(Date.now() / 1000) },
      ];

      renderSidebar();
      const agentItem = document.querySelector('.chat-sidebar-agent-item');
      expect(agentItem!.textContent).toContain('42L');
    });
  });
});

// =====================================================
// ChangesPanel Tests
// =====================================================

describe('ChangesPanel', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    onClose.mockReset();
  });

  test('returns null when not open', () => {
    const { container } = render(<ChangesPanel blocks={[]} open={false} onClose={onClose} />);
    expect(container.querySelector('.chat-changes-panel')).toBeNull();
  });

  test('renders panel when open', () => {
    render(<ChangesPanel blocks={[]} open={true} onClose={onClose} />);
    expect(document.querySelector('.chat-changes-panel')).toBeTruthy();
  });

  test('shows "Changes" title and file count', () => {
    render(<ChangesPanel blocks={[]} open={true} onClose={onClose} />);
    const title = document.querySelector('.chat-changes-panel-title');
    expect(title!.textContent).toBe('Changes');
    const total = document.querySelector('.chat-changes-panel-total');
    expect(total!.textContent).toBe('0 files');
  });

  test('close button calls onClose', () => {
    render(<ChangesPanel blocks={[]} open={true} onClose={onClose} />);
    const closeBtn = document.querySelector('.chat-changes-panel-close')!;
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  test('renders edit file changes', () => {
    const blocks: Block[] = [
      {
        type: 'tool_use',
        id: 1,
        tool: 'Edit',
        input: {
          file_path: '/Users/test/project/src/index.ts',
          old_string: 'const a = 1;',
          new_string: 'const a = 2;',
        },
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const total = document.querySelector('.chat-changes-panel-total');
    expect(total!.textContent).toBe('1 file');
    const fname = document.querySelector('.chat-changes-fname');
    expect(fname!.textContent).toBe('index.ts');
  });

  test('renders write file changes with + indicator', () => {
    const blocks: Block[] = [
      {
        type: 'tool_use',
        id: 1,
        tool: 'Write',
        input: {
          file_path: '/Users/test/project/newfile.ts',
          content: 'export default {};\n',
        },
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const kind = document.querySelector('.chat-changes-kind');
    expect(kind!.textContent).toBe('+');
  });

  test('shows diff with old and new strings for Edit blocks', () => {
    const blocks: Block[] = [
      {
        type: 'tool_use',
        id: 1,
        tool: 'Edit',
        input: {
          file_path: '/Users/test/file.ts',
          old_string: 'old line',
          new_string: 'new line',
        },
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const delLines = document.querySelectorAll('.chat-changes-diff-del');
    const addLines = document.querySelectorAll('.chat-changes-diff-add');
    expect(delLines.length).toBeGreaterThan(0);
    expect(addLines.length).toBeGreaterThan(0);
    expect(delLines[0].textContent).toContain('old line');
    expect(addLines[0].textContent).toContain('new line');
  });

  test('shows content lines for Write blocks', () => {
    const blocks: Block[] = [
      {
        type: 'tool_use',
        id: 1,
        tool: 'Write',
        input: {
          file_path: '/Users/test/new.ts',
          content: 'line 1\nline 2',
        },
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const addLines = document.querySelectorAll('.chat-changes-diff-add');
    expect(addLines).toHaveLength(2);
  });

  test('filter chips render correctly', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/edit.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'Write', input: { file_path: '/a/new.ts', content: 'hello' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const chips = document.querySelectorAll('.chat-changes-chip');
    expect(chips.length).toBeGreaterThanOrEqual(3);
    expect(chips[0].textContent).toContain('All');
    expect(chips[1].textContent).toContain('Edits');
    expect(chips[2].textContent).toContain('New');
  });

  test('clicking Edits filter shows only edit files', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/edit.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'Write', input: { file_path: '/a/new.ts', content: 'hello' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const editsChip = Array.from(document.querySelectorAll('.chat-changes-chip')).find(c => c.textContent?.includes('Edits'))!;
    fireEvent.click(editsChip);

    const files = document.querySelectorAll('.chat-changes-file-block');
    expect(files).toHaveLength(1);
    const fname = document.querySelector('.chat-changes-fname');
    expect(fname!.textContent).toBe('edit.ts');
  });

  test('clicking New filter shows only write/notebook files', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/edit.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'Write', input: { file_path: '/a/new.ts', content: 'hello' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const newChip = Array.from(document.querySelectorAll('.chat-changes-chip')).find(c => c.textContent?.includes('New'))!;
    fireEvent.click(newChip);

    const files = document.querySelectorAll('.chat-changes-file-block');
    expect(files).toHaveLength(1);
    const fname = document.querySelector('.chat-changes-fname');
    expect(fname!.textContent).toBe('new.ts');
  });

  test('clicking file toggles collapse state', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/file.ts', old_string: 'old', new_string: 'new' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);

    let diffs = document.querySelector('.chat-changes-diffs');
    expect(diffs).toBeTruthy();

    const fileRow = document.querySelector('.chat-changes-file')!;
    fireEvent.click(fileRow);

    diffs = document.querySelector('.chat-changes-diffs');
    expect(diffs).toBeNull();

    fireEvent.click(fileRow);
    diffs = document.querySelector('.chat-changes-diffs');
    expect(diffs).toBeTruthy();
  });

  test('multiple edits to same file are grouped', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/file.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'Edit', input: { file_path: '/a/file.ts', old_string: 'c', new_string: 'd' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const files = document.querySelectorAll('.chat-changes-file-block');
    expect(files).toHaveLength(1);
    const editCount = document.querySelector('.chat-changes-edit-n');
    expect(editCount).toBeTruthy();
    expect(editCount!.textContent).toContain('2');
  });

  test('groups files by directory', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/Users/test/src/a.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'Edit', input: { file_path: '/Users/test/lib/b.ts', old_string: 'c', new_string: 'd' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const dirLabels = document.querySelectorAll('.chat-changes-dir-label');
    expect(dirLabels).toHaveLength(2);
    expect(dirLabels[0].textContent).toContain('src');
    expect(dirLabels[1].textContent).toContain('lib');
  });

  test('TodoWrite blocks render as tasks', () => {
    const blocks: Block[] = [
      {
        type: 'tool_use',
        id: 1,
        tool: 'TodoWrite',
        input: {
          todos: [
            { status: 'completed', content: 'Done task' },
            { status: 'in_progress', content: 'Working on it' },
            { status: 'pending', content: 'Not started' },
          ],
        },
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const todos = document.querySelectorAll('.chat-changes-todo');
    expect(todos).toHaveLength(3);
    expect(todos[0].textContent).toContain('Done task');
    expect(todos[1].textContent).toContain('Working on it');
    expect(todos[2].textContent).toContain('Not started');
  });

  test('Tasks filter shows only tasks section', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/file.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'TodoWrite', input: { todos: [{ status: 'pending', content: 'Task' }] } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const tasksChip = Array.from(document.querySelectorAll('.chat-changes-chip')).find(c => c.textContent?.includes('Tasks'))!;
    fireEvent.click(tasksChip);

    const files = document.querySelectorAll('.chat-changes-file-block');
    expect(files).toHaveLength(0);

    const todos = document.querySelectorAll('.chat-changes-todo');
    expect(todos).toHaveLength(1);
  });

  test('NotebookEdit blocks are categorized as notebook kind', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'NotebookEdit', input: { notebook_path: '/a/notebook.ipynb', cell_index: 0 } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const kind = document.querySelector('.chat-changes-kind');
    expect(kind!.textContent).toBe('+');
    const fname = document.querySelector('.chat-changes-fname');
    expect(fname!.textContent).toBe('notebook.ipynb');
  });

  test('tool_group blocks are processed for nested tools', () => {
    const blocks: Block[] = [
      {
        type: 'tool_group',
        id: 1,
        tools: [
          { type: 'tool_use', id: 2, tool: 'Edit', input: { file_path: '/a/nested.ts', old_string: 'x', new_string: 'y' } },
        ],
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const files = document.querySelectorAll('.chat-changes-file-block');
    expect(files).toHaveLength(1);
    expect(document.querySelector('.chat-changes-fname')!.textContent).toBe('nested.ts');
  });

  test('file count pluralizes correctly', () => {
    const blocks1: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Write', input: { file_path: '/a/one.ts', content: 'hi' } },
    ];

    const { unmount } = render(<ChangesPanel blocks={blocks1} open={true} onClose={onClose} />);
    let total = document.querySelector('.chat-changes-panel-total');
    expect(total!.textContent).toBe('1 file');

    unmount();

    const blocks2: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Write', input: { file_path: '/a/one.ts', content: 'hi' } },
      { type: 'tool_use', id: 2, tool: 'Write', input: { file_path: '/a/two.ts', content: 'there' } },
    ];

    render(<ChangesPanel blocks={blocks2} open={true} onClose={onClose} />);
    total = document.querySelector('.chat-changes-panel-total');
    expect(total!.textContent).toBe('2 files');
  });

  test('notebook edit shows "Notebook cell edited" text', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'NotebookEdit', input: { notebook_path: '/a/nb.ipynb', cell_index: 2 } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const meta = document.querySelector('.chat-changes-diff-meta');
    expect(meta!.textContent).toBe('Notebook cell edited');
  });

  test('resize handle exists and responds to mousedown', () => {
    render(<ChangesPanel blocks={[]} open={true} onClose={onClose} />);
    const resizeHandle = document.querySelector('.chat-changes-resize');
    expect(resizeHandle).toBeTruthy();

    // Trigger mousedown on resize handle
    fireEvent.mouseDown(resizeHandle!, { clientX: 500 });
    // Body cursor should be set to col-resize
    expect(document.body.style.cursor).toBe('col-resize');

    // Simulate mouseup to clean up
    fireEvent.mouseUp(window);
  });

  test('resize drag updates panel width', () => {
    render(<ChangesPanel blocks={[]} open={true} onClose={onClose} />);
    const resizeHandle = document.querySelector('.chat-changes-resize')!;
    const panel = document.querySelector('.chat-changes-panel') as HTMLDivElement;

    const initialWidth = parseInt(panel.style.width);

    // Start drag
    fireEvent.mouseDown(resizeHandle, { clientX: 500 });

    // Move mouse (drag left = wider since panel is on right)
    fireEvent.mouseMove(window, { clientX: 400 });

    // End drag
    fireEvent.mouseUp(window);

    // Cursor should be reset
    expect(document.body.style.cursor).toBe('');
  });

  test('edit tilde indicator for edit kind', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/edit.ts', old_string: 'a', new_string: 'b' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const kind = document.querySelector('.chat-changes-kind');
    expect(kind!.textContent).toBe('~');
  });

  test('diff arrow indicator changes on collapse', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/file.ts', old_string: 'a', new_string: 'b' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    let arrow = document.querySelector('.chat-changes-arrow');
    expect(arrow!.classList.contains('open')).toBe(true);

    const fileRow = document.querySelector('.chat-changes-file')!;
    fireEvent.click(fileRow);

    arrow = document.querySelector('.chat-changes-arrow');
    expect(arrow!.classList.contains('open')).toBe(false);
  });

  test('dir shortening replaces /Users/xxx/ with ~/', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/Users/john/projects/src/app.ts', old_string: 'a', new_string: 'b' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const dirLabel = document.querySelector('.chat-changes-dir-label');
    expect(dirLabel!.textContent).toContain('~/');
    expect(dirLabel!.textContent).not.toContain('/Users/john/');
  });

  test('todo icons render correctly by status', () => {
    const blocks: Block[] = [
      {
        type: 'tool_use',
        id: 1,
        tool: 'TodoWrite',
        input: {
          todos: [
            { status: 'completed', content: 'Done' },
            { status: 'in_progress', content: 'WIP' },
            { status: 'pending', content: 'TODO' },
          ],
        },
      },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);
    const icons = document.querySelectorAll('.chat-changes-todo-icon');
    expect(icons).toHaveLength(3);
    // completed = checkmark, in_progress = triangle, pending = circle
    expect(icons[0].textContent).toBe('\u2713');
    expect(icons[1].textContent).toBe('\u25B6');
    expect(icons[2].textContent).toBe('\u25CB');
  });

  test('no changes match filter message appears', () => {
    // Create only Write blocks, then filter to Edits
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Write', input: { file_path: '/a/new.ts', content: 'hello' } },
    ];

    render(<ChangesPanel blocks={blocks} open={true} onClose={onClose} />);

    // The Edits chip shouldn't appear since editCount = 0
    const editsChip = Array.from(document.querySelectorAll('.chat-changes-chip')).find(c => c.textContent?.includes('Edits'));
    expect(editsChip).toBeFalsy();
  });
});

describe('extractChanges', () => {
  test('extracts Edit blocks', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/b.ts', old_string: 'a', new_string: 'b' } },
    ];
    const { files, todoSnapshots } = extractChanges(blocks);
    expect(files.size).toBe(1);
    expect(files.get('/a/b.ts')!.kind).toBe('edit');
    expect(todoSnapshots).toHaveLength(0);
  });

  test('extracts Write blocks', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Write', input: { file_path: '/a/new.ts', content: 'hello' } },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(1);
    expect(files.get('/a/new.ts')!.kind).toBe('write');
  });

  test('extracts TodoWrite blocks', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'TodoWrite', input: { todos: [{ status: 'pending', content: 'Do it' }] } },
    ];
    const { files, todoSnapshots } = extractChanges(blocks);
    expect(files.size).toBe(0);
    expect(todoSnapshots).toHaveLength(1);
    expect(todoSnapshots[0].todos[0].content).toBe('Do it');
  });

  test('ignores non-mutation tools', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: { file_path: '/a/b.ts' } },
      { type: 'tool_use', id: 2, tool: 'Bash', input: { command: 'ls' } },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(0);
  });

  test('groups multiple edits to the same file', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/a/b.ts', old_string: 'a', new_string: 'b' } },
      { type: 'tool_use', id: 2, tool: 'Edit', input: { file_path: '/a/b.ts', old_string: 'c', new_string: 'd' } },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(1);
    expect(files.get('/a/b.ts')!.edits).toHaveLength(2);
  });

  test('processes tool_group nested blocks', () => {
    const blocks: Block[] = [
      {
        type: 'tool_group',
        id: 1,
        tools: [
          { type: 'tool_use', id: 2, tool: 'Edit', input: { file_path: '/x/y.ts', old_string: 'a', new_string: 'b' } },
        ],
      },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(1);
  });

  test('handles blocks with no path gracefully', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: {} },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(0);
  });

  test('NotebookEdit uses notebook_path', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'NotebookEdit', input: { notebook_path: '/a/nb.ipynb' } },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(1);
    expect(files.get('/a/nb.ipynb')!.kind).toBe('notebook');
  });

  test('extracts correct filename and dir', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Edit', input: { file_path: '/Users/test/src/components/App.tsx', old_string: 'a', new_string: 'b' } },
    ];
    const { files } = extractChanges(blocks);
    const file = files.get('/Users/test/src/components/App.tsx')!;
    expect(file.filename).toBe('App.tsx');
    expect(file.dir).toBe('/Users/test/src/components/');
  });

  test('ignores non-tool_use block types', () => {
    const blocks: Block[] = [
      { type: 'assistant', id: 1, text: 'hello' },
      { type: 'user', id: 2, text: 'hi' },
    ];
    const { files } = extractChanges(blocks);
    expect(files.size).toBe(0);
  });
});

// =====================================================
// QuotePopover Tests
// =====================================================

describe('QuotePopover', () => {
  test('does not render when no text is selected', () => {
    const ref = { current: document.createElement('div') };
    document.body.appendChild(ref.current);
    const { container } = render(<QuotePopover containerRef={ref} />);
    expect(container.querySelector('.quote-popover')).toBeNull();
    document.body.removeChild(ref.current);
  });

  test('handles null containerRef gracefully', () => {
    const ref = { current: null };
    const { container } = render(<QuotePopover containerRef={ref} />);
    expect(container.querySelector('.quote-popover')).toBeNull();
  });

  test('registers and cleans up event listeners on container', () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);
    const addSpy = vi.spyOn(containerEl, 'addEventListener');
    const removeSpy = vi.spyOn(containerEl, 'removeEventListener');

    const ref = { current: containerEl };
    const { unmount } = render(<QuotePopover containerRef={ref} />);

    expect(addSpy).toHaveBeenCalledWith('mouseup', expect.any(Function));
    expect(addSpy).toHaveBeenCalledWith('scroll', expect.any(Function));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('mouseup', expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith('scroll', expect.any(Function));

    document.body.removeChild(containerEl);
  });

  test('registers mousedown listener on document', () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);
    const docAddSpy = vi.spyOn(document, 'addEventListener');

    const ref = { current: containerEl };
    const { unmount } = render(<QuotePopover containerRef={ref} />);

    expect(docAddSpy).toHaveBeenCalledWith('mousedown', expect.any(Function));

    unmount();
    document.body.removeChild(containerEl);
  });

  test('scroll event hides popover', () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);
    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    fireEvent.scroll(containerEl);

    expect(document.querySelector('.quote-popover')).toBeNull();
    document.body.removeChild(containerEl);
  });

  test('mouseup with collapsed selection hides popover', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-msg';
    msgEl.textContent = 'Selectable text';
    containerEl.appendChild(msgEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    // Mock collapsed selection (no text selected)
    const mockSelection = {
      isCollapsed: true,
      toString: () => '',
      getRangeAt: vi.fn(),
      removeAllRanges: vi.fn(),
    };
    vi.spyOn(window, 'getSelection').mockReturnValue(mockSelection as unknown as Selection);

    // Trigger mouseup and requestAnimationFrame
    fireEvent.mouseUp(containerEl);
    // requestAnimationFrame callback
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(document.querySelector('.quote-popover')).toBeNull();

    document.body.removeChild(containerEl);
  });

  test('mouseup with selection outside chat-msg hides popover', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    // Element NOT inside .chat-msg
    const outsideEl = document.createElement('div');
    outsideEl.textContent = 'Not a chat message';
    containerEl.appendChild(outsideEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    const mockRange = {
      commonAncestorContainer: outsideEl,
      getBoundingClientRect: () => ({ top: 100, left: 50, width: 100, height: 20, bottom: 120, right: 150, x: 50, y: 100, toJSON: () => {} }),
    };
    const mockSelection = {
      isCollapsed: false,
      toString: () => 'some text',
      getRangeAt: () => mockRange,
      removeAllRanges: vi.fn(),
    };
    vi.spyOn(window, 'getSelection').mockReturnValue(mockSelection as unknown as Selection);

    fireEvent.mouseUp(containerEl);
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(document.querySelector('.quote-popover')).toBeNull();
    document.body.removeChild(containerEl);
  });

  test('mouseup with valid selection inside chat-msg shows popover', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-msg';
    const textNode = document.createTextNode('Quotable text');
    msgEl.appendChild(textNode);
    containerEl.appendChild(msgEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    const mockRange = {
      commonAncestorContainer: textNode,
      getBoundingClientRect: () => ({ top: 100, left: 50, width: 100, height: 20, bottom: 120, right: 150, x: 50, y: 100, toJSON: () => {} }),
    };
    const mockSelection = {
      isCollapsed: false,
      toString: () => 'Quotable text',
      getRangeAt: () => mockRange,
      removeAllRanges: vi.fn(),
    };
    vi.spyOn(window, 'getSelection').mockReturnValue(mockSelection as unknown as Selection);

    fireEvent.mouseUp(containerEl);
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    const popover = document.querySelector('.quote-popover');
    expect(popover).toBeTruthy();
    expect(popover!.textContent).toContain('Quote');

    document.body.removeChild(containerEl);
  });

  test('clicking Quote dispatches chat:quote event and hides popover', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-msg';
    const textNode = document.createTextNode('Text to quote');
    msgEl.appendChild(textNode);
    containerEl.appendChild(msgEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    const mockRange = {
      commonAncestorContainer: textNode,
      getBoundingClientRect: () => ({ top: 100, left: 50, width: 100, height: 20, bottom: 120, right: 150, x: 50, y: 100, toJSON: () => {} }),
    };
    const mockSelection = {
      isCollapsed: false,
      toString: () => 'Text to quote',
      getRangeAt: () => mockRange,
      removeAllRanges: vi.fn(),
    };
    vi.spyOn(window, 'getSelection').mockReturnValue(mockSelection as unknown as Selection);

    // Show the popover
    fireEvent.mouseUp(containerEl);
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    const popover = document.querySelector('.quote-popover');
    expect(popover).toBeTruthy();

    // Listen for the custom event
    const quoteHandler = vi.fn();
    window.addEventListener('chat:quote', quoteHandler);

    // Click the quote button
    fireEvent.click(popover!);

    expect(quoteHandler).toHaveBeenCalledTimes(1);
    const detail = (quoteHandler.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.text).toBe('Text to quote');

    // Selection should be cleared
    expect(mockSelection.removeAllRanges).toHaveBeenCalled();

    // Popover should be hidden
    expect(document.querySelector('.quote-popover')).toBeNull();

    window.removeEventListener('chat:quote', quoteHandler);
    document.body.removeChild(containerEl);
  });

  test('mousedown outside popover hides it', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    const msgEl = document.createElement('div');
    msgEl.className = 'chat-msg';
    const textNode = document.createTextNode('Some text');
    msgEl.appendChild(textNode);
    containerEl.appendChild(msgEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    // Show the popover first
    const mockRange = {
      commonAncestorContainer: textNode,
      getBoundingClientRect: () => ({ top: 100, left: 50, width: 100, height: 20, bottom: 120, right: 150, x: 50, y: 100, toJSON: () => {} }),
    };
    const mockSelection = {
      isCollapsed: false,
      toString: () => 'Some text',
      getRangeAt: () => mockRange,
      removeAllRanges: vi.fn(),
    };
    vi.spyOn(window, 'getSelection').mockReturnValue(mockSelection as unknown as Selection);

    fireEvent.mouseUp(containerEl);
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(document.querySelector('.quote-popover')).toBeTruthy();

    // Mousedown outside the popover
    fireEvent.mouseDown(document.body);

    expect(document.querySelector('.quote-popover')).toBeNull();

    document.body.removeChild(containerEl);
  });

  test('mouseup with empty trimmed text hides popover', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    const mockSelection = {
      isCollapsed: false,
      toString: () => '   ',
      getRangeAt: vi.fn(),
      removeAllRanges: vi.fn(),
    };
    vi.spyOn(window, 'getSelection').mockReturnValue(mockSelection as unknown as Selection);

    fireEvent.mouseUp(containerEl);
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(document.querySelector('.quote-popover')).toBeNull();
    document.body.removeChild(containerEl);
  });

  test('mouseup with null selection hides popover', async () => {
    const containerEl = document.createElement('div');
    document.body.appendChild(containerEl);

    const ref = { current: containerEl };
    render(<QuotePopover containerRef={ref} />);

    vi.spyOn(window, 'getSelection').mockReturnValue(null);

    fireEvent.mouseUp(containerEl);
    await act(async () => {
      vi.advanceTimersByTime(20);
    });

    expect(document.querySelector('.quote-popover')).toBeNull();
    document.body.removeChild(containerEl);
  });
});

// =====================================================
// ArtifactViewer Tests
// =====================================================

describe('ArtifactViewer', () => {
  test('returns null when no activeArtifact', () => {
    mockStateRef.current = createMockState({ activeArtifact: null });
    const { container } = render(<ArtifactViewer />);
    expect(container.querySelector('.artifact-viewer')).toBeNull();
  });

  test('renders iframe with correct src for filename artifact', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'test-view.html', title: 'Test View' },
    });
    render(<ArtifactViewer />);

    const viewer = document.querySelector('.artifact-viewer');
    expect(viewer).toBeTruthy();

    const iframe = document.querySelector('.artifact-iframe') as HTMLIFrameElement;
    expect(iframe).toBeTruthy();
    expect(iframe.src).toContain('/api/views/serve/test-view.html');
  });

  test('renders iframe with correct src for path artifact', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: '', path: 'Notes/test.md', title: 'Markdown View' },
    });
    render(<ArtifactViewer />);

    const iframe = document.querySelector('.artifact-iframe') as HTMLIFrameElement;
    expect(iframe.src).toContain('/api/markdown/render');
    expect(iframe.src).toContain('Notes%2Ftest.md');
  });

  test('shows artifact title in toolbar', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'view.html', title: 'My Artifact Title' },
    });
    render(<ArtifactViewer />);

    const title = document.querySelector('.artifact-toolbar-title');
    expect(title!.textContent).toBe('My Artifact Title');
  });

  test('back button dispatches CLOSE_ARTIFACT', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'view.html', title: 'Test' },
    });
    render(<ArtifactViewer />);

    const backBtn = document.querySelector('.artifact-toolbar-back')!;
    fireEvent.click(backBtn);
    expect(mockDispatchRef.current).toHaveBeenCalledWith({ type: 'CLOSE_ARTIFACT' });
  });

  test('open in new tab button opens correct URL for filename', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'view.html', title: 'Test' },
    });
    render(<ArtifactViewer />);

    const buttons = document.querySelectorAll('.artifact-toolbar-btn');
    const openBtn = buttons[buttons.length - 1];
    fireEvent.click(openBtn);

    expect(openSpy).toHaveBeenCalledWith('/api/views/serve/view.html', '_blank');
    openSpy.mockRestore();
  });

  test('open in new tab button opens correct URL for path', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    mockStateRef.current = createMockState({
      activeArtifact: { filename: '', path: 'Notes/doc.md', title: 'Doc' },
    });
    render(<ArtifactViewer />);

    const buttons = document.querySelectorAll('.artifact-toolbar-btn');
    const openBtn = buttons[buttons.length - 1];
    fireEvent.click(openBtn);

    expect(openSpy).toHaveBeenCalledWith(
      expect.stringContaining('/api/markdown/render'),
      '_blank'
    );
    openSpy.mockRestore();
  });

  test('iframe has correct sandbox attributes', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'view.html', title: 'Sandboxed' },
    });
    render(<ArtifactViewer />);

    const iframe = document.querySelector('.artifact-iframe') as HTMLIFrameElement;
    expect(iframe.sandbox.toString()).toContain('allow-scripts');
    expect(iframe.sandbox.toString()).toContain('allow-same-origin');
  });

  test('postMessage handler calls sendMessageRef on chat_message', () => {
    const sendFn = vi.fn();
    mockSendMessageRefObj.current = sendFn;
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'view.html', title: 'Interactive' },
    });
    render(<ArtifactViewer />);

    const event = new MessageEvent('message', {
      data: { type: 'artifact', action: 'chat_message', payload: { text: 'Hello from artifact' } },
    });
    window.dispatchEvent(event);

    expect(sendFn).toHaveBeenCalledWith('Hello from artifact');
  });

  test('postMessage handler ignores non-artifact messages', () => {
    const sendFn = vi.fn();
    mockSendMessageRefObj.current = sendFn;
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'view.html', title: 'Test' },
    });
    render(<ArtifactViewer />);

    window.dispatchEvent(new MessageEvent('message', { data: { type: 'other' } }));
    expect(sendFn).not.toHaveBeenCalled();
  });

  test('socket artifact_updated listener is registered', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'watch.html', title: 'Watched' },
    });
    render(<ArtifactViewer />);

    expect(mockSocketRefObj.current!.on).toHaveBeenCalledWith('artifact_updated', expect.any(Function));
  });

  test('cleans up socket listener on unmount', () => {
    mockStateRef.current = createMockState({
      activeArtifact: { filename: 'watch.html', title: 'Watched' },
    });
    const { unmount } = render(<ArtifactViewer />);
    unmount();

    expect(mockSocketRefObj.current!.off).toHaveBeenCalledWith('artifact_updated', expect.any(Function));
  });
});

// =====================================================
// ArtifactSidebar Tests
// =====================================================

describe('ArtifactSidebar', () => {
  test('returns null when no artifacts', () => {
    mockStateRef.current = createMockState({ sessionArtifacts: [], activeArtifact: null });
    const { container } = render(<ArtifactSidebar />);
    expect(container.querySelector('.artifact-sidebar')).toBeNull();
  });

  test('returns null when actively viewing an artifact', () => {
    mockStateRef.current = createMockState({
      sessionArtifacts: [{ filename: 'test.html', title: 'Test' }],
      activeArtifact: { filename: 'test.html', title: 'Test' },
    });
    const { container } = render(<ArtifactSidebar />);
    expect(container.querySelector('.artifact-sidebar')).toBeNull();
  });

  test('renders artifact list when artifacts exist and none is active', () => {
    mockStateRef.current = createMockState({
      sessionArtifacts: [
        { filename: 'view1.html', title: 'First View' },
        { filename: 'view2.html', title: 'Second View' },
      ],
      activeArtifact: null,
    });
    render(<ArtifactSidebar />);

    const sidebar = document.querySelector('.artifact-sidebar');
    expect(sidebar).toBeTruthy();

    const header = document.querySelector('.artifact-sidebar-header');
    expect(header!.textContent).toBe('Artifacts');

    const items = document.querySelectorAll('.artifact-sidebar-item');
    expect(items).toHaveLength(2);
  });

  test('artifact item shows title', () => {
    mockStateRef.current = createMockState({
      sessionArtifacts: [{ filename: 'view.html', title: 'My View Title' }],
      activeArtifact: null,
    });
    render(<ArtifactSidebar />);

    const title = document.querySelector('.artifact-sidebar-title');
    expect(title!.textContent).toBe('My View Title');
    expect(title!.getAttribute('title')).toBe('My View Title');
  });

  test('clicking artifact item dispatches OPEN_ARTIFACT', () => {
    mockStateRef.current = createMockState({
      sessionArtifacts: [{ filename: 'click-me.html', title: 'Click Me' }],
      activeArtifact: null,
    });
    render(<ArtifactSidebar />);

    const item = document.querySelector('.artifact-sidebar-item')!;
    fireEvent.click(item);

    expect(mockDispatchRef.current).toHaveBeenCalledWith({
      type: 'OPEN_ARTIFACT',
      filename: 'click-me.html',
      title: 'Click Me',
    });
  });

  test('artifact with path uses path as filename in dispatch', () => {
    mockStateRef.current = createMockState({
      sessionArtifacts: [{ path: 'Notes/doc.md', title: 'A Document' }],
      activeArtifact: null,
    });
    render(<ArtifactSidebar />);

    const item = document.querySelector('.artifact-sidebar-item')!;
    fireEvent.click(item);

    expect(mockDispatchRef.current).toHaveBeenCalledWith({
      type: 'OPEN_ARTIFACT',
      filename: 'Notes/doc.md',
      title: 'A Document',
    });
  });

  test('renders icon SVG for each artifact', () => {
    mockStateRef.current = createMockState({
      sessionArtifacts: [{ filename: 'view.html', title: 'Has Icon' }],
      activeArtifact: null,
    });
    render(<ArtifactSidebar />);

    const icon = document.querySelector('.artifact-sidebar-icon');
    expect(icon).toBeTruthy();
  });
});
