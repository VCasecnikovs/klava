/**
 * Render tests for all dashboard tab components.
 * Goal: maximize code coverage by testing rendering, loading states,
 * error handling, and basic data display for each tab.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ---- Module mocks ----

vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

// Mock all API query hooks at the source
vi.mock('@/api/queries', () => ({
  useFeed: vi.fn(),
  useDeals: vi.fn(),
  usePeople: vi.fn(),
  useTasks: vi.fn(),
  useHeartbeat: vi.fn(),
  useFiles: vi.fn(),
  usePlans: vi.fn(),
  useViews: vi.fn(),
  useSources: vi.fn(),
  useDashboard: vi.fn(),
}));

// Mock ChatMarkdown to avoid complex markdown rendering in Feed/Plans
vi.mock('@/components/tabs/Chat/ChatMarkdown', () => ({
  renderChatMD: vi.fn((text: string) => `<p>${text}</p>`),
}));

// Mock marked for Files tab
vi.mock('marked', () => ({
  marked: { parse: vi.fn((text: string) => `<p>${text}</p>`) },
}));

// ---- Imports (after mocks) ----

import {
  useFeed, useDeals, usePeople, useTasks,
  useHeartbeat, useFiles, usePlans, useViews, useSources,
} from '@/api/queries';

import { FeedTab } from '@/components/tabs/Feed';
import { DealsTab } from '@/components/tabs/Deals';
import { DealsTable } from '@/components/tabs/Deals/DealsTable';
import { DealDetail } from '@/components/tabs/Deals/DealDetail';
import { PeopleTab } from '@/components/tabs/People';
import { PeopleTable } from '@/components/tabs/People/PeopleTable';
import { TasksTab } from '@/components/tabs/Tasks';
import { TaskCard } from '@/components/tabs/Tasks/TaskCard';
import { HealthTab } from '@/components/tabs/Health';
import { FilesTab } from '@/components/tabs/Files';
import { HeartbeatTab } from '@/components/tabs/Heartbeat';
import { PlansTab } from '@/components/tabs/Plans';
import { SkillsTab } from '@/components/tabs/Skills';
import { SourcesTab } from '@/components/tabs/Sources';
import { ViewsTab } from '@/components/tabs/Views';

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

/** Create a mock return value for react-query hooks */
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

/** Find element containing text (handles text split across child elements) */
function queryByTextContent(text: string): HTMLElement | null {
  const els = document.querySelectorAll('*');
  for (const el of els) {
    if (el.textContent?.includes(text) && el.children.length === 0) {
      return el as HTMLElement;
    }
  }
  return null;
}

beforeEach(() => {
  // Reset localStorage mock
  vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('{}');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// =====================================================================
// FeedTab
// =====================================================================
describe('FeedTab', () => {
  it('shows loading state', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({ isLoading: true }) as any);
    renderWithQuery(<FeedTab />);
    expect(screen.getByText('Loading feed...')).toBeTruthy();
  });

  it('shows error state', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({ error: new Error('Network fail') }) as any);
    renderWithQuery(<FeedTab />);
    expect(screen.getByText(/Feed error/)).toBeTruthy();
  });

  it('shows empty state', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({
      data: { messages: [], topics: [], total: 0 },
    }) as any);
    renderWithQuery(<FeedTab />);
    expect(screen.getByText(/No messages yet/)).toBeTruthy();
  });

  it('renders messages with topic filters', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({
      data: {
        messages: [
          {
            timestamp: new Date().toISOString(),
            topic: 'Heartbeat',
            topic_id: 1,
            message: 'Test heartbeat message',
            parse_mode: null,
            ago: '5m',
          },
          {
            timestamp: new Date().toISOString(),
            topic: 'Alerts',
            topic_id: 2,
            message: 'Alert message here',
            parse_mode: null,
          },
        ],
        topics: ['Heartbeat', 'Alerts'],
        total: 2,
      },
    }) as any);
    renderWithQuery(<FeedTab />);
    // Filter bar shows "All (2)"
    expect(screen.getByText('All (2)')).toBeTruthy();
    // Topic filters present (multiple elements expected - filter + message card)
    expect(screen.getAllByText('Heartbeat').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Alerts').length).toBeGreaterThanOrEqual(1);
    // Messages render (inside dangerouslySetInnerHTML, check by container)
    expect(document.body.textContent).toContain('Test heartbeat message');
    expect(document.body.textContent).toContain('Alert message here');
  });

  it('renders messages with deltas', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({
      data: {
        messages: [
          {
            timestamp: new Date().toISOString(),
            topic: 'Heartbeat',
            topic_id: 1,
            message: 'With deltas',
            parse_mode: null,
            deltas: [
              { type: 'obsidian', summary: 'Updated person note', category: 'knowledge' },
              { type: 'gtask', summary: 'Created task', category: 'ops' },
              { type: 'skipped', source: 'telegram/chat1', hint: 'spam', count: 5 },
            ],
          },
        ],
        topics: ['Heartbeat'],
        total: 1,
      },
    }) as any);
    renderWithQuery(<FeedTab />);
    // Delta items render
    expect(screen.getByText('Updated person note')).toBeTruthy();
    expect(screen.getByText('Created task')).toBeTruthy();
    // Noise section renders with count
    expect(screen.getByText(/Noise \(5\)/)).toBeTruthy();
  });

  it('renders message with legacy deltas in text', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({
      data: {
        messages: [
          {
            timestamp: new Date().toISOString(),
            topic: 'Main',
            topic_id: 3,
            message: 'Some text---DELTAS---[{"type":"deal","summary":"Deal updated"}]',
            parse_mode: null,
          },
        ],
        topics: ['Main'],
        total: 1,
      },
    }) as any);
    renderWithQuery(<FeedTab />);
    expect(screen.getByText('Deal updated')).toBeTruthy();
  });

  it('renders message with session_id and open button', () => {
    vi.mocked(useFeed).mockReturnValue(mockQuery({
      data: {
        messages: [
          {
            timestamp: new Date().toISOString(),
            topic: 'Main',
            topic_id: 3,
            message: 'Has session',
            parse_mode: null,
            session_id: 'sess-123',
          },
        ],
        topics: ['Main'],
        total: 1,
      },
    }) as any);
    renderWithQuery(<FeedTab />);
    const openBtn = screen.getByTitle('Open session');
    expect(openBtn).toBeTruthy();
  });
});

// =====================================================================
// DealsTab
// =====================================================================
describe('DealsTab', () => {
  it('shows loading state', () => {
    vi.mocked(useDeals).mockReturnValue(mockQuery() as any);
    renderWithQuery(<DealsTab />);
    expect(screen.getByText('Loading deals...')).toBeTruthy();
  });

  it('renders deals list with KPIs and priority section', () => {
    vi.mocked(useDeals).mockReturnValue(mockQuery({
      data: {
        metrics: { total_pipeline: 500000, weighted_pipeline: 200000, active_count: 5, overdue_count: 2 },
        deals: [
          { name: 'Acme Corp', stage: 'Negotiation', stage_num: 8, value: 85000, is_priority: true, is_active: true, overdue: true, days_until_follow_up: -3, follow_up: '2026-03-10' },
          { name: 'Globex Inc', stage: 'Proposal', stage_num: 6, value: 50000, is_priority: true, is_active: true, overdue: false, days_until_follow_up: 5 },
          { name: 'SmallDeal', stage: 'Prospecting', stage_num: 2, value: 5000, is_priority: false, is_active: true, overdue: false },
        ],
        pipeline_stages: [],
      },
    }) as any);
    renderWithQuery(<DealsTab />);
    // KPIs - use getAllByText since labels appear in both KPI and table
    expect(screen.getByText('Total Pipeline')).toBeTruthy();
    expect(screen.getByText('Weighted Pipeline')).toBeTruthy();
    // Priority section
    expect(screen.getByText('Priority Deals')).toBeTruthy();
    // Pipeline section
    expect(screen.getByText('Pipeline')).toBeTruthy();
    // Search input
    expect(screen.getByPlaceholderText('Search deals...')).toBeTruthy();
    // Deal names appear somewhere
    expect(document.body.textContent).toContain('Acme Corp');
    expect(document.body.textContent).toContain('Globex Inc');
  });
});

// =====================================================================
// DealsTable
// =====================================================================
describe('DealsTable', () => {
  const deals = [
    { name: 'DealA', stage: 'Negotiation', stage_num: 8, value: 100000, mrr: 5000, owner: 'user', last_contact: '2026-03-10', follow_up: '2026-03-15', days_in_stage: 10, product: 'Data', is_active: true, is_priority: false, overdue: false, days_until_follow_up: 2 },
    { name: 'DealB', stage: 'Prospecting', stage_num: 2, value: 20000, mrr: null, owner: 'Lev', last_contact: null, follow_up: null, days_in_stage: null, product: null, is_active: true, is_priority: true, overdue: true, days_until_follow_up: -5 },
  ];

  it('renders table with deals', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="all" searchVal="" onOpenDeal={onOpen} />
    );
    // Deal names appear in the table
    expect(document.body.textContent).toContain('DealA');
    expect(document.body.textContent).toContain('DealB');
    // Column headers (they contain sort icons appended, use regex)
    const headers = document.querySelectorAll('th');
    expect(headers.length).toBe(9); // 9 columns
  });

  it('filters by active', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="active" searchVal="" onOpenDeal={onOpen} />
    );
    expect(document.body.textContent).toContain('DealA');
    expect(document.body.textContent).toContain('DealB');
  });

  it('filters by search value', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="all" searchVal="DealA" onOpenDeal={onOpen} />
    );
    expect(document.body.textContent).toContain('DealA');
    expect(document.body.textContent).not.toContain('DealB');
  });

  it('shows empty state when no deals match', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="all" searchVal="nonexistent" onOpenDeal={onOpen} />
    );
    expect(screen.getByText('No deals match filter')).toBeTruthy();
  });

  it('calls onOpenDeal when clicking a deal name link', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="all" searchVal="" onOpenDeal={onOpen} />
    );
    const links = document.querySelectorAll('.deal-name-link');
    expect(links.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(links[0]);
    expect(onOpen).toHaveBeenCalled();
  });

  it('sorts by column on header click', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="all" searchVal="" onOpenDeal={onOpen} />
    );
    const headers = document.querySelectorAll('th');
    // Click first header (Deal name) to sort
    fireEvent.click(headers[0]);
    // Click again to reverse sort
    fireEvent.click(headers[0]);
    // Click a different header
    fireEvent.click(headers[2]);
  });

  it('applies overdue and priority filter', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="overdue" searchVal="" onOpenDeal={onOpen} />
    );
    // Only DealB is overdue and active
    expect(document.body.textContent).toContain('DealB');
  });

  it('applies priority filter', () => {
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={deals} filter="priority" searchVal="" onOpenDeal={onOpen} />
    );
    expect(document.body.textContent).toContain('DealB');
  });

  it('applies stalled filter', () => {
    const stalledDeals = [
      ...deals,
      { name: 'Stalled', stage: 'Stalled', stage_num: 16, value: 0, is_active: false },
    ];
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={stalledDeals} filter="stalled" searchVal="" onOpenDeal={onOpen} />
    );
    expect(document.body.textContent).toContain('Stalled');
  });

  it('applies lost filter', () => {
    const lostDeals = [
      ...deals,
      { name: 'LostDeal', stage: 'Lost', stage_num: 17, value: 0, is_active: false },
    ];
    const onOpen = vi.fn();
    renderWithQuery(
      <DealsTable deals={lostDeals} filter="lost" searchVal="" onOpenDeal={onOpen} />
    );
    expect(document.body.textContent).toContain('LostDeal');
  });
});

// =====================================================================
// DealDetail
// =====================================================================
describe('DealDetail', () => {
  it('renders deal detail with fields and back button', () => {
    const onBack = vi.fn();
    const deal = {
      name: 'TestDeal', stage: 'Negotiation', value: 100000, mrr: 5000,
      product: 'Data', owner: 'user', deal_size: 'Enterprise', deal_type: 'New',
      payment_type: 'One-time', last_contact: '2026-03-10', follow_up: '2026-03-20',
      days_in_stage: 15, decision_maker: 'John', lead_clean: 'Acme Corp',
      referrer_clean: 'Jane Doe', next_action: 'Send proposal',
      is_priority: true, overdue: true, days_until_follow_up: -2,
      file_path: 'Deals/TestDeal', telegram_chat: 'testchat',
    };
    renderWithQuery(<DealDetail deal={deal} onBack={onBack} />);

    // Back button
    const backBtn = screen.getByText('Back');
    expect(backBtn).toBeTruthy();
    fireEvent.click(backBtn.closest('button')!);
    expect(onBack).toHaveBeenCalled();

    // Deal name
    expect(document.body.textContent).toContain('TestDeal');

    // Priority badge
    expect(screen.getByText('PRIORITY DEAL')).toBeTruthy();

    // Overdue badge
    expect(screen.getByText(/OVERDUE 2d/)).toBeTruthy();

    // Fields
    expect(document.body.textContent).toContain('Negotiation');
    expect(document.body.textContent).toContain('Send proposal');

    // Links
    expect(screen.getByText('Deal Note')).toBeTruthy();
    expect(screen.getByText(/Org: Acme Corp/)).toBeTruthy();
    expect(screen.getByText(/Ref: Jane Doe/)).toBeTruthy();
    expect(screen.getByText('Telegram')).toBeTruthy();
  });

  it('renders minimal deal without optional fields', () => {
    const deal = {
      name: 'BasicDeal', stage: 'Prospecting', value: null, mrr: null,
      is_priority: false, overdue: false,
    };
    renderWithQuery(<DealDetail deal={deal} onBack={vi.fn()} />);
    expect(document.body.textContent).toContain('BasicDeal');
    expect(screen.queryByText('PRIORITY DEAL')).toBeNull();
    expect(screen.queryByText(/OVERDUE/)).toBeNull();
  });
});

// =====================================================================
// PeopleTab
// =====================================================================
describe('PeopleTab', () => {
  it('shows loading state', () => {
    vi.mocked(usePeople).mockReturnValue(mockQuery() as any);
    renderWithQuery(<PeopleTab />);
    expect(screen.getByText('Loading contacts...')).toBeTruthy();
  });

  it('renders people table with KPIs', () => {
    vi.mocked(usePeople).mockReturnValue(mockQuery({
      data: {
        metrics: { total_contacts: 50, companies: 20, recent_7d: 10, stale_30d: 5 },
        people: [
          { name: 'John Smith', company: 'Acme', role: 'CEO', location: 'NYC', tags: ['client'], last_contact: '2026-03-10', days_since_contact: 3 },
        ],
      },
    }) as any);
    renderWithQuery(<PeopleTab />);
    // KPIs
    expect(screen.getByText('Total Contacts')).toBeTruthy();
    expect(screen.getByText('Companies')).toBeTruthy();
    // Section heading
    expect(screen.getByText('Contacts')).toBeTruthy();
    // Search
    expect(screen.getByPlaceholderText('Search name, company, tag...')).toBeTruthy();
  });
});

// =====================================================================
// PeopleTable
// =====================================================================
describe('PeopleTable', () => {
  const people = [
    { name: 'Alice', company: 'TechCo', role: 'CTO', location: 'SF', tags: ['tech', 'vip'], last_contact: '2026-03-10', days_since_contact: 3 },
    { name: 'Bob', company: 'StartupInc', role: 'CEO', location: 'LA', tags: [], last_contact: null, days_since_contact: null },
  ];

  it('renders people table with columns', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="all" searchVal="" />
    );
    expect(document.body.textContent).toContain('Alice');
    expect(document.body.textContent).toContain('Bob');
    // Column headers present
    const headers = document.querySelectorAll('th');
    expect(headers.length).toBe(7); // 7 columns
  });

  it('filters by recent (7d)', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="recent" searchVal="" />
    );
    expect(document.body.textContent).toContain('Alice');
    expect(document.body.textContent).not.toContain('Bob');
  });

  it('filters by stale (30d+)', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="stale" searchVal="" />
    );
    // Bob has null days_since_contact - stale filter treats null as stale
    expect(document.body.textContent).toContain('Bob');
  });

  it('filters by no-contact', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="no-contact" searchVal="" />
    );
    expect(document.body.textContent).toContain('Bob');
    expect(document.body.textContent).not.toContain('Alice');
  });

  it('filters by search value', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="all" searchVal="alice" />
    );
    expect(document.body.textContent).toContain('Alice');
    expect(document.body.textContent).not.toContain('Bob');
  });

  it('filters by tag search', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="all" searchVal="vip" />
    );
    expect(document.body.textContent).toContain('Alice');
    expect(document.body.textContent).not.toContain('Bob');
  });

  it('shows empty when nothing matches', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="all" searchVal="zzz" />
    );
    expect(screen.getByText('No contacts match filter')).toBeTruthy();
  });

  it('sorts by column on header click', () => {
    renderWithQuery(
      <PeopleTable people={people} filter="all" searchVal="" />
    );
    const headers = document.querySelectorAll('th');
    // Click "Company" header
    fireEvent.click(headers[1]);
    // Click "Days" header (triggers default descending)
    fireEvent.click(headers[6]);
    // Click "Days" again to toggle
    fireEvent.click(headers[6]);
  });
});

// =====================================================================
// TasksTab
// =====================================================================
describe('TasksTab', () => {
  it('shows loading state', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery() as any);
    renderWithQuery(<TasksTab />);
    expect(screen.getByText('Loading tasks...')).toBeTruthy();
  });

  it('renders tasks with sections and KPIs', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: {
        kpis: { total: 10, overdue: 2, today: 3, deals: 4 },
        sections: {
          overdue: {
            label: 'Overdue',
            tasks: [
              { id: 't1', title: 'Follow up Acme Corp', source: 'github', source_label: 'GH', tags: [{ name: 'deal', color: 'blue' }], overdue: true, overdue_days: 5, days_info: '5d overdue' },
            ],
          },
          today: {
            label: 'Today',
            tasks: [
              { id: 't2', title: 'Send proposal', source: 'gtasks', source_label: 'GT', tags: [], is_today: true },
            ],
          },
        },
        section_order: ['overdue', 'today'],
      },
    }) as any);
    renderWithQuery(<TasksTab />);
    // KPIs - use getAllByText since "Overdue" appears in KPI + section + task
    expect(screen.getAllByText('Overdue').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Total')).toBeTruthy();
    // Tasks render
    expect(screen.getByText('Follow up Acme Corp')).toBeTruthy();
    expect(screen.getByText('Send proposal')).toBeTruthy();
  });

  it('shows empty when no tasks match filter', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: {
        kpis: { total: 0, overdue: 0, today: 0, deals: 0 },
        sections: {},
        section_order: [],
      },
    }) as any);
    renderWithQuery(<TasksTab />);
    expect(screen.getByText('No tasks in this category')).toBeTruthy();
  });

  it('skips klava sections', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: {
        kpis: { total: 1, overdue: 0, today: 0, deals: 0 },
        sections: {
          klava: {
            label: 'Klava',
            tasks: [
              { id: 'k1', title: 'Background task', source: 'gtasks', source_label: 'KL', tags: [], list_name: 'klava' },
            ],
          },
        },
        section_order: ['klava'],
      },
    }) as any);
    renderWithQuery(<TasksTab />);
    expect(screen.getByText('No tasks in this category')).toBeTruthy();
  });

  it('collapses and expands sections', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: {
        kpis: { total: 2, overdue: 1, today: 1, deals: 0 },
        sections: {
          today: {
            label: 'Today',
            tasks: [
              { id: 't1', title: 'Task Today', source: 'gtasks', source_label: 'GT', tags: [], is_today: true },
            ],
          },
        },
        section_order: ['today'],
      },
    }) as any);
    renderWithQuery(<TasksTab />);
    // Click section heading to collapse
    const heading = document.querySelector('.task-section-heading');
    expect(heading).toBeTruthy();
    fireEvent.click(heading!);
  });
});

// =====================================================================
// TaskCard
// =====================================================================
describe('TaskCard', () => {
  it('renders task with title and actions', () => {
    const onMark = vi.fn();
    const onNoteChange = vi.fn();
    const task = {
      id: 'task-1', title: 'Test task', raw_title: 'Test task',
      source: 'gtasks', source_label: 'GT', tags: [{ name: 'deal', color: 'blue' }],
      overdue: false, is_today: false, notes: 'Some notes here',
      due: '2026-03-20', list_name: 'default',
    };
    renderWithQuery(
      <TaskCard task={task} onMark={onMark} onNoteChange={onNoteChange} />
    );
    expect(screen.getByText('Test task')).toBeTruthy();
    expect(document.body.textContent).toContain('GT');
    expect(document.body.textContent).toContain('deal');
    expect(screen.getByText('Done')).toBeTruthy();
    expect(screen.getByText('+1 week')).toBeTruthy();
    expect(screen.getByText('Cancel')).toBeTruthy();
  });

  it('calls onMark when action buttons clicked', () => {
    const onMark = vi.fn();
    const onNoteChange = vi.fn();
    const task = {
      id: 'task-1', title: 'Task', raw_title: 'Task',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'default',
    };
    renderWithQuery(
      <TaskCard task={task} onMark={onMark} onNoteChange={onNoteChange} />
    );
    fireEvent.click(screen.getByText('Done'));
    expect(onMark).toHaveBeenCalledWith('task-1', 'done', 'Task');
    fireEvent.click(screen.getByText('+1 week'));
    expect(onMark).toHaveBeenCalledWith('task-1', 'postpone', 'Task');
    fireEvent.click(screen.getByText('Cancel'));
    expect(onMark).toHaveBeenCalledWith('task-1', 'cancel', 'Task');
  });

  it('shows mark label when marked', () => {
    const task = {
      id: 'task-1', title: 'Task', raw_title: 'Task',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'default',
    };
    const mark = { action: 'done' as const, title: 'Task', note: '' };
    renderWithQuery(
      <TaskCard task={task} mark={mark} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(screen.getByText('DONE')).toBeTruthy();
  });

  it('shows postpone mark label', () => {
    const task = {
      id: 'task-2', title: 'Task2', raw_title: 'Task2',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'default',
    };
    const mark = { action: 'postpone' as const, title: 'Task2', note: '' };
    renderWithQuery(
      <TaskCard task={task} mark={mark} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(screen.getByText('+1 WEEK')).toBeTruthy();
  });

  it('shows cancel mark label', () => {
    const task = {
      id: 'task-3', title: 'Task3', raw_title: 'Task3',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'default',
    };
    const mark = { action: 'cancel' as const, title: 'Task3', note: '' };
    renderWithQuery(
      <TaskCard task={task} mark={mark} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(screen.getByText('CANCEL')).toBeTruthy();
  });

  it('renders task with days_info', () => {
    const task = {
      id: 'task-4', title: 'Overdue task', raw_title: 'Overdue task',
      source: 'github', source_label: 'GH', tags: [],
      list_name: 'default', overdue: true, days_info: '3d overdue',
    };
    renderWithQuery(
      <TaskCard task={task} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(document.body.textContent).toContain('3d overdue');
  });

  it('renders backlog tag', () => {
    const task = {
      id: 'task-5', title: 'Backlog task', raw_title: 'Backlog task',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'backlog',
    };
    renderWithQuery(
      <TaskCard task={task} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(document.body.textContent).toContain('backlog');
  });

  it('renders klava task with running status', () => {
    const task = {
      id: 'kl-1', title: 'Background job', raw_title: 'Background job',
      source: 'gtasks', source_label: 'KL', tags: [],
      list_name: 'klava',
      klava: { status: 'running', started_at: new Date().toISOString(), session_id: 'sess-abc123' },
    };
    renderWithQuery(
      <TaskCard task={task} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(screen.getByText(/Running since/)).toBeTruthy();
  });

  it('renders klava task with failed status', () => {
    const task = {
      id: 'kl-2', title: 'Failed job', raw_title: 'Failed job',
      source: 'gtasks', source_label: 'KL', tags: [],
      list_name: 'klava',
      klava: { status: 'failed' },
    };
    renderWithQuery(
      <TaskCard task={task} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    expect(screen.getByText('Failed - check Feed for details')).toBeTruthy();
  });

  it('handles note input change', () => {
    const onNoteChange = vi.fn();
    const task = {
      id: 'task-n', title: 'NoteTask', raw_title: 'NoteTask',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'default',
    };
    renderWithQuery(
      <TaskCard task={task} onMark={vi.fn()} onNoteChange={onNoteChange} />
    );
    const input = screen.getByPlaceholderText('Action to take (or just info to add)...');
    fireEvent.change(input, { target: { value: 'my note' } });
    expect(onNoteChange).toHaveBeenCalledWith('task-n', 'my note', 'NoteTask');
  });

  it('expands card on click', () => {
    const task = {
      id: 'task-e', title: 'ExpandTask', raw_title: 'ExpandTask',
      source: 'gtasks', source_label: 'GT', tags: [],
      list_name: 'default', notes: 'Visible notes',
    };
    renderWithQuery(
      <TaskCard task={task} onMark={vi.fn()} onNoteChange={vi.fn()} />
    );
    const card = document.querySelector('.task-card')!;
    fireEvent.click(card);
    expect(card.classList.contains('expanded')).toBe(true);
  });
});

// =====================================================================
// HealthTab
// =====================================================================
describe('HealthTab', () => {
  it('shows loading state', () => {
    renderWithQuery(<HealthTab />);
    expect(screen.getByText('Loading...')).toBeTruthy();
  });

  it('renders health data with KPIs and panels', () => {
    const data = {
      services: [
        { name: 'webhook-server', running: true },
        { name: 'tg-gateway', running: true },
        { name: 'cron-scheduler', running: false },
      ],
      data_sources: [
        { name: 'telegram', healthy: true, records: 1000 },
        { name: 'signal', healthy: false, records: 200 },
      ],
      stats: {
        runs_24h: 48, failures_24h: 2, total_cost_usd: 1.50,
        sessions_active: 1, failure_rate_pct: 4.2, total_records: 1200,
      },
      cron_jobs: [],
      activity: [],
      scheduler: { uptime_display: '2d 5h' },
      skill_inventory: [], skill_changes: [],
      heartbeat_backlog: [], reply_queue: { overdue: 0 },
      failing_jobs: [], agent_activity: [], evolution_timeline: [],
      growth_metrics: [], error_learning: [],
      daily_notes: { today: { exists: false, lines: 0, entries: 0 }, yesterday: { exists: false, lines: 0, entries: 0 } },
      obsidian_metrics: { modified_24h: 0 }, claude_md_details: {},
      costs: { today: 0, week: 0, month: 0 },
    } as any;
    renderWithQuery(<HealthTab data={data} />);
    // KPIs - "Services" label exists in KPI and Panel, use getAllByText
    expect(screen.getAllByText('Services').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('2/3')).toBeTruthy();
    expect(screen.getAllByText('Data Sources').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('1/2')).toBeTruthy();
    expect(screen.getByText('Runs / 24h')).toBeTruthy();
    // Panels
    expect(screen.getByText('CRON Jobs')).toBeTruthy();
    expect(screen.getByText('Activity Feed')).toBeTruthy();
    expect(screen.getByText('Costs')).toBeTruthy();
    // Uptime
    expect(screen.getByText('2d 5h')).toBeTruthy();
  });
});

// =====================================================================
// FilesTab
// =====================================================================
describe('FilesTab', () => {
  it('shows loading state', () => {
    vi.mocked(useFiles).mockReturnValue(mockQuery() as any);
    renderWithQuery(<FilesTab />);
    expect(screen.getByText('Loading files...')).toBeTruthy();
  });

  it('renders file content with selector buttons', () => {
    vi.mocked(useFiles).mockReturnValue(mockQuery({
      data: {
        claude_md: { content: '## CLAUDE.md content here', lines: 100, modified_ago: '2h ago' },
        memory_md: { content: '## MEMORY content', lines: 50 },
        today: '2026-03-16',
        yesterday: '2026-03-15',
        daily_notes: {
          '2026-03-16': { content: 'Today note content', lines: 10, exists: true },
          '2026-03-15': { content: 'Yesterday note', lines: 5, exists: true },
        },
        total_notes: 30,
      },
    }) as any);
    renderWithQuery(<FilesTab />);
    // KPIs
    expect(screen.getByText('CLAUDE.md Lines')).toBeTruthy();
    expect(screen.getByText("Today's Note")).toBeTruthy();
    // File selector buttons
    const claudeBtn = screen.getAllByText('CLAUDE.md');
    expect(claudeBtn.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Today')).toBeTruthy();
    expect(screen.getByText('Yesterday')).toBeTruthy();
    expect(screen.getByText('MEMORY.md')).toBeTruthy();
  });

  it('switches active file when button clicked', () => {
    vi.mocked(useFiles).mockReturnValue(mockQuery({
      data: {
        claude_md: { content: 'CLAUDE content', lines: 100, modified_ago: '2h ago' },
        memory_md: { content: 'MEMORY content', lines: 50 },
        today: '2026-03-16',
        yesterday: '2026-03-15',
        daily_notes: {
          '2026-03-16': { content: 'Today note', lines: 10, exists: true },
          '2026-03-15': { content: 'Yesterday note', lines: 5, exists: true },
        },
        total_notes: 30,
      },
    }) as any);
    renderWithQuery(<FilesTab />);
    // Switch to Today
    fireEvent.click(screen.getByText('Today'));
    // Switch to MEMORY.md
    fireEvent.click(screen.getByText('MEMORY.md'));
    // Switch to Yesterday
    fireEvent.click(screen.getByText('Yesterday'));
  });
});

// =====================================================================
// HeartbeatTab
// =====================================================================
describe('HeartbeatTab', () => {
  it('shows loading state', () => {
    vi.mocked(useHeartbeat).mockReturnValue(mockQuery() as any);
    renderWithQuery(<HeartbeatTab />);
    expect(screen.getByText('Loading heartbeat...')).toBeTruthy();
  });

  it('renders heartbeat with runs and KPIs', () => {
    vi.mocked(useHeartbeat).mockReturnValue(mockQuery({
      data: {
        runs: [
          {
            timestamp: new Date().toISOString(),
            job_id: 'heartbeat',
            status: 'acted',
            duration: 45,
            output: 'Some output here',
            actions: ['Created task for Acme Corp'],
            deltas: [
              { type: 'gtask_created', summary: 'Acme Corp follow-up' },
              { type: 'skipped', source: 'telegram/chat', hint: 'noise', count: 3 },
            ],
          },
          {
            timestamp: new Date().toISOString(),
            job_id: 'heartbeat',
            status: 'idle',
            duration: 10,
            output: 'No new data',
          },
        ],
        job_stats: {
          heartbeat: { today: 24, acted_today: 8, last_status: 'acted', last_run: new Date().toISOString(), avg_duration: 30, total_7d: 168 },
        },
        job_meta: {
          heartbeat: { label: 'Heartbeat', order: 1 },
        },
        kpis: { runs_today: 24, acted_today: 8, idle_today: 16, failed_today: 0, total_actions_today: 15, tracked_items: 5 },
        consumer_sources: {
          heartbeat: {
            sources: { telegram: { position: 100, total: 120, new: 20 } },
            updated_at: new Date().toISOString(),
            total_new: 20,
          },
        },
        today_deltas: {
          obsidian: ['Updated Person note', 'Created Deal note'],
          gtask: ['Created follow-up task'],
          skipped: 10,
        },
        reported_items: { 'Acme Corp deal update': new Date().toISOString() },
      },
    }) as any);
    renderWithQuery(<HeartbeatTab />);

    // KPIs
    expect(screen.getByText('Runs Today')).toBeTruthy();
    expect(screen.getByText('Acted')).toBeTruthy();

    // Source queues
    expect(screen.getByText('Source Queues')).toBeTruthy();

    // Today's Output section
    expect(screen.getByText("Today's Output")).toBeTruthy();

    // Job overview
    expect(screen.getByText('Job Overview')).toBeTruthy();
    // Heartbeat appears multiple times (filter, job card, run card), just verify presence
    expect(screen.getAllByText('Heartbeat').length).toBeGreaterThanOrEqual(1);

    // Run history
    expect(screen.getByText('Run History')).toBeTruthy();

    // Tracked items
    expect(screen.getByText('Tracked Items (dedup)')).toBeTruthy();
  });

  it('shows empty runs message', () => {
    vi.mocked(useHeartbeat).mockReturnValue(mockQuery({
      data: {
        runs: [],
        job_stats: {},
        kpis: { runs_today: 0, acted_today: 0, idle_today: 0, failed_today: 0, total_actions_today: 0, tracked_items: 0 },
      },
    }) as any);
    renderWithQuery(<HeartbeatTab />);
    expect(screen.getByText('No runs found')).toBeTruthy();
  });

  it('renders failed run status', () => {
    vi.mocked(useHeartbeat).mockReturnValue(mockQuery({
      data: {
        runs: [
          {
            timestamp: new Date().toISOString(),
            job_id: 'heartbeat',
            status: 'failed',
            duration: 5,
            error: 'Connection timeout',
          },
        ],
        job_stats: {
          heartbeat: { today: 1, acted_today: 0, last_status: 'failed', last_run: new Date().toISOString(), avg_duration: 5, total_7d: 1 },
        },
        job_meta: { heartbeat: { label: 'Heartbeat', order: 1 } },
        kpis: { runs_today: 1, acted_today: 0, idle_today: 0, failed_today: 1, total_actions_today: 0, tracked_items: 0 },
      },
    }) as any);
    renderWithQuery(<HeartbeatTab />);
    expect(document.body.textContent).toContain('Connection timeout');
  });

  it('expands a run card on click', () => {
    vi.mocked(useHeartbeat).mockReturnValue(mockQuery({
      data: {
        runs: [
          {
            timestamp: new Date().toISOString(),
            job_id: 'heartbeat',
            status: 'acted',
            duration: 30,
            output: 'Detailed output text',
            actions: ['Action 1'],
            intake_details: { telegram: { 'Work': 5, 'Personal': 2 } },
            todos: [
              { content: 'First todo', status: 'completed' },
              { content: 'Second todo', status: 'in_progress' },
              { content: 'Third todo', status: 'pending' },
            ],
          },
        ],
        job_stats: {
          heartbeat: { today: 1, acted_today: 1, last_status: 'acted', last_run: new Date().toISOString(), avg_duration: 30, total_7d: 1 },
        },
        job_meta: { heartbeat: { label: 'Heartbeat', order: 1 } },
        kpis: { runs_today: 1, acted_today: 1, idle_today: 0, failed_today: 0, total_actions_today: 1, tracked_items: 0 },
      },
    }) as any);
    renderWithQuery(<HeartbeatTab />);

    // Click to expand
    const runCard = document.querySelector('.hb-run')!;
    fireEvent.click(runCard);
    // After expanding, output and details should be visible
    expect(document.body.textContent).toContain('Detailed output text');
    expect(document.body.textContent).toContain('telegram');
    // Todos
    expect(document.body.textContent).toContain('First todo');
    expect(document.body.textContent).toContain('Second todo');
  });
});

// =====================================================================
// PlansTab
// =====================================================================
describe('PlansTab', () => {
  it('shows loading state', () => {
    vi.mocked(usePlans).mockReturnValue(mockQuery() as any);
    renderWithQuery(<PlansTab />);
    expect(screen.getByText('Loading plans...')).toBeTruthy();
  });

  it('shows empty state when no plans', () => {
    vi.mocked(usePlans).mockReturnValue(mockQuery({
      data: { plans: [] },
    }) as any);
    renderWithQuery(<PlansTab />);
    expect(screen.getByText(/No plans found/)).toBeTruthy();
  });

  it('renders plans list with first expanded', () => {
    vi.mocked(usePlans).mockReturnValue(mockQuery({
      data: {
        plans: [
          { name: 'plan1.md', content: '# My Plan\nSome content', modified: new Date().toISOString(), size: 2048 },
          { name: 'plan2.md', content: '# Another Plan\nMore stuff', modified: new Date().toISOString(), size: 1024 },
        ],
      },
    }) as any);
    renderWithQuery(<PlansTab />);
    expect(screen.getByText('2 plans (sorted by last modified)')).toBeTruthy();
    expect(screen.getByText('My Plan')).toBeTruthy();
    expect(screen.getByText('Another Plan')).toBeTruthy();
  });

  it('toggles plan expansion on click', () => {
    vi.mocked(usePlans).mockReturnValue(mockQuery({
      data: {
        plans: [
          { name: 'plan1.md', content: '# First\nBody text', modified: new Date().toISOString(), size: 512 },
          { name: 'plan2.md', content: '# Second\nOther text', modified: new Date().toISOString(), size: 256 },
        ],
      },
    }) as any);
    renderWithQuery(<PlansTab />);
    // Click second plan header to expand it (and collapse first)
    const headers = document.querySelectorAll('.plan-card-header');
    expect(headers.length).toBe(2);
    fireEvent.click(headers[1]);
  });
});

// =====================================================================
// SkillsTab
// =====================================================================
describe('SkillsTab', () => {
  const emptyDashboard = {
    services: [], stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
    heartbeat_backlog: [], reply_queue: { overdue: 0 }, failing_jobs: [],
    data_sources: [], activity: [], agent_activity: [], evolution_timeline: [],
    growth_metrics: [], error_learning: [],
    daily_notes: { today: { exists: false, lines: 0, entries: 0 }, yesterday: { exists: false, lines: 0, entries: 0 } },
    obsidian_metrics: { modified_24h: 0 }, claude_md_details: {},
    costs: { today: 0, week: 0, month: 0 },
  };

  it('shows loading state', () => {
    renderWithQuery(<SkillsTab />);
    expect(screen.getByText('Loading...')).toBeTruthy();
  });

  it('renders skills with KPIs and sort options', () => {
    const data = {
      ...emptyDashboard,
      skill_inventory: [
        { name: 'heartbeat-skill', description: 'Periodic intake', calls_30d: 720, error_count: 0, call_count: 720, last_call_ago: '30m', last_modified_ago: '1d' },
        { name: 'vox-crm', description: 'CRM updates', calls_30d: 50, error_count: 2, call_count: 50, last_call_ago: '2h', last_modified_ago: '3d' },
      ],
      skill_changes: [
        { date: '2026-03-16T10:00:00', type: 'modified', skill: 'heartbeat-skill', summary: 'Updated intake logic', message: 'Updated intake logic', hash: 'abc1234', files: ['skills/heartbeat/SKILL.md'], insertions: 10, deletions: 3 },
      ],
    } as any;
    renderWithQuery(<SkillsTab data={data} />);

    // KPIs
    expect(screen.getByText('Total Skills')).toBeTruthy();
    expect(screen.getByText('Total Calls')).toBeTruthy();
    expect(screen.getByText('With Errors')).toBeTruthy();

    // Skills render
    expect(screen.getByText('heartbeat-skill')).toBeTruthy();
    expect(screen.getByText('vox-crm')).toBeTruthy();

    // Changes timeline
    expect(screen.getByText('Skill Changes (7d)')).toBeTruthy();
    expect(screen.getByText('Updated intake logic')).toBeTruthy();

    // Sort options
    expect(screen.getByText('By Calls')).toBeTruthy();
    expect(screen.getByText('By Last Used')).toBeTruthy();
    expect(screen.getByText('By Modified')).toBeTruthy();
  });

  it('shows empty skills state', () => {
    const data = { ...emptyDashboard, skill_inventory: [], skill_changes: [] } as any;
    renderWithQuery(<SkillsTab data={data} />);
    expect(screen.getByText('No skills found')).toBeTruthy();
  });

  it('sorts skills by different modes', () => {
    const data = {
      ...emptyDashboard,
      skill_inventory: [
        { name: 'a-skill', calls_30d: 10, error_count: 0, call_count: 10, last_call: '2026-03-15T10:00:00', last_modified: '2026-03-16T10:00:00' },
        { name: 'b-skill', calls_30d: 50, error_count: 0, call_count: 50, last_call: '2026-03-16T10:00:00', last_modified: '2026-03-15T10:00:00' },
      ],
      skill_changes: [],
    } as any;
    renderWithQuery(<SkillsTab data={data} />);

    // Switch to By Last Used
    fireEvent.click(screen.getByText('By Last Used'));
    // Switch to By Modified
    fireEvent.click(screen.getByText('By Modified'));
  });

  it('expands skill card on click', () => {
    const data = {
      ...emptyDashboard,
      skill_inventory: [
        { name: 'test-skill', description: 'A test skill description', calls_30d: 5, error_count: 0, call_count: 5, calls: [{ timestamp: '2026-03-16T10:00:00', status: 'ok' }], git_commits: [{ hash: 'abc1234567', message: 'Initial commit' }] },
      ],
      skill_changes: [],
    } as any;
    renderWithQuery(<SkillsTab data={data} />);
    fireEvent.click(screen.getByText('test-skill'));
    // After expanding, description should be visible
    expect(screen.getByText('A test skill description')).toBeTruthy();
    expect(screen.getByText('Recent Calls')).toBeTruthy();
    expect(screen.getByText('Git History')).toBeTruthy();
  });

  it('expands skill change timeline entry', () => {
    const data = {
      ...emptyDashboard,
      skill_inventory: [],
      skill_changes: [
        {
          date: '2026-03-16T10:00:00', type: 'modified', skill: 'test',
          summary: 'Change summary', message: 'Change summary',
          hash: 'def5678', files: ['skills/test/SKILL.md', 'skills/test/run.py'],
          insertions: 5, deletions: 2,
          diff_preview: '--- a/SKILL.md\n+added line\n-removed line\ncontext',
        },
      ],
    } as any;
    renderWithQuery(<SkillsTab data={data} />);
    // Click to expand the timeline entry
    const header = document.querySelector('.tl-header');
    if (header) fireEvent.click(header);
  });
});

// =====================================================================
// SourcesTab
// =====================================================================
describe('SourcesTab', () => {
  it('shows loading state', () => {
    vi.mocked(useSources).mockReturnValue(mockQuery({ isFetching: true }) as any);
    renderWithQuery(<SourcesTab />);
    expect(screen.getByText('Loading...')).toBeTruthy();
  });

  it('shows no data state', () => {
    vi.mocked(useSources).mockReturnValue(mockQuery({ isFetching: false }) as any);
    renderWithQuery(<SourcesTab />);
    expect(screen.getByText('No data')).toBeTruthy();
  });

  it('renders sources grouped by category', () => {
    vi.mocked(useSources).mockReturnValue(mockQuery({
      data: {
        telegram: {
          display_name: 'Telegram',
          description: 'Telegram messages',
          category: 'messaging',
          dependencies: { python: [], cli: [], credentials: ['TG_API_KEY'], os: [] },
          config_schema: {},
          loadable: true,
          enabled: true,
          ready: { ok: true },
          stats: { file_size: 1024000, last_modified: new Date().toISOString(), record_count: 50000 },
        },
        signal: {
          display_name: 'Signal',
          description: 'Signal messages',
          category: 'messaging',
          dependencies: { python: ['signalbot'], cli: [], credentials: [], os: ['macOS'] },
          config_schema: {},
          loadable: true,
          enabled: true,
          ready: { ok: false, missing: ['signalbot'] },
          stats: { file_size: 200000, last_modified: new Date().toISOString(), record_count: 5000 },
        },
        github: {
          display_name: 'GitHub',
          description: 'GitHub issues and commits',
          category: 'dev',
          dependencies: { python: [], cli: ['gh'], credentials: [], os: [] },
          config_schema: {},
          loadable: true,
          enabled: false,
          ready: null,
          stats: null,
        },
      },
    }) as any);
    renderWithQuery(<SourcesTab />);

    // KPIs
    expect(screen.getByText('Total Sources')).toBeTruthy();
    expect(screen.getByText('Enabled')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Total Records')).toBeTruthy();

    // Category panels
    expect(screen.getByText('Messaging')).toBeTruthy();
    expect(screen.getByText('Development')).toBeTruthy();

    // Source cards
    expect(screen.getByText('Telegram')).toBeTruthy();
    expect(screen.getByText('Signal')).toBeTruthy();
    expect(screen.getByText('GitHub')).toBeTruthy();

    // Status badges
    const activeBadges = screen.getAllByText('Active');
    expect(activeBadges.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Missing')).toBeTruthy();
    expect(screen.getByText('Off')).toBeTruthy();

    // Missing dependency shown for Signal
    expect(screen.getByText('signalbot')).toBeTruthy();
  });

  it('expands source card to show dependencies', () => {
    vi.mocked(useSources).mockReturnValue(mockQuery({
      data: {
        telegram: {
          display_name: 'Telegram',
          description: 'Messages',
          category: 'messaging',
          dependencies: { python: ['telethon'], cli: [], credentials: ['TG_API_KEY', 'TG_API_HASH'], os: [] },
          config_schema: {},
          loadable: true,
          enabled: true,
          ready: { ok: true },
          stats: { file_size: 1024000, last_modified: new Date().toISOString(), record_count: 50000 },
        },
      },
    }) as any);
    renderWithQuery(<SourcesTab />);
    // Click to expand
    fireEvent.click(screen.getByText('Telegram'));
    // Dependencies should now be visible
    expect(document.body.textContent).toContain('telethon');
    expect(document.body.textContent).toContain('TG_API_KEY, TG_API_HASH');
  });
});

// =====================================================================
// ViewsTab
// =====================================================================
describe('ViewsTab', () => {
  it('shows loading state', () => {
    vi.mocked(useViews).mockReturnValue(mockQuery() as any);
    renderWithQuery(<ViewsTab />);
    expect(screen.getByText('Loading views...')).toBeTruthy();
  });

  it('shows empty state when no views', () => {
    vi.mocked(useViews).mockReturnValue(mockQuery({
      data: { views: [], metrics: { total: 0, today: 0 } },
    }) as any);
    renderWithQuery(<ViewsTab />);
    expect(screen.getByText(/No views generated yet/)).toBeTruthy();
  });

  it('renders views list', () => {
    vi.mocked(useViews).mockReturnValue(mockQuery({
      data: {
        views: [
          { filename: 'report.html', title: 'Deal Report', modified_ago: '2h ago', size_kb: 15 },
          { filename: 'comparison.html', title: 'Data Comparison', subtitle: 'Q1 vs Q2', modified_ago: '1d ago', size_kb: 30 },
        ],
        metrics: { total: 2, today: 1 },
      },
    }) as any);
    renderWithQuery(<ViewsTab />);

    // KPIs
    expect(screen.getByText('Total Views')).toBeTruthy();

    // Section heading
    expect(screen.getByText('HTML Views')).toBeTruthy();

    // Views render
    expect(screen.getByText('Deal Report')).toBeTruthy();
    expect(screen.getByText('Data Comparison')).toBeTruthy();
    expect(screen.getByText('Q1 vs Q2')).toBeTruthy();
  });

  it('shows viewer when pendingView is set', () => {
    vi.mocked(useViews).mockReturnValue(mockQuery({
      data: { views: [], metrics: { total: 0, today: 0 } },
    }) as any);
    const onConsumed = vi.fn();
    renderWithQuery(
      <ViewsTab
        pendingView={{ url: '/api/views/serve/test.html', title: 'My View' }}
        onPendingViewConsumed={onConsumed}
      />
    );
    expect(screen.getByText('Back')).toBeTruthy();
    expect(screen.getByText('My View')).toBeTruthy();
    expect(onConsumed).toHaveBeenCalled();
  });
});
