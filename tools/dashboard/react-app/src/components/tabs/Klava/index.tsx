import { useState, useMemo, useEffect, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useKlavaTasks } from '@/api/queries';
import { api, type KlavaTask } from '@/api/client';
import { KPIRow } from '@/components/shared/KPIRow';
import { esc } from '@/lib/utils';
import { useSocket } from '@/hooks/useSocket';

// ─── Status helpers ──────────────────────────────────────────────

function statusIcon(status: string, hasQuestion: boolean): string {
  if (hasQuestion) return '\u2753'; // question mark
  switch (status) {
    case 'running': return '\u25B6';
    case 'done': return '\u2714';
    case 'failed': return '\u2718';
    default: return '\u25CB';
  }
}

function statusColor(status: string, hasQuestion: boolean): string {
  if (hasQuestion) return 'var(--yellow)';
  switch (status) {
    case 'running': return 'var(--blue)';
    case 'done': return 'var(--green)';
    case 'failed': return 'var(--red)';
    default: return 'var(--text-muted)';
  }
}

function priorityBadge(priority: string) {
  const color = priority === 'high' ? 'var(--red)' : priority === 'medium' ? 'var(--yellow)' : 'var(--text-muted)';
  return <span className="klava-badge" style={{ color }}>{priority.toUpperCase()}</span>;
}

function timeAgo(dateStr: string | null): string {
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

// ─── Create Task Form ────────────────────────────────────────────

function CreateForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [priority, setPriority] = useState('medium');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!title.trim()) return;
    setLoading(true);
    try {
      await api.klavaCreate(title.trim(), body.trim(), priority);
      setTitle('');
      setBody('');
      setPriority('medium');
      setOpen(false);
      onCreated();
    } catch (e) {
      console.error('Failed to create task:', e);
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button className="klava-create-btn" onClick={() => setOpen(true)}>
        + New Task
      </button>
    );
  }

  return (
    <div className="klava-create-form">
      <input
        className="klava-input"
        placeholder="Task title..."
        value={title}
        onChange={e => setTitle(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
        autoFocus
      />
      <textarea
        className="klava-textarea"
        placeholder="Details (optional)..."
        value={body}
        onChange={e => setBody(e.target.value)}
        rows={3}
      />
      <div className="klava-form-row">
        <select
          className="klava-select"
          value={priority}
          onChange={e => setPriority(e.target.value)}
        >
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <div className="klava-form-actions">
          <button className="klava-btn klava-btn-cancel" onClick={() => setOpen(false)}>Cancel</button>
          <button className="klava-btn klava-btn-submit" onClick={handleSubmit} disabled={loading || !title.trim()}>
            {loading ? 'Creating...' : 'Create & Run'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Question Card ───────────────────────────────────────────────

function QuestionCard({ task, onAnswered }: { task: KlavaTask; onAnswered: () => void }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const questions = task.questions || [];

  const handleSubmit = async () => {
    if (Object.keys(answers).length === 0) return;
    setSubmitting(true);
    try {
      await api.klavaAnswer(task.id, answers);
      setAnswers({});
      onAnswered();
    } catch (e) {
      console.error('Failed to answer:', e);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="klava-question">
      <div className="klava-question-header">Your assistant needs input:</div>
      {questions.map((q, i) => (
        <div key={i} className="klava-question-item">
          <div className="klava-question-text">{q.question}</div>
          {q.options && q.options.length > 0 ? (
            <div className="klava-question-options">
              {q.options.map((opt, j) => (
                <button
                  key={j}
                  className={`klava-option-btn ${answers[q.question] === opt.value ? 'selected' : ''}`}
                  onClick={() => setAnswers(prev => ({ ...prev, [q.question]: opt.value }))}
                >
                  {opt.label || opt.value}
                </button>
              ))}
            </div>
          ) : (
            <input
              className="klava-input"
              placeholder="Type your answer..."
              value={answers[q.question] || ''}
              onChange={e => setAnswers(prev => ({ ...prev, [q.question]: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
            />
          )}
        </div>
      ))}
      <button
        className="klava-btn klava-btn-submit"
        onClick={handleSubmit}
        disabled={submitting || Object.keys(answers).length === 0}
      >
        {submitting ? 'Sending...' : 'Answer'}
      </button>
    </div>
  );
}

// ─── Task Card ───────────────────────────────────────────────────

function TaskCard({ task, onRefresh }: { task: KlavaTask; onRefresh: () => void }) {
  const status = task.status;
  const hasQ = task.has_question;
  const [expanded, setExpanded] = useState(false);
  const hasResult = !!(task.result && task.result.trim());
  const isDone = status === 'done' || status === 'failed';

  const handleOpenChat = () => {
    if (task.session_id) {
      window.dispatchEvent(new CustomEvent('chat:resume-session', {
        detail: { sessionId: task.session_id },
      }));
    }
  };

  const handleLaunch = async () => {
    try {
      await api.klavaLaunch(task.id);
      onRefresh();
    } catch (e) {
      console.error('Failed to launch:', e);
    }
  };

  return (
    <div className={`klava-card klava-card-${hasQ ? 'question' : status}`}>
      <div className="klava-card-status" style={{ color: statusColor(status, hasQ) }}>
        {statusIcon(status, hasQ)}
      </div>
      <div className="klava-card-main">
        <div className="klava-card-header">
          <span className="klava-card-title">{esc(task.title)}</span>
          <div className="klava-card-badges">
            {priorityBadge(task.priority)}
            {task.source && task.source !== 'dashboard' && task.source !== 'manual' && (
              <span className="klava-badge klava-badge-source">{task.source}</span>
            )}
          </div>
        </div>

        {/* Body preview: only for non-completed, non-question tasks */}
        {task.body && !hasQ && !isDone && (
          <div className="klava-card-body">{esc(task.body.slice(0, 300))}</div>
        )}

        {hasQ && <QuestionCard task={task} onAnswered={onRefresh} />}

        {/* Result for completed tasks */}
        {isDone && hasResult && (
          <div className="klava-result">
            <button
              className="klava-result-toggle"
              onClick={() => setExpanded(v => !v)}
            >
              {expanded ? '\u25BC' : '\u25B6'} Result
            </button>
            {expanded && (
              <div className="klava-result-body">{task.result}</div>
            )}
            {!expanded && (
              <div className="klava-result-preview">
                {task.result.slice(0, 150)}{task.result.length > 150 ? '...' : ''}
              </div>
            )}
          </div>
        )}

        {/* Done but no result captured */}
        {isDone && !hasResult && task.body && (
          <div className="klava-card-body">{esc(task.body.slice(0, 200))}</div>
        )}

        <div className="klava-card-footer">
          {status === 'running' && !hasQ && (
            <span className="klava-card-info klava-running-indicator">
              <span className="klava-pulse" /> Working {task.started_at ? timeAgo(task.started_at) : ''}
            </span>
          )}
          {status === 'running' && hasQ && (
            <span className="klava-card-info" style={{ color: 'var(--yellow)' }}>
              Waiting for your answer
            </span>
          )}
          {status === 'failed' && (
            <span className="klava-card-info" style={{ color: 'var(--red)' }}>Failed</span>
          )}
          {status === 'done' && (
            <span className="klava-card-info" style={{ color: 'var(--green)' }}>
              Done {task.completed_at ? timeAgo(task.completed_at) : ''}
            </span>
          )}
          {status === 'pending' && (
            <span className="klava-card-info">
              Pending
              <button className="klava-btn-inline" onClick={handleLaunch}>Launch</button>
            </span>
          )}
          <div className="klava-card-actions">
            {task.session_id && (
              <button className="klava-btn-inline" onClick={handleOpenChat} title="Open in Chat">
                Open in Chat
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Tab ────────────────────────────────────────────────────

export function KlavaTab() {
  const { data: tasks, refetch } = useKlavaTasks(true);
  const queryClient = useQueryClient();
  const socket = useSocket();

  // Listen for Socket.IO events
  useEffect(() => {
    if (!socket) return;

    const onLaunched = () => refetch();
    const onQuestion = () => refetch();
    const onDone = () => refetch();

    socket.on('klava_launched', onLaunched);
    socket.on('klava_question', onQuestion);
    socket.on('klava_done', onDone);

    return () => {
      socket.off('klava_launched', onLaunched);
      socket.off('klava_question', onQuestion);
      socket.off('klava_done', onDone);
    };
  }, [socket, refetch]);

  // Subscribe to running task sessions for live updates
  useEffect(() => {
    if (!socket || !tasks) return;
    const runningTabIds = tasks
      .filter(t => t.status === 'running' && t.tab_id)
      .map(t => t.tab_id!);
    if (runningTabIds.length > 0) {
      socket.emit('klava_subscribe', { tab_ids: runningTabIds });
    }
  }, [socket, tasks]);

  const handleRefresh = useCallback(() => {
    refetch();
  }, [refetch]);

  // Separate tasks by status
  const { active, completed } = useMemo(() => {
    if (!tasks) return { active: [], completed: [] };
    const active = tasks.filter(t => t.status === 'pending' || t.status === 'running');
    const completed = tasks.filter(t => t.status === 'done' || t.status === 'failed');
    // Questions first, then running, then pending
    active.sort((a, b) => {
      if (a.has_question && !b.has_question) return -1;
      if (!a.has_question && b.has_question) return 1;
      if (a.status === 'running' && b.status !== 'running') return -1;
      if (a.status !== 'running' && b.status === 'running') return 1;
      return 0;
    });
    // Most recent completed first
    completed.sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));
    return { active, completed: completed.slice(0, 10) };
  }, [tasks]);

  const kpis = useMemo(() => {
    if (!tasks) return [];
    const pending = tasks.filter(t => t.status === 'pending').length;
    const running = tasks.filter(t => t.status === 'running').length;
    const questions = tasks.filter(t => t.has_question).length;
    return [
      { val: active.length, label: 'Active', color: 'var(--text)' },
      { val: questions, label: 'Questions', color: questions > 0 ? 'var(--yellow)' : 'var(--text-muted)' },
      { val: running, label: 'Running', color: running > 0 ? 'var(--blue)' : 'var(--text-muted)' },
      { val: pending, label: 'Pending', color: 'var(--text-muted)' },
    ];
  }, [tasks, active]);

  if (!tasks) return <div className="empty">Loading...</div>;

  return (
    <>
      <KPIRow kpis={kpis} />

      <div className="klava-toolbar">
        <CreateForm onCreated={handleRefresh} />
        <button className="tasks-action-btn refresh-btn-tasks" onClick={handleRefresh}>
          Refresh
        </button>
      </div>

      {active.length === 0 && completed.length === 0 ? (
        <div className="klava-empty">
          <div className="klava-empty-icon">{'\u2713'}</div>
          <div className="klava-empty-text">Queue empty</div>
          <div className="klava-empty-hint">
            Create a task above, or send items from Feed/Tasks tabs
          </div>
        </div>
      ) : (
        <div className="klava-queue">
          {active.map(task => (
            <TaskCard key={task.id} task={task} onRefresh={handleRefresh} />
          ))}

          {completed.length > 0 && (
            <>
              <div className="klava-section-header">Completed</div>
              {completed.map(task => (
                <TaskCard key={task.id} task={task} onRefresh={handleRefresh} />
              ))}
            </>
          )}
        </div>
      )}
    </>
  );
}
