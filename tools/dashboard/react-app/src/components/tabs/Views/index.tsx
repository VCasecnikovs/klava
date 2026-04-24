import { useState, useMemo, useEffect } from 'react';
import { useViews } from '@/api/queries';
import { KPIRow } from '@/components/shared/KPIRow';
import { ViewsViewer } from './ViewsViewer';
import { esc } from '@/lib/utils';
import { showToast } from '@/components/shared/Toast';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ViewsDataObj = any;

interface Props {
  pendingView?: { url?: string; filename?: string; title: string } | null;
  onPendingViewConsumed?: () => void;
}

export function ViewsTab({ pendingView, onPendingViewConsumed }: Props = {}) {
  const { data, refetch } = useViews(true);
  const [viewing, setViewing] = useState<{ filename?: string; url?: string; title: string } | null>(null);

  // Consume pending view passed down from App (set by SocketIO or CustomEvent)
  useEffect(() => {
    if (pendingView) {
      setViewing(pendingView);
      onPendingViewConsumed?.();
    }
  }, [pendingView, onPendingViewConsumed]);

  const kpis = useMemo(() => {
    if (!data) return [];
    const m = (data as ViewsDataObj).metrics || {};
    return [
      { val: m.total || 0, label: 'Total Views' },
      { val: m.today || 0, label: 'Today' },
    ];
  }, [data]);

  if (!data) return <div className="empty">Loading views...</div>;

  // Viewer mode
  if (viewing) {
    return (
      <ViewsViewer
        filename={viewing.filename}
        url={viewing.url}
        title={viewing.title}
        onBack={() => setViewing(null)}
      />
    );
  }

  // List mode
  const views: ViewsDataObj[] = (data as ViewsDataObj).views || [];

  return (
    <>
      <KPIRow kpis={kpis} />

      <div className="section-heading" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        HTML Views
        <button
          className="filter-btn"
          onClick={() => { refetch(); showToast('Refreshing...'); }}
          style={{ fontSize: 11, padding: '2px 8px', cursor: 'pointer' }}
        >
          Refresh
        </button>
      </div>

      {views.length === 0 ? (
        <div className="empty">No views generated yet. Use html-view skill to create views.</div>
      ) : (
        <div>
          {views.map((v: ViewsDataObj) => (
            <div
              key={v.filename}
              className="panel"
              style={{ marginBottom: 8, cursor: 'pointer', transition: 'border-color 0.15s' }}
              onClick={() => setViewing({ filename: v.filename, title: v.title })}
              onMouseOver={e => (e.currentTarget.style.borderColor = 'var(--border-hover)')}
              onMouseOut={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{
                    fontWeight: 600, color: 'var(--text)', marginBottom: 2,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {esc(v.title)}
                  </div>
                  {v.subtitle && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                      {esc(v.subtitle)}
                    </div>
                  )}
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
                    {esc(v.filename)}
                  </div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {esc(v.modified_ago)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {v.size_kb}KB
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
