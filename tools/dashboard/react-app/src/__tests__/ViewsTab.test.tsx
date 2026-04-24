/**
 * Tests for ViewsTab - specifically the pendingView prop that fixes
 * the race condition where SocketIO views_open fired before ViewsTab
 * had a chance to mount and register its own event listener.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import { ViewsTab } from '@/components/tabs/Views';

// Mock socket.io-client (used by App.tsx, not ViewsTab directly)
vi.mock('socket.io-client', () => import('@/__mocks__/socket.io-client'));

// Mock useViews query to avoid real HTTP calls
vi.mock('@/api/queries', () => ({
  useViews: vi.fn(() => ({
    data: {
      views: [
        { filename: 'test-view.html', title: 'Test View', modified_ago: '1m ago', size_kb: 10 },
      ],
      metrics: { total: 1, today: 1 },
    },
    refetch: vi.fn(),
    isFetching: false,
  })),
}));

beforeEach(() => {
  cleanup();
});

describe('ViewsTab - pendingView prop (race condition fix)', () => {
  it('shows list when no pendingView', () => {
    render(<ViewsTab />);
    expect(screen.getByText('HTML Views')).toBeTruthy();
    expect(screen.getByText('Test View')).toBeTruthy();
  });

  it('shows viewer immediately when pendingView is set', () => {
    const onConsumed = vi.fn();
    render(
      <ViewsTab
        pendingView={{ url: '/api/views/serve/test.html', title: 'My View' }}
        onPendingViewConsumed={onConsumed}
      />
    );

    // Should show viewer, not the list
    expect(screen.queryByText('HTML Views')).toBeNull();
    // Back button is present in ViewsViewer
    expect(screen.getByText('Back')).toBeTruthy();
    // Title visible
    expect(screen.getByText('My View')).toBeTruthy();
  });

  it('calls onPendingViewConsumed after consuming pendingView', () => {
    const onConsumed = vi.fn();
    render(
      <ViewsTab
        pendingView={{ url: '/api/views/serve/test.html', title: 'My View' }}
        onPendingViewConsumed={onConsumed}
      />
    );

    expect(onConsumed).toHaveBeenCalledTimes(1);
  });

  it('updates viewer when pendingView changes', async () => {
    const onConsumed = vi.fn();
    const { rerender } = render(
      <ViewsTab
        pendingView={{ url: '/api/views/serve/first.html', title: 'First View' }}
        onPendingViewConsumed={onConsumed}
      />
    );

    expect(screen.getByText('First View')).toBeTruthy();

    await act(async () => {
      rerender(
        <ViewsTab
          pendingView={{ url: '/api/views/serve/second.html', title: 'Second View' }}
          onPendingViewConsumed={onConsumed}
        />
      );
    });

    expect(screen.getByText('Second View')).toBeTruthy();
    expect(onConsumed).toHaveBeenCalledTimes(2);
  });

  it('shows list when pendingView is null', () => {
    render(<ViewsTab pendingView={null} onPendingViewConsumed={vi.fn()} />);
    expect(screen.getByText('HTML Views')).toBeTruthy();
  });
});
