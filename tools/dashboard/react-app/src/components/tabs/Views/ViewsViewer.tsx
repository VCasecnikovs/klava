import { useEffect, useRef, useCallback } from 'react';
import { esc } from '@/lib/utils';
import { api } from '@/api/client';
import { showToast } from '@/components/shared/Toast';
import { io, type Socket } from 'socket.io-client';

interface Props {
  filename?: string;
  url?: string;
  title: string;
  onBack: () => void;
}

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

function getThemeVars(): Record<string, string> {
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

export function ViewsViewer({ filename, url, title, onBack }: Props) {
  const iframeSrc = url || '/api/views/serve/' + encodeURIComponent(filename || '');
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const socketRef = useRef<Socket | null>(null);
  const pendingCalls = useRef<Map<string, number | string>>(new Map());

  const sendToIframe = useCallback((msg: JsonRpcMessage) => {
    iframeRef.current?.contentWindow?.postMessage(msg, '*');
  }, []);

  useEffect(() => {
    const socket = io('/chat', { upgrade: false });
    socketRef.current = socket;

    socket.on('artifact_tool_result', (data: { call_id: string; result?: unknown; error?: string }) => {
      const rpcId = pendingCalls.current.get(data.call_id);
      if (rpcId === undefined) return;
      pendingCalls.current.delete(data.call_id);

      if (data.error) {
        sendToIframe({ jsonrpc: '2.0', id: rpcId, error: { code: -32000, message: data.error } });
      } else {
        sendToIframe({ jsonrpc: '2.0', id: rpcId, result: data.result });
      }
    });

    return () => { socket.disconnect(); socketRef.current = null; };
  }, [sendToIframe]);

  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      const d = e.data;
      if (!d || typeof d !== 'object') return;

      if (isJsonRpc(d) && d.method) {
        const method = d.method;
        const id = d.id;

        if (method === 'ui/initialize') {
          sendToIframe({
            jsonrpc: '2.0', id,
            result: {
              capabilities: { tools: true, messages: true, theme: true },
              theme: { mode: 'dark', cssVariables: getThemeVars() },
            },
          });
          return;
        }

        if (method === 'ui/requests/message') {
          const text = (d.params as { text?: string })?.text;
          if (text) {
            window.dispatchEvent(new CustomEvent('chat:send-message', { detail: { text } }));
          }
          if (id !== undefined) sendToIframe({ jsonrpc: '2.0', id, result: { success: true } });
          return;
        }

        if (method === 'ui/requests/openLink') {
          const linkUrl = (d.params as { url?: string })?.url;
          if (linkUrl) window.open(linkUrl, '_blank');
          if (id !== undefined) sendToIframe({ jsonrpc: '2.0', id, result: { success: true } });
          return;
        }

        if (method === 'tools/call') {
          const params = d.params as { name?: string; arguments?: Record<string, unknown> } | undefined;
          if (!params?.name) {
            if (id !== undefined) {
              sendToIframe({ jsonrpc: '2.0', id, error: { code: -32602, message: 'Missing tool name' } });
            }
            return;
          }
          const callId = `vv_${Date.now()}_${id}`;
          if (id !== undefined) pendingCalls.current.set(callId, id);

          socketRef.current?.emit('artifact_tool_call', {
            call_id: callId,
            tool_name: params.name,
            tool_input: params.arguments || {},
          });
          return;
        }

        if (id !== undefined) {
          sendToIframe({ jsonrpc: '2.0', id, error: { code: -32601, message: `Unknown method: ${method}` } });
        }
        return;
      }

      // Legacy artifact bridge
      if (d.type === 'artifact') {
        if (d.action === 'chat_message' && d.payload?.text) {
          window.dispatchEvent(new CustomEvent('chat:send-message', { detail: { text: d.payload.text } }));
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [sendToIframe]);

  const handleOpenExternal = () => {
    if (filename) {
      api.openView(filename, true).then(r => {
        if (r) showToast('Opened in browser');
      }).catch(() => showToast('Failed to open'));
    } else if (url) {
      window.open(url, '_blank');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <button
          onClick={onBack}
          style={{
            background: 'var(--bg-elevated)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-xs)',
            padding: '4px 12px', cursor: 'pointer', fontSize: 13,
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          <span style={{ fontSize: 16 }}>&larr;</span> Back
        </button>
        <span style={{ color: 'var(--text-secondary)', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {esc(title || filename)}
        </span>
        <button
          onClick={handleOpenExternal}
          style={{
            background: 'none', color: 'var(--text-muted)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-xs)',
            padding: '4px 10px', cursor: 'pointer', fontSize: 11, marginLeft: 'auto',
          }}
        >
          Open in new tab
        </button>
      </div>
      <iframe
        ref={iframeRef}
        src={iframeSrc}
        style={{
          width: '100%', height: 'calc(100vh - 120px)',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          background: '#fff',
        }}
        sandbox="allow-scripts allow-same-origin allow-popups allow-modals"
      />
    </div>
  );
}
