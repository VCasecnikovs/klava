import {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useRef,
  type ReactNode,
  type Dispatch,
} from 'react';
import { io, type Socket } from 'socket.io-client';
import type { Session } from '@/api/types';
import { api, type StreamingSession } from '@/api/client';
import type { ArtifactRef } from '@/components/tabs/Chat/artifacts/types';

// --- Types ---

export interface AttachedFile {
  name: string;
  path: string;
  type: string;
  size: number;
  url?: string;
  thumbUrl?: string;
}

export interface QueuedMessage {
  text: string;
  files: AttachedFile[];
}

export interface ToolUseData {
  tool: string;
  input: unknown;
  id?: string;
  _sid?: string;
}

export type SidebarFilter = 'active' | 'all' | 'human' | 'cron';

export interface ActiveEntry {
  tab_id: string | null;
  session_id: string | null;
}

// Block type used by both backend and React rendering
export interface Block {
  type: string;
  id: number;
  text?: string;
  files?: AttachedFile[];
  words?: number;
  preview?: string;
  tool?: string;
  input?: unknown;
  running?: boolean;
  duration_ms?: number;
  start_time?: number;
  content?: string;
  tools?: Block[];
  agent_blocks?: Block[];
  label?: string;
  questions?: Array<{
    header?: string;
    question?: string;
    multiSelect?: boolean;
    options?: Array<{ label: string; description?: string }>;
  }>;
  answered?: boolean;
  active?: boolean;
  seconds?: number;
  cost?: number;
  session_id?: string;
  message?: string;
  pending?: boolean;
  subtype?: string | null;
  stop_reason?: string | null;
  num_turns?: number | null;
  duration_api_ms?: number | null;
  usage?: {
    input_tokens?: number;
    output_tokens?: number;
    cache_creation_input_tokens?: number;
    cache_read_input_tokens?: number;
    [k: string]: unknown;
  } | null;
  permission_denials?: Array<{ tool?: string | null; reason?: string | null }>;
  errors?: string[];
  model?: string | null;
  model_usage?: Record<string, {
    input_tokens?: number;
    output_tokens?: number;
    cache_read_input_tokens?: number;
    cache_creation_input_tokens?: number;
    cost_usd?: number;
    [k: string]: unknown;
  }>;
  status?: string;
  rate_limit_type?: string;
  utilization?: number | null;
  resets_at?: number | null;
  overage_status?: string;
  overage_resets_at?: number | null;
  overage_disabled_reason?: string | null;
}

export interface PermissionRequest {
  tool: string;
  description: string;
  tab_id?: string;
}

export interface CommsApprovalRequest {
  channel: string;
  recipient: string;
  message: string;
  tool_name: string;
  tab_id?: string;
}

export interface ChatState {
  socketConnected: boolean;
  tabId: string | null;              // Frontend UUID, stable for lifetime of chat slot
  claudeSessionId: string | null;    // Real Claude UUID, null until result arrives
  watching: boolean;
  allSessions: Session[];
  activeSessions: ActiveEntry[];
  sessionNames: Record<string, string>;
  backendQueue: Array<{ text: string; index: number }>;
  queueSessionId: string | null;
  sessionQueues: Record<string, Array<{ text: string; index: number }>>;
  streamStart: number | null;
  sidebarFilter: SidebarFilter;
  wasConnected: boolean;
  reconnectAttempts: number;
  attachedFiles: AttachedFile[];
  lastToolName: string | null;
  lastToolInput: unknown;
  lastToolStartTime: number;
  streamingSessions: Map<string, StreamingSession>;
  unreadSessions: Set<string>;
  todos: Array<{ status?: string; content?: string; activeForm?: string }>;
  todosCollapsed: boolean;
  // Two-entity chat architecture
  historyBlocks: Block[];
  realtimeBlocks: Block[];
  realtimeStatus: 'idle' | 'streaming' | 'ready';
  model: string;
  effort: string;
  pendingPermission: PermissionRequest | null;
  pendingComms: CommsApprovalRequest | null;
  permissionMode: 'ask' | 'accept_all' | 'deny_all';
  sessionMode: 'bypass' | 'plan';
  activeArtifact: ArtifactRef | null;
  sessionArtifacts: ArtifactRef[];
  drafts: Record<string, string>;
}

// --- Actions ---

export type ChatAction =
  | { type: 'SET_CONNECTED'; connected: boolean }
  | { type: 'SET_TAB_ID'; tabId: string | null }
  | { type: 'SET_CLAUDE_SESSION_ID'; claudeSessionId: string | null }
  | { type: 'UPDATE_SESSION_REAL_ID'; tabId: string; realId: string }
  | { type: 'SET_WATCHING'; watching: boolean }
  | { type: 'SET_SESSIONS'; sessions: Session[] }
  | { type: 'ADD_SESSION'; session: Session }
  | { type: 'SET_SESSION_NAME'; sessionId: string; name: string }
  | { type: 'RENAME_SESSION_KEY'; oldId: string; newId: string }
  | { type: 'SET_BACKEND_QUEUE'; queue: Array<{ text: string; index: number }>; sessionId?: string }
  | { type: 'SET_STREAM_START'; time: number }
  | { type: 'SET_SIDEBAR_FILTER'; filter: SidebarFilter }
  | { type: 'SET_WAS_CONNECTED'; value: boolean }
  | { type: 'INC_RECONNECT' }
  | { type: 'RESET_RECONNECT' }
  | { type: 'SET_ATTACHED_FILES'; files: AttachedFile[] }
  | { type: 'ADD_ATTACHED_FILE'; file: AttachedFile }
  | { type: 'REMOVE_ATTACHED_FILE'; index: number }
  | { type: 'CLEAR_ATTACHED_FILES' }
  | { type: 'SET_LAST_TOOL'; name: string | null; input?: unknown; startTime?: number }
  | { type: 'CHAT_STATE_SYNC'; activeSessions: ActiveEntry[]; sessionNames: Record<string, string>; streamingSessions: StreamingSession[]; unreadSessions: string[]; drafts?: Record<string, string> }
  | { type: 'SET_TODOS'; todos: Array<{ status?: string; content?: string; activeForm?: string }> }
  | { type: 'TOGGLE_TODOS_COLLAPSED' }
  // Two-entity chat architecture
  | { type: 'HISTORY_SNAPSHOT'; blocks: Block[] }
  | { type: 'HISTORY_BLOCK_ADD'; block: Block }
  | { type: 'REALTIME_SNAPSHOT'; blocks: Block[] }
  | { type: 'REALTIME_BLOCK_ADD'; block: Block }
  | { type: 'REALTIME_BLOCK_UPDATE'; id: number; patch: Partial<Block> }
  | { type: 'REALTIME_RESET' }
  | { type: 'SET_REALTIME_STATUS'; status: 'idle' | 'streaming' | 'ready' }
  | { type: 'SET_MODEL'; model: string }
  | { type: 'SET_EFFORT'; effort: string }
  | { type: 'SET_PENDING_PERMISSION'; permission: PermissionRequest | null }
  | { type: 'SET_PENDING_COMMS'; comms: CommsApprovalRequest | null }
  | { type: 'SET_PERMISSION_MODE'; mode: 'ask' | 'accept_all' | 'deny_all' }
  | { type: 'SET_SESSION_MODE'; mode: 'bypass' | 'plan' }
  | { type: 'OPEN_ARTIFACT'; filename: string; title: string; path?: string }
  | { type: 'CLOSE_ARTIFACT' }
  | { type: 'ADD_ARTIFACT'; artifact: ArtifactRef }
  | { type: 'RESET_ARTIFACTS' }
  | { type: 'SET_DRAFTS'; drafts: Record<string, string> }
  | { type: 'SET_DRAFT'; sessionId: string; text: string };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'SET_CONNECTED':
      return { ...state, socketConnected: action.connected };
    case 'SET_TAB_ID':
      return { ...state, tabId: action.tabId };
    case 'SET_CLAUDE_SESSION_ID':
      return { ...state, claudeSessionId: action.claudeSessionId };
    case 'UPDATE_SESSION_REAL_ID': {
      // Replace tabId entry with real UUID in allSessions (backend handles activeSessions)
      const { tabId, realId } = action;
      // Migrate per-session settings from tabId to realId
      try {
        const map = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
        if (map[tabId]) {
          map[realId] = map[tabId];
          delete map[tabId];
          localStorage.setItem('chat_session_settings', JSON.stringify(map));
        }
      } catch {}
      // If realId already exists in allSessions (e.g. loaded from API via SET_SESSIONS),
      // just remove the temp tabId entry to avoid creating a duplicate with the same id.
      const alreadyHasReal = state.allSessions.some(s => s.id === realId);
      return {
        ...state,
        allSessions: alreadyHasReal
          ? state.allSessions.filter(s => s.id !== tabId)
          : state.allSessions.map(s => s.id === tabId ? { ...s, id: realId } : s),
      };
    }
    case 'SET_WATCHING':
      return { ...state, watching: action.watching };
    case 'SET_SESSIONS': {
      // Race: chat_state_sync usually arrives before /api/sessions finishes
      // (socket is instant; HTTP reads dozens of JSONL files). chat_state_sync
      // synthesizes entries in allSessions for active sessions older than the
      // top-50 returned by /api/sessions. Replacing wholesale would wipe them
      // until the next broadcast. Merge instead: keep existing entries that
      // are active/streaming and not in the fresh fetch.
      const freshIds = new Set(action.sessions.map(s => s.id));
      const activeIds = new Set(
        state.activeSessions
          .map(a => a.session_id || a.tab_id)
          .filter(Boolean) as string[]
      );
      const streamingIds = new Set(state.streamingSessions.keys());
      const preserved = state.allSessions.filter(
        s => (activeIds.has(s.id) || streamingIds.has(s.id)) && !freshIds.has(s.id)
      );
      return { ...state, allSessions: [...preserved, ...action.sessions] };
    }
    case 'ADD_SESSION':
      return { ...state, allSessions: [action.session, ...state.allSessions] };
    case 'SET_SESSION_NAME': {
      const names = { ...state.sessionNames, [action.sessionId]: action.name };
      api.chatStateName(action.sessionId, action.name).catch(() => {});
      return { ...state, sessionNames: names };
    }
    case 'RENAME_SESSION_KEY': {
      const names = { ...state.sessionNames };
      if (names[action.oldId]) {
        names[action.newId] = names[action.oldId];
        delete names[action.oldId];
      }
      return { ...state, sessionNames: names };
    }
    case 'SET_BACKEND_QUEUE': {
      const sid = action.sessionId || state.queueSessionId;
      const newQueues = { ...state.sessionQueues };
      if (sid) {
        if (action.queue.length > 0) {
          newQueues[sid] = action.queue;
        } else {
          delete newQueues[sid];
        }
      }
      return { ...state, backendQueue: action.queue, queueSessionId: sid, sessionQueues: newQueues };
    }
    case 'SET_STREAM_START':
      return { ...state, streamStart: action.time };
    case 'SET_SIDEBAR_FILTER':
      try { localStorage.setItem('chat_sidebar_filter', action.filter); } catch { /* ignore */ }
      return { ...state, sidebarFilter: action.filter };
    case 'SET_WAS_CONNECTED':
      return { ...state, wasConnected: action.value };
    case 'INC_RECONNECT':
      return { ...state, reconnectAttempts: state.reconnectAttempts + 1 };
    case 'RESET_RECONNECT':
      return { ...state, reconnectAttempts: 0 };
    case 'SET_ATTACHED_FILES':
      return { ...state, attachedFiles: action.files };
    case 'ADD_ATTACHED_FILE':
      return { ...state, attachedFiles: [...state.attachedFiles, action.file] };
    case 'REMOVE_ATTACHED_FILE': {
      const f = state.attachedFiles[action.index];
      if (f?.thumbUrl) URL.revokeObjectURL(f.thumbUrl);
      return {
        ...state,
        attachedFiles: state.attachedFiles.filter((_, i) => i !== action.index),
      };
    }
    case 'CLEAR_ATTACHED_FILES': {
      state.attachedFiles.forEach(f => {
        if (f.thumbUrl) URL.revokeObjectURL(f.thumbUrl);
      });
      return { ...state, attachedFiles: [] };
    }
    case 'SET_LAST_TOOL':
      return {
        ...state,
        lastToolName: action.name,
        lastToolInput: action.input ?? null,
        lastToolStartTime: action.startTime ?? 0,
      };
    case 'CHAT_STATE_SYNC': {
      const streamMap = new Map<string, StreamingSession>();
      for (const s of action.streamingSessions) {
        streamMap.set(s.id, s);
      }
      const unreadSet = new Set(action.unreadSessions);
      // Auto-mark current session as read
      const currentId = state.claudeSessionId;
      if (currentId && unreadSet.has(currentId)) {
        unreadSet.delete(currentId);
        api.chatStateRead(currentId).catch(() => {});
      }

      // Backend is GT - just take what it gives us
      const newActive = action.activeSessions;

      // Ensure all active/streaming sessions have entries in allSessions
      const existingIds = new Set(state.allSessions.map(s => s.id));
      const syntheticEntries: Session[] = [];

      for (const entry of newActive) {
        // Check both session_id and tab_id against existing entries
        const sid = entry.session_id || entry.tab_id;
        const alreadyExists = (entry.session_id && existingIds.has(entry.session_id))
          || (entry.tab_id && existingIds.has(entry.tab_id));
        if (sid && !alreadyExists && !existingIds.has(sid)) {
          const streaming = streamMap.get(sid);
          syntheticEntries.push({
            id: sid,
            date: new Date().toISOString(),
            preview: streaming ? '(streaming...)' : '(loading...)',
            messages: 0,
            is_active: true,
          });
          existingIds.add(sid);
        }
      }

      for (const [sid] of streamMap) {
        if (!existingIds.has(sid)) {
          syntheticEntries.push({
            id: sid,
            date: new Date().toISOString(),
            preview: '(streaming...)',
            messages: 0,
            is_active: true,
          });
          existingIds.add(sid);
        }
      }

      const newAllSessions = syntheticEntries.length > 0
        ? [...syntheticEntries, ...state.allSessions]
        : state.allSessions;

      return {
        ...state,
        allSessions: newAllSessions,
        activeSessions: newActive,
        sessionNames: action.sessionNames,
        streamingSessions: streamMap,
        unreadSessions: unreadSet,
        drafts: action.drafts ?? state.drafts,
      };
    }
    case 'SET_TODOS':
      return { ...state, todos: action.todos };
    case 'TOGGLE_TODOS_COLLAPSED':
      return { ...state, todosCollapsed: !state.todosCollapsed };
    // Two-entity chat architecture
    case 'HISTORY_SNAPSHOT':
      return { ...state, historyBlocks: action.blocks };
    case 'HISTORY_BLOCK_ADD': {
      if (state.historyBlocks.some(b => b.id === action.block.id)) return state;
      return { ...state, historyBlocks: [...state.historyBlocks, action.block] };
    }
    case 'REALTIME_SNAPSHOT':
      return { ...state, realtimeBlocks: action.blocks };
    case 'REALTIME_BLOCK_ADD': {
      if (state.realtimeBlocks.some(b => b.id === action.block.id)) return state;
      return { ...state, realtimeBlocks: [...state.realtimeBlocks, action.block] };
    }
    case 'REALTIME_BLOCK_UPDATE': {
      const idx = state.realtimeBlocks.findIndex(b => b.id === action.id);
      if (idx === -1) return state;
      const updated = { ...state.realtimeBlocks[idx], ...action.patch };
      const newBlocks = [...state.realtimeBlocks];
      newBlocks[idx] = updated;
      return { ...state, realtimeBlocks: newBlocks };
    }
    case 'REALTIME_RESET':
      return { ...state, realtimeBlocks: [], realtimeStatus: 'idle', streamStart: null };
    case 'SET_REALTIME_STATUS':
      return { ...state, realtimeStatus: action.status };
    case 'SET_MODEL': {
      const sid = state.claudeSessionId || state.tabId;
      if (sid) {
        // Active session: save per-session only, don't pollute global default
        try {
          const map = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
          map[sid] = { ...(map[sid] || {}), model: action.model };
          localStorage.setItem('chat_session_settings', JSON.stringify(map));
        } catch {}
      } else {
        // Welcome screen (no session): update global default
        localStorage.setItem('chat_model', action.model);
      }
      return { ...state, model: action.model };
    }
    case 'SET_EFFORT': {
      const sid = state.claudeSessionId || state.tabId;
      if (sid) {
        try {
          const map = JSON.parse(localStorage.getItem('chat_session_settings') || '{}');
          map[sid] = { ...(map[sid] || {}), effort: action.effort };
          localStorage.setItem('chat_session_settings', JSON.stringify(map));
        } catch {}
      } else {
        localStorage.setItem('chat_effort', action.effort);
      }
      return { ...state, effort: action.effort };
    }
    case 'SET_PENDING_PERMISSION':
      return { ...state, pendingPermission: action.permission };
    case 'SET_PENDING_COMMS':
      return { ...state, pendingComms: action.comms };
    case 'SET_PERMISSION_MODE':
      return { ...state, permissionMode: action.mode };
    case 'SET_SESSION_MODE':
      return { ...state, sessionMode: action.mode };
    case 'OPEN_ARTIFACT':
      return { ...state, activeArtifact: { filename: action.filename, path: action.path, title: action.title } };
    case 'CLOSE_ARTIFACT':
      return { ...state, activeArtifact: null };
    case 'ADD_ARTIFACT': {
      if (state.sessionArtifacts.some(a => a.filename === action.artifact.filename)) return state;
      return { ...state, sessionArtifacts: [...state.sessionArtifacts, action.artifact] };
    }
    case 'RESET_ARTIFACTS':
      return { ...state, activeArtifact: null, sessionArtifacts: [] };
    case 'SET_DRAFTS':
      return { ...state, drafts: action.drafts };
    case 'SET_DRAFT': {
      const newDrafts = { ...state.drafts };
      if (action.text) {
        newDrafts[action.sessionId] = action.text;
      } else {
        delete newDrafts[action.sessionId];
      }
      return { ...state, drafts: newDrafts };
    }
    default:
      return state;
  }
}

// --- Context ---

interface ChatContextValue {
  state: ChatState;
  dispatch: Dispatch<ChatAction>;
  socketRef: React.MutableRefObject<Socket | null>;
  messagesRef: React.MutableRefObject<HTMLDivElement | null>;
  streamingTextRef: React.MutableRefObject<HTMLDivElement | null>;
  sendMessageRef: React.MutableRefObject<((text: string) => void) | null>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChatContext must be used within ChatProvider');
  return ctx;
}

export const INITIAL_STATE: ChatState = {
  socketConnected: false,
  tabId: null,
  claudeSessionId: null,
  watching: false,
  allSessions: [],
  activeSessions: [],
  sessionNames: {},
  backendQueue: [],
  queueSessionId: null,
  sessionQueues: {},
  streamStart: 0,
  sidebarFilter: ((): SidebarFilter => {
    const stored = localStorage.getItem('chat_sidebar_filter');
    return (stored === 'active' || stored === 'all' || stored === 'human' || stored === 'cron') ? stored : 'all';
  })(),
  wasConnected: false,
  reconnectAttempts: 0,
  attachedFiles: [],
  lastToolName: null,
  lastToolInput: null,
  lastToolStartTime: 0,
  streamingSessions: new Map<string, StreamingSession>(),
  unreadSessions: new Set<string>(),
  todos: [],
  todosCollapsed: false,
  historyBlocks: [],
  realtimeBlocks: [],
  realtimeStatus: 'idle',
  model: localStorage.getItem('chat_model') || 'opus',
  effort: localStorage.getItem('chat_effort') || 'high',
  pendingPermission: null,
  pendingComms: null,
  permissionMode: 'ask',
  sessionMode: 'bypass',
  activeArtifact: null,
  sessionArtifacts: [],
  drafts: {},
};

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, INITIAL_STATE);

  const socketRef = useRef<Socket | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const streamingTextRef = useRef<HTMLDivElement | null>(null);
  const sendMessageRef = useRef<((text: string) => void) | null>(null);

  // Initialize Socket.IO connection once
  useEffect(() => {
    const socket = io('/chat', { upgrade: false });
    socketRef.current = socket;

    socket.on('connect', () => {
      console.log('[socket.io] connected, id:', socket.id, 'transport:', socket.io.engine.transport.name);
      dispatch({ type: 'SET_CONNECTED', connected: true });
      dispatch({ type: 'RESET_RECONNECT' });
    });

    socket.on('disconnect', (reason) => {
      console.log('[socket.io] disconnected, reason:', reason);
      dispatch({ type: 'SET_CONNECTED', connected: false });
      dispatch({ type: 'INC_RECONNECT' });
    });

    socket.on('connect_error', (err) => {
      console.error('[socket.io] connect_error:', err.message);
    });

    // Backend state sync - replaces localStorage
    socket.on('chat_state_sync', (data: { active_sessions?: ActiveEntry[]; session_names?: Record<string, string>; streaming_sessions?: StreamingSession[]; unread_sessions?: string[]; drafts?: Record<string, string> }) => {
      dispatch({
        type: 'CHAT_STATE_SYNC',
        activeSessions: data.active_sessions || [],
        sessionNames: data.session_names || {},
        streamingSessions: data.streaming_sessions || [],
        unreadSessions: data.unread_sessions || [],
        drafts: data.drafts,
      });
    });

    // Draft update from another device
    socket.on('draft_update', (data: { session_id: string; text: string }) => {
      dispatch({ type: 'SET_DRAFT', sessionId: data.session_id, text: data.text });
    });

    // Queue update from backend
    socket.on('queue_update', (data: { queue?: Array<{ text: string; index: number }>; tab_id?: string }) => {
      const queue = (data.queue as Array<{ text: string; index: number }>) || [];
      dispatch({ type: 'SET_BACKEND_QUEUE', queue, sessionId: data.tab_id || undefined });
    });

    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, []);

  const value: ChatContextValue = {
    state,
    dispatch,
    socketRef,
    messagesRef,
    streamingTextRef,
    sendMessageRef,
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
