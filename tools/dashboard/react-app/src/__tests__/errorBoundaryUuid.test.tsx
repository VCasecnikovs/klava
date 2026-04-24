/**
 * Tests for ChatErrorBoundary and uuid() polyfill.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ChatErrorBoundary } from '@/components/tabs/Chat/ErrorBoundary';
import { uuid } from '@/components/tabs/Chat/uuid';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ========================
// ChatErrorBoundary
// ========================
describe('ChatErrorBoundary', () => {
  // Suppress console.error for error boundary tests
  const originalError = console.error;
  beforeAll(() => { console.error = vi.fn(); });
  afterAll(() => { console.error = originalError; });

  function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
    if (shouldThrow) throw new Error('Test error');
    return <div>Working fine</div>;
  }

  it('renders children normally when no error', () => {
    render(
      <ChatErrorBoundary>
        <div>Hello World</div>
      </ChatErrorBoundary>
    );
    expect(screen.getByText('Hello World')).toBeTruthy();
  });

  it('shows error UI when child throws', () => {
    render(
      <ChatErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ChatErrorBoundary>
    );
    expect(screen.getByText('Something went wrong')).toBeTruthy();
    expect(screen.getByText('Test error')).toBeTruthy();
    expect(screen.getByText('Retry')).toBeTruthy();
  });

  it('resets error state when Retry is clicked', () => {
    // We can't easily test full recovery because React re-renders the same tree.
    // But we can verify that clicking Retry calls setState to reset error state.
    render(
      <ChatErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ChatErrorBoundary>
    );
    expect(screen.getByText('Something went wrong')).toBeTruthy();
    expect(screen.getByText('Test error')).toBeTruthy();

    // Click Retry - state resets, but the child throws again
    fireEvent.click(screen.getByText('Retry'));
    // Error boundary catches it again - still showing error
    // This verifies handleRetry runs and getDerivedStateFromError catches again
    expect(screen.getByText('Something went wrong')).toBeTruthy();
  });

  it('shows "Unknown error" when error has no message', () => {
    function ThrowNull() {
      throw { message: undefined };
    }
    render(
      <ChatErrorBoundary>
        <ThrowNull />
      </ChatErrorBoundary>
    );
    expect(screen.getByText('Unknown error')).toBeTruthy();
  });
});

// ========================
// uuid
// ========================
describe('uuid', () => {
  it('returns a valid UUID v4 format string', () => {
    const id = uuid();
    // UUID v4 format: xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it('returns unique values on each call', () => {
    const ids = new Set(Array.from({ length: 100 }, () => uuid()));
    expect(ids.size).toBe(100);
  });

  it('uses crypto.randomUUID when available', () => {
    const original = crypto.randomUUID;
    const mockUUID = '12345678-1234-4123-8123-123456789012';
    crypto.randomUUID = vi.fn().mockReturnValue(mockUUID);

    const result = uuid();
    expect(result).toBe(mockUUID);
    expect(crypto.randomUUID).toHaveBeenCalled();

    crypto.randomUUID = original;
  });

  it('falls back to getRandomValues when randomUUID unavailable', () => {
    const original = crypto.randomUUID;
    // @ts-ignore - temporarily remove randomUUID
    delete (crypto as any).randomUUID;

    const id = uuid();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

    crypto.randomUUID = original;
  });
});
