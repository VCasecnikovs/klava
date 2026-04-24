import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { esc, fmt, fmtCost, dateLabel, toDateKey, toTime, sparkSVG, timeAgo, cn } from '@/lib/utils';

// ---- esc ----
describe('esc', () => {
  it('returns empty string for falsy values', () => {
    expect(esc('')).toBe('');
    expect(esc(null)).toBe('');
    expect(esc(undefined)).toBe('');
    expect(esc(0)).toBe('');
    expect(esc(false)).toBe('');
  });

  it('escapes HTML special characters', () => {
    expect(esc('<script>alert("xss")</script>')).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
  });

  it('escapes ampersands', () => {
    expect(esc('a & b')).toBe('a &amp; b');
  });

  it('passes through safe strings unchanged', () => {
    expect(esc('hello world')).toBe('hello world');
  });

  it('converts numbers to string', () => {
    expect(esc(42)).toBe('42');
  });
});

// ---- fmt ----
describe('fmt', () => {
  it('formats integers with locale separators', () => {
    expect(fmt(1000)).toBe('1,000');
    expect(fmt(1234567)).toBe('1,234,567');
  });

  it('formats floats with 2 decimal places', () => {
    expect(fmt(3.14)).toBe('3.14');
    expect(fmt(1000.5)).toBe('1,000.50');
  });

  it('returns "0" for non-number falsy values', () => {
    expect(fmt(null)).toBe('0');
    expect(fmt(undefined)).toBe('0');
    expect(fmt('')).toBe('0');
  });

  it('returns string representation for non-number truthy values', () => {
    expect(fmt('hello')).toBe('hello');
  });

  it('handles zero', () => {
    expect(fmt(0)).toBe('0');
  });

  it('handles negative numbers', () => {
    expect(fmt(-1234)).toBe('-1,234');
  });
});

// ---- fmtCost ----
describe('fmtCost', () => {
  it('returns $0 for zero', () => {
    expect(fmtCost(0)).toBe('$0');
  });

  it('returns $0 for null/undefined', () => {
    expect(fmtCost(null)).toBe('$0');
    expect(fmtCost(undefined)).toBe('$0');
  });

  it('formats small values with 4 decimals', () => {
    expect(fmtCost(0.005)).toBe('$0.0050');
    expect(fmtCost(0.0001)).toBe('$0.0001');
  });

  it('formats normal values with 2 decimals', () => {
    expect(fmtCost(1.5)).toBe('$1.50');
    expect(fmtCost(0.01)).toBe('$0.01');
    expect(fmtCost(99.99)).toBe('$99.99');
  });

  it('handles boundary at 0.01', () => {
    expect(fmtCost(0.009)).toBe('$0.0090');
    expect(fmtCost(0.01)).toBe('$0.01');
  });
});

// ---- dateLabel ----
describe('dateLabel', () => {
  it('returns "Today" for today\'s date', () => {
    const today = new Date();
    const key = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    expect(dateLabel(key)).toBe('Today');
  });

  it('returns "Yesterday" for yesterday\'s date', () => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    expect(dateLabel(key)).toBe('Yesterday');
  });

  it('returns formatted date for older dates', () => {
    const result = dateLabel('2024-01-15');
    expect(result).toContain('Jan');
    expect(result).toContain('15');
  });

  it('returns "Invalid Date" for unparseable date strings', () => {
    // dateLabel appends T00:00:00 and tries to parse - invalid dates don't throw,
    // they produce NaN diff which falls through to toLocaleDateString returning "Invalid Date"
    const result = dateLabel('not-a-date');
    expect(result).toBe('Invalid Date');
  });

  it('returns raw string when Date operations throw', () => {
    // Force the catch branch by making Date constructor throw
    const origDate = globalThis.Date;
    globalThis.Date = function () { throw new Error('boom'); } as any;
    try {
      expect(dateLabel('2024-01-15')).toBe('2024-01-15');
    } finally {
      globalThis.Date = origDate;
    }
  });
});

// ---- toDateKey ----
describe('toDateKey', () => {
  it('extracts date portion from ISO timestamp', () => {
    expect(toDateKey('2024-01-15T10:30:00Z')).toBe('2024-01-15');
  });

  it('returns "unknown" for undefined', () => {
    expect(toDateKey(undefined)).toBe('unknown');
  });

  it('returns "unknown" for empty string', () => {
    expect(toDateKey('')).toBe('unknown');
  });

  it('handles date-only strings', () => {
    expect(toDateKey('2024-12-25')).toBe('2024-12-25');
  });
});

// ---- toTime ----
describe('toTime', () => {
  it('extracts HH:MM from ISO timestamp', () => {
    expect(toTime('2024-01-15T10:30:00Z')).toBe('10:30');
  });

  it('returns empty string for undefined', () => {
    expect(toTime(undefined)).toBe('');
  });

  it('returns empty string for empty string', () => {
    expect(toTime('')).toBe('');
  });

  it('returns empty string if no time pattern found', () => {
    expect(toTime('no-time-here')).toBe('');
  });
});

// ---- sparkSVG ----
describe('sparkSVG', () => {
  it('returns empty string for undefined series', () => {
    expect(sparkSVG(undefined, '#f00')).toBe('');
  });

  it('returns empty string for series with < 2 points', () => {
    expect(sparkSVG([], '#f00')).toBe('');
    expect(sparkSVG([1], '#f00')).toBe('');
  });

  it('generates SVG for valid series', () => {
    const result = sparkSVG([1, 2, 3], '#ff0000');
    expect(result).toContain('<svg');
    expect(result).toContain('viewBox="0 0 64 28"');
    expect(result).toContain('stroke="#ff0000"');
    expect(result).toContain('fill="#ff0000"');
  });

  it('handles all-same values', () => {
    const result = sparkSVG([5, 5, 5], '#00f');
    expect(result).toContain('<svg');
  });
});

// ---- timeAgo ----
describe('timeAgo', () => {
  it('returns empty string for empty input', () => {
    expect(timeAgo('')).toBe('');
  });

  it('returns "just now" for recent timestamps', () => {
    const now = new Date().toISOString();
    expect(timeAgo(now)).toBe('just now');
  });

  it('returns minutes ago', () => {
    const d = new Date(Date.now() - 5 * 60 * 1000);
    expect(timeAgo(d.toISOString())).toBe('5m ago');
  });

  it('returns hours ago', () => {
    const d = new Date(Date.now() - 3 * 3600 * 1000);
    expect(timeAgo(d.toISOString())).toBe('3h ago');
  });

  it('returns days ago', () => {
    const d = new Date(Date.now() - 2 * 86400 * 1000);
    expect(timeAgo(d.toISOString())).toBe('2d ago');
  });
});

// ---- cn ----
describe('cn', () => {
  it('joins truthy class names', () => {
    expect(cn('a', 'b', 'c')).toBe('a b c');
  });

  it('filters out falsy values', () => {
    expect(cn('a', false, 'b', null, undefined, 'c')).toBe('a b c');
  });

  it('returns empty string for all falsy', () => {
    expect(cn(false, null, undefined)).toBe('');
  });

  it('handles single class', () => {
    expect(cn('only')).toBe('only');
  });

  it('handles no arguments', () => {
    expect(cn()).toBe('');
  });
});
