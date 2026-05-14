---
name: state-log
description: State + Log convention for sourced facts. Every deal note, person note, org note follows this shape. Use when migrating notes, writing new entity notes, or auditing for unsourced claims.
---

# State + Log convention

Every entity note (deal, person, org, project hub) has the same shape:

```markdown
---
<frontmatter: stable identifiers + cached projection of ## State for downstream tooling>
---

# Title

## Product / Subject  ← stable spec, optional

## State              ← current facts, every bullet has src:

## Log                ← append-only timeline, reverse-chronological, every entry has src:
```

## Layer rules

**Frontmatter** is a denormalized cache. Holds stable identifiers (lead, referrer,
owner, product, deal_size, deal_type, value) plus mirrors of mutable State fields
that downstream tooling reads (`stage`, `last_contact`, `follow_up`, `next_action`).
No provenance here. When frontmatter and State disagree, **State wins** and the
cache gets updated.

Downstream readers that depend on frontmatter cache:
- `gateway/lib/status_collector.py` — Deals dashboard, Followups overdue calc.
- `.claude/skills/vox-crm/SKILL.md` — CRM updates.
- `scripts/silence-detector.py` — stale-deal flagging.

**`## State`** is the canonical truth. Every bullet:

```
- **<key>:** <value> · src: `<source-uri>` · <YYYY-MM-DD>
```

Source URIs:

| Channel | URI |
|---|---|
| Telegram | `tg://<chat_id>/<msg_id>` |
| Signal | `signal://<group>/<ts>` or `signal://<person>/<date>` |
| WhatsApp | `whatsapp://<chat>/<msg_id>` |
| iMessage | `imessage://<chat>/<rowid>` |
| Hlopya call | `hlopya://<meeting-slug-or-id>` |
| Gmail | `gmail://<msg_id>` |
| GitHub | `gh://<owner>/<repo>/issue/<n>` |
| Calendar | `gcal://<event_id>` |
| Browser observation | `browser://<host>` |
| Executor session | `executor://<YYYY-MM-DD>` |
| Vadim verbal | `vadim-said://<YYYY-MM-DD>` |
| Obsidian internal | `obsidian://<path>#<heading>` |

Weak provenance — `src: frontmatter` — is acceptable as a migration stub but
flagged by the linter as `_needs upgrade_`. Heartbeat / manual edits convert
these into real URIs over time.

Structural keys (`artifacts`, `links`, `related`, `channels`, `people`) are
allowed without `src:` — they index into other sourced content rather than
asserting a fact themselves.

**`## Log`** is append-only. Format:

```markdown
### YYYY-MM-DD — <short title>
- **src:** `<source-uri>`
- **mentions:** [[Entity]], [[Another Entity]]
- **summary:** what happened, key quotes, context
- **facts-touched:** key1, key2  (or — if pure observation)
```

Reverse chronological — newest first. Always wikilink entities mentioned;
that's how the backlink graph stays alive.

## Catchall folders are NOT scoped notes

`People/`, `Organizations/`, `Topics/`, `Inbox/`, `Meetings/`, `archive/`
contain entity notes but don't get the State+Log treatment as a folder —
only individual notes inside them do (e.g. `People/Pufit.md` has State+Log,
the `People/` folder itself does not).

## Tools

Live in `~/Documents/GitHub/claude/scripts/`:

- `migrate_to_state_log.py` — idempotent, non-destructive migration. Pulls
  dated sub-headings out of any section, sorts reverse-chronologically into
  `## Log`. Preserves existing State bullets verbatim; adds weak mirrors only
  for keys not already covered. Dry-run by default, `--apply` to write.

  ```bash
  python3 scripts/migrate_to_state_log.py \
      --vault ~/Documents/MyBrain \
      --glob 'Vox Lab/Deals/**/*.md' \
      --apply
  ```

- `lint_state_facts.py` — checks: presence of State + Log, every State bullet
  has `src:`, frontmatter cache matches State leading values, log strictly
  reverse-chronological, no duplicate `## History` headers.

  ```bash
  python3 scripts/lint_state_facts.py \
      --vault ~/Documents/MyBrain \
      --glob '**/*.md' \
      --fail-on hard
  ```

  Severity: `hard` blocks commits / CI. `soft` is the `_needs upgrade_`
  baseline — track it down over time, don't gate on it.

## Tagging

Migration script applies to notes with frontmatter tag:

- `vox-deal` — Vox Lab sales pipeline notes.
- `personal-deal` — Vadim's personal deal notes (not Vox).

Add new tags here as the convention spreads to other entity types
(`person`, `org`, `project-hub`).

## When to write what

- **New fact arrives** (Signal message, Hlopya call, email, etc.):
  1. Append a new `### YYYY-MM-DD — <title>` to `## Log` with `src:`,
     `mentions:`, summary.
  2. If the new fact changes a State field, update the corresponding bullet
     in `## State` with the new value and new `src:` pointing at the same
     log entry's source. List the touched keys in `facts-touched:`.
  3. If a cached field (`stage`, `last_contact`, `follow_up`, `next_action`)
     changed, also update frontmatter so the dashboard sees it. The linter
     will catch drift.

- **Verbal info from Vadim** with no upstream record:
  - Source URI: `vadim-said://<YYYY-MM-DD>` — weaker than a message, still
    attributed. Linter accepts it; you can upgrade later if a downstream
    log surfaces.

- **Anti-hallucination rule:** never write a fact to `## State` without a
  `src:`. If you have no source, it doesn't go in. The linter enforces.

## What this kills

- Freeform prose updates buried in unstructured notes.
- "Last_contact" silently going stale because nothing updates it.
- Facts contradicting frontmatter without anyone noticing.
- Backlinks rotting because writers forget `[[wikilinks]]` (every log entry
  mentions field forces them).
- Hallucinated claims surviving because no source check was done.
