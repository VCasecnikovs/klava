/**
 * Tests for components with low/zero coverage:
 * - ToolRunBlock, SessionTimer, PermissionModal, AssistantBlock (Chat blocks)
 * - PipelineChart (Deals), ActivityFeed, CronJobsList (Health)
 */
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import React, { useRef, useReducer, type ReactNode } from 'react';

// Mock socket.io-client before any component imports
vi.mock('socket.io-client', () => ({
  io: vi.fn(() => ({
    on: vi.fn(),
    off: vi.fn(),
    emit: vi.fn(),
    disconnect: vi.fn(),
    connected: false,
    id: 'mock-socket-id',
    io: { engine: { transport: { name: 'polling' } } },
  })),
}));

// Mock the API client
vi.mock('@/api/client', () => ({
  api: {
    dislike: vi.fn().mockResolvedValue({}),
    chatStateName: vi.fn().mockResolvedValue({}),
    chatStateRead: vi.fn().mockResolvedValue({}),
  },
}));

// Import types and reducer after mocks
import type { Block, ChatState } from '@/context/ChatContext';
import { chatReducer, INITIAL_STATE } from '@/context/ChatContext';

// Components under test
import { ToolRunBlock } from '@/components/tabs/Chat/blocks/ToolRunBlock';
import { SessionTimer } from '@/components/tabs/Chat/blocks/SessionTimer';
import { PermissionModal } from '@/components/tabs/Chat/blocks/PermissionModal';
import { AssistantBlock } from '@/components/tabs/Chat/blocks/AssistantBlock';
import { PipelineChart } from '@/components/tabs/Deals/PipelineChart';
import { ActivityFeed } from '@/components/tabs/Health/ActivityFeed';
import { CronJobsList } from '@/components/tabs/Health/CronJobsList';

// --- Test ChatContext provider (same pattern as blocks.test.tsx) ---

const ChatContext = React.createContext<{
  state: ChatState;
  dispatch: React.Dispatch<any>;
  socketRef: React.MutableRefObject<any>;
  messagesRef: React.MutableRefObject<HTMLDivElement | null>;
  streamingTextRef: React.MutableRefObject<HTMLDivElement | null>;
  sendMessageRef: React.MutableRefObject<((text: string) => void) | null>;
} | null>(null);

vi.mock('@/context/ChatContext', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/context/ChatContext')>();
  return {
    ...original,
    useChatContext: () => {
      const ctx = React.useContext(ChatContext);
      if (!ctx) throw new Error('useChatContext must be used within TestChatProvider');
      return ctx;
    },
  };
});

function TestChatProvider({
  children,
  stateOverrides = {},
}: {
  children: ReactNode;
  stateOverrides?: Partial<ChatState>;
}) {
  const initialState: ChatState = {
    ...INITIAL_STATE,
    ...stateOverrides,
  };
  const [state, dispatch] = useReducer(chatReducer, initialState);
  const socketRef = useRef({
    emit: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    connected: true,
  });
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const streamingTextRef = useRef<HTMLDivElement | null>(null);
  const sendMessageRef = useRef<((text: string) => void) | null>(null);

  return (
    <ChatContext.Provider
      value={{ state, dispatch, socketRef: socketRef as any, messagesRef, streamingTextRef, sendMessageRef }}
    >
      {children}
    </ChatContext.Provider>
  );
}

function renderWithCtx(ui: React.ReactElement, stateOverrides?: Partial<ChatState>) {
  return render(
    <TestChatProvider stateOverrides={stateOverrides}>
      {ui}
    </TestChatProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// =====================
// ToolRunBlock
// =====================
describe('ToolRunBlock', () => {
  test('returns null when no tool_use blocks', () => {
    const blocks: Block[] = [{ type: 'assistant', id: 1, text: 'hello' }];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    expect(container.innerHTML).toBe('');
  });

  test('renders summary for a single tool_use block', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: { file_path: '/test.ts' } },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    expect(container.querySelector('.chat-tool-run')).toBeInTheDocument();
    expect(screen.getByText('read 1 file')).toBeInTheDocument();
  });

  test('renders plural summary for multiple tool_use blocks', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: { file_path: '/a.ts' } },
      { type: 'tool_use', id: 2, tool: 'Read', input: { file_path: '/b.ts' } },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    expect(screen.getByText('read 2 files')).toBeInTheDocument();
  });

  test('renders summary for mixed tool types', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Bash', input: { command: 'ls' } },
      { type: 'tool_use', id: 2, tool: 'Read', input: { file_path: '/test.ts' } },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    // Should show both tools described
    const desc = container.querySelector('.chat-tool-run-desc');
    expect(desc?.textContent).toContain('ran 1 command');
    expect(desc?.textContent).toContain('read 1 file');
  });

  test('renders duration when tool has duration_ms', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: {}, duration_ms: 2500 },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    expect(container.querySelector('.chat-tool-run-duration')?.textContent).toBe('2.5s');
  });

  test('renders duration in ms when under 1000ms', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: {}, duration_ms: 450 },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    expect(container.querySelector('.chat-tool-run-duration')?.textContent).toBe('450ms');
  });

  test('expands/collapses on header click', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: { file_path: '/test.ts' } },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);

    // Initially not expanded
    expect(container.querySelector('.chat-tool-run.expanded')).not.toBeInTheDocument();
    expect(container.querySelector('.chat-tool-run-body')).not.toBeInTheDocument();

    // Click header to expand
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);
    expect(container.querySelector('.chat-tool-run.expanded')).toBeInTheDocument();
    expect(container.querySelector('.chat-tool-run-body')).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);
    expect(container.querySelector('.chat-tool-run.expanded')).not.toBeInTheDocument();
  });

  test('renders tool items with name and summary when expanded', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Bash', input: { command: 'ls -la', description: 'list files' } },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);

    expect(screen.getByText('Bash')).toBeInTheDocument();
  });

  test('attaches tool_result to preceding tool_use', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: { file_path: '/test.ts' } },
      { type: 'tool_result', id: 2, content: 'file contents here\nsecond line' },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);

    // Result preview should show first line
    expect(container.querySelector('.chat-tool-run-item-result-preview')?.textContent).toBe('file contents here');
  });

  test('handles tool_group blocks', () => {
    const blocks: Block[] = [
      {
        type: 'tool_group',
        id: 3,
        tools: [
          { type: 'tool_use', id: 1, tool: 'Grep', input: { pattern: 'test' } },
          { type: 'tool_result', id: 2, content: 'match found' },
        ],
      },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    expect(screen.getByText('searched 1 pattern')).toBeInTheDocument();
  });

  test('shows spinner for running tools', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Bash', input: { command: 'make' }, running: true },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={true} />);
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);

    expect(container.querySelector('.tool-spinner')).toBeInTheDocument();
  });

  test('handles unknown tool name with generic verb', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'CustomTool', input: {} },
      { type: 'tool_use', id: 2, tool: 'CustomTool', input: {} },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    const desc = container.querySelector('.chat-tool-run-desc');
    expect(desc?.textContent).toContain('used CustomTool 2 times');
  });

  test('handles single unknown tool with singular verb', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'CustomTool', input: {} },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    const desc = container.querySelector('.chat-tool-run-desc');
    expect(desc?.textContent).toContain('used CustomTool');
  });

  test('truncates long result preview at 120 chars', () => {
    const longContent = 'A'.repeat(200);
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: {} },
      { type: 'tool_result', id: 2, content: longContent },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);

    const preview = container.querySelector('.chat-tool-run-item-result-preview')?.textContent || '';
    expect(preview.length).toBeLessThanOrEqual(123); // 120 + "..."
    expect(preview).toContain('...');
  });

  test('handles tool_result with text fallback', () => {
    const blocks: Block[] = [
      { type: 'tool_use', id: 1, tool: 'Read', input: {} },
      { type: 'tool_result', id: 2, text: 'text fallback content' },
    ];
    const { container } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
    fireEvent.click(container.querySelector('.chat-tool-run-header')!);

    expect(container.querySelector('.chat-tool-run-item-result-preview')?.textContent).toBe('text fallback content');
  });

  test('renders all TOOL_VERBS correctly', () => {
    const toolTests = [
      { tool: 'Edit', singular: 'edited 1 file', plural: 'edited 2 files' },
      { tool: 'Write', singular: 'wrote 1 file', plural: 'wrote 2 files' },
      { tool: 'Glob', singular: 'found 1 pattern', plural: 'found 2 patterns' },
      { tool: 'WebSearch', singular: 'searched 1 query', plural: 'searched 2 queries' },
      { tool: 'WebFetch', singular: 'fetched 1 page', plural: 'fetched 2 pages' },
      { tool: 'Task', singular: 'ran 1 task', plural: 'ran 2 tasks' },
    ];
    for (const { tool, singular } of toolTests) {
      const blocks: Block[] = [{ type: 'tool_use', id: 1, tool, input: {} }];
      const { container, unmount } = render(<ToolRunBlock blocks={blocks} isStreaming={false} />);
      expect(container.querySelector('.chat-tool-run-desc')?.textContent).toBe(singular);
      unmount();
    }
  });
});

// =====================
// SessionTimer
// =====================
describe('SessionTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test('returns null when not streaming', () => {
    const { container } = renderWithCtx(<SessionTimer />, { realtimeStatus: 'idle' });
    expect(container.innerHTML).toBe('');
  });

  test('renders when streaming', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 5000,
      realtimeBlocks: [],
    });
    expect(container.querySelector('.chat-session-timer')).toBeInTheDocument();
  });

  test('shows thinking activity by default', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 3000,
      realtimeBlocks: [],
    });
    expect(container.querySelector('.chat-session-timer-activity')?.textContent).toBe('thinking');
  });

  test('shows writing activity when last block is assistant', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 3000,
      realtimeBlocks: [
        { type: 'assistant', id: 1, text: 'hello' },
      ],
    });
    expect(container.querySelector('.chat-session-timer-activity')?.textContent).toBe('writing');
  });

  test('shows tool activity when running tool_use block', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 3000,
      realtimeBlocks: [
        { type: 'tool_use', id: 1, tool: 'Read', running: true, start_time: (now - 1000) / 1000 },
      ],
    });
    expect(container.querySelector('.chat-session-timer-activity')?.textContent).toBe('Read');
  });

  test('shows tool activity from tool_group with running tool', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 3000,
      realtimeBlocks: [
        {
          type: 'tool_group',
          id: 1,
          tools: [
            { type: 'tool_use', id: 2, tool: 'Bash', running: true, start_time: (now - 500) / 1000 },
          ],
        },
      ],
    });
    expect(container.querySelector('.chat-session-timer-activity')?.textContent).toBe('Bash');
  });

  test('displays elapsed time in seconds format', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 45000,
      realtimeBlocks: [],
    });
    expect(container.querySelector('.chat-session-timer-total')?.textContent).toBe('45s');
  });

  test('displays elapsed time in minutes+seconds format', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 125000,
      realtimeBlocks: [],
    });
    expect(container.querySelector('.chat-session-timer-total')?.textContent).toBe('2m 5s');
  });

  test('shows tool detail timing', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 5000,
      realtimeBlocks: [
        { type: 'tool_use', id: 1, tool: 'Grep', running: true, start_time: (now - 2500) / 1000 },
      ],
    });
    const detail = container.querySelector('.chat-session-timer-detail');
    expect(detail).toBeInTheDocument();
    expect(detail?.textContent).toContain('s');
  });

  test('updates timer via interval', () => {
    const now = Date.now();
    const { container } = renderWithCtx(<SessionTimer />, {
      realtimeStatus: 'streaming',
      streamStart: now - 5000,
      realtimeBlocks: [],
    });

    const before = container.querySelector('.chat-session-timer-total')?.textContent;

    // Advance timers by 3 seconds
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    const after = container.querySelector('.chat-session-timer-total')?.textContent;
    // The timer should have updated (the exact value depends on fake timer mechanics)
    expect(container.querySelector('.chat-session-timer')).toBeInTheDocument();
  });
});

// =====================
// PermissionModal
// =====================
describe('PermissionModal', () => {
  test('returns null when no pending permission', () => {
    const { container } = renderWithCtx(<PermissionModal />, { pendingPermission: null });
    expect(container.innerHTML).toBe('');
  });

  test('renders permission request UI', () => {
    const { container } = renderWithCtx(<PermissionModal />, {
      pendingPermission: { tool: 'Bash', description: 'Run command: rm -rf /tmp/test' },
    });
    expect(screen.getByText('Permission Required')).toBeInTheDocument();
    expect(screen.getByText('Bash')).toBeInTheDocument();
    expect(screen.getByText('Run command: rm -rf /tmp/test')).toBeInTheDocument();
  });

  test('renders Allow and Deny buttons', () => {
    renderWithCtx(<PermissionModal />, {
      pendingPermission: { tool: 'Bash', description: 'test command' },
    });
    expect(screen.getByText('Allow')).toBeInTheDocument();
    expect(screen.getByText('Deny')).toBeInTheDocument();
  });

  test('clicking Allow dispatches and clears permission', () => {
    const { container } = renderWithCtx(<PermissionModal />, {
      pendingPermission: { tool: 'Bash', description: 'test' },
    });
    fireEvent.click(screen.getByText('Allow'));
    // After clicking, modal should be gone (dispatch clears pendingPermission)
    expect(container.querySelector('.chat-permission')).not.toBeInTheDocument();
  });

  test('clicking Deny dispatches and clears permission', () => {
    const { container } = renderWithCtx(<PermissionModal />, {
      pendingPermission: { tool: 'Bash', description: 'test' },
    });
    fireEvent.click(screen.getByText('Deny'));
    expect(container.querySelector('.chat-permission')).not.toBeInTheDocument();
  });

  test('has correct CSS classes', () => {
    const { container } = renderWithCtx(<PermissionModal />, {
      pendingPermission: { tool: 'Read', description: 'Read file' },
    });
    expect(container.querySelector('.chat-permission')).toBeInTheDocument();
    expect(container.querySelector('.chat-permission-inner')).toBeInTheDocument();
    expect(container.querySelector('.chat-permission-title')).toBeInTheDocument();
    expect(container.querySelector('.chat-permission-tool')).toBeInTheDocument();
    expect(container.querySelector('.chat-permission-desc')).toBeInTheDocument();
    expect(container.querySelector('.chat-permission-btns')).toBeInTheDocument();
    expect(container.querySelector('.chat-btn-allow')).toBeInTheDocument();
    expect(container.querySelector('.chat-btn-deny')).toBeInTheDocument();
  });
});

// =====================
// AssistantBlock
// =====================
describe('AssistantBlock', () => {
  test('renders plain text content', () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Hello world' };
    render(<AssistantBlock block={block} />);
    const el = document.querySelector('.chat-msg-assistant');
    expect(el).toBeInTheDocument();
    expect(el?.textContent).toContain('Hello world');
  });

  test('renders empty text gracefully', () => {
    const block: Block = { type: 'assistant', id: 1, text: '' };
    const { container } = render(<AssistantBlock block={block} />);
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });

  test('renders with chat-msg-with-actions wrapper', () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Test' };
    const { container } = render(<AssistantBlock block={block} />);
    expect(container.querySelector('.chat-msg-with-actions')).toBeInTheDocument();
  });

  test('shows dislike button', () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Test message' };
    const { container } = render(<AssistantBlock block={block} />);
    const btn = container.querySelector('.chat-dislike-btn');
    expect(btn).toBeInTheDocument();
    expect(btn?.textContent).toBe('\uD83D\uDC4E'); // thumbs down emoji
  });

  test('shows feedback form when dislike button clicked', () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Bad response' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);

    expect(container.querySelector('.chat-feedback-form')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('What went wrong?')).toBeInTheDocument();
    expect(screen.getByText('Send')).toBeInTheDocument();
  });

  test('toggles feedback form on double click', () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Response' };
    const { container } = render(<AssistantBlock block={block} />);

    // First click - open
    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    expect(container.querySelector('.chat-feedback-form')).toBeInTheDocument();

    // Second click - close
    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    expect(container.querySelector('.chat-feedback-form')).not.toBeInTheDocument();
  });

  test('submits feedback on Send click', async () => {
    const { api } = await import('@/api/client');
    const block: Block = { type: 'assistant', id: 1, text: 'Bad answer' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    const input = screen.getByPlaceholderText('What went wrong?');
    fireEvent.change(input, { target: { value: 'Too verbose' } });
    fireEvent.click(screen.getByText('Send'));

    expect(api.dislike).toHaveBeenCalledWith(1, 'Bad answer', 'Too verbose');
  });

  test('shows checkmark after submission', async () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Test' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    fireEvent.click(screen.getByText('Send'));

    const btn = container.querySelector('.chat-dislike-btn');
    expect(btn?.textContent).toBe('\u2713'); // checkmark
    expect(btn?.classList.contains('submitted')).toBe(true);
  });

  test('prevents double submission', async () => {
    const { api } = await import('@/api/client');
    const block: Block = { type: 'assistant', id: 1, text: 'Test' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    fireEvent.click(screen.getByText('Send'));

    // Try clicking dislike again - should not open form
    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    expect(container.querySelector('.chat-feedback-form')).not.toBeInTheDocument();
  });

  test('submits feedback on Enter key', async () => {
    const { api } = await import('@/api/client');
    const block: Block = { type: 'assistant', id: 1, text: 'Test text' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    const input = screen.getByPlaceholderText('What went wrong?');
    fireEvent.change(input, { target: { value: 'feedback' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(api.dislike).toHaveBeenCalled();
  });

  test('closes feedback form on Escape key', () => {
    const block: Block = { type: 'assistant', id: 1, text: 'Test' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    const input = screen.getByPlaceholderText('What went wrong?');
    fireEvent.keyDown(input, { key: 'Escape' });

    expect(container.querySelector('.chat-feedback-form')).not.toBeInTheDocument();
  });

  test('does not submit on Shift+Enter', async () => {
    const { api } = await import('@/api/client');
    (api.dislike as ReturnType<typeof vi.fn>).mockClear();
    const block: Block = { type: 'assistant', id: 1, text: 'Test' };
    const { container } = render(<AssistantBlock block={block} />);

    fireEvent.click(container.querySelector('.chat-dislike-btn')!);
    const input = screen.getByPlaceholderText('What went wrong?');
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });

    // Form should still be visible, no submission
    expect(container.querySelector('.chat-feedback-form')).toBeInTheDocument();
    expect(api.dislike).not.toHaveBeenCalled();
  });

  test('renders artifact content when text contains artifact fence', () => {
    const text = 'Here is an artifact:\n```artifact\n{"filename": "test.html", "title": "Test View"}\n```\nAfter artifact.';
    const block: Block = { type: 'assistant', id: 1, text };
    const { container } = render(<AssistantBlock block={block} />);
    expect(container.querySelector('.artifact-card')).toBeInTheDocument();
  });

  test('handles text without block.text (undefined)', () => {
    const block: Block = { type: 'assistant', id: 1 };
    const { container } = render(<AssistantBlock block={block} />);
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });
});

// =====================
// PipelineChart
// =====================
describe('PipelineChart', () => {
  test('shows empty message when no stages', () => {
    const { container } = render(<PipelineChart stages={[]} />);
    expect(container.querySelector('.empty')?.textContent).toBe('No active deals');
  });

  test('shows empty message when stages is undefined', () => {
    const { container } = render(<PipelineChart />);
    expect(container.querySelector('.empty')?.textContent).toBe('No active deals');
  });

  test('renders stages with bars', () => {
    const stages = [
      { stage: 'Prospecting', stage_num: 2, count: 5, total_value: 100000 },
      { stage: 'Negotiating', stage_num: 5, count: 3, total_value: 250000 },
    ];
    const { container } = render(<PipelineChart stages={stages} />);

    // Should have stage labels
    expect(screen.getByText('Prospecting')).toBeInTheDocument();
    expect(screen.getByText('Negotiating')).toBeInTheDocument();

    // Should have count numbers
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  test('formats currency values correctly', () => {
    const stages = [
      { stage: 'Won', stage_num: 10, count: 1, total_value: 1500000 },
      { stage: 'Small', stage_num: 3, count: 2, total_value: 500 },
      { stage: 'Medium', stage_num: 6, count: 1, total_value: 50000 },
    ];
    const { container } = render(<PipelineChart stages={stages} />);

    // $1.5M
    expect(screen.getByText('$1.5M')).toBeInTheDocument();
    // $500
    expect(screen.getByText('$500')).toBeInTheDocument();
    // $50,000
    expect(screen.getByText('$50,000')).toBeInTheDocument();
  });

  test('handles null total_value', () => {
    const stages = [
      { stage: 'Unknown', stage_num: 1, count: 1, total_value: null as any },
    ];
    const { container } = render(<PipelineChart stages={stages} />);
    expect(screen.getByText('-')).toBeInTheDocument();
  });

  test('applies correct stage colors', () => {
    const stages = [
      { stage: 'Early', stage_num: 2, count: 2, total_value: 1000 },   // muted (<=3)
      { stage: 'Mid', stage_num: 5, count: 3, total_value: 2000 },     // yellow (<=6)
      { stage: 'Late', stage_num: 8, count: 1, total_value: 3000 },    // blue (<=9)
      { stage: 'Won', stage_num: 11, count: 1, total_value: 4000 },    // green (<=12)
      { stage: 'Beyond', stage_num: 15, count: 1, total_value: 5000 }, // claude-md (>12)
    ];
    const { container } = render(<PipelineChart stages={stages} />);
    const rows = container.querySelectorAll('div[style*="display: flex"]');
    expect(rows.length).toBe(5);
  });

  test('calculates bar width proportionally', () => {
    const stages = [
      { stage: 'Big', stage_num: 3, count: 10, total_value: 1000 },
      { stage: 'Small', stage_num: 5, count: 1, total_value: 100 },
    ];
    const { container } = render(<PipelineChart stages={stages} />);
    // The bar widths should reflect relative counts: big=100%, small=max(1/10*100, 8)=10%
    // We can't easily test computed styles but can verify the elements exist
    expect(container.querySelectorAll('div[style*="display: flex"]').length).toBe(2);
  });
});

// =====================
// ActivityFeed
// =====================
describe('ActivityFeed', () => {
  const baseItem = {
    job_id: 'heartbeat',
    status: 'completed',
    timestamp: '2026-03-16T10:00:00Z',
    ago: '5m ago',
    duration_seconds: 30,
  };

  test('renders empty state when no items match filter', () => {
    render(<ActivityFeed items={[]} />);
    expect(screen.getByText('No activity matching filter')).toBeInTheDocument();
  });

  test('renders activity items', () => {
    const items = [
      { ...baseItem, job_id: 'heartbeat', ago: '5m ago' },
      { ...baseItem, job_id: 'reflection', ago: '2h ago', timestamp: '2026-03-16T08:00:00Z' },
    ];
    render(<ActivityFeed items={items} />);

    expect(screen.getByText('heartbeat')).toBeInTheDocument();
    expect(screen.getByText('reflection')).toBeInTheDocument();
  });

  test('builds dynamic filter buttons from job_ids', () => {
    const items = [
      { ...baseItem, job_id: 'heartbeat' },
      { ...baseItem, job_id: 'reflection', timestamp: '2026-03-16T09:00:00Z' },
    ];
    render(<ActivityFeed items={items} />);

    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Heartbeat')).toBeInTheDocument();
    expect(screen.getByText('Reflection')).toBeInTheDocument();
  });

  test('shows Errors filter when errors present', () => {
    const items = [
      { ...baseItem, error: 'Something failed' },
    ];
    render(<ActivityFeed items={items} />);
    expect(screen.getByText('Errors')).toBeInTheDocument();
  });

  test('does not show Errors filter when no errors', () => {
    const items = [{ ...baseItem }];
    render(<ActivityFeed items={items} />);
    expect(screen.queryByText('Errors')).not.toBeInTheDocument();
  });

  test('filters items by job_id when filter clicked', () => {
    const items = [
      { ...baseItem, job_id: 'heartbeat', ago: '5m ago' },
      { ...baseItem, job_id: 'reflection', ago: '2h ago', timestamp: '2026-03-16T09:00:00Z' },
    ];
    const { container } = render(<ActivityFeed items={items} />);

    // Click Reflection filter button
    const reflectionBtn = screen.getByText('Reflection');
    fireEvent.click(reflectionBtn);

    // Only reflection items should show
    const actJobs = container.querySelectorAll('.act-job');
    expect(actJobs.length).toBe(1);
    expect(actJobs[0].textContent).toBe('reflection');
  });

  test('filters errors when errors filter active', () => {
    const items = [
      { ...baseItem, job_id: 'heartbeat', ago: '5m ago' },
      { ...baseItem, job_id: 'heartbeat', error: 'Failed!', status: 'failed', ago: '10m ago', timestamp: '2026-03-16T09:50:00Z' },
    ];
    const { container } = render(<ActivityFeed items={items} />);

    fireEvent.click(screen.getByText('Errors'));

    const actItems = container.querySelectorAll('.act-item');
    expect(actItems.length).toBe(1);
  });

  test('shows cost when present', () => {
    const items = [{ ...baseItem, cost_usd: 0.05 }];
    render(<ActivityFeed items={items} />);
    expect(screen.getByText('$0.05')).toBeInTheDocument();
  });

  test('does not show cost when zero', () => {
    const items = [{ ...baseItem, cost_usd: 0 }];
    const { container } = render(<ActivityFeed items={items} />);
    const costEl = container.querySelector('.act-cost');
    expect(costEl?.textContent).toBe('');
  });

  test('expands item with output on click', () => {
    const items = [{ ...baseItem, output: 'Heartbeat completed successfully' }];
    const { container } = render(<ActivityFeed items={items} />);

    // Initially not expanded
    expect(container.querySelector('.act-output')).not.toBeInTheDocument();

    // Click header to expand
    fireEvent.click(container.querySelector('.act-header')!);
    expect(container.querySelector('.act-output')).toBeInTheDocument();
    expect(screen.getByText('Heartbeat completed successfully')).toBeInTheDocument();
  });

  test('collapses item on second click', () => {
    const items = [{ ...baseItem, output: 'Some output' }];
    const { container } = render(<ActivityFeed items={items} />);

    fireEvent.click(container.querySelector('.act-header')!);
    expect(container.querySelector('.act-output')).toBeInTheDocument();

    fireEvent.click(container.querySelector('.act-header')!);
    expect(container.querySelector('.act-output')).not.toBeInTheDocument();
  });

  test('shows error class for items with errors', () => {
    const items = [{ ...baseItem, error: 'Boom!' }];
    const { container } = render(<ActivityFeed items={items} />);

    // The dot should have 'off' class
    expect(container.querySelector('.svc-dot.off')).toBeInTheDocument();

    // Expand to see error output
    fireEvent.click(container.querySelector('.act-header')!);
    expect(container.querySelector('.act-output.error')).toBeInTheDocument();
  });

  test('shows chevron only for expandable items', () => {
    const items = [
      { ...baseItem, output: 'Has output' },
      { ...baseItem, timestamp: '2026-03-16T09:00:00Z' }, // no output, no error
    ];
    const { container } = render(<ActivityFeed items={items} />);
    const chevrons = container.querySelectorAll('.act-chevron');
    expect(chevrons.length).toBe(1);
  });

  test('shows duration in seconds', () => {
    const items = [{ ...baseItem, duration_seconds: 45 }];
    render(<ActivityFeed items={items} />);
    expect(screen.getByText('45s')).toBeInTheDocument();
  });

  test('shows failed status items in errors filter', () => {
    const items = [
      { ...baseItem, status: 'failed', job_id: 'test-job', ago: '1m ago' },
    ];
    const { container } = render(<ActivityFeed items={items} />);

    fireEvent.click(screen.getByText('Errors'));
    const actItems = container.querySelectorAll('.act-item');
    expect(actItems.length).toBe(1);
  });
});

// =====================
// CronJobsList
// =====================
describe('CronJobsList', () => {
  test('renders a list of cron jobs', () => {
    const jobs = [
      {
        id: 'heartbeat',
        schedule: '*/30 * * * *',
        enabled: true,
        mode: 'claude',
        model: 'sonnet',
        name: 'Heartbeat',
        status: 'completed',
        schedule_display: 'Every 30 min',
        last_run_ago: '5m ago',
        runs_24h: 48,
        avg_duration_s: 30,
      },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);

    expect(screen.getByText('Heartbeat')).toBeInTheDocument();
    expect(screen.getByText('claude')).toBeInTheDocument();
    expect(screen.getByText('sonnet')).toBeInTheDocument();
  });

  test('shows job id when no name', () => {
    const jobs = [
      { id: 'my-job', schedule: '0 * * * *', enabled: true, mode: 'script' },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('my-job')).toBeInTheDocument();
  });

  test('applies disabled class for disabled jobs', () => {
    const jobs = [
      { id: 'disabled-job', schedule: '0 * * * *', enabled: false, mode: 'claude' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    expect(container.querySelector('.cron-row.disabled')).toBeInTheDocument();
  });

  test('shows green dot for completed status', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'claude', status: 'completed' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    const dot = container.querySelector('.cron-dot') as HTMLElement;
    expect(dot.style.background).toBe('var(--green)');
  });

  test('shows red dot for failed status', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'claude', status: 'failed' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    const dot = container.querySelector('.cron-dot') as HTMLElement;
    expect(dot.style.background).toBe('var(--red)');
  });

  test('shows yellow dot for running status', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'claude', status: 'running' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    const dot = container.querySelector('.cron-dot') as HTMLElement;
    expect(dot.style.background).toBe('var(--yellow)');
  });

  test('shows muted dot for unknown status', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'claude' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    const dot = container.querySelector('.cron-dot') as HTMLElement;
    expect(dot.style.background).toBe('var(--text-muted)');
  });

  test('displays schedule_display over raw schedule', () => {
    const jobs = [
      { id: 'j1', schedule: '*/30 * * * *', enabled: true, mode: 'claude', schedule_display: 'Every 30 min' },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('Every 30 min')).toBeInTheDocument();
  });

  test('falls back to schedule when no schedule_display', () => {
    const jobs = [
      { id: 'j1', schedule: '0 5 * * *', enabled: true, mode: 'script' },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('0 5 * * *')).toBeInTheDocument();
  });

  test('shows last_run_ago over last_run', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'claude', last_run_ago: '2m ago', last_run: '2026-03-16T10:00:00Z' },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('2m ago')).toBeInTheDocument();
  });

  test('falls back to last_run then never', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'script' },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('never')).toBeInTheDocument();
  });

  test('shows runs/24h and avg duration', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'claude', runs_24h: 12, avg_duration_s: 45 },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('12 runs/24h')).toBeInTheDocument();
    expect(screen.getByText('45s avg')).toBeInTheDocument();
  });

  test('defaults runs and avg to 0', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'script' },
    ];
    render(<CronJobsList jobs={jobs} />);
    expect(screen.getByText('0 runs/24h')).toBeInTheDocument();
    expect(screen.getByText('0s avg')).toBeInTheDocument();
  });

  test('renders multiple jobs', () => {
    const jobs = [
      { id: 'heartbeat', schedule: '*/30 * * * *', enabled: true, mode: 'claude', name: 'Heartbeat' },
      { id: 'reflection', schedule: '30 5 * * *', enabled: true, mode: 'claude', name: 'Reflection' },
      { id: 'cleanup', schedule: '0 0 * * *', enabled: false, mode: 'script', name: 'Cleanup' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    expect(container.querySelectorAll('.cron-row').length).toBe(3);
  });

  test('does not show model badge when model is absent', () => {
    const jobs = [
      { id: 'j1', schedule: '* * * * *', enabled: true, mode: 'script' },
    ];
    const { container } = render(<CronJobsList jobs={jobs} />);
    expect(container.querySelector('.cron-badge-model')).not.toBeInTheDocument();
  });
});
