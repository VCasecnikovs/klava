import { describe, it, expect } from 'vitest';
import { TABS } from '@/api/types';
import type { TabConfig, TabId } from '@/api/types';

describe('TABS constant', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(TABS)).toBe(true);
    expect(TABS.length).toBeGreaterThan(0);
  });

  it('contains all expected tab IDs', () => {
    const ids = TABS.map((t) => t.id);
    // Feed lives inside Lifeline as a filter - no standalone tab.
    const expected: TabId[] = [
      'lifeline', 'tasks', 'habits', 'klava', 'views',
      'health', 'heartbeat', 'skills', 'files', 'people', 'settings',
    ];
    for (const id of expected) {
      expect(ids).toContain(id);
    }
    expect(TABS).toHaveLength(expected.length);
  });

  it('has unique IDs', () => {
    const ids = TABS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('every tab has id and label', () => {
    for (const tab of TABS) {
      expect(typeof tab.id).toBe('string');
      expect(tab.id.length).toBeGreaterThan(0);
      expect(typeof tab.label).toBe('string');
      expect(tab.label.length).toBeGreaterThan(0);
    }
  });

  it('badgeStyle is valid when present', () => {
    const validStyles = ['subtle', 'danger', ''];
    for (const tab of TABS) {
      if (tab.badgeStyle !== undefined) {
        expect(validStyles).toContain(tab.badgeStyle);
      }
    }
  });

  it('lifeline tab is first', () => {
    expect(TABS[0].id).toBe('lifeline');
  });

  it('tab configs match TabConfig interface shape', () => {
    for (const tab of TABS) {
      const config: TabConfig = tab; // type check
      expect(config).toBeDefined();
    }
  });
});
