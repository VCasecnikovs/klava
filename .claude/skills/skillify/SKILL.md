---
name: skillify
description: Capture current session workflow into a reusable skill
user_invocable: true
---

# Skillify

Interactive wizard that replays the current conversation, extracts the repeatable workflow, and writes it as a new skill. Complementary to `/skill-creator` (reference manual for skill anatomy) - skillify is the hands-on builder that learns from what just happened.

## When to Use

User types `/skillify` after completing a workflow they want to capture as a reusable skill.

## Flow

1. **Session Replay** - analyze conversation history
2. **4-Round Interview** - refine the skill interactively
3. **Generate SKILL.md** - preview for approval
4. **Save and Commit** - write file, fix permissions, git commit

## Step 1: Session Replay

Analyze the current conversation to extract the workflow that was just performed.

**Extract:**
- Tools used (Read, Write, Edit, Bash, Grep, Glob, etc.) and in what order
- Files touched (read, created, modified)
- External commands run (CLI tools, scripts, APIs)
- User corrections and course-corrections mid-task
- Decision points where the user chose between options
- Inputs that varied (arguments, file paths, names) vs constants
- Success criteria - how the user confirmed the task was done

**Produce a draft workflow summary:** numbered list of steps, each with: action taken, tool used, what it produced. Present this to the user as the starting point.

## Step 2: 4-Round Interview

Ask questions in plain text (not AskUserQuestion - unreliable in our setup). One round per message. Wait for user response before proceeding to next round.

### Round 1: Identity

Present your draft workflow summary from Step 1 and ask:

- **Name:** Propose a kebab-case name based on what was done. Ask user to confirm or rename
- **Description:** Propose a one-line description (keep simple - no colons/quotes). Confirm
- **Goal:** What does this skill accomplish? What problem does it solve?
- **Success criteria:** How do you know the skill worked correctly?

### Round 2: Steps and Arguments

Present the refined step list and ask:

- Review the steps - anything missing, wrong order, or unnecessary?
- Which values should be **arguments** (vary per invocation) vs **hardcoded**?
- **Save location:** project `.claude/skills/` or personal `~/Documents/GitHub/claude/.claude/skills/`? Default to personal unless user says otherwise
- Does this skill need any **scripts/** (deterministic code), **references/** (docs to load), or **assets/** (templates)?

### Round 3: Per-Step Deep Dive

For each step, confirm:

- **Produces:** What output does this step create? (file, data, side effect)
- **Success check:** How to verify this step worked?
- **Execution mode:**
  - `Direct` (default) - the agent executes directly
  - `Task` - delegate to subagent via Task tool
  - `[human]` - user performs this step manually (agent waits)
- **Parallel:** Can this step run in parallel with adjacent steps?
- **Irreversible?** If the step has side effects (sends message, deploys code, deletes file) - mark as `[human checkpoint]` requiring user confirmation before executing

Keep this round efficient. Group simple steps, only deep-dive on non-obvious ones.

### Round 4: Triggers and Rules

- **Trigger phrases:** What would a user say that should invoke this skill? (for the description field)
- **Hard rules:** Any gotchas, constraints, or "never do X" learned during the session
- **User corrections from session:** Present any corrections the user made during the original workflow and ask: "Should these become permanent rules in the skill?"

## Step 3: Generate SKILL.md

Assemble the complete SKILL.md and present it as a code block for review.

**Structure:**

```markdown
---
name: {name}
description: {description from Round 1, include trigger phrases from Round 4}
user_invocable: true
---

# {Title}

{One paragraph: what this skill does and when to use it}

## Flow

{Numbered overview of all steps}

## Step N: {Name}

{Instructions for each step}

**Execution:** {Direct | Task | [human]}
**Produces:** {what this step outputs}
**Verify:** {how to check it worked}

## Hard Rules

{Constraints, gotchas, "never do X" from Round 4 and session corrections}
```

**Generation rules:**
- Use imperative voice ("Read the file", not "The file should be read")
- Include specific file paths, tool names, CLI commands - not vague instructions
- Capture user corrections as Hard Rules, not just step modifications
- Keep under 300 lines. Split to references/ if approaching limit
- No README, CHANGELOG, or auxiliary files
- `user_invocable: true` unless the skill is only for automated pipelines
- Frontmatter description must include trigger phrases so the skill auto-matches

**Show the complete SKILL.md to the user as a code block.** Ask: "Look good? Any changes before I save?"

## Step 4: Save and Commit

After user approves (or after applying their edits):

1. Create the skill directory if it doesn't exist
2. Write SKILL.md to the chosen location
3. Create any scripts/, references/, assets/ files identified in Round 2
4. Fix permissions: `chmod 644 SKILL.md` (and `chmod 755 scripts/*.py scripts/*.sh` if any)
5. Git add and commit: `skill: add /{name} - {one-line description}`

Report: skill path, how to invoke (`/{name}`), and any follow-up suggestions (e.g. "test it on a real task next time the workflow comes up").

## Hard Rules

- Never skip the preview step (Step 3). User must see the full SKILL.md before it's written
- Never use AskUserQuestion - it's unreliable. Ask in plain text, one round per message
- Keep frontmatter description simple - no colons, quotes, or complex formatting (breaks YAML parsing)
- If the session had no clear repeatable workflow, say so honestly instead of fabricating one
- Don't duplicate what skill-creator already covers (skill anatomy, progressive disclosure, packaging). Skillify is the interactive builder, skill-creator is the reference manual
- Capture user corrections as Hard Rules in the generated skill, not just as step adjustments
