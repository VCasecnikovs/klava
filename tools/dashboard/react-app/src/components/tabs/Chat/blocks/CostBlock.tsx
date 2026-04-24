import { useState } from 'react';
import type { Block } from '@/context/ChatContext';

function fmtNum(n: number | undefined | null): string {
  if (n == null) return '-';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n / 1000).toFixed(n < 10_000 ? 1 : 0) + 'k';
  return (n / 1_000_000).toFixed(1) + 'M';
}

export function CostBlock({ block }: { block: Block }) {
  const [open, setOpen] = useState(false);

  const min = Math.floor((block.seconds || 0) / 60);
  const sec = (block.seconds || 0) % 60;
  const timeStr = (min > 0 ? min + 'm ' : '') + sec + 's';
  const costStr = (block.cost || 0) > 0 ? ' \u00b7 $' + (block.cost || 0).toFixed(4) : '';

  const usage = block.usage || null;
  const denials = block.permission_denials || [];
  const stop = block.stop_reason || null;
  const subtype = block.subtype || null;
  const turns = block.num_turns ?? null;
  const apiMs = block.duration_api_ms ?? null;
  const model = block.model || null;
  const modelUsage = block.model_usage || {};
  const modelUsageEntries = Object.entries(modelUsage);

  const hasDetail =
    !!usage ||
    denials.length > 0 ||
    !!stop ||
    (subtype && subtype !== 'success') ||
    turns != null ||
    modelUsageEntries.length > 0 ||
    !!model;

  const stopHint =
    stop === 'end_turn' || stop === 'stop_sequence' || !stop
      ? null
      : stop === 'max_tokens'
      ? ' \u00b7 truncated (max tokens)'
      : stop === 'tool_use'
      ? null
      : ' \u00b7 ' + stop;

  const denialHint = denials.length > 0 ? ` \u00b7 ${denials.length} tool denial${denials.length > 1 ? 's' : ''}` : '';

  return (
    <div className="chat-cost">
      <span
        className={hasDetail ? 'chat-cost-summary chat-cost-clickable' : 'chat-cost-summary'}
        onClick={hasDetail ? () => setOpen((v) => !v) : undefined}
        role={hasDetail ? 'button' : undefined}
      >
        {timeStr}
        {costStr}
        {stopHint}
        {denialHint}
        {hasDetail ? (open ? ' \u25be' : ' \u25b8') : ''}
      </span>
      {open && hasDetail && (
        <div className="chat-cost-detail">
          {model && <div>model: <code>{model}</code></div>}
          {turns != null && <div>turns: {turns}</div>}
          {subtype && subtype !== 'success' && <div>subtype: {subtype}</div>}
          {stop && <div>stop_reason: {stop}</div>}
          {apiMs != null && <div>api: {Math.round(apiMs)}ms</div>}
          {modelUsageEntries.length > 1 && (
            <div className="chat-cost-model-usage">
              per-model:
              {modelUsageEntries.map(([m, u]) => (
                <div key={m} className="chat-cost-model-usage-row">
                  <code>{m}</code>
                  {typeof u?.input_tokens === 'number' && (
                    <span className="chat-cost-token-pill">in {fmtNum(u.input_tokens)}</span>
                  )}
                  {typeof u?.output_tokens === 'number' && (
                    <span className="chat-cost-token-pill">out {fmtNum(u.output_tokens)}</span>
                  )}
                  {typeof u?.cost_usd === 'number' && u.cost_usd > 0 && (
                    <span className="chat-cost-token-pill">${u.cost_usd.toFixed(4)}</span>
                  )}
                </div>
              ))}
            </div>
          )}
          {usage && (
            <div className="chat-cost-usage">
              tokens:
              <span className="chat-cost-token-pill">in {fmtNum(usage.input_tokens as number)}</span>
              <span className="chat-cost-token-pill">out {fmtNum(usage.output_tokens as number)}</span>
              {(usage.cache_read_input_tokens as number) ? (
                <span className="chat-cost-token-pill">cache-read {fmtNum(usage.cache_read_input_tokens as number)}</span>
              ) : null}
              {(usage.cache_creation_input_tokens as number) ? (
                <span className="chat-cost-token-pill">cache-new {fmtNum(usage.cache_creation_input_tokens as number)}</span>
              ) : null}
            </div>
          )}
          {denials.length > 0 && (
            <div className="chat-cost-denials">
              <div>Permission denials:</div>
              {denials.map((d, i) => (
                <div key={i}>
                  - <code>{d.tool || '?'}</code>
                  {d.reason ? `: ${d.reason}` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
