import { useEffect, useRef, useCallback } from 'react';
import { useChatContext } from '@/context/ChatContext';

interface JsonRpcMessage {
  jsonrpc: '2.0';
  method?: string;
  params?: Record<string, unknown>;
  id?: number | string;
  result?: unknown;
  error?: { code: number; message: string };
}

function isJsonRpc(data: unknown): data is JsonRpcMessage {
  return typeof data === 'object' && data !== null && (data as JsonRpcMessage).jsonrpc === '2.0';
}

function getThemeCssVariables(): Record<string, string> {
  const root = getComputedStyle(document.documentElement);
  const vars: Record<string, string> = {};
  for (const name of [
    '--bg-base', '--bg-elevated', '--bg-surface',
    '--text-primary', '--text-secondary', '--text-muted',
    '--border', '--accent', '--radius',
  ]) {
    const val = root.getPropertyValue(name).trim();
    if (val) vars[name] = val;
  }
  return vars;
}

export function ArtifactViewer() {
  const { state, dispatch, socketRef, sendMessageRef } = useChatContext();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { activeArtifact } = state;
  const pendingToolCalls = useRef<Map<string, { iframeRpcId: number | string }>>(new Map());

  const sendToIframe = useCallback((msg: JsonRpcMessage) => {
    iframeRef.current?.contentWindow?.postMessage(msg, '*');
  }, []);

  useEffect(() => {
    if (!activeArtifact) return;

    const handleMessage = (e: MessageEvent) => {
      const d = e.data;
      if (!d || typeof d !== 'object') return;

      // MCP Apps JSON-RPC protocol
      if (isJsonRpc(d) && d.method) {
        handleJsonRpc(d);
        return;
      }

      // Legacy artifact bridge protocol
      if (d.type === 'artifact') {
        if (d.action === 'chat_message' && d.payload?.text) {
          sendMessageRef.current?.(d.payload.text);
        }
        if (d.action === 'ready') {
          console.log('[ArtifactViewer] Legacy artifact ready:', activeArtifact.filename);
        }
      }
    };

    const handleJsonRpc = (msg: JsonRpcMessage) => {
      const method = msg.method!;
      const id = msg.id;

      if (method === 'ui/initialize') {
        sendToIframe({
          jsonrpc: '2.0',
          id: id,
          result: {
            capabilities: { tools: true, messages: true, theme: true },
            theme: {
              mode: 'dark',
              cssVariables: getThemeCssVariables(),
            },
          },
        });
        return;
      }

      if (method === 'ui/requests/message') {
        const text = (msg.params as { text?: string })?.text;
        if (text) sendMessageRef.current?.(text);
        if (id !== undefined) {
          sendToIframe({ jsonrpc: '2.0', id, result: { success: true } });
        }
        return;
      }

      if (method === 'ui/requests/openLink') {
        const url = (msg.params as { url?: string })?.url;
        if (url) window.open(url, '_blank');
        if (id !== undefined) {
          sendToIframe({ jsonrpc: '2.0', id, result: { success: true } });
        }
        return;
      }

      if (method === 'ui/requests/setDisplayMode') {
        if (id !== undefined) {
          sendToIframe({ jsonrpc: '2.0', id, result: { success: true } });
        }
        return;
      }

      if (method === 'tools/call') {
        const params = msg.params as { name?: string; arguments?: Record<string, unknown> } | undefined;
        if (!params?.name) {
          if (id !== undefined) {
            sendToIframe({ jsonrpc: '2.0', id, error: { code: -32602, message: 'Missing tool name' } });
          }
          return;
        }

        const callId = `art_${Date.now()}_${id}`;
        if (id !== undefined) {
          pendingToolCalls.current.set(callId, { iframeRpcId: id });
        }

        socketRef.current?.emit('artifact_tool_call', {
          call_id: callId,
          tool_name: params.name,
          tool_input: params.arguments || {},
          tab_id: state.tabId,
        });
        return;
      }

      if (id !== undefined) {
        sendToIframe({
          jsonrpc: '2.0', id,
          error: { code: -32601, message: `Unknown method: ${method}` },
        });
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [activeArtifact, sendMessageRef, sendToIframe, socketRef, state.tabId]);

  // Listen for tool call results from backend
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket || !activeArtifact) return;

    const onToolResult = (data: { call_id: string; result?: unknown; error?: string }) => {
      const pending = pendingToolCalls.current.get(data.call_id);
      if (!pending) return;
      pendingToolCalls.current.delete(data.call_id);

      if (data.error) {
        sendToIframe({
          jsonrpc: '2.0',
          id: pending.iframeRpcId,
          error: { code: -32000, message: data.error },
        });
      } else {
        sendToIframe({
          jsonrpc: '2.0',
          id: pending.iframeRpcId,
          result: data.result,
        });
      }
    };

    const onArtifactUpdated = (data: { filename: string }) => {
      if (data.filename === activeArtifact.filename && iframeRef.current) {
        iframeRef.current.src = iframeRef.current.src;
      }
    };

    socket.on('artifact_tool_result', onToolResult);
    socket.on('artifact_updated', onArtifactUpdated);
    return () => {
      socket.off('artifact_tool_result', onToolResult);
      socket.off('artifact_updated', onArtifactUpdated);
    };
  }, [socketRef, activeArtifact, sendToIframe]);

  const handleClose = useCallback(() => {
    sendToIframe({ jsonrpc: '2.0', method: 'ui/notifications/requestTeardown' });
    dispatch({ type: 'CLOSE_ARTIFACT' });
  }, [dispatch, sendToIframe]);

  const handleOpenExternal = useCallback(() => {
    if (!activeArtifact) return;
    if (activeArtifact.path) {
      window.open(`/api/markdown/render?path=${encodeURIComponent(activeArtifact.path)}`, '_blank');
    } else if (activeArtifact.filename) {
      window.open(`/api/views/serve/${activeArtifact.filename}`, '_blank');
    }
  }, [activeArtifact]);

  if (!activeArtifact) return null;

  const iframeSrc = activeArtifact.path
    ? `/api/markdown/render?path=${encodeURIComponent(activeArtifact.path)}`
    : `/api/views/serve/${activeArtifact.filename}`;

  return (
    <div className="artifact-viewer">
      <div className="artifact-toolbar">
        <button className="artifact-toolbar-btn artifact-toolbar-back" onClick={handleClose} title="Back to chat">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back
        </button>
        <span className="artifact-toolbar-title">{activeArtifact.title}</span>
        <button className="artifact-toolbar-btn" onClick={handleOpenExternal} title="Open in new tab">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M6 2H3a1 1 0 00-1 1v8a1 1 0 001 1h8a1 1 0 001-1V8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <path d="M8 2h4v4M7 7l5-5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      <iframe
        ref={iframeRef}
        className="artifact-iframe"
        src={iframeSrc}
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-modals"
        title={activeArtifact.title}
      />
    </div>
  );
}
