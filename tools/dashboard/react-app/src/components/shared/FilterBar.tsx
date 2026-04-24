interface FilterBarProps {
  id?: string;
  filters: { value: string; label: string }[];
  active: string;
  onChange: (value: string) => void;
  onRefresh?: () => void;
  style?: React.CSSProperties;
}

export function FilterBar({ id, filters, active, onChange, onRefresh, style }: FilterBarProps) {
  return (
    <div className="filter-bar" id={id} style={style} onClick={e => {
      const btn = (e.target as HTMLElement).closest('.filter-btn') as HTMLElement | null;
      if (!btn) return;
      const val = btn.dataset.filter;
      if (val) onChange(val);
    }}>
      {filters.map(f => (
        <button
          key={f.value}
          className={`filter-btn${active === f.value ? ' active' : ''}`}
          data-filter={f.value}
        >
          {f.label}
        </button>
      ))}
      {onRefresh && (
        <button className="refresh-btn" onClick={e => { e.stopPropagation(); onRefresh(); }}>
          Refresh
        </button>
      )}
    </div>
  );
}
