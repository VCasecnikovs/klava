import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { DashboardData } from '@/api/types';

const TOAST_IDS = {
  services: 'alert-services',
  cron: 'alert-cron',
} as const;

// Stable fingerprint of the current alert content. If the set of failures
// changes, the hash changes and the toast re-shows even if the previous
// one was dismissed. If the content is identical on the next poll we
// leave the existing toast alone (no flicker, no zombie re-surface).
function hashServices(data?: DashboardData): string {
  const down = (data?.services || []).filter(s => !s.running);
  return down.map(s => s.label || s.name).sort().join('|');
}

function hashCron(data?: DashboardData): string {
  const fails = data?.failing_jobs || [];
  return fails.map(f => `${f.job_id}:${f.consecutive}`).sort().join('|');
}

/**
 * AlertBanners is headless — it drives sonner toasts via useEffect.
 * Nothing renders inline; the Toaster component (mounted at App root)
 * paints the stacked cards. See https://sonner.emilkowal.ski for API.
 */
export function AlertBanners({ data }: { data?: DashboardData }) {
  // Remember the content hash of each toast after the user manually
  // dismissed it. If data changes to a *different* set of failures,
  // hash no longer matches and we re-emit.
  const dismissedRef = useRef<Record<string, string>>({});
  const [cronExpanded, setCronExpanded] = useState(false);

  // Services down (red)
  useEffect(() => {
    const h = hashServices(data);
    if (!h) {
      toast.dismiss(TOAST_IDS.services);
      return;
    }
    if (dismissedRef.current.services === h) return;

    const down = (data?.services || []).filter(s => !s.running);
    toast.error(
      <div>
        <strong>Services down:</strong>{' '}
        {down.map(s => s.label || s.name).join(', ')}
      </div>,
      {
        id: TOAST_IDS.services,
        duration: Infinity,
        onDismiss: () => { dismissedRef.current.services = h; },
        closeButton: true,
      }
    );
  }, [data]);

  // Failing CRON (red) — with expandable error details
  useEffect(() => {
    const h = hashCron(data);
    if (!h) {
      toast.dismiss(TOAST_IDS.cron);
      return;
    }
    if (dismissedRef.current.cron === h) return;

    const fails = data?.failing_jobs || [];
    toast.error(
      <div style={{ width: '100%' }}>
        <div
          onClick={() => setCronExpanded(v => !v)}
          style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <strong>Failing CRON:</strong>
          <span style={{ flex: 1 }}>
            {fails.map(f => `${f.job_id} (${f.consecutive}x)`).join(', ')}
          </span>
          <span
            style={{
              fontSize: 9,
              transition: 'transform 0.2s',
              transform: cronExpanded ? 'rotate(90deg)' : undefined,
              opacity: 0.6,
            }}
          >
            ▶
          </span>
        </div>
        {cronExpanded && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: 11 }}>
            {fails.map((f, i) => (
              <div key={i} style={{ marginBottom: 6 }}>
                <span style={{ fontWeight: 600, marginRight: 8 }}>{f.job_id}</span>
                <span style={{ opacity: 0.6 }}>
                  {f.consecutive}x failures{f.ago ? ` · ${f.ago}` : ''}
                </span>
                <div style={{ fontFamily: 'var(--mono, monospace)', fontSize: 10, opacity: 0.8, marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 60, overflowY: 'auto' }}>
                  {f.last_error || f.error || 'Unknown error'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>,
      {
        id: TOAST_IDS.cron,
        duration: Infinity,
        onDismiss: () => { dismissedRef.current.cron = h; },
        closeButton: true,
      }
    );
  }, [data, cronExpanded]);

  // Stale data sources are no longer surfaced as toasts - the `stale-sources-tasks`
  // cron job creates Klava tasks instead, so they show up in Tasks with proper
  // context rather than blocking the dashboard header.

  return null;
}
