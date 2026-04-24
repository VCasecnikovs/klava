import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { useDeckCards, type DeckCard } from '@/api/queries';
import { api, type KlavaTask } from '@/api/client';
import { extractHashtags } from '@/lib/hashtags';
import { renderChatMD } from '@/components/tabs/Chat/ChatMarkdown';

// ─── Shape palette + tag inference ───────────────────────────────

const SHAPE_COLOR: Record<string, string> = {
  reply: 'var(--blue, #63b4ff)',
  approve: 'var(--green, #5dd28b)',
  review: '#6bd8c4',
  decide: '#c38dff',
  act: '#9aa0aa',
  read: '#8b8b96',
};

function titlePrefix(title: string): string | null {
  const m = title.match(/^\[([A-Z]+)\]\s/);
  return m ? m[1] : null;
}

function inferShape(t: KlavaTask): string {
  if (t.shape) return t.shape;
  const tag = titlePrefix(t.title);
  if (!tag) return 'act';
  if (tag === 'REPLY') return 'reply';
  if (tag === 'APPROVE' || tag === 'PROPOSAL') return 'approve';
  if (tag === 'REVIEW') return 'review';
  if (tag === 'DECIDE') return 'decide';
  if (tag === 'READ') return 'read';
  return 'act';
}

function isProposal(t: KlavaTask): boolean {
  return t.type === 'proposal' || titlePrefix(t.title) === 'PROPOSAL';
}

function isResult(t: KlavaTask): boolean {
  return t.type === 'result' || titlePrefix(t.title) === 'RESULT';
}

function visibleTitle(t: KlavaTask): string {
  return t.title.replace(/^\[[A-Z]+\]\s*/, '');
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '';
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch { return ''; }
}

// Rethink Panel retired April 2026 — replaced by Execute / Research-more /
// Follow-up buttons with inline CommentPopover. See git history for the old
// implementation if you need to resurrect the Discuss-in-Chat flow.

// DispatchPanel retired April 2026 — the three-option Do / Enrich / Plan
// surface collapsed into a single Klava comment popover driven through
// DECK_ACTIONS (id: 'klava', dispatch: 'comment-popover', mode: 'klava-new').
// See git history for the three-mode variant if you need to resurrect it.

// ─── Universal Card ──────────────────────────────────────────────

type CardAction =
  | 'done' | 'snooze' | 'shuffle' | 'skip'
  | 'approve' | 'reject'
  | 'session'
  | 'execute' | 'research-more' | 'follow-up' | 'delegate' | 'proposal';
// 'skip' is retained as an internal exit reason used by `advance()` — the
// visible Skip button was retired April 2026 in favour of Done / Reject.
// 'approve' is internal-only now; the visible Proposal button is 'execute'
// which carries an optional user comment through to the new Klava task.
// 'delegate' + 'proposal' = replaced the single 'klava-new' April 2026.
// Delegate → Klava executes; the dispatched [ACTION] row morphs into a
//   [RESULT] card in place (consumer.mark_done → convert_to_result).
// Proposal → Klava drafts a plan; the dispatched [RESEARCH] row morphs
//   into a [PROPOSAL] card in place (convert_to_proposal).
// The original source is marked done at dispatch; the dispatched row is
// the single survivor on the Deck and evolves from running → result /
// proposal without ever creating a second card. Same GTask id the whole way.

interface DeckCardLike extends KlavaTask {
  _overdue?: boolean;
  _overdue_days?: number;
  _is_today?: boolean;
  _priority_score?: number;
  _section?: string;
  _list_name?: string;
  _due?: string | null;
}

type ContinueMode = 'execute' | 'research-more' | 'follow-up' | 'reject-result' | 'delegate' | 'proposal';

interface CardProps {
  task: DeckCardLike;
  exiting: CardAction | null;
  onAction: (action: CardAction) => void;
  onLaunch: () => void;
  onSnooze: (days: number) => void;
  onContinue: (mode: ContinueMode, comment: string) => void;
  // When set, the CommentButton with matching def.id should open its popover
  // (keyboard-shortcut path). CommentButton calls onPopoverConsumed() after
  // reading the signal so one keypress = one open.
  popoverRequest: { id: string; tick: number } | null;
  onPopoverConsumed: () => void;
}

// ─── Deck action registry ────────────────────────────────────────
// Single source of truth for every button on a deck card. Drives JSX
// rendering, keyboard shortcuts, and (later) the footer keyhint. Adding a
// new button or changing where it appears should be a one-line edit here.

type CardKind = 'proposal' | 'result' | 'task';

type ActionDispatch =
  | { kind: 'action'; action: CardAction }
  | { kind: 'event'; name: string }
  | { kind: 'launch' }
  | { kind: 'snooze-chooser' }
  | { kind: 'comment-popover'; mode: ContinueMode; submitLabel: string; placeholder: string };

interface DeckActionDef {
  id: string;
  icon?: string;
  label: string;
  shortcut?: string;
  altKeys?: string[];
  kinds: CardKind[];
  primaryOn?: CardKind[];
  guard?: (t: KlavaTask) => boolean;
  title: string;
  dispatch: ActionDispatch;
}

// Vocabulary (April 2026):
//   Execute (proposal, A/Enter): run the plan. Queues a new Klava task that
//     resumes the proposal's session if present. Optional comment steers.
//   Research-more (proposal, M): keep as a proposal but refine it. Klava
//     produces a revised [PROPOSAL] based on the comment.
//   Follow-up (result, F): iterate on a finished [RESULT]. Same-session
//     continuation; optional comment steers the next pass.
//   Session (task, O): open in Chat as an active session — write into it.
//   Klava (task, K): enqueue async job, Klava executes and returns a Result.
//   Done (task/result, D): close this card, no new work.
//   Reject (proposal/task/result, R): "I won't do this" — closes with reason.
//     On a Result, the reason gets stamped into the GTask for audit.
//   Snooze (all, S): push due date by 1d / 1w / 1m via chooser.
//   Shuffle (all, H/Tab): move to back of pile, no mutation.
// Execute / Research-more / Follow-up / Reject-on-Result all open a
// CommentPopover. Keyboard shortcut = submit with empty comment (fast path);
// clicking the button opens the textarea so you can steer.
const DECK_ACTIONS: DeckActionDef[] = [
  {
    id: 'execute',
    icon: '✓',
    label: 'Execute',
    shortcut: 'A',
    altKeys: ['Enter'],
    kinds: ['proposal'],
    primaryOn: ['proposal'],
    title: 'Execute — run the plan, optionally with a steering comment',
    dispatch: {
      kind: 'comment-popover',
      mode: 'execute',
      submitLabel: 'Execute',
      placeholder: 'Optional steering comment — e.g. "focus on EU clients first".',
    },
  },
  {
    id: 'research-more',
    icon: '🔁',
    label: 'Research more',
    shortcut: 'M',
    kinds: ['proposal'],
    title: 'Research more — Klava refines this proposal based on your comment',
    dispatch: {
      kind: 'comment-popover',
      mode: 'research-more',
      submitLabel: 'Refine',
      placeholder: 'What should change? e.g. "split into stalled vs lost, preserve client X."',
    },
  },
  {
    id: 'follow-up',
    icon: '↪',
    label: 'Follow-up',
    shortcut: 'F',
    kinds: ['result'],
    title: 'Follow-up — iterate on this result in the same session',
    dispatch: {
      kind: 'comment-popover',
      mode: 'follow-up',
      submitLabel: 'Send follow-up',
      placeholder: 'What\'s next? e.g. "now draft the email to Bob."',
    },
  },
  {
    id: 'session',
    icon: '▶',
    label: 'Session',
    shortcut: 'O',
    kinds: ['task', 'result', 'proposal'],
    title: 'Open in Chat — spawns a new session with this card prefilled as context.',
    dispatch: { kind: 'action', action: 'session' },
  },
  {
    id: 'delegate',
    icon: '🤖',
    label: 'Delegate',
    shortcut: 'K',
    kinds: ['task'],
    primaryOn: ['task'],
    title: 'Delegate to Klava — she runs it, this card updates in place with the result',
    dispatch: {
      kind: 'comment-popover',
      mode: 'delegate',
      submitLabel: 'Delegate',
      placeholder: 'Optional steering — where to look, what to focus on. e.g. "search TG thread from Mar 14, keep tone informal."',
    },
  },
  {
    id: 'proposal',
    icon: '📝',
    label: 'Proposal',
    shortcut: 'P',
    kinds: ['task'],
    title: 'Ask Klava for a proposal — this card updates in place with the plan',
    dispatch: {
      kind: 'comment-popover',
      mode: 'proposal',
      submitLabel: 'Request proposal',
      placeholder: 'Optional framing — angle, constraints, audience. e.g. "three options, trade-offs, pick one."',
    },
  },
  {
    id: 'done',
    icon: '✓',
    label: 'Done',
    shortcut: 'D',
    altKeys: ['Enter'],
    kinds: ['task', 'result'],
    primaryOn: ['result'],
    title: 'Close this card — no new work',
    dispatch: { kind: 'action', action: 'done' },
  },
  {
    id: 'reject',
    icon: '✕',
    label: 'Reject',
    shortcut: 'R',
    kinds: ['proposal', 'task'],
    title: "Reject — mark as 'I won't do this'",
    dispatch: { kind: 'action', action: 'reject' },
  },
  {
    id: 'reject-result',
    icon: '✕',
    label: 'Reject',
    shortcut: 'R',
    kinds: ['result'],
    title: 'Reject result — acknowledge but record that we won\'t act on it',
    dispatch: {
      kind: 'comment-popover',
      mode: 'reject-result',
      submitLabel: 'Reject',
      placeholder: 'Reason (optional) — why not act on this result?',
    },
  },
  {
    id: 'snooze',
    icon: '⏱',
    label: 'Snooze',
    shortcut: 'S',
    kinds: ['proposal', 'task', 'result'],
    title: 'Snooze — push due date by 1d / 1w / 1m',
    dispatch: { kind: 'snooze-chooser' },
  },
  {
    id: 'shuffle',
    icon: '⤵',
    label: 'Shuffle',
    shortcut: 'H',
    altKeys: ['Tab'],
    kinds: ['proposal', 'task', 'result'],
    title: 'Move this card to back — no mutation',
    dispatch: { kind: 'action', action: 'shuffle' },
  },
];

function cardKind(t: KlavaTask): CardKind {
  if (isProposal(t)) return 'proposal';
  if (isResult(t)) return 'result';
  return 'task';
}

// Stable left-to-right button order on every card:
//   0  primary action (Execute / Session / Done)
//   1  secondary continuations (Research-more / Klava / Follow-up)
//   2  reject / reject-result
//   3  snooze
//   4  shuffle
function actionRank(def: DeckActionDef, kind: CardKind): number {
  if (def.primaryOn?.includes(kind)) return 0;
  if (def.id === 'reject' || def.id === 'reject-result') return 2;
  if (def.id === 'snooze') return 3;
  if (def.id === 'shuffle') return 4;
  return 1;
}

function actionsFor(kind: CardKind, t: KlavaTask): DeckActionDef[] {
  const picked = DECK_ACTIONS.filter(a => a.kinds.includes(kind) && (!a.guard || a.guard(t)));
  return picked
    .map((def, idx) => ({ def, idx }))
    .sort((a, b) => {
      const ra = actionRank(a.def, kind), rb = actionRank(b.def, kind);
      if (ra !== rb) return ra - rb;
      return a.idx - b.idx; // stable: preserve registry order within a tier
    })
    .map(x => x.def);
}

function matchesActionKey(def: DeckActionDef, e: KeyboardEvent): boolean {
  const lower = e.key.toLowerCase();
  if (def.shortcut && lower === def.shortcut.toLowerCase()) return true;
  if (def.altKeys) {
    for (const k of def.altKeys) {
      if (k.length === 1 ? lower === k.toLowerCase() : e.key === k) return true;
    }
  }
  return false;
}

interface DeckButtonProps {
  def: DeckActionDef;
  kind: CardKind;
  task: KlavaTask;
  onAction: (action: CardAction) => void;
  onLaunch: () => void;
  onSnooze: (days: number) => void;
  onContinue: (mode: ContinueMode, comment: string) => void;
  popoverRequest: { id: string; tick: number } | null;
  onPopoverConsumed: () => void;
}

function DeckButton({ def, kind, task, onAction, onLaunch, onSnooze, onContinue, popoverRequest, onPopoverConsumed }: DeckButtonProps) {
  const primary = def.primaryOn?.includes(kind);

  if (def.dispatch.kind === 'snooze-chooser') {
    return <SnoozeButton def={def} primary={!!primary} onSnooze={onSnooze} />;
  }

  if (def.dispatch.kind === 'comment-popover') {
    return (
      <CommentButton
        def={def}
        primary={!!primary}
        onSubmit={(comment) => {
          if (def.dispatch.kind === 'comment-popover') {
            onContinue(def.dispatch.mode, comment);
          }
        }}
        popoverRequest={popoverRequest}
        onPopoverConsumed={onPopoverConsumed}
      />
    );
  }

  const dispatch = def.dispatch;
  const handleClick = () => {
    switch (dispatch.kind) {
      case 'action':
        onAction(dispatch.action);
        return;
      case 'event':
        window.dispatchEvent(new CustomEvent(dispatch.name, { detail: { taskId: task.id } }));
        return;
      case 'launch':
        onLaunch();
        return;
    }
  };
  return (
    <button
      className={primary ? 'deck-btn deck-btn-primary' : 'deck-btn'}
      onClick={handleClick}
      title={def.title}
    >
      {def.icon ? `${def.icon} ` : ''}{def.label}
      {def.shortcut && <kbd className="deck-btn-key">{def.shortcut}</kbd>}
    </button>
  );
}

interface CommentButtonProps {
  def: DeckActionDef;
  primary: boolean;
  onSubmit: (comment: string) => void;
  popoverRequest: { id: string; tick: number } | null;
  onPopoverConsumed: () => void;
}

function CommentButton({ def, primary, onSubmit, popoverRequest, onPopoverConsumed }: CommentButtonProps) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const seenTick = useRef<number>(-1);

  // Keyboard shortcut path: parent signals "open this button's popover" via
  // popoverRequest. The `tick` is incremented so repeated presses re-open.
  useEffect(() => {
    if (popoverRequest && popoverRequest.id === def.id && popoverRequest.tick !== seenTick.current) {
      seenTick.current = popoverRequest.tick;
      setOpen(true);
      onPopoverConsumed();
    }
  }, [popoverRequest, def.id, onPopoverConsumed]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  useEffect(() => {
    if (open) requestAnimationFrame(() => textareaRef.current?.focus());
    else setComment('');
  }, [open]);

  const submit = () => {
    setOpen(false);
    onSubmit(comment);
  };

  if (def.dispatch.kind !== 'comment-popover') return null;
  const { submitLabel, placeholder } = def.dispatch;

  return (
    <div className="deck-comment-wrap" ref={wrapRef}>
      <button
        className={primary ? 'deck-btn deck-btn-primary' : 'deck-btn'}
        onClick={() => setOpen(o => !o)}
        title={def.title}
      >
        {def.icon ? `${def.icon} ` : ''}{def.label}
        {def.shortcut && <kbd className="deck-btn-key">{def.shortcut}</kbd>}
      </button>
      {open && (
        <div className="deck-comment-menu">
          <textarea
            ref={textareaRef}
            className="deck-comment-textarea"
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder={placeholder}
            rows={3}
            onKeyDown={e => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); submit(); }
              else if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
            }}
          />
          <div className="deck-comment-actions">
            <button className="deck-btn deck-btn-primary" onClick={submit}>
              {submitLabel} <kbd className="deck-btn-key">⌘↵</kbd>
            </button>
            <button className="deck-btn deck-btn-ghost" onClick={() => setOpen(false)}>
              Cancel <kbd className="deck-btn-key">Esc</kbd>
            </button>
          </div>
          <div className="deck-comment-hint">
            Empty comment = default behaviour. <kbd>⌘↵</kbd> submit · <kbd>Esc</kbd> cancel.
          </div>
        </div>
      )}
    </div>
  );
}

interface SnoozeButtonProps {
  def: DeckActionDef;
  primary: boolean;
  onSnooze: (days: number) => void;
}

function SnoozeButton({ def, primary, onSnooze }: SnoozeButtonProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const pick = (days: number) => {
    setOpen(false);
    onSnooze(days);
  };

  return (
    <div className="deck-snooze-wrap" ref={wrapRef}>
      <button
        className={primary ? 'deck-btn deck-btn-primary' : 'deck-btn'}
        onClick={() => setOpen(o => !o)}
        title={def.title}
      >
        {def.icon ? `${def.icon} ` : ''}{def.label}
        {def.shortcut && <kbd className="deck-btn-key">{def.shortcut}</kbd>}
      </button>
      {open && (
        <div className="deck-snooze-menu">
          <button className="deck-snooze-opt" onClick={() => pick(1)}>+1 day</button>
          <button className="deck-snooze-opt" onClick={() => pick(7)}>+1 week</button>
          <button className="deck-snooze-opt" onClick={() => pick(30)}>+1 month</button>
        </div>
      )}
    </div>
  );
}

function UniversalCard({ task, exiting, onAction, onLaunch, onSnooze, onContinue, popoverRequest, onPopoverConsumed }: CardProps) {
  const shape = inferShape(task);
  const proposal = isProposal(task);
  const result = isResult(task);
  const accent = SHAPE_COLOR[shape] || SHAPE_COLOR.act;
  const tag = titlePrefix(task.title) || shape.toUpperCase();
  const overdueBadge = task._overdue
    ? `${task._overdue_days || 0}d overdue`
    : task._is_today ? 'today' : null;

  return (
    <div className={`deck-card deck-card-${shape}${exiting ? ` deck-card-exiting-${exiting}` : ''}`}>
      <div className="deck-card-meta">
        <span className="deck-card-tag" style={{ color: accent, borderColor: accent }}>{tag}</span>
        {task.priority === 'high' && <span className="deck-priority-dot" title="High priority" />}
        {overdueBadge && (
          <span className="deck-mode-tag" style={task._overdue ? { color: '#ff6b6b', borderColor: '#ff6b6b' } : undefined}>
            {overdueBadge}
          </span>
        )}
        {task.mode_tags?.map(m => (
          <span key={m} className="deck-mode-tag">{m}</span>
        ))}
        {task._section && <span className="deck-mode-tag">{task._section}</span>}
        <span className="deck-card-source">{task._list_name || task.source || 'manual'}</span>
        {task.criticality != null && (
          <span className="deck-crit" title="Criticality">· crit {task.criticality}</span>
        )}
        <span className="deck-card-spacer" />
        <span className="deck-card-date">
          {task._due || (task.created ? timeAgo(task.created) : '')}
        </span>
      </div>

      <h2 className="deck-card-title">{visibleTitle(task)}</h2>

      {proposal && (task.proposal_plan || task.body) && (
        <div className="deck-card-plan">
          <div className="deck-card-plan-label">Proposed plan</div>
          <pre className="deck-card-plan-body">
            {task.proposal_plan || (task.body || '').replace(/^##\s*Plan\s*\n?/i, '').slice(0, 1200)}
          </pre>
        </div>
      )}

      {!proposal && task.body && task.body.trim() && (() => {
        // Strip the backend's `...(truncated)` marker before markdown render so
        // it doesn't hang as raw text at the end of the scroll — render a
        // subtle footer pill instead. The marker was baked in for cards
        // produced before the 7500-char bump (tasks/consumer.py, klava_manager.py).
        const rawBody = task.body;
        const truncated = /\n\.\.\.\(truncated\)\s*$/i.test(rawBody);
        const cleanBody = truncated ? rawBody.replace(/\n\.\.\.\(truncated\)\s*$/i, '') : rawBody;
        return (
          <>
            <div
              className={`deck-card-body${result ? ' deck-card-body-result' : ''}`}
              dangerouslySetInnerHTML={{ __html: renderChatMD(cleanBody) }}
            />
            {truncated && (
              <div className="deck-card-truncated-footer" title="Output was capped when the card was written; full text not retained.">
                output truncated
              </div>
            )}
          </>
        );
      })()}

      {!proposal && (!task.body || !task.body.trim()) && (
        <div className="deck-card-empty-hint">
          No description. <kbd>🤖 Delegate</kbd> to Klava — she'll research who /
          what / why-now and the card will convert into a Result.
        </div>
      )}

      <div className="deck-card-actions">
        {actionsFor(cardKind(task), task).map(def => (
          <DeckButton
            key={def.id}
            def={def}
            kind={cardKind(task)}
            task={task}
            onAction={onAction}
            onLaunch={onLaunch}
            onSnooze={onSnooze}
            onContinue={onContinue}
            popoverRequest={popoverRequest}
            onPopoverConsumed={onPopoverConsumed}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Filters ─────────────────────────────────────────────────────

type SortMode = 'smart' | 'oldest' | 'priority' | 'newest' | 'alpha';

interface DeckFilters {
  sort: SortMode;
  search: string;
  typeFilter: 'all' | 'task' | 'proposal';
  tags: string[]; // active tag filters (OR — matches any)
}

const DEFAULT_FILTERS: DeckFilters = {
  sort: 'smart',
  search: '',
  typeFilter: 'all',
  tags: [],
};

const FILTERS_STORAGE_KEY = 'deck:filters:v1';

function loadFilters(): DeckFilters {
  try {
    const raw = localStorage.getItem(FILTERS_STORAGE_KEY);
    if (!raw) return DEFAULT_FILTERS;
    const parsed = JSON.parse(raw) as Partial<DeckFilters>;
    return { ...DEFAULT_FILTERS, ...parsed };
  } catch { return DEFAULT_FILTERS; }
}

function saveFilters(f: DeckFilters) {
  try { localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(f)); }
  catch { /* quota / private mode — silently fail */ }
}

function userTagsOfCard(t: DeckCardLike): string[] {
  const set = new Set<string>();
  extractHashtags(t.title).forEach(x => set.add(x));
  extractHashtags(t.body).forEach(x => set.add(x));
  extractHashtags(t.proposal_plan).forEach(x => set.add(x));
  return [...set];
}

function tagsOfCard(t: DeckCardLike): string[] {
  const set = new Set<string>();
  userTagsOfCard(t).forEach(x => set.add(x));
  (t.mode_tags || []).forEach(x => set.add(x));
  if (t._section) set.add(t._section);
  if (t._overdue) set.add('overdue');
  if (t._is_today) set.add('today');
  if (t.priority === 'high') set.add('high-pri');
  if (t.type === 'proposal' || titlePrefix(t.title) === 'PROPOSAL') set.add('proposal');
  return [...set];
}

function filterAndSort(cards: DeckCardLike[], f: DeckFilters): DeckCardLike[] {
  let out = cards;

  if (f.typeFilter === 'proposal') out = out.filter(t => t.type === 'proposal' || titlePrefix(t.title) === 'PROPOSAL');
  else if (f.typeFilter === 'task') out = out.filter(t => t.type !== 'proposal' && t.type !== 'result' && titlePrefix(t.title) !== 'PROPOSAL' && titlePrefix(t.title) !== 'RESULT');

  if (f.tags.length > 0) {
    const active = new Set(f.tags);
    out = out.filter(t => tagsOfCard(t).some(tag => active.has(tag)));
  }

  if (f.search.trim()) {
    const q = f.search.trim().toLowerCase();
    out = out.filter(t =>
      t.title.toLowerCase().includes(q) ||
      (t.body || '').toLowerCase().includes(q) ||
      (t.proposal_plan || '').toLowerCase().includes(q)
    );
  }

  if (f.sort === 'smart') return out; // queries.ts already sorted this way
  const copy = [...out];
  if (f.sort === 'oldest') {
    copy.sort((a, b) => (b._overdue_days ?? 0) - (a._overdue_days ?? 0)
      || (a.created ? new Date(a.created).getTime() : 0) - (b.created ? new Date(b.created).getTime() : 0));
  } else if (f.sort === 'priority') {
    const w = (p: string) => p === 'high' ? 2 : p === 'medium' ? 1 : 0;
    copy.sort((a, b) => w(b.priority) - w(a.priority)
      || (b.criticality ?? 0) - (a.criticality ?? 0)
      || (b._priority_score ?? 0) - (a._priority_score ?? 0));
  } else if (f.sort === 'newest') {
    copy.sort((a, b) => (b.created ? new Date(b.created).getTime() : 0) - (a.created ? new Date(a.created).getTime() : 0));
  } else if (f.sort === 'alpha') {
    copy.sort((a, b) => visibleTitle(a).localeCompare(visibleTitle(b)));
  }
  return copy;
}

interface FilterBarProps {
  filters: DeckFilters;
  setFilters: (f: DeckFilters) => void;
  availableTags: string[];
  userTagSet: Set<string>;
  tagCounts: Record<string, number>;
  totalMatched: number;
  totalOpen: number;
  searchRef: React.Ref<HTMLInputElement>;
  onRefresh: () => void;
  isFetching: boolean;
}

function FilterBar({ filters, setFilters, availableTags, userTagSet, tagCounts, totalMatched, totalOpen, searchRef, onRefresh, isFetching }: FilterBarProps) {
  const userTags = availableTags.filter(t => userTagSet.has(t));
  const autoTags = availableTags.filter(t => !userTagSet.has(t));
  const toggleTag = (tag: string) => {
    const next = filters.tags.includes(tag)
      ? filters.tags.filter(x => x !== tag)
      : [...filters.tags, tag];
    setFilters({ ...filters, tags: next });
  };
  const hasActive = filters.search || filters.typeFilter !== 'all' || filters.tags.length > 0 || filters.sort !== 'smart';

  return (
    <div className="deck-filterbar">
      <div className="deck-filterbar-row">
        <div className="deck-filter-search-wrap">
          <input
            ref={searchRef}
            className="deck-filter-search"
            type="text"
            placeholder="Search…   [/]"
            value={filters.search}
            onChange={e => setFilters({ ...filters, search: e.target.value })}
            onKeyDown={e => {
              if (e.key === 'Escape') { e.preventDefault(); setFilters({ ...filters, search: '' }); (e.target as HTMLInputElement).blur(); }
            }}
          />
        </div>

        <select
          className="deck-filter-sort"
          value={filters.sort}
          onChange={e => setFilters({ ...filters, sort: e.target.value as SortMode })}
          title="Sort order"
        >
          <option value="smart">Sort: Smart</option>
          <option value="oldest">Sort: Oldest / most overdue</option>
          <option value="priority">Sort: Priority</option>
          <option value="newest">Sort: Newest</option>
          <option value="alpha">Sort: A → Z</option>
        </select>

        <div className="deck-filter-typegroup">
          {(['all', 'task', 'proposal'] as const).map(t => (
            <button
              key={t}
              className={`deck-filter-typebtn${filters.typeFilter === t ? ' active' : ''}`}
              onClick={() => setFilters({ ...filters, typeFilter: t })}
            >
              {t === 'all' ? 'All' : t === 'task' ? 'Tasks' : 'Proposals'}
            </button>
          ))}
        </div>

        <span className="deck-filter-count">
          <strong>{totalMatched}</strong> / {totalOpen}
        </span>

        {hasActive && (
          <button
            className="deck-filter-clear"
            onClick={() => setFilters(DEFAULT_FILTERS)}
            title="Clear all filters"
          >
            ✕ Clear
          </button>
        )}

        <button
          className="deck-filter-clear"
          onClick={onRefresh}
          disabled={isFetching}
          title="Refresh Deck (auto-refresh runs every 5 min and on tab focus)"
          style={{ marginLeft: 'auto' }}
        >
          {isFetching ? '⟳ …' : '⟳ Refresh'}
        </button>
      </div>

      {userTags.length > 0 && (
        <div className="deck-filterbar-tags">
          {userTags.map(tag => {
            const active = filters.tags.includes(tag);
            const count = tagCounts[tag] || 0;
            return (
              <button
                key={`u-${tag}`}
                className={`deck-filter-chip user${active ? ' active' : ''}`}
                onClick={() => toggleTag(tag)}
                title="Your hashtag — extracted from task title/notes"
              >
                #{tag} <span className="deck-filter-chip-count">{count}</span>
              </button>
            );
          })}
        </div>
      )}
      {autoTags.length > 0 && (
        <div className="deck-filterbar-tags deck-filterbar-tags-auto">
          {autoTags.map(tag => {
            const active = filters.tags.includes(tag);
            const count = tagCounts[tag] || 0;
            return (
              <button
                key={`a-${tag}`}
                className={`deck-filter-chip${active ? ' active' : ''}`}
                onClick={() => toggleTag(tag)}
                title="Auto-derived marker"
              >
                #{tag} <span className="deck-filter-chip-count">{count}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Empty state ────────────────────────────────────────────────

function EmptyDeck({ hasAny }: { hasAny: boolean }) {
  return (
    <div className="deck-empty">
      <div className="deck-empty-icon">◇</div>
      <h2 className="deck-empty-title">
        {hasAny ? 'All caught up' : 'Deck is empty'}
      </h2>
      <p className="deck-empty-text">
        {hasAny
          ? 'You processed every visible card. The idle-research loop will surface a new proposal when it fires.'
          : 'No Klava tasks yet. Create one from the Assistant tab, or wait for the idle-research loop.'}
      </p>
    </div>
  );
}

// ─── Main Tab ───────────────────────────────────────────────────

export function DeckTab() {
  const { data: tasks, refetch, isLoading, isFetching } = useDeckCards(true);
  const [processed, setProcessed] = useState<Set<string>>(new Set());
  const [shufflePenalty, setShufflePenalty] = useState<Map<string, number>>(new Map());
  const [exiting, setExiting] = useState<CardAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [filters, setFiltersState] = useState<DeckFilters>(loadFilters);
  // Keyboard shortcut channel for comment-popover buttons. Each keypress bumps
  // `tick` so a stale signal can't re-fire and repeated presses re-open.
  const [popoverRequest, setPopoverRequest] = useState<{ id: string; tick: number } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const requestPopover = useCallback((id: string) => {
    setPopoverRequest(prev => ({ id, tick: (prev?.tick ?? 0) + 1 }));
  }, []);
  const clearPopoverRequest = useCallback(() => setPopoverRequest(null), []);

  const setFilters = useCallback((f: DeckFilters) => {
    setFiltersState(f);
    saveFilters(f);
  }, []);

  useEffect(() => () => { if (exitTimer.current) clearTimeout(exitTimer.current); }, []);

  const openAll = useMemo<DeckCard[]>(() => {
    const all: DeckCard[] = tasks || [];
    const open = all.filter(t =>
      t.status !== 'done' &&
      t.status !== 'failed' &&
      t.proposal_status !== 'rejected' &&
      !processed.has(t.id)
    );
    return open
      .map((t, idx) => ({ t, idx, penalty: shufflePenalty.get(t.id) || 0 }))
      .sort((a, b) => a.penalty - b.penalty || a.idx - b.idx)
      .map(x => x.t);
  }, [tasks, processed, shufflePenalty]);

  // Tag universe + counts (computed from all open cards, not filtered — so
  // chips don't disappear when you narrow down).
  const { availableTags, tagCounts, userTagSet } = useMemo(() => {
    const counts: Record<string, number> = {};
    const userSet = new Set<string>();
    openAll.forEach(t => {
      tagsOfCard(t).forEach(tag => { counts[tag] = (counts[tag] || 0) + 1; });
      userTagsOfCard(t).forEach(tag => userSet.add(tag));
    });
    const tags = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    return { availableTags: tags, tagCounts: counts, userTagSet: userSet };
  }, [openAll]);

  const openTasks = useMemo<DeckCard[]>(
    () => filterAndSort(openAll, filters) as DeckCard[],
    [openAll, filters]
  );

  const current = openTasks[0];

  const advance = useCallback((action: CardAction, id: string) => {
    setExiting(action);
    exitTimer.current = setTimeout(() => {
      setExiting(null);
      if (action === 'shuffle') {
        setShufflePenalty(prev => {
          const next = new Map(prev);
          next.set(id, (next.get(id) || 0) + 1);
          return next;
        });
      } else {
        setProcessed(prev => {
          const next = new Set(prev);
          next.add(id);
          return next;
        });
      }
    }, 220);
  }, []);

  const handleAction = useCallback(async (action: CardAction) => {
    if (!current || busy) return;
    const id = current.id;
    const isGTask = id.startsWith('gtask_');
    const isGhIssue = id.startsWith('gh_');
    // Klava cards come from /api/klava/tasks with raw Google Task IDs (no
    // prefix). Anything that isn't a gtask_-prefixed inbox card or a gh_
    // issue is a Klava list GTask and must close through klavaComplete.
    const isKlava = !isGTask && !isGhIssue;

    try {
      if (action === 'approve') {
        setBusy(true);
        await api.klavaApprove(id);
        advance(action, id);
        setTimeout(() => refetch(), 260);
      } else if (action === 'reject') {
        setBusy(true);
        if (isProposal(current)) {
          await api.klavaReject(id, '');
        } else if (isKlava) {
          await api.klavaCancel(id);
        } else if (isGTask) {
          await api.updateTask(id, 'cancel');
        }
        advance(action, id);
        setTimeout(() => refetch(), 260);
      } else if (action === 'done') {
        setBusy(true);
        if (isKlava) {
          await api.klavaComplete(id);
        } else if (isGTask) {
          await api.updateTask(id, 'done');
        }
        advance(action, id);
        setTimeout(() => refetch(), 260);
      } else if (action === 'skip') {
        // User expectation: skip closes the card in GTasks too, not just
        // locally on the Deck. Klava + inbox cards both route to completion.
        setBusy(true);
        try {
          if (isKlava) {
            await api.klavaComplete(id);
          } else if (isGTask) {
            await api.updateTask(id, 'done');
          }
        } catch (e) {
          console.error('skip backend close failed:', e);
          alert(`Skip failed: ${(e as Error).message}`);
        }
        advance(action, id);
        setTimeout(() => refetch(), 260);
      } else if (action === 'snooze') {
        // Snooze goes through the chooser → handleSnooze(days). This branch
        // catches keyboard-press fallthrough (which we no longer support) and
        // stays defensive.
        advance(action, id);
      } else if (action === 'session') {
        // Always spawn a fresh chat session and prefill the card as context.
        // The old 'resume the session that produced this' behaviour was confusing —
        // the user consistently wanted a clean slate with the card's content inline.
        const plainTitle = current.title.replace(/^\[[A-Z]+\]\s*/, '');
        const body = (current.body || '').trim();
        const dueStr = current._due ? ` — due ${current._due}` : '';
        const overdueStr = current._overdue ? ` (${current._overdue_days}d overdue)` : '';
        const isResult = current.type === 'result';
        const isProposal = current.type === 'proposal' || titlePrefix(current.title) === 'PROPOSAL';
        let prompt: string;
        if (isResult) {
          prompt = [
            `Let's discuss this result.`,
            ``,
            `**Result:** ${plainTitle}${dueStr}`,
            `**Card id:** ${current.id}`,
            ``,
            body ? `**Result body:**\n${body}` : `**Result body:** (empty)`,
            ``,
            `Re-read the result above and wait for my questions. Don't re-run anything yet.`,
          ].join('\n');
        } else if (isProposal) {
          const plan = (current.proposal_plan || '').trim();
          prompt = [
            `Let's walk through this proposal before deciding.`,
            ``,
            `**Proposal:** ${plainTitle}${dueStr}`,
            `**Card id:** ${current.id}`,
            ``,
            plan ? `**Plan:**\n${plan}` : (body ? `**Body:**\n${body}` : `**Body:** (empty)`),
            ``,
            `Read the plan above and wait for my questions. If I ask for changes, show me the revised plan first — don't execute without a green light.`,
          ].join('\n');
        } else {
          prompt = [
            `Let's work on this task live.`,
            ``,
            `**Task:** ${plainTitle}${dueStr}${overdueStr}`,
            `**GTask id:** ${current.id}`,
            ``,
            body ? `**Notes:**\n${body}` : `**Notes:** (empty — please give me a "who / what / state / why now" briefing before we plan)`,
            ``,
            `Start by giving me a concise briefing from Obsidian (People / Organizations / Deals) and vadimgest, then we decide together what to do.`,
          ].join('\n');
        }
        // Reset to a clean chat session (no send, just clear state), then prefill.
        window.dispatchEvent(new CustomEvent('chat:open'));
        window.dispatchEvent(new CustomEvent('chat:new-session'));
        setTimeout(() => {
          window.dispatchEvent(new CustomEvent('chat:prefill-input', { detail: { text: prompt } }));
        }, 250);
        // Don't advance — the user may come back to finalize after chatting.
      } else {
        // shuffle only — skip/done/snooze are handled above with backend
        // completion calls. shuffle stays local (moves the card down the pile).
        advance(action, id);
      }
    } catch (e) {
      console.error('Deck action failed:', e);
      alert(`${action} failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }, [current, busy, advance, refetch, openAll]);

  const handleContinue = useCallback(async (mode: ContinueMode, comment: string) => {
    if (!current || busy) return;
    const id = current.id;
    try {
      setBusy(true);
      if (mode === 'reject-result') {
        await api.klavaRejectResult(id, comment);
        advance('reject', id);
      } else if (mode === 'delegate' || mode === 'proposal') {
        // Delegate: Klava runs the task; the dispatched [ACTION] row morphs
        //   into a [RESULT] card in place on completion (consumer.mark_done
        //   calls convert_to_result). One card evolves — no extra result.
        // Proposal: Klava drafts; the [RESEARCH] row morphs into a [PROPOSAL]
        //   card in place (convert_to_proposal). Same single-card UX.
        // The comment popover is always shown so the user can steer. Empty
        // comment = defaults.
        const plainTitle = current.title.replace(/^\[[A-Z]+\]\s*/, '');
        const body = current.body || '';
        const trimmedTips = comment.trim();
        const context = [
          `## Source GTask`,
          `id: ${current.id}`,
          current._list_name ? `list: ${current._list_name}` : '',
          current._due ? `due: ${current._due}` : '',
          current._overdue ? `overdue: ${current._overdue_days}d` : '',
          current._section ? `section: ${current._section}` : '',
          ``,
          `## Title`,
          plainTitle,
          ``,
          `## Notes`,
          body.trim() || '(empty)',
        ].filter(Boolean).join('\n');
        const tipsSection = trimmedTips
          ? `\n\n## Steering comment\n${trimmedTips}\n\nThese tips are load-bearing. Follow them before falling back to defaults.`
          : '';
        const instructions = mode === 'delegate'
          ? `\n\n## Instructions\nAct more, ask less. Research context first (Obsidian People / Organizations / Deals, vadimgest for recent messages, Hlopya for calls). Then execute the task — draft the email, run the query, file the issue, whatever it implies.\n\nYour FINAL message becomes the result card. The consumer will convert this task in place into a [RESULT] card on the Deck (same GTask id, new title + body). Do NOT call \`create_result\` — just make the final message the result. Shape it as "here is a task, here is what I did, here is the result or links where you can observe it", not a step-by-step. Use sections: ## What was done / ## Result / ## Artifacts / ## Suggested next step. If you hit a hard blocker, name the blocker and what unblocks it.`
          : `\n\n## Instructions\nDon't execute — propose. Research context first (Obsidian, vadimgest, Hlopya). Then draft a concrete proposal.\n\nYour FINAL message becomes the proposal plan. The consumer will convert this task in place into a [PROPOSAL] card on the Deck (same GTask id, new title + body) awaiting my Execute / Refine / Reject. Do NOT call \`create_proposal\` — just make the final message the plan. Cover: what to do, why now, key risks, the concrete first step. Keep it tight — one screen, not an essay.`;
        const prompt = `${context}${tipsSection}${instructions}`;
        const titlePrefix = mode === 'delegate' ? '[ACTION]' : '[RESEARCH]';
        await api.klavaCreate(`${titlePrefix} ${plainTitle}`, prompt, 'medium', true);
        // Mark the source GTask done so the Deck shows only the eventual
        // RESULT / PROPOSAL card, not both. If this fails we still advance
        // locally — the worst case is the old card re-appears on refetch,
        // and the user can Done it manually.
        try {
          const isGTask = id.startsWith('gtask_');
          if (isGTask) {
            await api.updateTask(id, 'done');
          } else if (!id.startsWith('gh_')) {
            await api.klavaComplete(id);
          }
        } catch (e) {
          console.warn('Source card completion failed after delegate/proposal dispatch:', e);
        }
        advance('done', id);
      } else {
        await api.klavaContinue(id, mode, comment);
        // For 'research-more', the backend also rejects the current proposal
        // so the Deck replaces this card with the refined one on refetch.
        // For 'execute' and 'follow-up', the card stays open until user
        // explicitly closes it — the new task lands as a peer on the Deck.
        const exitAs: CardAction = mode === 'research-more' ? 'reject' : 'done';
        advance(exitAs, id);
      }
      setTimeout(() => refetch(), 260);
    } catch (e) {
      console.error(`Continue (${mode}) failed:`, e);
      alert(`${mode} failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }, [current, busy, advance, refetch]);

  const handleSnooze = useCallback(async (days: number) => {
    if (!current || busy) return;
    const id = current.id;
    const isGTask = id.startsWith('gtask_');
    const isGhIssue = id.startsWith('gh_');
    const isKlava = !isGTask && !isGhIssue;
    try {
      setBusy(true);
      if (isGTask) {
        await api.updateTask(id, 'postpone', '', days);
      } else if (isKlava) {
        await api.klavaPostpone(id, days);
      }
      advance('snooze', id);
      setTimeout(() => refetch(), 260);
    } catch (e) {
      console.error('Snooze failed:', e);
      alert(`Snooze failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }, [current, busy, advance, refetch]);

  const handleLaunch = useCallback(async () => {
    if (!current) return;
    try {
      await api.klavaLaunch(current.id);
      refetch();
    } catch (e) {
      console.error('Launch failed:', e);
    }
  }, [current, refetch]);

  // Keyboard shortcuts — resolved via the DECK_ACTIONS registry so there's
  // one source of truth for both the rendered buttons and their keys.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // e.target can be window/document when events are dispatched programmatically
      // or bubble from non-Element sources; those have no .closest(), and calling it
      // throws TypeError which previously aborted the whole handler so no shortcut
      // fired. Guard with instanceof before touching .closest().
      const target = e.target instanceof Element ? e.target : null;
      const inTextInput = !!target?.closest('input, textarea');
      if (e.key === '/' && !inTextInput) {
        e.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
        return;
      }
      if (inTextInput) return;
      if (!current) return;
      const kind = cardKind(current);
      for (const def of actionsFor(kind, current)) {
        if (!matchesActionKey(def, e)) continue;
        e.preventDefault();
        switch (def.dispatch.kind) {
          case 'action':
            handleAction(def.dispatch.action);
            return;
          case 'event':
            window.dispatchEvent(new CustomEvent(def.dispatch.name, { detail: { taskId: current.id } }));
            return;
          case 'launch':
            // Launch has no keyboard binding in the registry.
            return;
          case 'snooze-chooser':
            // Keyboard S is the power-user fast path — default +1 week, skip
            // the popover. Click the button for the 1d/1w/1m picker.
            handleSnooze(7);
            return;
          case 'comment-popover':
            // Open the popover so the user can steer with a comment. The old
            // fast-path (empty submit on keypress) was removed — Delegate /
            // Proposal / Execute / etc. always surface the input.
            requestPopover(def.id);
            return;
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleAction, handleSnooze, handleContinue, current, requestPopover]);

  const totalOpen = (tasks || []).filter(t => t.status !== 'done' && t.status !== 'failed').length;
  const proposals = (tasks || []).filter(isProposal).length;
  const overdueCount = (tasks || []).filter((t: DeckCard) => t._overdue).length;
  const todayCount = (tasks || []).filter((t: DeckCard) => t._is_today).length;

  if (isLoading) {
    return <div className="deck-shell"><div className="deck-empty"><div>Loading…</div></div></div>;
  }

  return (
    <div className="deck-shell">
      <div className="deck-topbar">
        <span className="deck-topbar-title">Deck</span>
        <span className="deck-topbar-sep">·</span>
        <span className="deck-topbar-meta">
          <strong>{openTasks.length}</strong> visible
          <span className="deck-topbar-sep">/</span>
          <strong>{totalOpen}</strong> open
          {proposals > 0 && <><span className="deck-topbar-sep">·</span><strong>{proposals}</strong> proposal{proposals === 1 ? '' : 's'}</>}
          {overdueCount > 0 && <><span className="deck-topbar-sep">·</span><strong style={{ color: '#ff6b6b' }}>{overdueCount}</strong> overdue</>}
          {todayCount > 0 && <><span className="deck-topbar-sep">·</span><strong>{todayCount}</strong> today</>}
        </span>
        <span className="deck-spacer" />
        <span className="deck-keyhint">
          <kbd>/</kbd> search · <kbd>A</kbd> execute · <kbd>M</kbd> refine · <kbd>F</kbd> follow-up · <kbd>O</kbd> session · <kbd>K</kbd> delegate · <kbd>P</kbd> proposal · <kbd>D</kbd> done · <kbd>R</kbd> reject · <kbd>S</kbd> snooze · <kbd>H</kbd> shuffle
        </span>
      </div>

      <FilterBar
        filters={filters}
        setFilters={setFilters}
        availableTags={availableTags}
        userTagSet={userTagSet}
        tagCounts={tagCounts}
        totalMatched={openTasks.length}
        totalOpen={openAll.length}
        searchRef={searchRef}
        onRefresh={() => refetch()}
        isFetching={isFetching}
      />

      <div className="deck-stage">
        {/* Peek cards (up to 3 behind) */}
        {openTasks.slice(1, 4).map((t, i) => (
          <div
            key={t.id}
            className="deck-peek"
            style={{
              transform: `translateY(${(i + 1) * 14}px) scale(${1 - (i + 1) * 0.04})`,
              opacity: Math.max(0.12, 0.7 - (i + 1) * 0.2),
              zIndex: 10 - (i + 1),
            }}
          />
        ))}

        {current ? (
          <div key={current.id} className="deck-active">
            <UniversalCard
              task={current}
              exiting={exiting}
              onAction={handleAction}
              onLaunch={handleLaunch}
              onSnooze={handleSnooze}
              onContinue={handleContinue}
              popoverRequest={popoverRequest}
              onPopoverConsumed={clearPopoverRequest}
            />
          </div>
        ) : (
          <EmptyDeck hasAny={(tasks || []).length > 0} />
        )}
      </div>
    </div>
  );
}

export default DeckTab;
