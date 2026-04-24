import { useState, useMemo } from 'react';
import type { Block } from '@/context/ChatContext';
import { getToolConfig, getToolSummary, formatToolInput } from '../toolRegistry';

interface ToolRunBlockProps {
  blocks: Block[];
  isStreaming: boolean;
}

type ToolItem = { use: Block; result?: Block };

function buildToolItems(blocks: Block[]): ToolItem[] {
  const items: ToolItem[] = [];
  for (const b of blocks) {
    if (b.type === 'tool_use') {
      items.push({ use: b });
    } else if (b.type === 'tool_result') {
      // Attach to previous item
      if (items.length > 0 && !items[items.length - 1].result) {
        items[items.length - 1].result = b;
      }
    } else if (b.type === 'tool_group' && b.tools) {
      // Expand sub-items the same way
      for (const t of b.tools) {
        if (t.type === 'tool_use') {
          items.push({ use: t });
        } else if (t.type === 'tool_result') {
          if (items.length > 0 && !items[items.length - 1].result) {
            items[items.length - 1].result = t;
          }
        }
      }
    }
  }
  return items;
}

function getResultPreview(item: ToolItem): string {
  if (!item.result) return '';
  const content = item.result.content || item.result.text || '';
  if (!content) return '';
  // First line, truncated
  const first = content.split('\n')[0] || '';
  return first.length > 120 ? first.substring(0, 120) + '...' : first;
}

function formatDuration(ms?: number): string {
  if (!ms) return '';
  return ms > 1000 ? (ms / 1000).toFixed(1) + 's' : ms + 'ms';
}

const TOOL_VERBS: Record<string, [string, string]> = {
  Read: ['read %n file', 'read %n files'],
  Grep: ['searched %n pattern', 'searched %n patterns'],
  Edit: ['edited %n file', 'edited %n files'],
  Write: ['wrote %n file', 'wrote %n files'],
  Bash: ['ran %n command', 'ran %n commands'],
  Glob: ['found %n pattern', 'found %n patterns'],
  WebSearch: ['searched %n query', 'searched %n queries'],
  WebFetch: ['fetched %n page', 'fetched %n pages'],
  Task: ['ran %n task', 'ran %n tasks'],
};

function describeTools(counts: Record<string, number>): string {
  const parts: string[] = [];
  for (const [name, count] of Object.entries(counts)) {
    const verbs = TOOL_VERBS[name];
    if (verbs) {
      const template = count === 1 ? verbs[0] : verbs[1];
      parts.push(template.replace('%n', String(count)));
    } else {
      parts.push(count === 1 ? `used ${name}` : `used ${name} ${count} times`);
    }
  }
  return parts.join(', ');
}

function ToolItemRow({ item }: { item: ToolItem }) {
  const toolName = item.use.tool || 'Unknown';
  const config = getToolConfig(toolName);
  const summary = getToolSummary(toolName, item.use.input);
  const duration = formatDuration(item.use.duration_ms);
  const preview = getResultPreview(item);
  const isRunning = item.use.running;

  const inputHtml = useMemo(() => formatToolInput(toolName, item.use.input), [toolName, item.use.input]);

  return (
    <div className="chat-tool-run-item">
      <div className="chat-tool-run-item-header">
        <span
          className="chat-tool-run-item-icon"
          dangerouslySetInnerHTML={{ __html: isRunning ? '<span class="tool-spinner"></span>' : config.icon }}
        />
        <span className="chat-tool-run-item-name">{toolName}</span>
        <span className="chat-tool-run-item-summary">{summary}</span>
        <span className="chat-tool-run-item-meta">{duration}</span>
      </div>
      {inputHtml && (
        <div className="chat-tool-run-item-detail" dangerouslySetInnerHTML={{ __html: inputHtml }} />
      )}
      {preview && (
        <div className="chat-tool-run-item-result-preview">{preview}</div>
      )}
    </div>
  );
}

export function ToolRunBlock({ blocks, isStreaming: _isStreaming }: ToolRunBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const items = useMemo(() => buildToolItems(blocks), [blocks]);

  const summary = useMemo(() => {
    const counts: Record<string, number> = {};
    let totalDuration = 0;

    for (const item of items) {
      const name = item.use.tool || 'Unknown';
      counts[name] = (counts[name] || 0) + 1;
      if (item.use.duration_ms) totalDuration += item.use.duration_ms;
    }

    const description = describeTools(counts);

    let durationStr = '';
    if (totalDuration > 0) {
      durationStr = totalDuration > 1000
        ? (totalDuration / 1000).toFixed(1) + 's'
        : totalDuration + 'ms';
    }

    return { description, durationStr, hasParts: Object.keys(counts).length > 0 };
  }, [items]);

  if (!summary.hasParts) return null;

  return (
    <div className={`chat-tool-run${expanded ? ' expanded' : ''}`}>
      <div
        className="chat-tool-run-header"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="chat-tool-run-arrow">&#9654;</span>
        <span className="chat-tool-run-desc">{summary.description}</span>
        {summary.durationStr && (
          <span className="chat-tool-run-duration">{summary.durationStr}</span>
        )}
      </div>
      {expanded && (
        <div className="chat-tool-run-body">
          {items.map((item, idx) => (
            <div key={`ti-${item.use.id}`}>
              {idx > 0 && <div className="chat-tool-run-sep" />}
              <ToolItemRow item={item} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
