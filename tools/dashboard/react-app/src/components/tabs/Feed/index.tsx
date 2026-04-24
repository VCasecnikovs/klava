import { useState, useCallback, useEffect, useRef } from 'react';
import { useFeed } from '@/api/queries';
import { FilterBar } from '@/components/shared/FilterBar';
import { showToast } from '@/components/shared/Toast';
import { renderChatMD } from '@/components/tabs/Chat/ChatMarkdown';
import type { FeedMessage, FeedDelta } from '@/api/types';

/** Resolve effective topic: for legacy messages, use job_id to reclassify */
const JOB_TOPIC_OVERRIDE: Record<string, string> = {
  reflection: 'Reflection',
  'task-consumer': 'Tasks',
  heartbeat: 'Heartbeat',
  'heartbeat-manual': 'Heartbeat',
};

function normalizeTopic(t: string | null | undefined): string {
  if (!t) return 'General';
  if (t.toLowerCase() === 'heartbeat') return 'Heartbeat';
  return t;
}

function effectiveTopic(msg: FeedMessage): string {
  const topic = normalizeTopic(msg.topic);
  // Reflection runs through heartbeat scheduler - keep existing override.
  if (msg.job_id && topic === 'Heartbeat' && msg.job_id in JOB_TOPIC_OVERRIDE && msg.job_id !== 'heartbeat') {
    return JOB_TOPIC_OVERRIDE[msg.job_id];
  }
  // Anything from a heartbeat job should be labeled Heartbeat, not General.
  if (msg.job_id && JOB_TOPIC_OVERRIDE[msg.job_id]) {
    return JOB_TOPIC_OVERRIDE[msg.job_id];
  }
  return topic;
}

const FEED_LAST_READ_KEY = 'feed-last-read-ts';

function openSession(sessionId: string) {
  window.dispatchEvent(new CustomEvent('chat:resume-session', { detail: { sessionId } }));
}

/** Known topic color overrides. Unknown topics get auto-generated colors via hash. */
const TOPIC_COLOR_OVERRIDES: Record<string, { bg: string; color: string; stripe: string }> = {
  Heartbeat: { bg: 'rgba(96,165,250,0.10)', color: 'var(--blue)', stripe: 'var(--blue)' },
  Reflection: { bg: 'rgba(139,92,246,0.10)', color: '#8b5cf6', stripe: '#8b5cf6' },
  Alerts: { bg: 'rgba(239,68,68,0.10)', color: '#ef4444', stripe: '#ef4444' },
  Tasks: { bg: 'rgba(52,211,153,0.10)', color: '#34d399', stripe: '#34d399' },
  Main: { bg: 'rgba(52,211,153,0.08)', color: 'var(--green)', stripe: 'var(--green)' },
};

/** Generate a deterministic HSL color from a string for unknown topics. */
function hashTopicColor(name: string): { bg: string; color: string; stripe: string } {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  const color = `hsl(${hue}, 55%, 60%)`;
  return { bg: `hsla(${hue}, 55%, 60%, 0.10)`, color, stripe: color };
}

function topicColor(name: string): { bg: string; color: string; stripe: string } {
  return TOPIC_COLOR_OVERRIDES[name] || hashTopicColor(name);
}

/** Delta type -> icon + color */
const DELTA_STYLE: Record<string, { icon: string; color: string }> = {
  obsidian: { icon: '📝', color: '#a78bfa' },
  gtask: { icon: '✅', color: '#34d399' },
  gmail: { icon: '📧', color: '#f87171' },
  calendar: { icon: '📅', color: '#fbbf24' },
  deal: { icon: '💰', color: '#f59e0b' },
  dispatched: { icon: '🔍', color: '#60a5fa' },
  observation: { icon: '👁', color: '#c084fc' },
  inbox: { icon: '📥', color: '#a78bfa' },
  skipped: { icon: '⏭', color: 'var(--text-muted)' },
};

function getDeltaStyle(type: string): { icon: string; color: string } {
  for (const [key, style] of Object.entries(DELTA_STYLE)) {
    if (type.includes(key)) return style;
  }
  return { icon: '•', color: 'var(--text-secondary)' };
}

const CATEGORY_LABELS: Record<string, { label: string; icon: string }> = {
  deal: { label: 'Deals', icon: '💰' },
  reply: { label: 'Replies', icon: '✅' },
  knowledge: { label: 'Knowledge', icon: '📝' },
  personal: { label: 'Personal', icon: '👤' },
  tech: { label: 'Tech', icon: '🔧' },
  ops: { label: 'Ops', icon: '⚙' },
};

const TRAJECTORY_STYLE: Record<string, { color: string; bg: string }> = {
  escalating: { color: '#f87171', bg: 'rgba(248,113,113,0.15)' },
  new: { color: '#60a5fa', bg: 'rgba(96,165,250,0.15)' },
  stable: { color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.06)' },
  declining: { color: '#34d399', bg: 'rgba(52,211,153,0.15)' },
  resolved: { color: '#a3a3a3', bg: 'rgba(255,255,255,0.04)' },
};

function getDeltaLabel(d: FeedDelta): { main: string; sub?: string } {
  if (d.type === 'skipped') {
    const src = d.source?.replace(/^(telegram|signal)\//, '') || '?';
    const hint = d.hint || d.reason || '';
    const countStr = d.count && d.count > 1 ? ` x${d.count}` : '';
    return { main: `${src}${countStr}`, sub: hint };
  }

  // Primary: summary > constructed fallback
  const main = d.summary
    || [d.deal_name || d.label || d.title || d.subject || d.path || d.target || d.key, d.change || d.reason]
        .filter(Boolean).join(' - ')
    || d.type;

  // Secondary line depends on delta type
  const subParts: string[] = [];
  if (d.stage) subParts.push(`Stage: ${d.stage}`);
  if (d.next_action) subParts.push(`Next: ${d.next_action}`);
  if (d.facts && d.facts.length > 0) subParts.push(d.facts.join(', '));
  if (d.expected) subParts.push(`→ ${d.expected}`);
  if (d.lens && d.tag) subParts.push(`${d.lens}/${d.tag}`);
  else if (d.lens) subParts.push(d.lens);

  return { main, sub: subParts.length > 0 ? subParts.join(' | ') : undefined };
}

function groupByCategory(deltas: FeedDelta[]): Map<string, FeedDelta[]> {
  const groups = new Map<string, FeedDelta[]>();
  for (const d of deltas) {
    const cat = d.category || 'other';
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat)!.push(d);
  }
  return groups;
}

/**
 * Parse legacy ---DELTAS--- from message text.
 * Returns [cleanText, parsedDeltas | null].
 */
function extractLegacyDeltas(text: string): [string, FeedDelta[] | null] {
  const idx = text.indexOf('---DELTAS---');
  if (idx < 0) return [text, null];
  const clean = text.slice(0, idx).trimEnd();
  try {
    const parsed = JSON.parse(text.slice(idx + 12).trim());
    return [clean, Array.isArray(parsed) ? parsed : null];
  } catch {
    return [clean, null];
  }
}

/** Strip trailing ```json ... ``` blocks (delta data already shown in DeltasPanel) */
function stripJsonCodeBlocks(text: string): string {
  return text.replace(/\n*```json\s*\n[\s\S]*?```\s*$/g, '').trimEnd();
}

/** Strip wrapping code fences that models add around output (```\n...\n```) */
function stripCodeFenceWrap(text: string): string {
  const t = text.trim();
  if (!t.startsWith('```')) return text;
  const firstNl = t.indexOf('\n');
  if (firstNl < 0) return text;
  if (t.endsWith('```')) {
    return t.slice(firstNl + 1, t.lastIndexOf('```')).trim();
  }
  // Opening fence without closing - strip the opening line
  return t.slice(firstNl + 1).trim();
}

function DeltaItem({ delta: d }: { delta: FeedDelta }) {
  const style = getDeltaStyle(d.type);
  const label = getDeltaLabel(d);
  return (
    <div className="feed-delta-item" style={{ borderLeftColor: style.color }}>
      <div className="feed-delta-content">
        <div className="feed-delta-main">
          <span className="feed-delta-icon">{style.icon}</span>
          <span className="feed-delta-text">{label.main}</span>
          {d.trigger && <span className="feed-delta-trigger" title={d.trigger}>← {d.trigger}</span>}
        </div>
        {label.sub && (
          <div className="feed-delta-sub">
            {label.sub}
            {d.trajectory && (
              <span
                className="feed-delta-badge"
                style={{
                  color: TRAJECTORY_STYLE[d.trajectory]?.color || 'var(--text-muted)',
                  background: TRAJECTORY_STYLE[d.trajectory]?.bg || 'rgba(255,255,255,0.06)',
                }}
              >
                {d.trajectory}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function NoiseSection({ skipped, totalSkipped }: { skipped: FeedDelta[]; totalSkipped: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="feed-deltas-skipped">
      <span
        className="feed-deltas-label feed-deltas-label--clickable"
        onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
      >
        Noise ({totalSkipped}) {expanded ? '▾' : '▸'}
      </span>
      {expanded ? (
        <div className="feed-deltas-list">
          {skipped.map((d, i) => {
            const src = d.source?.replace(/^(telegram|signal)\//, '') || '?';
            const cnt = d.count && d.count > 1 ? ` x${d.count}` : '';
            return (
              <div key={i} className="feed-delta-item feed-delta-item--noise" style={{ borderLeftColor: 'var(--text-muted)' }}>
                <div className="feed-delta-content">
                  <div className="feed-delta-main">
                    <span className="feed-delta-icon">⏭</span>
                    <span className="feed-delta-text" style={{ color: 'var(--text-muted)' }}>
                      <strong>{src}{cnt}</strong>
                      {d.hint && <> - {d.hint}</>}
                    </span>
                  </div>
                  {d.reason && d.reason !== d.hint && (
                    <div className="feed-delta-sub">{d.reason}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="feed-deltas-skip-list">
          {skipped.map((d, i) => {
            const label = getDeltaLabel(d);
            return (
              <span key={i} className="feed-delta-skip-pill" title={label.sub || label.main}>
                {label.main}{label.sub ? `: ${label.sub}` : ''}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function DeltasPanel({ deltas }: { deltas: FeedDelta[] }) {
  const actions = deltas.filter(d => d.type !== 'skipped');
  const skipped = deltas.filter(d => d.type === 'skipped');
  const totalSkipped = skipped.reduce((sum, d) => sum + (d.count || 1), 0);

  if (actions.length === 0 && skipped.length === 0) return null;

  const hasCategories = actions.some(d => d.category);
  const grouped = hasCategories ? groupByCategory(actions) : null;

  return (
    <div className="feed-deltas">
      {grouped ? (
        Array.from(grouped.entries()).map(([cat, items]) => {
          const catInfo = CATEGORY_LABELS[cat] || { label: cat, icon: '•' };
          return (
            <div key={cat} className="feed-deltas-section">
              <span className="feed-deltas-label">{catInfo.icon} {catInfo.label} ({items.length})</span>
              <div className="feed-deltas-list">
                {items.map((d, i) => <DeltaItem key={i} delta={d} />)}
              </div>
            </div>
          );
        })
      ) : (
        actions.length > 0 && (
          <div className="feed-deltas-section">
            <span className="feed-deltas-label">Changes ({actions.length})</span>
            <div className="feed-deltas-list">
              {actions.map((d, i) => <DeltaItem key={i} delta={d} />)}
            </div>
          </div>
        )
      )}
      {skipped.length > 0 && (
        <NoiseSection skipped={skipped} totalSkipped={totalSkipped} />
      )}
    </div>
  );
}

function MessageCard({ msg, compact }: { msg: FeedMessage; compact?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const topic = effectiveTopic(msg);
  const tc = topicColor(topic);
  const ts = new Date(msg.timestamp);
  const time = ts.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

  // Get deltas from structured field or parse from legacy message text
  const [textPart, legacyDeltas] = extractLegacyDeltas(msg.message);
  const deltas = msg.deltas || legacyDeltas;
  const rawText = msg.deltas ? msg.message : textPart;
  const messageText = stripCodeFenceWrap(stripJsonCodeBlocks(rawText));

  const truncLen = compact ? 200 : 400;
  const needsTrunc = messageText.length > truncLen && !expanded;
  const displayMsg = needsTrunc ? messageText.slice(0, truncLen) + '...' : messageText;
  const renderedHtml = renderChatMD(displayMsg);

  return (
    <div
      className={`feed-msg ${expanded ? 'feed-msg--expanded' : ''}`}
      style={{ borderLeftColor: tc.stripe, background: tc.bg }}
      onClick={() => needsTrunc || expanded ? setExpanded(!expanded) : undefined}
    >
      <div className="feed-msg-header">
        <span className="feed-msg-topic" style={{ color: tc.color }}>
          {topic}
        </span>
        <span className="feed-msg-time">{time}</span>
        {needsTrunc && (
          <span className="feed-msg-expand">&#9662;</span>
        )}
        {expanded && messageText.length > truncLen && (
          <span className="feed-msg-expand feed-msg-expand--up">&#9652;</span>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          {msg.ago && <span className="feed-msg-ago">{msg.ago}</span>}
          {msg.session_id && (
            <button
              className="feed-msg-open"
              title="Open session"
              onClick={(e) => { e.stopPropagation(); openSession(msg.session_id!); }}
            >
              Open &#8599;
            </button>
          )}
        </span>
      </div>
      <div className="feed-msg-body" dangerouslySetInnerHTML={{ __html: renderedHtml }} />
      {deltas && deltas.length > 0 && <DeltasPanel deltas={deltas} />}
    </div>
  );
}

function DateSeparator({ label }: { label: string }) {
  return (
    <div className="feed-date-sep">
      <span>{label}</span>
    </div>
  );
}

function getDateLabel(ts: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const msgDay = new Date(ts.getFullYear(), ts.getMonth(), ts.getDate());
  const diff = (today.getTime() - msgDay.getTime()) / 86400000;
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  return ts.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
}

/** Dispatch custom event with total unread count for tab badge in App.tsx */
function dispatchUnreadCount(count: number) {
  window.dispatchEvent(new CustomEvent('feed:unread', { detail: { count } }));
}

/** Collect all unique lenses from feed messages' deltas */
function collectLenses(messages: FeedMessage[]): string[] {
  const set = new Set<string>();
  for (const m of messages) {
    if (!m.deltas) continue;
    for (const d of m.deltas) {
      if (d.lens) set.add(d.lens);
    }
  }
  return [...set].sort();
}

/** Check if a message has any delta matching the given lens */
function messageHasLens(msg: FeedMessage, lens: string): boolean {
  if (!msg.deltas) return false;
  return msg.deltas.some(d => d.lens === lens);
}

export function FeedTab() {
  const { data, isLoading, error, refetch } = useFeed(true);
  const [topicFilter, setTopicFilter] = useState('all');
  const [lensFilter, setLensFilter] = useState('all');
  const handleRefresh = useCallback(() => { refetch(); showToast('Refreshing...'); }, [refetch]);
  const hasDispatchedRef = useRef(false);

  // Unread tracking: compute unread counts based on localStorage timestamp
  const lastReadTs = useRef<string | null>(null);
  const [unreadByTopic, setUnreadByTopic] = useState<Record<string, number>>({});
  const [totalUnread, setTotalUnread] = useState(0);

  // Read last-read timestamp from localStorage on mount
  useEffect(() => {
    try {
      lastReadTs.current = localStorage.getItem(FEED_LAST_READ_KEY);
    } catch { /* ignore */ }
  }, []);

  // Compute unread counts whenever data changes
  useEffect(() => {
    if (!data || data.messages.length === 0) {
      if (!hasDispatchedRef.current) {
        dispatchUnreadCount(0);
        hasDispatchedRef.current = true;
      }
      return;
    }

    const lastRead = lastReadTs.current;
    let total = 0;
    const byTopic: Record<string, number> = {};

    for (const msg of data.messages) {
      if (!lastRead || msg.timestamp > lastRead) {
        total++;
        const t = effectiveTopic(msg);
        byTopic[t] = (byTopic[t] || 0) + 1;
      }
    }

    setUnreadByTopic(byTopic);
    setTotalUnread(total);
    dispatchUnreadCount(total);
    hasDispatchedRef.current = true;
  }, [data]);

  // When feed tab is visible, mark all as read (update timestamp to newest message)
  useEffect(() => {
    if (!data || data.messages.length === 0) return;

    // The messages are sorted newest-first, so first message has the latest timestamp
    const newestTs = data.messages[0].timestamp;
    try {
      localStorage.setItem(FEED_LAST_READ_KEY, newestTs);
      lastReadTs.current = newestTs;
    } catch { /* ignore */ }

    // After marking as read, reset unread counts
    setUnreadByTopic({});
    setTotalUnread(0);
    dispatchUnreadCount(0);
  }, [data]);

  if (isLoading) return <div style={{ padding: 24, color: 'var(--text-muted)' }}>Loading feed...</div>;
  if (error) return <div className="error-banner">Feed error: {String(error)}</div>;
  if (!data || data.messages.length === 0) {
    return <div style={{ padding: 24, color: 'var(--text-muted)' }}>No messages yet. Feed will populate as proactive messages are sent.</div>;
  }

  // Build topics from effective topic names (reclassified)
  const topicSet = new Set<string>();
  for (const m of data.messages) topicSet.add(effectiveTopic(m));
  const topics = [...topicSet].sort();

  const filters = [
    { value: 'all', label: `All (${data.total})` },
    ...topics.map(t => {
      const unread = unreadByTopic[t];
      return {
        value: t,
        label: unread ? `${t} (${unread})` : t,
      };
    }),
  ];

  // Collect lenses from all messages for the lens filter row
  const lenses = collectLenses(data.messages);
  const lensFilters = lenses.length > 0 ? [
    { value: 'all', label: 'All lenses' },
    ...lenses.map(l => ({ value: l, label: l })),
  ] : [];

  // Apply both topic and lens filters
  let messages = data.messages;
  if (topicFilter !== 'all') messages = messages.filter(m => effectiveTopic(m) === topicFilter);
  if (lensFilter !== 'all') messages = messages.filter(m => messageHasLens(m, lensFilter));

  // Group messages by date
  let lastDateLabel = '';
  const items: { type: 'date' | 'msg'; label?: string; msg?: FeedMessage }[] = [];
  for (const msg of messages) {
    const label = getDateLabel(new Date(msg.timestamp));
    if (label !== lastDateLabel) {
      items.push({ type: 'date', label });
      lastDateLabel = label;
    }
    items.push({ type: 'msg', msg });
  }

  return (
    <div style={{ padding: '0 24px 24px' }}>
      <FilterBar
        filters={filters}
        active={topicFilter}
        onChange={setTopicFilter}
        onRefresh={handleRefresh}
        style={{ marginBottom: lensFilters.length > 0 ? 8 : 16 }}
      />
      {lensFilters.length > 0 && (
        <FilterBar
          filters={lensFilters}
          active={lensFilter}
          onChange={setLensFilter}
          style={{ marginBottom: 16, opacity: 0.85, fontSize: '0.85em' }}
        />
      )}
      <div className="feed-list">
        {items.map((item, i) =>
          item.type === 'date' ? (
            <DateSeparator key={`date-${item.label}`} label={item.label!} />
          ) : (
            <MessageCard key={`${item.msg!.timestamp}-${i}`} msg={item.msg!} />
          )
        )}
      </div>
    </div>
  );
}
