import { useState } from 'react';
import { usePlans } from '@/api/queries';
import { renderChatMD } from '@/components/tabs/Chat/ChatMarkdown';

interface Plan {
  name: string;
  content: string;
  modified: string;
  size: number;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function PlanCard({ plan, isExpanded, onToggle }: { plan: Plan; isExpanded: boolean; onToggle: () => void }) {
  const title = plan.content.split('\n').find(l => l.startsWith('# '))?.replace(/^#\s+/, '') || plan.name;

  return (
    <div className={`plan-card${isExpanded ? ' expanded' : ''}`}>
      <div className="plan-card-header" onClick={onToggle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 11, opacity: 0.4, transition: 'transform 0.15s', transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>&#9654;</span>
          <span className="plan-card-title">{title}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
          <span className="plan-card-meta">{timeAgo(plan.modified)}</span>
          <span className="plan-card-meta">{(plan.size / 1024).toFixed(1)}kb</span>
        </div>
      </div>
      {isExpanded && (
        <div
          className="plan-card-body"
          dangerouslySetInnerHTML={{ __html: renderChatMD(plan.content) }}
        />
      )}
    </div>
  );
}

export function PlansTab() {
  const { data } = usePlans(true);
  const [expandedIdx, setExpandedIdx] = useState<number>(0);

  if (!data) return <div className="empty">Loading plans...</div>;

  const plans: Plan[] = (data as any).plans || [];

  if (plans.length === 0) {
    return <div className="empty">No plans found in .claude/plans/</div>;
  }

  return (
    <div style={{ padding: '0 0 24px' }}>
      <div style={{ padding: '12px 0 8px', fontSize: 12, color: 'var(--text-muted)' }}>
        {plans.length} plans (sorted by last modified)
      </div>
      {plans.map((plan, i) => (
        <PlanCard
          key={plan.name}
          plan={plan}
          isExpanded={expandedIdx === i}
          onToggle={() => setExpandedIdx(expandedIdx === i ? -1 : i)}
        />
      ))}
    </div>
  );
}
