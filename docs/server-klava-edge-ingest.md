# Server Klava Edge Ingest

Goal: run Klava and canonical vadimgest on a private server while local Macs
push events for sources that only exist locally.

## Current Server Cutover

Production Klava now runs on `codex-klava` / `bakeneko`.

- Klava dashboard: `http://100.100.129.50:18788/dashboard`
- Vadimgest dashboard and edge ingest: `http://100.100.129.50:8484`
- Server repo: `/srv/codex-klava/repos/claude`
- Server Obsidian vault: `/srv/codex-klava/data/MyBrain`
- Server vadimgest data: `/srv/codex-klava/data/vadimgest`
- Server Klava runtime data: `/srv/codex-klava/data/klava`

The old Mac webhook dashboard on `:18788` should stay disabled after cutover.
The Mac vadimgest dashboard on `127.0.0.1:8484` can stay enabled because it is
the local Edge Sync control panel.

## Source Ownership Matrix

| Area | Owner | Notes |
| --- | --- | --- |
| Klava dashboard, Deck, Chat, approvals | Server | `klava-webhook.service` on systemd |
| Klava cron scheduler and task consumer | Server | `klava-cron-scheduler.service`; Google Tasks is the queue |
| Telegram gateway | Server | `klava-tg-gateway.service` |
| Canonical vadimgest store and search | Server | Server receives edge batches and indexes canonical data |
| Obsidian vault | Server plus Obsidian Sync | Server vault lives at `/srv/codex-klava/data/MyBrain` |
| Google, GitHub, Nextcloud, task APIs | Server where possible | OAuth and CLIs are configured on the server |
| iMessage, desktop/browser history, Dayflow, local app data | Mac edge agent | These depend on local macOS state and permissions |
| WhatsApp, Signal, LinkedIn/browser-cookie sources | Mac edge by default | Move only if a headless/server-safe connector exists |
| Attachments and large local files | Not V1 edge | V1 pushes normalized JSON records, not binary blobs |

Server-side source sync jobs that depend on local desktop state should remain
disabled. The Mac `com.vadimgest.edge-agent` owns local collection and upload.

## Server Services

```bash
systemctl status klava-webhook klava-cron-scheduler klava-tg-gateway vadimgest-dashboard obsidian-headless-sync
```

The server uses systemd, not launchd. Codex and Klava context are installed for
both `root` and `codex`:

- `~/.codex/AGENTS.md`
- `~/.codex/klava/`
- `~/.codex/skills/`
- `~/.claude/CLAUDE.md`
- `~/.claude/MEMORY.md`
- `~/.claude/skills`

`AGENTS.md` also exists at `/srv/codex-klava/repos/claude/AGENTS.md` so Codex
connections opened directly in the repo inherit the Klava-aligned profile.

The server owns:

- `klava-api`, Dashboard, Deck, tasks, runs, approvals
- canonical vadimgest append-only store
- search/indexing over uploaded events

Each local machine runs an edge agent that owns:

- local-only connectors such as iMessage, browser state, Dayflow, Signal, local files
- source credentials and macOS permissions
- cursor/retry state for upload

## Endpoint

`POST /api/edge/events/batch`

```json
{
  "device_id": "macbook-vadim",
  "source": "imessage",
  "events": [
    {
      "source_uri": "imessage://chat/a/message/1",
      "observed_at": "2026-05-16T10:00:00+00:00",
      "actor": "Alice",
      "text": "Can you send the proposal?",
      "attachments": [],
      "privacy": {
        "raw_uploaded": true,
        "redaction": "none"
      },
      "meta": {
        "chat": "Alice"
      }
    }
  ]
}
```

Events may also carry their own `source`; that overrides the batch-level
source. If `id` or `event_id` is omitted, the server derives a stable id from
`source + source_uri`, or from the canonical event JSON as a fallback.

## Response

```json
{
  "ok": true,
  "accepted": 1,
  "skipped": 0,
  "errors": [],
  "records": [
    {
      "index": 0,
      "source": "imessage",
      "id": "edge_f1...",
      "line": 1,
      "status": "accepted"
    }
  ]
}
```

Re-sending the same event is safe. Existing ids are returned as `skipped`, so
edge agents can retry batches until they get a durable response.

## Storage Shape

Edge events are written to the normal vadimgest source JSONL files:

- `imessage` -> `sources/imessage.jsonl`
- `dayflow` -> `sources/dayflow.jsonl`
- arbitrary edge source names are sanitized to `[a-z0-9_-]`

Record fields:

- `id`
- `type`, default `edge_event`
- `source_uri`
- `observed_at` and `timestamp`
- `actor`
- `text`
- `attachments`
- `privacy`
- `edge.device_id`
- `edge.received_at`
- `meta`

## Next Slice

Add a local `edge-agent` command that:

1. reads enabled local-only sources;
2. tracks per-source cursors locally;
3. posts batches to `/api/edge/events/batch`;
4. retries idempotently on network failure;
5. optionally uploads attachments as objects before sending event references.
