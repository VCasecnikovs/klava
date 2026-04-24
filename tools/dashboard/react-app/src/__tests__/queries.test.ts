import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import {
  useDashboard, useFiles, usePipelines, useTasks, useDeals,
  usePeople, useHeartbeat, useFeed, useViews, useSessions,
  useSelfEvolve, usePlans, useAgents, useSources,
} from '@/api/queries';
import { api } from '@/api/client';

// Mock the entire api client module
vi.mock('@/api/client', () => ({
  api: {
    dashboard: vi.fn(),
    files: vi.fn(),
    pipelines: vi.fn(),
    tasks: vi.fn(),
    deals: vi.fn(),
    people: vi.fn(),
    heartbeat: vi.fn(),
    feed: vi.fn(),
    views: vi.fn(),
    sources: vi.fn(),
    plans: vi.fn(),
    sessions: vi.fn(),
    selfEvolve: vi.fn(),
    agents: vi.fn(),
  },
}));

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('React Query hooks', () => {
  // ---- useDashboard ----
  describe('useDashboard', () => {
    it('fetches dashboard data', async () => {
      const mockData = { services: [], stats: { runs_24h: 10 } };
      vi.mocked(api.dashboard).mockResolvedValue(mockData as any);

      const { result } = renderHook(() => useDashboard(), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
      expect(api.dashboard).toHaveBeenCalledTimes(1);
    });

    it('handles dashboard error', async () => {
      vi.mocked(api.dashboard).mockRejectedValue(new Error('HTTP 500'));

      const { result } = renderHook(() => useDashboard(), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.error?.message).toBe('HTTP 500');
    });
  });

  // ---- useFiles ----
  describe('useFiles', () => {
    it('does not fetch when disabled (default)', async () => {
      const { result } = renderHook(() => useFiles(), { wrapper: createWrapper() });
      // enabled defaults to false, should not fetch
      expect(api.files).not.toHaveBeenCalled();
      expect(result.current.isFetching).toBe(false);
    });

    it('fetches with date when enabled', async () => {
      const mockData = { claude_md: { content: '', lines: 0 } };
      vi.mocked(api.files).mockResolvedValue(mockData as any);

      const { result } = renderHook(() => useFiles('2024-01-15', true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(api.files).toHaveBeenCalledWith('2024-01-15');
    });

    it('fetches without date when enabled', async () => {
      const mockData = { claude_md: { content: '', lines: 0 } };
      vi.mocked(api.files).mockResolvedValue(mockData as any);

      const { result } = renderHook(() => useFiles(undefined, true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(api.files).toHaveBeenCalledWith(undefined);
    });
  });

  // ---- usePipelines ----
  describe('usePipelines', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => usePipelines(), { wrapper: createWrapper() });
      expect(api.pipelines).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      vi.mocked(api.pipelines).mockResolvedValue({ definitions: [], sessions: [] });

      const { result } = renderHook(() => usePipelines(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(api.pipelines).toHaveBeenCalledTimes(1);
    });
  });

  // ---- useTasks ----
  describe('useTasks', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useTasks(), { wrapper: createWrapper() });
      expect(api.tasks).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      const mockData = { sections: [], total: 0, overdue: 0, today: 0, completed_today: 0 };
      vi.mocked(api.tasks).mockResolvedValue(mockData);

      const { result } = renderHook(() => useTasks(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
    });
  });

  // ---- useDeals ----
  describe('useDeals', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useDeals(), { wrapper: createWrapper() });
      expect(api.deals).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      const mockData = { deals: [], stats: { total: 0, active: 0, pipeline_value: 0, overdue_followups: 0, avg_days_since_contact: 0 } };
      vi.mocked(api.deals).mockResolvedValue(mockData);

      const { result } = renderHook(() => useDeals(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
    });
  });

  // ---- usePeople ----
  describe('usePeople', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => usePeople(), { wrapper: createWrapper() });
      expect(api.people).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      const mockData = { people: [{ name: 'Test' }], stats: { total: 1, contacted_7d: 0, contacted_30d: 0, never_contacted: 1 } };
      vi.mocked(api.people).mockResolvedValue(mockData as any);

      const { result } = renderHook(() => usePeople(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data?.people).toHaveLength(1);
    });
  });

  // ---- useHeartbeat ----
  describe('useHeartbeat', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useHeartbeat(), { wrapper: createWrapper() });
      expect(api.heartbeat).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      const mockData = { runs: [], job_stats: {}, stats: {} };
      vi.mocked(api.heartbeat).mockResolvedValue(mockData as any);

      const { result } = renderHook(() => useHeartbeat(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    });
  });

  // ---- useFeed ----
  describe('useFeed', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useFeed(), { wrapper: createWrapper() });
      expect(api.feed).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      const mockData = { messages: [], topics: [], total: 0, generated_at: '2024-01-01' };
      vi.mocked(api.feed).mockResolvedValue(mockData);

      const { result } = renderHook(() => useFeed(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
    });
  });

  // ---- useViews ----
  describe('useViews', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useViews(), { wrapper: createWrapper() });
      expect(api.views).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      vi.mocked(api.views).mockResolvedValue({ views: [] });

      const { result } = renderHook(() => useViews(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    });
  });

  // ---- useSessions ----
  describe('useSessions', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useSessions(), { wrapper: createWrapper() });
      expect(api.sessions).not.toHaveBeenCalled();
    });

    it('fetches and unwraps sessions array', async () => {
      const sessions = [{ id: 's1', date: '2024-01-01', preview: 'hi', messages: 1, is_active: false }];
      vi.mocked(api.sessions).mockResolvedValue({ sessions } as any);

      const { result } = renderHook(() => useSessions(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      // useSessions unwraps: .then(r => r.sessions)
      expect(result.current.data).toEqual(sessions);
    });
  });

  // ---- useSelfEvolve ----
  describe('useSelfEvolve', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useSelfEvolve(), { wrapper: createWrapper() });
      expect(api.selfEvolve).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      const mockData = { metrics: { added: 0, fixed: 0, avg_days: '0', last_run: '' }, items: [] };
      vi.mocked(api.selfEvolve).mockResolvedValue(mockData);

      const { result } = renderHook(() => useSelfEvolve(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual(mockData);
    });
  });

  // ---- usePlans ----
  describe('usePlans', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => usePlans(), { wrapper: createWrapper() });
      expect(api.plans).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      vi.mocked(api.plans).mockResolvedValue({ plans: [{ name: 'p1', content: '', modified: '', size: 0 }] });

      const { result } = renderHook(() => usePlans(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data?.plans).toHaveLength(1);
    });
  });

  // ---- useAgents ----
  describe('useAgents', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useAgents(), { wrapper: createWrapper() });
      expect(api.agents).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      vi.mocked(api.agents).mockResolvedValue({ agents: [], max_concurrent: 5 });

      const { result } = renderHook(() => useAgents(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(result.current.data).toEqual({ agents: [], max_concurrent: 5 });
    });
  });

  // ---- useSources ----
  describe('useSources', () => {
    it('does not fetch when disabled', () => {
      renderHook(() => useSources(), { wrapper: createWrapper() });
      expect(api.sources).not.toHaveBeenCalled();
    });

    it('fetches when enabled', async () => {
      vi.mocked(api.sources).mockResolvedValue({} as any);

      const { result } = renderHook(() => useSources(true), { wrapper: createWrapper() });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
    });
  });
});
