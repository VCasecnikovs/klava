/**
 * Tests for SelfEvolveTab, PipelinesTab, and KlavaTab.
 * These three tab components previously had 0% coverage.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ---- Module mocks (must be before component imports) ----

vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

vi.mock('@/api/queries', () => ({
  useSelfEvolve: vi.fn(),
  usePipelines: vi.fn(),
  useTasks: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  api: {
    selfEvolveRun: vi.fn(),
    selfEvolveUpdate: vi.fn(),
    selfEvolveDelete: vi.fn(),
  },
}));

// ---- Imports (after mocks) ----

import { useSelfEvolve, usePipelines, useTasks } from '@/api/queries';
import { api } from '@/api/client';
import { SelfEvolveTab } from '@/components/tabs/SelfEvolve/index';
import { PipelinesTab } from '@/components/tabs/Pipelines/index';
import { KlavaTab } from '@/components/tabs/Klava/index';

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

// ---- Test data factories ----

function makeBacklogItem(overrides: Record<string, unknown> = {}) {
  return {
    date: '2026-03-15',
    title: 'Fix heartbeat timing',
    source: 'reflection',
    priority: 'high',
    status: 'open',
    seen: 1,
    description: 'Heartbeat sometimes runs too slow',
    fix_hint: 'Check cron interval',
    resolved: '',
    session_id: undefined,
    ...overrides,
  };
}

function makeSelfEvolveData(overrides: Record<string, unknown> = {}) {
  return {
    metrics: { added: 10, fixed: 5, avg_days: '3.2', last_run: '2026-03-15 10:00' },
    items: [
      makeBacklogItem(),
      makeBacklogItem({ title: 'Improve memory writes', priority: 'medium', status: 'done', source: 'session' }),
      makeBacklogItem({ title: 'In progress task', priority: 'low', status: 'in-progress', source: 'heartbeat' }),
    ],
    ...overrides,
  };
}

function makePipelineDefinition(overrides: Record<string, unknown> = {}) {
  return {
    name: 'complex-task',
    states: ['PLAN', 'EXECUTE', 'RESULT', 'EVALUATE', 'done', 'failed'],
    terminal_states: ['done', 'failed'],
    description: 'Complex task pipeline',
    transition_count: 5,
    max_retries: 3,
    ...overrides,
  };
}

function makePipelineSession(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'sess-abc-123',
    pipeline: 'complex-task',
    current_state: 'EXECUTE',
    started: '2026-03-15T10:00:00Z',
    last_transition: '2026-03-15T10:05:00Z',
    retries: 1,
    retry_count: 1,
    total_duration_display: '5m 30s',
    context: { task: 'Write tests' },
    history: [
      { from: undefined, to: 'PLAN', at: '2026-03-15T10:00:00Z', label: 'start' },
      { from: 'PLAN', to: 'EXECUTE', at: '2026-03-15T10:05:00Z' },
    ],
    ...overrides,
  };
}

function makePipelinesData(overrides: Record<string, unknown> = {}) {
  return {
    definitions: [makePipelineDefinition()],
    sessions: [],
    active: [makePipelineSession()],
    completed_today: [],
    stats: {
      active_count: 1,
      completed_today_count: 0,
      definition_count: 1,
    },
    ...overrides,
  };
}

function makeKlavaTask(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    title: 'Analyze deal pipeline',
    raw_title: 'Analyze deal pipeline',
    notes: 'Review Acme Corp and Globex Inc deals',
    klava: {
      status: 'pending',
      priority: 'high',
      source: 'heartbeat',
    },
    ...overrides,
  };
}

function makeTasksData(sections: Record<string, unknown> = {}) {
  return {
    sections: {
      klava: {
        name: 'klava',
        tasks: [],
      },
      ...sections,
    },
    total: 0,
    overdue: 0,
    today: 0,
    completed_today: 0,
  };
}

beforeEach(() => {
  vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('{}');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
  // Reset module-level mock call counts (vi.restoreAllMocks only restores spies)
  vi.mocked(api.selfEvolveRun).mockReset();
  vi.mocked(api.selfEvolveUpdate).mockReset();
  vi.mocked(api.selfEvolveDelete).mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// =====================================================================
// SelfEvolveTab
// =====================================================================
describe('SelfEvolveTab', () => {
  it('shows loading state', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ isLoading: true }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.getByText('Loading...')).toBeTruthy();
  });

  it('shows no data state', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: undefined }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.getByText('No data')).toBeTruthy();
  });

  it('renders KPI row with metrics', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // KPI labels exist (Open appears in both KPI and filter, so use getAllByText)
    const kpiRow = document.querySelector('.kpi-row')!;
    expect(kpiRow).toBeTruthy();
    expect(kpiRow.textContent).toContain('Open');
    expect(kpiRow.textContent).toContain('2');

    // Fixed (30d)
    expect(screen.getByText('Fixed (30d)')).toBeTruthy();
    expect(screen.getByText('5')).toBeTruthy();

    // Fix rate = 5/10 * 100 = 50%
    expect(screen.getByText('Fix Rate')).toBeTruthy();
    expect(screen.getByText('50%')).toBeTruthy();

    // Avg Days
    expect(screen.getByText('Avg Days')).toBeTruthy();
    expect(screen.getByText('3.2')).toBeTruthy();
  });

  it('renders backlog section heading with last run', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.getByText('Backlog')).toBeTruthy();
    expect(screen.getByText(/Last run:.*2026-03-15 10:00/)).toBeTruthy();
  });

  it('renders Run Now button', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    renderWithQuery(<SelfEvolveTab />);
    const btn = screen.getByText('Run Now');
    expect(btn).toBeTruthy();
    expect(btn.tagName).toBe('BUTTON');
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it('filters open items by default', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // open items: "Fix heartbeat timing" (open) and "In progress task" (in-progress)
    expect(screen.getByText('Fix heartbeat timing')).toBeTruthy();
    expect(screen.getByText('In progress task')).toBeTruthy();
    // done item should NOT be visible
    expect(screen.queryByText('Improve memory writes')).toBeNull();
  });

  it('shows all items when "All" filter is selected', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Click the "All" filter button
    const allBtn = screen.getByText('All');
    fireEvent.click(allBtn);

    // Now all 3 items should be visible
    expect(screen.getByText('Fix heartbeat timing')).toBeTruthy();
    expect(screen.getByText('Improve memory writes')).toBeTruthy();
    expect(screen.getByText('In progress task')).toBeTruthy();
  });

  it('shows done/wontfix items when "Done" filter is selected', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [
          makeBacklogItem({ title: 'Open item', status: 'open' }),
          makeBacklogItem({ title: 'Done item', status: 'done' }),
          makeBacklogItem({ title: 'Wontfix item', status: 'wontfix' }),
        ],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByText('Done'));

    expect(screen.queryByText('Open item')).toBeNull();
    expect(screen.getByText('Done item')).toBeTruthy();
    expect(screen.getByText('Wontfix item')).toBeTruthy();
  });

  it('shows empty state when no items match filter', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ status: 'done' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Default filter is 'open', but only done items exist
    expect(screen.getByText('All clear - nothing to fix')).toBeTruthy();
  });

  it('shows "No items" when done filter is empty', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ status: 'open' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByText('Done'));
    expect(screen.getByText('No items')).toBeTruthy();
  });

  it('expands card on click to show description', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({
          description: 'Detailed description here',
          fix_hint: 'Try adjusting interval',
        })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Description not visible initially
    expect(screen.queryByText('Detailed description here')).toBeNull();

    // Click card to expand
    fireEvent.click(screen.getByText('Fix heartbeat timing'));
    expect(screen.getByText('Detailed description here')).toBeTruthy();
    expect(screen.getByText(/Hint:.*Try adjusting interval/)).toBeTruthy();
  });

  it('shows session link when session_id is present', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ session_id: 'session-xyz-123' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    const sessionLink = screen.getByText('session');
    expect(sessionLink.tagName).toBe('A');
    expect(sessionLink.getAttribute('href')).toContain('session=session-xyz-123');
  });

  it('shows expanded session details when expanded and session_id exists', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ session_id: 'session-xyz-123' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Expand card
    fireEvent.click(screen.getByText('Fix heartbeat timing'));
    // Should show session ID in expanded view
    const sessionLinks = screen.getAllByText(/session-xyz-123/);
    expect(sessionLinks.length).toBeGreaterThan(0);
  });

  it('shows resolved text when item is resolved', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ resolved: 'Fixed by commit abc123', status: 'open' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByText('Fix heartbeat timing'));
    expect(screen.getByText(/Resolved:.*Fixed by commit abc123/)).toBeTruthy();
  });

  it('shows seen count when > 1', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ seen: 3 })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.getByText('x3')).toBeTruthy();
  });

  it('does not show seen count when == 1', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ seen: 1 })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.queryByText('x1')).toBeNull();
  });

  it('renders source badges with correct text', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ source: 'dislike' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    // Source badge renders uppercase
    expect(screen.getByText('dislike')).toBeTruthy();
  });

  it('renders status badges', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ status: 'open' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.getByText('open')).toBeTruthy();
  });

  it('handles Run Now click - success', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    vi.mocked(api.selfEvolveRun).mockResolvedValue({ status: 'ok' });
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByText('Run Now'));
    // Button should show "Running..."
    expect(screen.getByText('Running...')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Completed')).toBeTruthy();
    });
  });

  it('handles Run Now click - error response', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    vi.mocked(api.selfEvolveRun).mockResolvedValue({ status: 'error', error: 'Script failed' });
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByText('Run Now'));

    await waitFor(() => {
      expect(screen.getByText('Error: Script failed')).toBeTruthy();
    });
  });

  it('handles Run Now click - fetch failure', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({ data: makeSelfEvolveData() }) as any);
    vi.mocked(api.selfEvolveRun).mockRejectedValue(new Error('Network error'));
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByText('Run Now'));

    await waitFor(() => {
      expect(screen.getByText(/Failed:/)).toBeTruthy();
    });
  });

  it('opens edit form on edit button click', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Click edit button (pencil icon ✎ = &#9998;)
    const editBtn = screen.getByTitle('Edit');
    fireEvent.click(editBtn);

    // Should show edit form fields
    expect(screen.getByText('Title')).toBeTruthy();
    expect(screen.getByText('Priority')).toBeTruthy();
    expect(screen.getByText('Status')).toBeTruthy();
    expect(screen.getByText('Desc')).toBeTruthy();
    expect(screen.getByText('Hint')).toBeTruthy();
    expect(screen.getByText('Save')).toBeTruthy();
    expect(screen.getByText('Cancel')).toBeTruthy();
  });

  it('cancels editing when Cancel is clicked', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByTitle('Edit'));
    expect(screen.getByText('Cancel')).toBeTruthy();

    fireEvent.click(screen.getByText('Cancel'));
    // Edit form should be gone
    expect(screen.queryByText('Cancel')).toBeNull();
  });

  it('saves edit and calls API', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    vi.mocked(api.selfEvolveUpdate).mockResolvedValue({ ok: true });
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(api.selfEvolveUpdate).toHaveBeenCalledWith('Fix heartbeat timing', {
        title: 'Fix heartbeat timing',
        priority: 'high',
        status: 'open',
        description: 'Heartbeat sometimes runs too slow',
        fix_hint: 'Check cron interval',
      });
    });
  });

  it('handles save failure with alert', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    vi.mocked(api.selfEvolveUpdate).mockRejectedValue(new Error('Save error'));
    // happy-dom may not have window.alert - define it if missing
    window.alert = window.alert || (() => {});
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining('Save failed'));
    });
  });

  it('handles delete button with confirm', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    vi.mocked(api.selfEvolveDelete).mockResolvedValue({ ok: true });
    window.confirm = window.confirm || (() => true);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderWithQuery(<SelfEvolveTab />);

    const deleteBtn = screen.getByTitle('Delete');
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(api.selfEvolveDelete).toHaveBeenCalledWith('Fix heartbeat timing');
    });
  });

  it('cancels delete when confirm is declined', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    vi.mocked(api.selfEvolveDelete).mockClear();
    // Override both window.confirm and globalThis.confirm
    const confirmMock = vi.fn().mockReturnValue(false);
    window.confirm = confirmMock;
    globalThis.confirm = confirmMock;
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByTitle('Delete'));
    expect(confirmMock).toHaveBeenCalled();
    expect(api.selfEvolveDelete).not.toHaveBeenCalled();
  });

  it('handles delete failure with alert', async () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    vi.mocked(api.selfEvolveDelete).mockRejectedValue(new Error('Delete error'));
    window.confirm = window.confirm || (() => true);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    window.alert = window.alert || (() => {});
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    renderWithQuery(<SelfEvolveTab />);

    fireEvent.click(screen.getByTitle('Delete'));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(expect.stringContaining('Delete failed'));
    });
  });

  it('handles unknown source color deterministically', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ source: 'custom-source-xyz' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    // Should render without crashing - source badge uses hsl fallback
    expect(screen.getByText('custom-source-xyz')).toBeTruthy();
  });

  it('renders 0% fix rate with 0 added items', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        metrics: { added: 0, fixed: 0, avg_days: '-', last_run: 'never' },
        items: [],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    expect(screen.getByText('0%')).toBeTruthy();
    expect(screen.getByText(/Last run:.*never/)).toBeTruthy();
  });

  it('renders avg_days as dash when not available', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        metrics: { added: 5, fixed: 2, avg_days: '', last_run: '2026-03-15' },
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);
    // When avg_days is falsy, it should show '-'
    expect(screen.getByText('-')).toBeTruthy();
  });

  it('collapses card on second click', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem({ description: 'Expand me' })],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Click to expand
    fireEvent.click(screen.getByText('Fix heartbeat timing'));
    expect(screen.getByText('Expand me')).toBeTruthy();

    // Click again to collapse
    fireEvent.click(screen.getByText('Fix heartbeat timing'));
    expect(screen.queryByText('Expand me')).toBeNull();
  });

  it('allows editing form fields via onChange handlers', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Enter edit mode
    fireEvent.click(screen.getByTitle('Edit'));

    // Change title input
    const titleInput = screen.getByDisplayValue('Fix heartbeat timing');
    fireEvent.change(titleInput, { target: { value: 'New title' } });
    expect((titleInput as HTMLInputElement).value).toBe('New title');

    // Change priority select
    const selects = document.querySelectorAll('select');
    const prioritySelect = selects[0];
    fireEvent.change(prioritySelect, { target: { value: 'low' } });
    expect((prioritySelect as HTMLSelectElement).value).toBe('low');

    // Change status select
    const statusSelect = selects[1];
    fireEvent.change(statusSelect, { target: { value: 'done' } });
    expect((statusSelect as HTMLSelectElement).value).toBe('done');

    // Change description textarea
    const textarea = document.querySelector('textarea')!;
    fireEvent.change(textarea, { target: { value: 'New description' } });
    expect(textarea.value).toBe('New description');

    // Change hint input
    const hintInput = screen.getByDisplayValue('Check cron interval');
    fireEvent.change(hintInput, { target: { value: 'New hint' } });
    expect((hintInput as HTMLInputElement).value).toBe('New hint');
  });

  it('does not toggle expand when clicking inside edit form', () => {
    vi.mocked(useSelfEvolve).mockReturnValue(mockQuery({
      data: makeSelfEvolveData({
        items: [makeBacklogItem()],
      }),
    }) as any);
    renderWithQuery(<SelfEvolveTab />);

    // Enter edit mode
    fireEvent.click(screen.getByTitle('Edit'));
    expect(screen.getByText('Save')).toBeTruthy();

    // Click inside the edit form area (stopPropagation should prevent toggle)
    const editForm = document.querySelector('[style*="flex-direction: column"]');
    if (editForm) {
      fireEvent.click(editForm);
      // Edit form should still be visible
      expect(screen.getByText('Save')).toBeTruthy();
    }
  });
});

// =====================================================================
// PipelinesTab
// =====================================================================
describe('PipelinesTab', () => {
  it('shows loading state', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: undefined }) as any);
    renderWithQuery(<PipelinesTab />);
    expect(screen.getByText('Loading pipelines...')).toBeTruthy();
  });

  it('renders KPI row with stats', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: makePipelinesData() }) as any);
    renderWithQuery(<PipelinesTab />);

    expect(screen.getByText('Active')).toBeTruthy();
    expect(screen.getByText('Completed Today')).toBeTruthy();
    expect(screen.getByText('Definitions')).toBeTruthy();
  });

  it('renders active sessions section', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: makePipelinesData() }) as any);
    renderWithQuery(<PipelinesTab />);

    expect(screen.getByText('Active Sessions')).toBeTruthy();
    // complex-task appears in both active sessions and definitions sections
    expect(screen.getAllByText('complex-task').length).toBeGreaterThan(0);
  });

  it('shows "No active pipelines" when no active sessions', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({ active: [] }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    expect(screen.getByText('No active pipelines')).toBeTruthy();
  });

  it('renders pipeline definitions section', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: makePipelinesData() }) as any);
    renderWithQuery(<PipelinesTab />);

    expect(screen.getByText('Pipeline Definitions')).toBeTruthy();
    // Description may appear alongside other 'complex-task' text
    const container = document.body;
    expect(container.textContent).toContain('Complex task pipeline');
    expect(container.textContent).toContain('6 states');
  });

  it('renders flow visualization with non-terminal states', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: makePipelinesData() }) as any);
    renderWithQuery(<PipelinesTab />);

    // Non-terminal states: PLAN, EXECUTE, RESULT, EVALUATE (done and failed are terminal)
    expect(screen.getAllByText('PLAN').length).toBeGreaterThan(0);
    expect(screen.getAllByText('EXECUTE').length).toBeGreaterThan(0);
    expect(screen.getAllByText('RESULT').length).toBeGreaterThan(0);
    expect(screen.getAllByText('EVALUATE').length).toBeGreaterThan(0);
  });

  it('renders active session details', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: makePipelinesData() }) as any);
    renderWithQuery(<PipelinesTab />);

    // State badge (EXECUTE appears in flow vis AND session details)
    expect(screen.getAllByText('EXECUTE').length).toBeGreaterThan(0);
    // Session id
    const body = document.body.textContent || '';
    expect(body).toContain('sess-abc-123');
    // Duration and retries
    expect(body).toContain('5m 30s');
    // Task
    expect(body).toContain('Write tests');
  });

  it('renders session history', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({ data: makePipelinesData() }) as any);
    renderWithQuery(<PipelinesTab />);

    // History transitions
    expect(screen.getByText(/\(start\)/)).toBeTruthy();
    expect(screen.getByText('[start]')).toBeTruthy();
  });

  it('renders failed session with failed badge', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        active: [makePipelineSession({ current_state: 'failed' })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    const badge = screen.getByText('failed');
    expect(badge.className).toContain('failed');
  });

  it('renders completed today section', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        completed_today: [
          {
            session_id: 'completed-1',
            pipeline: 'intake',
            current_state: 'done',
            final_state: 'done',
            started: '2026-03-15T08:00:00Z',
            last_transition: '2026-03-15T08:05:00Z',
            retries: 0,
            retry_count: 0,
            history_length: 3,
            context: { task: 'Morning intake' },
          },
        ],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    // "Completed Today" appears both in KPI and section heading
    expect(screen.getAllByText('Completed Today').length).toBeGreaterThan(0);
    const body = document.body.textContent || '';
    expect(body).toContain('intake');
    expect(body).toContain('done');
    expect(body).toContain('Morning intake');
  });

  it('renders completed today with failed state', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        completed_today: [
          {
            session_id: 'completed-2',
            pipeline: 'test-pipeline',
            current_state: 'failed',
            final_state: 'failed',
            started: '2026-03-15T08:00:00Z',
            last_transition: '2026-03-15T08:05:00Z',
            retries: 2,
            history: [{ to: 'PLAN', at: '2026-03-15T08:00:00Z' }],
          },
        ],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    const failedBadge = screen.getByText('failed');
    expect(failedBadge.className).toContain('failed');
  });

  it('renders with empty stats object', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: {
        definitions: [makePipelineDefinition()],
        sessions: [],
        active: [],
        completed_today: [],
        stats: {},
      },
    }) as any);
    renderWithQuery(<PipelinesTab />);

    // Should use defaults (0 for active_count, etc.)
    expect(screen.getByText('No active pipelines')).toBeTruthy();
  });

  it('falls back to definitions.length when definition_count not in stats', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: {
        definitions: [makePipelineDefinition(), makePipelineDefinition({ name: 'intake' })],
        sessions: [],
        active: [],
        completed_today: [],
        stats: { active_count: 0, completed_today_count: 0 },
      },
    }) as any);
    renderWithQuery(<PipelinesTab />);

    // Should show 2 from definitions.length
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('renders pipeline definition without description', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        definitions: [makePipelineDefinition({ description: undefined })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    // Should render without description div
    expect(screen.queryByText('Complex task pipeline')).toBeNull();
    expect(screen.getByText('Pipeline Definitions')).toBeTruthy();
  });

  it('renders session without context task', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        active: [makePipelineSession({ context: {} })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    expect(screen.queryByText(/Task:/)).toBeNull();
  });

  it('renders session without history', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        active: [makePipelineSession({ history: [] })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    // Should render without history section but not crash
    expect(screen.getByText(/sess-abc-123/)).toBeTruthy();
  });

  it('renders history entry with broken at timestamp gracefully', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        active: [makePipelineSession({
          history: [{ from: 'A', to: 'B', at: '' }],
        })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);
    // Should not crash
    expect(screen.getByText(/sess-abc-123/)).toBeTruthy();
  });

  it('renders flow visualization with visited states', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        active: [makePipelineSession({
          current_state: 'RESULT',
          history: [
            { to: 'PLAN', at: '2026-03-15T10:00:00Z' },
            { to: 'EXECUTE', at: '2026-03-15T10:01:00Z' },
            { to: 'RESULT', at: '2026-03-15T10:02:00Z' },
          ],
        })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);

    // Check that flow nodes are rendered with correct classes
    const flowNodes = document.querySelectorAll('.pipeline-flow-node');
    expect(flowNodes.length).toBeGreaterThan(0);
  });

  it('uses retries fallback when retry_count is undefined', () => {
    vi.mocked(usePipelines).mockReturnValue(mockQuery({
      data: makePipelinesData({
        active: [makePipelineSession({ retry_count: undefined, retries: 7 })],
      }),
    }) as any);
    renderWithQuery(<PipelinesTab />);
    expect(screen.getByText(/retries: 7/)).toBeTruthy();
  });
});

// =====================================================================
// KlavaTab
// =====================================================================
describe('KlavaTab', () => {
  it('shows loading state', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({ data: undefined }) as any);
    renderWithQuery(<KlavaTab />);
    expect(screen.getByText('Loading...')).toBeTruthy();
  });

  it('shows empty queue state when no tasks', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({ data: makeTasksData() }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('Queue empty')).toBeTruthy();
    expect(screen.getByText(/Tasks appear here/)).toBeTruthy();
  });

  it('renders KPI row with task counts', () => {
    const tasks = [
      makeKlavaTask({ id: '1', klava: { status: 'pending', priority: 'high', source: 'heartbeat' } }),
      makeKlavaTask({ id: '2', klava: { status: 'running', priority: 'medium', source: 'chat' } }),
      makeKlavaTask({ id: '3', klava: { status: 'failed', priority: 'low', source: 'manual' } }),
      makeKlavaTask({ id: '4', klava: { status: 'done', priority: 'medium', source: 'self' } }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    // Total: 4
    expect(screen.getByText('Total')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy();
    // Pending: 1
    expect(screen.getByText('Pending')).toBeTruthy();
    // Running: 1
    expect(screen.getByText('Running')).toBeTruthy();
    // Failed: 1
    expect(screen.getByText('Failed')).toBeTruthy();
  });

  it('renders task cards with title and priority badge', () => {
    const tasks = [
      makeKlavaTask({ id: '1', title: 'Analyze deal pipeline', raw_title: 'Analyze deal pipeline' }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('Analyze deal pipeline')).toBeTruthy();
    expect(screen.getByText('HIGH')).toBeTruthy();
  });

  it('renders task notes when present', () => {
    const tasks = [
      makeKlavaTask({ id: '1', notes: 'Check Acme Corp deal status' }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('Check Acme Corp deal status')).toBeTruthy();
  });

  it('does not render notes when absent', () => {
    const tasks = [
      makeKlavaTask({ id: '1', notes: undefined }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.queryByText('Check Acme Corp deal status')).toBeNull();
  });

  it('shows running task info with session_id', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: {
          status: 'running',
          priority: 'medium',
          source: 'heartbeat',
          started_at: new Date(Date.now() - 5 * 60000).toISOString(),
          session_id: 'abcdef0123456789',
        },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    // "Running" appears in KPI and card - use getAllByText
    expect(screen.getAllByText(/Running/).length).toBeGreaterThan(0);
    const body = document.body.textContent || '';
    expect(body).toContain('abcdef01');
  });

  it('shows pending task waiting message', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: { status: 'pending', priority: 'medium', source: 'manual' },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('Waiting in queue')).toBeTruthy();
  });

  it('shows failed task message', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: { status: 'failed', priority: 'high', source: 'chat' },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText(/Failed - check consumer log/)).toBeTruthy();
  });

  it('shows source badge for non-manual sources', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: { status: 'pending', priority: 'medium', source: 'heartbeat' },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('heartbeat')).toBeTruthy();
  });

  it('hides source badge for manual source', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: { status: 'pending', priority: 'medium', source: 'manual' },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.queryByText('manual')).toBeNull();
  });

  it('renders Refresh button and calls refetch', () => {
    const refetchFn = vi.fn();
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData(),
      refetch: refetchFn,
    }) as any);
    renderWithQuery(<KlavaTab />);

    const refreshBtn = screen.getByText('Refresh');
    expect(refreshBtn).toBeTruthy();
    fireEvent.click(refreshBtn);
    expect(refetchFn).toHaveBeenCalled();
  });

  it('renders subtitle text', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({ data: makeTasksData() }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('Async task queue - background Claude sessions')).toBeTruthy();
  });

  it('renders card with correct status class', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: { status: 'running', priority: 'medium', source: 'manual' },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    const card = document.querySelector('.klava-card-running');
    expect(card).toBeTruthy();
  });

  it('handles data without klava section gracefully', () => {
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: { sections: {}, total: 0, overdue: 0, today: 0, completed_today: 0 },
    }) as any);
    renderWithQuery(<KlavaTab />);

    // Should show empty state
    expect(screen.getByText('Queue empty')).toBeTruthy();
  });

  it('handles task without klava metadata gracefully', () => {
    const tasks = [
      { id: '1', title: 'No metadata task', raw_title: 'No metadata task' },
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    // Should render with default status "pending" and default priority "medium"
    expect(screen.getByText('No metadata task')).toBeTruthy();
    expect(screen.getByText('MEDIUM')).toBeTruthy();
    expect(screen.getByText('Waiting in queue')).toBeTruthy();
  });

  it('renders default priority MEDIUM when priority is undefined', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: { status: 'pending', source: 'chat' },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('MEDIUM')).toBeTruthy();
  });

  it('renders multiple tasks in queue', () => {
    const tasks = [
      makeKlavaTask({ id: '1', title: 'Task A', raw_title: 'Task A' }),
      makeKlavaTask({ id: '2', title: 'Task B', raw_title: 'Task B' }),
      makeKlavaTask({ id: '3', title: 'Task C', raw_title: 'Task C' }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText('Task A')).toBeTruthy();
    expect(screen.getByText('Task B')).toBeTruthy();
    expect(screen.getByText('Task C')).toBeTruthy();
    // Total KPI shows 3 (may also appear in Pending count)
    expect(screen.getAllByText('3').length).toBeGreaterThan(0);
  });

  it('renders running task time ago', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: {
          status: 'running',
          priority: 'high',
          source: 'self',
          started_at: new Date(Date.now() - 30 * 60000).toISOString(),
        },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText(/Running 30m ago/)).toBeTruthy();
  });

  it('renders "just now" for very recent running task', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: {
          status: 'running',
          priority: 'high',
          source: 'self',
          started_at: new Date().toISOString(),
        },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText(/Running just now/)).toBeTruthy();
  });

  it('renders hours ago for older running tasks', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: {
          status: 'running',
          priority: 'high',
          source: 'self',
          started_at: new Date(Date.now() - 3 * 3600000).toISOString(),
        },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText(/Running 3h ago/)).toBeTruthy();
  });

  it('renders days ago for very old running tasks', () => {
    const tasks = [
      makeKlavaTask({
        id: '1',
        klava: {
          status: 'running',
          priority: 'high',
          source: 'self',
          started_at: new Date(Date.now() - 2 * 86400000).toISOString(),
        },
      }),
    ];
    vi.mocked(useTasks).mockReturnValue(mockQuery({
      data: makeTasksData({ klava: { name: 'klava', tasks } }),
    }) as any);
    renderWithQuery(<KlavaTab />);

    expect(screen.getByText(/Running 2d ago/)).toBeTruthy();
  });
});
