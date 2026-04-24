import { useState, useMemo } from 'react';
import { useFiles, useFileMd } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { marked } from 'marked';
import type { MdLibraryEntry } from '@/api/types';

type ActiveFile = 'claude_md' | 'memory_md' | 'today' | 'yesterday' | string;

// Extended type for API response which may have extra fields
type FilesDataExt = {
  claude_md: { content: string; lines: number; modified?: string; modified_ago?: string };
  memory_md: { content: string; lines: number; modified?: string };
  today: string;
  yesterday: string;
  daily_notes: Record<string, { content: string; lines: number; exists: boolean }>;
  total_notes?: number;
  md_library?: MdLibraryEntry[];
};

// Library paths are tagged so we can distinguish them from the built-in views.
const LIB_PREFIX = 'lib:';

export function FilesTab() {
  const [activeFile, setActiveFile] = useState<ActiveFile>('claude_md');
  const [customDate, setCustomDate] = useState<string>('');
  const [libFilter, setLibFilter] = useState<string>('');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // Fetch with custom date if needed
  const fetchDate = customDate || undefined;
  const { data: rawData } = useFiles(fetchDate, true);
  const data = rawData as unknown as FilesDataExt | undefined;

  // Library file fetch (only when a library item is active)
  const activeLibPath = activeFile.startsWith(LIB_PREFIX)
    ? activeFile.slice(LIB_PREFIX.length)
    : null;
  const { data: libFile, isLoading: libLoading } = useFileMd(activeLibPath, !!activeLibPath);

  // Compute content based on active file (before any early return to keep hooks order stable)
  const { content, title } = useMemo(() => {
    if (!data) return { content: '', title: '' };
    const todayDate = data.today || '';

    if (activeFile === 'claude_md') {
      return { content: data.claude_md?.content || '', title: 'CLAUDE.md' };
    } else if (activeFile === 'memory_md') {
      return { content: data.memory_md?.content || '', title: 'MEMORY.md' };
    } else if (activeFile === 'today') {
      const note = data.daily_notes?.[todayDate];
      const c = note?.exists ? note.content : '';
      return { content: c || '*No daily note for today yet.*', title: `Daily Note: ${todayDate}` };
    } else if (activeFile === 'yesterday') {
      const note = data.daily_notes?.[data.yesterday];
      const c = note?.exists ? note.content : '';
      return { content: c || '*No daily note for yesterday.*', title: `Daily Note: ${data.yesterday}` };
    } else if (activeFile.match(/^\d{4}-\d{2}-\d{2}$/)) {
      const note = data.daily_notes?.[activeFile];
      const c = note?.exists ? note.content : '';
      return { content: c || '*No daily note for this date.*', title: `Daily Note: ${activeFile}` };
    } else if (activeLibPath) {
      if (libLoading) return { content: '*Loading...*', title: activeLibPath };
      const c = libFile?.content ?? '';
      return { content: c || '*No content.*', title: activeLibPath };
    }
    return { content: '', title: '' };
  }, [data, activeFile, activeLibPath, libFile, libLoading]);

  // Render markdown - always called (hooks must be unconditional)
  const renderedHtml = useMemo(() => {
    if (!content) return '';
    try {
      return marked.parse(content) as string;
    } catch {
      return `<pre>${content}</pre>`;
    }
  }, [content]);

  // Group library entries by category with optional text filter
  const grouped = useMemo(() => {
    const lib = data?.md_library ?? [];
    const q = libFilter.trim().toLowerCase();
    const filtered = q
      ? lib.filter(e => e.label.toLowerCase().includes(q) || e.path.toLowerCase().includes(q))
      : lib;
    const bucket: Record<string, MdLibraryEntry[]> = {};
    for (const e of filtered) {
      (bucket[e.category] = bucket[e.category] ?? []).push(e);
    }
    return bucket;
  }, [data?.md_library, libFilter]);

  if (!data) return <div className="empty">Loading files...</div>;

  const todayDate = data.today || '';
  const todayNote = data.daily_notes?.[todayDate] || { lines: 0, exists: false, content: '' };
  const libraryCount = data.md_library?.length ?? 0;

  const fileButtons: { file: ActiveFile; label: string; className: string }[] = [
    { file: 'claude_md', label: 'CLAUDE.md', className: 'file-btn claude-md' },
    { file: 'today', label: 'Today', className: 'file-btn daily' },
    { file: 'yesterday', label: 'Yesterday', className: 'file-btn daily' },
    { file: 'memory_md', label: 'MEMORY.md', className: 'file-btn memory-md' },
  ];

  // Category order: Skills, Docs, Tasks, Gateway, Changelog, then anything else alphabetically
  const categoryOrder = ['Skills', 'Docs', 'Tasks', 'Gateway', 'Changelog'];
  const categories = Object.keys(grouped).sort((a, b) => {
    const ai = categoryOrder.indexOf(a);
    const bi = categoryOrder.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  return (
    <>
      <KPIRow kpis={[
        { val: data.claude_md?.lines || 0, label: 'CLAUDE.md Lines', color: 'var(--claude-md)' },
        { val: todayNote.lines || 0, label: "Today's Note", color: todayNote.exists ? 'var(--learning)' : 'var(--text-muted)' },
        { val: data.total_notes || 0, label: 'Total Notes' },
        { val: libraryCount, label: 'Library Files' },
        {
          val: data.claude_md?.modified_ago || 'never',
          label: 'Last Modified',
          color: 'var(--text-secondary)'
        },
      ]} />

      <div className="files-selector">
        {fileButtons.map(fb => (
          <button
            key={fb.file}
            className={`${fb.className}${activeFile === fb.file ? ' active' : ''}`}
            onClick={() => { setActiveFile(fb.file); setCustomDate(''); }}
          >
            {fb.label}
          </button>
        ))}
        <input
          type="date"
          className="files-date-picker"
          title="Pick a date"
          value={customDate}
          onChange={e => {
            const date = e.target.value;
            if (!date) return;
            setActiveFile(date);
            setCustomDate(date);
          }}
        />
      </div>

      <div className="files-layout">
        <aside className="files-library">
          <div className="files-library-header">
            <span className="files-library-title">Library</span>
            <span className="files-library-count">{libraryCount}</span>
          </div>
          <input
            type="text"
            className="files-library-filter"
            placeholder="Filter…"
            value={libFilter}
            onChange={e => setLibFilter(e.target.value)}
          />
          <div className="files-library-list">
            {categories.length === 0 ? (
              <div className="empty" style={{ padding: '8px' }}>No matches</div>
            ) : (
              categories.map(cat => {
                const items = grouped[cat];
                const isCollapsed = !!collapsed[cat];
                return (
                  <div key={cat} className="files-library-group">
                    <button
                      className="files-library-group-header"
                      onClick={() => setCollapsed(c => ({ ...c, [cat]: !c[cat] }))}
                    >
                      <span>{isCollapsed ? '▸' : '▾'} {cat}</span>
                      <span className="files-library-group-count">{items.length}</span>
                    </button>
                    {!isCollapsed && (
                      <ul className="files-library-items">
                        {items.map(entry => {
                          const id = LIB_PREFIX + entry.path;
                          const active = activeFile === id;
                          return (
                            <li key={entry.path}>
                              <button
                                className={`files-library-item${active ? ' active' : ''}`}
                                title={entry.path}
                                onClick={() => { setActiveFile(id); setCustomDate(''); }}
                              >
                                <span className="files-library-label">{entry.label}</span>
                                {entry.modified_ago && (
                                  <span className="files-library-meta">{entry.modified_ago}</span>
                                )}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </aside>

        <div className="files-content">
          {activeLibPath && (
            <div className="files-content-breadcrumb">{title}</div>
          )}
          {!content ? (
            <div className="empty">No content</div>
          ) : (
            <div dangerouslySetInnerHTML={{ __html: renderedHtml }} />
          )}
        </div>
      </div>
    </>
  );
}
