---
user_invocable: true
name: autoplan
description: Auto-review pipeline that runs product, architecture, and code reviews sequentially with auto-decisions. One command to get a fully reviewed plan
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
  - WebSearch
---

# /autoplan - Auto-Review Pipeline

One command. Rough plan in, fully reviewed plan out.

Runs 3 review perspectives sequentially - product thinking, architecture, code quality - auto-deciding mechanical choices using 6 principles and surfacing only taste decisions for the user's approval at the end.

## When to use

- Before implementing a feature: `/autoplan` on a plan file or description
- Before a big refactor: validates approach before writing code
- When you want rigorous review without 15 back-and-forth questions

## The 6 Decision Principles

These auto-answer every intermediate question:

1. **Choose completeness** - ship the whole thing, cover edge cases
2. **Blast radius** - fix everything in modified files + direct importers. Auto-approve if <5 files, no new infra
3. **Pragmatic** - two options fix the same thing? pick the cleaner one. 5 seconds choosing, not 5 minutes
4. **DRY** - duplicates existing functionality? reject. Reuse what exists
5. **Explicit over clever** - 10-line obvious fix > 200-line abstraction
6. **Bias toward action** - merge > review cycles > stale deliberation

**Conflict resolution:**
- Product phase: P1 (completeness) + P2 (blast radius) dominate
- Architecture phase: P5 (explicit) + P3 (pragmatic) dominate
- Code phase: P5 (explicit) + P4 (DRY) dominate

## Decision Classification

**Mechanical** - one clearly right answer. Auto-decide silently.
Examples: add error handling (always yes), reduce scope on a complete plan (always no).

**Taste** - reasonable people could disagree. Auto-decide with recommendation, but surface at the final gate.
Sources:
1. Close approaches - top two are both viable with different tradeoffs
2. Borderline scope - in blast radius but ambiguous
3. Multi-model disagreement - Codex/Gemini recommends differently and has a valid point

## Execution Flow

### Phase 0: Intake

1. Read context: CLAUDE.md, README, recent git log, git diff --stat
2. Identify the plan: user's description, a plan file, or infer from branch changes
3. Detect scope: is there UI? backend? infra? data pipeline?
4. Output: "Working with: [plan summary]. Scope: [areas]. Starting review pipeline."

### Phase 1: Product Review (the "is this the right thing?")

Think like a CEO/founder reviewing a feature proposal.

**Run through each:**

1. **Premise challenge** - what assumptions does this plan make? Which could be wrong?
   - List each premise explicitly. For each: valid/questionable/wrong + evidence
2. **Problem reframe** - is this solving the right problem? Could a reframing yield 10x impact?
3. **Scope calibration** - is this too big? too small? What's the narrowest wedge that delivers value?
4. **User impact** - who benefits? How much? Is this a painkiller or a vitamin?
5. **Alternatives** - what other approaches exist? Were any dismissed too quickly?
6. **6-month regret test** - what about this plan will look foolish in 6 months?

**GATE: Present premises to the user for confirmation.** This is the ONE question that is NOT auto-decided. Premises need human judgment.

**Optional multi-model voice:** If the plan is complex (>3 files affected), get a second opinion:
```bash
codex exec "Review this plan for strategic blind spots. Challenge premises. What alternatives were dismissed? File: <path>" -C "$(git rev-parse --show-toplevel)" -s read-only 2>/dev/null
```
Or via Gemini for larger context. Tag findings as `[codex]` or `[gemini]`.

Auto-decide remaining questions using principles. Log each decision.

### Phase 2: Architecture Review (the "is the structure sound?")

Think like a staff engineer reviewing a design doc.

**Run through each:**

1. **Dependency map** - what new components? how do they connect to existing code?
   - Produce ASCII diagram of data flow
2. **Coupling analysis** - is anything too tightly coupled? Could changes cascade?
3. **Edge cases** - what breaks under 10x load? nil/empty/error paths? race conditions?
4. **State management** - where does state live? can it get stale? consistency model?
5. **Security surface** - new attack vectors? auth boundaries? input validation?
6. **Performance** - N+1 queries? memory pressure? caching opportunities?
7. **Error handling** - what fails gracefully? what fails silently? what corrupts data?

**Test plan:** For each new codepath, identify: what type of test covers it? does one exist? gap?
Write test plan as a checklist.

Auto-decide each finding using principles. Log decisions.

### Phase 3: Code Quality Review (the "will this break at 2am?")

Think like a paranoid staff engineer doing a pre-landing review.

**Focus on production-breaking issues that pass CI:**

1. **Race conditions** - concurrent access to shared state without synchronization
2. **Trust boundaries** - LLM output used without validation? user input unescaped?
3. **Side effects in conditionals** - if branches that mutate state but might not execute
4. **Resource leaks** - unclosed connections, unreleased locks, orphaned processes
5. **Silent failures** - caught exceptions that swallow errors without logging
6. **DRY violations** - same logic in 2+ places that will drift
7. **Missing rollback** - multi-step operations that can leave partial state on failure

For each finding:
- **AUTO-FIX** if mechanical (missing error handling, obvious DRY violation, resource leak)
- **ASK** if taste (architecture choice, naming convention, abstraction level)

### Phase 4: Final Gate

**STOP and present to the user:**

```
## /autoplan Review Complete

### Summary
[1-3 sentences on what was reviewed]

### Decisions: [N] total ([M] auto-decided, [K] taste decisions for you)

### Your Choices
[For each taste decision:]
**Choice [N]: [title]** (from [phase])
Recommendation: [X] because [principle].
Alternative: [Y] - [tradeoff]

### Auto-Decided: [M] decisions (see audit trail below)

### Review Scores
- Product: [summary]
- Architecture: [summary]
- Code Quality: [summary]

### Decision Audit Trail
| # | Phase | Decision | Principle | Rationale |
|---|-------|----------|-----------|-----------|
```

**Options:**
- A) Approve as-is - proceed to implementation
- B) Override specific taste decisions
- C) Ask about a specific decision
- D) Plan needs revision - specify what
- E) Reject - start over

## Important Rules

1. **Full depth, not summaries.** Each review section requires actually reading the code/plan, not summarizing from memory. "No issues found" is valid only after stating what you examined
2. **Log every auto-decision.** No silent choices. Every decision gets an audit trail row
3. **Sequential order.** Product → Architecture → Code. Each builds on the last
4. **Premises are the one gate.** Only mandatory human input
5. **Never abort.** Surface all taste decisions, never redirect to interactive review
6. **Artifacts are deliverables.** Test plan, dependency diagram, audit trail - must exist when done
7. **3 attempts max.** If Phase 4 option D chosen, max 3 revision cycles
