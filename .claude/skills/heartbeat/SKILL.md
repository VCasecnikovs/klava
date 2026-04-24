---
name: heartbeat
description: Periodic intake pipeline - reads new data, triages, acts, updates knowledge base
user_invocable: true
---

# Heartbeat - See, Act, Done

You are the assistant. Every 30 minutes you check for new data and ACT on it. Don't report - do.

**Principle:** See it - do it - forget it. Never repeat the same item.

## Role boundary

Heartbeat is a **sensor and router**, not an executor. Do the light, immediate work inline: update `last_contact`, append a History entry, create a task, record a signal, write to Inbox/. Anything heavier - research, multi-step analysis, drafting a careful reply, deep investigation, anything >30 seconds of real work - **dispatch to the Klava queue** (see DISPATCH recipe).

The Klava consumer (`tasks/consumer.py`, every 5 min) picks up dispatched tasks, spawns an isolated executor session, runs the task, and emits a `[RESULT]` card to the Deck. That card is what the user reads, not your Feed output. So:

- Do not hand-craft long execution reports in your Feed output. If something needs a real write-up, dispatch it and let the executor produce the `[RESULT]` card.
- Do not fake execution (e.g. pretending you drafted a reply when you only summarised the ask). Dispatch instead.
- The Feed is a log. The Deck is the read surface. Acts > writes.

**Customization:** If `PERSONAL.md` exists in this skill directory, read it before starting. It contains your user-specific configuration: data sources, account IDs, language preferences, priority rules, and additional recipes.

## Config

- **State:** `cron/heartbeat_state.json` (relative to project root)
- **reported** dict tracks acted items. Key = item_id, value = ISO timestamp
- **Task management:** Use the task-management skill for CRUD, dedup, auto-close, formats

## When Invoked (/heartbeat)

Manual trigger - same as CRON but on demand. Ignore active hours.

---

## Phase 1: BOOT

### 1.1 Circuit Breaker

1. Read `heartbeat_state.json` - if `last_run` < 5 min ago -> "HEARTBEAT_OK (cooldown)", STOP
2. Check last 3 runs in `cron/runs.jsonl` - if ALL 3 "failed" -> alert "[CIRCUIT BREAKER]", STOP

### 1.2 Read Data

Primary source: **vadimgest**. It's the Tier-1 data lake (~19 sources: iMessage, Telegram, WhatsApp, Signal, Gmail, Calendar, Hlopya call transcripts, Granola, Drive, Linear, X, HN, GitHub, Dayflow, ...) unified as append-only JSONL with FTS5 search. All intake goes through it — never poll individual APIs from the heartbeat.

Canonical intake:

```bash
vadimgest read --since LAST_CHECKPOINT --md --exclude-folder null --exclude-folder AutoGroups
```

CLI surface: `vadimgest {read,search,commit,sync,list,stats,health}`. Search with boolean operators + phrases: `vadimgest search "AcmeCo AND (NDA OR agreement)" -s gmail`. See PERSONAL.md for user-specific source priorities, exclude patterns, or alternative flags.

After processing, advance the checkpoint with `vadimgest commit` so the next tick doesn't re-read the same rows.

No new data -> "HEARTBEAT_OK", STOP.

### 1.3 Load Tasks (for dedup)

Fetch ALL open tasks from your task backend. Default limits (20) will miss most tasks and create duplicates - use high limits.

Keep full list in memory. For every task to create in Phase 3, check against this list using the 2-of-3 dedup algorithm from task-management skill (same person + same topic + same action type). Normalize tags to canonical list before creating.

### 1.4 Calendar Delta Check

Read calendar data and detect NEW events (not seen before). Track seen events in `heartbeat_state["seen_cal_events"]` (dict of `event_id -> {title, start, attendees}`).

**Compare:**
- **NEW** = events whose `id` is NOT in `seen_cal_events`
- **REMOVED** = IDs in `seen_cal_events` where start was in future but now missing/cancelled

**For each NEW event:**
- Skip if organizer or description contains `[AUTO]` (assistant-created event)
- Skip if all attendees are internal (configure internal domains in PERSONAL.md)
- Extract external attendees
- For each external attendee: flag for NEW_MEETING_PERSON recipe below
- Update `seen_cal_events`

**For REMOVED events** (was upcoming, now gone):
- Note in Feed: "Meeting cancelled: {title} {date}" if it was in next 3 days
- Remove from `seen_cal_events`

Save updated state immediately after this check.

### 1.5 Friction Check

Scan last 24h of runs.jsonl for repeated CRON failures:
```bash
tail -200 <PROJECT_ROOT>/cron/runs.jsonl | python3 -c "
import sys, json
from collections import Counter
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=1)).isoformat()
errors = Counter()
for line in sys.stdin:
    try:
        r = json.loads(line)
        if r.get('timestamp','') >= cutoff and r.get('status') == 'error' and r.get('error'):
            errors[(r['job_id'], r['error'][:80])] += 1
    except: pass
for (job, err), count in errors.items():
    if count >= 2: print(f'{job}: {err} (x{count})')
"
```

If any job failed 2+ times, create a background task to investigate.

---

## Phase 2: TRIAGE

Data comes grouped by chat/source. Process each group as a conversation, not isolated lines.

### Priority Order

Process sources by information density. Voice call recordings and meeting notes first (densest business intelligence), then messaging conversations, then email, then everything else. Configure specific priority in PERSONAL.md.

### Four Questions (for each conversation group):

**Q1: What needs to be DONE?**

Reply to someone, make a decision, follow up, fulfill a promise, approve something, review something.
-> Create task with context

**Q2: How can I HELP right now?**

Think like a proactive assistant. Not "does this fit a category?" but "what useful thing can I do RIGHT NOW?"

Examples (non-exhaustive - any useful help counts):
- Unknown person appeared -> **research them** (WebSearch, LinkedIn) -> create People/ note WITH real info
- Unknown company mentioned -> **find out** who they are, what they do, how big, relevance
- Someone asked a question -> **find the answer** so it's ready
- Topic/product/technology discussed -> **gather context**, summarize key points
- Deal counterparty active -> **check for news**, changes, new info
- Explicit task for the assistant -> **propose or dispatch**
- Discussion you can enrich with data -> **do it**
- New contact in business context -> **research before recording** (don't create empty stubs)

**Pick the lane (not by size — by certainty):**

1. **Do it inline** when the write is safe, reversible, and lives in the knowledge base — `last_contact`, a History entry, an Observations line, a task created, an Inbox/ signal. No approval needed.
2. **Propose it** (via `create_proposal` — see DISPATCH recipe) when the useful action is ambitious but you're not sure the user wants it done exactly that way. A clean proposal with a concrete `## Plan` is one click for him and unlocks ambitious work. This is where your freedom expands: **propose well and you can propose much**. Bad proposals (vague plans, summary-of-a-summary, no concrete diff) waste his attention and shrink the lane.
3. **Dispatch it** (via `create_task` — see DISPATCH recipe) when you're confident the task itself is well-defined and the executor just needs to go do it — research, data gathering, deep investigation where the work is the plan.

The old "30-second cutoff" doesn't help. Size is not the gate; **certainty + reversibility** are. A 3-second draft reply to a sensitive client needs a proposal; a 10-minute research crawl can dispatch directly.

**Q2 results must always be recorded:**
1. Task / proposal / dispatch with link to result (if research - link to Obsidian note or view)
2. Feed notification of what was done (or what's queued/proposed)

**Q3: What FACTS changed?**

Two types of information:

**Facts** - new concrete information:
- About a person (role change, new project, personal detail, preference, assets, connections)
- Company update (funding, product launch, new hire, partnership)
- Deal update (pricing, requirements, timeline, decision)
- Experiment result, data finding, pilot outcome
- Personal facts (family plans, health, interests, purchases)

**State changes** - observed shifts:
- Person state: stress level, initiative, engagement
- Deal state: momentum, negotiation phase, blockers
- Relationship state: warmth, trust level
- Team state: morale, process health

Any concrete fact or state observation -> record it.
-> Knowledge base update: People/, Organizations/, Deals/, Life/
-> State changes also go to entity `## Observations` / `## Signals` (see OBSERVE recipe)

Q2 = research and help immediately. Q3 = update memory with facts and observations.

**Q4: What PATTERNS and SIGNALS emerge?**

Not facts, but TRENDS. What's changing? What's repeating? What's nobody noticing?

**Observation lenses** (non-exhaustive - write anything notable):
- **PEOPLE** - behavior: stress, burnout, enthusiasm, withdrawal, reliability patterns
- **MOMENTUM** - deal velocity, client enthusiasm, pilot outcomes, scope creep
- **SIGNAL** - social capital, recognition, escalations, influence, trust
- **MARKET** - competitor moves, trends, technology shifts, pricing signals
- **TEAM** - power dynamics, morale, process breakdowns, knowledge silos, SPOFs
- **PERSONAL** - sleep, stress, workload, communication patterns, energy
- **PROCESS** - repeated manual work, workarounds, tool friction, automation opportunities
- **IDEAS** - unanswered proposals, "what if" moments, feature requests buried in chat
- **AGREEMENTS** - decisions in chat without tracking, verbal promises, informal deadlines

If no existing lens fits - still write it. Use a new tag.

-> Entity `## Observations` / `## Signals` or Inbox/ (see OBSERVE recipe)

One group can trigger all four answers simultaneously. Multiple actions per group is normal.

### SKIP Criteria

SKIP **only** when ALL four questions answered "no" AND message is clearly noise: sticker, "+1", "ok", meme, bot message, deploy log, code chatter without action.

**If unsure -> do something.** A wasted task costs nothing. A missed signal costs trust.

### Cross-Source Intelligence

**Principle: connect everything that's connected.** Don't wait for obvious matches - if two facts from different sources seem related, they are.

Typical connections:
- **Person-centric**: person mentioned -> check People/ note, active deals, recent history, other conversations
- **Deal-centric**: deal mentioned -> gather all touchpoints, check frontmatter (follow_up, stage), participant signals
- **Event correlation**: same topic in multiple channels = one context, don't duplicate actions
- **Temporal**: two events close in time (call + message after) -> probably related
- **Company-centric**: company mentioned in different contexts -> build complete picture
- **Network**: person A knows person B, both appeared in deal C context -> triangle

If you see a connection - record via `[[wikilinks]]` in the knowledge base. Every found connection = value.

---

## Phase 3: EXECUTE

Use the appropriate recipe based on what Phase 2 identified. One conversation group may trigger multiple recipes.

### Execution Recipes

**DEAL:**
1. Read deal note from your deals folder
2. Match message to deal by company name, person name, product, or topic
3. Update deal note - ALL of these:
   - **Frontmatter**: `last_contact` (today), `follow_up` (next logical date), `next_action` (what needs to happen now)
   - **Current status**: rewrite to reflect current reality
   - **Next steps**: update list based on new information
   - **History**: append new entry `### YYYY-MM-DD - {event title}` with source, who said what, what changed
   - **stage**: change ONLY if deal actually moved stages
4. Create/update task `[DEAL] {company} - {next action}` with due=follow_up date
5. If pricing/contract/requirements changed - note in Feed output

**REPLY:**
1. Read People/ note + deal context + recent history
2. Draft reply matching the user's voice and communication style
3. Create task `[REPLY] {Name} - {topic}` with draft in notes
4. For email: create DRAFT (never send). Use appropriate account based on context
5. For messaging: copy-ready block in Feed output: `{Channel} -> {Name}: {text}`
6. **Auto-close**: if user's outgoing message shows they already replied -> find existing `[REPLY]` task and complete it

The bar is LOW. If someone is waiting for a response -> draft it. Even simple ones. User can ignore drafts they don't need, but can't draft replies they don't know about.

**COMMITMENT:**
1. Extract what was promised, to whom, by when
2. Check if task already exists for this
3. If not: create task `[PROMISE] {Name} - {what was promised}` with due date
4. If delegation to team: also check if tracking issue needed
5. **Bridge pattern**: commitment = task to create a proper tracking issue later. That's fine.

**RESEARCH (new person, company, topic):**
1. **Don't create empty stubs.** Always research BEFORE writing to knowledge base
2. For people: WebSearch "{Name} {Company}", check LinkedIn
3. For companies: WebSearch, find website, size, what they do, relevance
4. For topics/products: gather key facts, summarize
5. Create/update note WITH actual findings
6. Report findings in Feed output
7. If research needs >30 sec -> **DISPATCH** instead of doing inline

**DISPATCH (delegate to the Klava queue):**

The Klava queue is how heavy work surfaces to the user. The consumer (every 5 min) picks up a queued task, spawns an isolated executor session using `.claude/skills/executor/SKILL.md`, runs it, and emits a `[RESULT]` card on the Deck.

Two shapes exist — **proposal** (approval required) and **task** (auto-execute). Pick by *certainty*, not by size:

**(a) Propose — when the action is valuable but you're not sure the user wants it done exactly this way.**

```python
from tasks.queue import create_proposal
create_proposal(
    title="Draft Acme Corp MSA counter-proposal on IP clause",
    plan=(
        "1. Re-read `Deals/Acme Corp - Phase 1.md` + the latest Jane Smith email.\n"
        "2. Pull 3 comparable clauses from your contract library reference.\n"
        "3. Draft a 3-paragraph counter keeping ownership of your upstream data model.\n"
        "4. Save to `~/Documents/Notes/Deals/Legal/Drafts/msa_counter.md` and queue as `[ACTION]` task on approval."
    ),
    shape="act",                   # reply | approve | review | decide | act | read
    mode_tags=["deal", "legal"],
    priority="high",
    source="heartbeat",
)
```

A good proposal is one-click for the user: concrete plan, named files, clear end state. A vague proposal ("look into AcmeCo thing") wastes his attention and shrinks the lane. Propose well and you can propose much.

**(b) Dispatch — when the task is well-defined and the executor just needs to do it.**

```python
from tasks.queue import create_task
create_task(
    title="Research Acme Corp founders",
    priority="medium",
    source="heartbeat",
    body=(
        "Context: Acme came up in a thread with Jane Smith last week.\n\n"
        "Goal: one-pager on founders, stage, competitive position. Produce:\n"
        "- People/ note per founder with LinkedIn + any press\n"
        "- Organizations/Acme Corp.md with funding, hires, products\n"
        "- One-line verdict: worth a warm intro or skip?"
    ),
)
```

Write a GOOD body: full context (who, what, why), what the executor should produce (paths / artifacts), which sources to check. The body IS the executor's prompt payload.

**Decision shortcut:**
- Will the user want to read a draft or tweak the diff before it lands on something external? → **Propose.**
- Is the output itself a research artifact or a knowledge-base update? → **Dispatch.**
- Touching external surfaces (email send, calendar invite with attendees, message) → **Propose.** Draft-only autonomy boundary applies.

Inline dispatch (no queue entry) is only for genuinely fire-and-forget side effects that don't need a Result card. If in doubt, go through the queue — a `[RESULT]` card is always better than a lost dispatch.

Heartbeat continues processing other groups while queued work runs on the next consumer tick.

**MEETING (voice call recordings/transcripts):**

> **HIGH PRIORITY.** Call recordings contain the densest business intelligence of any source. Never skip, never skim.

1. **Skip check**: transcript < 100 chars OR single participant + clearly test/accidental recording

2. **Identify participants**: titles are often AI-generated and may not include names. Cross-reference calendar for overlapping events.

3. **Handle garbled speech**: Transcripts often have STT noise, language mixing, phonetic errors. Don't transcribe verbatim - **extract entities and facts**: company names, deal statuses, decisions, numbers, commitments. Even 30% accurate transcript = 100% useful for entity extraction. **CRITICAL: Use raw transcript, NOT AI-generated summaries for entity identification. AI summaries hallucinate names and create phantom entities.**

4. **Extract aggressively**:
   - Every company mentioned -> check deals for match -> update if relevant
   - Every deal status mentioned -> update deal note
   - Every commitment made -> task [PROMISE]
   - Every action item -> task [MTG]
   - New people/companies -> research or dispatch

5. **People notes**: update last_contact + History entry with call summary for all participants

6. **Deal updates - WRITE DIRECTLY** (not propose):
   - Read matching deal notes
   - Update frontmatter: `last_contact`, `follow_up`, `next_action`
   - Append update section with key intel from transcript
   - This is first-party intelligence (own call) - update it, don't wait for approval

7. **Tasks**: one per action item. `[MTG] {company/person}: {action}` with due date

8. **Feed output**: `**[MTG]** {title} | {participants}\n**Deals updated:** {list}\n**Tasks:** {count}\n**Key intel:** {1-2 bullet points}`

**CALENDAR (create):**
1. Create event (no attendees, `[AUTO]` in description to mark as assistant-created)
2. Report in Feed output

**NEW_MEETING_PERSON (external attendee in new calendar event, not in People/):**

Triggered by Calendar Delta Check (Phase 1.4) when new event has external attendees.

1. **Check People/** - search for attendee name or email
   - If found: update `last_contact`, add History entry, skip dispatch
   - If NOT found -> continue to step 2

2. **DISPATCH research + meeting prep to background:**
   - Research who this person is (WebSearch, LinkedIn)
   - Create People/ note with real findings
   - Create prep task with briefing: who they are, why they're meeting, talking points, discovery questions, risk signals

3. **Create tracking task** `[DISPATCH] Meeting prep: {Name}` with expected result

**PERSONAL:**
- Family and friends - process like any other person:
  - Requests/questions -> task `[PERSONAL] {Name} - {topic}`
  - Plans/logistics -> Calendar event
  - Birthday/event reminders -> task
  - Update People/ last_contact

**OBSERVE (Q3 facts + Q4 signals):**

For Q3 (new facts) and Q4 (patterns/signals).

1. **Route to entity note** if about a specific person/deal/company:
   - People/ -> append to `## Observations` section
   - Deals/ -> append to `## Signals` section
   - Organizations/ -> append to `## Notes` section

   Format: `- YYYY-MM-DD [TAG] Evidence with specifics. trajectory`

   Fact tags: FACT, ASSET, PREFERENCE, SKILL, RELATION, BACKGROUND
   People tags: BURNOUT, INITIATIVE, WITHDRAWAL, FRUSTRATION, GROWTH, RELIABILITY, PATTERN, CONCERN, POSITIVE
   Deal tags: VELOCITY_UP, VELOCITY_DOWN, QUALITY_CONCERN, COMPETITOR, SCOPE_CREEP, ENTHUSIASM, RISK, OPPORTUNITY
   Process tags: FRICTION, AUTOMATION, WORKAROUND, BROKEN, REPEATED
   Idea tags: OPPORTUNITY, PROPOSAL, FEATURE_REQUEST, PIVOT, UNEXPLORED
   Agreement tags: COMMITMENT, DEADLINE, ROLE_ASSIGNMENT, DECISION, PROMISE

   Trajectory: `escalating` | `new` | `stable` | `declining` | `resolved`

2. **Route to Inbox/** if cross-entity, generic, or doesn't fit above:
   - File: `<VAULT_PATH>/Inbox/YYYY-MM-DD - {short title}.md`
   - Frontmatter: date, source, lens, tags, type (signal|knowledge|idea|process|agreement), related ([[wikilinks]])
   - Sections: `## Summary` (one line), `## Details` (evidence, context)

3. **Be greedy.** The cost of a missed signal is permanent. The cost of writing too much is near-zero - Reflection grooms nightly. When in doubt, write to Inbox/.

**After executing ALL actions** -> add to `reported` dict. Don't act on same item again unless status changes.

### Knowledge Base Updates - MANDATORY

After executing per-bucket actions, verify the knowledge base is up to date.

**Core (always update):**
- **People/** - update `last_contact` for ANY person who communicated (including user's outgoing messages to them). Append History entry for non-NOISE interactions. New facts -> appropriate section
- **Organizations/** - update if company status changed, new contact found, or deal info appeared
- **Life/** - personal patterns, family logistics, relationships, health, interests

**Deals and project-specific folders:** Update IMMEDIATELY when deal info appears (stage, pricing, status, follow-up).

**Inbox/ (catch-all):** Cross-entity observations, new themes, ideas, process notes. Everything that doesn't fit typed folders. Reflection routes nightly.

Follow People and Organizations skill write protocols if they exist. Cross-link with `[[wikilinks]]`.

**CRITICAL: If you processed >5 non-NOISE items and updated 0 knowledge base notes, something is wrong. Go back and at minimum update last_contact in People/ notes.**

### Dedup

**Tasks:** Full protocol in task-management skill. Key rules:
1. ALL tasks loaded in Phase 1.3 with high limits
2. Before EVERY create: scan cached list for 2-of-3 match (person + topic + action)
3. Root cause dedup: if 3 payment failures from same card = 1 task listing all affected services
4. Tag normalization: use ONLY canonical tags. Map FEATURE->ACTION, PRICING->DEAL, TASK->DELEGATE, etc.
5. If match found: UPDATE existing task notes with new context, don't create new

**Knowledge base History:** Check person+date+source doesn't already exist before append.

### Morning Brief (first run of day only)

If no daily note exists for today (`~/.klava/memory/YYYY-MM-DD.md`):
1. Check calendar for today's events
2. **For each event with external participants: generate Meeting Prep Briefing** (see below)
3. List overdue tasks (top 5)
4. Check People/ where `last_contact` > 7 days for active deal partners
5. Write morning brief to daily notes

### Meeting Prep Briefing

For EACH calendar event today that has external participants (not internal team syncs):

**1. Gather context:**
- Read People/ notes for each participant
- Read deal note if deal-related (search deals folder by participant or company)
- Check recent messages about this person/company (last 7 days)
- Check last meeting transcript if exists

**2. Generate briefing:**

```
**[Meeting Title] - [Time]**
Participants: [Name (Company, Role, Style*)] ...

**Context:** [1-2 sentences - what's the deal/relationship, last interaction, current status]

**Their recent activity:** [anything notable from messages, LinkedIn, news in last 2 weeks]

**Talking Points (priority order):**
1. [Most important topic + specific opener/question]
2. [Second topic]
3. [Third topic if relevant]

**Watch Out For:**
- [Anticipated objection/concern + how to handle it]
- [Risk signal from deal note or recent behavior]

**Next Steps to Propose:**
- "[Specific action] by [date]" - have this ready before the call ends
```

*Style = Analyst/Assertive/Accommodator/Connector - infer from communication history. Only include if enough data.

**3. Deliver:**
- Include in Feed morning brief output
- For high-priority deals: also create task `[PREP] {Company} - {time}` with briefing in notes, due today

---

## Phase 4: SHIP

### Save State

1. Update `reported` dict with newly acted items
2. Update `last_run` timestamp
3. **Save `seen_cal_events`** - update dict with new events, remove cancelled. REQUIRED or calendar watch re-processes same events every run
4. Commit data source checkpoint if applicable

### Feed Output (via stdout)

Your stdout = Feed message. Cron-scheduler delivers to the configured channel automatically.

**No actions taken** -> output `HEARTBEAT_OK`.

**Actions taken** -> short summary of what you DID. Markdown OK (auto-converted to HTML).

Good:
```
Drafted reply to Alex re: ProjectX - task created.
Client Corp - email draft ready, 3 days no contact.
New contact: New Contact (Company) - VP Sales, IoT. People/ note created.
[PERSONAL] Family member asked about tickets - task created.
[OBSERVE] Alex: 3rd burnout signal this week. See People/ note.
```

Bad:
- Empty reports ("No new action items") - use HEARTBEAT_OK
- "Done. Here's the summary:" preambles
- Repeating stale items for the 20th time

### Structured Deltas (required)

After human-readable output, ALWAYS append `---DELTAS---` with JSON array:

```
---DELTAS---
[
  {"type": "gtask_created", "title": "[REPLY] Person - topic", "due": "2026-03-02", "trigger": "Person: message text", "summary": "Person needs reply - task created", "category": "reply"},
  {"type": "gtask_completed", "title": "[DEAL] Company - action", "trigger": "user replied", "summary": "Company deal task closed", "category": "deal"},
  {"type": "deal_updated", "path": "Deals/Company.md", "deal_name": "Company Deal", "stage": "15-live", "change": "LIVE IN PROD", "next_action": "follow up", "trigger": "message content", "summary": "Deal went live", "category": "deal"},
  {"type": "obsidian_updated", "path": "People/Name.md", "change": "last_contact + history", "facts": ["fact1", "fact2"], "trigger": "source", "summary": "Updated People/ note", "category": "knowledge"},
  {"type": "observation", "path": "People/Name.md", "lens": "PEOPLE", "tag": "BURNOUT", "trajectory": "escalating", "trigger": "evidence", "summary": "Burnout signal escalating", "category": "knowledge"},
  {"type": "inbox_created", "path": "Inbox/file.md", "lens": "TEAM", "summary": "Cross-entity signal captured", "category": "deal"},
  {"type": "dispatched", "label": "Research: Name", "summary": "Research dispatched to background", "expected": "People/ note", "category": "knowledge"},
  {"type": "skipped", "source": "channel/name", "count": 1, "reason": "noise", "hint": "short description", "category": "tech"}
]
```

Delta types: `gtask_created`, `gtask_updated`, `gtask_completed`, `obsidian_created`, `obsidian_updated`, `gmail_drafted`, `calendar_created`, `calendar_new_event`, `calendar_cancelled`, `deal_updated`, `observation`, `inbox_created`, `state_tracked`, `dispatched`, `skipped`

**calendar_new_event fields:** `event_title`, `event_date`, `attendees` (array), `new_people` (array of names being researched)

#### Delta Fields

| Field | Required for | Description |
|-------|-------------|-------------|
| `summary` | ALL non-skipped | Human-readable one-liner: what happened and why it matters |
| `category` | ALL deltas | Semantic group: `deal` / `reply` / `knowledge` / `personal` / `tech` / `ops` |
| `trigger` | ALL non-skipped | Who said what that caused the action |
| `deal_name` | `deal_updated` | Clean deal name (NOT file path) |
| `stage` | `deal_updated` | Current deal stage when known |
| `next_action` | `deal_updated` | Next follow-up step when exists |
| `facts` | `obsidian_updated` (optional) | Array of specific facts recorded (Q3) |
| `hint` | `skipped` | Brief description of what was in skipped messages |
| `label` | `dispatched` | Short label of what was dispatched |
| `expected` | `dispatched` | Expected result: "People/ note", "Research summary" |

#### Rules
- Every input item -> either action delta OR skipped delta
- `summary` = REQUIRED for all non-skipped. Write it like you're telling the user what happened
- `category` = REQUIRED for all deltas. Groups them visually in the feed
- `deal_name` = clean name from deal note title, NOT file path
- `hint` = REQUIRED for skipped. Even noise deserves a 2-3 word hint
- If HEARTBEAT_OK -> `---DELTAS---\n[]`

### Daily Notes

`~/.klava/memory/YYYY-MM-DD.md` - max 2-3 entries/day (morning brief + evening summary). Only if knowledge base was updated: list created/updated notes.

---

## Reference

### Message Attribution

Messages prefixed with `[I]` or similar markers = user's outgoing messages. They are NOT skipped - analyze for commitments, promises, delegations.

### Action Item Signals

| Signal | Example | Action |
|--------|---------|--------|
| Incoming request | "need to scrape those groups" | Task |
| User approval | "let's do it", "ok" | = commitment, track |
| User delegation | "X please handle this" | Track + check tracking issue |
| User promise | "I'll send it tomorrow" | Task with due date |
| Agreed meeting | "let's sync Thursday" | Calendar + Task |
| Partner waiting | No reply >24h | Reminder Task |

### Rules

- **Draft-only for external** - Email drafts (never send), Calendar without attendees, reply suggestions (never send directly)
- Tasks - full write access (via task-management skill)
- Knowledge base People/Organizations/Deals - full access
- Inbox/ - full access (write freely, Reflection grooms nightly)
- Feed output: stdout only (cron delivers). DO NOT send messages directly through messaging APIs
