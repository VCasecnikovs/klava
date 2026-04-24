import { useState } from 'react';
import { esc } from '@/lib/utils';
import { showToast } from '@/components/shared/Toast';

interface TaskMark {
  action: 'done' | 'postpone' | 'cancel' | null;
  title: string;
  note: string;
}

interface Props {
  marks: Record<string, TaskMark>;
  onRemove: (id: string) => void;
  onClearAll: () => void;
  onSetAction: (id: string, action: 'done' | 'postpone' | 'cancel') => void;
  onSetNote: (id: string, note: string) => void;
}

function formatTaskText(entries: [string, TaskMark][]): string {
  const today = new Date().toISOString().slice(0, 10);
  const actionMap: Record<string, string> = { done: 'DONE', postpone: 'POSTPONE', cancel: 'CANCEL' };

  let text = `/tasks\nTASK UPDATES (${today}):\n\n`;
  for (const [taskId, m] of entries) {
    if (m.action) {
      text += `- ${m.title} [${actionMap[m.action]}] (id:${taskId})\n`;
    } else {
      text += `- ${m.title} (id:${taskId})\n`;
    }
    if (m.note) text += `  Note: ${m.note}\n`;
  }

  text += `\n---\nExecute via task-management skill (gog CLI). Task ID format: gtask_LISTID_TASKID.\n`;
  text += `- [DONE]     → gog tasks done {listId} {taskId} -a {email}\n`;
  text += `- [CANCEL]   → gog tasks update {listId} {taskId} -a {email} --title "[CANCELLED] {title}" && gog tasks done {listId} {taskId} -a {email}\n`;
  text += `- [POSTPONE] → gog tasks update {listId} {taskId} -a {email} --due YYYY-MM-DD\n`;
  text += `Then handle Notes intelligently: Note = instruction for what action to take (rename, update Obsidian, create follow-up task, find info, etc.) - sometimes it's just "add this to the note", sometimes it's a real action. Execute every Note, report what you DID.`;

  return text;
}

export function TCPanel({ marks, onRemove, onClearAll, onSetAction, onSetNote }: Props) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const entries = Object.entries(marks);
  const count = entries.length;

  const handleSendToSession = () => {
    if (entries.length === 0) return;
    const text = formatTaskText(entries);
    // Open chat panel if collapsed
    window.dispatchEvent(new CustomEvent('chat:open'));
    // Create new session and send message
    window.dispatchEvent(new CustomEvent('chat:new-session', { detail: { text } }));
    showToast(`Sending ${entries.length} changes to new session...`);
  };

  if (count === 0) return null;

  return (
    <>
      {/* FAB */}
      <div
        className="tc-fab"
        onClick={() => setPanelOpen(prev => !prev)}
      >
        <span>Changes</span>
        <span className="tc-fab-count">{count}</span>
      </div>

      {/* Panel */}
      {panelOpen && (
        <div className="tc-panel tc-visible">
          <div className="tc-panel-head">
            <span>Task Changes</span>
            <span className="tc-panel-count">{count}</span>
            <div style={{ flex: 1 }} />
            <button className="tc-panel-close" onClick={() => setPanelOpen(false)}>&times;</button>
          </div>
          <div className="tc-panel-list">
            {entries.length === 0 ? (
              <div className="tc-panel-empty">No changes yet. Mark tasks as done, postpone, or cancel.</div>
            ) : (
              entries.map(([id, m]) => {
                const badgeClass = m.action ? 'tc-badge-' + m.action : 'tc-badge-note';
                const badgeText = m.action === 'done' ? 'DONE' : m.action === 'postpone' ? '+1 WEEK' : m.action === 'cancel' ? 'CANCEL' : 'NOTE';
                return (
                  <div className="tc-panel-item" key={id} data-tc-id={id}>
                    <span className={`tc-panel-badge ${badgeClass}`}>{badgeText}</span>
                    <div className="tc-panel-body">
                      <div className="tc-panel-title">{esc(m.title || id)}</div>
                      {m.note && <div className="tc-panel-note">{esc(m.note)}</div>}
                      {editingId === id && (
                        <div className="tc-edit-wrap">
                          <textarea
                            className="tc-edit-area"
                            rows={2}
                            placeholder="Action to take (or just info to add)..."
                            defaultValue={m.note || ''}
                            autoFocus
                            id="tc-edit-ta"
                          />
                          <div className="tc-action-btns">
                            {(['done', 'postpone', 'cancel'] as const).map(a => (
                              <button
                                key={a}
                                className={`tc-action-btn${m.action === a ? ' active' : ''}`}
                                onClick={() => onSetAction(id, a)}
                              >
                                {a === 'done' ? 'Done' : a === 'postpone' ? '+1 Week' : 'Cancel'}
                              </button>
                            ))}
                            <button
                              className="tc-action-btn"
                              style={{ borderColor: 'var(--green)', color: 'var(--green)' }}
                              onClick={() => {
                                const ta = document.getElementById('tc-edit-ta') as HTMLTextAreaElement | null;
                                if (ta) onSetNote(id, ta.value);
                                setEditingId(null);
                              }}
                            >Save</button>
                          </div>
                        </div>
                      )}
                    </div>
                    <div className="tc-panel-btns">
                      <button className="tc-panel-btn" onClick={() => setEditingId(editingId === id ? null : id)}>Edit</button>
                      <button className="tc-panel-btn tc-panel-btn-del" onClick={() => onRemove(id)}>Del</button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          <div className="tc-panel-foot">
            <button className="tc-panel-copy" onClick={handleSendToSession}>Send to Session</button>
            <button className="tc-panel-clear" onClick={onClearAll}>Clear All</button>
          </div>
        </div>
      )}
    </>
  );
}
