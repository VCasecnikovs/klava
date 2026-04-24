---
name: reflection
description: Nightly knowledge grooming - routes Inbox, cross-links notes, detects silence, updates memory
user_invocable: true
---

# Nightly Reflection

You are the nightly groomer. Once per day you clean up everything the Heartbeat wrote during the day.

**Purpose:** Heartbeat writes fast and rough. You clean, connect, route, and update memory.

**Customization:** If `PERSONAL.md` exists in this skill directory, read it before starting. It contains vault paths, account IDs, extra phases, and user-specific configuration.

**CRITICAL: 4-phase execution.** Output phase markers as you work. Each phase has a budget. If you've spent >40% of tokens on one phase, wrap up and move to the next.

---

## Phase 1: ORIENT (budget: ~15%, read-only)

**Goal:** Understand what happened today. Build a mental map before touching anything.

### 1.1 Daily Notes

```bash
cat ~/.klava/memory/$(date +%Y-%m-%d).md 2>/dev/null
cat ~/.klava/memory/$(date -v-1d +%Y-%m-%d).md 2>/dev/null
```

### 1.2 Today's Sessions (optional)

If a session finder is configured in PERSONAL.md, run it to see what Claude sessions happened today.

### 1.3 Knowledge Base Changes

Find all notes modified today:

```bash
find <VAULT_PATH>/People/ \
     <VAULT_PATH>/Organizations/ \
     <VAULT_PATH>/Life/ \
     <VAULT_PATH>/Inbox/ \
     <VAULT_PATH>/Topics/ \
     -name "*.md" -mtime 0 2>/dev/null
```

Add any project-specific folders from PERSONAL.md (deals, research, etc.).

Don't read all files upfront - read on demand as you work. Context is limited.

### 1.4 Skill Changes

```bash
cd <PROJECT_ROOT> && git diff --name-only HEAD~5 -- .claude/skills/ .claude/CLAUDE.md 2>/dev/null
```

Note what skills/config changed since last reflection. May need to adjust behavior.

### 1.5 Current Inbox

```bash
find <VAULT_PATH>/Inbox/ -name "*.md" ! -name "README.md" 2>/dev/null | head -50
```

Read all Inbox items (not just today's - old unrouted items too).

**No raw data reads.** Reflection works only with the knowledge base + daily notes + sessions. Raw data intake is Heartbeat's job.

### Phase 1 Output

```
## ORIENT COMPLETE
- Daily notes: {found/empty}
- Sessions today: {N}
- Files modified: {N}
- Inbox items: {N}
- Skill changes: {list or "none"}
```

---

## Phase 2: GATHER & ROUTE (budget: ~30%)

**Goal:** Route Inbox items to their proper homes. Create Topics from converging signals.

### 2.1 Inbox Routing

Route items from the Inbox folder to proper locations.

#### Deep dump files (type: context-baseline)

Large raw data dumps (10KB+) with `type: context-baseline` in frontmatter. These are raw exports that an observer already processed into smaller observation files.

**How to handle:**
1. Read in chunks (first 200 lines + last 200 lines + keyword search for: "agree", "decide", "deadline", "money", "deal")
2. Extract ONLY novel observations not already captured in smaller Inbox files or existing notes
3. Append extracted items to appropriate destination files as dated entries
4. DELETE the deep file after extraction
5. If nothing novel found after sampling, just delete

**Budget rule:** Don't spend more than 5 minutes per deep file.

#### For each regular Inbox item:

Read the file. Decide where it belongs:

**Route to typed folder** if it clearly belongs there:
- About a specific person -> merge into `People/{Name}.md` (appropriate section)
- About a deal -> merge into deal note
- About a company -> merge into `Organizations/{Company}.md`
- About market/competition -> research folder
- About personal patterns -> `Life/{topic}.md`

**Route to existing Topic** if matches `Topics/*.md`:
- Read Topic titles and tags
- If item relates -> append to Topic's `## Items` with date

**Create new Topic** if 3+ Inbox items (across multiple days) converge on same theme:
- Only if theme doesn't fit cleanly into typed folders
- Create `Topics/{Topic Name}.md` (see format below)
- Move all related items into the new Topic

**Merge related items:** Multiple items about same thing -> combine with dated entries, delete duplicates.

**Cleanup:** Successfully routed -> delete from Inbox. Can't route yet -> keep for next night.

### 2.2 Topics Management

Manage auto-created knowledge categories in the Topics folder.

#### Topic format

```markdown
---
tags: [topic, {domain-tags}]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: ["{source1}", "{source2}"]
---

# {Topic Name}

## Summary
{1-2 sentence summary}

## Items
- YYYY-MM-DD: {dated entry}

## Related
- [[Entity 1]]
- [[Entity 2]]
```

#### Maintenance

1. Update `updated` date for Topics that received new items
2. Regenerate `## Summary` if 5+ new items since last summary
3. Merge Topics if two clearly cover same theme
4. Cross-link Topics that share entities
5. Update Topics README/index if one exists

#### Creation criteria

Auto-create only when:
- 3+ Inbox items (across multiple days) converge on same theme
- Theme doesn't fit People/Organizations/Deals/Life

### Phase 2 Output

```
## GATHER & ROUTE COMPLETE
- Inbox: {N} items, {M} routed, {K} to Topics, {J} new Topics, {L} kept
- Topics updated: {list}
```

---

## Phase 3: CONSOLIDATE (budget: ~40%)

**Goal:** Cross-link everything, groom knowledge base, detect silence, learn from feedback, update memory.

### 3.1 Cross-Linking

**Principle: everything related must be linked with `[[wikilinks]]`.**

Scan ALL files modified today. For each:

#### People/
- Person mentions company but no `[[Company]]` link -> add
- Person in deal context but no deal wikilink -> add
- Two people in same conversation -> cross-link both notes
- Person introduced by someone -> "Introduced by `[[Person]]`"

#### Organizations/
- Org mentions person but no `[[Person]]` in Contacts -> add
- Org has active deal but no deal link -> add

#### Deals/
- Deal mentions people/companies not linked -> add wikilinks
- Related deals (same client, same domain) -> cross-link

#### Life/
- Life entries mention people -> add `[[Person]]` links

#### Topics/
- Topics reference entities from other folders -> add `## Related` links

#### Complete frontmatter

For every modified file: fill empty frontmatter fields if data is available:
- People: handle, email, phone, company, role, location, met, last_contact
- Organizations: website, source, status, deal_size, last_contact
- Topics: tags, sources

**Safety:** APPEND/ENRICH only. Never delete existing content. Never overwrite non-empty fields unless clearly outdated.

### 3.2 Knowledge Base Grooming

#### Duplicates
Same person/company under different names -> merge into canonical name, preserve ALL content, update all wikilinks.

#### Broken wikilinks
`[[Name]]` pointing to non-existent files -> create stub if real entity, fix typo if spelling error.

#### Frontmatter normalization
- `tags` must be array: `tags: [a, b]` not `tags: "a"`
- `last_contact` must be YYYY-MM-DD or null
- All template fields must exist (even if empty)

#### Naming consistency
- People: `FirstName LastName.md` or `FirstName LastName (Company).md`
- Organizations: `Company Name.md`
- Fix: rename + update all incoming wikilinks

#### Orphaned cross-links
- Person's `company` field -> no Organizations/ note -> create stub
- Org's Contacts -> person with no People/ note -> create stub

**Safety:** NEVER delete information when merging. When renaming, update ALL references. When in doubt, log as TODO in daily notes.

### 3.3 Silence Detection

Detect entities going cold:

- **Deals:** any `follow_up` date in the past = overdue
- **People:** `last_contact` >= 14 days = stale (for active contacts only)

Write alerts to `Inbox/YYYY-MM-DD - Silence Alerts.md` with frontmatter `source: silence-detector`.

**Skip:** deals with stage containing `won`/`lost`/`closed`. People with `last_contact` > 180 days AND no active deals.

### 3.4 Feedback Learning

Analyze heartbeat reply suggestion quality.

#### Data
1. Tasks: completed `[REPLY]` tasks (approved) and deleted (rejected)
2. Cross-reference: suggestions used vs ignored

#### Analysis
- Approved: what made them good? Tone, length, context?
- Rejected: what went wrong? Too formal? Wrong context?
- Missing: replies user sent without a suggestion?

#### Actions
1. If pattern found -> update heartbeat skill or voice skill
2. Log: `Feedback: {N} approved, {M} rejected. Pattern: {insight}`
3. Update CLAUDE.md if significant preference discovered

### 3.5 Task Hygiene

Nightly dedup and cleanup of task backend.

#### Load all tasks
Use high limits to get the full list.

#### Dedup pass
Group all open tasks by person+topic. For each group with 2+ tasks:
1. Keep the NEWEST or most complete task
2. Merge notes from older tasks into the keeper
3. Complete older duplicates

#### Tag normalization
Fix non-standard tags to canonical set:
- `[FEATURE]` -> `[ACTION]`, `[PRICING]` -> `[DEAL]`, `[CONNECT]` -> `[INTRO]`
- `[RESEARCH]` -> `[ACTION]`, `[DRAFT]` -> `[REPLY]`, `[SYNC]` -> `[MTG]`
- `[TASK]` -> `[DELEGATE]`, No tag -> `[ACTION]`

#### Staleness check
- `[PREP]`/`[MTG]` for past events -> complete (event already happened)
- `[REPLY]` older than 14 days -> likely stale, check if still relevant
- `[DEAL]` older than 30 days -> check if deal is still active

### 3.6 Memory Update

Review what was learned today. Update:

#### CLAUDE.md
Update sections with: active deal status changes, key people context, business decisions, personal updates, new preferences.
**Exclude:** one-time debugging, implementation details, completed tasks, noise.

**User Edits:** If `### User Edits` section exists in CLAUDE.md, integrate ALL items into appropriate sections and clear the section.

#### Memory files
Update project-specific memory with patterns confirmed across sessions.

### Phase 3 Output

```
## CONSOLIDATE COMPLETE
- Cross-links: {N} new wikilinks across {M} files
- Grooming: {summary of fixes or "all clean"}
- Silence: {N} overdue deals, {M} stale people
- Feedback: {N} approved, {M} rejected. {insight}
- Tasks: {N} total open, {M} dupes merged, {K} tags normalized
- Memory: {changes or "no changes"}
```

---

## Phase 4: PRUNE & VERIFY (budget: ~15%)

**Goal:** Verify work, write summary, commit.

### 4.1 Verification

For each modified file:
- YAML frontmatter parses without error
- No broken wikilinks introduced
- No duplicate content from merge errors

#### On failure
1. Attempt fix (rewrite broken YAML, fix broken wikilinks)
2. Log: `FAIL: {check} - {error} -> {fix}`
3. If unfixable -> daily notes: `TODO: {description}`
4. Max 2 retries per file

### 4.2 Daily Summary -> Feed

After all phases, write summary AND output to stdout (Feed).

#### Append to daily notes (`~/.klava/memory/YYYY-MM-DD.md`)

```markdown
### Nightly Reflection

**Phase 1 (Orient):** {N} sessions, {M} files modified, {K} Inbox items
**Phase 2 (Gather):** {N} items routed, {M} to Topics, {K} new Topics
**Phase 3 (Consolidate):** {N} crosslinks, {M} grooming fixes, {K} silence alerts
**Phase 4 (Prune):** {N}/{M} checks passed

**Changes:**
- {File}: {what changed}
- ...
```

#### stdout = Feed message

Cron-scheduler delivers to configured channel. Include:
- Total files changed
- Most important discovery/connection
- Any issues needing attention
- Silence alerts summary (top overdue)

If nothing was done -> `HEARTBEAT_OK (reflection: no changes)`

#### Structured Deltas (required)

After human-readable output, ALWAYS append `---DELTAS---` with JSON array:

```
---DELTAS---
[
  {"type": "inbox_routed", "path": "People/Name.md", "from": "Inbox/source-file.md", "summary": "Signal routed to People/ note", "category": "knowledge"},
  {"type": "topic_created", "path": "Topics/Topic Name.md", "item_count": 4, "summary": "New topic created from converging items", "category": "knowledge"},
  {"type": "topic_updated", "path": "Topics/Topic.md", "items_added": 2, "summary": "Topic updated with new items", "category": "knowledge"},
  {"type": "crosslink_added", "count": 8, "files": ["People/A.md", "Deals/B.md"], "summary": "New wikilinks added", "category": "knowledge"},
  {"type": "obsidian_groomed", "action": "yaml_fixed", "path": "People/Name.md", "summary": "Fixed YAML frontmatter", "category": "ops"},
  {"type": "duplicate_merged", "kept": "People/A.md", "removed": "People/B.md", "summary": "Merged duplicate notes", "category": "ops"},
  {"type": "silence_alert", "entity": "Deals/Company.md", "days_stale": 27, "summary": "Deal overdue - N days no contact", "category": "deal"},
  {"type": "feedback_learned", "approved": 5, "rejected": 2, "insight": "pattern found", "summary": "Feedback analysis results", "category": "ops"},
  {"type": "memory_updated", "file": "CLAUDE.md", "change": "what changed", "summary": "Memory update description", "category": "ops"},
  {"type": "skipped", "source": "verification", "count": 1, "hint": "all checks passed", "category": "ops"}
]
```

Delta types: `inbox_routed`, `topic_created`, `topic_updated`, `crosslink_added`, `obsidian_groomed`, `duplicate_merged`, `silence_alert`, `feedback_learned`, `memory_updated`, `skipped`

#### Rules
- `summary` = REQUIRED for all non-skipped. Human-readable
- `category` = REQUIRED. Use: `knowledge` (routing, topics, crosslinks), `deal` (silence alerts), `ops` (grooming, memory, feedback)
- Every phase that produced changes -> at least one delta
- If nothing done -> `---DELTAS---\n[]`

### 4.3 Commit

```bash
cd <PROJECT_ROOT> && git add .claude/CLAUDE.md .claude/skills/ && \
  git diff --cached --quiet || git commit -m "reflection: $(date +%Y-%m-%d)"
# Daily notes live at ~/.klava/memory/ (outside the repo) and are NOT committed.
```

### Phase 4 Output

```
## PRUNE & VERIFY COMPLETE
- Checks: {N}/{M} passed
- Feed: {sent/nothing}
- Total files changed: {N}
```

---

## Execution Summary

| Phase | What | Budget |
|-------|------|--------|
| **1. ORIENT** | Read daily notes, sessions, knowledge base changes, Inbox | ~15% |
| **2. GATHER & ROUTE** | Inbox routing, Topics management | ~30% |
| **3. CONSOLIDATE** | Cross-linking, Grooming, Silence, Feedback, Tasks, Memory | ~40% |
| **4. PRUNE & VERIFY** | Verify changes, write summary, output Feed | ~15% |

**Phase markers are MANDATORY.** Output `===PHASE N: NAME===` before starting each phase and the phase completion block after.

---

## Safety

- **APPEND/ENRICH only** - never delete content from notes (except Inbox items after routing)
- **Never overwrite** non-empty fields unless clearly outdated
- **Never send** external messages (email, messaging)
- **Can edit** CLAUDE.md, skills, daily notes
- **Can create** stub notes, Topics, Inbox items
- **Can merge** duplicate notes (preserving ALL content)
- **Can rename** files (updating all references)
- **Can delete** Inbox items after successful routing
- **When in doubt** -> log as TODO in daily notes, don't make the change
