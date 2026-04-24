---
name: meeting-processing
description: Process meeting transcripts and notes into structured knowledge and tasks. Use when user shares a call transcript or says to process a meeting.
user_invocable: true
---

# Meeting Processing Skill

Extracts structured information and action items from meeting transcripts (Granola, manual paste, or any format).

## Triggers

- User shares a meeting transcript or notes
- User says "process meeting", "process this call"
- `/meeting-processing` command

## Auto-Processing Mode (optional)

If you have an automated intake pipeline that detects new meeting recordings, it can run a safe subset of this skill. Split responsibilities so auto-processing never writes to high-stakes entities without user review.

**Phase 1 - Auto (intake runs):**
- Step 1: Identify participants
- Step 3: Extract key information
- Step 4: Update Obsidian People notes (create stubs, tag them so cleanup can find them later, update `last_contact`)
- Step 5: Update Obsidian Organizations notes (stubs only)
- Step 7: Create Google Tasks from action items

**Phase 1 constraints:**
- Auto-created People/Org notes are minimal stubs so a later pass can enrich them
- No deal writes - Step 6 runs as PROPOSAL ONLY, included in output for user review
- Unrecognized names are flagged for the user, never auto-created

**Phase 2 - Manual (user triggers `/meeting-processing`):**
- Step 2: Deal pipeline cross-reference (full checklist approach with user confirmation)
- Step 6: Create/update Deal notes (after user confirms proposals from Phase 1)
- Enrich Phase 1 stubs with full context from transcript
- Handle unrecognized names with user input

**When the user runs `/meeting-processing` on an already auto-processed meeting:**
- Skip steps already done (check for existing History entries with same date)
- Focus on deal writes and enrichment
- Remove stub tags after enrichment

## Input Sources

1. **Meeting recorder export** (Granola, Otter, Fireflies, etc.) - raw transcript file or JSONL
2. **User-pasted text** - transcript + notes in the conversation
3. **Recorder link** - e.g. `https://notes.granola.ai/t/...`

## Processing Steps

### 1. Identify participants

- Extract all participants from transcript/notes
- Search Obsidian `People/` for existing notes (Glob by name, company)
- Search any personal data lake (email, chats, CRM) if not found in Obsidian
- Note which participants are new vs existing

### 2. Deal pipeline cross-reference (CRITICAL for sales partner calls)

**When the meeting participant is a sales partner/referrer :**

This step is MANDATORY. The garbled transcript WILL miss deals. The only reliable method is checklist-based.

1. **Pull the full deal list** for this participant: `grep -rl "Participant Name" ~/Documents/MyBrain/Deals/`
2. **Build a checklist** of ALL deals where they are lead/referrer
3. **For each deal on the checklist**, scan the transcript for ANY reference (company name, product type, person name, even partial/garbled matches)
4. **Present the checklist to the user** BEFORE writing updates: "I found evidence of discussion for X, Y, Z. Did you also discuss A, B, C?" - let user confirm/deny
5. **For abbreviations and unclear references** (e.g. "MD", "они посмотрели") - ASK the user, don't guess. List possible matches from the checklist

**Why this matters:** Garbled Granola transcripts make it impossible to catch everything from transcript alone. In past calls, deals were missed that were only found after reviewing the full checklist with the user.

### 3. Extract key information

From the transcript, extract:

- **Topics discussed** - main themes and subjects
- **Decisions made** - any agreements or conclusions
- **Market/industry insights** - competitive intelligence, trends, pricing
- **Technical details** - specs, requirements, constraints
- **Relationship context** - how people know each other, dynamics
- **Numbers** - pricing, volumes, timelines, team sizes

### 4. Update Obsidian People notes

For each identified participant (use `/people` skill patterns):

- **Existing note**: update frontmatter (`last_contact`), append to History, update Current/Background if significant new info
- **New person**: create note from template with whatever is known
- **Cross-link**: link people to companies `[[Company]]`, to each other, and to deals

### 5. Update Obsidian Organizations notes

If new companies discussed (use `/organizations` skill patterns):

- Check if Organization note exists
- Create or update with new information
- Cross-link to people and deals

### 6. Create or update Deal note

If the meeting involves a business lead/prospect (someone who wants to buy or partner):

- Check `~/Documents/MyBrain/Deals/` for existing deal with this company
- **Existing deal**: update with meeting notes, new info, adjust stage if needed
- **New lead**: create deal note immediately. Don't wait - every business meeting = deal note

**Deal note location:** `~/Documents/MyBrain/Deals/{Company} — {Product}.md`

**Frontmatter:**
```yaml
tags:
  - deal
lead: "[[Person Name (Company)]]"
stage: 1-prospecting          # or higher if meeting showed more progress
product: Short product name
value:                         # fill if discussed
mrr:
referrer: "[[Referrer]]"       # who introduced, if known
referrer_fee:
deal_size: small               # small <$10k, medium $10k-$100k, large >$100k
deal_type: api                 # data-sale, api, solution, partnership
owner: Вадим
owner_fee:
payment_type:
last_contact: YYYY-MM-DD
follow_up: YYYY-MM-DD          # next action date
telegram_chat:                  # chat_id if known
```

**Sections:** Сделка (summary), Что хотят (their needs), Context (how they found us, background), Meeting notes (chronological), Next steps (brief text, actual tasks in Google Tasks)

**Cross-link:** update People and Organization notes to reference `[[Deal Name]]`

**Stage guidance from meeting signals:**
- Just met / exploring = 1-prospecting
- Showed demo / they're interested = 2-qualification
- Discussing specifics / pricing = 3-proposal
- Pilot agreed = 6-pilot
- When unsure, default to 1-prospecting

### 7. Create action items as Google Tasks

Extract every actionable commitment from the meeting:

- What the user committed to do
- What others committed to do (track as follow-up)
- Deadlines mentioned or implied
- Follow-up meetings to schedule

Create Google Tasks with:
- Clear title referencing the context (e.g. "Acme Corp: send pricing sheet to Jane")
- Notes with full context so the task is self-contained
- Due dates (if mentioned, otherwise +5 business days)
- Task list: use the main Google Tasks list (configured in config.yaml)

### 8. Summary output

Present to user:

| Section | Content |
|---------|---------|
| Meeting info | Date, participants, duration, topic |
| Obsidian updates | What was created/updated (with file paths) |
| Google Tasks created | List with deadlines |
| Key insights | 3-5 most important takeaways |
| Suggested follow-ups | Things not captured as tasks but worth considering |

## Rules

- **Language**: Notes in English, Russian only for direct quotes
- **Preserve existing data**: When updating Obsidian notes, NEVER delete existing content
- **Self-contained tasks**: Each Google Task description must have enough context to act on without re-reading the transcript
- **Wikilinks**: Always cross-link people, companies, deals in Obsidian. Participant wikilinks MUST use actual Obsidian note filenames (e.g. `[[FirstName (Company)]]`, `[[FirstName LastName]]`). NEVER use generic labels like `[[People/Name (Me)]]` or `[[People/Name (Role)]]` - omit the `People/` prefix and resolve names to real note filenames
- **Dedup**: Check History section before appending - don't duplicate entries for same date+event
- **Err on the side of capturing more**: Better to create a task that gets deleted than miss an action item
- **ASK, don't guess**: For abbreviations, unclear references, ambiguous attributions (who told whom) - ASK the user. Wrong guess = wrong data in CRM
- **Verify known facts**: Government platforms (SAM.gov not SEM), company names, directions of information flow (who told whom about what) - verify before writing
- **Checklist before output**: Before presenting the final summary, show the user the full deal checklist with status (discussed/not discussed/unclear) - get confirmation BEFORE writing all notes

## Transcription quality and AI summary trust

**CRITICAL: AI-generated summaries (notes field) can FABRICATE entities.** Known failure mode: a recorder's AI summary invents a plausible person name from context clues (location + caller's first name), when the actual caller is someone else. Trusting that name creates phantom person/deal notes across the entire knowledge base.

**Trust hierarchy:**
1. **Raw transcript** (`transcript` field) - ground truth for WHO said WHAT. Use this for participant identification and fact extraction
2. **Calendar events** - cross-reference for participant names (most reliable source for WHO was on the call)
3. **AI-structured notes** (`notes` field) - useful for topic extraction and structure, but NEVER trust for participant names, company names, or entity identification
4. **Existing Obsidian/CRM data** - cross-reference all entities against known people/deals

**Transcription is poor for non-English speech and jargon.** Company names, people names, and technical terms often get garbled. A common pattern: "Wevan Labs" in the transcript turns out to be "ElevenLabs".

**Rules for handling meeting data:**
1. **ALWAYS prefer raw transcript over AI summaries for entity identification** - summaries hallucinate names and relationships
2. **Cross-reference calendar** for meeting participants before trusting any names from notes/transcript
3. **When a name doesn't match any known entity** - search Obsidian (and any personal data lake, if you have one) for phonetically similar names before creating a new note
4. **Flag unrecognized names to user** before creating new deal/people notes - ask "is this X?" rather than blindly creating
5. **Never create new Person notes based solely on AI summary** - require transcript evidence or user confirmation
6. **Common patterns:** English company names get mangled into random syllables, Russian words get mixed with Spanish/Portuguese fragments
