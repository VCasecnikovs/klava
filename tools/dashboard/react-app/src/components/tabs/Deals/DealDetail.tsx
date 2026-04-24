import { esc } from '@/lib/utils';
import { MdLink } from '@/components/shared/MdLink';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DealObj = any;

function fmtCurrency(val: number | null | undefined): string {
  if (val == null) return '-';
  if (val >= 1000000) return '$' + (val / 1000000).toFixed(1) + 'M';
  if (val >= 1000) return '$' + val.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return '$' + val.toFixed(0);
}

interface Props {
  deal: DealObj;
  onBack: () => void;
}

export function DealDetail({ deal: d, onBack }: Props) {
  // Markdown links (open in Views tab)
  const mdLinks: { label: string; path: string }[] = [];
  if (d.file_path) {
    mdLinks.push({ label: 'Deal Note', path: d.file_path + '.md' });
  }
  if (d.lead_clean && d.lead_clean !== 'Unknown') {
    mdLinks.push({ label: `Org: ${d.lead_clean}`, path: `Organizations/${d.lead_clean}.md` });
  }
  if (d.referrer_clean && d.referrer_clean !== 'Unknown') {
    mdLinks.push({ label: `Ref: ${d.referrer_clean}`, path: `People/${d.referrer_clean}.md` });
  }
  // External links
  const extLinks: { label: string; href: string }[] = [];
  if (d.telegram_chat) {
    extLinks.push({ label: 'Telegram', href: `https://t.me/${d.telegram_chat}` });
  }

  const fields = [
    { label: 'Stage', value: d.stage },
    { label: 'Value', value: fmtCurrency(d.value) },
    { label: 'MRR', value: fmtCurrency(d.mrr) },
    { label: 'Product', value: d.product || '-' },
    { label: 'Owner', value: d.owner || '-' },
    { label: 'Deal Size', value: d.deal_size || '-' },
    { label: 'Deal Type', value: d.deal_type || '-' },
    { label: 'Payment Type', value: d.payment_type || '-' },
    { label: 'Last Contact', value: d.last_contact || '-' },
    { label: 'Follow-up', value: d.follow_up || '-' },
    { label: 'Days in Stage', value: d.days_in_stage != null ? d.days_in_stage + 'd' : '-' },
    { label: 'Decision Maker', value: d.decision_maker || '-' },
    { label: 'Lead', value: d.lead_clean || '-' },
    { label: 'Referrer', value: d.referrer_clean || '-' },
  ];
  if (d.next_action) fields.push({ label: 'Next Action', value: d.next_action });

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button
          onClick={onBack}
          style={{
            background: 'var(--bg-elevated)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-xs)',
            padding: '4px 12px', cursor: 'pointer', fontSize: 13,
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          <span style={{ fontSize: 16 }}>&larr;</span> Back
        </button>
        <span style={{ fontWeight: 600, fontSize: 16 }}>{esc(d.name)}</span>
      </div>

      {(mdLinks.length > 0 || extLinks.length > 0) && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
          {mdLinks.map((l, i) => (
            <MdLink key={`md-${i}`} path={l.path} className="deal-link">{l.label}</MdLink>
          ))}
          {extLinks.map((l, i) => (
            <a key={`ext-${i}`} className="deal-link" href={l.href} target="_blank" rel="noopener noreferrer">
              {l.label}
            </a>
          ))}
        </div>
      )}

      {d.is_priority && (
        <div style={{ marginBottom: 12 }}>
          <span style={{
            background: 'var(--blue-dim)', color: 'var(--blue)',
            padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
          }}>PRIORITY DEAL</span>
        </div>
      )}
      {d.overdue && (
        <div style={{ marginBottom: 12 }}>
          <span style={{
            background: 'var(--red-dim)', color: 'var(--red)',
            padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
          }}>OVERDUE {Math.abs(d.days_until_follow_up || 0)}d</span>
        </div>
      )}

      <div className="deal-detail-grid">
        {fields.map((f, i) => (
          <div className="deal-detail-field" key={i}>
            <div className="ddf-label">{esc(f.label)}</div>
            <div className="ddf-value">{esc(f.value)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
