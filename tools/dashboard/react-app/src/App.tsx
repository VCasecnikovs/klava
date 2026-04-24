import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { TabId, DashboardData } from '@/api/types';
import { useDashboard } from '@/api/queries';
import { api } from '@/api/client';
import { Pulse } from '@/components/shell/Pulse';
import { Tabs } from '@/components/shell/Tabs';
import { AlertBanners } from '@/components/shell/AlertBanners';
import { Toast } from '@/components/shared/Toast';
import { Toaster } from 'sonner';
import { io } from 'socket.io-client';

// Tab imports
import { LifelineTab } from '@/components/tabs/Lifeline';
import { ChatPanel } from '@/components/tabs/Chat';
import { SkillsTab } from '@/components/tabs/Skills';
import { HealthTab } from '@/components/tabs/Health';
import { FilesTab } from '@/components/tabs/Files';
import { TasksTab } from '@/components/tabs/Tasks';
import { KlavaTab } from '@/components/tabs/Klava';
import { DeckTab } from '@/components/tabs/Deck';
import { HeartbeatTab } from '@/components/tabs/Heartbeat';
import { PeopleTab } from '@/components/tabs/People';
import { ViewsTab } from '@/components/tabs/Views';

import { HabitsTab } from '@/components/tabs/Habits';
import { SettingsTab } from '@/components/tabs/Settings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function getInitialTab(): TabId {
  // setup.sh opens the dashboard with ?firstrun=1 after a fresh install
  // to steer the user into the setup wizard (which lives on the Settings
  // tab and auto-opens when setup.completed_at is unset).
  const params = new URLSearchParams(window.location.search);
  if (params.get('firstrun') === '1') return 'settings';

  const hash = window.location.hash.replace('#', '');
  // Legacy #feed hash → merged into Lifeline.
  if (hash === 'feed') return 'lifeline';
  const valid: TabId[] = [
    'tasks', 'klava', 'deck', 'views', 'lifeline',
    'skills', 'health', 'files', 'heartbeat',
    'people', 'habits', 'settings',
  ];
  return valid.includes(hash as TabId) ? (hash as TabId) : 'deck';
}

type ChatMode = 'collapsed' | 'sidebar' | 'full';

const CHAT_MIN_WIDTH = 360;
const CHAT_DEFAULT_WIDTH = 460;

const isMobile = () => window.innerWidth <= 768;

function Dashboard() {
  // First-run gate: while setup.completed_at is unset, pin the user to the
  // Settings tab (which auto-opens the wizard). Once they complete the wizard,
  // they can navigate freely. null = still loading, true = completed,
  // false = needs setup.
  const [setupCompleted, setSetupCompleted] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const s = await api.setupStatus();
        if (!cancelled) setSetupCompleted(!!s.wizard_completed_at);
      } catch {
        if (!cancelled) setSetupCompleted(true);  // don't block if API errors
      }
    };
    check();
    // Re-poll when the user finishes the wizard (Settings dispatches this event)
    const handler = () => check();
    window.addEventListener('wizard:completed', handler);
    return () => { cancelled = true; window.removeEventListener('wizard:completed', handler); };
  }, []);

  const [activeTab, setActiveTabRaw] = useState<TabId>(getInitialTab);
  // Wrap setActiveTab so that any switch-attempt while setup is incomplete
  // redirects back to Settings. Once completed, this is a direct passthrough.
  const setActiveTab = useCallback((t: TabId) => {
    if (setupCompleted === false) {
      setActiveTabRaw('settings');
    } else {
      setActiveTabRaw(t);
    }
  }, [setupCompleted]);
  // When we learn setup isn't complete, snap to Settings so the wizard fires.
  useEffect(() => {
    if (setupCompleted === false && activeTab !== 'settings') {
      setActiveTabRaw('settings');
    }
  }, [setupCompleted, activeTab]);
  const [pendingView, setPendingView] = useState<{ url?: string; filename?: string; title: string } | null>(null);
  const [chatMode, setChatMode] = useState<ChatMode>(() => {
    if (isMobile()) return 'collapsed';
    try {
      const saved = localStorage.getItem('chat-panel-mode');
      if (saved === 'collapsed' || saved === 'sidebar' || saved === 'full') return saved;
      // Migrate old boolean format
      if (localStorage.getItem('chat-panel-open') === 'false') return 'collapsed';
    } catch { /* ignore */ }
    return 'sidebar';
  });
  const [chatWidth, setChatWidth] = useState(() => {
    try {
      const saved = parseInt(localStorage.getItem('chat-panel-width') || '', 10);
      if (saved >= CHAT_MIN_WIDTH) return saved;
    } catch { /* ignore */ }
    return CHAT_DEFAULT_WIDTH;
  });
  const visitedTabs = useRef(new Set<TabId>([getInitialTab()]));
  const { data, refetch, isFetching } = useDashboard();

  // Hash sync
  useEffect(() => {
    window.location.hash = activeTab;
  }, [activeTab]);

  useEffect(() => {
    const onHash = () => {
      const raw = window.location.hash.replace('#', '');
      const hash = (raw === 'feed' ? 'lifeline' : raw) as TabId;
      if (hash) setActiveTab(hash);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Persist chat mode and width
  useEffect(() => {
    localStorage.setItem('chat-panel-mode', chatMode);
  }, [chatMode]);

  useEffect(() => {
    localStorage.setItem('chat-panel-width', String(chatWidth));
  }, [chatWidth]);

  // Cmd+B = toggle sidebar/collapsed, Esc = exit fullscreen
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault();
        setChatMode(prev => prev === 'collapsed' ? 'sidebar' : 'collapsed');
      }
      if (e.key === 'Escape' && chatMode === 'full') {
        setChatMode('sidebar');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [chatMode]);

  // Listen for "open chat" requests (e.g. from "Send to Session")
  useEffect(() => {
    const handler = () => setChatMode(prev => prev === 'collapsed' ? 'sidebar' : prev);
    window.addEventListener('chat:open', handler);
    window.addEventListener('chat:split-view', handler);
    return () => {
      window.removeEventListener('chat:open', handler);
      window.removeEventListener('chat:split-view', handler);
    };
  }, []);

  // Listen for "open in Views tab" requests (from artifact cards in chat + SocketIO)
  useEffect(() => {
    // Handle direct CustomEvent dispatches (e.g. from artifact cards)
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      visitedTabs.current.add('views');
      setActiveTab('views');
      if (detail?.filename || detail?.url) {
        setPendingView({ url: detail.url, filename: detail.filename, title: detail.title || 'View' });
      }
    };
    window.addEventListener('views:open', handler);

    // Listen for backend-initiated view opens via SocketIO
    const socket = io('/chat', { upgrade: false });
    socket.on('views_open', (data: { url: string; title: string }) => {
      visitedTabs.current.add('views');
      setActiveTab('views');
      setPendingView({ url: data.url, title: data.title });
    });

    return () => {
      window.removeEventListener('views:open', handler);
      socket.disconnect();
    };
  }, []);

  const handleTabChange = useCallback((tab: TabId) => {
    visitedTabs.current.add(tab);
    setActiveTab(tab);
  }, []);

  const isVisited = useCallback((tab: TabId) => visitedTabs.current.has(tab), []);

  // Listen for feed:unread custom events from FeedTab
  const [feedUnread, setFeedUnread] = useState(0);
  useEffect(() => {
    const handler = (e: Event) => {
      const count = (e as CustomEvent).detail?.count ?? 0;
      setFeedUnread(count);
    };
    window.addEventListener('feed:unread', handler);
    return () => window.removeEventListener('feed:unread', handler);
  }, []);

  const tabBadges = useMemo(() => computeBadges(data, feedUnread), [data, feedUnread]);
  const tabLabelOverrides = useMemo(() => {
    const o: Partial<Record<TabId, string>> = {};
    if (data?.assistant_name) o.klava = data.assistant_name;
    return o;
  }, [data?.assistant_name]);

  return (
    <>
      <Pulse data={data} onRefresh={() => refetch()} isRefreshing={isFetching} />

      <div className={`dashboard-body${chatMode === 'full' ? ' chat-fullscreen' : ''}`}>
        {/* Chat panel - persistent left sidebar */}
        <ChatPanel
          mode={chatMode}
          width={chatWidth}
          onWidthChange={setChatWidth}
          onToggle={() => setChatMode(prev => {
            if (isMobile()) return prev === 'collapsed' ? 'full' : 'collapsed';
            return prev === 'collapsed' ? 'sidebar' : 'collapsed';
          })}
          onFullscreen={() => setChatMode(prev => prev === 'full' ? (isMobile() ? 'collapsed' : 'sidebar') : 'full')}
        />

        {/* Main content area */}
        <div className="main-panel">
          <AlertBanners data={data} />
          {!data && isFetching && (
            <div className="error-banner" style={{ margin: '16px 24px' }}>Loading...</div>
          )}

          <Tabs
            activeTab={activeTab}
            onTabChange={handleTabChange}
            tabBadges={tabBadges}
            labelOverrides={tabLabelOverrides}
          />

          <div className="main-content">
            <TabPage id="tasks" active={activeTab}>
              {isVisited('tasks') && <TasksTab />}
            </TabPage>
            <TabPage id="klava" active={activeTab}>
              {isVisited('klava') && <KlavaTab />}
            </TabPage>
            <TabPage id="deck" active={activeTab}>
              {isVisited('deck') && <DeckTab />}
            </TabPage>
            <TabPage id="views" active={activeTab}>
              {isVisited('views') && (
                <ViewsTab
                  pendingView={pendingView}
                  onPendingViewConsumed={() => setPendingView(null)}
                />
              )}
            </TabPage>
            <TabPage id="lifeline" active={activeTab}>
              <LifelineTab data={data} />
            </TabPage>
            <TabPage id="skills" active={activeTab}>
              <SkillsTab data={data} />
            </TabPage>
            <TabPage id="health" active={activeTab}>
              <HealthTab data={data} />
            </TabPage>

            <TabPage id="files" active={activeTab}>
              {isVisited('files') && <FilesTab />}
            </TabPage>
            <TabPage id="heartbeat" active={activeTab}>
              {isVisited('heartbeat') && <HeartbeatTab />}
            </TabPage>
            <TabPage id="people" active={activeTab}>
              {isVisited('people') && <PeopleTab />}
            </TabPage>
            <TabPage id="habits" active={activeTab}>
              {isVisited('habits') && <HabitsTab />}
            </TabPage>
            <TabPage id="settings" active={activeTab}>
              {isVisited('settings') && <SettingsTab />}
            </TabPage>
          </div>
        </div>
      </div>

      {/* Mobile FAB to open chat */}
      {chatMode === 'collapsed' && (
        <button
          className="chat-fab"
          onClick={() => setChatMode('full')}
          aria-label="Open chat"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </button>
      )}

      <Toast />
    </>
  );
}

function TabPage({ id, active, children }: { id: TabId; active: TabId; children: React.ReactNode }) {
  return (
    <div className={`page${active === id ? ' active' : ''}`} data-page={id}>
      {children}
    </div>
  );
}

function computeBadges(data?: DashboardData, feedUnread?: number) {
  const badges: Record<string, { count: number; style: 'subtle' | 'danger' | '' }> = {};

  // Feed badge from custom event
  if (feedUnread && feedUnread > 0) {
    badges.feed = { count: feedUnread, style: '' };
  }

  if (!data) return badges;

  const today = new Date().toISOString().substring(0, 10);

  let eventsToday = 0;
  (data.activity || []).forEach(a => { if (a.timestamp?.startsWith(today)) eventsToday++; });
  (data.agent_activity || []).forEach(a => { if (a.timestamp?.startsWith(today)) eventsToday++; });
  (data.evolution_timeline || []).forEach(e => { if (e.date === today) eventsToday++; });
  badges.lifeline = { count: eventsToday, style: 'subtle' };

  const skillErrors = (data.skill_inventory || []).filter(s => s.error_count > 0).length;
  badges.skills = { count: skillErrors, style: skillErrors > 0 ? 'danger' : '' };

  const healthIssues = (data.failing_jobs || []).length;
  badges.health = { count: healthIssues, style: healthIssues > 0 ? 'danger' : '' };

  return badges;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
      <Toaster
        position="bottom-right"
        theme="dark"
        richColors
        closeButton
        expand
        visibleToasts={6}
        toastOptions={{
          style: {
            fontSize: '12px',
          },
        }}
      />
    </QueryClientProvider>
  );
}
