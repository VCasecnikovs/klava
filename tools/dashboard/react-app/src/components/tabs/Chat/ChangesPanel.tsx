import { useState, useMemo, useCallback, useRef } from 'react';
import { type Block } from '@/context/ChatContext';

// --- Types ---

interface FileChange {
  path: string;
  filename: string;
  dir: string;
  kind: 'edit' | 'write' | 'notebook';
  edits: Array<{ tool: string; input: Record<string, unknown> }>;
}

interface TodoSnapshot {
  todos: Array<{ status?: string; content?: string }>;
}

type Filter = 'all' | 'edits' | 'new' | 'tasks';

// --- Extract mutation blocks ---

const MUTATION_TOOLS = new Set(['Edit', 'Write', 'NotebookEdit', 'TodoWrite']);

export function extractChanges(blocks: Block[]) {
  const files = new Map<string, FileChange>();
  const todoSnapshots: TodoSnapshot[] = [];

  const process = (b: Block) => {
    if (b.type !== 'tool_use' || !b.tool || !MUTATION_TOOLS.has(b.tool)) return;
    const input = (b.input as Record<string, unknown>) || {};

    if (b.tool === 'Edit' || b.tool === 'Write' || b.tool === 'NotebookEdit') {
      const path = (input.file_path as string) || (input.notebook_path as string) || '';
      if (!path) return;
      const filename = path.split('/').pop() || '';
      const dir = path.substring(0, path.length - filename.length);
      const kind = b.tool === 'Write' ? 'write' as const : b.tool === 'NotebookEdit' ? 'notebook' as const : 'edit' as const;

      if (!files.has(path)) {
        files.set(path, { path, filename, dir, kind, edits: [] });
      }
      const f = files.get(path)!;
      if (kind === 'write' && f.edits.length === 0) f.kind = 'write';
      f.edits.push({ tool: b.tool, input });
    }

    if (b.tool === 'TodoWrite') {
      todoSnapshots.push({ todos: Array.isArray(input.todos) ? input.todos as TodoSnapshot['todos'] : [] });
    }
  };

  for (const block of blocks) {
    process(block);
    if (block.type === 'tool_group' && block.tools) {
      for (const t of block.tools) process(t);
    }
  }

  return { files, todoSnapshots };
}

// --- Helpers ---

function shortenDir(dir: string): string {
  return dir.replace(/^\/Users\/[^/]+\//, '~/').replace(/\/$/, '') || '~';
}

const PANEL_MIN_W = 360;
const PANEL_MAX_W = 900;
const PANEL_DEFAULT_W = 480;

// --- Component ---

export function ChangesPanel({ blocks, open, onClose }: {
  blocks: Block[];
  open: boolean;
  onClose: () => void;
}) {
  const [filter, setFilter] = useState<Filter>('all');
  // Track collapsed files (diffs are OPEN by default)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [width, setWidth] = useState(() => {
    try {
      const saved = parseInt(localStorage.getItem('chat-changes-width') || '', 10);
      if (saved >= PANEL_MIN_W && saved <= PANEL_MAX_W) return saved;
    } catch { /* */ }
    return PANEL_DEFAULT_W;
  });

  const { files, todoSnapshots } = useMemo(() => extractChanges(blocks), [blocks]);
  const fileList = useMemo(() => Array.from(files.values()), [files]);

  const editCount = fileList.filter(f => f.kind === 'edit').length;
  const newCount = fileList.filter(f => f.kind === 'write' || f.kind === 'notebook').length;
  const hasTodos = todoSnapshots.length > 0;

  const filtered = useMemo(() => {
    if (filter === 'edits') return fileList.filter(f => f.kind === 'edit');
    if (filter === 'new') return fileList.filter(f => f.kind === 'write' || f.kind === 'notebook');
    if (filter === 'tasks') return [];
    return fileList;
  }, [fileList, filter]);

  // Group by directory
  const dirGroups = useMemo(() => {
    const groups = new Map<string, FileChange[]>();
    for (const f of filtered) {
      const d = f.dir || '/';
      if (!groups.has(d)) groups.set(d, []);
      groups.get(d)!.push(f);
    }
    return groups;
  }, [filtered]);

  const toggleFile = (path: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  };

  // Resize drag
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startW: width };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      // Drag left = wider (panel is on the right)
      const newW = Math.max(PANEL_MIN_W, Math.min(PANEL_MAX_W, dragRef.current.startW - (ev.clientX - dragRef.current.startX)));
      setWidth(newW);
    };
    const onUp = () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      if (dragRef.current) {
        const finalW = Math.max(PANEL_MIN_W, Math.min(PANEL_MAX_W, dragRef.current.startW - (0)));
        try { localStorage.setItem('chat-changes-width', String(finalW)); } catch { /* */ }
      }
      dragRef.current = null;
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [width]);

  // Save width on change
  const widthRef = useRef(width);
  widthRef.current = width;
  const saveWidth = useCallback(() => {
    try { localStorage.setItem('chat-changes-width', String(widthRef.current)); } catch { /* */ }
  }, []);

  if (!open) return null;

  const showTodos = (filter === 'all' || filter === 'tasks') && hasTodos;
  const latestTodos = hasTodos ? todoSnapshots[todoSnapshots.length - 1] : null;

  return (
    <div className="chat-changes-panel" style={{ width }}>
      {/* Resize handle on left edge */}
      <div
        className="chat-changes-resize"
        onMouseDown={(e) => { handleResizeStart(e); }}
        onMouseUp={saveWidth}
      />

      <div className="chat-changes-panel-head">
        <span className="chat-changes-panel-title">Changes</span>
        <span className="chat-changes-panel-total">{fileList.length} file{fileList.length !== 1 ? 's' : ''}</span>
        <button className="chat-changes-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Filters */}
      <div className="chat-changes-filters">
        {([
          ['all', 'All', fileList.length + (hasTodos ? 1 : 0)],
          ['edits', 'Edits', editCount],
          ['new', 'New', newCount],
          ['tasks', 'Tasks', hasTodos ? 1 : 0],
        ] as [Filter, string, number][]).map(([key, label, count]) => (
          count > 0 || key === 'all' ? (
            <button
              key={key}
              className={`chat-changes-chip${filter === key ? ' active' : ''}`}
              onClick={() => setFilter(key)}
            >
              {label}
              {count > 0 && <span className="chat-changes-chip-n">{count}</span>}
            </button>
          ) : null
        ))}
      </div>

      {/* File list - diffs OPEN by default */}
      <div className="chat-changes-body">
        {filtered.length === 0 && !showTodos && (
          <div className="chat-changes-empty">No changes match filter</div>
        )}

        {Array.from(dirGroups).map(([dir, dirFiles]) => (
          <div key={dir} className="chat-changes-dir">
            <div className="chat-changes-dir-label">{shortenDir(dir)}</div>
            {dirFiles.map(file => {
              const isCollapsed = collapsed.has(file.path);
              const hasEdits = file.edits.length > 0 && (file.kind === 'edit' || file.edits.some(e => e.tool === 'Edit'));
              return (
                <div key={file.path} className="chat-changes-file-block">
                  <div
                    className="chat-changes-file"
                    onClick={() => toggleFile(file.path)}
                  >
                    <span className={`chat-changes-arrow${isCollapsed ? '' : ' open'}`}>&#9654;</span>
                    <span className={`chat-changes-kind ${file.kind}`}>
                      {file.kind === 'write' || file.kind === 'notebook' ? '+' : '~'}
                    </span>
                    <span className="chat-changes-fname">{file.filename}</span>
                    {file.edits.length > 1 && (
                      <span className="chat-changes-edit-n">&times;{file.edits.length}</span>
                    )}
                  </div>

                  {/* Diffs shown by default */}
                  {!isCollapsed && (
                    <div className="chat-changes-diffs">
                      {file.edits.map((edit, i) => (
                        <div key={i} className="chat-changes-diff">
                          {edit.tool === 'Edit' ? (
                            <DiffBlock input={edit.input} />
                          ) : edit.tool === 'Write' ? (
                            <WriteBlock input={edit.input} />
                          ) : (
                            <div className="chat-changes-diff-meta">Notebook cell edited</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}

        {/* Todo section */}
        {showTodos && latestTodos && (
          <div className="chat-changes-dir">
            <div className="chat-changes-dir-label">Tasks</div>
            <div className="chat-changes-todos">
              {latestTodos.todos.map((t, i) => {
                const st = t.status || 'pending';
                return (
                  <div key={i} className={`chat-changes-todo ${st}`}>
                    <span className={`chat-changes-todo-icon ${st}`}>
                      {st === 'completed' ? '\u2713' : st === 'in_progress' ? '\u25B6' : '\u25CB'}
                    </span>
                    <span>{t.content || ''}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Diff block ---

function DiffBlock({ input }: { input: Record<string, unknown> }) {
  const oldStr = (input.old_string as string) || '';
  const newStr = (input.new_string as string) || '';

  return (
    <div className="chat-changes-diff-code">
      {oldStr.split('\n').map((line, i) => (
        <div key={`d${i}`} className="chat-changes-diff-del">
          <span className="chat-changes-diff-sign">-</span>
          <span>{line || '\u00A0'}</span>
        </div>
      ))}
      {newStr.split('\n').map((line, i) => (
        <div key={`a${i}`} className="chat-changes-diff-add">
          <span className="chat-changes-diff-sign">+</span>
          <span>{line || '\u00A0'}</span>
        </div>
      ))}
    </div>
  );
}

// --- Write block (show preview of content) ---

function WriteBlock({ input }: { input: Record<string, unknown> }) {
  const content = (input.content as string) || '';

  return (
    <div className="chat-changes-diff-code">
      {content.split('\n').map((line, i) => (
        <div key={i} className="chat-changes-diff-add">
          <span className="chat-changes-diff-sign">+</span>
          <span>{line || '\u00A0'}</span>
        </div>
      ))}
    </div>
  );
}
