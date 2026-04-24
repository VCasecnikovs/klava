import { useState } from 'react';
import { TaskCard } from './TaskCard';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TaskObj = any;

interface TaskMark {
  action: 'done' | 'postpone' | 'cancel' | null;
  title: string;
  note: string;
}

interface Props {
  group: {
    key: string;
    title: string;
    summary: string;
    count: number;
    task_ids: string[];
  };
  tasks: TaskObj[];
  marks: Record<string, TaskMark>;
  onMark: (taskId: string, action: 'done' | 'postpone' | 'cancel', title: string) => void;
  onNoteChange: (taskId: string, note: string, title: string) => void;
}

export function TaskGroupCard({ group, tasks, marks, onMark, onNoteChange }: Props) {
  const [expanded, setExpanded] = useState(false);

  const markedCount = tasks.filter(t => marks[t.id]?.action).length;
  const allMarkedDone = markedCount === tasks.length && tasks.every(t => marks[t.id]?.action === 'done');

  return (
    <div className={`task-group-card${expanded ? ' expanded' : ''}${allMarkedDone ? ' all-done' : ''}`}>
      <div className="task-group-header" onClick={() => setExpanded(prev => !prev)}>
        <span className="task-group-chevron">{expanded ? '\u25BE' : '\u25B8'}</span>
        <span className="task-group-title">{group.title}</span>
        <span className="task-group-count">{group.count}</span>
        {markedCount > 0 && (
          <span className="task-group-marked">{markedCount}/{tasks.length} marked</span>
        )}
      </div>
      <div className="task-group-summary">{group.summary}</div>
      {expanded && (
        <div className="task-group-tasks">
          {tasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              mark={marks[task.id]}
              onMark={onMark}
              onNoteChange={onNoteChange}
            />
          ))}
        </div>
      )}
      {!expanded && (
        <div className="task-group-actions">
          <button
            className="task-btn done"
            onClick={e => {
              e.stopPropagation();
              tasks.forEach(t => onMark(t.id, 'done', t.raw_title || t.title));
            }}
          >Mark all done</button>
          <button
            className="task-group-expand"
            onClick={e => { e.stopPropagation(); setExpanded(true); }}
          >Expand ({tasks.length})</button>
        </div>
      )}
    </div>
  );
}
