---
user_invocable: true
name: research-optimize
description: Evidence-based personal optimization framework. Use when user wants to optimize a metric (health, wealth, attractiveness, authority, productivity, etc.) using academic research. Decomposes abstract goals into researchable variables, gathers peer-reviewed evidence with effect sizes, calibrates to user's baseline, and produces ranked interventions by expected value.
---

# Research Optimize

Evidence-based framework for personal/business optimization using academic research.

## Workflow

### Phase 1: Context & Decomposition

**Step 1.1: Gather Context**

Use AskUserQuestion to collect critical info for calibration:

**Context Questions (CRITICAL - ask via options):**
- What contexts matter most for this metric? (e.g., investors, team, clients, public, partners)
- What specific situations trigger the need for this metric? (e.g., pitches, negotiations, team meetings)
- Who are you typically interacting with? (age, seniority, culture)

**Self-Assessment:**
- What do you perceive as your current strengths related to this metric?
- What do you perceive as your weaknesses/bottlenecks?
- Any physical factors relevant? (height, voice, appearance, age relative to peers)

**Sub-topics:**
- Any specific sub-topics you want to explore?
- Any you want to exclude?

Also check memory/conversation for existing user context.

**IMPORTANT: Check Obsidian vault for existing research:**
```bash
Grep -i "[topic]" ~/Documents/MyBrain/
```
Previous research may already exist - merge, don't duplicate.

**Step 1.2: Propose Decomposition**

Break down the target metric into 3-5 researchable sub-components.

**CRITICAL: Use the Skills-Signals-Perceptions Framework**

When decomposing ANY human optimization metric, ensure coverage across THREE dimensions:

| Dimension | What it covers | Example sub-components |
|-----------|----------------|------------------------|
| **Skills** | Behaviors, abilities, trainable competencies | Communication tactics, EQ, difficult conversations, strategic thinking |
| **Signals** | External markers, symbols, associations | Network/prestige, authority symbols, attire, status markers, credentials |
| **Perceptions** | How others process/judge you | First impressions, voice/physical presence, age bias, framing effects |

**Why this matters**: Focusing only on skills misses high-effect-size factors like:
- Network associations (r = .90)
- Authority symbols (d = 1.19)
- Speaking time (r = .82-.93)

These are SIGNALS and PERCEPTIONS, not skills - but often have HIGHER effect sizes.

For each sub-component evaluate:
- **Researchability**: Is there academic literature? (strong/moderate/limited)
- **Research question**: How would academics phrase this?
- **Outcome contribution**: What % of total outcome does this drive?
- **Dimension**: Skills / Signals / Perceptions

**Step 1.3: Confirm with User**

Present proposed sub-components and ask:
- "Есть ли ещё топики, которые стоит исследовать?"
- "Какие-то из этих топиков неактуальны для тебя?"
- Allow user to add/remove/modify sub-components

Output format:
```
## Decomposition: [METRIC]
**User context**: [key details affecting research]

| Sub-component | Researchability | Research Question | Outcome % |
|---------------|-----------------|-------------------|-----------|
| ... | strong/moderate/limited | "What factors affect X?" | ~N% |

Есть ли ещё топики для исследования? Какие-то из этих неактуальны?
```

After user confirms, proceed to Phase 2.

### Phase 2: Evidence Gathering

**FIRST**: Create output folder:
```
mkdir -p ~/Documents/MyBrain/Research/research-optimize-{topic}-{date}/
```

**THEN**: Launch parallel Task agents (subagent_type: "general-purpose") for each sub-component with strong/moderate researchability.

**Agent prompt template:**

```
Research: [SUB-COMPONENT] for [USER CONTEXT SUMMARY]

Find peer-reviewed studies, meta-analyses, and RCTs showing:

1. CAUSAL FACTORS (ranked by effect size):
- Effect size with 95% CI
- Evidence type: RCT / natural experiment / IV / twin study / longitudinal
- Sample size and study duration
- Replication status
- Population studied (check match to user's situation)

2. BASE RATES & DISTRIBUTIONS:
- Median outcome, not mean
- Percentile distribution (25th, 50th, 75th, 90th)
- "What % of people who try X achieve Y" - not just "X can lead to Y"

3. WHAT DOESN'T WORK:
- Debunked interventions with citations
- Survivorship bias examples
- Correlational findings that don't survive controls

4. EVIDENCE GAPS:
- "No evidence" vs "evidence of no effect" distinction
- Where findings are extrapolated vs directly applicable

Output as ranked table:
| Factor | Effect Size (95% CI) | Evidence Quality | Sample Size | Citation |
```

**WebSearch strategy for agents:**
- Search: "[topic] meta-analysis", "[topic] RCT", "[topic] systematic review"
- Domains: scholar.google.com, pubmed.ncbi.nlm.nih.gov, cochranelibrary.com
- Prioritize: Cochrane reviews, JAMA, Lancet, Nature, Science, domain-specific top journals

**AFTER all agents complete**: MUST save combined results to evidence.md using Write tool:
`~/Documents/MyBrain/Research/research-optimize-{topic}-{date}/evidence.md`

**Required format**:
```markdown
# Evidence: [METRIC]
Date: [DATE]
User context: [BRIEF SUMMARY]

## Sub-component 1: [NAME]

### Causal Factors (Ranked)
| Factor | Effect Size | CI | Evidence | Sample | Citation |

### Base Rates
[Distribution data]

### What Doesn't Work
[Debunked interventions]

### Evidence Gaps
[Limitations]

## Sub-component 2: [NAME]
...
```

### Phase 3: Personal Calibration

**CRITICAL: After finding evidence, calibrate to user's specific baseline.**

For each TOP 5-10 factors by effect size, determine user's current state:

**Step 3.1: Present Top Factors**
Show user the top factors ranked by effect size:
```
| Rank | Factor | Effect Size | Your Baseline Matters Because |
|------|--------|-------------|------------------------------|
| 1 | [Factor] | r = .XX | [Why baseline changes ROI] |
```

**Step 3.2: Ask Baseline Questions (via AskUserQuestion)**

For each high-effect factor, ask:
- Current level (1-10 or specific metric if measurable)
- Distance to target (how much room for improvement?)
- Feasibility (any blockers to improving this?)

Example:
```
To rank interventions for YOUR situation, I need your baseline on top factors:

1. Network/Prestige Associations (r = .90):
   - Current network quality: [weak/moderate/strong/excellent]
   - Access to known names for advisory: [none/some/many]

2. Voice Pitch (ρ = -.51):
   - Self-perceived pitch: [high/average/low]
   - Ever measured Hz?
```

**Why this matters**:
- If baseline is already high → factor has LOW marginal ROI for this user
- If baseline is low + effect size high → factor is TOP priority
- Same effect size can mean different ROI based on user's starting point

**Step 3.3: Calculate Marginal ROI**

Rank interventions by: Effect Size × Room for Improvement × Feasibility

Put highest-baseline factors in TIER 4 (Already Have), not TIER 1.

### Phase 4: Intervention Ranking (ROI Tiers Format)

Analyze evidence + user profile to produce ROI-tiered actions.

**Ranking criteria:**
- **ROI** = Effect size / (Cost + Time + Effort)
- Convert effect sizes to approximate % improvement for readability
- Flag evidence quality: Causal (RCT/experimental) vs Correlational vs Survey
- Identify bottlenecks (must-do before other interventions work)

**Output format:**

```markdown
# ROI: [METRIC]
**Профиль**: [USER BASELINE SUMMARY]

---

## TIER 1: КРИТИЧЕСКИЙ ROI (Must-do, убирает bottleneck)

| Фактор | Твой baseline | Target | Effect | Стоимость | Время | Evidence |
|--------|---------------|--------|--------|-----------|-------|----------|
| **[Factor]** | [current] | [target] | **+X-Y%** (effect size) | $X-Yk | N мес | **Causal/Correlational**: [source] |

**Почему Tier 1**: [Why this is a bottleneck that blocks other gains]

---

## TIER 2: ВЫСОКИЙ ROI (Differentiation)

| Фактор | Твой baseline | Target | Effect | Стоимость | Время | Evidence |
|--------|---------------|--------|--------|-----------|-------|----------|
| ... |

---

## TIER 3: MODERATE ROI (Optimization)

| Фактор | Твой baseline | Target | Effect | Стоимость | Время | Evidence |
|--------|---------------|--------|--------|-----------|-------|----------|
| ... |

---

## TIER 4: ALREADY HAVE (Don't over-invest)

| Фактор | Твой baseline | Action | Risk |
|--------|---------------|--------|------|
| **[Factor]** | [Already high] | [Maintain/leverage] | **Risk**: [What happens if over-signal] |

---

## STOP DOING (Negative ROI)

| Action | Expected Effect | Evidence |
|--------|-----------------|----------|
| [Bad action] | **-X-Y%** | **[Evidence type]**: [Why it backfires] |

---

## КОНТЕКСТ: [Relevant context switches]

| Если цель | Приоритеты меняются |
|-----------|---------------------|
| [Context A] | [How priorities shift] |
| [Context B] | [How priorities shift] |

---

## TIMELINE

| Период | Фокус | Ожидаемый прогресс |
|--------|-------|-------------------|
| Week 1-4 | Quick wins | [Immediate gains] |
| Month 1-6 | Primary | [Main intervention progress] |
| Month 6-12 | Secondary | [Optimization gains] |

---

## CONFIDENCE LEVELS

| High (Causal) | Medium (Correlational) | Extrapolated |
|---------------|------------------------|--------------|
| [Factor → outcome] | [Factor association] | [Your situation vs research pop] |

---

**Ключевой инсайт**: [One-sentence summary of most important finding for this user]
```

**MUST save** using Write tool to:
`~/Documents/MyBrain/Research/research-optimize-{topic}-{date}/interventions.md`

## Key Principles

1. **Causal > Correlational** - Always flag evidence type
2. **Effect sizes with ranges** - Never vague claims
3. **Base rates matter** - "Works for 5% of people" is different from "can work"
4. **What doesn't work** - As important as what does
5. **Calibrate to user** - Generic advice is worthless for outliers
6. **Save everything** - Research is expensive, results should persist
