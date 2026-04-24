import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { api } from '@/api/client';
import type { SettingsGroup, SettingsField } from '@/api/client';
import { Wizard } from './Wizard';

const REDACT = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';

type JSONScalar = string | number | boolean | null | undefined;

function getDotted(obj: unknown, dotted: string): JSONScalar {
  const parts = dotted.split('.');
  let node: unknown = obj;
  for (const k of parts) {
    if (!node || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[k];
  }
  if (node === null) return null;
  if (typeof node === 'object') return undefined;
  return node as JSONScalar;
}

function valueToString(v: JSONScalar): string {
  if (v === null || v === undefined) return '';
  return String(v);
}

function stringToValue(type: SettingsField['type'], s: string): string | number | boolean {
  if (type === 'toggle') return s === 'true';
  if (type === 'number') {
    const n = Number(s);
    return isNaN(n) ? s : n;
  }
  return s;
}

export function SettingsTab() {
  const [schema, setSchema] = useState<SettingsGroup[]>([]);
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [configPath, setConfigPath] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string | number | boolean>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // First-run wizard state. Auto-shows when setup.completed_at is unset, or
  // when the URL hash is #setup (bootstrap.command sends users here).
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardChecked, setWizardChecked] = useState(false);
  const [wizardCompletedAt, setWizardCompletedAt] = useState<string | null>(null);

  const refreshWizardStatus = useCallback(async () => {
    try {
      const status = await api.setupStatus();
      setWizardCompletedAt(status.wizard_completed_at);
      return status;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const status = await refreshWizardStatus();
      if (cancelled) return;
      const hashSetup = typeof window !== 'undefined' && window.location.hash === '#setup';
      if (status && (!status.wizard_completed_at || hashSetup)) {
        setWizardOpen(true);
      }
      setWizardChecked(true);
    })();
    return () => { cancelled = true; };
  }, [refreshWizardStatus]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.settings();
      setSchema(d.schema || []);
      setConfig(d.config || {});
      setConfigPath(d.config_path || '');
      const initial = new Set<string>();
      (d.schema || []).forEach(g => { if (g.collapsed) initial.add(g.key); });
      setCollapsedGroups(initial);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const dirtyCount = Object.keys(edits).length;

  const onSave = async () => {
    if (dirtyCount === 0) return;
    setSaving(true);
    try {
      await api.settingsUpdate(edits);
      setEdits({});
      setSavedAt(Date.now());
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const updateField = useCallback((field: SettingsField, raw: string) => {
    const current = getDotted(config, field.path);
    const currentStr = valueToString(current);
    setEdits(prev => {
      const next = { ...prev };
      if (raw === currentStr) {
        delete next[field.path];
      } else {
        next[field.path] = stringToValue(field.type, raw);
      }
      return next;
    });
  }, [config]);

  const toggleGroup = (key: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const timezoneOptions = useMemo(() => {
    const youGroup = schema.find(g => g.key === 'you');
    const tzField = youGroup?.fields.find(f => f.path === 'identity.timezone');
    const opts = tzField?.options || [];
    return opts.map(o => ({ value: String(o.value), label: o.label }));
  }, [schema]);

  const closeWizard = async () => {
    setWizardOpen(false);
    if (typeof window !== 'undefined' && window.location.hash === '#setup') {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    await Promise.all([load(), refreshWizardStatus()]);
    // Tell App.tsx to re-check setup state and unlock non-Settings tabs.
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('wizard:completed'));
    }
  };

  const restartWizard = async () => {
    try { await api.wizardReset(); } catch { /* best-effort */ }
    setWizardCompletedAt(null);
    setWizardOpen(true);
  };

  if (loading && schema.length === 0) return <div style={{ padding: 24, color: '#888' }}>Loading settings...</div>;

  return (
    <div style={{ padding: '0 24px 48px', maxWidth: 880, margin: '0 auto' }}>
      <div style={{
        position: 'sticky',
        top: 0,
        background: 'var(--bg, #0d0d10)',
        zIndex: 10,
        padding: '16px 0 12px',
        marginBottom: 16,
        borderBottom: '1px solid #1f1f22',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 20, color: '#eee' }}>Settings</h2>
          <div style={{ color: '#666', fontSize: 11, fontFamily: 'ui-monospace,monospace', marginTop: 2 }}>
            {configPath}
          </div>
        </div>
        <div style={{ flex: 1 }} />
        {dirtyCount > 0 && (
          <span style={{ color: '#4ade80', fontSize: 12 }}>{dirtyCount} unsaved</span>
        )}
        {savedAt && Date.now() - savedAt < 3000 && (
          <span style={{ color: '#4ade80', fontSize: 12 }}>saved</span>
        )}
        <button
          onClick={() => setEdits({})}
          disabled={dirtyCount === 0 || saving}
          style={ghostBtn(dirtyCount === 0 || saving)}
        >
          Reset
        </button>
        <button
          onClick={onSave}
          disabled={dirtyCount === 0 || saving}
          style={primaryBtn(dirtyCount === 0 || saving)}
        >
          {saving ? 'Saving...' : `Save${dirtyCount > 0 ? ` (${dirtyCount})` : ''}`}
        </button>
      </div>

      {error && (
        <div style={{
          padding: '10px 14px',
          marginBottom: 16,
          border: '1px solid #7f1d1d',
          background: 'rgba(127,29,29,0.15)',
          color: '#f87171',
          borderRadius: 8,
          fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {wizardOpen && (
        <Wizard
          onClose={closeWizard}
          config={config}
          timezoneOptions={timezoneOptions}
        />
      )}

      {wizardChecked && !wizardOpen && (
        <WizardCallout
          completedAt={wizardCompletedAt}
          onOpen={restartWizard}
        />
      )}

      {wizardChecked && <DaemonsPanel />}

      {schema.map(group => {
        const collapsed = collapsedGroups.has(group.key);
        const dirtyInGroup = group.fields.filter(f => f.path in edits).length;
        return (
          <section key={group.key} style={groupCard}>
            <header
              onClick={() => toggleGroup(group.key)}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 10,
                cursor: 'pointer',
                userSelect: 'none',
                padding: '14px 18px',
                borderBottom: collapsed ? 'none' : '1px solid #1f1f22',
              }}
            >
              <span style={{ color: '#666', fontSize: 11, width: 12 }}>
                {collapsed ? '\u25B8' : '\u25BE'}
              </span>
              <h3 style={{ margin: 0, fontSize: 14, color: '#eee', fontWeight: 600 }}>
                {group.label}
              </h3>
              {dirtyInGroup > 0 && (
                <span style={{ color: '#4ade80', fontSize: 11 }}>· {dirtyInGroup} unsaved</span>
              )}
              {group.description && !collapsed && (
                <span style={{ color: '#888', fontSize: 12, fontWeight: 400, marginLeft: 4 }}>
                  {group.description}
                </span>
              )}
            </header>
            {!collapsed && (
              <div style={{ padding: '8px 0' }}>
                {group.fields.map(field => (
                  <FieldRow
                    key={field.path}
                    field={field}
                    config={config}
                    edits={edits}
                    onChange={raw => updateField(field, raw)}
                  />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

const groupCard: React.CSSProperties = {
  border: '1px solid #1f1f22',
  borderRadius: 10,
  background: '#111114',
  marginBottom: 14,
  overflow: 'hidden',
};

function formatCompletedAt(iso: string | null): string {
  if (!iso) return 'never run';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const now = Date.now();
    const diffSec = Math.max(0, Math.round((now - d.getTime()) / 1000));
    if (diffSec < 60) return 'just now';
    if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
    const days = Math.round(diffSec / 86400);
    if (days < 30) return `${days}d ago`;
    return d.toISOString().slice(0, 10);
  } catch {
    return iso;
  }
}

function WizardCallout({ completedAt, onOpen }: {
  completedAt: string | null;
  onOpen: () => void;
}) {
  const neverRun = !completedAt;
  return (
    <section
      style={{
        border: '1px solid ' + (neverRun ? '#16a34a' : '#2a2a2e'),
        background: neverRun ? 'rgba(22,163,74,0.08)' : '#111114',
        borderRadius: 10,
        padding: '14px 18px',
        marginBottom: 14,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
      }}
    >
      <div
        style={{
          fontSize: 20,
          lineHeight: 1,
          width: 32,
          height: 32,
          borderRadius: 8,
          background: neverRun ? '#15803d' : '#1a1a1d',
          color: neverRun ? '#fff' : '#aaa',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
        aria-hidden
      >
        {'\u2728'}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: '#eee', fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
          Setup wizard
        </div>
        <div style={{ color: '#888', fontSize: 12 }}>
          {neverRun
            ? 'Guided walk-through to wire Telegram, Claude CLI, Obsidian, and enable background jobs.'
            : `Last completed ${formatCompletedAt(completedAt)}. Re-run to reconfigure integrations or re-enable crons.`}
        </div>
      </div>
      <button
        onClick={onOpen}
        style={{
          background: '#15803d',
          color: '#fff',
          border: '1px solid #16a34a',
          borderRadius: 6,
          padding: '8px 16px',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          flexShrink: 0,
        }}
      >
        {neverRun ? 'Start wizard' : 'Open wizard'}
      </button>
    </section>
  );
}

type DaemonRow = {
  label: string;
  name: string;
  path: string;
  loaded: boolean;
  pid: number | null;
  last_exit: number | null;
  running: boolean;
};

function DaemonsPanel() {
  const [daemons, setDaemons] = useState<DaemonRow[] | null>(null);
  const [prefix, setPrefix] = useState('');
  const [launchDir, setLaunchDir] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmSelf, setConfirmSelf] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.daemons();
      setDaemons(d.daemons);
      setPrefix(d.prefix || '');
      setLaunchDir(d.launch_agents_dir || '');
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setDaemons([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const restart = async (row: DaemonRow) => {
    setBusy(row.label);
    setMsg(null);
    try {
      const r = await api.daemonRestart(row.label);
      if (r.detached) {
        setMsg(r.note || `${row.name} restart scheduled — reconnecting...`);
        // Poll until the socket comes back; the page will typically auto-reload.
        setTimeout(() => { load(); }, 2500);
      } else if (r.ok) {
        setMsg(`${row.name} restarted`);
        await load();
      } else {
        setErr(r.error || 'restart failed');
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setConfirmSelf(null);
    }
  };

  if (daemons === null) {
    return (
      <section style={groupCard}>
        <div style={{ padding: '14px 18px', color: '#888', fontSize: 13 }}>
          Loading daemons...
        </div>
      </section>
    );
  }

  if (daemons.length === 0) {
    return (
      <section style={groupCard}>
        <div style={{ padding: '14px 18px' }}>
          <div style={{ color: '#eee', fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
            Daemons
          </div>
          <div style={{ color: '#888', fontSize: 12 }}>
            No installed agents matching <code style={{ color: '#aaa' }}>{prefix || '<prefix>'}.*.plist</code>
            {' '}in <code style={{ color: '#aaa' }}>{launchDir || '~/Library/LaunchAgents'}</code>. Run <code style={{ color: '#aaa' }}>./setup.sh</code> or use the wizard to install them.
          </div>
          {err && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{err}</div>}
        </div>
      </section>
    );
  }

  return (
    <section style={groupCard}>
      <header style={{ padding: '14px 18px', borderBottom: '1px solid #1f1f22' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: '#eee', fontWeight: 600 }}>
            Daemons
          </h3>
          <span style={{ color: '#888', fontSize: 12, fontWeight: 400 }}>
            launchd agents — restart without a terminal
          </span>
          <div style={{ flex: 1 }} />
          <button onClick={load} style={ghostBtn(false)} disabled={busy !== null}>
            Refresh
          </button>
        </div>
        <div style={{ color: '#666', fontSize: 11, fontFamily: 'ui-monospace,monospace', marginTop: 6 }}>
          {launchDir}
        </div>
      </header>

      {msg && (
        <div style={{
          margin: '8px 12px 0', padding: '8px 12px',
          border: '1px solid #15803d', background: 'rgba(22,163,74,0.1)',
          color: '#86efac', borderRadius: 6, fontSize: 12,
        }}>{msg}</div>
      )}
      {err && (
        <div style={{
          margin: '8px 12px 0', padding: '8px 12px',
          border: '1px solid #7f1d1d', background: 'rgba(127,29,29,0.15)',
          color: '#f87171', borderRadius: 6, fontSize: 12,
        }}>{err}</div>
      )}

      <div style={{ padding: '4px 0' }}>
        {daemons.map(row => {
          const isSelf = row.label.endsWith('.webhook-server');
          const rowBusy = busy === row.label;
          const confirming = confirmSelf === row.label;
          return (
            <div key={row.label} style={{
              padding: '10px 18px',
              display: 'flex', alignItems: 'center', gap: 12,
              borderTop: '1px solid #17171a',
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ color: '#eee', fontSize: 13, fontWeight: 500 }}>
                    {row.name}
                  </span>
                  <StatusDot running={row.running} loaded={row.loaded} />
                  <span style={{ color: '#888', fontSize: 11 }}>
                    {row.running
                      ? `running · PID ${row.pid}`
                      : row.loaded
                        ? 'loaded · idle'
                        : 'not loaded'}
                  </span>
                  {row.last_exit !== null && row.last_exit !== 0 && (
                    <span style={{ color: '#f59e0b', fontSize: 11 }}>
                      last exit {row.last_exit}
                    </span>
                  )}
                  {isSelf && (
                    <span style={{
                      color: '#f59e0b', fontSize: 10, fontWeight: 600,
                      border: '1px solid #78350f', background: 'rgba(245,158,11,0.1)',
                      borderRadius: 4, padding: '1px 6px',
                    }}>
                      SELF
                    </span>
                  )}
                </div>
                <div style={{ color: '#666', fontSize: 11, fontFamily: 'ui-monospace,monospace', marginTop: 2 }}>
                  {row.label}
                </div>
              </div>
              {confirming ? (
                <>
                  <span style={{ color: '#f59e0b', fontSize: 11 }}>
                    drops this session for ~5s
                  </span>
                  <button
                    onClick={() => setConfirmSelf(null)}
                    style={ghostBtn(rowBusy)}
                    disabled={rowBusy}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => restart(row)}
                    style={dangerBtn(rowBusy)}
                    disabled={rowBusy}
                  >
                    {rowBusy ? 'Restarting...' : 'Yes, restart'}
                  </button>
                </>
              ) : (
                <button
                  onClick={() => isSelf ? setConfirmSelf(row.label) : restart(row)}
                  style={isSelf ? dangerBtn(rowBusy) : primaryBtn(rowBusy)}
                  disabled={rowBusy || busy !== null}
                >
                  {rowBusy ? 'Restarting...' : 'Restart'}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function StatusDot({ running, loaded }: { running: boolean; loaded: boolean }) {
  const color = running ? '#22c55e' : loaded ? '#f59e0b' : '#6b7280';
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 8, height: 8, borderRadius: '50%',
        background: color,
        boxShadow: running ? '0 0 0 2px rgba(34,197,94,0.15)' : 'none',
      }}
    />
  );
}

function dangerBtn(disabled: boolean): React.CSSProperties {
  return {
    background: disabled ? '#1a1a1d' : '#991b1b',
    color: disabled ? '#666' : '#fff',
    border: '1px solid ' + (disabled ? '#2a2a2e' : '#b91c1c'),
    borderRadius: 6,
    padding: '6px 14px',
    fontSize: 12,
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
  };
}

function ghostBtn(disabled: boolean): React.CSSProperties {
  return {
    background: '#1a1a1d',
    color: '#aaa',
    border: '1px solid #2a2a2e',
    borderRadius: 6,
    padding: '6px 12px',
    fontSize: 12,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1,
  };
}

function primaryBtn(disabled: boolean): React.CSSProperties {
  return {
    background: disabled ? '#1a1a1d' : '#15803d',
    color: disabled ? '#666' : '#fff',
    border: '1px solid ' + (disabled ? '#2a2a2e' : '#16a34a'),
    borderRadius: 6,
    padding: '6px 14px',
    fontSize: 12,
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
  };
}

function FieldRow({ field, config, edits, onChange }: {
  field: SettingsField;
  config: Record<string, unknown>;
  edits: Record<string, string | number | boolean>;
  onChange: (raw: string) => void;
}) {
  const currentValue = getDotted(config, field.path);
  const dirty = field.path in edits;
  const display: string = dirty
    ? String(edits[field.path])
    : valueToString(currentValue);
  const isSecret = field.type === 'secret';
  const showRedactedPlaceholder = isSecret && !dirty && display === REDACT;

  return (
    <div style={{
      padding: '10px 18px',
      borderLeft: dirty ? '2px solid #4ade80' : '2px solid transparent',
      background: dirty ? 'rgba(74,222,128,0.04)' : 'transparent',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        marginBottom: field.description ? 4 : 0,
      }}>
        <label style={{
          flex: '0 0 220px',
          fontSize: 13,
          color: '#ddd',
          fontWeight: 500,
        }}>
          {field.label}
          {isSecret && (
            <span style={{ color: '#f59e0b', marginLeft: 6, fontSize: 10, fontWeight: 400 }}>
              SECRET
            </span>
          )}
        </label>
        <div style={{ flex: 1, minWidth: 0 }}>
          <FieldWidget
            field={field}
            value={display}
            redacted={showRedactedPlaceholder}
            onChange={onChange}
          />
        </div>
      </div>
      {field.description && (
        <div style={{
          marginLeft: 232,
          color: '#777',
          fontSize: 11,
          lineHeight: 1.5,
        }}>
          {field.description}
        </div>
      )}
    </div>
  );
}

function FieldWidget({ field, value, redacted, onChange }: {
  field: SettingsField;
  value: string;
  redacted: boolean;
  onChange: (raw: string) => void;
}) {
  if (field.type === 'toggle') {
    const checked = value === 'true';
    return (
      <button
        type="button"
        onClick={() => onChange(checked ? 'false' : 'true')}
        style={{
          width: 38,
          height: 22,
          borderRadius: 11,
          border: 'none',
          padding: 0,
          background: checked ? '#15803d' : '#3a3a3d',
          position: 'relative',
          cursor: 'pointer',
          transition: 'background 0.15s',
        }}
        aria-pressed={checked}
      >
        <span style={{
          position: 'absolute',
          top: 2,
          left: checked ? 18 : 2,
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: '#fff',
          transition: 'left 0.15s',
        }} />
      </button>
    );
  }

  if (field.type === 'select' && field.options) {
    return (
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={inputStyle}
      >
        {field.options.map(opt => (
          <option key={String(opt.value)} value={String(opt.value)}>
            {opt.label}
          </option>
        ))}
      </select>
    );
  }

  if (field.type === 'secret') {
    return <SecretInput value={value} redacted={redacted} onChange={onChange} />;
  }

  if (field.type === 'path') {
    return <PathInput value={value} onChange={onChange} />;
  }

  if (field.type === 'number') {
    return (
      <input
        type="number"
        value={value}
        onChange={e => onChange(e.target.value)}
        style={inputStyle}
      />
    );
  }

  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      style={inputStyle}
    />
  );
}

function SecretInput({ value, redacted, onChange }: {
  value: string;
  redacted: boolean;
  onChange: (raw: string) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <input
        type={revealed ? 'text' : 'password'}
        value={redacted ? '' : value}
        placeholder={redacted ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022 (set, hidden)' : 'not set'}
        onChange={e => onChange(e.target.value)}
        style={{ ...inputStyle, flex: 1 }}
      />
      <button
        type="button"
        onClick={() => setRevealed(r => !r)}
        title={revealed ? 'Hide' : 'Reveal what you typed'}
        style={ghostBtn(false)}
      >
        {revealed ? 'hide' : 'show'}
      </button>
      {value && !redacted && (
        <button
          type="button"
          onClick={() => onChange('')}
          title="Clear this secret"
          style={ghostBtn(false)}
        >
          clear
        </button>
      )}
    </div>
  );
}

function PathInput({ value, onChange }: { value: string; onChange: (raw: string) => void }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  return (
    <>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          style={{ ...inputStyle, flex: 1, fontFamily: 'ui-monospace,monospace' }}
        />
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          style={ghostBtn(false)}
        >
          Browse...
        </button>
      </div>
      {pickerOpen && (
        <FolderPicker
          initialPath={value || '~'}
          onPick={p => { onChange(p); setPickerOpen(false); }}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </>
  );
}

function FolderPicker({ initialPath, onPick, onClose }: {
  initialPath: string;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [entries, setEntries] = useState<{ name: string; path: string }[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [resolvedPath, setResolvedPath] = useState(initialPath);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (path: string) => {
    setLoading(true);
    setErr(null);
    try {
      const d = await api.settingsBrowse(path);
      setEntries(d.entries);
      setParent(d.parent);
      setResolvedPath(d.path);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(currentPath); }, [currentPath, load]);

  return (
    <div
      ref={overlayRef}
      onClick={e => { if (e.target === overlayRef.current) onClose(); }}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(0,0,0,0.6)',
        zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div style={{
        background: '#16161a',
        border: '1px solid #2a2a2e',
        borderRadius: 12,
        width: 540, maxHeight: '70vh',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid #1f1f22' }}>
          <div style={{ fontSize: 13, color: '#aaa', marginBottom: 6 }}>Pick a folder</div>
          <input
            type="text"
            value={currentPath}
            onChange={e => setCurrentPath(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') load(currentPath); }}
            placeholder="~/Documents/..."
            style={{ ...inputStyle, width: '100%', fontFamily: 'ui-monospace,monospace' }}
          />
          <div style={{ color: '#666', fontSize: 11, marginTop: 4, fontFamily: 'ui-monospace,monospace' }}>
            {resolvedPath}
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
          {loading && <div style={{ padding: 16, color: '#888', fontSize: 13 }}>Loading...</div>}
          {err && <div style={{ padding: 16, color: '#f87171', fontSize: 13 }}>{err}</div>}
          {!loading && !err && parent && (
            <button
              type="button"
              onClick={() => setCurrentPath(parent)}
              style={folderRowBtn}
            >
              <span style={{ color: '#666', marginRight: 10 }}>\u2191</span>..
            </button>
          )}
          {!loading && !err && entries.map(entry => (
            <button
              key={entry.path}
              type="button"
              onClick={() => setCurrentPath(entry.path)}
              style={folderRowBtn}
            >
              <span style={{ color: '#666', marginRight: 10 }}>/</span>{entry.name}
            </button>
          ))}
          {!loading && !err && entries.length === 0 && parent !== null && (
            <div style={{ padding: 16, color: '#666', fontSize: 12, fontStyle: 'italic' }}>
              (no subfolders)
            </div>
          )}
        </div>
        <div style={{
          padding: '12px 18px',
          borderTop: '1px solid #1f1f22',
          display: 'flex', gap: 8, justifyContent: 'flex-end',
        }}>
          <button type="button" onClick={onClose} style={ghostBtn(false)}>Cancel</button>
          <button type="button" onClick={() => onPick(resolvedPath)} style={primaryBtn(false)}>
            Pick this folder
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: '#0d0d10',
  color: '#eee',
  border: '1px solid #2a2a2e',
  borderRadius: 6,
  padding: '6px 10px',
  fontSize: 12,
  width: '100%',
  outline: 'none',
};

const folderRowBtn: React.CSSProperties = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  background: 'transparent',
  border: 'none',
  color: '#ddd',
  padding: '8px 18px',
  fontSize: 13,
  cursor: 'pointer',
};
