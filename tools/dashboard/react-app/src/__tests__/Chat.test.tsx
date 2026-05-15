/**
 * Integration tests for the Chat component with mock Socket.IO.
 *
 * Tests cover the two-entity chat protocol:
 *  1. New chat - realtime_block_add loading shows up
 *  2. Streaming flow - thinking + assistant + cost blocks render
 *  3. Resume session - history_snapshot renders all blocks
 *  4. Tab routing - realtime blocks only accepted for correct session
 *  5. Reconnect - handlers work after disconnect/reconnect
 */
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatPanel } from '@/components/tabs/Chat/index';
import { MockSocket } from '@/__mocks__/socket.io-client';

// ---- Module Mocks ----

// Mock socket.io-client BEFORE any imports that use it
vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

// Mock the API client to avoid real HTTP calls
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
    chatScopeGet: vi.fn().mockResolvedValue({ scope: null }),
    chatScopeSet: vi.fn().mockResolvedValue({ ok: true, scope: null }),
    scopes: vi.fn().mockResolvedValue({ scopes: [] }),
    uploadFile: vi.fn().mockResolvedValue({ files: [] }),
  },
}));

// ---- Helpers ----

/** Render ChatPanel wrapped in QueryClientProvider (needed by ChatSidebar) */
function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

/** Render ChatPanel and wait for socket to be created + connected */
async function renderChat() {
  MockSocket.instance = null;
  MockSocket.resetEmitted();

  let result: ReturnType<typeof render>;
  await act(async () => {
    result = renderWithProviders(
      <ChatPanel mode="sidebar" width={460} onWidthChange={() => {}} onToggle={() => {}} onFullscreen={() => {}} />
    );
  });

  // Wait for the socket to be instantiated (useEffect runs)
  await waitFor(() => {
    expect(MockSocket.instance).toBeTruthy();
  });

  const socket = MockSocket.instance!;

  // Simulate connection (the mock does it on setTimeout(0), but we do it
  // explicitly inside act to make sure React sees the state update)
  await act(async () => {
    socket.simulateConnect();
  });

  return { result: result!, socket };
}

/**
 * Helper to get the messages container.
 * ChatMain renders <div class="chat-messages" ref={messagesRef}>
 */
function getMessagesContainer(): HTMLElement {
  const el = document.querySelector('.chat-messages');
  if (!el) throw new Error('Could not find .chat-messages container');
  return el as HTMLElement;
}

/** Helper to make a tab/session current before injecting session-bound events. */
async function activateSession(sessionId: string, label = 'Test Session') {
  await act(async () => {
    MockSocket.instance?.simulateEvent('chat_state_sync', {
      active_sessions: [{ tab_id: null, session_id: sessionId }],
      session_names: { [sessionId]: label },
      streaming_sessions: [],
      unread_sessions: [],
    });
  });
  const item = Array.from(document.querySelectorAll('.chat-sidebar-item'))
    .find(el => el.textContent?.includes(label)) as HTMLElement;
  await act(async () => { fireEvent.click(item); });
}

/** Helper to establish a session with both history and realtime snapshots */
async function establishSession(socket: MockSocket, tabId: string, opts: {
  historyBlocks?: Array<Record<string, unknown>>;
  realtimeBlocks?: Array<Record<string, unknown>>;
  streaming?: boolean;
} = {}) {
  await activateSession(tabId, `Session ${tabId}`);
  const { historyBlocks = [], realtimeBlocks = [], streaming = false } = opts;
  await act(async () => {
    socket.simulateEvent('history_snapshot', {
      blocks: historyBlocks,
      session_id: tabId,
    });
  });
  await act(async () => {
    socket.simulateEvent('realtime_snapshot', {
      blocks: realtimeBlocks,
      streaming,
      queue: [],
      tab_id: tabId,
    });
  });
}

// ---- Test Suite ----

describe('Chat integration tests', () => {
  beforeEach(() => {
    MockSocket.instance = null;
    MockSocket.resetEmitted();
    // Provide crypto.randomUUID if not available
    if (!globalThis.crypto?.randomUUID) {
      Object.defineProperty(globalThis, 'crypto', {
        value: {
          randomUUID: () => 'test-uuid-' + Math.random().toString(36).slice(2),
        },
        writable: true,
        configurable: true,
      });
    }
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  // ---- Test 1 ----
  test('new chat: realtime_block_add loading renders loading indicator', async () => {
    const { socket } = await renderChat();

    const tabId = 'tab-loading-test';
    await establishSession(socket, tabId, { streaming: true });

    // Send realtime_block_add with loading block
    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: { type: 'loading', id: 1 },
        tab_id: tabId,
      });
    });

    // LoadingBlock was removed (replaced by SpinnerBar above input).
    // BlockRenderer returns null for 'loading' type, so no .chat-loading element.
    // Just verify the block was processed without errors.
    expect(document.querySelector('.chat-loading')).toBeNull();
  });

  // ---- Test 2 ----
  test('streaming: thinking + assistant + cost blocks render', async () => {
    const { socket } = await renderChat();

    const tabId = 'tab-streaming-test';
    await establishSession(socket, tabId, { streaming: true });

    // 1) Add loading
    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: { type: 'loading', id: 1 },
        tab_id: tabId,
      });
    });

    // 2) Remove loading via realtime_block_update
    await act(async () => {
      socket.simulateEvent('realtime_block_update', {
        id: 1,
        patch: { type: '_removed' },
        tab_id: tabId,
      });
    });

    // Loading should be removed
    expect(document.querySelector('.chat-loading')).not.toBeInTheDocument();

    // 3) Add thinking block
    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: {
          type: 'thinking',
          id: 2,
          text: 'Let me analyze this request carefully.',
          words: 6,
          preview: 'Let me analyze this request',
        },
        tab_id: tabId,
      });
    });

    expect(document.querySelector('.chat-thinking-bubble') ?? document.querySelector('.chat-thinking')).toBeInTheDocument();

    // 4) Add assistant block
    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: { type: 'assistant', id: 3, text: 'Hello! How can I help?' },
        tab_id: tabId,
      });
    });

    expect(document.querySelector('.chat-msg-assistant')).toBeInTheDocument();

    // 5) Add cost block
    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: {
          type: 'cost',
          id: 4,
          seconds: 5,
          cost: 0.01,
          session_id: 'real-session-uuid',
        },
        tab_id: tabId,
      });
    });

    expect(document.querySelector('.chat-cost')).toBeInTheDocument();
    expect(document.querySelector('.chat-cost')!.textContent).toContain('5s');
    expect(document.querySelector('.chat-cost')!.textContent).toContain('$0.0100');
  });

  // ---- Test 3 ----
  test('resume: history_snapshot renders all blocks at once', async () => {
    const { socket } = await renderChat();

    const tabId = 'tab-resume-test';
    const sessionId = 'session-resume-123';
    await activateSession(sessionId, 'Resume Session');

    // Simulate a full history_snapshot (as received when resuming a completed session)
    await act(async () => {
      socket.simulateEvent('history_snapshot', {
        blocks: [
          { type: 'user', id: 0, text: 'hello', files: [] },
          {
            type: 'thinking',
            id: 1,
            text: 'thinking about the greeting',
            words: 4,
            preview: 'thinking about',
          },
          { type: 'assistant', id: 2, text: 'Hi there!' },
          { type: 'cost', id: 3, seconds: 3, cost: 0.005 },
        ],
        session_id: sessionId,
      });
    });

    // Also send empty realtime to set tab_id
    await act(async () => {
      socket.simulateEvent('realtime_snapshot', {
        blocks: [],
        streaming: false,
        queue: [],
        tab_id: tabId,
      });
    });

    const container = getMessagesContainer();

    // user + assistant = 2 chat-msg elements
    const msgs = container.querySelectorAll('.chat-msg');
    expect(msgs.length).toBe(2);

    // Verify user message
    const userMsg = container.querySelector('.chat-msg-user');
    expect(userMsg).toBeInTheDocument();
    expect(userMsg!.textContent).toContain('hello');

    // Verify assistant message
    const assistantMsg = container.querySelector('.chat-msg-assistant');
    expect(assistantMsg).toBeInTheDocument();

    // Verify thinking block
    expect(container.querySelector('.chat-thinking-bubble') ?? container.querySelector('.chat-thinking')).toBeInTheDocument();

    // Verify cost block
    const cost = container.querySelector('.chat-cost');
    expect(cost).toBeInTheDocument();
    expect(cost!.textContent).toContain('3s');
  });

  // ---- Test 4 ----
  test('tab routing: realtime blocks render in correct session', async () => {
    const { socket } = await renderChat();

    const correctTabId = 'correct-tab';
    await establishSession(socket, correctTabId, {
      historyBlocks: [
        { type: 'user', id: 0, text: 'original', files: [] },
        { type: 'assistant', id: 1, text: 'original reply' },
      ],
    });

    // Verify we have 1 assistant message in history
    const assistantsBefore = document.querySelectorAll('.chat-msg-assistant');
    expect(assistantsBefore.length).toBe(1);

    // Send realtime_block_add - should append to realtime
    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: { type: 'assistant', id: 0, text: 'from realtime' },
        tab_id: correctTabId,
      });
    });

    // Should now have 2 assistant messages (1 history + 1 realtime)
    const assistantsFinal = document.querySelectorAll('.chat-msg-assistant');
    expect(assistantsFinal.length).toBe(2);
  });

  // ---- Test 5 ----
  test('reconnect: handlers work after disconnect and reconnect', async () => {
    const { socket } = await renderChat();

    const tabId = 'tab-reconnect-test';
    await establishSession(socket, tabId);

    // Disconnect
    await act(async () => {
      socket.simulateDisconnect();
    });

    // Should show reconnect banner
    expect(document.querySelector('#chat-reconnect')).toBeInTheDocument();

    // Reconnect
    await act(async () => {
      socket.simulateConnect();
    });

    // Reconnect banner should be removed
    expect(document.querySelector('#chat-reconnect')).not.toBeInTheDocument();

    // Verify handlers still work after reconnect: send new history_snapshot
    await act(async () => {
      socket.simulateEvent('history_snapshot', {
        blocks: [
          { type: 'user', id: 0, text: 'after reconnect', files: [] },
          { type: 'assistant', id: 1, text: 'reconnected reply' },
        ],
        session_id: tabId,
      });
    });
    await act(async () => {
      socket.simulateEvent('realtime_snapshot', {
        blocks: [],
        streaming: false,
        queue: [],
        tab_id: tabId,
      });
    });

    // Verify blocks rendered after reconnect
    const container = getMessagesContainer();
    expect(container.querySelector('.chat-msg-user')).toBeInTheDocument();
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
    expect(container.querySelector('.chat-msg-user')!.textContent).toContain('after reconnect');
  });

  test('realtime_done preserves final block update that arrived in the same tick', async () => {
    const { socket } = await renderChat();
    const tabId = 'tab-final-update-race';
    await establishSession(socket, tabId, {
      streaming: true,
      realtimeBlocks: [
        { type: 'user', id: 0, text: 'say final', files: [] },
        { type: 'assistant', id: 1, text: '' },
      ],
    });

    await act(async () => {
      socket.simulateEvent('realtime_block_update', {
        id: 1,
        patch: { text: 'Final answer survived.' },
        tab_id: tabId,
      });
      socket.simulateEvent('realtime_done', { has_next: false, tab_id: tabId });
    });

    expect(document.querySelector('.chat-msg-user')?.textContent).toContain('say final');
    expect(document.querySelector('.chat-msg-assistant')?.textContent).toContain('Final answer survived.');
    expect(document.querySelectorAll('.chat-msg-assistant').length).toBe(1);
  });

  test('new chat fast finish keeps optimistic user block when realtime_done arrives quickly', async () => {
    const { socket } = await renderChat();
    const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'fast question' } });
      fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', charCode: 13 });
    });

    const send = MockSocket.emitted.find(e => e.event === 'send_message');
    const tabId = (send?.args[0] as { tab_id?: string })?.tab_id;
    expect(tabId).toBeTruthy();

    await act(async () => {
      socket.simulateEvent('realtime_block_add', {
        block: { type: 'assistant', id: 1, text: 'fast answer' },
        tab_id: tabId,
      });
      socket.simulateEvent('realtime_done', { has_next: false, tab_id: tabId });
    });

    expect(document.querySelector('.chat-msg-user')?.textContent).toContain('fast question');
    expect(document.querySelector('.chat-msg-assistant')?.textContent).toContain('fast answer');
  });

  // ---- Test 6: queue panel never renders ----
  test('queue panel is NOT rendered when queue_update arrives', async () => {
    const { socket } = await renderChat();
    const tabId = 'tab-queue-test';

    await establishSession(socket, tabId, { streaming: true });

    // Simulate backend sending queue_update with queued items
    await act(async () => {
      socket.simulateEvent('queue_update', {
        queue: [
          { text: 'second message', index: 0 },
          { text: 'third message', index: 1 },
        ],
        tab_id: tabId,
      });
    });

    // Queue panel must NOT exist - user doesn't want it
    expect(document.querySelector('.chat-queue-panel')).not.toBeInTheDocument();
  });

  // ---- Test 7: per-session model/effort restore ----
  test('switching sessions restores saved model and effort per session', async () => {
    const { socket } = await renderChat();
    const sessA = 'session-a';
    const sessB = 'session-b';

    localStorage.setItem('chat_session_settings', JSON.stringify({
      [sessA]: { model: 'opus[1m]', effort: 'max' },
      [sessB]: { model: 'sonnet', effort: 'low' },
    }));

    await act(async () => {
      socket.simulateEvent('chat_state_sync', {
        active_sessions: [
          { tab_id: null, session_id: sessA },
          { tab_id: null, session_id: sessB },
        ],
        session_names: { [sessA]: 'Session A', [sessB]: 'Session B' },
        streaming_sessions: [],
        unread_sessions: [],
      });
    });

    const sessionAItem = Array.from(document.querySelectorAll('.chat-sidebar-item'))
      .find(el => el.textContent?.includes('Session A')) as HTMLElement;
    const sessionBItem = Array.from(document.querySelectorAll('.chat-sidebar-item'))
      .find(el => el.textContent?.includes('Session B')) as HTMLElement;
    expect(sessionAItem).toBeInTheDocument();
    expect(sessionBItem).toBeInTheDocument();

    await act(async () => { fireEvent.click(sessionAItem); });
    expect((document.querySelector('select[title="Model"]') as HTMLSelectElement).value).toBe('opus[1m]');
    expect((document.querySelector('select[title="Reasoning effort"]') as HTMLSelectElement).value).toBe('max');

    await act(async () => { fireEvent.click(sessionBItem); });
    expect((document.querySelector('select[title="Model"]') as HTMLSelectElement).value).toBe('sonnet');
    expect((document.querySelector('select[title="Reasoning effort"]') as HTMLSelectElement).value).toBe('low');

    await act(async () => { fireEvent.click(sessionAItem); });
    expect((document.querySelector('select[title="Model"]') as HTMLSelectElement).value).toBe('opus[1m]');
    expect((document.querySelector('select[title="Reasoning effort"]') as HTMLSelectElement).value).toBe('max');
  });

  test('history model detection does not overwrite saved 1M model variant', async () => {
    const { socket } = await renderChat();
    const sessionId = 'session-with-1m';

    localStorage.setItem('chat_session_settings', JSON.stringify({
      [sessionId]: { model: 'opus[1m]', effort: 'high' },
    }));

    await act(async () => {
      socket.simulateEvent('chat_state_sync', {
        active_sessions: [{ tab_id: null, session_id: sessionId }],
        session_names: { [sessionId]: '1M Session' },
        streaming_sessions: [],
        unread_sessions: [],
      });
    });

    const item = Array.from(document.querySelectorAll('.chat-sidebar-item'))
      .find(el => el.textContent?.includes('1M Session')) as HTMLElement;
    await act(async () => { fireEvent.click(item); });

    await act(async () => {
      socket.simulateEvent('history_snapshot', {
        blocks: [{ type: 'assistant', id: 0, text: 'saved session' }],
        session_id: sessionId,
        model: 'claude-opus-4-7',
      });
    });

    expect((document.querySelector('select[title="Model"]') as HTMLSelectElement).value).toBe('opus[1m]');
  });

  test('resuming Codex-native GPT-5.5 history restores GPT-5.5 model selector', async () => {
    const { socket } = await renderChat();
    const sessionId = 'session-with-gpt55';

    await act(async () => {
      socket.simulateEvent('chat_state_sync', {
        active_sessions: [{ tab_id: null, session_id: sessionId }],
        session_names: { [sessionId]: 'GPT Session' },
        streaming_sessions: [],
        unread_sessions: [],
      });
    });

    const item = Array.from(document.querySelectorAll('.chat-sidebar-item'))
      .find(el => el.textContent?.includes('GPT Session')) as HTMLElement;
    await act(async () => { fireEvent.click(item); });

    await act(async () => {
      socket.simulateEvent('history_snapshot', {
        blocks: [{ type: 'assistant', id: 0, text: 'saved gpt session' }],
        session_id: sessionId,
        model: 'gpt-5.5',
      });
    });

    expect((document.querySelector('select[title="Model"]') as HTMLSelectElement).value).toBe('codex:gpt-5.5');

    const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;
    const sendButton = document.querySelector('.chat-send') as HTMLButtonElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'continue this session' } });
      fireEvent.click(sendButton);
    });

    const sendEvent = MockSocket.emitted.find(e => e.event === 'send_message');
    expect(sendEvent?.args[0]).toMatchObject({
      resume_session_id: sessionId,
      model: 'codex:gpt-5.5',
    });
  });


  // ---- Test 8: input clears after send even on stale draft_sync ----
  test('input draft clears after send even when chat_state_sync has stale draft', async () => {
    const { socket } = await renderChat();
    const tabId = 'tab-draft-clear-test';

    // Establish a streaming session so handleSend takes the socket.emit path
    await establishSession(socket, tabId, { streaming: true });

    const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;
    expect(textarea).toBeInTheDocument();

    // User types a message
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'hello world' } });
    });
    expect(textarea.value).toBe('hello world');

    // User sends (Enter key) - handleSend fires, socket emits send_message, returns true
    await act(async () => {
      fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', charCode: 13 });
    });

    // Input should be cleared immediately after send
    expect(textarea.value).toBe('');

    // Server sends chat_state_sync with stale (pre-send) draft value
    await act(async () => {
      socket.simulateEvent('chat_state_sync', {
        active_sessions: [],
        session_names: {},
        streaming_sessions: [],
        unread_sessions: [],
        drafts: { [tabId]: 'hello world' }, // stale - should NOT restore
      });
    });

    // Input must still be empty - draft must NOT be restored from stale sync
    expect(textarea.value).toBe('');
  });
});
