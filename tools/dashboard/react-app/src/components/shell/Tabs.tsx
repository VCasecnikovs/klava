import { useRef, useEffect, useCallback } from 'react';
import { TABS, type TabId } from '@/api/types';
import { Badge } from '@/components/shared/Badge';

interface TabsProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  tabBadges: Record<string, { count: number; style: 'subtle' | 'danger' | '' }>;
  labelOverrides?: Partial<Record<TabId, string>>;
}

export function Tabs({ activeTab, onTabChange, tabBadges, labelOverrides }: TabsProps) {
  const navRef = useRef<HTMLElement>(null);

  const scrollActiveIntoView = useCallback(() => {
    const nav = navRef.current;
    if (!nav) return;
    const active = nav.querySelector('.tab.active') as HTMLElement | null;
    if (active) {
      active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }, []);

  useEffect(() => {
    scrollActiveIntoView();
  }, [activeTab, scrollActiveIntoView]);

  return (
    <nav className="tabs" ref={navRef}>
      {TABS.map(tab => (
        <div
          key={tab.id}
          className={`tab${activeTab === tab.id ? ' active' : ''}`}
          onClick={() => onTabChange(tab.id)}
        >
          {labelOverrides?.[tab.id] || tab.label}
          {tab.badgeId && tabBadges[tab.badgeId] && (
            <Badge
              count={tabBadges[tab.badgeId].count}
              style={tabBadges[tab.badgeId].style}
            />
          )}
        </div>
      ))}
    </nav>
  );
}
