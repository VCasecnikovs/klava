/**
 * Tests for TCPanel (Task Changes Panel) and ViewsViewer components.
 * These had 16% and 30% coverage respectively.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

// Mock showToast
vi.mock('@/components/shared/Toast', () => ({
  showToast: vi.fn(),
}));

// Mock api client
vi.mock('@/api/client', () => ({
  api: {
    openView: vi.fn(),
  },
  apiClient: { get: vi.fn(), post: vi.fn() },
  socket: { on: vi.fn(), off: vi.fn(), emit: vi.fn() },
}));

import { TCPanel } from '@/components/tabs/Tasks/TCPanel';
import { ViewsViewer } from '@/components/tabs/Views/ViewsViewer';
import { showToast } from '@/components/shared/Toast';
import { api } from '@/api/client';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ========================
// TCPanel Tests
// ========================
describe('TCPanel', () => {
  const baseMark = { action: null as 'done' | 'postpone' | 'cancel' | null, title: 'Test Task', note: '' };
  const defaultProps = {
    marks: {} as Record<string, typeof baseMark>,
    onRemove: vi.fn(),
    onClearAll: vi.fn(),
    onSetAction: vi.fn(),
    onSetNote: vi.fn(),
  };

  it('renders nothing when marks is empty', () => {
    const { container } = render(<TCPanel {...defaultProps} marks={{}} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders FAB with count when there are marks', () => {
    const marks = {
      'task-1': { action: 'done' as const, title: 'Task 1', note: '' },
      'task-2': { action: null, title: 'Task 2', note: 'some note' },
    };
    render(<TCPanel {...defaultProps} marks={marks} />);
    expect(screen.getByText('Changes')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
  });

  it('toggles panel open/close when FAB is clicked', () => {
    const marks = { 'task-1': { action: 'done' as const, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);

    // Panel not visible initially
    expect(screen.queryByText('Task Changes')).toBeNull();

    // Click FAB to open
    fireEvent.click(screen.getByText('Changes'));
    expect(screen.getByText('Task Changes')).toBeTruthy();

    // Click FAB again to close
    fireEvent.click(screen.getByText('Changes'));
    expect(screen.queryByText('Task Changes')).toBeNull();
  });

  it('closes panel via close button', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);

    fireEvent.click(screen.getByText('Changes'));
    expect(screen.getByText('Task Changes')).toBeTruthy();

    fireEvent.click(screen.getByText('×'));
    expect(screen.queryByText('Task Changes')).toBeNull();
  });

  it('displays task items with correct badges', () => {
    const marks = {
      'task-done': { action: 'done' as const, title: 'Done Task', note: '' },
      'task-postpone': { action: 'postpone' as const, title: 'Postponed Task', note: '' },
      'task-cancel': { action: 'cancel' as const, title: 'Cancelled Task', note: '' },
      'task-note': { action: null, title: 'Note Task', note: 'my note' },
    };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));

    expect(screen.getByText('DONE')).toBeTruthy();
    expect(screen.getByText('+1 WEEK')).toBeTruthy();
    expect(screen.getByText('CANCEL')).toBeTruthy();
    expect(screen.getByText('NOTE')).toBeTruthy();
    expect(screen.getByText('Done Task')).toBeTruthy();
    expect(screen.getByText('my note')).toBeTruthy();
  });

  it('calls onRemove when Del button is clicked', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Del'));
    expect(defaultProps.onRemove).toHaveBeenCalledWith('task-1');
  });

  it('calls onClearAll when Clear All is clicked', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Clear All'));
    expect(defaultProps.onClearAll).toHaveBeenCalled();
  });

  it('opens edit area when Edit is clicked', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: 'existing note' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Edit'));

    // Edit area should now be visible with textarea and action buttons
    const textarea = document.getElementById('tc-edit-ta') as HTMLTextAreaElement;
    expect(textarea).toBeTruthy();
    expect(textarea.defaultValue).toBe('existing note');
  });

  it('toggles edit area off when Edit is clicked again', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));

    // Open edit
    fireEvent.click(screen.getByText('Edit'));
    expect(document.getElementById('tc-edit-ta')).toBeTruthy();

    // Close edit
    fireEvent.click(screen.getByText('Edit'));
    expect(document.getElementById('tc-edit-ta')).toBeNull();
  });

  it('calls onSetAction when action buttons are clicked in edit', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Edit'));

    // Click Done action button (inside edit area, not the badge)
    const actionBtns = document.querySelectorAll('.tc-action-btn');
    // Should be: Done, +1 Week, Cancel, Save
    expect(actionBtns.length).toBe(4);
    fireEvent.click(actionBtns[0]); // Done
    expect(defaultProps.onSetAction).toHaveBeenCalledWith('task-1', 'done');

    fireEvent.click(actionBtns[1]); // +1 Week = postpone
    expect(defaultProps.onSetAction).toHaveBeenCalledWith('task-1', 'postpone');

    fireEvent.click(actionBtns[2]); // Cancel
    expect(defaultProps.onSetAction).toHaveBeenCalledWith('task-1', 'cancel');
  });

  it('calls onSetNote and closes edit when Save is clicked', () => {
    const marks = { 'task-1': { action: null, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Edit'));

    const textarea = document.getElementById('tc-edit-ta') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'new note text' } });

    fireEvent.click(screen.getByText('Save'));
    // onSetNote is called with textarea value
    expect(defaultProps.onSetNote).toHaveBeenCalledWith('task-1', expect.any(String));
    // Edit area should be closed
    expect(document.getElementById('tc-edit-ta')).toBeNull();
  });

  it('dispatches chat:open and chat:new-session on Send to Session', () => {
    const marks = { 'task-1': { action: 'done' as const, title: 'Task 1', note: 'note1' } };
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Send to Session'));

    // Should dispatch chat:open and chat:new-session
    const events = dispatchSpy.mock.calls.map(c => (c[0] as CustomEvent).type);
    expect(events).toContain('chat:open');
    expect(events).toContain('chat:new-session');
    expect(showToast).toHaveBeenCalled();

    dispatchSpy.mockRestore();
  });

  it('shows active class on action button matching current action', () => {
    const marks = { 'task-1': { action: 'done' as const, title: 'Task 1', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    fireEvent.click(screen.getByText('Edit'));

    const doneBtn = document.querySelector('.tc-action-btn.active');
    expect(doneBtn).toBeTruthy();
    expect(doneBtn!.textContent).toBe('Done');
  });

  it('uses task id as title fallback when title is empty', () => {
    const marks = { 'task-123': { action: null, title: '', note: '' } };
    render(<TCPanel {...defaultProps} marks={marks} />);
    fireEvent.click(screen.getByText('Changes'));
    expect(screen.getByText('task-123')).toBeTruthy();
  });
});

// ========================
// ViewsViewer Tests
// ========================
describe('ViewsViewer', () => {
  const defaultProps = {
    filename: 'report.html',
    title: 'My Report',
    onBack: vi.fn(),
  };

  it('renders with title and back button', () => {
    render(<ViewsViewer {...defaultProps} />);
    expect(screen.getByText('My Report')).toBeTruthy();
    expect(screen.getByText('Back')).toBeTruthy();
    expect(screen.getByText('Open in new tab')).toBeTruthy();
  });

  it('sets iframe src from filename', () => {
    render(<ViewsViewer {...defaultProps} />);
    const iframe = document.querySelector('iframe');
    expect(iframe).toBeTruthy();
    expect(iframe!.src).toContain('/api/views/serve/report.html');
  });

  it('sets iframe src from url prop', () => {
    render(<ViewsViewer url="https://example.com/page" title="External" onBack={vi.fn()} />);
    const iframe = document.querySelector('iframe');
    expect(iframe!.src).toBe('https://example.com/page');
  });

  it('calls onBack when back button is clicked', () => {
    render(<ViewsViewer {...defaultProps} />);
    fireEvent.click(screen.getByText('Back'));
    expect(defaultProps.onBack).toHaveBeenCalled();
  });

  it('calls api.openView when Open in new tab clicked with filename', async () => {
    (api.openView as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    render(<ViewsViewer {...defaultProps} />);
    fireEvent.click(screen.getByText('Open in new tab'));

    // Wait for promise
    await vi.waitFor(() => {
      expect(api.openView).toHaveBeenCalledWith('report.html', true);
    });
  });

  it('opens new window when Open in new tab clicked with url (no filename)', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<ViewsViewer url="https://example.com" title="Ext" onBack={vi.fn()} />);
    fireEvent.click(screen.getByText('Open in new tab'));
    expect(openSpy).toHaveBeenCalledWith('https://example.com', '_blank');
    openSpy.mockRestore();
  });

  it('shows toast on successful openView', async () => {
    (api.openView as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    render(<ViewsViewer {...defaultProps} />);
    fireEvent.click(screen.getByText('Open in new tab'));

    await vi.waitFor(() => {
      expect(showToast).toHaveBeenCalledWith('Opened in browser');
    });
  });

  it('shows error toast when openView fails', async () => {
    (api.openView as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('fail'));
    render(<ViewsViewer {...defaultProps} />);
    fireEvent.click(screen.getByText('Open in new tab'));

    await vi.waitFor(() => {
      expect(showToast).toHaveBeenCalledWith('Failed to open');
    });
  });

  it('uses filename as title fallback when title is empty', () => {
    render(<ViewsViewer filename="test.html" title="" onBack={vi.fn()} />);
    // esc(title || filename) => should show filename
    expect(screen.getByText('test.html')).toBeTruthy();
  });
});
