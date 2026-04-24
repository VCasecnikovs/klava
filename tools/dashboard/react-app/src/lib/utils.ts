export function esc(s: unknown): string {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

export function fmt(n: unknown): string {
  if (typeof n !== 'number') return String(n || 0);
  if (!Number.isInteger(n)) return n.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n.toLocaleString('en');
}

export function fmtCost(v: number | undefined | null): string {
  if (!v || v === 0) return '$0';
  if (v < 0.01) return '$' + v.toFixed(4);
  return '$' + v.toFixed(2);
}

export function dateLabel(str: string): string {
  try {
    const d = new Date(str + 'T00:00:00');
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diff = (today.getTime() - d.getTime()) / 86400000;
    if (diff < 1) return 'Today';
    if (diff < 2) return 'Yesterday';
    return d.toLocaleDateString('en', { month: 'short', day: 'numeric' });
  } catch {
    return str;
  }
}

export function toDateKey(ts: string | undefined): string {
  if (!ts) return 'unknown';
  return ts.substring(0, 10);
}

export function toTime(ts: string | undefined): string {
  if (!ts) return '';
  const m = ts.match(/(\d{2}:\d{2})/);
  return m ? m[1] : '';
}

export function sparkSVG(series: number[] | undefined, color: string): string {
  if (!series || series.length < 2) return '';
  const w = 64, h = 28, pad = 2;
  const max = Math.max(...series) || 1;
  const min = Math.min(...series);
  const range = max - min || 1;
  const pts = series.map((v, i) => {
    const x = pad + (i / (series.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / range) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const area = pts.join(' ') + ` ${w - pad},${h} ${pad},${h}`;
  return `<svg class="growth-sparkline" viewBox="0 0 ${w} ${h}">
    <polygon class="spark-area" points="${area}" fill="${color}" />
    <polyline points="${pts.join(' ')}" stroke="${color}" />
  </svg>`;
}

export function timeAgo(ts: string): string {
  if (!ts) return '';
  const now = Date.now();
  const then = new Date(ts).getTime();
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
