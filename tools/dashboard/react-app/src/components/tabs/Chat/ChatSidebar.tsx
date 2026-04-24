import { useCallback, useRef, useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useChatContext, type SidebarFilter } from '@/context/ChatContext';
import { useAgents } from '@/api/queries';
import { api } from '@/api/client';
import type { Session, Agent } from '@/api/types';
import { timeAgo } from '@/lib/utils';

const AGENT_STATUS_COLORS: Record<string, string> = {
  running: 'var(--blue)',
  starting: 'var(--yellow)',
  completed: 'var(--green)',
  failed: 'var(--red)',
  killed: 'var(--red)',
  idle: 'var(--text-dim)',
  processing_message: 'var(--blue)',
};

function classifySession(s: Session): 'cron' | 'human' {
  const p = (s.preview || '').toLowerCase();
  if (p.startsWith('[heartbeat') || p.includes('heartbeat')) return 'cron';
  if (p.startsWith('you are synthesizing') || p.includes('screen recording')) return 'cron';
  if (s.project?.includes('Dayflow')) return 'cron';
  return 'human';
}

interface ChatSidebarProps {
  onResumeSession: (sessionId: string) => void;
  onNewSession: () => void;
}

export function ChatSidebar({ onResumeSession, onNewSession }: ChatSidebarProps) {
  const { state, dispatch, socketRef } = useChatContext();
  const { allSessions, activeSessions, sessionNames, sidebarFilter, tabId, claudeSessionId, streamingSessions, unreadSessions, realtimeStatus, streamStart } = state;
  const listRef = useRef<HTMLDivElement>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const editInputRef = useRef<HTMLInputElement>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Session[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const [tick, setTick] = useState(0); // triggers re-render for elapsed timer + spinner
  const syncedAtRef = useRef(Date.now());
  const queryClient = useQueryClient();
  const { data: agentsData } = useAgents(true);
  const agents = agentsData?.agents ?? [];
  const [agentsExpanded, setAgentsExpanded] = useState(true);

  // Real-time agent updates via existing socket
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;
    const handler = () => queryClient.invalidateQueries({ queryKey: ['agents'] });
    socket.on('agent_update', handler);
    return () => { socket.off('agent_update', handler); };
  }, [socketRef, queryClient]);

  const handleKillAgent = useCallback(async (agentId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try { await api.agentKill(agentId); } catch {}
  }, []);

  const handleDeleteAgent = useCallback(async (agentId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await fetch(`/api/agents/${agentId}`, { method: 'DELETE' });
      queryClient.invalidateQueries({ queryKey: ['agents'] });
    } catch {}
  }, [queryClient]);

  // Track when streaming sessions are synced from backend
  useEffect(() => {
    syncedAtRef.current = Date.now();
  }, [streamingSessions]);

  // Tick every second while any session is streaming
  const hasStreaming = streamingSessions.size > 0 || realtimeStatus === 'streaming';
  useEffect(() => {
    if (!hasStreaming) return;
    const id = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(id);
  }, [hasStreaming]);

  const setFilter = useCallback((filter: SidebarFilter) => {
    dispatch({ type: 'SET_SIDEBAR_FILTER', filter });
  }, [dispatch]);

  const removeActive = useCallback((sid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Find the active entry to get both tab_id and session_id
    const entry = activeSessions.find(a => a.session_id === sid || a.tab_id === sid);
    if (entry && socketRef.current) {
      socketRef.current.emit('remove_active', { tab_id: entry.tab_id, session_id: entry.session_id });
    }
    // If closing the currently viewed session, reset to welcome screen
    const isCurrent = claudeSessionId ? (claudeSessionId === sid) : (tabId === sid);
    if (isCurrent) {
      onNewSession();
    }
  }, [activeSessions, socketRef, claudeSessionId, tabId, onNewSession]);

  const cancelSession = useCallback((sid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    api.chatStateCancel(sid).catch(() => {});
  }, []);

  const forkSession = useCallback(async (sid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const result = await api.sessionFork(sid);
      // Refresh sessions list, then open the fork
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
      onResumeSession(result.session_id);
    } catch (err) {
      console.error('Fork failed:', err);
    }
  }, [queryClient, onResumeSession]);

  const startRename = useCallback((sid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(sid);
  }, []);

  const saveRename = useCallback((sid: string, value: string) => {
    const val = value.trim();
    if (val) {
      dispatch({ type: 'SET_SESSION_NAME', sessionId: sid, name: val });
    }
    setEditingId(null);
  }, [dispatch]);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  // Debounced full-text search
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (searchQuery.length < 2) {
      setSearchResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchTimerRef.current = setTimeout(() => {
      api.sessionsSearch(searchQuery)
        .then(data => setSearchResults(data.sessions))
        .catch(() => setSearchResults(null))
        .finally(() => setSearching(false));
    }, 300);
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current); };
  }, [searchQuery]);

  // Filter sessions
  let sessions: Session[];
  if (searchResults) {
    sessions = searchResults;
  } else if (sidebarFilter === 'active') {
    const activeIds = new Set(
      activeSessions.map(a => a.session_id || a.tab_id).filter(Boolean) as string[]
    );
    sessions = allSessions.filter(s => activeIds.has(s.id));
  } else if (sidebarFilter === 'human') {
    sessions = allSessions.filter(s => classifySession(s) === 'human');
  } else if (sidebarFilter === 'cron') {
    sessions = allSessions.filter(s => classifySession(s) === 'cron');
  } else {
    sessions = allSessions;
  }

  const showRemove = sidebarFilter === 'active';

  const filterBar = (
    <div style={{ display: 'flex', borderBottom: '1px solid var(--border)' }}>
      {(['active', 'all', 'human', 'cron'] as SidebarFilter[]).map(f => (
        <button
          key={f}
          className={`chat-filter-btn${sidebarFilter === f ? ' active' : ''}`}
          data-filter={f}
          onClick={() => setFilter(f)}
        >
          {f.charAt(0).toUpperCase() + f.slice(1)}
        </button>
      ))}
    </div>
  );

  const searchBar = (
    <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
      <input
        type="text"
        placeholder="Search sessions..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        style={{
          width: '100%',
          background: 'var(--bg)',
          color: 'var(--text)',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: '4px 8px',
          fontSize: 12,
          outline: 'none',
          boxSizing: 'border-box',
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--blue)'; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
      />
    </div>
  );

  const sessionList = (
    <div className="chat-sidebar-list" ref={listRef}>
      {searching && (
        <div className="chat-sidebar-empty" style={{ opacity: 0.5 }}>Searching...</div>
      )}
      {!searching && sessions.length === 0 && searchResults !== null && (
        <div className="chat-sidebar-empty">No matches</div>
      )}
      {!searching && sessions.length === 0 && searchResults === null && sidebarFilter === 'active' && (
        <div className="chat-sidebar-empty">
          No active chats.<br />Start a new chat or open one from All.
        </div>
      )}
      {!searching && sessions.length === 0 && searchResults === null && sidebarFilter !== 'active' && (
        <div className="chat-sidebar-empty">No sessions found</div>
      )}

      {sessions.map(s => {
        const isCurrent = claudeSessionId ? claudeSessionId === s.id : tabId === s.id;
        const date = s.date ? timeAgo(s.date) : '';
        const kind = classifySession(s);
        const displayName = sessionNames[s.id] || s.preview || 'New chat';
        const isEditing = editingId === s.id;
        const isLocalStreaming = isCurrent && realtimeStatus === 'streaming';
        const isSessionStreaming = streamingSessions.has(s.id) || isLocalStreaming;
        const streamInfo = streamingSessions.get(s.id);
        const isUnread = unreadSessions.has(s.id) && !isCurrent;

        return (
          <div
            key={s.id}
            className={`chat-sidebar-item${isCurrent ? ' active' : ''}`}
            onClick={() => onResumeSession(s.id)}
          >
            <div className="chat-sidebar-item-row">
              <div
                className="chat-sidebar-item-title"
                onDoubleClick={window.innerWidth > 768 ? (e) => startRename(s.id, e) : undefined}
              >
                {isSessionStreaming && <span className="chat-streaming-dot" />}
                {!isSessionStreaming && isUnread && <span className="chat-unread-dot" />}
                {kind === 'cron' && (
                  <span style={{ color: 'var(--yellow)', fontSize: 8, marginRight: 3 }}>&#9679;</span>
                )}
                {isEditing ? (
                  <input
                    ref={editInputRef}
                    type="text"
                    defaultValue={sessionNames[s.id] || s.preview || ''}
                    style={{
                      width: '100%',
                      background: 'var(--bg)',
                      color: 'var(--text)',
                      border: '1px solid var(--blue)',
                      borderRadius: 4,
                      padding: '2px 6px',
                      fontSize: 12,
                      outline: 'none',
                    }}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => saveRename(s.id, e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { e.preventDefault(); (e.target as HTMLInputElement).blur(); }
                      if (e.key === 'Escape') setEditingId(null);
                    }}
                  />
                ) : (
                  displayName
                )}
              </div>
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <span className="chat-sidebar-fork" onClick={(e) => forkSession(s.id, e)} title="Fork session">&#9095;</span>
                {isSessionStreaming && (
                  <span className="chat-sidebar-cancel" onClick={(e) => cancelSession(s.id, e)} title="Cancel">&#9632;</span>
                )}
                {showRemove && !isSessionStreaming && (
                  <span className="chat-sidebar-remove" onClick={(e) => removeActive(s.id, e)} title="Remove from active">&times;</span>
                )}
              </div>
            </div>
            {s.snippet && (
              <div style={{ fontSize: 10, color: 'var(--text-dim)', padding: '2px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.snippet}
              </div>
            )}
            <div className="chat-sidebar-item-meta">
              {date}
              {s.messages ? ` \u00b7 ${s.messages} msgs` : ''}
              {isSessionStreaming && (() => {
                const symbols = ['\u00b7', '\u273B', '\u273D', '\u2736', '\u2733', '\u2722'];
                let localElapsed: number;
                let toolLabel: string;
                if (streamInfo && streamInfo.elapsed !== undefined) {
                  localElapsed = streamInfo.elapsed + Math.floor((Date.now() - syncedAtRef.current) / 1000);
                  const evt = streamInfo.last_event;
                  toolLabel = !evt
                    ? 'thinking'
                    : evt.type === 'external'
                      ? 'terminal'
                      : evt.type === 'tool_use'
                        ? evt.tool || 'tool'
                        : evt.type === 'thinking_delta'
                          ? 'thinking'
                          : 'writing';
                } else {
                  // Local streaming, no backend sync yet
                  localElapsed = streamStart ? Math.floor((Date.now() - streamStart) / 1000) : 0;
                  toolLabel = 'thinking';
                }
                const symbol = symbols[tick % symbols.length];
                const timeStr = localElapsed >= 60
                  ? `${Math.floor(localElapsed / 60)}m ${localElapsed % 60}s`
                  : `${localElapsed}s`;
                return (
                  <span style={{ color: 'var(--green)', marginLeft: 4, fontFamily: 'var(--mono)', fontSize: '10px' }}>
                    {symbol} {toolLabel} {timeStr}
                  </span>
                );
              })()}
            </div>
          </div>
        );
      })}
    </div>
  );

  const runningAgents = agents.filter(a => a.status === 'running' || a.status === 'pending_retry');

  const agentsSection = agents.length > 0 ? (
    <div className="chat-sidebar-agents">
      <div
        className="chat-sidebar-agents-header"
        onClick={() => setAgentsExpanded(e => !e)}
      >
        <span>
          Agents
          {runningAgents.length > 0 && (
            <span className="chat-sidebar-agents-badge">{runningAgents.length}</span>
          )}
          {runningAgents.length === 0 && (
            <span className="chat-sidebar-agents-count">{agents.length}</span>
          )}
        </span>
        <span style={{ fontSize: 10, opacity: 0.5 }}>{agentsExpanded ? '\u25BE' : '\u25B8'}</span>
      </div>
      {agentsExpanded && (
        <div className="chat-sidebar-agents-list">
          {agents.map(agent => {
            const isAlive = agent.status === 'running' || agent.status === 'pending_retry';
            const isDead = agent.status === 'completed' || agent.status === 'failed' || agent.status === 'killed';
            const statusColor = AGENT_STATUS_COLORS[agent.status] || 'var(--text-dim)';
            const elapsed = agent.started ? Math.floor(Date.now() / 1000 - agent.started) : 0;
            const elapsedStr = elapsed >= 3600
              ? `${Math.floor(elapsed / 3600)}h ${Math.floor((elapsed % 3600) / 60)}m`
              : elapsed >= 60
                ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`
                : `${elapsed}s`;
            return (
              <div
                key={agent.id}
                className={`chat-sidebar-agent-item${isAlive ? ' alive' : ''}${agent.session_id ? ' clickable' : ''}`}
                onClick={() => agent.session_id && onResumeSession(agent.session_id)}
                style={agent.session_id ? { cursor: 'pointer' } : undefined}
              >
                <div className="chat-sidebar-item-row">
                  <div className="chat-sidebar-item-title">
                    <span
                      className={`chat-agent-status-dot${isAlive ? ' running' : ''}`}
                      style={{ color: statusColor }}
                    >
                      {'\u25CF'}
                    </span>
                    {agent.name}
                  </div>
                  <div style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
                    {isAlive && (
                      <span
                        className="chat-sidebar-remove"
                        onClick={(e) => handleKillAgent(agent.id, e)}
                        title="Kill agent"
                      >
                        {'\u25A0'}
                      </span>
                    )}
                    {isDead && (
                      <span
                        className="chat-sidebar-remove"
                        onClick={(e) => handleDeleteAgent(agent.id, e)}
                        title="Remove"
                      >
                        &times;
                      </span>
                    )}
                  </div>
                </div>
                <div className="chat-sidebar-item-meta">
                  <span className="chat-agent-model-badge">{agent.model}</span>
                  {' '}
                  <span style={{ color: 'var(--yellow)' }}>${agent.cost_usd.toFixed(3)}</span>
                  {isAlive && (
                    <span style={{ color: 'var(--green)', marginLeft: 4 }}>{elapsedStr}</span>
                  )}
                  {agent.output_lines > 0 && (
                    <span style={{ opacity: 0.5 }}> · {agent.output_lines}L</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  ) : null;

  // Content only - parent provides the wrapper div with width/visibility
  return (
    <>
      {filterBar}
      {searchBar}
      {sessionList}
      {agentsSection}
    </>
  );
}
