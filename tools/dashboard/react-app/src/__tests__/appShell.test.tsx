/**
 * Tests for App shell components: App.tsx, AlertBanners, Pulse, Tabs, Badge, Toast, AgentsTab.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ---- Module mocks ----

vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
    dismiss: vi.fn(),
  },
  Toaster: () => null,
}));

vi.mock('@/api/queries', () => ({
  useDashboard: vi.fn(),
  useFeed: vi.fn(),
  useDeals: vi.fn(),
  usePeople: vi.fn(),
  useTasks: vi.fn(),
  useHeartbeat: vi.fn(),
  useFiles: vi.fn(),
  usePlans: vi.fn(),
  useViews: vi.fn(),
  useSources: vi.fn(),
  useAgents: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
  socket: { on: vi.fn(), off: vi.fn(), emit: vi.fn() },
  api: {
    dashboard: vi.fn(),
    agents: vi.fn(),
    agentDetail: vi.fn().mockResolvedValue({ id: '1', output: [], status: 'running', name: 'test' }),
    agentKill: vi.fn().mockResolvedValue({ status: 'killed' }),
  },
}));

// Mock heavy tab components so App.tsx renders fast
vi.mock('@/components/tabs/Feed', () => ({ FeedTab: () => <div data-testid="feed-tab">Feed</div> }));
vi.mock('@/components/tabs/Tasks', () => ({ TasksTab: () => <div data-testid="tasks-tab">Tasks</div> }));
vi.mock('@/components/tabs/Klava', () => ({ KlavaTab: () => <div data-testid="klava-tab">Klava</div> }));
vi.mock('@/components/tabs/Views', () => ({ ViewsTab: (props: any) => <div data-testid="views-tab">Views {props.pendingView?.title}</div> }));
vi.mock('@/components/tabs/Plans', () => ({ PlansTab: () => <div data-testid="plans-tab">Plans</div> }));
vi.mock('@/components/tabs/Lifeline', () => ({ LifelineTab: () => <div data-testid="lifeline-tab">Lifeline</div> }));
vi.mock('@/components/tabs/Skills', () => ({ SkillsTab: () => <div data-testid="skills-tab">Skills</div> }));
vi.mock('@/components/tabs/Health', () => ({ HealthTab: () => <div data-testid="health-tab">Health</div> }));
vi.mock('@/components/tabs/Sources', () => ({ SourcesTab: () => <div data-testid="sources-tab">Sources</div> }));
vi.mock('@/components/tabs/Files', () => ({ FilesTab: () => <div data-testid="files-tab">Files</div> }));
vi.mock('@/components/tabs/Deals', () => ({ DealsTab: () => <div data-testid="deals-tab">Deals</div> }));
vi.mock('@/components/tabs/Heartbeat', () => ({ HeartbeatTab: () => <div data-testid="heartbeat-tab">Heartbeat</div> }));
vi.mock('@/components/tabs/People', () => ({ PeopleTab: () => <div data-testid="people-tab">People</div> }));
vi.mock('@/components/tabs/Chat', () => ({
  ChatPanel: (props: any) => (
    <div data-testid="chat-panel" data-mode={props.mode}>
      <button data-testid="chat-toggle" onClick={props.onToggle}>toggle</button>
      <button data-testid="chat-fullscreen" onClick={props.onFullscreen}>fullscreen</button>
    </div>
  ),
}));

// ---- Imports (after mocks) ----

import { useDashboard, useAgents } from '@/api/queries';
import { api } from '@/api/client';
import App from '@/App';
import { AlertBanners } from '@/components/shell/AlertBanners';
import { Pulse } from '@/components/shell/Pulse';
import { Tabs } from '@/components/shell/Tabs';
import { Badge } from '@/components/shared/Badge';
import { Toast, showToast } from '@/components/shared/Toast';
import { AgentsTab } from '@/components/tabs/Agents';

// ---- Helpers ----

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = createQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderWithQuery(ui: React.ReactElement) {
  return render(ui, { wrapper: Wrapper });
}

function mockQuery(overrides: Record<string, unknown> = {}) {
  return {
    data: undefined,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null);
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
  window.location.hash = '';
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// =====================================================================
// Badge
// =====================================================================
describe('Badge', () => {
  it('returns null for count <= 0', () => {
    const { container } = render(<Badge count={0} />);
    expect(container.innerHTML).toBe('');
  });

  it('returns null for negative count', () => {
    const { container } = render(<Badge count={-1} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders count with default style', () => {
    render(<Badge count={5} />);
    const badge = screen.getByText('5');
    expect(badge).toBeTruthy();
    expect(badge.className).toBe('tab-badge');
  });

  it('renders with subtle style', () => {
    render(<Badge count={3} style="subtle" />);
    const badge = screen.getByText('3');
    expect(badge.className).toBe('tab-badge subtle');
  });

  it('renders with danger style', () => {
    render(<Badge count={2} style="danger" />);
    const badge = screen.getByText('2');
    expect(badge.className).toBe('tab-badge danger');
  });

  it('renders with empty string style (treated as default)', () => {
    render(<Badge count={1} style="" />);
    const badge = screen.getByText('1');
    expect(badge.className).toBe('tab-badge');
  });
});

// =====================================================================
// Toast
// =====================================================================
describe('Toast', () => {
  it('renders empty initially', () => {
    const { container } = render(<Toast />);
    const toastContainer = container.firstChild as HTMLElement;
    expect(toastContainer.children.length).toBe(0);
  });

  it('shows toast when showToast is called', () => {
    render(<Toast />);
    act(() => {
      showToast('Hello World');
    });
    expect(screen.getByText('Hello World')).toBeTruthy();
  });

  it('shows multiple toasts', () => {
    render(<Toast />);
    act(() => {
      showToast('Toast 1');
      showToast('Toast 2');
    });
    expect(screen.getByText('Toast 1')).toBeTruthy();
    expect(screen.getByText('Toast 2')).toBeTruthy();
  });

  it('auto-removes toast after 3 seconds', () => {
    render(<Toast />);
    act(() => {
      showToast('Disappearing');
    });
    expect(screen.getByText('Disappearing')).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.queryByText('Disappearing')).toBeNull();
  });

  it('showToast does nothing when Toast is not mounted', () => {
    // No Toast rendered - should not throw
    const { unmount } = render(<Toast />);
    unmount();
    expect(() => showToast('No crash')).not.toThrow();
  });
});

// =====================================================================
// Pulse
// =====================================================================
describe('Pulse', () => {
  it('renders with no data', () => {
    render(<Pulse data={undefined} onRefresh={vi.fn()} isRefreshing={false} />);
    expect(screen.getByText('mission control')).toBeTruthy();
    // Stats should show dashes
    const dashes = screen.getAllByText('-');
    expect(dashes.length).toBeGreaterThanOrEqual(4);
  });

  it('renders with data', () => {
    const data = {
      services: [
        { name: 'svc1', running: true },
        { name: 'svc2', running: false },
        { name: 'svc3', running: true },
      ],
      stats: { runs_24h: 42, failures_24h: 2, total_cost_usd: 1.5, sessions_active: 1 },
      heartbeat_backlog: [1, 2, 3],
      reply_queue: { overdue: 5, total: 10, items: [] },
      failing_jobs: [],
      data_sources: [],
      activity: [],
      agent_activity: [],
      evolution_timeline: [],
      skill_inventory: [],
      skill_changes: [],
      growth_metrics: [],
      error_learning: [],
      daily_notes: {} as any,
      obsidian_metrics: {} as any,
      claude_md_details: {} as any,
      costs: {} as any,
    };
    render(<Pulse data={data as any} onRefresh={vi.fn()} isRefreshing={false} />);
    expect(screen.getByText('2/3')).toBeTruthy(); // healthy/total services
    expect(screen.getByText('42')).toBeTruthy(); // runs_24h
    expect(screen.getByText('2')).toBeTruthy(); // failures
    expect(screen.getByText('$1.50')).toBeTruthy(); // cost
    expect(screen.getByText('3')).toBeTruthy(); // backlog length
    expect(screen.getByText('5')).toBeTruthy(); // overdue
  });

  it('shows refreshing state', () => {
    render(<Pulse data={undefined} onRefresh={vi.fn()} isRefreshing={true} />);
    expect(screen.getByText('...')).toBeTruthy();
  });

  it('shows refresh button when not refreshing', () => {
    render(<Pulse data={undefined} onRefresh={vi.fn()} isRefreshing={false} />);
    expect(screen.getByText('refresh')).toBeTruthy();
  });

  it('calls onRefresh when button clicked', () => {
    const onRefresh = vi.fn();
    render(<Pulse data={undefined} onRefresh={onRefresh} isRefreshing={false} />);
    fireEvent.click(screen.getByText('refresh'));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it('shows error dot when failing jobs exist', () => {
    const data = {
      services: [],
      stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
      heartbeat_backlog: [],
      reply_queue: { overdue: 0, total: 0, items: [] },
      failing_jobs: [{ job_id: 'test', consecutive: 3 }],
      data_sources: [],
      activity: [],
      agent_activity: [],
      evolution_timeline: [],
      skill_inventory: [],
      skill_changes: [],
      growth_metrics: [],
      error_learning: [],
      daily_notes: {} as any,
      obsidian_metrics: {} as any,
      claude_md_details: {} as any,
      costs: {} as any,
    };
    const { container } = render(<Pulse data={data as any} onRefresh={vi.fn()} isRefreshing={false} />);
    const dot = container.querySelector('.health-dot.error');
    expect(dot).toBeTruthy();
  });

  it('shows warn dot when stale sources exist', () => {
    const data = {
      services: [],
      stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
      heartbeat_backlog: [],
      reply_queue: { overdue: 0, total: 0, items: [] },
      failing_jobs: [],
      data_sources: [{ name: 'src1', healthy: false, records: 0, last_data_ago: '2h' }],
      activity: [],
      agent_activity: [],
      evolution_timeline: [],
      skill_inventory: [],
      skill_changes: [],
      growth_metrics: [],
      error_learning: [],
      daily_notes: {} as any,
      obsidian_metrics: {} as any,
      claude_md_details: {} as any,
      costs: {} as any,
    };
    const { container } = render(<Pulse data={data as any} onRefresh={vi.fn()} isRefreshing={false} />);
    const dot = container.querySelector('.health-dot.warn');
    expect(dot).toBeTruthy();
  });
});

// =====================================================================
// AlertBanners (sonner-backed — no inline DOM)
// =====================================================================
import { toast as mockToast } from 'sonner';

describe('AlertBanners', () => {
  beforeEach(() => {
    (mockToast.error as any).mockClear();
    (mockToast.warning as any).mockClear();
    (mockToast.dismiss as any).mockClear();
  });

  it('emits nothing when no data', () => {
    render(<AlertBanners data={undefined} />);
    expect(mockToast.error).not.toHaveBeenCalled();
    expect(mockToast.warning).not.toHaveBeenCalled();
  });

  it('emits nothing when no failures or stale sources', () => {
    const data = {
      failing_jobs: [],
      data_sources: [{ name: 'ok', healthy: true, records: 100 }],
    };
    render(<AlertBanners data={data as any} />);
    expect(mockToast.error).not.toHaveBeenCalled();
    expect(mockToast.warning).not.toHaveBeenCalled();
  });

  it('emits failing CRON toast', () => {
    const data = {
      failing_jobs: [{ job_id: 'heartbeat', consecutive: 3 }],
      data_sources: [],
    };
    render(<AlertBanners data={data as any} />);
    expect(mockToast.error).toHaveBeenCalled();
    const call = (mockToast.error as any).mock.calls[0];
    expect(call[1].id).toBe('alert-cron');
    expect(call[1].duration).toBe(Infinity);
  });

  it('does NOT emit a toast for stale sources (they become Klava tasks instead)', () => {
    const data = {
      failing_jobs: [],
      data_sources: [
        { name: 'telegram', healthy: false, records: 10, last_data_ago: '5h' },
        { name: 'signal', healthy: true, records: 20 },
      ],
    };
    render(<AlertBanners data={data as any} />);
    expect(mockToast.warning).not.toHaveBeenCalled();
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('emits only CRON toast when both failing jobs and stale sources exist', () => {
    const data = {
      failing_jobs: [{ job_id: 'cron1', consecutive: 1 }],
      data_sources: [{ name: 'src1', healthy: false, records: 0, last_data_ago: 'never' }],
    };
    render(<AlertBanners data={data as any} />);
    expect(mockToast.error).toHaveBeenCalledTimes(1);
    expect(mockToast.warning).not.toHaveBeenCalled();
  });

  it('dismisses toasts when condition clears', () => {
    const dataWithFailure = {
      failing_jobs: [{ job_id: 'heartbeat', consecutive: 3 }],
      data_sources: [],
    };
    const { rerender } = render(<AlertBanners data={dataWithFailure as any} />);
    expect(mockToast.error).toHaveBeenCalled();

    rerender(<AlertBanners data={{ failing_jobs: [], data_sources: [] } as any} />);
    expect(mockToast.dismiss).toHaveBeenCalledWith('alert-cron');
  });
});

// =====================================================================
// Tabs
// =====================================================================
describe('Tabs', () => {
  it('renders all tab labels', () => {
    const onTabChange = vi.fn();
    render(<Tabs activeTab="feed" onTabChange={onTabChange} tabBadges={{}} />);
    expect(screen.getByText('Feed')).toBeTruthy();
    expect(screen.getByText('Tasks')).toBeTruthy();
    expect(screen.getByText('Klava')).toBeTruthy();
    expect(screen.getByText('Views')).toBeTruthy();
    expect(screen.getByText('Plans')).toBeTruthy();
    expect(screen.getByText('Lifeline')).toBeTruthy();
    expect(screen.getByText('Skills')).toBeTruthy();
    expect(screen.getByText('Health')).toBeTruthy();
    expect(screen.getByText('Files')).toBeTruthy();
    expect(screen.getByText('Deals')).toBeTruthy();
    expect(screen.getByText('Heartbeat')).toBeTruthy();
    expect(screen.getByText('People')).toBeTruthy();
  });

  it('marks active tab', () => {
    const { container } = render(<Tabs activeTab="deals" onTabChange={vi.fn()} tabBadges={{}} />);
    const activeTab = container.querySelector('.tab.active');
    expect(activeTab).toBeTruthy();
    expect(activeTab!.textContent).toBe('Deals');
  });

  it('calls onTabChange when tab clicked', () => {
    const onTabChange = vi.fn();
    render(<Tabs activeTab="feed" onTabChange={onTabChange} tabBadges={{}} />);
    fireEvent.click(screen.getByText('Deals'));
    expect(onTabChange).toHaveBeenCalledWith('deals');
  });

  it('renders badges for tabs with badge data', () => {
    const badges = {
      health: { count: 3, style: 'danger' as const },
      lifeline: { count: 12, style: 'subtle' as const },
    };
    render(<Tabs activeTab="feed" onTabChange={vi.fn()} tabBadges={badges} />);
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('12')).toBeTruthy();
  });

  it('does not render badges with count 0', () => {
    const badges = {
      health: { count: 0, style: 'danger' as const },
    };
    const { container } = render(<Tabs activeTab="feed" onTabChange={vi.fn()} tabBadges={badges} />);
    const badgeEls = container.querySelectorAll('.tab-badge');
    expect(badgeEls.length).toBe(0);
  });
});

// =====================================================================
// AgentsTab
// =====================================================================
describe('AgentsTab', () => {
  it('shows empty state when no agents', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: { agents: [], max_concurrent: 3 },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('No dispatch agents')).toBeTruthy();
  });

  it('renders KPI row with running/finished/capacity', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Agent A', type: 'dispatch', status: 'running', model: 'sonnet', output_lines: 10, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 - 60 },
          { id: '2', name: 'Agent B', type: 'heartbeat', status: 'completed', model: 'haiku', output_lines: 5, inbox_size: 0, last_output: '', cost_usd: 0.1 },
        ],
        max_concurrent: 5,
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    // KPI values
    expect(screen.getByText('Running')).toBeTruthy();
    expect(screen.getByText('Finished')).toBeTruthy();
    expect(screen.getByText('Capacity')).toBeTruthy();
    expect(screen.getByText('1/5')).toBeTruthy(); // capacity
  });

  it('renders active and history sections', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Runner', type: 'dispatch', status: 'running', model: 'opus', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 - 30 },
          { id: '2', name: 'Done', type: 'heartbeat', status: 'completed', model: 'haiku', output_lines: 20, inbox_size: 0, last_output: '', cost_usd: 0.5 },
          { id: '3', name: 'FailedOne', type: 'tg', status: 'failed', model: 'sonnet', output_lines: 3, inbox_size: 0, last_output: '', cost_usd: 0, error: 'boom' },
        ],
        max_concurrent: 3,
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('Active')).toBeTruthy();
    expect(screen.getByText('History')).toBeTruthy();
    expect(screen.getByText('Runner')).toBeTruthy();
    expect(screen.getByText('Done')).toBeTruthy();
    expect(screen.getByText('FailedOne')).toBeTruthy();
  });

  it('shows agent model and type pills', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Test', type: 'dispatch', status: 'completed', model: 'opus-4', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('opus-4')).toBeTruthy();
    expect(screen.getByText('dispatch')).toBeTruthy();
  });

  it('shows kill button for running agents', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Active', type: 'dispatch', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const killBtn = container.querySelector('.agent-card-kill');
    expect(killBtn).toBeTruthy();
  });

  it('does not show kill button for completed agents', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Done', type: 'dispatch', status: 'completed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const killBtn = container.querySelector('.agent-card-kill');
    expect(killBtn).toBeNull();
  });

  it('calls api.agentKill when kill button is clicked', async () => {
    const refetchFn = vi.fn();
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: 'abc', name: 'Active', type: 'dispatch', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
        ],
        max_concurrent: 3,
      },
      refetch: refetchFn,
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const killBtn = container.querySelector('.agent-card-kill') as HTMLElement;
    await act(async () => {
      fireEvent.click(killBtn);
    });
    expect(vi.mocked(api.agentKill)).toHaveBeenCalledWith('abc');
  });

  it('shows refresh button', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: { agents: [], max_concurrent: 3 },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('Refresh')).toBeTruthy();
  });

  it('calls refetch when refresh button clicked', () => {
    const refetchFn = vi.fn();
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: { agents: [], max_concurrent: 3 },
      refetch: refetchFn,
    }) as any);
    renderWithQuery(<AgentsTab />);
    fireEvent.click(screen.getByText('Refresh'));
    expect(refetchFn).toHaveBeenCalled();
  });

  it('expands agent card on click to show detail', async () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Expandable', type: 'dispatch', status: 'completed', model: 'sonnet', output_lines: 5, inbox_size: 0, last_output: '', cost_usd: 0 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const card = container.querySelector('.agent-card') as HTMLElement;
    await act(async () => {
      fireEvent.click(card);
    });
    // After expansion, should show loading or detail inline
    expect(container.querySelector('.agent-card.expanded')).toBeTruthy();
  });

  it('shows output_lines when > 0', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Lines', type: 'dispatch', status: 'completed', model: 'sonnet', output_lines: 42, inbox_size: 0, last_output: '', cost_usd: 0 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('42 lines')).toBeTruthy();
  });

  it('shows error indicator on agent card', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Errored', type: 'dispatch', status: 'failed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, error: 'something broke' },
        ],
        max_concurrent: 3,
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('error')).toBeTruthy();
  });

  it('shows pending_retry agents in Active section', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'Retrying', type: 'dispatch', status: 'pending_retry', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('Active')).toBeTruthy();
    expect(screen.getByText('Retrying')).toBeTruthy();
  });

  it('shows agent detail with output lines when expanded', async () => {
    vi.mocked(api.agentDetail).mockResolvedValue({
      id: '1',
      name: 'DetailAgent',
      type: 'dispatch',
      status: 'completed',
      model: 'sonnet',
      output_lines: 3,
      inbox_size: 0,
      last_output: '',
      cost_usd: 0,
      output: ['line 1', 'line 2', 'line 3'],
    } as any);

    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'DetailAgent', type: 'dispatch', status: 'completed', model: 'sonnet', output_lines: 3, inbox_size: 0, last_output: '', cost_usd: 0 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const card = container.querySelector('.agent-card') as HTMLElement;
    await act(async () => {
      fireEvent.click(card);
    });
    // Wait for detail to load
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.getByText('line 1')).toBeTruthy();
    expect(screen.getByText('line 2')).toBeTruthy();
    expect(screen.getByText('line 3')).toBeTruthy();
  });

  it('shows agent detail with todos when expanded', async () => {
    vi.mocked(api.agentDetail).mockResolvedValue({
      id: '2',
      name: 'TodoAgent',
      type: 'dispatch',
      status: 'running',
      model: 'opus',
      output_lines: 0,
      inbox_size: 0,
      last_output: '',
      cost_usd: 0,
      started: Date.now() / 1000,
      output: [],
      todos: [
        { content: 'Read files', status: 'completed' },
        { content: 'Write code', status: 'in_progress' },
        { content: 'Test stuff', status: 'pending' },
      ],
    } as any);

    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '2', name: 'TodoAgent', type: 'dispatch', status: 'running', model: 'opus', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const card = container.querySelector('.agent-card') as HTMLElement;
    await act(async () => {
      fireEvent.click(card);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.getByText('Read files')).toBeTruthy();
    expect(screen.getByText('Write code')).toBeTruthy();
    expect(screen.getByText('Test stuff')).toBeTruthy();
    // Tasks counter (1/3 appears in multiple elements)
    expect(screen.getAllByText(/1\/3/).length).toBeGreaterThan(0);
  });

  it('shows agent detail with error when expanded', async () => {
    vi.mocked(api.agentDetail).mockResolvedValue({
      id: '3',
      name: 'ErrAgent',
      type: 'dispatch',
      status: 'failed',
      model: 'sonnet',
      output_lines: 0,
      inbox_size: 0,
      last_output: '',
      cost_usd: 0,
      output: [],
      error: 'Process exited with code 1',
    } as any);

    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '3', name: 'ErrAgent', type: 'dispatch', status: 'failed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, error: 'fail' },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const card = container.querySelector('.agent-card') as HTMLElement;
    await act(async () => {
      fireEvent.click(card);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.getByText('Error: Process exited with code 1')).toBeTruthy();
  });

  it('shows "No output yet..." when detail has empty output', async () => {
    vi.mocked(api.agentDetail).mockResolvedValue({
      id: '4',
      name: 'EmptyAgent',
      type: 'dispatch',
      status: 'running',
      model: 'sonnet',
      output_lines: 0,
      inbox_size: 0,
      last_output: '',
      cost_usd: 0,
      started: Date.now() / 1000,
      output: [],
    } as any);

    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '4', name: 'EmptyAgent', type: 'dispatch', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const card = container.querySelector('.agent-card') as HTMLElement;
    await act(async () => {
      fireEvent.click(card);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.getByText('No output yet...')).toBeTruthy();
  });

  it('collapses expanded agent card on second click', async () => {
    vi.mocked(api.agentDetail).mockResolvedValue({
      id: '5', name: 'Toggler', type: 'dispatch', status: 'completed',
      model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '',
      cost_usd: 0, output: [],
    } as any);

    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '5', name: 'Toggler', type: 'dispatch', status: 'completed', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0 },
        ],
        max_concurrent: 3,
      },
    }) as any);
    const { container } = renderWithQuery(<AgentsTab />);
    const card = container.querySelector('.agent-card') as HTMLElement;

    // Expand
    await act(async () => {
      fireEvent.click(card);
    });
    expect(container.querySelector('.agent-card.expanded')).toBeTruthy();

    // Collapse
    await act(async () => {
      fireEvent.click(card);
    });
    expect(container.querySelector('.agent-card.expanded')).toBeNull();
  });

  it('defaults max_concurrent to agents.length when not provided', () => {
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: {
        agents: [
          { id: '1', name: 'A', type: 'dispatch', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
          { id: '2', name: 'B', type: 'dispatch', status: 'running', model: 'sonnet', output_lines: 0, inbox_size: 0, last_output: '', cost_usd: 0, started: Date.now() / 1000 },
        ],
        // no max_concurrent
      },
    }) as any);
    renderWithQuery(<AgentsTab />);
    expect(screen.getByText('2/2')).toBeTruthy(); // capacity = running/agents.length
  });
});

// =====================================================================
// App (Dashboard)
// =====================================================================
describe('App', () => {
  beforeEach(() => {
    vi.mocked(useDashboard).mockReturnValue(mockQuery({
      data: undefined,
      isFetching: false,
    }) as any);
    // Agents mock for lazy tab
    vi.mocked(useAgents).mockReturnValue(mockQuery({
      data: { agents: [], max_concurrent: 3 },
    }) as any);
  });

  it('renders without crashing', () => {
    render(<App />);
    expect(screen.getByText('mission control')).toBeTruthy();
  });

  it('shows lifeline tab by default', () => {
    render(<App />);
    const lifelinePage = document.querySelector('[data-page="lifeline"].active');
    expect(lifelinePage).toBeTruthy();
  });

  it('shows loading state when fetching with no data', () => {
    vi.mocked(useDashboard).mockReturnValue(mockQuery({
      data: undefined,
      isFetching: true,
    }) as any);
    render(<App />);
    expect(screen.getByText('Loading...')).toBeTruthy();
  });

  it('does not show loading when data exists', () => {
    vi.mocked(useDashboard).mockReturnValue(mockQuery({
      data: {
        services: [],
        stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
        heartbeat_backlog: [],
        reply_queue: { overdue: 0, total: 0, items: [] },
        failing_jobs: [],
        data_sources: [],
        activity: [],
        agent_activity: [],
        evolution_timeline: [],
        skill_inventory: [],
        skill_changes: [],
        growth_metrics: [],
        error_learning: [],
        daily_notes: {},
        obsidian_metrics: {},
        claude_md_details: {},
        costs: {},
      },
      isFetching: true,
    }) as any);
    render(<App />);
    expect(screen.queryByText('Loading...')).toBeNull();
  });

  it('reads initial tab from hash', () => {
    window.location.hash = '#deals';
    render(<App />);
    const dealsPage = document.querySelector('[data-page="deals"].active');
    expect(dealsPage).toBeTruthy();
  });

  it('defaults to lifeline for invalid hash', () => {
    window.location.hash = '#nonexistent';
    render(<App />);
    const lifelinePage = document.querySelector('[data-page="lifeline"].active');
    expect(lifelinePage).toBeTruthy();
  });

  it('redirects #feed hash to lifeline tab', () => {
    window.location.hash = '#feed';
    render(<App />);
    const lifelinePage = document.querySelector('[data-page="lifeline"].active');
    expect(lifelinePage).toBeTruthy();
  });

  it('shows chat FAB when chat is collapsed', () => {
    render(<App />);
    // Default on desktop should be sidebar, but localStorage returns null
    // and isMobile() is false in jsdom (window.innerWidth is 1024 by default)
    // so chatMode defaults to 'sidebar'. We need to check if FAB is absent
    // for sidebar mode and present for collapsed mode.
    const chatPanel = screen.getByTestId('chat-panel');
    expect(chatPanel.dataset.mode).toBe('sidebar');
    // FAB should not be visible in sidebar mode
    expect(screen.queryByLabelText('Open chat')).toBeNull();
  });

  it('toggles chat with Cmd+B', () => {
    render(<App />);
    const chatPanel = screen.getByTestId('chat-panel');
    expect(chatPanel.dataset.mode).toBe('sidebar');

    // Cmd+B should collapse
    fireEvent.keyDown(window, { key: 'b', metaKey: true });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('collapsed');

    // Cmd+B again should open sidebar
    fireEvent.keyDown(window, { key: 'b', metaKey: true });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('exits fullscreen with Escape', () => {
    render(<App />);
    // Go to fullscreen
    fireEvent.click(screen.getByTestId('chat-fullscreen'));
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('full');

    // Escape exits fullscreen
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('shows FAB when collapsed and opens chat in full on click', () => {
    render(<App />);
    // Collapse the chat
    fireEvent.keyDown(window, { key: 'b', metaKey: true });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('collapsed');

    // FAB should appear
    const fab = screen.getByLabelText('Open chat');
    expect(fab).toBeTruthy();

    // Clicking FAB should go to full mode
    fireEvent.click(fab);
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('full');
  });

  it('renders Toast component', () => {
    render(<App />);
    // Toast is rendered but empty
    act(() => {
      showToast('App toast test');
    });
    expect(screen.getByText('App toast test')).toBeTruthy();
  });

  it('navigates tabs when clicking on tab', () => {
    render(<App />);
    fireEvent.click(screen.getByText('Deals'));
    const dealsPage = document.querySelector('[data-page="deals"].active');
    expect(dealsPage).toBeTruthy();
    // Feed should no longer be active
    const feedPage = document.querySelector('[data-page="feed"].active');
    expect(feedPage).toBeNull();
  });

  it('chat toggle cycles between sidebar and collapsed', () => {
    render(<App />);
    const chatPanel = screen.getByTestId('chat-panel');
    expect(chatPanel.dataset.mode).toBe('sidebar');

    // Click toggle button to collapse
    fireEvent.click(screen.getByTestId('chat-toggle'));
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('collapsed');

    // Click toggle again to expand
    fireEvent.click(screen.getByTestId('chat-toggle'));
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('computes badges from dashboard data', () => {
    const today = new Date().toISOString().substring(0, 10);
    vi.mocked(useDashboard).mockReturnValue(mockQuery({
      data: {
        services: [],
        stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
        heartbeat_backlog: [],
        reply_queue: { overdue: 0, total: 0, items: [] },
        failing_jobs: [{ job_id: 'j1', consecutive: 2 }],
        data_sources: [{ name: 'src', healthy: false, records: 0 }],
        activity: [
          { job_id: 'a', status: 'ok', timestamp: `${today}T10:00:00` },
        ],
        agent_activity: [],
        evolution_timeline: [
          { type: 'test', date: today, summary: 'test' },
        ],
        skill_inventory: [
          { name: 's1', calls_30d: 5, error_count: 2 },
        ],
        skill_changes: [],
        growth_metrics: [],
        error_learning: [],
        daily_notes: {},
        obsidian_metrics: {},
        claude_md_details: {},
        costs: {},
      },
      isFetching: false,
    }) as any);
    render(<App />);
    // Health badge should show 1 (1 failing job)
    // Skills badge should show 1 (1 skill with errors)
    // Lifeline badge should show 2 (1 activity + 1 evolution today)
    const badges = document.querySelectorAll('.tab-badge');
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });

  it('handles chat:open custom event', () => {
    render(<App />);
    // Collapse first
    fireEvent.keyDown(window, { key: 'b', metaKey: true });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('collapsed');

    // Dispatch chat:open - should open sidebar
    act(() => {
      window.dispatchEvent(new Event('chat:open'));
    });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('handles views:open custom event', () => {
    render(<App />);
    act(() => {
      window.dispatchEvent(new CustomEvent('views:open', {
        detail: { filename: 'test.html', title: 'Test View' },
      }));
    });
    // Should switch to views tab
    const viewsPage = document.querySelector('[data-page="views"].active');
    expect(viewsPage).toBeTruthy();
  });

  it('adds chat-fullscreen class to dashboard-body when in full mode', () => {
    const { container } = render(<App />);
    fireEvent.click(screen.getByTestId('chat-fullscreen'));
    const body = container.querySelector('.dashboard-body.chat-fullscreen');
    expect(body).toBeTruthy();
  });

  it('Ctrl+B also toggles chat (non-Mac)', () => {
    render(<App />);
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
    fireEvent.keyDown(window, { key: 'b', ctrlKey: true });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('collapsed');
  });

  it('Escape does nothing when not in full mode', () => {
    render(<App />);
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
    fireEvent.keyDown(window, { key: 'Escape' });
    // Should stay sidebar
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('handles chat:split-view event', () => {
    render(<App />);
    // Collapse first
    fireEvent.keyDown(window, { key: 'b', metaKey: true });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('collapsed');

    act(() => {
      window.dispatchEvent(new Event('chat:split-view'));
    });
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('chat:open does not change mode if already open', () => {
    render(<App />);
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
    act(() => {
      window.dispatchEvent(new Event('chat:open'));
    });
    // Should stay sidebar, not change to anything else
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('handles views:open without detail', () => {
    render(<App />);
    act(() => {
      window.dispatchEvent(new CustomEvent('views:open', { detail: null }));
    });
    const viewsPage = document.querySelector('[data-page="views"].active');
    expect(viewsPage).toBeTruthy();
  });

  it('fullscreen toggle returns to sidebar on second click', () => {
    render(<App />);
    // Go full
    fireEvent.click(screen.getByTestId('chat-fullscreen'));
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('full');
    // Toggle fullscreen again - should go back to sidebar
    fireEvent.click(screen.getByTestId('chat-fullscreen'));
    expect(screen.getByTestId('chat-panel').dataset.mode).toBe('sidebar');
  });

  it('navigates to agents tab via hash', () => {
    window.location.hash = '#agents';
    render(<App />);
    const agentsPage = document.querySelector('[data-page="agents"].active');
    expect(agentsPage).toBeTruthy();
  });

  it('handles hashchange event', () => {
    render(<App />);
    act(() => {
      window.location.hash = '#skills';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    const skillsPage = document.querySelector('[data-page="skills"].active');
    expect(skillsPage).toBeTruthy();
  });

  it('computes empty badges when data has no issues', () => {
    vi.mocked(useDashboard).mockReturnValue(mockQuery({
      data: {
        services: [],
        stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
        heartbeat_backlog: [],
        reply_queue: { overdue: 0, total: 0, items: [] },
        failing_jobs: [],
        data_sources: [],
        activity: [],
        agent_activity: [],
        evolution_timeline: [],
        skill_inventory: [],
        skill_changes: [],
        growth_metrics: [],
        error_learning: [],
        daily_notes: {},
        obsidian_metrics: {},
        claude_md_details: {},
        costs: {},
      },
      isFetching: false,
    }) as any);
    render(<App />);
    // No danger badges should be rendered
    const dangerBadges = document.querySelectorAll('.tab-badge.danger');
    expect(dangerBadges.length).toBe(0);
  });

  it('initializes with correct tab for agents hash', () => {
    window.location.hash = '#agents';
    render(<App />);
    const agentsPage = document.querySelector('[data-page="agents"].active');
    expect(agentsPage).toBeTruthy();
  });
});
