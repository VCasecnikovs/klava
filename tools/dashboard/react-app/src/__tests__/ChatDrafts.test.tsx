/**
 * Focused regression tests for Chat draft persistence.
 */
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChatPanel } from '@/components/tabs/Chat/index';
import { MockSocket } from '@/__mocks__/socket.io-client';

vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

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

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

async function renderChat() {
  MockSocket.instance = null;
  MockSocket.resetEmitted();

  let result: ReturnType<typeof render>;
  await act(async () => {
    result = renderWithProviders(
      <ChatPanel mode="sidebar" width={460} onWidthChange={() => {}} onToggle={() => {}} onFullscreen={() => {}} />
    );
  });

  await waitFor(() => {
    expect(MockSocket.instance).toBeTruthy();
  });

  const socket = MockSocket.instance!;
  await act(async () => {
    socket.simulateConnect();
  });

  return { result: result!, socket };
}

describe('Chat draft persistence', () => {
  beforeEach(() => {
    MockSocket.instance = null;
    MockSocket.resetEmitted();
    localStorage.clear();
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

  test('draft survives switching away before debounced server echo', async () => {
    const { socket } = await renderChat();
    const sessA = 'session-draft-a';
    const sessB = 'session-draft-b';

    await act(async () => {
      socket.simulateEvent('chat_state_sync', {
        active_sessions: [
          { tab_id: null, session_id: sessA },
          { tab_id: null, session_id: sessB },
        ],
        session_names: { [sessA]: 'Draft A', [sessB]: 'Draft B' },
        streaming_sessions: [],
        unread_sessions: [],
        drafts: {},
      });
    });

    const sessionAItem = Array.from(document.querySelectorAll('.chat-sidebar-item'))
      .find(el => el.textContent?.includes('Draft A')) as HTMLElement;
    const sessionBItem = Array.from(document.querySelectorAll('.chat-sidebar-item'))
      .find(el => el.textContent?.includes('Draft B')) as HTMLElement;
    expect(sessionAItem).toBeInTheDocument();
    expect(sessionBItem).toBeInTheDocument();

    await act(async () => { fireEvent.click(sessionAItem); });
    const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'unsent session A draft' } });
    });
    expect(textarea.value).toBe('unsent session A draft');

    await act(async () => { fireEvent.click(sessionBItem); });
    expect(textarea.value).toBe('');

    await act(async () => { fireEvent.click(sessionAItem); });
    expect(textarea.value).toBe('unsent session A draft');
  });
});
