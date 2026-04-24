import { useState } from 'react';
import { marked } from 'marked';
import { esc } from '@/lib/utils';

marked.setOptions({ breaks: true, gfm: true });

function formatTaskNotes(notes: string): string {
  const lines = notes.split('\n');
  const parts: string[] = [];
  let inDraft = false;
  let mdBuffer: string[] = [];

  const flushMd = () => {
    if (mdBuffer.length === 0) return;
    const raw = mdBuffer.join('\n');
    mdBuffer = [];
    const html = marked.parse(raw);
    if (typeof html === 'string') parts.push(html);
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^Draft\s*\(/i.test(trimmed) || /^Draft:/i.test(trimmed)) {
      flushMd();
      if (inDraft) parts.push('</div>');
      inDraft = true;
      parts.push(`<div class="task-notes-label">📝 ${esc(trimmed)}</div><div class="task-notes-draft">`);
      continue;
    }
    if (/^(Context|See|Source|Trigger|Channel):/i.test(trimmed)) {
      flushMd();
      if (inDraft) { parts.push('</div>'); inDraft = false; }
      parts.push(`<div class="task-notes-label">${esc(trimmed)}</div>`);
      continue;
    }
    mdBuffer.push(line);
  }
  flushMd();
  if (inDraft) parts.push('</div>');
  return parts.join('');
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TaskObj = any;

interface TaskMark {
  action: 'done' | 'postpone' | 'cancel' | null;
  title: string;
  note: string;
}

interface Props {
  task: TaskObj;
  mark?: TaskMark;
  onMark: (taskId: string, action: 'done' | 'postpone' | 'cancel', title: string) => void;
  onNoteChange: (taskId: string, note: string, title: string) => void;
}

export function TaskCard({ task, mark, onMark, onNoteChange }: Props) {
  // Auto-expand [REPLY] and [PREP] tasks so drafts are visible without clicking
  const hasReplyDraft = task.notes && /^\[REPLY\]|\[PREP\]/.test(task.raw_title || task.title || '');
  const [expanded, setExpanded] = useState(hasReplyDraft);

  const isKlava = task.list_name === 'klava';
  const klava = task.klava || {};

  const cardCls = ['task-card'];
  if (task.overdue) cardCls.push('overdue');
  if (task.is_today) cardCls.push('is-today');
  if (mark?.action) cardCls.push('marked-' + mark.action);
  if (expanded) cardCls.push('expanded');
  if (isKlava) cardCls.push('klava-task');
  if (isKlava && klava.status === 'running') cardCls.push('klava-running');

  const srcCls = task.source === 'github' ? 'gh' : isKlava ? 'kl' : 'gt';
  const titleCls = task.bold ? 'task-card-title bold' : 'task-card-title';

  const markLabel = mark?.action
    ? mark.action === 'done' ? 'DONE' : mark.action === 'postpone' ? '+1 WEEK' : 'CANCEL'
    : null;

  const taskTitle = task.raw_title || task.title;

  return (
    <div
      className={cardCls.join(' ')}
      data-task-id={task.id}
      onClick={() => setExpanded((prev: boolean) => !prev)}
    >
      <div className="task-card-header">
        <span className={`task-source ${srcCls}`}>{esc(task.source_label)}</span>
        {(task.tags || []).map((t: { name: string; color: string }, i: number) => (
          <span key={i} className={`task-tag ${esc(t.color)}`}>{esc(t.name)}</span>
        ))}
        {task.list_name === 'backlog' && <span className="task-tag gray">backlog</span>}
        {task.domain && task.domain !== 'personal' && (
          <span className={`task-tag domain-${task.domain}`}>{task.domain.toUpperCase()}</span>
        )}
        {(task.auto_tags || []).map((at: string, i: number) => (
          <span key={`at-${i}`} className={`task-tag auto-tag-${at}`}>{at}</span>
        ))}
        <span className={titleCls}>{esc(task.title)}</span>
        {task.days_info ? (
          <span className={`task-due${task.overdue ? ' overdue' : ''}`}>{esc(task.days_info)}</span>
        ) : task.due ? (
          <span className="task-due">{esc(task.due)}</span>
        ) : null}
        {markLabel && (
          <span className={`task-mark-label ${mark!.action}`}>{markLabel}</span>
        )}
      </div>
      <div className="task-card-body">
        {task.notes && <div className="task-notes" dangerouslySetInnerHTML={{ __html: formatTaskNotes(task.notes) }} />}
        {isKlava && klava.status === 'running' && klava.started_at && (
          <div className="klava-running-info">
            Running since {new Date(klava.started_at).toLocaleTimeString()}
            {klava.session_id && <span className="klava-session"> (session: {klava.session_id.slice(0, 8)}...)</span>}
          </div>
        )}
        {isKlava && klava.status === 'failed' && (
          <div className="klava-failed-info">Failed - check Feed for details</div>
        )}
        <div className="task-actions">
          <input
            type="text"
            className="task-note-input"
            placeholder="Action to take (or just info to add)..."
            value={mark?.note || ''}
            onClick={e => e.stopPropagation()}
            onChange={e => {
              e.stopPropagation();
              onNoteChange(task.id, e.target.value, taskTitle);
            }}
          />
          <button
            className={`task-btn done${mark?.action === 'done' ? ' active' : ''}`}
            onClick={e => { e.stopPropagation(); onMark(task.id, 'done', taskTitle); }}
          >Done</button>
          <button
            className={`task-btn postpone${mark?.action === 'postpone' ? ' active' : ''}`}
            onClick={e => { e.stopPropagation(); onMark(task.id, 'postpone', taskTitle); }}
          >+1 week</button>
          <button
            className={`task-btn skip${mark?.action === 'cancel' ? ' active' : ''}`}
            onClick={e => { e.stopPropagation(); onMark(task.id, 'cancel', taskTitle); }}
          >Cancel</button>
        </div>
      </div>
    </div>
  );
}
