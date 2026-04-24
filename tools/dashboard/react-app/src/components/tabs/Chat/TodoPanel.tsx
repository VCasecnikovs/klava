import { useChatContext } from '@/context/ChatContext';
import { esc } from '@/lib/utils';

export function TodoPanel() {
  const { state, dispatch } = useChatContext();
  const { todos, todosCollapsed } = state;

  if (!todos || todos.length === 0) return null;

  const done = todos.filter(t => t.status === 'completed').length;
  const total = todos.length;
  const allDone = done === total;

  // Find in-progress task for collapsed view
  const activeTask = todos.find(t => t.status === 'in_progress');

  return (
    <div className={`chat-todo-panel${allDone ? ' chat-todo-panel-done' : ''}`}>
      <div
        className="chat-todo-panel-header"
        onClick={() => dispatch({ type: 'TOGGLE_TODOS_COLLAPSED' })}
      >
        <span className={`chat-todo-panel-arrow${todosCollapsed ? '' : ' expanded'}`}>&#9654;</span>
        <span className="chat-todo-panel-title">Tasks</span>
        <span className="chat-todo-panel-count">{done}/{total}</span>
        {todosCollapsed && activeTask && (
          <span className="chat-todo-panel-active">
            {esc(activeTask.activeForm || activeTask.content || '')}
          </span>
        )}
        {/* Progress bar */}
        <div className="chat-todo-panel-progress">
          <div
            className="chat-todo-panel-progress-fill"
            style={{ width: `${total > 0 ? (done / total) * 100 : 0}%` }}
          />
        </div>
      </div>
      {!todosCollapsed && (
        <div className="chat-todo-panel-list">
          {todos.map((t, i) => {
            const st = t.status || 'pending';
            return (
              <div key={i} className={`chat-todo-panel-item ${st}`}>
                <span className={`chat-todo-panel-check ${st}`}>
                  {st === 'completed' ? '\u2713' : st === 'in_progress' ? '\u25B6' : ''}
                </span>
                <span className={`chat-todo-panel-text${st === 'completed' ? ' done' : ''}`}>
                  {st === 'in_progress' ? (t.activeForm || t.content || '') : (t.content || '')}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
