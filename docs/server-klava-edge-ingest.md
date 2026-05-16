# Server Klava Edge Ingest

Goal: run Klava and canonical vadimgest on a private server while local Macs
push events for sources that only exist locally.

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
