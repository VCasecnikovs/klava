import { useState, useEffect, useCallback } from 'react';
import { api, type WizardAuthSnapshot } from '@/api/client';

type ProbeState = 'idle' | 'running' | 'ok' | 'fail';

interface ProbeResult {
  state: ProbeState;
  message?: string;
  hint?: string;
}

interface WizardProps {
  /** Called after the user finishes or dismisses the wizard. */
  onClose: () => void;
  /** Current config snapshot — used to prefill fields. */
  config: Record<string, unknown>;
  /** Supported timezones from the schema, for the dropdown. */
  timezoneOptions: Array<{ value: string; label: string }>;
}

type StepKey = 'intro' | 'identity' | 'telegram' | 'claude' | 'github' | 'google' | 'obsidian' | 'apikeys' | 'vadimgest' | 'crons' | 'done';

const STEP_ORDER: StepKey[] = ['intro', 'identity', 'telegram', 'claude', 'github', 'google', 'obsidian', 'apikeys', 'vadimgest', 'crons', 'done'];

function getDotted(obj: unknown, dotted: string): string {
  const parts = dotted.split('.');
  let node: unknown = obj;
  for (const k of parts) {
    if (!node || typeof node !== 'object') return '';
    node = (node as Record<string, unknown>)[k];
  }
  if (node === null || node === undefined) return '';
  return String(node);
}

export function Wizard({ onClose, config, timezoneOptions }: WizardProps) {
  const [step, setStep] = useState<StepKey>('intro');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Step 1 — Identity
  const [userName, setUserName] = useState(getDotted(config, 'identity.user_name'));
  const [assistantName, setAssistantName] = useState(getDotted(config, 'identity.assistant_name') || 'Klava');
  const [email, setEmail] = useState(getDotted(config, 'identity.email'));
  const [timezone, setTimezone] = useState(getDotted(config, 'identity.timezone') || 'UTC');

  // Step 2 — Telegram (optional)
  const [skipTelegram, setSkipTelegram] = useState(false);
  const [botToken, setBotToken] = useState(getDotted(config, 'telegram.bot_token'));
  const [chatId, setChatId] = useState(getDotted(config, 'telegram.chat_id'));
  const [tgProbe, setTgProbe] = useState<ProbeResult>({ state: 'idle' });

  // Step 3 — Claude auth
  const [claudeProbe, setClaudeProbe] = useState<ProbeResult>({ state: 'idle' });

  // Step 4 — Obsidian (optional)
  const [skipObsidian, setSkipObsidian] = useState(false);
  const [vaultPath, setVaultPath] = useState(getDotted(config, 'paths.obsidian_vault'));
  const [obsProbe, setObsProbe] = useState<ProbeResult>({ state: 'idle' });

  // Step 5 — Crons
  const [plists, setPlists] = useState<Array<{ label: string; path: string; loaded: boolean; name: string }>>([]);
  const [plistScanDir, setPlistScanDir] = useState('');
  const [plistPrefix, setPlistPrefix] = useState('');
  const [selectedPlists, setSelectedPlists] = useState<Set<string>>(new Set());
  const [plistsLoading, setPlistsLoading] = useState(false);
  const [plistResults, setPlistResults] = useState<Array<{ label: string; ok: boolean; error?: string }>>([]);

  const loadPlists = useCallback(async () => {
    setPlistsLoading(true);
    try {
      const d = await api.wizardListPlists();
      setPlists(d.plists || []);
      setPlistScanDir(d.launch_agents_dir || '');
      setPlistPrefix(d.prefix || '');
      // Default-select plists that aren't loaded yet, except tg-gateway which
      // is useless until Telegram is configured.
      const defaults = new Set<string>();
      (d.plists || []).forEach(p => {
        if (p.loaded) return;
        if (skipTelegram && p.name === 'tg-gateway') return;
        defaults.add(p.label);
      });
      setSelectedPlists(defaults);
    } finally {
      setPlistsLoading(false);
    }
  }, [skipTelegram]);

  useEffect(() => {
    if (step === 'crons') loadPlists();
  }, [step, loadPlists]);

  const idx = STEP_ORDER.indexOf(step);
  const goNext = () => setStep(STEP_ORDER[Math.min(idx + 1, STEP_ORDER.length - 1)]);
  const goBack = () => setStep(STEP_ORDER[Math.max(idx - 1, 0)]);

  // ── step handlers ──────────────────────────────────────────────────

  const saveIdentity = async () => {
    setSaving(true); setSaveError(null);
    try {
      await api.settingsUpdate({
        'identity.user_name': userName.trim(),
        'identity.assistant_name': assistantName.trim() || 'Klava',
        'identity.email': email.trim(),
        'identity.timezone': timezone,
      });
      goNext();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const testTelegram = async () => {
    setTgProbe({ state: 'running' });
    try {
      const n = Number(chatId);
      if (!botToken.trim() || !Number.isFinite(n)) {
        setTgProbe({ state: 'fail', message: 'Bot token and numeric chat_id required.' });
        return;
      }
      const r = await api.wizardTestTelegram(botToken.trim(), n);
      if (r.ok) {
        setTgProbe({ state: 'ok', message: `Delivered. Bot: @${r.bot_username}` });
      } else {
        setTgProbe({ state: 'fail', message: r.error || 'failed', hint: r.hint });
      }
    } catch (e) {
      setTgProbe({ state: 'fail', message: e instanceof Error ? e.message : String(e) });
    }
  };

  const saveTelegram = async () => {
    setSaving(true); setSaveError(null);
    try {
      if (skipTelegram) {
        goNext();
        return;
      }
      const updates: Record<string, unknown> = {};
      if (botToken.trim()) updates['telegram.bot_token'] = botToken.trim();
      const n = Number(chatId);
      if (Number.isFinite(n)) updates['telegram.chat_id'] = n;
      if (Object.keys(updates).length > 0) {
        await api.settingsUpdate(updates);
      }
      goNext();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const testClaude = async () => {
    setClaudeProbe({ state: 'running' });
    try {
      const r = await api.wizardTestClaude();
      if (r.ok) {
        setClaudeProbe({ state: 'ok', message: `Installed: ${r.version}` });
      } else {
        setClaudeProbe({ state: 'fail', message: r.error || 'failed', hint: r.hint });
      }
    } catch (e) {
      setClaudeProbe({ state: 'fail', message: e instanceof Error ? e.message : String(e) });
    }
  };

  const testObsidian = async (create = false) => {
    setObsProbe({ state: 'running' });
    try {
      const r = await api.wizardTestObsidian(vaultPath.trim(), create);
      if (r.ok) {
        const marker = r.has_obsidian_marker
          ? '.obsidian/ found'
          : r.md_count
            ? `${r.md_count} markdown files`
            : 'empty — Klava will populate it';
        setObsProbe({ state: 'ok', message: `${r.path} (${marker})` });
      } else {
        setObsProbe({
          state: 'fail',
          message: r.error || 'failed',
          hint: r.can_create ? 'create' : undefined,
        });
      }
    } catch (e) {
      setObsProbe({ state: 'fail', message: e instanceof Error ? e.message : String(e) });
    }
  };

  const saveObsidian = async () => {
    setSaving(true); setSaveError(null);
    try {
      if (!skipObsidian && vaultPath.trim()) {
        await api.settingsUpdate({ 'paths.obsidian_vault': vaultPath.trim() });
      }
      goNext();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const enableCrons = async () => {
    setSaving(true); setSaveError(null);
    setPlistResults([]);
    try {
      const labels = Array.from(selectedPlists);
      if (labels.length === 0) {
        goNext();
        return;
      }
      const r = await api.wizardEnableCrons(labels);
      setPlistResults(r.results || []);
      if (!r.ok) {
        setSaveError('Some launch agents failed to load — see per-row messages.');
        return;
      }
      goNext();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const finish = async () => {
    setSaving(true); setSaveError(null);
    try {
      await api.wizardComplete();
      onClose();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  // ── render ─────────────────────────────────────────────────────────

  return (
    <div style={wizardCard}>
      <header style={wizardHeader}>
        <div>
          <div style={{ color: '#9ca3af', fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase' }}>
            First-run setup · step {Math.max(idx, 0) + 1} of {STEP_ORDER.length}
          </div>
          <h2 style={{ margin: '4px 0 0', fontSize: 20, color: '#f5f5f5' }}>
            {TITLES[step]}
          </h2>
        </div>
        <button onClick={onClose} style={ghostBtn} title="Skip wizard and use the raw Settings form">
          Skip wizard
        </button>
      </header>

      <div style={stepDots}>
        {STEP_ORDER.map((s, i) => (
          <span
            key={s}
            style={{
              width: i === idx ? 22 : 8,
              height: 8,
              borderRadius: 4,
              background: i <= idx ? '#15803d' : '#2a2a2e',
              transition: 'all 0.15s',
            }}
          />
        ))}
      </div>

      <div style={stepBody}>
        {step === 'intro' && (
          <IntroStep onNext={goNext} />
        )}

        {step === 'identity' && (
          <IdentityStep
            userName={userName} setUserName={setUserName}
            assistantName={assistantName} setAssistantName={setAssistantName}
            email={email} setEmail={setEmail}
            timezone={timezone} setTimezone={setTimezone}
            timezoneOptions={timezoneOptions}
          />
        )}

        {step === 'telegram' && (
          <TelegramStep
            skip={skipTelegram} setSkip={setSkipTelegram}
            botToken={botToken} setBotToken={setBotToken}
            chatId={chatId} setChatId={setChatId}
            probe={tgProbe}
            onTest={testTelegram}
          />
        )}

        {step === 'claude' && (
          <ClaudeStep probe={claudeProbe} onTest={testClaude} />
        )}

        {step === 'github' && (
          <CliAuthStep
            method="gh"
            title="GitHub"
            blurb="Klava uses the GitHub CLI (gh) for issue syncing, PR work, and Vox Lab task management. Signs in via your browser — no tokens to paste."
            installCmd="brew install gh"
          />
        )}

        {step === 'google' && (
          <CliAuthStep
            method="gog"
            title="Google"
            blurb="Gmail drafts, Google Tasks, Calendar events, Drive file access — all gated behind a single OAuth flow via the gog CLI. Uses a shared OAuth client by default; see Advanced below to bring your own."
            installCmd="brew install gogcli"
            requiresAccount={true}
            accountPlaceholder="you@gmail.com"
            advanced={<GogCredentialsAdvanced />}
          />
        )}

        {step === 'obsidian' && (
          <ObsidianStep
            skip={skipObsidian} setSkip={setSkipObsidian}
            vaultPath={vaultPath} setVaultPath={setVaultPath}
            probe={obsProbe}
            onTest={testObsidian}
          />
        )}

        {step === 'apikeys' && (
          <ApiKeysStep />
        )}

        {step === 'vadimgest' && (
          <VadimgestStep />
        )}

        {step === 'crons' && (
          <CronsStep
            plists={plists}
            scanDir={plistScanDir}
            prefix={plistPrefix}
            selected={selectedPlists}
            setSelected={setSelectedPlists}
            loading={plistsLoading}
            results={plistResults}
          />
        )}

        {step === 'done' && (
          <DoneStep />
        )}
      </div>

      {saveError && (
        <div style={errorBanner}>{saveError}</div>
      )}

      <footer style={wizardFooter}>
        {idx > 0 && step !== 'done' && (
          <button onClick={goBack} disabled={saving} style={ghostBtn}>
            Back
          </button>
        )}
        <div style={{ flex: 1 }} />
        {step === 'intro' && (
          <button onClick={goNext} style={primaryBtn}>Let's go</button>
        )}
        {step === 'identity' && (
          <button
            onClick={saveIdentity}
            disabled={saving || !userName.trim() || !email.trim()}
            style={userName.trim() && email.trim() ? primaryBtn : disabledBtn}
          >
            {saving ? 'Saving…' : 'Save and continue'}
          </button>
        )}
        {step === 'telegram' && (
          <button
            onClick={saveTelegram}
            disabled={saving}
            style={primaryBtn}
          >
            {saving ? 'Saving…' : skipTelegram ? 'Skip and continue' : 'Save and continue'}
          </button>
        )}
        {step === 'claude' && (
          <button onClick={goNext} style={primaryBtn}>Continue</button>
        )}
        {step === 'github' && (
          <button onClick={goNext} style={primaryBtn}>Continue</button>
        )}
        {step === 'google' && (
          <button onClick={goNext} style={primaryBtn}>Continue</button>
        )}
        {step === 'obsidian' && (
          <button onClick={saveObsidian} disabled={saving} style={primaryBtn}>
            {saving ? 'Saving…' : skipObsidian ? 'Skip and continue' : 'Save and continue'}
          </button>
        )}
        {step === 'apikeys' && (
          <button onClick={goNext} style={primaryBtn}>Continue</button>
        )}
        {step === 'vadimgest' && (
          <button onClick={goNext} style={primaryBtn}>Continue</button>
        )}
        {step === 'crons' && (
          <button onClick={enableCrons} disabled={saving || plistsLoading} style={primaryBtn}>
            {saving ? 'Enabling…' : selectedPlists.size === 0 ? 'Skip and continue' : `Load ${selectedPlists.size} agent${selectedPlists.size === 1 ? '' : 's'}`}
          </button>
        )}
        {step === 'done' && (
          <button onClick={finish} disabled={saving} style={primaryBtn}>
            {saving ? 'Finishing…' : 'Finish'}
          </button>
        )}
      </footer>
    </div>
  );
}

// ── sub-steps ───────────────────────────────────────────────────────

function IntroStep({ onNext: _onNext }: { onNext: () => void }) {
  return (
    <div style={{ color: '#d0d0d0', lineHeight: 1.6, fontSize: 14 }}>
      <p style={{ marginTop: 0 }}>
        This wizard walks through the fields Klava needs to be useful. It should take about two minutes.
      </p>
      <ul style={{ paddingLeft: 20, color: '#aaa' }}>
        <li>Basic identity — your name, email, timezone</li>
        <li>Telegram — optional, for mobile notifications</li>
        <li>Claude Code CLI — verify it's installed and callable</li>
        <li>Obsidian vault — optional, for the knowledge base</li>
        <li>Scheduled jobs — load the launch agents that keep Klava running</li>
      </ul>
      <p style={{ color: '#888', fontSize: 12 }}>
        You can skip any optional step. Everything is reversible from the Settings form after you finish.
      </p>
    </div>
  );
}

function IdentityStep(p: {
  userName: string; setUserName: (v: string) => void;
  assistantName: string; setAssistantName: (v: string) => void;
  email: string; setEmail: (v: string) => void;
  timezone: string; setTimezone: (v: string) => void;
  timezoneOptions: Array<{ value: string; label: string }>;
}) {
  return (
    <div>
      <Field label="Your name" required>
        <input
          value={p.userName}
          onChange={e => p.setUserName(e.target.value)}
          placeholder="Your name"
          style={inputStyle}
          autoFocus
        />
      </Field>
      <Field label="What should Klava call itself?">
        <input
          value={p.assistantName}
          onChange={e => p.setAssistantName(e.target.value)}
          placeholder="Klava"
          style={inputStyle}
        />
      </Field>
      <Field label="Email" required>
        <input
          value={p.email}
          onChange={e => p.setEmail(e.target.value)}
          placeholder="you@example.com"
          type="email"
          style={inputStyle}
        />
      </Field>
      <Field label="Timezone">
        <select
          value={p.timezone}
          onChange={e => p.setTimezone(e.target.value)}
          style={inputStyle}
        >
          {p.timezoneOptions.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}

function TelegramStep(p: {
  skip: boolean; setSkip: (v: boolean) => void;
  botToken: string; setBotToken: (v: string) => void;
  chatId: string; setChatId: (v: string) => void;
  probe: ProbeResult;
  onTest: () => void;
}) {
  return (
    <div>
      <p style={hintText}>
        Telegram powers mobile notifications and lets you message Klava from your phone.
        Create a bot with <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" style={linkStyle}>@BotFather</a>, then
        get your numeric chat ID from <a href="https://t.me/userinfobot" target="_blank" rel="noreferrer" style={linkStyle}>@userinfobot</a>.
      </p>

      <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '12px 0', color: '#aaa', fontSize: 13 }}>
        <input
          type="checkbox"
          checked={p.skip}
          onChange={e => p.setSkip(e.target.checked)}
        />
        I don't want mobile notifications — skip this step
      </label>

      {!p.skip && (
        <>
          <Field label="Bot token">
            <input
              value={p.botToken}
              onChange={e => p.setBotToken(e.target.value)}
              placeholder="1234567:ABC-DEF..."
              style={inputStyle}
            />
          </Field>
          <Field label="Your numeric chat ID">
            <input
              value={p.chatId}
              onChange={e => p.setChatId(e.target.value)}
              placeholder="123456789"
              style={inputStyle}
            />
          </Field>

          <div style={{ marginTop: 12 }}>
            <button
              onClick={p.onTest}
              disabled={p.probe.state === 'running' || !p.botToken.trim() || !p.chatId.trim()}
              style={p.probe.state === 'running' || !p.botToken.trim() || !p.chatId.trim() ? disabledBtn : ghostBtn}
            >
              {p.probe.state === 'running' ? 'Sending test…' : 'Send test message'}
            </button>
            <ProbeBadge probe={p.probe} style={{ marginLeft: 12 }} />
          </div>
        </>
      )}
    </div>
  );
}

function ClaudeStep({ probe, onTest }: { probe: ProbeResult; onTest: () => void }) {
  const [authStatus, setAuthStatus] = useState<{installed: boolean; logged_in: boolean; error?: string | null} | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [snap, setSnap] = useState<WizardAuthSnapshot | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(false);

  const refreshAuth = useCallback(async () => {
    setCheckingAuth(true);
    try {
      const s = await api.wizardClaudeAuthStatus();
      setAuthStatus({ installed: s.installed, logged_in: s.logged_in, error: s.error });
    } catch (e) {
      setAuthStatus({ installed: false, logged_in: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setCheckingAuth(false);
    }
  }, []);

  useEffect(() => {
    if (probe.state === 'idle') onTest();
    refreshAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll snapshot while a login session is running
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await api.wizardClaudeAuthSnapshot(sessionId);
        if (cancelled) return;
        setSnap(s);
        if (s.done) {
          await refreshAuth();
          setSessionId(null);
        }
      } catch {
        // transient errors are fine, keep polling
      }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [sessionId, refreshAuth]);

  const startLogin = async () => {
    setLoginError(null);
    setSnap(null);
    try {
      const r = await api.wizardClaudeAuthStart();
      if (r.ok && r.session) {
        setSessionId(r.session.id);
        setSnap(r.session);
      } else {
        setLoginError(r.error || 'failed to start login');
      }
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : String(e));
    }
  };

  const stopLogin = async () => {
    if (sessionId) {
      try { await api.wizardClaudeAuthStop(sessionId); } catch { /* ignore */ }
      setSessionId(null);
      setSnap(null);
      refreshAuth();
    }
  };

  return (
    <div>
      <p style={hintText}>
        Klava runs its agent sessions via the Claude Code CLI. Two things need to be true:
        the CLI must be installed, and you must be signed in to your Anthropic account.
      </p>

      <div style={{ marginTop: 16 }}>
        <button
          onClick={onTest}
          disabled={probe.state === 'running'}
          style={probe.state === 'running' ? disabledBtn : ghostBtn}
        >
          {probe.state === 'running' ? 'Checking…' : 'Re-check install'}
        </button>
        <ProbeBadge probe={probe} style={{ marginLeft: 12 }} />
      </div>

      {probe.state === 'fail' && probe.hint && (
        <p style={{ ...hintText, color: '#fbbf24', marginTop: 12 }}>{probe.hint}</p>
      )}

      {probe.state === 'ok' && (
        <div style={{ marginTop: 20, padding: 12, background: '#18181b', borderRadius: 6 }}>
          <div style={{ color: '#aaa', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
            Authentication
          </div>
          {checkingAuth && !authStatus ? (
            <div style={{ color: '#888', fontSize: 13 }}>Checking auth status…</div>
          ) : authStatus && authStatus.logged_in ? (
            <div>
              <span style={{ color: '#34d399', fontWeight: 500 }}>✓ Signed in to Anthropic</span>
              <button onClick={refreshAuth} style={{ ...ghostBtn, marginLeft: 12, fontSize: 12, padding: '4px 10px' }}>
                Re-check
              </button>
            </div>
          ) : sessionId ? (
            <div>
              <div style={{ color: '#aaa', fontSize: 13, marginBottom: 8 }}>
                Running <code style={{ color: '#e4e4e7' }}>claude auth login</code>. Open the URL below, authorize Klava, then come back.
              </div>
              {(() => {
                // Prefer parser-extracted URL; otherwise scan lines for the
                // first https URL (claude.com OAuth URL isn't caught by the
                // gh-tuned generic parser in vadimgest).
                const url = snap?.verification_url
                  || snap?.lines.map(l => l.match(/https?:\/\/\S+/)?.[0]).find(Boolean)
                  || null;
                return url ? (
                  <div style={{ marginTop: 8 }}>
                    <a href={url} target="_blank" rel="noreferrer"
                       style={{ color: '#60a5fa', fontSize: 14, wordBreak: 'break-all' }}>
                      → {url}
                    </a>
                  </div>
                ) : null;
              })()}
              {snap?.device_code && (
                <div style={{ marginTop: 8, fontSize: 13, color: '#fbbf24' }}>
                  Device code: <strong style={{ fontSize: 16, letterSpacing: 1 }}>{snap.device_code}</strong>
                </div>
              )}
              {snap && snap.lines.length > 0 && (
                <pre style={{ ...codeBlock, marginTop: 12, maxHeight: 220, overflow: 'auto', fontSize: 11 }}>
                  {snap.lines.join('\n')}
                </pre>
              )}
              <button onClick={stopLogin} style={{ ...ghostBtn, marginTop: 12 }}>Cancel</button>
            </div>
          ) : (
            <div>
              <div style={{ color: '#fbbf24', marginBottom: 8 }}>✗ Not signed in</div>
              <button onClick={startLogin} style={primaryBtn}>Sign in with Anthropic</button>
              {loginError && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{loginError}</div>}
              {authStatus?.error && !loginError && (
                <div style={{ color: '#888', fontSize: 11, marginTop: 8 }}>{authStatus.error}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ObsidianStep(p: {
  skip: boolean; setSkip: (v: boolean) => void;
  vaultPath: string; setVaultPath: (v: string) => void;
  probe: ProbeResult;
  onTest: (create?: boolean) => void;
}) {
  return (
    <div>
      <p style={hintText}>
        Klava reads and writes notes inside an Obsidian vault. Skip this if you don't use Obsidian —
        most features still work, but the knowledge graph (People, Deals, Topics) won't be wired up.
      </p>

      <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '12px 0', color: '#aaa', fontSize: 13 }}>
        <input
          type="checkbox"
          checked={p.skip}
          onChange={e => p.setSkip(e.target.checked)}
        />
        I don't use Obsidian — skip
      </label>

      {!p.skip && (
        <>
          <Field label="Vault path">
            <input
              value={p.vaultPath}
              onChange={e => p.setVaultPath(e.target.value)}
              placeholder="~/Documents/MyBrain"
              style={inputStyle}
            />
          </Field>

          <div style={{ marginTop: 12 }}>
            <button
              onClick={() => p.onTest(false)}
              disabled={p.probe.state === 'running' || !p.vaultPath.trim()}
              style={p.probe.state === 'running' || !p.vaultPath.trim() ? disabledBtn : ghostBtn}
            >
              {p.probe.state === 'running' ? 'Checking…' : 'Check folder'}
            </button>
            <ProbeBadge probe={p.probe} style={{ marginLeft: 12 }} />
          </div>
          {p.probe.state === 'fail' && p.probe.hint === 'create' && (
            <div style={{ marginTop: 10 }}>
              <button onClick={() => p.onTest(true)} style={primaryBtn}>
                Create folder
              </button>
              <span style={{ color: '#888', fontSize: 12, marginLeft: 12 }}>
                Klava will make the folder for you — Obsidian picks it up when you open the app.
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CliAuthStep({ method, title, blurb, installCmd, requiresAccount, accountPlaceholder, advanced }: {
  method: string;
  title: string;
  blurb: string;
  installCmd: string;
  requiresAccount?: boolean;
  accountPlaceholder?: string;
  advanced?: React.ReactNode;
}) {
  const [status, setStatus] = useState<{ signed_in: boolean; detail?: string; error?: string; accounts?: string[] } | null>(null);
  const [account, setAccount] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [snap, setSnap] = useState<WizardAuthSnapshot | null>(null);
  // lastFailedSnap holds the last session snapshot after it exits non-zero
  // so the error output stays visible. Cleared when the user clicks Retry.
  const [lastFailedSnap, setLastFailedSnap] = useState<WizardAuthSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notInstalled, setNotInstalled] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await api.wizardCliAuthStatus(method, account || undefined);
      setStatus({ signed_in: s.signed_in, detail: s.detail, error: s.error, accounts: s.accounts });
      if (s.error && /unavailable|not installed|not found/i.test(s.error)) setNotInstalled(true);
    } catch (e) {
      setStatus({ signed_in: false, error: e instanceof Error ? e.message : String(e) });
    }
  }, [method, account]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const s = await api.wizardCliAuthSnapshot(sessionId);
        if (cancelled) return;
        setSnap(s);
        if (s.done) {
          // Re-probe auth status once the subprocess exits. The refresh is
          // the source of truth — some CLIs close their pty before their
          // exit code reaches us, so exit_code can be null on legitimate
          // success. Only mark as failure if the status probe agrees the
          // user still isn't signed in.
          const latest = await api.wizardCliAuthStatus(method, account || undefined)
            .catch(() => ({ signed_in: false, error: 'status probe failed' }));
          if (!cancelled) {
            setStatus({
              signed_in: latest.signed_in,
              detail: ('detail' in latest ? latest.detail : undefined),
              error: ('error' in latest ? latest.error : undefined) ?? undefined,
              accounts: ('accounts' in latest ? latest.accounts : undefined),
            });
            if (!latest.signed_in && s.lines.length > 0) {
              setLastFailedSnap(s);
            }
            setSessionId(null);
          }
        }
      } catch { /* ignore transient */ }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [sessionId, method, account]);

  const start = async () => {
    setError(null); setSnap(null); setNotInstalled(false); setLastFailedSnap(null);
    try {
      const r = await api.wizardCliAuthStart(method, account || undefined);
      if (r.ok && r.session) {
        setSessionId(r.session.id);
        setSnap(r.session);
      } else {
        setError(r.error || 'start failed');
        if (r.needs_install) setNotInstalled(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const stop = async () => {
    if (sessionId) {
      try { await api.wizardCliAuthStop(sessionId); } catch { /* ignore */ }
      setSessionId(null); setSnap(null); refresh();
    }
  };

  return (
    <div>
      <p style={hintText}>{blurb}</p>

      {requiresAccount && !status?.signed_in && !sessionId && (
        <Field label="Account (email)">
          <input value={account} onChange={e => setAccount(e.target.value)}
                 placeholder={accountPlaceholder || ''} style={inputStyle} />
        </Field>
      )}

      <div style={{ marginTop: 16, padding: 12, background: '#18181b', borderRadius: 6 }}>
        <div style={{ color: '#aaa', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
          {title} status
        </div>
        {notInstalled ? (
          <div>
            <div style={{ color: '#fbbf24', marginBottom: 8 }}>✗ {method} CLI not installed</div>
            <pre style={codeBlock}>{installCmd}</pre>
            <button onClick={() => { setNotInstalled(false); refresh(); }} style={{ ...ghostBtn, marginTop: 8, fontSize: 12 }}>
              Re-check
            </button>
          </div>
        ) : status === null ? (
          <div style={{ color: '#888', fontSize: 13 }}>Checking…</div>
        ) : status.signed_in ? (
          <div>
            <span style={{ color: '#34d399', fontWeight: 500 }}>✓ Signed in</span>
            {status.detail && <span style={{ color: '#aaa', fontSize: 13, marginLeft: 8 }}>{status.detail}</span>}
            <button onClick={refresh} style={{ ...ghostBtn, marginLeft: 12, fontSize: 12, padding: '4px 10px' }}>Re-check</button>
          </div>
        ) : sessionId ? (
          <div>
            <div style={{ color: '#aaa', fontSize: 13, marginBottom: 8 }}>
              Running {method} login. Open the URL, authorize, come back.
            </div>
            {(() => {
              const url = snap?.verification_url
                || snap?.lines.map(l => l.match(/https?:\/\/\S+/)?.[0]).find(Boolean)
                || null;
              return url ? (
                <a href={url} target="_blank" rel="noreferrer"
                   style={{ color: '#60a5fa', fontSize: 14, wordBreak: 'break-all' }}>
                  → {url}
                </a>
              ) : null;
            })()}
            {snap?.device_code && (
              <div style={{ marginTop: 8, fontSize: 13, color: '#fbbf24' }}>
                Code: <strong style={{ fontSize: 16, letterSpacing: 1 }}>{snap.device_code}</strong>
              </div>
            )}
            {snap && snap.lines.length > 0 && (
              <pre style={{ ...codeBlock, marginTop: 12, maxHeight: 200, overflow: 'auto', fontSize: 11 }}>
                {snap.lines.join('\n')}
              </pre>
            )}
            <button onClick={stop} style={{ ...ghostBtn, marginTop: 12 }}>Cancel</button>
          </div>
        ) : (
          <div>
            <div style={{ color: '#fbbf24', marginBottom: 8 }}>✗ Not signed in</div>
            {lastFailedSnap && lastFailedSnap.lines.length > 0 && (
              <div style={{ marginBottom: 12, padding: 10, background: '#1f1415', borderRadius: 4, borderLeft: '3px solid #f87171' }}>
                <div style={{ color: '#f87171', fontSize: 12, fontWeight: 500, marginBottom: 6 }}>
                  Last attempt failed{lastFailedSnap.exit_code !== null ? ` (exit ${lastFailedSnap.exit_code})` : ''}:
                </div>
                <pre style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace', fontSize: 11, color: '#e4e4e7', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {lastFailedSnap.lines.slice(-15).join('\n')}
                </pre>
              </div>
            )}
            <button
              onClick={start}
              disabled={!!(requiresAccount && !account.trim())}
              style={(requiresAccount && !account.trim()) ? disabledBtn : primaryBtn}
            >
              {lastFailedSnap ? `Retry ${title} sign-in` : `Sign in with ${title}`}
            </button>
            {error && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{error}</div>}
          </div>
        )}
      </div>

      {advanced && <AdvancedPanel>{advanced}</AdvancedPanel>}
    </div>
  );
}

function AdvancedPanel({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 16, border: '1px solid #27272a', borderRadius: 6 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', textAlign: 'left', padding: '10px 12px',
          background: 'transparent', border: 'none', color: '#aaa',
          fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
      >
        <span style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 120ms' }}>▸</span>
        Advanced
      </button>
      {open && <div style={{ padding: '0 12px 12px 12px' }}>{children}</div>}
    </div>
  );
}

function GogCredentialsAdvanced() {
  const [json, setJson] = useState('');
  const [saving, setSaving] = useState(false);
  const [savedClientId, setSavedClientId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true); setError(null); setSavedClientId(null);
    try {
      const r = await api.wizardGogCredentials(json);
      if (r.ok && r.client_id) {
        setSavedClientId(r.client_id);
        setJson('');
      } else {
        setError(r.error || 'save failed');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <p style={{ ...hintText, fontSize: 12, marginTop: 0 }}>
        Replace the shared Klava OAuth client with your own. Create a Desktop OAuth
        client at <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer"
        style={{ color: '#60a5fa' }}>console.cloud.google.com/apis/credentials</a>,
        download the JSON, paste it below.
      </p>
      <textarea
        value={json}
        onChange={e => setJson(e.target.value)}
        placeholder={'{\n  "installed": {\n    "client_id": "...",\n    "client_secret": "..."\n  }\n}'}
        rows={8}
        style={{ ...inputStyle, fontFamily: 'ui-monospace, SFMono-Regular, monospace', fontSize: 11, width: '100%' }}
      />
      <div style={{ marginTop: 10, display: 'flex', gap: 12, alignItems: 'center' }}>
        <button onClick={save} disabled={saving || !json.trim()} style={(!json.trim() || saving) ? disabledBtn : primaryBtn}>
          {saving ? 'Saving…' : 'Save credentials'}
        </button>
        {savedClientId && (
          <span style={{ color: '#34d399', fontSize: 12 }}>
            ✓ Saved client {savedClientId.substring(0, 16)}…
          </span>
        )}
      </div>
      {error && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{error}</div>}
    </>
  );
}

function ApiKeysStep() {
  // Keys Klava reads from .env. All optional — a blank value just leaves
  // the feature disabled. We do NOT read existing values (secrets are
  // redacted by the backend), so fields start empty and overwrite on save.
  const [keys, setKeys] = useState<Record<string, string>>({
    GEMINI_API_KEY: '',
    GITHUB_PERSONAL_ACCESS_TOKEN: '',
    OBSIDIAN_API_KEY: '',
    SIGNAL_USER_ID: '',
  });
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const updates: Record<string, string> = {};
      for (const [k, v] of Object.entries(keys)) {
        if (v.trim()) updates[k] = v.trim();
      }
      if (Object.keys(updates).length === 0) {
        setError('Nothing to save — fill at least one field or skip this step.');
        return;
      }
      const r = await api.wizardEnvWrite(updates);
      if (r.ok) {
        setSavedAt(Date.now());
        setKeys(prev => Object.fromEntries(Object.keys(prev).map(k => [k, ''])));
      } else {
        setError(r.error || 'save failed');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const FIELDS: Array<{ key: string; label: string; hint: string }> = [
    { key: 'GEMINI_API_KEY', label: 'Google Gemini API key', hint: 'aistudio.google.com/app/apikey — for /gemini-cli skill' },
    { key: 'GITHUB_PERSONAL_ACCESS_TOKEN', label: 'GitHub PAT (fallback)', hint: 'github.com/settings/tokens — only if you skipped gh auth login' },
    { key: 'OBSIDIAN_API_KEY', label: 'Obsidian Local REST API token', hint: 'Enable the Obsidian plugin first, then paste token' },
    { key: 'SIGNAL_USER_ID', label: 'Signal phone number', hint: 'Your registered Signal phone, with country code, e.g. +37127000000' },
  ];

  return (
    <div>
      <p style={hintText}>
        Optional API keys Klava reads from <code style={{ color: '#e4e4e7' }}>.env</code>. Leave blank to skip —
        each one just disables its feature. Existing values in <code style={{ color: '#e4e4e7' }}>.env</code>
        are kept unless you overwrite them here.
      </p>

      {FIELDS.map(f => (
        <Field key={f.key} label={f.label}>
          <input
            type="password"
            value={keys[f.key]}
            onChange={e => setKeys(prev => ({ ...prev, [f.key]: e.target.value }))}
            placeholder=""
            style={inputStyle}
          />
          <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>{f.hint}</div>
        </Field>
      ))}

      <div style={{ marginTop: 16 }}>
        <button onClick={save} disabled={saving} style={saving ? disabledBtn : primaryBtn}>
          {saving ? 'Saving…' : 'Save keys to .env'}
        </button>
        {savedAt && (
          <span style={{ color: '#34d399', marginLeft: 12, fontSize: 13 }}>✓ Saved</span>
        )}
        {error && <div style={{ color: '#f87171', fontSize: 12, marginTop: 8 }}>{error}</div>}
      </div>
    </div>
  );
}

function VadimgestStep() {
  const [status, setStatus] = useState<{ up: boolean; url: string; sources_total: number; sources_enabled: number } | null>(null);

  const vadimgestUrl = 'http://localhost:8484';

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const healthRes = await fetch(vadimgestUrl + '/', { method: 'HEAD', mode: 'no-cors' }).catch(() => null);
        const up = healthRes !== null;
        let total = 0, enabled = 0;
        try {
          const sRes = await fetch(vadimgestUrl + '/api/sources');
          if (sRes.ok) {
            const data = await sRes.json();
            if (Array.isArray(data)) {
              total = data.length;
              enabled = data.filter((s: { enabled?: boolean }) => s.enabled).length;
            }
          }
        } catch { /* ignore */ }
        if (!cancelled) setStatus({ up, url: vadimgestUrl, sources_total: total, sources_enabled: enabled });
      } catch {
        if (!cancelled) setStatus({ up: false, url: vadimgestUrl, sources_total: 0, sources_enabled: 0 });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div>
      <p style={hintText}>
        Vadimgest is your personal data hub — it syncs Telegram, Signal, Gmail, Obsidian, Granola,
        Hlopya, iMessage, WhatsApp and more into a unified search index. Klava reads from it.
      </p>
      <p style={hintText}>
        Source-by-source configuration (auth flows for Gmail/GitHub, Signal DB pairing, etc.) lives
        in vadimgest's own dashboard. Open it in a new tab, enable the sources you want, come back.
      </p>

      <div style={{ marginTop: 20, padding: 12, background: '#18181b', borderRadius: 6 }}>
        <div style={{ color: '#aaa', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
          Status
        </div>
        {status === null ? (
          <div style={{ color: '#888', fontSize: 13 }}>Checking…</div>
        ) : status.up ? (
          <>
            <div style={{ color: '#34d399', fontWeight: 500, marginBottom: 8 }}>
              ✓ Vadimgest dashboard is running at {status.url}
            </div>
            <div style={{ color: '#aaa', fontSize: 13 }}>
              {status.sources_enabled} of {status.sources_total} sources enabled.
            </div>
          </>
        ) : (
          <div style={{ color: '#fbbf24', fontSize: 13 }}>
            Vadimgest dashboard isn't responding at {status.url}. Check the vadimgest-dashboard
            launchd agent (Settings → Daemons), then re-open this step.
          </div>
        )}
      </div>

      <div style={{ marginTop: 16 }}>
        <a href={vadimgestUrl} target="_blank" rel="noreferrer" style={{ ...primaryBtn, display: 'inline-block', textDecoration: 'none' }}>
          Open vadimgest dashboard ↗
        </a>
      </div>

      <p style={{ ...hintText, marginTop: 16, fontSize: 12 }}>
        You can always configure more sources later — come back to this wizard any time from
        Settings → "Run the wizard again".
      </p>
    </div>
  );
}

function CronsStep(p: {
  plists: Array<{ label: string; path: string; loaded: boolean; name: string }>;
  scanDir: string;
  prefix: string;
  selected: Set<string>;
  setSelected: (s: Set<string>) => void;
  loading: boolean;
  results: Array<{ label: string; ok: boolean; error?: string }>;
}) {
  const toggle = (label: string) => {
    const next = new Set(p.selected);
    if (next.has(label)) next.delete(label);
    else next.add(label);
    p.setSelected(next);
  };

  return (
    <div>
      <p style={hintText}>
        Launch agents are what keeps Klava running — the scheduler, the Telegram bot, the watchdog, etc.
        Loading them now means they start on login and stay running in the background.
      </p>

      {p.loading && <div style={{ color: '#888', marginTop: 12 }}>Scanning ~/Library/LaunchAgents…</div>}

      {!p.loading && p.plists.length === 0 && (
        <div style={{
          marginTop: 12,
          padding: '12px 14px',
          border: '1px solid #3f3f22',
          background: 'rgba(251,191,36,0.06)',
          borderRadius: 8,
          color: '#d4d4d8',
          fontSize: 13,
          lineHeight: 1.5,
        }}>
          <div style={{ color: '#fbbf24', marginBottom: 6, fontWeight: 500 }}>
            Nothing to load yet
          </div>
          No plists matched <code style={codeInline}>{p.prefix || '<prefix>'}.*.plist</code> in{' '}
          <code style={codeInline}>{p.scanDir || '~/Library/LaunchAgents'}</code>.
          <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
            Most common cause: the <strong>Identity</strong> step used a different{' '}
            <code style={codeInline}>launchd_prefix</code> than the one <code style={codeInline}>./setup.sh</code>{' '}
            installed agents under. Go back and match them, or re-run <code style={codeInline}>./setup.sh</code>{' '}
            in a terminal to reinstall under the new prefix.
          </div>
          <div style={{ color: '#999', fontSize: 12, marginTop: 6 }}>
            You can also skip this step — agents will start on next login once they exist.
          </div>
        </div>
      )}

      {!p.loading && p.plists.map(plist => {
        const result = p.results.find(r => r.label === plist.label);
        const isSelected = p.selected.has(plist.label);
        return (
          <div key={plist.label} style={plistRow(isSelected)}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => toggle(plist.label)}
                disabled={plist.loaded}
              />
              <div>
                <div style={{ fontSize: 13, color: '#eee', fontWeight: 500 }}>
                  {plist.name}
                </div>
                <div style={{ fontSize: 11, color: '#666', fontFamily: 'ui-monospace,monospace' }}>
                  {plist.label}
                </div>
              </div>
            </label>
            {plist.loaded && (
              <span style={{ color: '#4ade80', fontSize: 11 }}>already loaded</span>
            )}
            {result && (
              <span style={{ color: result.ok ? '#4ade80' : '#f87171', fontSize: 11 }}>
                {result.ok ? 'loaded' : (result.error || 'failed')}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DoneStep() {
  return (
    <div style={{ color: '#d0d0d0', lineHeight: 1.6, fontSize: 14 }}>
      <p style={{ marginTop: 0 }}>
        Klava is configured. The dashboard is yours — start with the <strong style={{ color: '#4ade80' }}>Chat</strong> tab for a conversation, or <strong style={{ color: '#4ade80' }}>Deck</strong> for the task feed.
      </p>
      <p style={{ color: '#aaa', fontSize: 13 }}>
        If you skipped Claude auth, remember to run <code style={codeInline}>claude login</code> in a terminal — otherwise any agent session will fail.
      </p>
      <p style={{ color: '#666', fontSize: 12, marginTop: 24 }}>
        You can re-run this wizard anytime from the <em>Settings</em> header.
      </p>
    </div>
  );
}

// ── primitives ─────────────────────────────────────────────────────

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: 'block', fontSize: 12, color: '#9ca3af', marginBottom: 4 }}>
        {label}{required && <span style={{ color: '#f87171', marginLeft: 4 }}>*</span>}
      </label>
      {children}
    </div>
  );
}

function ProbeBadge({ probe, style }: { probe: ProbeResult; style?: React.CSSProperties }) {
  if (probe.state === 'idle') return null;
  const color = probe.state === 'ok' ? '#4ade80' : probe.state === 'fail' ? '#f87171' : '#9ca3af';
  const dot = probe.state === 'running' ? '⋯' : probe.state === 'ok' ? '✓' : '✗';
  return (
    <span style={{ color, fontSize: 12, ...style }}>
      {dot} {probe.message || probe.state}
    </span>
  );
}

// ── styles ─────────────────────────────────────────────────────────

const TITLES: Record<StepKey, string> = {
  intro: 'Welcome',
  identity: 'Who are you?',
  telegram: 'Telegram (optional)',
  claude: 'Claude Code CLI',
  github: 'GitHub (optional)',
  google: 'Google (optional)',
  obsidian: 'Obsidian vault (optional)',
  apikeys: 'API keys (optional)',
  vadimgest: 'Vadimgest data sources',
  crons: 'Launch agents',
  done: 'All set',
};

const wizardCard: React.CSSProperties = {
  border: '1px solid #2a2a2e',
  borderRadius: 12,
  background: '#111114',
  padding: 0,
  marginBottom: 24,
  overflow: 'hidden',
};

const wizardHeader: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '16px 20px 12px',
  borderBottom: '1px solid #1f1f22',
};

const stepDots: React.CSSProperties = {
  display: 'flex',
  gap: 6,
  padding: '12px 20px',
  alignItems: 'center',
  borderBottom: '1px solid #1f1f22',
};

const stepBody: React.CSSProperties = {
  padding: '20px 20px 8px',
  minHeight: 200,
};

const wizardFooter: React.CSSProperties = {
  display: 'flex',
  gap: 10,
  alignItems: 'center',
  padding: '14px 20px',
  borderTop: '1px solid #1f1f22',
  background: '#0e0e11',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  background: '#0a0a0c',
  color: '#f5f5f5',
  border: '1px solid #2a2a2e',
  borderRadius: 6,
  padding: '8px 10px',
  fontSize: 13,
  fontFamily: 'inherit',
};

const primaryBtn: React.CSSProperties = {
  background: '#15803d',
  color: '#fff',
  border: '1px solid #16a34a',
  borderRadius: 6,
  padding: '7px 16px',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
};

const disabledBtn: React.CSSProperties = {
  ...primaryBtn,
  background: '#1a1a1d',
  color: '#666',
  border: '1px solid #2a2a2e',
  cursor: 'not-allowed',
};

const ghostBtn: React.CSSProperties = {
  background: '#1a1a1d',
  color: '#aaa',
  border: '1px solid #2a2a2e',
  borderRadius: 6,
  padding: '7px 14px',
  fontSize: 12,
  cursor: 'pointer',
};

const hintText: React.CSSProperties = {
  color: '#9ca3af',
  fontSize: 13,
  lineHeight: 1.6,
  marginTop: 0,
};

const linkStyle: React.CSSProperties = {
  color: '#60a5fa',
  textDecoration: 'underline',
};

const codeBlock: React.CSSProperties = {
  background: '#0a0a0c',
  border: '1px solid #2a2a2e',
  borderRadius: 6,
  padding: '10px 12px',
  fontSize: 12,
  color: '#d0d0d0',
  fontFamily: 'ui-monospace,monospace',
  overflow: 'auto',
};

const codeInline: React.CSSProperties = {
  background: '#0a0a0c',
  border: '1px solid #2a2a2e',
  borderRadius: 4,
  padding: '1px 6px',
  fontSize: 12,
  color: '#d0d0d0',
  fontFamily: 'ui-monospace,monospace',
};

const errorBanner: React.CSSProperties = {
  margin: '0 20px 12px',
  padding: '10px 14px',
  border: '1px solid #7f1d1d',
  background: 'rgba(127,29,29,0.15)',
  color: '#f87171',
  borderRadius: 8,
  fontSize: 12,
};

function plistRow(selected: boolean): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 12px',
    borderRadius: 6,
    border: '1px solid ' + (selected ? '#15803d' : '#2a2a2e'),
    background: selected ? 'rgba(21,128,61,0.08)' : 'transparent',
    marginBottom: 6,
  };
}
