import { useRef, useCallback, useState, useEffect } from 'react';
import { useChatContext, type AttachedFile } from '@/context/ChatContext';
import { api } from '@/api/client';
import { uuid } from './uuid';
import { SpinnerBar } from './blocks/SpinnerBar';
import { PermissionToggle } from './blocks/PermissionToggle';
import { ContextUsage } from './blocks/ContextUsage';
import type { Skill } from '@/api/types';

const MODEL_OPTIONS = [
  { value: 'opus',        label: 'Opus 4.7' },
  { value: 'opus[1m]',    label: 'Opus 4.7 \u00b7 1M' },
  { value: 'sonnet',      label: 'Sonnet 4.6' },
  { value: 'sonnet[1m]',  label: 'Sonnet 4.6 \u00b7 1M' },
  { value: 'haiku',       label: 'Haiku 4.5' },
];

const EFFORT_OPTIONS = [
  { value: 'none',     label: 'None' },
  { value: 'low',      label: 'Low' },
  { value: 'medium',   label: 'Med' },
  { value: 'high',     label: 'High' },
  { value: 'max',      label: 'Max' },
  { value: 'adaptive', label: 'Adaptive' },
];

interface QuoteBlock {
  id: string;
  text: string;
  reply: string;
}

interface ChatInputProps {
  onSend: (text: string, files: AttachedFile[]) => boolean;
  onCancel: () => void;
}

export function ChatInput({ onSend, onCancel }: ChatInputProps) {
  const { state, dispatch, socketRef } = useChatContext();
  const { realtimeStatus, attachedFiles, model, effort } = state;
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [quotes, setQuotes] = useState<QuoteBlock[]>([]);
  const dragCounter = useRef(0);
  const [expanded, setExpanded] = useState(false);

  // --- Draft management (controlled textarea) ---
  const draftKey = state.claudeSessionId || state.tabId || '';
  const [localDraft, setLocalDraft] = useState('');
  const draftKeyRef = useRef(draftKey);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // True when user has typed but debounced save hasn't fired yet
  const localDirtyRef = useRef(false);
  // Set to true right after send to block one stale draft_sync from restoring old text
  const justSentRef = useRef(false);

  // Load draft when session changes
  useEffect(() => {
    if (draftKey !== draftKeyRef.current) {
      draftKeyRef.current = draftKey;
      localDirtyRef.current = false;
      setLocalDraft(draftKey ? (state.drafts[draftKey] || '') : '');
      // Reset textarea height
      if (inputRef.current) {
        inputRef.current.style.height = 'auto';
      }
    }
  }, [draftKey, state.drafts]);

  // Sync from server when draft_update arrives for current session
  // Skip if user has unsaved local changes (prevents chat_state_sync from
  // overwriting text mid-typing with a stale server value).
  // Also skip once right after send to block stale chat_state_sync race condition:
  // backend may broadcast state before clearing draft, causing a stale value to
  // arrive and restore the just-cleared input.
  useEffect(() => {
    if (localDirtyRef.current) return;
    if (justSentRef.current) { justSentRef.current = false; return; }
    if (draftKey && state.drafts[draftKey] !== undefined) {
      setLocalDraft(prev => {
        const server = state.drafts[draftKey] || '';
        return prev === server ? prev : server;
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.drafts[draftKey]]);

  // Debounced save to server
  const saveDraft = useCallback((text: string, key?: string) => {
    const k = key || draftKeyRef.current;
    if (!k) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      localDirtyRef.current = false;
      socketRef.current?.emit('draft_save', { session_id: k, text });
    }, 500);
  }, [socketRef]);

  // --- Skill autocomplete ---
  const [skills, setSkills] = useState<Skill[]>([]);
  const [showSkillMenu, setShowSkillMenu] = useState(false);
  const [skillFilter, setSkillFilter] = useState('');
  const [skillSelectedIdx, setSkillSelectedIdx] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  // Fetch skills on mount
  useEffect(() => {
    api.dashboard().then(data => {
      const invocable = (data.skill_inventory || []).filter(s => s.user_invocable);
      setSkills(invocable);
    }).catch(() => {});
  }, []);

  const filteredSkills = skills.filter(s =>
    s.name.toLowerCase().includes(skillFilter.toLowerCase()) ||
    (s.description || '').toLowerCase().includes(skillFilter.toLowerCase())
  );

  // Detect "/" at start of input or after whitespace
  const checkSlashTrigger = useCallback((val: string, pos: number) => {
    const before = val.substring(0, pos);
    const match = before.match(/(?:^|\s)(\/[\w-]*)$/);
    if (match) {
      const query = match[1].substring(1);
      setSkillFilter(query);
      setShowSkillMenu(true);
      setSkillSelectedIdx(0);
    } else {
      setShowSkillMenu(false);
    }
  }, []);

  // Insert selected skill into input
  const insertSkill = useCallback((skillName: string) => {
    const textarea = inputRef.current;
    if (!textarea) return;
    const pos = textarea.selectionStart;
    const before = localDraft.substring(0, pos);
    const after = localDraft.substring(pos);

    const replaced = before.replace(/(?:^|\s)(\/[\w-]*)$/, (m) => {
      const prefix = m.startsWith('/') ? '' : m[0];
      return prefix + '/' + skillName;
    });

    const newVal = replaced + after;
    setLocalDraft(newVal);
    saveDraft(newVal);
    setShowSkillMenu(false);

    requestAnimationFrame(() => {
      if (textarea) {
        const newPos = replaced.length;
        textarea.selectionStart = newPos;
        textarea.selectionEnd = newPos;
        textarea.focus();
      }
    });
  }, [localDraft, saveDraft]);

  // Scroll selected item into view
  useEffect(() => {
    if (showSkillMenu && menuRef.current) {
      const item = menuRef.current.children[skillSelectedIdx] as HTMLElement;
      if (item) item.scrollIntoView({ block: 'nearest' });
    }
  }, [skillSelectedIdx, showSkillMenu]);

  // Listen for quote events from QuotePopover
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail?.text;
      if (text) {
        setQuotes(prev => [...prev, { id: uuid(), text, reply: '' }]);
        requestAnimationFrame(() => {
          const fields = document.querySelectorAll<HTMLTextAreaElement>('.quote-reply-input');
          if (fields.length > 0) fields[fields.length - 1].focus();
        });
      }
    };
    window.addEventListener('chat:quote', handler);
    return () => window.removeEventListener('chat:quote', handler);
  }, []);

  // Listen for prefill events (from PlanReviewBlock "Request Changes")
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent).detail?.text;
      if (text && inputRef.current) {
        setLocalDraft(text);
        localDirtyRef.current = true;
        saveDraft(text);
        requestAnimationFrame(() => {
          if (inputRef.current) {
            inputRef.current.focus();
            inputRef.current.selectionStart = text.length;
            inputRef.current.selectionEnd = text.length;
          }
        });
      }
    };
    window.addEventListener('chat:prefill-input', handler);
    return () => window.removeEventListener('chat:prefill-input', handler);
  }, [saveDraft]);

  const updateQuoteReply = useCallback((id: string, reply: string) => {
    setQuotes(prev => prev.map(q => q.id === id ? { ...q, reply } : q));
  }, []);

  const removeQuote = useCallback((id: string) => {
    setQuotes(prev => prev.filter(q => q.id !== id));
  }, []);

  const handleSend = useCallback(() => {
    const rawText = localDraft.trim();
    const hasFiles = attachedFiles.length > 0;
    const hasQuotes = quotes.length > 0;
    if (!rawText && !hasFiles && !hasQuotes) return;

    // Build message: quotes with replies + general text
    const parts: string[] = [];
    for (const q of quotes) {
      const quoted = q.text.split('\n').map(line => `> ${line}`).join('\n');
      parts.push(quoted);
      if (q.reply.trim()) {
        parts.push(q.reply.trim());
      }
    }
    if (rawText) parts.push(rawText);

    const text = parts.join('\n\n');
    const files = hasFiles ? [...attachedFiles] : [];

    let sent: boolean;
    try {
      sent = onSend(text, files);
    } catch (err) {
      console.error('[ChatInput] send error:', err);
      return;
    }
    if (!sent) return;

    setLocalDraft('');
    localDirtyRef.current = false;
    justSentRef.current = true;
    if (draftKeyRef.current) {
      // Flush: clear draft on server immediately
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      socketRef.current?.emit('draft_save', { session_id: draftKeyRef.current, text: '' });
    }
    if (inputRef.current) inputRef.current.style.height = 'auto';
    setExpanded(false);
    setQuotes([]);
    dispatch({ type: 'CLEAR_ATTACHED_FILES' });
  }, [localDraft, attachedFiles, dispatch, onSend, quotes, socketRef]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    // Skill autocomplete navigation
    if (showSkillMenu && filteredSkills.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSkillSelectedIdx(prev => (prev + 1) % filteredSkills.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSkillSelectedIdx(prev => (prev - 1 + filteredSkills.length) % filteredSkills.length);
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        insertSkill(filteredSkills[skillSelectedIdx].name);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowSkillMenu(false);
        return;
      }
    }

    // Escape exits expanded mode
    if (e.key === 'Escape' && expanded) {
      e.preventDefault();
      setExpanded(false);
      return;
    }

    // Cmd/Ctrl+Enter always sends
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
      if (expanded) setExpanded(false);
      return;
    }

    // Plain Enter: send in normal mode, newline in expanded mode
    if (e.key === 'Enter' && !e.shiftKey) {
      if (!expanded) {
        e.preventDefault();
        handleSend();
      }
      // In expanded mode, let Enter insert newline naturally
    }
  }, [handleSend, showSkillMenu, filteredSkills, skillSelectedIdx, insertSkill, expanded]);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    localDirtyRef.current = true;
    setLocalDraft(val);
    saveDraft(val);
    // Expanded mode is user-controlled only (toggle button or Esc). Typing
    // never flips the mode — auto-expand-on-long-text was removed because it
    // changed layout mid-keystroke and felt jumpy.
    // Auto-resize. In non-expanded mode, clamp to ~12rem so height grows
    // gradually with content rather than ballooning to half the viewport.
    const inlineCap = Math.min(window.innerHeight * 0.5, 192);  // ~12rem
    const maxH = expanded ? window.innerHeight * 0.7 : inlineCap;
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, maxH) + 'px';
    // Skill autocomplete check
    checkSlashTrigger(val, e.target.selectionStart);
  }, [saveDraft, checkSlashTrigger, expanded]);

  // File upload
  const uploadFiles = useCallback(async (files: File[]) => {
    for (const file of files) {
      try {
        const data = await api.uploadFile(file);
        for (const f of data.files) {
          let thumbUrl: string | undefined;
          if (f.type.startsWith('image/')) {
            thumbUrl = URL.createObjectURL(file);
          }
          dispatch({ type: 'ADD_ATTACHED_FILE', file: { ...f, thumbUrl } });
        }
      } catch (e) {
        console.error('File upload failed:', e);
      }
    }
  }, [dispatch]);

  // Paste handler for images
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      uploadFiles(files);
    }
  }, [uploadFiles]);

  // Drag and drop
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current++;
    setDragActive(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current--;
    if (dragCounter.current <= 0) {
      setDragActive(false);
      dragCounter.current = 0;
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    dragCounter.current = 0;
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length > 0) {
      uploadFiles(files);
    }
  }, [uploadFiles]);

  const removeFile = useCallback((idx: number) => {
    dispatch({ type: 'REMOVE_ATTACHED_FILE', index: idx });
  }, [dispatch]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) uploadFiles(files);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [uploadFiles]);

  // Mobile keyboard: adjust chat panel position via visualViewport API
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const isMobile = window.matchMedia('(max-width: 768px)').matches;
    if (!isMobile) return;

    const onResize = () => {
      const kbHeight = window.innerHeight - vv.height - vv.offsetTop;
      document.documentElement.style.setProperty(
        '--keyboard-height',
        kbHeight > 0 ? `${kbHeight}px` : '0px'
      );
    };
    vv.addEventListener('resize', onResize);
    vv.addEventListener('scroll', onResize);
    return () => {
      vv.removeEventListener('resize', onResize);
      vv.removeEventListener('scroll', onResize);
      document.documentElement.style.setProperty('--keyboard-height', '0px');
    };
  }, []);

  return (
    <div
      className="chat-input-area"
      style={{ position: 'relative' }}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Multi-quote blocks with inline replies */}
      {quotes.length > 0 && (
        <div className="chat-quotes-stack">
          {quotes.map((q) => (
            <div key={q.id} className="chat-quote-block">
              <div className="chat-quote-preview">
                <div className="chat-quote-preview-bar" />
                <div className="chat-quote-preview-text">
                  {q.text.length > 200 ? q.text.slice(0, 200) + '...' : q.text}
                </div>
                <button
                  className="chat-quote-preview-close"
                  onClick={() => removeQuote(q.id)}
                  title="Remove quote"
                >
                  &times;
                </button>
              </div>
              <textarea
                className="quote-reply-input"
                placeholder="Reply to this..."
                rows={1}
                value={q.reply}
                onChange={(e) => updateQuoteReply(q.id, e.target.value)}
                onInput={(e) => {
                  const el = e.currentTarget;
                  el.style.height = 'auto';
                  el.style.height = Math.min(el.scrollHeight, 100) + 'px';
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
              />
            </div>
          ))}
        </div>
      )}

      {/* File previews */}
      {attachedFiles.length > 0 && (
        <div className="chat-files-preview">
          {attachedFiles.map((f, i) => (
            <div key={i} className="chat-file-chip">
              {f.thumbUrl ? (
                <img className="chat-file-chip-thumb" src={f.thumbUrl} alt={f.name} />
              ) : f.type.startsWith('image/') ? (
                <svg className="chat-file-chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="M21 15l-5-5L5 21" />
                </svg>
              ) : (
                <svg className="chat-file-chip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <path d="M14 2v6h6" />
                </svg>
              )}
              <span className="chat-file-chip-name" title={f.name}>{f.name}</span>
              <span className="chat-file-chip-remove" onClick={() => removeFile(i)}>&times;</span>
            </div>
          ))}
        </div>
      )}

      {/* Skill autocomplete menu */}
      {showSkillMenu && filteredSkills.length > 0 && (
        <div className="skill-autocomplete" ref={menuRef}>
          {filteredSkills.map((s, i) => (
            <div
              key={s.name}
              className={`skill-autocomplete-item${i === skillSelectedIdx ? ' selected' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); insertSkill(s.name); }}
              onMouseEnter={() => setSkillSelectedIdx(i)}
            >
              <span className="skill-autocomplete-name">/{s.name}</span>
              {s.description && (
                <span className="skill-autocomplete-desc">{s.description}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Controls bar - lives above the input; everything except Send. */}
      <div className="chat-controls-bar">
        <SpinnerBar />
        <div className="chat-controls-group">
          <ContextUsage />
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={handleFileInput}
          />
          <button
            className="chat-icon-btn"
            onClick={() => fileInputRef.current?.click()}
            title="Attach file"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <button
            className={`chat-icon-btn${expanded ? ' active' : ''}`}
            onClick={() => {
              setExpanded(prev => {
                const next = !prev;
                requestAnimationFrame(() => {
                  if (inputRef.current) {
                    const maxH = next ? window.innerHeight * 0.7 : Math.min(window.innerHeight * 0.5, 192);
                    inputRef.current.style.height = 'auto';
                    inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, maxH) + 'px';
                    inputRef.current.focus();
                  }
                });
                return next;
              });
            }}
            title={expanded ? 'Collapse (Esc)' : 'Expand editor'}
          >
            {expanded ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 14h6v6" /><path d="M20 10h-6V4" /><path d="M14 10l7-7" /><path d="M3 21l7-7" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 3h6v6" /><path d="M9 21H3v-6" /><path d="M21 3l-7 7" /><path d="M3 21l7-7" />
              </svg>
            )}
          </button>
          <select
            className="chat-select chat-select-sm"
            value={model}
            onChange={(e) => dispatch({ type: 'SET_MODEL', model: e.target.value })}
            title="Model"
          >
            {MODEL_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            className="chat-select chat-select-sm"
            value={effort}
            onChange={(e) => dispatch({ type: 'SET_EFFORT', effort: e.target.value })}
            title="Reasoning effort"
          >
            {EFFORT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <PermissionToggle />
        </div>
      </div>

      <div className={`chat-input-wrap${expanded ? ' chat-input-expanded' : ''}`}>
        <textarea
          ref={inputRef}
          className={`chat-input${expanded ? ' expanded' : ''}`}
          placeholder={expanded ? 'Compose your message... (\u2318Enter to send, Esc to collapse)' : 'Message Claude... (\u2318Enter for newline)'}
          rows={expanded ? 10 : 1}
          value={localDraft}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
        />

        {realtimeStatus === 'streaming' ? (
          <button
            className="chat-btn chat-btn-deny"
            onClick={onCancel}
            style={{ whiteSpace: 'nowrap' }}
          >
            Cancel
          </button>
        ) : (
          <button
            className="chat-send"
            onClick={() => { handleSend(); if (expanded) setExpanded(false); }}
            title={expanded ? 'Send (Cmd+Enter)' : 'Send (Enter)'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          </button>
        )}
      </div>

      {/* Drop overlay */}
      <div className={`chat-drop-overlay${dragActive ? ' active' : ''}`}>
        <span>Drop files here</span>
      </div>
    </div>
  );
}
