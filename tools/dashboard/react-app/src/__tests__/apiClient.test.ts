import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from '@/api/client';

// Mock global fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockJsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  });
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe('api client', () => {
  // ---- GET endpoints ----
  describe('GET endpoints', () => {
    it('dashboard fetches /api/dashboard', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ health: 'ok' }));
      const result = await api.dashboard();
      expect(mockFetch).toHaveBeenCalledWith('/api/dashboard');
      expect(result).toEqual({ health: 'ok' });
    });

    it('sessions fetches /api/sessions', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ sessions: [] }));
      const result = await api.sessions();
      expect(mockFetch).toHaveBeenCalledWith('/api/sessions');
      expect(result).toEqual({ sessions: [] });
    });

    it('session fetches /api/sessions/:id', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ session_id: 'abc', messages: [] }));
      await api.session('abc');
      expect(mockFetch).toHaveBeenCalledWith('/api/sessions/abc');
    });

    it('files fetches /api/files with optional date param', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ files: [] }));
      await api.files('2024-01-15');
      expect(mockFetch).toHaveBeenCalledWith('/api/files?date=2024-01-15');
    });

    it('files fetches /api/files without date param', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ files: [] }));
      await api.files();
      expect(mockFetch).toHaveBeenCalledWith('/api/files');
    });

    it('chatState fetches /api/chat/state', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ active_sessions: [] }));
      await api.chatState();
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/state');
    });
  });

  // ---- POST endpoints ----
  describe('POST endpoints', () => {
    it('chatStateName posts with correct body', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({}));
      await api.chatStateName('sess-1', 'My Chat');
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/state/name', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: 'sess-1', name: 'My Chat' }),
      });
    });

    it('chatStateRead posts with session id', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({}));
      await api.chatStateRead('sess-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/state/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: 'sess-1' }),
      });
    });

    it('chatStateCancel posts with session id', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({}));
      await api.chatStateCancel('sess-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/state/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: 'sess-1' }),
      });
    });
  });

  // ---- Error handling ----
  describe('error handling', () => {
    it('throws on non-OK GET response', async () => {
      mockFetch.mockReturnValue(mockJsonResponse(null, 500));
      await expect(api.dashboard()).rejects.toThrow('HTTP 500');
    });

    it('throws on non-OK POST response', async () => {
      mockFetch.mockReturnValue(mockJsonResponse(null, 403));
      await expect(api.chatStateName('s', 'name')).rejects.toThrow('HTTP 403');
    });

    it('throws on 404', async () => {
      mockFetch.mockReturnValue(mockJsonResponse(null, 404));
      await expect(api.session('nonexistent')).rejects.toThrow('HTTP 404');
    });
  });

  // ---- uploadFile ----
  describe('uploadFile', () => {
    it('posts FormData to /api/chat/upload', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ files: [{ name: 'test.txt', path: '/tmp/test.txt', url: '/files/test.txt', size: 100, type: 'text/plain' }] }));
      const file = new File(['content'], 'test.txt', { type: 'text/plain' });
      const result = await api.uploadFile(file);
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/upload', expect.objectContaining({ method: 'POST' }));
      expect(result.files).toHaveLength(1);
    });

    it('throws on upload failure', async () => {
      mockFetch.mockReturnValue(mockJsonResponse(null, 500));
      const file = new File(['content'], 'test.txt');
      await expect(api.uploadFile(file)).rejects.toThrow('Upload failed: 500');
    });
  });

  // ---- updateTask ----
  describe('updateTask', () => {
    it('posts task update with note', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      await api.updateTask('task-1', 'complete', 'Done');
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: 'task-1', action: 'complete', note: 'Done' }),
      });
    });

    it('throws on task update failure', async () => {
      mockFetch.mockReturnValue(mockJsonResponse(null, 500));
      await expect(api.updateTask('task-1', 'complete')).rejects.toThrow('Task update failed: 500');
    });

    it('posts task update without note', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      await api.updateTask('task-2', 'snooze');
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: 'task-2', action: 'snooze', note: undefined }),
      });
    });
  });

  // ---- remaining GET endpoints (full coverage) ----
  describe('remaining GET endpoints', () => {
    it('pipelines fetches /api/pipelines', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ definitions: [], sessions: [] }));
      const result = await api.pipelines();
      expect(mockFetch).toHaveBeenCalledWith('/api/pipelines');
      expect(result).toEqual({ definitions: [], sessions: [] });
    });

    it('tasks fetches /api/tasks', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ sections: [], total: 0 }));
      const result = await api.tasks();
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks');
      expect(result).toEqual({ sections: [], total: 0 });
    });

    it('deals fetches /api/deals', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ deals: [], stats: {} }));
      const result = await api.deals();
      expect(mockFetch).toHaveBeenCalledWith('/api/deals');
      expect(result).toEqual({ deals: [], stats: {} });
    });

    it('people fetches /api/people', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ people: [], stats: {} }));
      const result = await api.people();
      expect(mockFetch).toHaveBeenCalledWith('/api/people');
      expect(result).toEqual({ people: [], stats: {} });
    });

    it('heartbeat fetches /api/heartbeat', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ runs: [] }));
      const result = await api.heartbeat();
      expect(mockFetch).toHaveBeenCalledWith('/api/heartbeat');
      expect(result).toEqual({ runs: [] });
    });

    it('feed fetches /api/feed', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ messages: [] }));
      const result = await api.feed();
      expect(mockFetch).toHaveBeenCalledWith('/api/feed');
      expect(result).toEqual({ messages: [] });
    });

    it('views fetches /api/views', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ views: [] }));
      const result = await api.views();
      expect(mockFetch).toHaveBeenCalledWith('/api/views');
      expect(result).toEqual({ views: [] });
    });

    it('sources fetches /api/sources', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ telegram: {} }));
      const result = await api.sources();
      expect(mockFetch).toHaveBeenCalledWith('/api/sources');
      expect(result).toEqual({ telegram: {} });
    });

    it('plans fetches /api/plans', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ plans: [] }));
      const result = await api.plans();
      expect(mockFetch).toHaveBeenCalledWith('/api/plans');
      expect(result).toEqual({ plans: [] });
    });

    it('sessionsSearch fetches with encoded query', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ sessions: [] }));
      await api.sessionsSearch('hello world');
      expect(mockFetch).toHaveBeenCalledWith('/api/sessions/search?q=hello%20world');
    });

    it('selfEvolve fetches /api/self-evolve', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ metrics: {}, items: [] }));
      const result = await api.selfEvolve();
      expect(mockFetch).toHaveBeenCalledWith('/api/self-evolve');
      expect(result).toEqual({ metrics: {}, items: [] });
    });

    it('agents fetches /api/agents', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ agents: [], max_concurrent: 3 }));
      const result = await api.agents();
      expect(mockFetch).toHaveBeenCalledWith('/api/agents');
      expect(result).toEqual({ agents: [], max_concurrent: 3 });
    });

    it('agentDetail fetches /api/agents/:id', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ id: 'a1', name: 'Test', output: [] }));
      const result = await api.agentDetail('a1');
      expect(mockFetch).toHaveBeenCalledWith('/api/agents/a1');
      expect(result).toEqual({ id: 'a1', name: 'Test', output: [] });
    });
  });

  // ---- remaining POST endpoints ----
  describe('remaining POST endpoints', () => {
    it('chatSendHttp posts message payload', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true, queued: true }));
      const payload = { prompt: 'Hello', tab_id: 'tab-1', model: 'opus' };
      const result = await api.chatSendHttp(payload);
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      expect(result).toEqual({ ok: true, queued: true });
    });

    it('chatSendHttp with resume_session_id and files', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      const payload = {
        prompt: 'Check this',
        tab_id: 'tab-2',
        model: 'sonnet',
        resume_session_id: 'sess-old',
        files: [{ name: 'f.txt', path: '/tmp/f.txt', type: 'text/plain' }],
      };
      await api.chatSendHttp(payload);
      expect(mockFetch).toHaveBeenCalledWith('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    });

    it('sessionFork posts to /api/sessions/:id/fork', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ session_id: 'new-1', source_id: 'old-1', name: 'Fork', messages: 5 }));
      const result = await api.sessionFork('old-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/sessions/old-1/fork', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      expect(result).toEqual({ session_id: 'new-1', source_id: 'old-1', name: 'Fork', messages: 5 });
    });

    it('selfEvolveUpdate posts item updates', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      const result = await api.selfEvolveUpdate('Bug fix', { status: 'done' });
      expect(mockFetch).toHaveBeenCalledWith('/api/self-evolve/item', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Bug fix', updates: { status: 'done' } }),
      });
      expect(result).toEqual({ ok: true });
    });

    it('selfEvolveRun posts to /api/self-evolve/run', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ status: 'ok', output: 'done' }));
      const result = await api.selfEvolveRun();
      expect(mockFetch).toHaveBeenCalledWith('/api/self-evolve/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      expect(result).toEqual({ status: 'ok', output: 'done' });
    });

    it('dislike posts feedback', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      await api.dislike(42, 'bad text', 'wrong answer', 'sess-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/feedback/dislike', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block_id: 42, text_preview: 'bad text', comment: 'wrong answer', session_id: 'sess-1' }),
      });
    });

    it('dislike without sessionId', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      await api.dislike(1, 'text', 'comment');
      expect(mockFetch).toHaveBeenCalledWith('/api/feedback/dislike', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block_id: 1, text_preview: 'text', comment: 'comment', session_id: undefined }),
      });
    });

    it('agentKill posts to /api/agents/:id/kill', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ status: 'killed' }));
      const result = await api.agentKill('agent-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/agents/agent-1/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      expect(result).toEqual({ status: 'killed' });
    });
  });

  // ---- openView ----
  describe('openView', () => {
    it('posts to /api/views/open with default browser=false', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      await api.openView('report.html');
      expect(mockFetch).toHaveBeenCalledWith('/api/views/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: 'report.html', browser: false }),
      });
    });

    it('posts to /api/views/open with browser=true', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      await api.openView('report.html', true);
      expect(mockFetch).toHaveBeenCalledWith('/api/views/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: 'report.html', browser: true }),
      });
    });

    it('does not throw on non-OK response (no ok check)', async () => {
      // openView does NOT check resp.ok before calling json()
      mockFetch.mockReturnValue(mockJsonResponse({ error: 'not found' }, 404));
      const result = await api.openView('missing.html');
      expect(result).toEqual({ error: 'not found' });
    });
  });

  // ---- selfEvolveDelete ----
  describe('selfEvolveDelete', () => {
    it('sends DELETE to /api/self-evolve/item', async () => {
      mockFetch.mockReturnValue(mockJsonResponse({ ok: true }));
      const result = await api.selfEvolveDelete('Old item');
      expect(mockFetch).toHaveBeenCalledWith('/api/self-evolve/item', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Old item' }),
      });
      expect(result).toEqual({ ok: true });
    });

    it('throws on non-OK DELETE response', async () => {
      mockFetch.mockReturnValue(mockJsonResponse(null, 500));
      await expect(api.selfEvolveDelete('Bad')).rejects.toThrow('HTTP 500');
    });
  });
});
