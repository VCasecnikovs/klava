import { useState } from 'react';
import { esc } from '@/lib/utils';
import type { Block } from '@/context/ChatContext';
import { renderChatMD } from '../ChatMarkdown';

function decodeEscapedReasoningText(text: string): string {
  return text
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t')
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, '\\');
}

function extractQuotedTextValue(raw: string): string | null {
  const key = /['"]text['"]\s*:\s*/.exec(raw);
  if (!key) return null;
  const quoteIndex = key.index + key[0].length;
  const quote = raw[quoteIndex];
  if (quote !== '"' && quote !== "'") return null;

  let value = '';
  for (let i = quoteIndex + 1; i < raw.length; i++) {
    const char = raw[i];
    if (char === '\\' && i + 1 < raw.length) {
      value += char + raw[i + 1];
      i++;
      continue;
    }
    if (char === quote) return decodeEscapedReasoningText(value).trim();
    value += char;
  }
  return null;
}

function reasoningValueToText(value: unknown): string {
  if (typeof value === 'string') return normalizeThinkingText(value);
  if (Array.isArray(value)) {
    return value.map(reasoningValueToText).filter(Boolean).join('\n\n');
  }
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    if (typeof obj.text === 'string') return normalizeThinkingText(obj.text);
    if (typeof obj.content === 'string') return normalizeThinkingText(obj.content);
    if (Array.isArray(obj.summary)) return reasoningValueToText(obj.summary);
    if (Array.isArray(obj.content)) return reasoningValueToText(obj.content);
  }
  return '';
}

export function normalizeThinkingText(text: string | null | undefined): string {
  const raw = (text || '').trim();
  if (!raw) return '';

  try {
    const parsed = JSON.parse(raw);
    const parsedText = reasoningValueToText(parsed);
    if (parsedText) return parsedText;
  } catch { /* native Codex rollout can contain Python-style object repr */ }

  if ((raw.startsWith('{') || raw.startsWith('[')) && /['"]text['"]\s*:/.test(raw)) {
    const extracted = extractQuotedTextValue(raw);
    if (extracted) return extracted;
  }

  return decodeEscapedReasoningText(raw);
}

export function thinkingPreview(text: string, fallback = ''): string {
  const source = normalizeThinkingText(fallback) || normalizeThinkingText(text);
  const firstLine = source.split('\n').find(line => line.trim())?.trim() || '';
  return firstLine.length > 80 ? `${firstLine.substring(0, 80)}...` : firstLine;
}

export function ThinkingBlock({ block }: { block: Block }) {
  const [expanded, setExpanded] = useState(false);
  const text = normalizeThinkingText(block.text);
  const words = block.words || (text ? text.split(/\s+/).filter(Boolean).length : 0);
  const preview = thinkingPreview(text, block.preview);

  return (
    <div className={`chat-thinking${expanded ? ' expanded' : ''}`}>
      <div
        className="chat-thinking-header"
        onClick={() => setExpanded(e => !e)}
        dangerouslySetInnerHTML={{
          __html: `<span class="chat-thinking-arrow">&#9654;</span>Thinking<span class="chat-thinking-meta">${words} words</span><span class="chat-thinking-preview">${esc(preview)}${preview.length >= 60 ? '...' : ''}</span>`
        }}
      />
      <div
        className="chat-thinking-content"
        style={{ display: expanded ? 'block' : 'none' }}
        dangerouslySetInnerHTML={{ __html: renderChatMD(text) }}
      />
    </div>
  );
}
