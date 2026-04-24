interface KPI {
  val: number | string;
  label: string;
  color?: string;
}

export function KPIRow({ kpis }: { kpis: KPI[] }) {
  return (
    <div className="kpi-row">
      {kpis.map((k, i) => (
        <div className="kpi" key={i}>
          <div className="kpi-val" style={{ color: k.color || 'var(--text)' }}>{k.val}</div>
          <div className="kpi-label">{k.label}</div>
        </div>
      ))}
    </div>
  );
}
