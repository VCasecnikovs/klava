import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLocalStorage } from '@/lib/useLocalStorage';

// Use a fresh localStorage mock for each test
beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('useLocalStorage', () => {
  // ---- initialization ----
  describe('initialization', () => {
    it('returns initialValue when localStorage is empty', () => {
      const { result } = renderHook(() => useLocalStorage('test-key', 'default'));
      expect(result.current[0]).toBe('default');
    });

    it('returns stored value when localStorage has data', () => {
      localStorage.setItem('test-key', JSON.stringify('saved'));
      const { result } = renderHook(() => useLocalStorage('test-key', 'default'));
      expect(result.current[0]).toBe('saved');
    });

    it('returns initialValue when localStorage has invalid JSON', () => {
      localStorage.setItem('bad-key', '{invalid json');
      const { result } = renderHook(() => useLocalStorage('bad-key', 'fallback'));
      expect(result.current[0]).toBe('fallback');
    });

    it('works with object initial values', () => {
      const initial = { count: 0, name: 'test' };
      const { result } = renderHook(() => useLocalStorage('obj-key', initial));
      expect(result.current[0]).toEqual(initial);
    });

    it('works with array initial values', () => {
      const initial = [1, 2, 3];
      const { result } = renderHook(() => useLocalStorage('arr-key', initial));
      expect(result.current[0]).toEqual(initial);
    });

    it('works with boolean initial values', () => {
      const { result } = renderHook(() => useLocalStorage('bool-key', false));
      expect(result.current[0]).toBe(false);
    });

    it('works with numeric initial values', () => {
      const { result } = renderHook(() => useLocalStorage('num-key', 42));
      expect(result.current[0]).toBe(42);
    });

    it('works with null initial value', () => {
      const { result } = renderHook(() => useLocalStorage<string | null>('null-key', null));
      expect(result.current[0]).toBe(null);
    });
  });

  // ---- setValue with direct value ----
  describe('setValue with direct value', () => {
    it('updates state and localStorage', () => {
      const { result } = renderHook(() => useLocalStorage('key', 'initial'));

      act(() => {
        result.current[1]('updated');
      });

      expect(result.current[0]).toBe('updated');
      expect(JSON.parse(localStorage.getItem('key')!)).toBe('updated');
    });

    it('handles object values', () => {
      const { result } = renderHook(() => useLocalStorage('obj', { a: 1 }));

      act(() => {
        result.current[1]({ a: 2 });
      });

      expect(result.current[0]).toEqual({ a: 2 });
      expect(JSON.parse(localStorage.getItem('obj')!)).toEqual({ a: 2 });
    });

    it('handles setting to null', () => {
      const { result } = renderHook(() => useLocalStorage<string | null>('nullable', 'hello'));

      act(() => {
        result.current[1](null);
      });

      expect(result.current[0]).toBe(null);
      expect(JSON.parse(localStorage.getItem('nullable')!)).toBe(null);
    });
  });

  // ---- setValue with updater function ----
  describe('setValue with updater function', () => {
    it('updates state using previous value', () => {
      const { result } = renderHook(() => useLocalStorage('counter', 0));

      act(() => {
        result.current[1]((prev) => prev + 1);
      });

      expect(result.current[0]).toBe(1);
      expect(JSON.parse(localStorage.getItem('counter')!)).toBe(1);
    });

    it('supports multiple sequential updates', () => {
      const { result } = renderHook(() => useLocalStorage('counter', 0));

      act(() => {
        result.current[1]((prev) => prev + 1);
      });
      act(() => {
        result.current[1]((prev) => prev + 10);
      });

      expect(result.current[0]).toBe(11);
    });

    it('updater function works with arrays', () => {
      const { result } = renderHook(() => useLocalStorage<string[]>('items', []));

      act(() => {
        result.current[1]((prev) => [...prev, 'a']);
      });
      act(() => {
        result.current[1]((prev) => [...prev, 'b']);
      });

      expect(result.current[0]).toEqual(['a', 'b']);
    });
  });

  // ---- error handling ----
  describe('error handling', () => {
    it('handles localStorage.getItem throwing', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError');
      });

      const { result } = renderHook(() => useLocalStorage('secure-key', 'fallback'));
      expect(result.current[0]).toBe('fallback');
    });

    it('handles localStorage.setItem throwing (quota exceeded)', () => {
      const { result } = renderHook(() => useLocalStorage('full-key', 'initial'));

      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceededError');
      });

      // Should still update React state even if localStorage throws
      act(() => {
        result.current[1]('new-value');
      });

      expect(result.current[0]).toBe('new-value');
    });
  });

  // ---- key isolation ----
  describe('key isolation', () => {
    it('different keys are independent', () => {
      const { result: result1 } = renderHook(() => useLocalStorage('key-a', 'A'));
      const { result: result2 } = renderHook(() => useLocalStorage('key-b', 'B'));

      act(() => {
        result1.current[1]('A2');
      });

      expect(result1.current[0]).toBe('A2');
      expect(result2.current[0]).toBe('B');
    });
  });
});
