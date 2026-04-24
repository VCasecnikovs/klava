/**
 * Unit tests for Chat block components.
 *
 * Each block is rendered in isolation with a minimal ChatContext provider.
 * Tests verify rendering, CSS classes, content display, and interactions.
 */
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import React, { createContext, useRef, useReducer, type ReactNode } from 'react';

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

// Import components after mocks
import type { Block, ChatState } from '@/context/ChatContext';
import { chatReducer, INITIAL_STATE } from '@/context/ChatContext';
import { BlockRenderer } from '@/components/tabs/Chat/blocks/BlockRenderer';
import { ThinkingBlock } from '@/components/tabs/Chat/blocks/ThinkingBlock';
import { ThinkingBubble } from '@/components/tabs/Chat/blocks/ThinkingBubble';
import { ToolUseBlock } from '@/components/tabs/Chat/blocks/ToolUseBlock';
import { ToolGroupBlock } from '@/components/tabs/Chat/blocks/ToolGroupBlock';
import { ToolResultBlock } from '@/components/tabs/Chat/blocks/ToolResultBlock';
import { AgentBlock } from '@/components/tabs/Chat/blocks/AgentBlock';
import { QuestionBlock } from '@/components/tabs/Chat/blocks/QuestionBlock';
import { CostBlock } from '@/components/tabs/Chat/blocks/CostBlock';
import { ErrorBlock } from '@/components/tabs/Chat/blocks/ErrorBlock';
import { UserBlock } from '@/components/tabs/Chat/blocks/UserBlock';
import { AssistantBlock } from '@/components/tabs/Chat/blocks/AssistantBlock';
import { StreamingBlock } from '@/components/tabs/Chat/blocks/StreamingBlock';
import { ArtifactCard } from '@/components/tabs/Chat/artifacts/ArtifactCard';
import { PlanReviewBlock } from '@/components/tabs/Chat/blocks/PlanReviewBlock';

// --- Test ChatContext provider ---
// We create a minimal provider that exposes the same shape as the real ChatContext.
// This avoids spinning up the full ChatProvider (which connects socket.io).

// Re-create the context shape expected by useChatContext
const ChatContext = React.createContext<{
  state: ChatState;
  dispatch: React.Dispatch<any>;
  socketRef: React.MutableRefObject<any>;
  messagesRef: React.MutableRefObject<HTMLDivElement | null>;
  streamingTextRef: React.MutableRefObject<HTMLDivElement | null>;
  sendMessageRef: React.MutableRefObject<((text: string) => void) | null>;
} | null>(null);

// Patch useChatContext to use our test context
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
  sendMessage,
}: {
  children: ReactNode;
  stateOverrides?: Partial<ChatState>;
  sendMessage?: (text: string) => void;
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
  const sendMessageRef = useRef<((text: string) => void) | null>(sendMessage || null);

  return (
    <ChatContext.Provider
      value={{ state, dispatch, socketRef: socketRef as any, messagesRef, streamingTextRef, sendMessageRef }}
    >
      {children}
    </ChatContext.Provider>
  );
}

function renderWithCtx(ui: React.ReactElement, stateOverrides?: Partial<ChatState>, sendMessage?: (text: string) => void) {
  return render(
    <TestChatProvider stateOverrides={stateOverrides} sendMessage={sendMessage}>
      {ui}
    </TestChatProvider>
  );
}

// --- Tests ---

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// =====================
// UserBlock
// =====================
describe('UserBlock', () => {
  test('renders text content', () => {
    const block: Block = { type: 'user', id: 1, text: 'Hello from user' };
    render(<UserBlock block={block} />);
    expect(screen.getByText('Hello from user')).toBeInTheDocument();
  });

  test('renders with chat-msg-user class', () => {
    const block: Block = { type: 'user', id: 1, text: 'Test' };
    const { container } = render(<UserBlock block={block} />);
    expect(container.querySelector('.chat-msg-user')).toBeInTheDocument();
  });

  test('renders pending class when pending', () => {
    const block: Block = { type: 'user', id: 1, text: 'Pending msg', pending: true };
    const { container } = render(<UserBlock block={block} />);
    expect(container.querySelector('.chat-msg-pending')).toBeInTheDocument();
  });

  test('does not render pending class when not pending', () => {
    const block: Block = { type: 'user', id: 1, text: 'Normal msg' };
    const { container } = render(<UserBlock block={block} />);
    expect(container.querySelector('.chat-msg-pending')).not.toBeInTheDocument();
  });

  test('renders file attachments', () => {
    const block: Block = {
      type: 'user',
      id: 1,
      text: 'Check this file',
      files: [{ name: 'readme.txt', path: '/tmp/readme.txt', type: 'text/plain', size: 100 }],
    };
    const { container } = render(<UserBlock block={block} />);
    expect(container.querySelector('.chat-msg-file')).toBeInTheDocument();
    expect(container.innerHTML).toContain('readme.txt');
  });

  test('renders image attachments', () => {
    const block: Block = {
      type: 'user',
      id: 1,
      text: '',
      files: [{ name: 'photo.png', path: '/tmp/photo.png', type: 'image/png', size: 5000, url: '/uploads/photo.png' }],
    };
    const { container } = render(<UserBlock block={block} />);
    const img = container.querySelector('.chat-msg-image') as HTMLImageElement;
    expect(img).toBeInTheDocument();
    expect(img.src).toContain('/uploads/photo.png');
    expect(img.alt).toBe('photo.png');
  });

  test('renders with no text and no files gracefully', () => {
    const block: Block = { type: 'user', id: 1 };
    const { container } = render(<UserBlock block={block} />);
    expect(container.querySelector('.chat-msg-user')).toBeInTheDocument();
  });
});

// =====================
// AssistantBlock
// =====================
describe('AssistantBlock', () => {
  test('renders text as markdown', () => {
    const block: Block = { type: 'assistant', id: 2, text: 'Hello from assistant' };
    renderWithCtx(<AssistantBlock block={block} />);
    expect(screen.getByText('Hello from assistant')).toBeInTheDocument();
  });

  test('has chat-msg-assistant class', () => {
    const block: Block = { type: 'assistant', id: 2, text: 'Test' };
    const { container } = renderWithCtx(<AssistantBlock block={block} />);
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });

  test('has dislike button', () => {
    const block: Block = { type: 'assistant', id: 2, text: 'Test' };
    const { container } = renderWithCtx(<AssistantBlock block={block} />);
    expect(container.querySelector('.chat-dislike-btn')).toBeInTheDocument();
  });

  test('clicking dislike shows feedback form', () => {
    const block: Block = { type: 'assistant', id: 2, text: 'Test' };
    const { container } = renderWithCtx(<AssistantBlock block={block} />);
    const btn = container.querySelector('.chat-dislike-btn')!;
    fireEvent.click(btn);
    expect(container.querySelector('.chat-feedback-form')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('What went wrong?')).toBeInTheDocument();
  });

  test('renders empty text gracefully', () => {
    const block: Block = { type: 'assistant', id: 2, text: '' };
    const { container } = renderWithCtx(<AssistantBlock block={block} />);
    expect(container.querySelector('.chat-msg-with-actions')).toBeInTheDocument();
  });

  test('renders text with artifact fences', () => {
    const text = 'Here is an artifact:\n```artifact\n{"filename": "test.html", "title": "Test"}\n```\nDone.';
    const block: Block = { type: 'assistant', id: 2, text };
    const { container } = renderWithCtx(<AssistantBlock block={block} />);
    expect(container.querySelector('.artifact-card')).toBeInTheDocument();
    expect(screen.getByText('Test')).toBeInTheDocument();
  });
});

// =====================
// ThinkingBlock
// =====================
describe('ThinkingBlock', () => {
  test('renders thinking header with word count', () => {
    const block: Block = { type: 'thinking', id: 3, text: 'Deep thought here', words: 3, preview: 'Deep thought' };
    const { container } = render(<ThinkingBlock block={block} />);
    expect(container.querySelector('.chat-thinking')).toBeInTheDocument();
    expect(container.innerHTML).toContain('3 words');
  });

  test('renders preview text', () => {
    const block: Block = { type: 'thinking', id: 3, text: 'Full text', words: 2, preview: 'Full text' };
    const { container } = render(<ThinkingBlock block={block} />);
    expect(container.innerHTML).toContain('Full text');
  });

  test('starts collapsed', () => {
    const block: Block = { type: 'thinking', id: 3, text: 'Hidden content', words: 2, preview: 'preview' };
    const { container } = render(<ThinkingBlock block={block} />);
    const content = container.querySelector('.chat-thinking-content') as HTMLElement;
    expect(content.style.display).toBe('none');
  });

  test('expands on click', () => {
    const block: Block = { type: 'thinking', id: 3, text: 'Revealed content', words: 2, preview: 'preview' };
    const { container } = render(<ThinkingBlock block={block} />);
    const header = container.querySelector('.chat-thinking-header')!;
    fireEvent.click(header);
    const content = container.querySelector('.chat-thinking-content') as HTMLElement;
    expect(content.style.display).toBe('block');
    expect(container.querySelector('.chat-thinking')!.classList.contains('expanded')).toBe(true);
  });

  test('toggles collapse on second click', () => {
    const block: Block = { type: 'thinking', id: 3, text: 'Content', words: 1, preview: 'x' };
    const { container } = render(<ThinkingBlock block={block} />);
    const header = container.querySelector('.chat-thinking-header')!;
    fireEvent.click(header);
    fireEvent.click(header);
    const content = container.querySelector('.chat-thinking-content') as HTMLElement;
    expect(content.style.display).toBe('none');
  });

  test('handles zero words', () => {
    const block: Block = { type: 'thinking', id: 3 };
    const { container } = render(<ThinkingBlock block={block} />);
    expect(container.innerHTML).toContain('0 words');
  });

  test('appends ellipsis for long preview', () => {
    const longPreview = 'A'.repeat(60);
    const block: Block = { type: 'thinking', id: 3, text: 'long', words: 1, preview: longPreview };
    const { container } = render(<ThinkingBlock block={block} />);
    expect(container.innerHTML).toContain('...');
  });
});

// =====================
// ThinkingBubble
// =====================
describe('ThinkingBubble', () => {
  test('renders with total word count', () => {
    const blocks: Block[] = [
      { type: 'thinking', id: 10, text: 'First pass thinking.', words: 3, preview: 'First pass' },
      { type: 'thinking', id: 11, text: 'Second pass more.', words: 3, preview: 'Second pass' },
    ];
    const { container } = render(<ThinkingBubble blocks={blocks} />);
    expect(container.querySelector('.chat-thinking-bubble')).toBeInTheDocument();
    expect(container.innerHTML).toContain('6 words');
  });

  test('shows preview when collapsed', () => {
    const blocks: Block[] = [
      { type: 'thinking', id: 10, text: 'First sentence here.', words: 3 },
    ];
    const { container } = render(<ThinkingBubble blocks={blocks} />);
    expect(container.querySelector('.chat-thinking-bubble-pass-preview')).toBeInTheDocument();
    expect(container.innerHTML).toContain('First sentence here.');
  });

  test('expands to show passes on click', () => {
    const blocks: Block[] = [
      { type: 'thinking', id: 10, text: 'Pass one text.', words: 3 },
      { type: 'thinking', id: 11, text: 'Pass two text.', words: 3 },
    ];
    const { container } = render(<ThinkingBubble blocks={blocks} />);
    const header = container.querySelector('.chat-thinking-bubble-header')!;
    fireEvent.click(header);
    expect(container.querySelector('.chat-thinking-bubble-body')).toBeInTheDocument();
    const passes = container.querySelectorAll('.chat-thinking-bubble-pass');
    expect(passes.length).toBe(2);
  });

  test('shows "Thinking" label when expanded', () => {
    const blocks: Block[] = [
      { type: 'thinking', id: 10, text: 'Some text.', words: 2 },
    ];
    const { container } = render(<ThinkingBubble blocks={blocks} />);
    const header = container.querySelector('.chat-thinking-bubble-header')!;
    fireEvent.click(header);
    expect(container.innerHTML).toContain('Thinking');
  });

  test('shows separator between passes', () => {
    const blocks: Block[] = [
      { type: 'thinking', id: 10, text: 'Pass 1.', words: 2 },
      { type: 'thinking', id: 11, text: 'Pass 2.', words: 2 },
    ];
    const { container } = render(<ThinkingBubble blocks={blocks} />);
    const header = container.querySelector('.chat-thinking-bubble-header')!;
    fireEvent.click(header);
    expect(container.querySelector('.chat-thinking-bubble-sep')).toBeInTheDocument();
  });

  test('preview truncates long text', () => {
    const longText = 'A'.repeat(100);
    const blocks: Block[] = [
      { type: 'thinking', id: 10, text: longText, words: 1 },
    ];
    const { container } = render(<ThinkingBubble blocks={blocks} />);
    const preview = container.querySelector('.chat-thinking-bubble-pass-preview');
    expect(preview!.textContent!.endsWith('...')).toBe(true);
    expect(preview!.textContent!.length).toBeLessThanOrEqual(84); // 80 chars + '...'
  });

  test('handles empty blocks array', () => {
    const { container } = render(<ThinkingBubble blocks={[]} />);
    expect(container.querySelector('.chat-thinking-bubble')).toBeInTheDocument();
    expect(container.innerHTML).toContain('0 words');
  });
});

// =====================
// ToolUseBlock
// =====================
describe('ToolUseBlock', () => {
  test('renders tool name', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: { command: 'ls -la' } };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.querySelector('.chat-tool')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Bash');
  });

  test('renders tool summary', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Read', input: { file_path: '/home/user/test.ts' } };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.innerHTML).toContain('test.ts');
  });

  test('shows running class and spinner when running', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: { command: 'sleep 10' }, running: true };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.querySelector('.chat-tool.running')).toBeInTheDocument();
    expect(container.querySelector('.chat-tool-spinner')).toBeInTheDocument();
  });

  test('shows duration when finished', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: { command: 'echo' }, duration_ms: 1500 };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.innerHTML).toContain('1.5s');
  });

  test('shows duration in ms for short operations', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: { command: 'echo' }, duration_ms: 200 };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.innerHTML).toContain('200ms');
  });

  test('expands detail on click', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: { command: 'echo hello' } };
    const { container } = render(<ToolUseBlock block={block} />);
    const header = container.querySelector('.chat-tool-header')!;
    fireEvent.click(header);
    const detail = container.querySelector('.chat-tool-detail') as HTMLElement;
    expect(detail.style.display).toBe('block');
  });

  test('collapses detail on second click', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: { command: 'echo hello' } };
    const { container } = render(<ToolUseBlock block={block} />);
    const header = container.querySelector('.chat-tool-header')!;
    fireEvent.click(header);
    fireEvent.click(header);
    const detail = container.querySelector('.chat-tool-detail') as HTMLElement;
    expect(detail.style.display).toBe('none');
  });

  test('renders Edit tool with diff view', () => {
    const block: Block = {
      type: 'tool_use',
      id: 4,
      tool: 'Edit',
      input: { file_path: '/tmp/foo.ts', old_string: 'old', new_string: 'new' },
    };
    const { container } = render(<ToolUseBlock block={block} />);
    const header = container.querySelector('.chat-tool-header')!;
    fireEvent.click(header);
    expect(container.innerHTML).toContain('tool-diff-del');
    expect(container.innerHTML).toContain('tool-diff-add');
  });

  test('renders Grep tool with pattern', () => {
    const block: Block = {
      type: 'tool_use',
      id: 4,
      tool: 'Grep',
      input: { pattern: 'TODO', path: '/src' },
    };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.innerHTML).toContain('/TODO/');
  });

  test('handles null input gracefully', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Unknown' };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.querySelector('.chat-tool')).toBeInTheDocument();
  });

  test('auto-expands Task tool when running', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Task', input: { prompt: 'do stuff' }, running: true };
    const { container } = render(<ToolUseBlock block={block} />);
    expect(container.querySelector('.chat-tool.expanded')).toBeInTheDocument();
  });
});

// =====================
// ToolGroupBlock
// =====================
describe('ToolGroupBlock', () => {
  test('renders group with label showing count', () => {
    const block: Block = {
      type: 'tool_group',
      id: 5,
      tools: [
        { type: 'tool_use', id: 100, tool: 'Read', input: { file_path: '/a.ts' } },
        { type: 'tool_use', id: 101, tool: 'Grep', input: { pattern: 'test' } },
      ],
    };
    const { container } = render(<ToolGroupBlock block={block} />);
    expect(container.querySelector('.chat-tool-group')).toBeInTheDocument();
    expect(container.innerHTML).toContain('2 parallel calls');
  });

  test('renders each tool inside the group', () => {
    const block: Block = {
      type: 'tool_group',
      id: 5,
      tools: [
        { type: 'tool_use', id: 100, tool: 'Read', input: { file_path: '/a.ts' } },
        { type: 'tool_use', id: 101, tool: 'Write', input: { file_path: '/b.ts', content: 'x' } },
      ],
    };
    const { container } = render(<ToolGroupBlock block={block} />);
    const tools = container.querySelectorAll('.chat-tool');
    expect(tools.length).toBe(2);
  });

  test('handles empty tools array', () => {
    const block: Block = { type: 'tool_group', id: 5, tools: [] };
    const { container } = render(<ToolGroupBlock block={block} />);
    expect(container.querySelector('.chat-tool-group')).toBeInTheDocument();
    expect(container.innerHTML).toContain('0 parallel calls');
  });
});

// =====================
// ToolResultBlock
// =====================
describe('ToolResultBlock', () => {
  test('renders null for empty content', () => {
    const block: Block = { type: 'tool_result', id: 6, content: '' };
    const { container } = render(<ToolResultBlock block={block} />);
    expect(container.innerHTML).toBe('');
  });

  test('renders short content directly', () => {
    const block: Block = { type: 'tool_result', id: 6, content: 'OK', tool: 'Edit' };
    const { container } = render(<ToolResultBlock block={block} />);
    expect(container.querySelector('.chat-tool-result')).toBeInTheDocument();
  });

  test('renders long content collapsed with char count', () => {
    const longContent = 'x'.repeat(300);
    const block: Block = { type: 'tool_result', id: 6, content: longContent, tool: 'Unknown' };
    const { container } = render(<ToolResultBlock block={block} />);
    expect(container.querySelector('.chat-tool-result.collapsed')).toBeInTheDocument();
    expect(container.innerHTML).toContain('300 chars');
  });

  test('expands collapsed result on click', () => {
    const longContent = 'x'.repeat(300);
    const block: Block = { type: 'tool_result', id: 6, content: longContent, tool: 'Unknown' };
    const { container } = render(<ToolResultBlock block={block} />);
    const header = container.querySelector('.chat-tool-result-header')!;
    fireEvent.click(header);
    expect(container.querySelector('.chat-tool-result.collapsed')).not.toBeInTheDocument();
  });

  test('renders Bash result with rich formatting', () => {
    const block: Block = { type: 'tool_result', id: 6, content: 'output line', tool: 'Bash' };
    const { container } = render(<ToolResultBlock block={block} />);
    expect(container.querySelector('.chat-tool-result')).toBeInTheDocument();
    expect(container.innerHTML).toContain('output line');
  });

  test('renders Read result with line numbers', () => {
    const block: Block = { type: 'tool_result', id: 6, content: 'line1\nline2', tool: 'Read', input: { file_path: '/test.ts' } };
    const { container } = render(<ToolResultBlock block={block} />);
    expect(container.querySelector('.chat-tool-result')).toBeInTheDocument();
    expect(container.innerHTML).toContain('test.ts');
  });
});

// =====================
// AgentBlock
// =====================
describe('AgentBlock', () => {
  test('renders agent header', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: { description: 'Test agent task' },
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.querySelector('.chat-agent')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Agent');
    expect(container.innerHTML).toContain('Test agent task');
  });

  test('shows running state', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: { description: 'Running task' },
      running: true,
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.querySelector('.chat-agent.running')).toBeInTheDocument();
    expect(container.querySelector('.chat-tool-spinner')).toBeInTheDocument();
  });

  test('auto-expands when running', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: { description: 'Auto expand' },
      running: true,
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.querySelector('.chat-agent.expanded')).toBeInTheDocument();
  });

  test('shows "Starting..." when running with no content', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: {},
      running: true,
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.innerHTML).toContain('Starting...');
  });

  test('shows "Completed" when not running with no content', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: {},
      running: false,
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    // Need to expand to see the body
    const header = container.querySelector('.chat-agent-header')!;
    fireEvent.click(header);
    expect(container.innerHTML).toContain('Completed');
  });

  test('renders sub-blocks inside agent', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: { description: 'Multi-step' },
      running: true,
      agent_blocks: [
        { type: 'tool_use', id: 70, tool: 'Bash', input: { command: 'echo hi' } },
        { type: 'assistant', id: 71, text: 'Sub-agent reply' },
      ],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.querySelector('.chat-tool')).toBeInTheDocument();
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });

  test('shows duration when finished', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: {},
      duration_ms: 5000,
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.innerHTML).toContain('5.0s');
  });

  test('shows tool count', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: {},
      agent_blocks: [
        { type: 'tool_use', id: 70, tool: 'Read', input: {} },
        { type: 'tool_use', id: 71, tool: 'Bash', input: {} },
        { type: 'assistant', id: 72, text: 'done' },
      ],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.innerHTML).toContain('2 tools');
  });

  test('shows subagent type badge', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: { subagent_type: 'research' },
      agent_blocks: [],
    };
    const { container } = render(<AgentBlock block={block} />);
    expect(container.innerHTML).toContain('research');
    expect(container.querySelector('.chat-agent-badge')).toBeInTheDocument();
  });

  test('toggles expansion on click', () => {
    const block: Block = {
      type: 'agent',
      id: 7,
      input: {},
      agent_blocks: [{ type: 'assistant', id: 70, text: 'sub' }],
    };
    const { container } = render(<AgentBlock block={block} />);
    const header = container.querySelector('.chat-agent-header')!;
    // Initially collapsed (not running)
    expect(container.querySelector('.chat-agent.expanded')).not.toBeInTheDocument();
    fireEvent.click(header);
    expect(container.querySelector('.chat-agent.expanded')).toBeInTheDocument();
    fireEvent.click(header);
    expect(container.querySelector('.chat-agent.expanded')).not.toBeInTheDocument();
  });
});

// =====================
// QuestionBlock
// =====================
describe('QuestionBlock', () => {
  test('renders question text and options', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      questions: [
        {
          question: 'Which option?',
          options: [
            { label: 'Option A' },
            { label: 'Option B' },
          ],
        },
      ],
    };
    renderWithCtx(<QuestionBlock block={block} />);
    expect(screen.getByText('Which option?')).toBeInTheDocument();
    expect(screen.getByText('Option A')).toBeInTheDocument();
    expect(screen.getByText('Option B')).toBeInTheDocument();
  });

  test('renders badge when not answered', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      questions: [{ question: 'Test?', options: [{ label: 'Yes' }] }],
    };
    const { container } = renderWithCtx(<QuestionBlock block={block} />);
    expect(container.querySelector('.chat-question-badge')).toBeInTheDocument();
    expect(container.innerHTML).toContain('asking a question');
  });

  test('renders "asking N questions" for multiple questions', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      questions: [
        { question: 'Q1?', options: [{ label: 'A' }] },
        { question: 'Q2?', options: [{ label: 'B' }] },
      ],
    };
    const { container } = renderWithCtx(<QuestionBlock block={block} />);
    expect(container.innerHTML).toContain('2 questions');
  });

  test('shows "Other..." button', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      questions: [{ question: 'Q?', options: [{ label: 'A' }] }],
    };
    renderWithCtx(<QuestionBlock block={block} />);
    expect(screen.getByText('Other...')).toBeInTheDocument();
  });

  test('clicking Other shows text input', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      questions: [{ question: 'Q?', options: [{ label: 'A' }] }],
    };
    const { container } = renderWithCtx(<QuestionBlock block={block} />);
    fireEvent.click(screen.getByText('Other...'));
    expect(container.querySelector('.chat-question-other-input')).toBeInTheDocument();
  });

  test('clicking option auto-submits for single-select', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      questions: [{ question: 'Pick one', options: [{ label: 'Alpha' }, { label: 'Beta' }] }],
    };
    const { container } = renderWithCtx(<QuestionBlock block={block} />);
    fireEvent.click(screen.getByText('Alpha'));
    // After answering, should show answered summary
    expect(container.querySelector('.chat-question-answered-summary')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Alpha');
  });

  test('renders answered state when block is pre-answered', () => {
    const block: Block = {
      type: 'question',
      id: 8,
      answered: true,
      questions: [{ question: 'Q?', options: [{ label: 'A' }] }],
    };
    const { container } = renderWithCtx(<QuestionBlock block={block} />);
    expect(container.querySelector('.chat-question-wrapper-answered')).toBeInTheDocument();
  });
});

// =====================
// CostBlock
// =====================
describe('CostBlock', () => {
  test('renders time and cost', () => {
    const block: Block = { type: 'cost', id: 9, seconds: 65, cost: 0.0523 };
    const { container } = render(<CostBlock block={block} />);
    expect(container.querySelector('.chat-cost')).toBeInTheDocument();
    expect(container.textContent).toContain('1m 5s');
    expect(container.textContent).toContain('$0.0523');
  });

  test('renders seconds only when no minutes', () => {
    const block: Block = { type: 'cost', id: 9, seconds: 45, cost: 0 };
    const { container } = render(<CostBlock block={block} />);
    expect(container.textContent).toBe('45s');
  });

  test('renders cost with 4 decimal places', () => {
    const block: Block = { type: 'cost', id: 9, seconds: 10, cost: 0.1234 };
    const { container } = render(<CostBlock block={block} />);
    expect(container.textContent).toContain('$0.1234');
  });

  test('does not show cost when cost is 0', () => {
    const block: Block = { type: 'cost', id: 9, seconds: 5, cost: 0 };
    const { container } = render(<CostBlock block={block} />);
    expect(container.textContent).toBe('5s');
    expect(container.textContent).not.toContain('$');
  });

  test('handles zero seconds', () => {
    const block: Block = { type: 'cost', id: 9, seconds: 0, cost: 0.01 };
    const { container } = render(<CostBlock block={block} />);
    expect(container.textContent).toContain('0s');
  });

  test('handles missing values', () => {
    const block: Block = { type: 'cost', id: 9 };
    const { container } = render(<CostBlock block={block} />);
    expect(container.querySelector('.chat-cost')).toBeInTheDocument();
    expect(container.textContent).toBe('0s');
  });
});

// =====================
// ErrorBlock
// =====================
describe('ErrorBlock', () => {
  test('renders error message', () => {
    const block: Block = { type: 'error', id: 10, message: 'Something went wrong' };
    const { container } = render(<ErrorBlock block={block} />);
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Something went wrong');
  });

  test('renders "Error:" prefix', () => {
    const block: Block = { type: 'error', id: 10, message: 'Test error' };
    const { container } = render(<ErrorBlock block={block} />);
    expect(container.innerHTML).toContain('Error:');
  });

  test('renders default message when no message', () => {
    const block: Block = { type: 'error', id: 10 };
    const { container } = render(<ErrorBlock block={block} />);
    expect(container.innerHTML).toContain('Unknown error');
  });
});

// =====================
// StreamingBlock
// =====================
describe('StreamingBlock', () => {
  test('renders with streaming cursor class', () => {
    const block: Block = { type: 'assistant', id: 11, text: 'Streaming content...' };
    const { container } = renderWithCtx(<StreamingBlock block={block} />);
    expect(container.querySelector('.chat-streaming-cursor')).toBeInTheDocument();
  });

  test('renders with chat-msg-assistant class', () => {
    const block: Block = { type: 'assistant', id: 11, text: 'Hello' };
    const { container } = renderWithCtx(<StreamingBlock block={block} />);
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });

  test('renders initial text content', () => {
    const block: Block = { type: 'assistant', id: 11, text: 'Initial text' };
    const { container } = renderWithCtx(<StreamingBlock block={block} />);
    expect(container.innerHTML).toContain('Initial text');
  });
});

// =====================
// ArtifactCard
// =====================
describe('ArtifactCard', () => {
  test('renders HTML artifact card with title and filename', () => {
    const { container } = render(
      <ArtifactCard artifact={{ filename: 'test-view.html', title: 'My View' }} />
    );
    expect(container.querySelector('.artifact-card')).toBeInTheDocument();
    expect(screen.getByText('My View')).toBeInTheDocument();
    expect(screen.getByText('test-view.html')).toBeInTheDocument();
  });

  test('renders markdown artifact with path', () => {
    const { container } = render(
      <ArtifactCard artifact={{ path: 'People/John.md', title: 'John Note' }} />
    );
    expect(container.querySelector('.artifact-card')).toBeInTheDocument();
    expect(screen.getByText('John Note')).toBeInTheDocument();
    expect(screen.getByText('People/John.md')).toBeInTheDocument();
  });

  test('dispatches views:open event on click for HTML', () => {
    const handler = vi.fn();
    window.addEventListener('views:open', handler);
    const { container } = render(
      <ArtifactCard artifact={{ filename: 'test.html', title: 'Test' }} />
    );
    fireEvent.click(container.querySelector('.artifact-card')!);
    expect(handler).toHaveBeenCalledTimes(1);
    window.removeEventListener('views:open', handler);
  });

  test('dispatches views:open event on click for markdown', () => {
    const handler = vi.fn();
    window.addEventListener('views:open', handler);
    const { container } = render(
      <ArtifactCard artifact={{ path: 'Test.md', title: 'Test' }} />
    );
    fireEvent.click(container.querySelector('.artifact-card')!);
    expect(handler).toHaveBeenCalledTimes(1);
    const detail = (handler.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.url).toContain('Test.md');
    window.removeEventListener('views:open', handler);
  });
});

// =====================
// PlanReviewBlock
// =====================
describe('PlanReviewBlock', () => {
  test('renders plan content', () => {
    const planBlock: Block = { type: 'plan', id: 12, content: 'Step 1: Do the thing' };
    const { container } = renderWithCtx(<PlanReviewBlock planBlock={planBlock} />);
    expect(container.querySelector('.chat-plan-review')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Step 1: Do the thing');
  });

  test('renders "Plan Ready for Review" header', () => {
    const planBlock: Block = { type: 'plan', id: 12, content: 'Plan here' };
    renderWithCtx(<PlanReviewBlock planBlock={planBlock} />);
    expect(screen.getByText('Plan Ready for Review')).toBeInTheDocument();
  });

  test('shows Approve and Request Changes buttons when not responded', () => {
    const planBlock: Block = { type: 'plan', id: 12, content: 'Plan' };
    renderWithCtx(<PlanReviewBlock planBlock={planBlock} />);
    expect(screen.getByText('Approve Plan')).toBeInTheDocument();
    expect(screen.getByText('Request Changes')).toBeInTheDocument();
  });

  test('clicking Approve sends message and shows responded label', () => {
    const sendFn = vi.fn();
    const planBlock: Block = { type: 'plan', id: 12, content: 'Plan' };
    const { container } = renderWithCtx(<PlanReviewBlock planBlock={planBlock} />, {}, sendFn);
    fireEvent.click(screen.getByText('Approve Plan'));
    expect(sendFn).toHaveBeenCalledWith('Proceed with this plan');
    expect(container.innerHTML).toContain('Plan approved');
    expect(container.querySelector('.chat-plan-review-responded')).toBeInTheDocument();
  });

  test('clicking Request Changes dispatches prefill event', () => {
    const handler = vi.fn();
    window.addEventListener('chat:prefill-input', handler);
    const planBlock: Block = { type: 'plan', id: 12, content: 'Plan' };
    renderWithCtx(<PlanReviewBlock planBlock={planBlock} />);
    fireEvent.click(screen.getByText('Request Changes'));
    expect(handler).toHaveBeenCalledTimes(1);
    const detail = (handler.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.text).toBe("I'd like to change: ");
    window.removeEventListener('chat:prefill-input', handler);
  });

  test('renders responded state when plan is pre-answered', () => {
    const planBlock: Block = { type: 'plan', id: 12, content: 'Plan', answered: true };
    const { container } = renderWithCtx(<PlanReviewBlock planBlock={planBlock} />);
    expect(container.querySelector('.chat-plan-review-responded')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Plan approved');
  });

  test('falls back to assistantBlock text when no plan content', () => {
    const planBlock: Block = { type: 'plan', id: 12 };
    const assistantBlock: Block = { type: 'assistant', id: 11, text: 'Fallback plan text' };
    const { container } = renderWithCtx(
      <PlanReviewBlock planBlock={planBlock} assistantBlock={assistantBlock} />
    );
    expect(container.innerHTML).toContain('Fallback plan text');
  });
});

// =====================
// BlockRenderer
// =====================
describe('BlockRenderer', () => {
  test('renders UserBlock for type "user"', () => {
    const block: Block = { type: 'user', id: 1, text: 'Hello' };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-msg-user')).toBeInTheDocument();
  });

  test('renders AssistantBlock for type "assistant"', () => {
    const block: Block = { type: 'assistant', id: 2, text: 'Reply' };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });

  test('renders ThinkingBlock for type "thinking"', () => {
    const block: Block = { type: 'thinking', id: 3, words: 5, preview: 'hmm' };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-thinking')).toBeInTheDocument();
  });

  test('renders ToolUseBlock for type "tool_use"', () => {
    const block: Block = { type: 'tool_use', id: 4, tool: 'Bash', input: {} };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-tool')).toBeInTheDocument();
  });

  test('renders ToolGroupBlock for type "tool_group"', () => {
    const block: Block = { type: 'tool_group', id: 5, tools: [] };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-tool-group')).toBeInTheDocument();
  });

  test('renders AgentBlock for type "agent"', () => {
    const block: Block = { type: 'agent', id: 6, input: {}, agent_blocks: [] };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-agent')).toBeInTheDocument();
  });

  test('renders QuestionBlock for type "question"', () => {
    const block: Block = { type: 'question', id: 7, questions: [] };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-question-wrapper')).toBeInTheDocument();
  });

  test('renders CostBlock for type "cost"', () => {
    const block: Block = { type: 'cost', id: 8, seconds: 10, cost: 0.01 };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-cost')).toBeInTheDocument();
  });

  test('renders ErrorBlock for type "error"', () => {
    const block: Block = { type: 'error', id: 9, message: 'oops' };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.innerHTML).toContain('oops');
  });

  test('renders null for type "_removed"', () => {
    const block: Block = { type: '_removed', id: 10 };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.innerHTML).toBe('');
  });

  test('renders null for type "loading"', () => {
    const block: Block = { type: 'loading', id: 11 };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.innerHTML).toBe('');
  });

  test('renders StreamingBlock for last assistant during streaming', () => {
    const block: Block = { type: 'assistant', id: 12, text: 'Streaming...' };
    const { container } = renderWithCtx(<BlockRenderer block={block} isStreaming={true} isLast={true} />);
    expect(container.querySelector('.chat-streaming-cursor')).toBeInTheDocument();
  });

  test('renders AssistantBlock (not streaming) for non-last assistant during streaming', () => {
    const block: Block = { type: 'assistant', id: 12, text: 'Old reply' };
    const { container } = renderWithCtx(<BlockRenderer block={block} isStreaming={true} isLast={false} />);
    expect(container.querySelector('.chat-streaming-cursor')).not.toBeInTheDocument();
    expect(container.querySelector('.chat-msg-assistant')).toBeInTheDocument();
  });

  test('renders plan block with active state', () => {
    const block: Block = { type: 'plan', id: 13, active: true };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-plan-banner')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Entered Plan Mode');
  });

  test('renders plan block with ready state', () => {
    const block: Block = { type: 'plan', id: 13, active: false };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-plan-banner-ready')).toBeInTheDocument();
    expect(container.innerHTML).toContain('Plan Ready for Review');
  });

  test('renders null for unknown type', () => {
    const block: Block = { type: 'unknown_xyz', id: 99 };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.innerHTML).toBe('');
  });

  test('renders ToolResultBlock for type "tool_result"', () => {
    const block: Block = { type: 'tool_result', id: 14, content: 'Result data', tool: 'Bash' };
    const { container } = renderWithCtx(<BlockRenderer block={block} />);
    expect(container.querySelector('.chat-tool-result')).toBeInTheDocument();
  });
});
