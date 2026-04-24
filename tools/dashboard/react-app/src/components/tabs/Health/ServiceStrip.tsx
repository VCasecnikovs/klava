import type { Service } from '@/api/types';

export function ServiceStrip({ services }: { services: Service[] }) {
  return (
    <div className="svc-strip">
      {services.map((s, i) => (
        <div className="svc-chip" key={i}>
          <div className={`svc-dot ${s.running ? 'on' : 'off'}`} />
          <span>{s.label || s.name}</span>
          {s.pid && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
              pid:{s.pid}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
