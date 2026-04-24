/**
 * Tests for the redesigned Lifeline tab.
 * Lifeline is now a pure log of system-made changes, grouped into
 * CLAUDE.md / Daily / Skills / Obsidian. Data comes from data.lifeline.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { DashboardData, LifelineEvent } from '@/api/types';
import { LifelineTab } from '@/components/tabs/Lifeline/index';

vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

function makeData(events: LifelineEvent[] = []): DashboardData {
  return {
    services: [],
    stats: { runs_24h: 0, failures_24h: 0, total_cost_usd: 0, sessions_active: 0 },
    heartbeat_backlog: [],
    reply_queue: { overdue: 0 },
    failing_jobs: [],
    data_sources: [],
    activity: [],
    agent_activity: [],
    evolution_timeline: [],
    skill_inventory: [],
    skill_changes: [],
    growth_metrics: [],
    error_learning: [],
    daily_notes: {
      today: { exists: false, lines: 0, entries: 0 },
      yesterday: { exists: false, lines: 0, entries: 0 },
    },
    obsidian_metrics: { modified_24h: 0 },
    claude_md_details: {},
    costs: { today: 0, week: 0, month: 0 },
    lifeline: events,
  };
}

function ev(overrides: Partial<LifelineEvent> = {}): LifelineEvent {
  return {
    ts: '2026-04-18T10:00:00',
    date: '2026-04-18',
    time: '10:00',
    group: 'obsidian',
    summary: 'heartbeat: some change',
    author: 'Клавдия',
    commit: 'abc12345',
    files: ['Inbox/note.md'],
    repo: 'mybrain',
    ...overrides,
  };
}

describe('LifelineTab', () => {
  it('renders loading state when data is undefined', () => {
    render(<LifelineTab data={undefined} />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders empty state when lifeline is empty', () => {
    render(<LifelineTab data={makeData([])} />);
    expect(screen.getByText(/No system-made changes yet/)).toBeInTheDocument();
  });

  it('renders all four filter options with counts', () => {
    const data = makeData([
      ev({ group: 'claude_md' }),
      ev({ group: 'daily' }),
      ev({ group: 'skills' }),
      ev({ group: 'obsidian' }),
      ev({ group: 'obsidian' }),
    ]);
    render(<LifelineTab data={data} />);
    expect(screen.getByText(/All \(5\)/)).toBeInTheDocument();
    expect(screen.getByText(/CLAUDE\.md \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Daily \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Skills \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Obsidian \(2\)/)).toBeInTheDocument();
  });

  it('renders events from all four groups with the right chips', () => {
    const data = makeData([
      ev({ group: 'claude_md', summary: 'reflection: claude.md edit', commit: 'c1' }),
      ev({ group: 'daily',     summary: 'heartbeat: daily note',      commit: 'c2' }),
      ev({ group: 'skills',    summary: 'self-evolve: new skill',     commit: 'c3' }),
      ev({ group: 'obsidian',  summary: 'heartbeat: vault edit',      commit: 'c4' }),
    ]);
    render(<LifelineTab data={data} />);
    expect(screen.getByText('CLAUDE')).toBeInTheDocument();
    expect(screen.getByText('DAILY')).toBeInTheDocument();
    expect(screen.getByText('SKILL')).toBeInTheDocument();
    expect(screen.getByText('VAULT')).toBeInTheDocument();
  });

  it('filters events by group', () => {
    const data = makeData([
      ev({ group: 'claude_md', summary: 'claude-md change', commit: 'c1' }),
      ev({ group: 'obsidian',  summary: 'obsidian change',  commit: 'c2' }),
    ]);
    render(<LifelineTab data={data} />);
    expect(screen.getByText('claude-md change')).toBeInTheDocument();
    expect(screen.getByText('obsidian change')).toBeInTheDocument();

    fireEvent.click(screen.getByText(/CLAUDE\.md \(1\)/));
    expect(screen.getByText('claude-md change')).toBeInTheDocument();
    expect(screen.queryByText('obsidian change')).not.toBeInTheDocument();
  });

  it('groups events by day with day labels', () => {
    const data = makeData([
      ev({ date: '2026-04-18', ts: '2026-04-18T10:00', summary: 'today event', commit: 'a' }),
      ev({ date: '2026-04-17', ts: '2026-04-17T10:00', summary: 'yesterday event', commit: 'b' }),
    ]);
    const { container } = render(<LifelineTab data={data} />);
    const labels = container.querySelectorAll('.tl-day-label');
    expect(labels.length).toBe(2);
  });

  it('expands to show files on click', () => {
    const data = makeData([
      ev({ files: ['Inbox/a.md', 'People/b.md', 'Deals/c.md'] }),
    ]);
    const { container } = render(<LifelineTab data={data} />);
    const header = container.querySelector('.tl-header');
    expect(header).toBeTruthy();

    fireEvent.click(header!);
    expect(screen.getByText('Inbox/a.md')).toBeInTheDocument();
    expect(screen.getByText('People/b.md')).toBeInTheDocument();
    expect(screen.getByText('Deals/c.md')).toBeInTheDocument();
  });

  it('shows "+N more" when files exceed visible limit', () => {
    const files = Array.from({ length: 20 }, (_, i) => `file-${i}.md`);
    const data = makeData([ev({ files, files_total: 20 })]);
    const { container } = render(<LifelineTab data={data} />);
    fireEvent.click(container.querySelector('.tl-header')!);
    expect(screen.getByText(/\+8 more/)).toBeInTheDocument();
  });

  it('renders file count chip on the header', () => {
    const data = makeData([
      ev({ files: ['a.md', 'b.md'], files_total: 2 }),
      ev({ files: ['x.md'], commit: 'other' }),
    ]);
    render(<LifelineTab data={data} />);
    expect(screen.getByText('2 files')).toBeInTheDocument();
    expect(screen.getByText('1 file')).toBeInTheDocument();
  });

  it('shows commit hash on every row', () => {
    const data = makeData([ev({ commit: 'deadbeef' })]);
    render(<LifelineTab data={data} />);
    expect(screen.getByText('deadbeef')).toBeInTheDocument();
  });
});
