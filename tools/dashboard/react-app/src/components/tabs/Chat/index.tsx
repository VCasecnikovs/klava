import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  ChatProvider,
  useChatContext,
  type AttachedFile,
  type Block,
} from '@/context/ChatContext';
import { api } from '@/api/client';
import { uuid } from './uuid';
import { ChatSidebar } from './ChatSidebar';
import { ChatInput } from './ChatInput';
import { renderChatMD } from './ChatMarkdown';
import { TodoPanel } from './TodoPanel';
import { ChangesPanel, extractChanges } from './ChangesPanel';
import { BlockRenderer } from './blocks/BlockRenderer';
import { ToolRunBlock } from './blocks/ToolRunBlock';
import { ThinkingBubble } from './blocks/ThinkingBubble';
import { PlanReviewBlock } from './blocks/PlanReviewBlock';
import { PermissionModal } from './blocks/PermissionModal';
import { CommsApprovalModal } from './blocks/CommsApprovalModal';
import { ChatErrorBoundary } from './ErrorBoundary';
import { QuotePopover } from './QuotePopover';
import { SvgLightbox } from './SvgLightbox';
import { extractArtifactRefs } from './artifacts/parseArtifact';

// --- Helper: extract artifact refs from blocks ---
function extractArtifactsFromBlocks(blocks: Block[], dispatch: React.Dispatch<import('@/context/ChatContext').ChatAction>) {
  for (const block of blocks) {
    if (block.type === 'assistant' && block.text) {
      const refs = extractArtifactRefs(block.text);
      for (const ref of refs) {
        dispatch({ type: 'ADD_ARTIFACT', artifact: ref });
      }
    }
  }
}

// --- Helper: extract task tool uses from a block array ---
export function extractTaskTools(blocks: Block[], handler: (tool: string, input: Record<string, unknown>) => void) {
  for (const block of blocks) {
    if (block.type === 'tool_use' && (block.tool === 'TaskCreate' || block.tool === 'TaskUpdate')) {
      handler(block.tool, (block.input as Record<string, unknown>) || {});
    }
    if (block.type === 'tool_group' && block.tools) {
      for (const t of block.tools) {
        if (t.tool === 'TaskCreate' || t.tool === 'TaskUpdate') {
          handler(t.tool, (t.input as Record<string, unknown>) || {});
        }
      }
    }
  }
}

// --- Block grouping: collapse consecutive tool/thinking blocks, detect plan pairs ---
const TOOL_BLOCK_TYPES = new Set(['tool_use', 'tool_group', 'tool_result']);

export type GroupedItem =
  | { type: 'tool_run'; blocks: Block[] }
  | { type: 'thinking_group'; blocks: Block[] }
  | { type: 'plan_review'; assistantBlock?: Block; planBlock: Block }
  | { type: 'single'; block: Block };

export function groupBlocks(blocks: Block[]): GroupedItem[] {
  const result: GroupedItem[] = [];
  let currentToolRun: Block[] = [];
  let currentThinking: Block[] = [];

  const flushTools = () => {
    if (currentToolRun.length > 0) {
      result.push({ type: 'tool_run', blocks: currentToolRun });
      currentToolRun = [];
    }
  };

  const flushThinking = () => {
    if (currentThinking.length > 0) {
      result.push({ type: 'thinking_group', blocks: currentThinking });
      currentThinking = [];
    }
  };

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];

    if (TOOL_BLOCK_TYPES.has(block.type)) {
      flushThinking();
      currentToolRun.push(block);
    } else if (block.type === 'thinking') {
      flushTools();
      currentThinking.push(block);
    } else {
      flushTools();
      flushThinking();

      // Detect plan review: plan(active:false) - collect assistant text written during plan mode
      if (block.type === 'plan' && !block.active) {
        // Find matching plan(active:true) in result and collect assistant text between
        let planStartIdx = -1;
        for (let j = result.length - 1; j >= 0; j--) {
          const item = result[j];
          if (item.type === 'single' && item.block.type === 'plan' && item.block.active) {
            planStartIdx = j;
            break;
          }
        }

        let collectedText = '';
        if (planStartIdx >= 0) {
          // Collect assistant text and remove plan banner + assistant blocks
          const toRemove: number[] = [planStartIdx]; // Remove EnterPlanMode banner
          for (let j = planStartIdx + 1; j < result.length; j++) {
            const item = result[j];
            if (item.type === 'single' && item.block.type === 'assistant' && item.block.text) {
              collectedText += item.block.text + '\n';
              toRemove.push(j);
            }
          }
          // Remove in reverse order to maintain indices
          for (let k = toRemove.length - 1; k >= 0; k--) {
            result.splice(toRemove[k], 1);
          }
        }

        const content = collectedText.trim() || block.content || '';
        if (content) {
          result.push({ type: 'plan_review', planBlock: { ...block, content } });
        } else {
          // Fallback: just show the banner
          result.push({ type: 'single', block });
        }
        continue;
      }

      // Legacy: assistant block followed by plan(active:false) without content
      if (block.type === 'assistant' && i + 1 < blocks.length) {
        const next = blocks[i + 1];
        if (next.type === 'plan' && !next.active) {
          result.push({ type: 'plan_review', assistantBlock: block, planBlock: next });
          i++; // skip the plan block
          continue;
        }
      }

      result.push({ type: 'single', block });
    }
  }
  flushTools();
  flushThinking();
  return result;
}

// --- ChatMain: Two-entity architecture (History + Realtime) ---

// Sessions sidebar default width
const SESSIONS_DEFAULT_WIDTH = 240;
const SESSIONS_MIN_WIDTH = 160;
const SESSIONS_MAX_WIDTH = 400;

function ChatMain({ onToggle, onFullscreen, isFullscreen, panelWidth }: { onToggle?: () => void; onFullscreen?: () => void; isFullscreen?: boolean; panelWidth?: number }) {
  const {
    state,
    dispatch,
    socketRef,
    messagesRef,
    streamingTextRef,
    sendMessageRef,
  } = useChatContext();

  const { tabId, claudeSessionId, watching, socketConnected, historyBlocks, realtimeBlocks, realtimeStatus, model, effort, sessionMode } = state;

  // Refs for mutable state accessed in event handlers (to avoid stale closures)
  const stateRef = useRef(state);
  stateRef.current = state;

  // --- Changes panel ---
  const [changesOpen, setChangesOpen] = useState(false);
  const allBlocks = useMemo(() => [...historyBlocks, ...realtimeBlocks], [historyBlocks, realtimeBlocks]);
  const changesCount = useMemo(() => {
    const { files, todoSnapshots } = extractChanges(allBlocks);
    return files.size + (todoSnapshots.length > 0 ? 1 : 0);
  }, [allBlocks]);

  // --- Sticky Todo / Task tracking ---
  const tasksRef = useRef<Array<{ id: string; subject: string; status: string; activeForm?: string }>>([]);

  const updateStickyTodo = useCallback((todos: Array<{ status?: string; content?: string; activeForm?: string }>) => {
    dispatch({ type: 'SET_TODOS', todos });
  }, [dispatch]);

  const syncTasksToPanel = useCallback(() => {
    const todos = tasksRef.current.map(t => ({
      status: t.status,
      content: t.subject,
      activeForm: t.activeForm,
    }));
    updateStickyTodo(todos);
  }, [updateStickyTodo]);

  const handleTaskToolUse = useCallback((toolName: string, input: Record<string, unknown>) => {
    if (toolName === 'TaskCreate') {
      const id = String(tasksRef.current.length + 1);
      tasksRef.current.push({
        id,
        subject: (input.subject as string) || '',
        status: 'pending',
        activeForm: (input.activeForm as string) || undefined,
      });
      syncTasksToPanel();
    } else if (toolName === 'TaskUpdate') {
      const taskId = input.taskId as string;
      const task = tasksRef.current.find(t => t.id === taskId);
      if (task) {
        if (input.status) task.status = input.status as string;
        if (input.activeForm !== undefined) task.activeForm = input.activeForm as string;
        if (input.subject) task.subject = input.subject as string;
        syncTasksToPanel();
      }
    }
  }, [syncTasksToPanel]);

  // --- Scroll helper with sticky mode ---
  const isSticky = useRef(true);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const scrollBottom = useCallback(() => {
    const el = messagesRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      isSticky.current = true;
      setShowScrollBtn(false);
    }
  }, [messagesRef]);

  // Check if user is near bottom (within 80px threshold)
  const checkSticky = useCallback(() => {
    const el = messagesRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    isSticky.current = atBottom;
    setShowScrollBtn(!atBottom);
  }, [messagesRef]);

  // Listen for user scroll events
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    const onScroll = () => checkSticky();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [messagesRef, checkSticky]);

  // Auto-scroll only when sticky
  useEffect(() => {
    if (isSticky.current) scrollBottom();
  }, [historyBlocks, realtimeBlocks, scrollBottom]);

  // --- Socket setup with two-entity event handling ---
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;

    // Guard against stale events from a previously-watched session leaking into
    // the active one. Backend events carry the producing session's tab_id; when
    // it's present and neither matches the current tabId nor the current
    // claudeSessionId, the event belongs to a session we no longer care about.
    // Resume-watch events from non-streaming sessions carry tab_id = session_id,
    // so we allow either to match.
    const isForeignEvent = (evtTabId?: string): boolean => {
      if (!evtTabId) return false;
      const s = stateRef.current;
      if (!s.tabId && !s.claudeSessionId) return false;
      return evtTabId !== s.tabId && evtTabId !== s.claudeSessionId;
    };

    const onConnect = () => {
      dispatch({ type: 'SET_CONNECTED', connected: true });
      dispatch({ type: 'RESET_RECONNECT' });
      const s = stateRef.current;
      if (s.wasConnected && s.claudeSessionId && socketRef.current?.connected) {
        socketRef.current.emit('watch_session', { session_id: s.claudeSessionId });
      }
      dispatch({ type: 'SET_WAS_CONNECTED', value: true });
    };

    const onDisconnect = () => {
      dispatch({ type: 'SET_CONNECTED', connected: false });
      dispatch({ type: 'INC_RECONNECT' });
    };

    // --- Entity 1: History events ---

    const onHistorySnapshot = (data: { blocks: Block[]; session_id?: string; model?: string }) => {
      const s = stateRef.current;
      if (data.session_id && s.claudeSessionId && data.session_id !== s.claudeSessionId && data.session_id !== s.tabId) {
        console.log('[history_snapshot] dropped foreign snapshot for', data.session_id, 'current:', s.claudeSessionId);
        return;
      }
      console.log('[history_snapshot]', data.blocks.length, 'blocks', 'model:', data.model);

      // Reset tasks and rebuild from history
      tasksRef.current = [];
      dispatch({ type: 'SET_TODOS', todos: [] });
      extractTaskTools(data.blocks, handleTaskToolUse);

      // Extract artifact refs from history
      dispatch({ type: 'RESET_ARTIFACTS' });
      extractArtifactsFromBlocks(data.blocks, dispatch);

      dispatch({ type: 'HISTORY_SNAPSHOT', blocks: data.blocks });

      // Restore session mode from last plan block in history
      const lastPlanBlock = [...data.blocks].reverse().find(b => b.type === 'plan');
      if (lastPlanBlock) {
        dispatch({ type: 'SET_SESSION_MODE', mode: lastPlanBlock.active ? 'plan' : 'bypass' });
      }

      // Auto-detect model from session history
      if (data.model) {
        const modelMap: Record<string, string> = {
          'claude-opus-4-7': 'opus',
          'claude-opus-4-7-20260401': 'opus',
          'claude-opus-4-6': 'opus',
          'claude-sonnet-4-6': 'sonnet',
          'claude-sonnet-4-6-20260301': 'sonnet',
          'claude-haiku-4-5': 'haiku',
          'claude-haiku-4-5-20251001': 'haiku',
        };
        const uiModel = modelMap[data.model] || (data.model.includes('opus') ? 'opus' : data.model.includes('sonnet') ? 'sonnet' : data.model.includes('haiku') ? 'haiku' : null);
        if (uiModel) dispatch({ type: 'SET_MODEL', model: uiModel });
      }
    };

    const onHistoryBlockAdd = (data: { block: Block; tab_id: string }) => {
      if (isForeignEvent(data.tab_id)) {
        console.log('[history_block_add] dropped foreign event', data.tab_id);
        return;
      }
      // From file watcher (external sessions)
      dispatch({ type: 'HISTORY_BLOCK_ADD', block: data.block });

      // Auto-toggle Mode for plan blocks from history
      if (data.block.type === 'plan') {
        dispatch({ type: 'SET_SESSION_MODE', mode: data.block.active ? 'plan' : 'bypass' });
      }

      // Track artifacts
      if (data.block.type === 'assistant' && data.block.text) {
        for (const ref of extractArtifactRefs(data.block.text)) {
          dispatch({ type: 'ADD_ARTIFACT', artifact: ref });
        }
      }

      // Track task tools
      if (data.block.type === 'tool_use' && (data.block.tool === 'TaskCreate' || data.block.tool === 'TaskUpdate')) {
        handleTaskToolUse(data.block.tool, (data.block.input as Record<string, unknown>) || {});
      }
      if (data.block.type === 'tool_group' && data.block.tools) {
        for (const t of data.block.tools) {
          if (t.tool === 'TaskCreate' || t.tool === 'TaskUpdate') {
            handleTaskToolUse(t.tool, (t.input as Record<string, unknown>) || {});
          }
        }
      }
    };

    // --- Entity 2: Realtime events ---

    const onRealtimeSnapshot = (data: { blocks: Block[]; streaming: boolean; queue?: Array<{ text: string; index: number }>; tab_id: string; elapsed?: number }) => {
      // Snapshot from a foreign session means our last watch_session hasn't
      // settled yet. Don't overwrite the current session's realtime state.
      if (isForeignEvent(data.tab_id)) {
        console.log('[realtime_snapshot] dropped foreign snapshot for', data.tab_id);
        return;
      }
      console.log('[realtime_snapshot]', data.blocks.length, 'blocks, streaming:', data.streaming, 'tab:', data.tab_id);

      // Only adopt tab_id from streaming sessions (their tab_id is the
      // real owner). For non-streaming watch, keep the tabId the frontend
      // already set in handleResumeSession.
      if (data.streaming && data.tab_id) {
        dispatch({ type: 'SET_TAB_ID', tabId: data.tab_id });
      }
      dispatch({ type: 'REALTIME_SNAPSHOT', blocks: data.blocks });

      // Track task tools from realtime blocks
      extractTaskTools(data.blocks, handleTaskToolUse);
      extractArtifactsFromBlocks(data.blocks, dispatch);

      if (data.streaming) {
        dispatch({ type: 'SET_REALTIME_STATUS', status: 'streaming' });
        // Only set streamStart from backend elapsed if not already tracking locally.
        // If chatStartStream already set streamStart (user sent a message), keep it -
        // backend elapsed is session-total time which would show e.g. "thinking 21m"
        // instead of the correct per-message elapsed.
        if (!stateRef.current.streamStart) {
          const elapsedMs = (data.elapsed || 0) * 1000;
          dispatch({ type: 'SET_STREAM_START', time: Date.now() - elapsedMs });
        }
      } else {
        dispatch({ type: 'SET_REALTIME_STATUS', status: 'idle' });
      }

      if (data.queue && data.queue.length > 0) {
        dispatch({ type: 'SET_BACKEND_QUEUE', queue: data.queue, sessionId: data.tab_id });
      }
    };

    const onRealtimeBlockAdd = (data: { block: Block; tab_id: string }) => {
      if (isForeignEvent(data.tab_id)) {
        console.log('[realtime_block_add] dropped foreign event', data.tab_id);
        return;
      }
      console.log('[realtime_block_add]', data.block.type, 'id:', data.block.id, 'tab:', data.tab_id);

      // Track task tools
      if (data.block.type === 'tool_use' && (data.block.tool === 'TaskCreate' || data.block.tool === 'TaskUpdate')) {
        handleTaskToolUse(data.block.tool, (data.block.input as Record<string, unknown>) || {});
      }
      if (data.block.type === 'tool_group' && data.block.tools) {
        for (const t of data.block.tools) {
          if (t.tool === 'TaskCreate' || t.tool === 'TaskUpdate') {
            handleTaskToolUse(t.tool, (t.input as Record<string, unknown>) || {});
          }
        }
      }

      // Track artifacts
      if (data.block.type === 'assistant' && data.block.text) {
        for (const ref of extractArtifactRefs(data.block.text)) {
          dispatch({ type: 'ADD_ARTIFACT', artifact: ref });
        }
      }

      // Auto-toggle Mode: Bypass ↔ Plan when agent calls EnterPlanMode / ExitPlanMode
      if (data.block.type === 'plan') {
        dispatch({ type: 'SET_SESSION_MODE', mode: data.block.active ? 'plan' : 'bypass' });
      }

      dispatch({ type: 'REALTIME_BLOCK_ADD', block: data.block });

      // Side effects for cost/error blocks
      if (data.block.type === 'cost') {
        if (data.block.session_id) {
          const s = stateRef.current;
          dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: data.block.session_id });
          if (s.tabId) {
            dispatch({ type: 'UPDATE_SESSION_REAL_ID', tabId: s.tabId, realId: data.block.session_id });
          }
          // Backend handles adding to active list via _run_claude result handler
        }
      }
    };

    const onRealtimeBlockUpdate = (data: { id: number; patch: Partial<Block>; tab_id: string }) => {
      if (isForeignEvent(data.tab_id)) return;
      // For streaming assistant text, update the imperative ref directly for performance
      if (data.patch.text !== undefined) {
        const s = stateRef.current;
        const block = s.realtimeBlocks.find(b => b.id === data.id);
        if (block?.type === 'assistant' && streamingTextRef.current) {
          streamingTextRef.current.innerHTML = renderChatMD(data.patch.text);
        }
      }

      dispatch({ type: 'REALTIME_BLOCK_UPDATE', id: data.id, patch: data.patch });
    };

    const onRealtimeDone = (data: { has_next: boolean; tab_id: string }) => {
      if (isForeignEvent(data.tab_id)) {
        console.log('[realtime_done] dropped foreign event', data.tab_id);
        return;
      }
      console.log('[realtime_done] has_next:', data.has_next);
      const s = stateRef.current;

      // Freeze realtime blocks into history
      dispatch({ type: 'HISTORY_SNAPSHOT', blocks: [...s.historyBlocks, ...s.realtimeBlocks] });
      dispatch({ type: 'REALTIME_RESET' });

      if (data.has_next) {
        dispatch({ type: 'SET_REALTIME_STATUS', status: 'streaming' });
      } else {
        dispatch({ type: 'SET_REALTIME_STATUS', status: 'idle' });
      }
    };

    // --- Other events ---

    const onQueueUpdate = (data: { queue?: Array<{ text: string; index: number }>; tab_id?: string }) => {
      if (isForeignEvent(data.tab_id)) return;
      const queue = data.queue || [];
      dispatch({ type: 'SET_BACKEND_QUEUE', queue, sessionId: data.tab_id || undefined });
    };

    const onWatchStarted = (data?: { session_id?: string; tab_id?: string }) => {
      dispatch({ type: 'SET_WATCHING', watching: true });
      if (data?.tab_id) {
        dispatch({ type: 'SET_TAB_ID', tabId: data.tab_id });
      }
    };

    const onWatchStopped = () => {
      dispatch({ type: 'SET_WATCHING', watching: false });
    };

    const onPermissionRequest = (data: { tool?: string; description?: string; tab_id?: string }) => {
      const s = stateRef.current;
      if (data.tab_id && data.tab_id !== s.tabId) return;

      // Auto-respond based on permission mode
      if (s.permissionMode === 'accept_all') {
        if (socketRef.current) socketRef.current.emit('permission_response', { allow: true });
        return;
      }
      if (s.permissionMode === 'deny_all') {
        if (socketRef.current) socketRef.current.emit('permission_response', { allow: false });
        return;
      }

      dispatch({
        type: 'SET_PENDING_PERMISSION',
        permission: { tool: data.tool || '', description: data.description || '', tab_id: data.tab_id },
      });
    };

    const onCommsApprovalRequest = (data: { channel?: string; recipient?: string; message?: string; tool_name?: string; tab_id?: string }) => {
      const s = stateRef.current;
      if (data.tab_id && data.tab_id !== s.tabId) return;
      dispatch({
        type: 'SET_PENDING_COMMS',
        comms: {
          channel: data.channel || '',
          recipient: data.recipient || '',
          message: data.message || '',
          tool_name: data.tool_name || '',
          tab_id: data.tab_id,
        },
      });
    };

    const onCancelled = () => {
      // Same pattern as onRealtimeDone: freeze realtime blocks into history
      // before reset. Without this, everything streamed pre-cancel vanishes
      // from the chat until the user leaves and re-enters the session
      // (server still has them in CHAT_SESSIONS['blocks']).
      const s = stateRef.current;
      dispatch({ type: 'HISTORY_SNAPSHOT', blocks: [...s.historyBlocks, ...s.realtimeBlocks] });
      dispatch({ type: 'REALTIME_RESET' });
    };

    const onSessionNotFound = (data: { session_id?: string }) => {
      const s = stateRef.current;
      // Only handle if this is for our current session
      if (data.session_id && s.claudeSessionId && data.session_id !== s.claudeSessionId) return;
      console.warn('[session_not_found]', data.session_id);
      // Reset to welcome screen - session no longer exists
      dispatch({ type: 'SET_TAB_ID', tabId: null });
      dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: null });
      dispatch({ type: 'HISTORY_SNAPSHOT', blocks: [] });
      dispatch({ type: 'REALTIME_RESET' });
    };

    // Register all handlers
    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('history_snapshot', onHistorySnapshot);
    socket.on('history_block_add', onHistoryBlockAdd);
    socket.on('realtime_snapshot', onRealtimeSnapshot);
    socket.on('realtime_block_add', onRealtimeBlockAdd);
    socket.on('realtime_block_update', onRealtimeBlockUpdate);
    socket.on('realtime_done', onRealtimeDone);
    socket.on('queue_update', onQueueUpdate);
    socket.on('watch_started', onWatchStarted);
    socket.on('watch_stopped', onWatchStopped);
    socket.on('permission_request', onPermissionRequest);
    socket.on('comms_approval_request', onCommsApprovalRequest);
    socket.on('session_not_found', onSessionNotFound);
    socket.on('cancelled', onCancelled);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('history_snapshot', onHistorySnapshot);
      socket.off('history_block_add', onHistoryBlockAdd);
      socket.off('realtime_snapshot', onRealtimeSnapshot);
      socket.off('realtime_block_add', onRealtimeBlockAdd);
      socket.off('realtime_block_update', onRealtimeBlockUpdate);
      socket.off('realtime_done', onRealtimeDone);
      socket.off('queue_update', onQueueUpdate);
      socket.off('watch_started', onWatchStarted);
      socket.off('watch_stopped', onWatchStopped);
      socket.off('permission_request', onPermissionRequest);
      socket.off('comms_approval_request', onCommsApprovalRequest);
      socket.off('cancelled', onCancelled);
      socket.off('session_not_found', onSessionNotFound);
    };
  }, [socketConnected, socketRef, dispatch, messagesRef, scrollBottom, handleTaskToolUse, streamingTextRef]);

  // --- Load sidebar sessions on mount ---
  useEffect(() => {
    api.sessions().then(data => {
      dispatch({ type: 'SET_SESSIONS', sessions: data.sessions });
    }).catch(() => { /* ignore load failure */ });
  }, [dispatch]);

  // --- Session management ---
  const chatStopWatching = useCallback(() => {
    const s = stateRef.current;
    if (s.watching && socketRef.current) {
      socketRef.current.emit('unwatch_session', { session_id: s.claudeSessionId });
      dispatch({ type: 'SET_WATCHING', watching: false });
    }
  }, [socketRef, dispatch]);

  const chatStartStream = useCallback((text: string, files: AttachedFile[]) => {
    chatStopWatching();
    const s = stateRef.current;
    let currentTabId = s.tabId;
    const resumeSessionId = s.claudeSessionId;

    const isNewSession = !currentTabId;
    if (isNewSession) {
      currentTabId = uuid();
      dispatch({ type: 'SET_TAB_ID', tabId: currentTabId });
      dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: null });
      dispatch({ type: 'ADD_SESSION', session: {
        id: currentTabId,
        date: new Date().toISOString(),
        preview: text.substring(0, 40),
        messages: 1,
        is_active: true,
      }});
      // Backend adds to active list via on_send_message handler
      dispatch({ type: 'SET_SIDEBAR_FILTER', filter: 'active' });
    }

    // Save model/effort for this session so switching back restores it
    if (currentTabId) {
      try {
        const map = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
        map[currentTabId] = { ...(map[currentTabId] || {}), model: s.model, effort: s.effort };
        localStorage.setItem('chat_session_settings', JSON.stringify(map));
      } catch {}
    }

    dispatch({ type: 'SET_REALTIME_STATUS', status: 'streaming' });
    dispatch({ type: 'SET_STREAM_START', time: Date.now() });

    // Optimistic user block at id 0 (realtime always starts fresh)
    dispatch({ type: 'REALTIME_BLOCK_ADD', block: { type: 'user', id: 0, text, files: files.length > 0 ? files : undefined } });

    const payload: Record<string, unknown> = {
      prompt: text,
      tab_id: currentTabId,
      model,
      effort,
      mode: sessionMode,
    };
    if (resumeSessionId) payload.resume_session_id = resumeSessionId;
    if (files.length > 0) payload.files = files.map(f => ({ name: f.name, path: f.path, type: f.type }));
    console.log('[chatStartStream] emitting send_message, socket.connected:', socketRef.current?.connected, 'payload tab_id:', payload.tab_id);
    socketRef.current?.emit('send_message', payload);
  }, [chatStopWatching, dispatch, socketRef, model, effort, sessionMode]);

  // --- HTTP fallback for when Socket.IO is unavailable (e.g. mobile/Tailscale) ---
  const httpSend = useCallback((text: string, files: AttachedFile[]) => {
    const s = stateRef.current;
    let currentTabId = s.tabId;
    const resumeSessionId = s.claudeSessionId;

    if (!currentTabId) {
      currentTabId = uuid();
      dispatch({ type: 'SET_TAB_ID', tabId: currentTabId });
      dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: null });
      dispatch({ type: 'ADD_SESSION', session: {
        id: currentTabId,
        date: new Date().toISOString(),
        preview: text.substring(0, 40),
        messages: 1,
        is_active: true,
      }});
      dispatch({ type: 'SET_SIDEBAR_FILTER', filter: 'active' });
    }

    dispatch({ type: 'SET_REALTIME_STATUS', status: 'streaming' });
    dispatch({ type: 'REALTIME_BLOCK_ADD', block: { type: 'user', id: 0, text, files: files.length > 0 ? files : undefined } });

    const payload: { prompt: string; tab_id: string; model: string; effort: string; resume_session_id?: string; files?: Array<{ name: string; path: string; type: string }> } = {
      prompt: text,
      tab_id: currentTabId,
      model,
      effort,
    };
    if (resumeSessionId) payload.resume_session_id = resumeSessionId;
    if (files.length > 0) payload.files = files.map(f => ({ name: f.name, path: f.path, type: f.type }));

    console.log('[httpSend] POST /api/chat/send', payload.tab_id);
    api.chatSendHttp(payload).then(res => {
      console.log('[httpSend] response:', res);
    }).catch(err => {
      console.error('[httpSend] failed:', err);
      dispatch({ type: 'REALTIME_BLOCK_ADD', block: { type: 'error', id: 1, message: `HTTP send failed: ${err.message}` } });
      dispatch({ type: 'SET_REALTIME_STATUS', status: 'idle' });
    });
  }, [dispatch, model, effort]);

  // --- Public actions ---
  const handleSend = useCallback((text: string, files: AttachedFile[]): boolean => {
    console.log('[handleSend] socket:', !!socketRef.current, 'connected:', socketRef.current?.connected, 'id:', socketRef.current?.id);

    // Socket.IO available - use it
    if (socketRef.current?.connected) {
      if (stateRef.current.realtimeStatus === 'streaming') {
        const payload: Record<string, unknown> = {
          prompt: text,
          tab_id: stateRef.current.tabId,
          model,
          effort,
          mode: stateRef.current.sessionMode,
        };
        if (stateRef.current.claudeSessionId) payload.resume_session_id = stateRef.current.claudeSessionId;
        if (files.length > 0) payload.files = files.map(f => ({ name: f.name, path: f.path, type: f.type }));
        socketRef.current.emit('send_message', payload);
        return true;
      }

      chatStartStream(text, files);
      scrollBottom();
      return true;
    }

    // HTTP fallback when socket is not connected
    console.log('[handleSend] using HTTP fallback');
    httpSend(text, files);
    scrollBottom();
    return true;
  }, [socketRef, chatStartStream, model, effort, scrollBottom, httpSend]);

  // Expose handleSend to artifact components via context ref
  useEffect(() => {
    sendMessageRef.current = (text: string) => handleSend(text, []);
    return () => { sendMessageRef.current = null; };
  }, [handleSend]);

  // Listen for chat:send-message from Views/artifacts (MCP App bridge)
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail?.text;
      if (text && sendMessageRef.current) sendMessageRef.current(text);
    };
    window.addEventListener('chat:send-message', handler);
    return () => window.removeEventListener('chat:send-message', handler);
  }, []);

  const handleCancel = useCallback(() => {
    if (socketRef.current) socketRef.current.emit('cancel', { tab_id: stateRef.current.tabId });
  }, [socketRef]);

  const handleNewSession = useCallback(() => {
    chatStopWatching();
    if (stateRef.current.realtimeStatus === 'streaming' && socketRef.current) {
      socketRef.current.emit('detach_all');
    }
    dispatch({ type: 'SET_TAB_ID', tabId: null });
    dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: null });
    dispatch({ type: 'HISTORY_SNAPSHOT', blocks: [] });
    dispatch({ type: 'REALTIME_RESET' });
    dispatch({ type: 'SET_REALTIME_STATUS', status: 'idle' });
    tasksRef.current = [];
    dispatch({ type: 'SET_TODOS', todos: [] });
    dispatch({ type: 'RESET_ARTIFACTS' });
    dispatch({ type: 'SET_PERMISSION_MODE', mode: 'ask' });
    // Reset to global defaults for new session
    dispatch({ type: 'SET_MODEL', model: localStorage.getItem('chat_model') || 'opus' });
    dispatch({ type: 'SET_EFFORT', effort: localStorage.getItem('chat_effort') || 'high' });
  }, [chatStopWatching, socketRef, dispatch]);

  // Listen for cross-tab "send to new session" events (e.g. from Tasks tab,
  // or Deck's Session button which spawns an empty session + prefills the input).
  // With text: reset + auto-send (fire-and-forget delegation).
  // Without text: reset only — caller typically follows up with
  //   `chat:prefill-input` so the user can edit before sending.
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail?.text;
      window.location.hash = 'chat';
      handleNewSession();
      if (text) {
        requestAnimationFrame(() => {
          handleSend(text, []);
        });
      }
    };
    window.addEventListener('chat:new-session', handler);
    return () => window.removeEventListener('chat:new-session', handler);
  }, [handleNewSession, handleSend]);

  // Per-message fork: UserBlock dispatches chat:fork-from-block with a block id.
  // Call backend, then switch this tab to the newly-created forked tab.
  useEffect(() => {
    const handler = async (e: Event) => {
      const blockId = (e as CustomEvent).detail?.block_id;
      if (blockId == null) return;
      const s = stateRef.current;
      const sourceTabId = s.tabId;
      if (!sourceTabId) return;
      try {
        const res = await api.chatFork({
          source_tab_id: sourceTabId,
          from_block_id: blockId,
          model: s.model,
          effort: s.effort,
          session_mode: s.sessionMode,
        });
        if (!res.ok || !res.tab_id) return;
        chatStopWatching();
        dispatch({ type: 'SET_TAB_ID', tabId: res.tab_id });
        dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: null });
        dispatch({ type: 'HISTORY_SNAPSHOT', blocks: [] });
        dispatch({ type: 'REALTIME_RESET' });
        dispatch({ type: 'SET_REALTIME_STATUS', status: 'streaming' });
        dispatch({ type: 'SET_STREAM_START', time: Date.now() });
        scrollBottom();
      } catch (err) {
        console.error('[Chat] fork failed:', err);
      }
    };
    window.addEventListener('chat:fork-from-block', handler);
    return () => window.removeEventListener('chat:fork-from-block', handler);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleResumeSession = useCallback(async (sid: string) => {
    const s = stateRef.current;
    if (s.claudeSessionId === sid || s.tabId === sid) {
      scrollBottom();
      if (!s.watching && socketRef.current?.connected && s.claudeSessionId) {
        socketRef.current.emit('watch_session', { session_id: s.claudeSessionId });
      }
      return;
    }

    chatStopWatching();
    dispatch({ type: 'SET_BACKEND_QUEUE', queue: [] });

    // Check if sid is a pending tab_id (session still running, no claude UUID yet).
    // This happens when the streaming_sessions broadcast uses tab_id as the id fallback.
    // In this case we must NOT set claudeSessionId=sid because sid is a frontend UUID,
    // not a real claude session UUID - doing so causes resume_session_id=tab_id on the
    // next send which makes the SDK try --resume with an invalid UUID.
    const isPendingTab = s.activeSessions.some(a => a.tab_id === sid && !a.session_id);

    if (isPendingTab) {
      // Join the in-progress stream: adopt the tab_id, leave claudeSessionId null
      dispatch({ type: 'SET_TAB_ID', tabId: sid });
      dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: null });
    } else {
      const newTabId = uuid();
      dispatch({ type: 'SET_TAB_ID', tabId: newTabId });
      dispatch({ type: 'SET_CLAUDE_SESSION_ID', claudeSessionId: sid });

      // Restore per-session model/effort (fallback to hardcoded defaults, not global)
      try {
        const map = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
        const saved = map[sid];
        dispatch({ type: 'SET_MODEL', model: saved?.model || 'opus' });
        dispatch({ type: 'SET_EFFORT', effort: saved?.effort || 'high' });
      } catch {}

      if (stateRef.current.unreadSessions.has(sid)) {
        api.chatStateRead(sid).catch(() => {});
      }
    }

    // Don't add to active list just from viewing - only add when actually sending a message
    // Don't force-switch to "active" filter - if user clicked from "all",
    // switching to "active" and then getting session_not_found causes it to vanish

    // Clear both entities and show loading state
    dispatch({ type: 'HISTORY_SNAPSHOT', blocks: [] });
    dispatch({ type: 'REALTIME_RESET' });
    dispatch({ type: 'SET_REALTIME_STATUS', status: 'idle' });
    tasksRef.current = [];
    dispatch({ type: 'SET_TODOS', todos: [] });
    dispatch({ type: 'RESET_ARTIFACTS' });

    if (socketRef.current?.connected) {
      socketRef.current.emit('watch_session', { session_id: sid });
    }
  }, [chatStopWatching, dispatch, scrollBottom, socketRef]);

  // Listen for cross-tab "resume session" events (e.g. from Feed tab)
  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId } = (e as CustomEvent).detail || {};
      if (sessionId) {
        window.dispatchEvent(new Event('chat:open'));
        handleResumeSession(sessionId);
      }
    };
    window.addEventListener('chat:resume-session', handler);
    return () => window.removeEventListener('chat:resume-session', handler);
  }, [handleResumeSession]);

  // Determine if we show welcome screen
  const showWelcome = historyBlocks.length === 0 && realtimeBlocks.length === 0 && realtimeStatus === 'idle' && !tabId;
  const showLoading = historyBlocks.length === 0 && realtimeBlocks.length === 0 && tabId;

  // Pre-filter blocks for rendering
  const visibleHistory = historyBlocks.filter(b => b.type !== '_removed');
  const visibleRealtime = realtimeBlocks.filter(b => b.type !== '_removed');

  // Group tool runs for collapsed display
  const groupedHistory = useMemo(() => groupBlocks(visibleHistory), [visibleHistory]);
  const groupedRealtime = useMemo(() => groupBlocks(visibleRealtime), [visibleRealtime]);

  // Sessions sidebar: collapsible, persistent, resizable
  const [sessionsVisible, setSessionsVisible] = useState(() => {
    try { return localStorage.getItem('chat-sessions-visible') !== 'false'; } catch { return true; }
  });
  const [sessionsWidth, setSessionsWidth] = useState(() => {
    try {
      const saved = parseInt(localStorage.getItem('chat-sessions-width') || '', 10);
      if (saved >= SESSIONS_MIN_WIDTH) return saved;
    } catch { /* ignore */ }
    return SESSIONS_DEFAULT_WIDTH;
  });

  // Persist sessions sidebar state
  useEffect(() => { localStorage.setItem('chat-sessions-visible', String(sessionsVisible)); }, [sessionsVisible]);
  useEffect(() => { localStorage.setItem('chat-sessions-width', String(sessionsWidth)); }, [sessionsWidth]);

  // Sessions resize handler
  const handleSessionsResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = sessionsWidth;
    const onMove = (ev: MouseEvent) => {
      const newW = Math.max(SESSIONS_MIN_WIDTH, Math.min(SESSIONS_MAX_WIDTH, startW + ev.clientX - startX));
      setSessionsWidth(newW);
    };
    const onUp = () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [sessionsWidth]);

  return (
    <>
      {/* Sessions sidebar - collapsible */}
      {sessionsVisible && (
        <>
          <div className="chat-sidebar" style={{ width: sessionsWidth }}>
            <div className="chat-sidebar-head">
              <span className="chat-sidebar-title">Sessions</span>
              <button className="chat-new-btn" onClick={handleNewSession} title="New chat">+</button>
            </div>
            <ChatSidebar
              onResumeSession={(sid) => {
                handleResumeSession(sid);
                if (window.innerWidth <= 768) setSessionsVisible(false);
              }}
              onNewSession={handleNewSession}
            />
          </div>
          <div className="chat-sessions-resize" onMouseDown={handleSessionsResize} />
        </>
      )}

      <div className="chat-main">
        {/* Header */}
        <div className="chat-header">
          <div className="chat-header-left">
            {/* Sessions toggle button */}
            <button
              className="chat-header-btn"
              onClick={() => setSessionsVisible(prev => !prev)}
              title={sessionsVisible ? 'Hide sessions' : 'Show sessions'}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <span className="chat-session-id" style={{ display: 'flex', flexDirection: 'column', gap: 1, lineHeight: 1.2 }}>
              <span
                title={claudeSessionId || 'no session'}
                onClick={() => claudeSessionId && navigator.clipboard.writeText(claudeSessionId)}
                style={{ cursor: claudeSessionId ? 'pointer' : 'default' }}
              >
                <span style={{ opacity: 0.4, fontSize: '0.8em', marginRight: 3 }}>session</span>
                <span>{claudeSessionId ? claudeSessionId.substring(0, 12) + '...' : 'pending'}</span>
              </span>
              <span
                title={tabId || 'no tab'}
                onClick={() => tabId && navigator.clipboard.writeText(tabId)}
                style={{ cursor: tabId ? 'pointer' : 'default' }}
              >
                <span style={{ opacity: 0.4, fontSize: '0.8em', marginRight: 3 }}>tab</span>
                <span style={{ opacity: 0.7 }}>{tabId ? tabId.substring(0, 12) + '...' : ''}</span>
              </span>
            </span>
            {watching && realtimeStatus === 'streaming' && (
              <span className="chat-live-badge">
                <span className="chat-live-dot" />
                Live
              </span>
            )}
            {!socketConnected && (
              <span style={{ fontSize: 10, color: 'var(--red)', marginLeft: 4 }}>offline</span>
            )}
          </div>
          <div className="chat-header-right">
            <button
              className={`chat-header-btn${changesOpen ? ' active' : ''}`}
              onClick={() => setChangesOpen(prev => !prev)}
              title="Session changes"
              style={{ position: 'relative' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="12" y1="18" x2="12" y2="12" />
                <line x1="9" y1="15" x2="15" y2="15" />
              </svg>
              {changesCount > 0 && (
                <span className="chat-changes-badge">{changesCount}</span>
              )}
            </button>
            {onFullscreen && (
              <button className="chat-header-btn" onClick={onFullscreen} title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'}>
                {isFullscreen ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="4 14 10 14 10 20" />
                    <polyline points="20 10 14 10 14 4" />
                    <line x1="14" y1="10" x2="21" y2="3" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                )}
              </button>
            )}
            {onToggle && !isFullscreen && (
              <button className="chat-header-btn" onClick={onToggle} title="Collapse chat (Cmd+B)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="11 17 6 12 11 7" />
                  <line x1="6" y1="12" x2="18" y2="12" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Messages - always visible (artifact opens as split panel) */}
        <div className="chat-messages" ref={messagesRef}>
          {!socketConnected && (
            <div id="chat-reconnect" className="chat-reconnect-banner">
              <span className="chat-loading-dots"><span /><span /><span /></span> Reconnecting...
            </div>
          )}
          {showWelcome ? (
            <div className="chat-welcome">
              <div className="chat-welcome-title">Claude Code</div>
              <div className="chat-welcome-sub">Start a new conversation</div>
            </div>
          ) : showLoading ? (
            <div className="chat-loading" style={{ justifyContent: 'center', padding: '40px' }}>
              <div className="chat-loading-dots"><span /><span /><span /></div> Loading...
            </div>
          ) : (
            <>
              {/* Entity 1: History - loaded from JSONL, immutable */}
              {groupedHistory.map((item, idx) => {
                if (item.type === 'tool_run') return <ToolRunBlock key={`hg-${idx}`} blocks={item.blocks} isStreaming={false} />;
                if (item.type === 'thinking_group') return <ThinkingBubble key={`ht-${idx}`} blocks={item.blocks} />;
                if (item.type === 'plan_review') return <PlanReviewBlock key={`hp-${idx}`} assistantBlock={item.assistantBlock} planBlock={item.planBlock} />;
                return (
                  <BlockRenderer
                    key={`h-${item.block.id}`}
                    block={item.block}
                    isStreaming={false}
                    isLast={false}
                  />
                );
              })}

              {/* Entity 2: Realtime - streaming from backend */}
              {groupedRealtime.map((item, idx) => {
                if (item.type === 'tool_run') return <ToolRunBlock key={`rg-${idx}`} blocks={item.blocks} isStreaming={realtimeStatus === 'streaming'} />;
                if (item.type === 'thinking_group') return <ThinkingBubble key={`rt-${idx}`} blocks={item.blocks} />;
                if (item.type === 'plan_review') return <PlanReviewBlock key={`rp-${idx}`} assistantBlock={item.assistantBlock} planBlock={item.planBlock} />;
                return (
                  <BlockRenderer
                    key={`r-${item.block.id}`}
                    block={item.block}
                    isStreaming={realtimeStatus === 'streaming'}
                    isLast={idx === groupedRealtime.length - 1 && item.block.type === 'assistant'}
                  />
                );
              })}
            </>
          )}
        </div>

        {/* Todo state panel */}
        <TodoPanel />

        {/* Changes panel - right overlay */}
        <ChangesPanel blocks={allBlocks} open={changesOpen} onClose={() => setChangesOpen(false)} />

        {/* Quote popover for text selection */}
        <QuotePopover containerRef={messagesRef} />

        {/* Scroll to bottom button */}
        {showScrollBtn && (
          <button className="chat-scroll-bottom-btn" onClick={scrollBottom} title="Scroll to bottom">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        )}

        {/* Input owns its own controls bar (spinner, context usage, mode toggle, model/effort/attach/expand) */}
        <ChatInput onSend={handleSend} onCancel={handleCancel} />
      </div>

      {/* Permission modal - React component */}
      <PermissionModal />
      <CommsApprovalModal />
      <SvgLightbox />
    </>
  );
}

// --- Main exported component ---

export function ChatPanel({ mode, width, onWidthChange, onToggle, onFullscreen }: {
  mode: 'collapsed' | 'sidebar' | 'full';
  width: number;
  onWidthChange: (w: number) => void;
  onToggle: () => void;
  onFullscreen: () => void;
}) {
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    startX.current = e.clientX;
    startWidth.current = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const dx = ev.clientX - startX.current;
      const maxW = Math.floor(window.innerWidth * 0.5);
      const newW = Math.max(360, Math.min(maxW, startWidth.current + dx));
      onWidthChange(newW);
    };

    const onUp = () => {
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [width, onWidthChange]);

  // Inline width style for sidebar mode only
  const panelStyle: React.CSSProperties | undefined = mode === 'sidebar' ? { width: `${width}px` } : undefined;

  return (
    <>
      {/* Collapsed strip - visible when chat is hidden */}
      <div
        className={`chat-collapsed-strip${mode !== 'collapsed' ? ' hidden' : ''}`}
        onClick={onToggle}
        title="Open chat (Cmd+B)"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
      </div>

      {/* Chat panel */}
      <div
        className={`chat-panel${mode === 'collapsed' ? ' collapsed' : ''}${mode === 'full' ? ' fullscreen' : ''}`}
        style={panelStyle}
      >
        <ChatProvider>
          <div className="chat-layout">
            <ChatErrorBoundary>
              <ChatMain onToggle={onToggle} onFullscreen={onFullscreen} isFullscreen={mode === 'full'} panelWidth={mode === 'sidebar' ? width : undefined} />
            </ChatErrorBoundary>
          </div>
        </ChatProvider>

        {/* Resize handle - only in sidebar mode */}
        {mode === 'sidebar' && (
          <div className="chat-resize-handle" onMouseDown={handleResizeStart} />
        )}
      </div>
    </>
  );
}
