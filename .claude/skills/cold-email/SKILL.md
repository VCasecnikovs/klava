---
name: cold-email
description: Write high-converting B2B cold emails and sequences. Use when drafting outreach, prospecting, or cold email campaigns
user_invocable: true
---

# Cold Email Writer

Write data-driven B2B cold emails that actually get replies. Based on analysis of millions of cold emails (Gong, Belkins, Outreach, Mailshake research 2024-2026).

## Triggers

- "напиши холодное письмо", "cold email", "draft outreach"
- "написать письмо для [компания/человек]"
- "email sequence", "follow-up sequence"
- "outreach campaign"

## Input

- **Required:** Target company OR person name OR deal name
- **Optional:** language (EN default), framework preference, specific pain point to address

## Workflow

### Step 1: Gather Context

Before writing a single word, research the prospect:

```bash
# Find deal/person/org in your knowledge base (Obsidian vault path comes from config.yaml)
Glob "**/*{name}*.md" ~/Documents/MyBrain/

# Read everything we have
Read "~/Documents/MyBrain/People/{Person}.md"
Read "~/Documents/MyBrain/Organizations/{Company}.md"
Read "~/Documents/MyBrain/Deals/{Deal}.md"
```

Extract:
- **Person:** role, company, recent activity, what they care about
- **Company:** industry, size, stage, recent events, tech stack
- **Deal:** history, what was discussed, stage, objections, pricing discussed
- **Trigger event:** new hire, expansion, funding, regulatory change, public statement

If no Obsidian context exists - research via web:
```bash
# LinkedIn profile
/linkedin search "{person name}" at "{company}"

# Company news
WebSearch "{company} recent news 2026"
```

### Step 2: Select Framework

Pick framework based on context. Decision tree:

```
Have a trigger event? → TRIGGER-BASED (#6)
Have something valuable to share (report/data)? → SHARING ASSET (#8)
Know their specific pain point? → PAS (#1)
Have a killer case study with numbers? → 3C (#5)
Know a specific achievement to praise? → 3Ps (#4)
Want to show transformation? → BAB (#3)
Have a wow-stat? → AIDA (#2)
Nothing specific, need volume? → GOATED ONE-LINER (#7)
Can create personalized visual? → CUSTOMIZED VISUAL (#9)
ICP is very clear, problem obvious? → STRAIGHT TO BUSINESS (#10)
```

For **data/asset-heavy outreach** (e.g. you're selling access to a dataset, API, or report), default order of preference:
1. **Sharing Asset** - you have real data to show
2. **Trigger-Based** - if there's a recent event
3. **PAS** - if you know their pain
4. **3C** - if you have a relevant case study

### Step 3: Write the Email

#### Hard Rules (non-negotiable)

1. **60-100 words.** 6-8 sentences max. If it doesn't fit on one iPhone screen - cut
2. **No "I/We" opening.** First sentence must be about THEM
3. **No links in first email.** Zero. Kills deliverability
4. **No images, attachments, HTML formatting.** Plain text only
5. **One CTA. One.** Always soft: "Would this be worth exploring?" not "Book a demo"
6. **No filler:** "I hope this finds you well", "My name is X from Y", "I wanted to reach out"
7. **Subject line: lowercase, <5 words, personal or question**
8. **Signature: minimal.** Name + Company. No logos, no links, no phone, no title block

#### Personalization Requirements

Every email MUST have at least ONE of these (in order of impact):
- Reference to their specific recent action/event (best)
- Observation about their company (good)
- Reference to their content/talk/post (good)
- Industry-specific pain point (acceptable)
- Role-specific pain point (minimum)

Generic "Hi {first_name}" with zero personalization = DO NOT SEND.

#### CTA Hierarchy (best → worst)

1. "Would you be open to seeing how this could work for {{company}}?" ← best
2. "Is this something your team is thinking about?"
3. "Happy to send a sample report - no strings. Want me to?"
4. "Worth a quick conversation?"
5. "Mind if I send a 2-min walkthrough?"
6. "Does a 15-min call next Tuesday work?" ← too committal for first touch
7. "Let me know if you're interested." ← never use, lazy

#### Subject Line Formulas (by open rate)

| Formula | Example | Open Rate |
|---------|---------|-----------|
| "hi {{first_name}}" | "hi sarah" | 45% |
| Question | "quick question about {{company}}" | 46% |
| Lowercase + company | "{{company}} + data quality" | 40%+ |
| Trigger reference | "saw the {{event}} announcement" | 38-42% |
| Result-based | "how {{similar}} cut research time 80%" | 35-40% |

Rules: lowercase everything, max 5 words, no emoji, no numbers, no "Partnership opportunity" / "Quick sync" / "Following up"

### Step 4: Write the Sequence

Always write a 4-touch sequence, not just one email:

#### Day 1 - Initial Email
Main email using selected framework. Maximum personalization here.

#### Day 3 - Follow-up #1 (Value Add)
**NOT "just following up."** Add NEW value:
- New data point or insight
- Relevant case study
- Link to article that validates their problem

Template:
```
One more thought on this - [new insight/data point relevant to them].

[1-2 sentences connecting it to their situation].

[Soft re-ask of CTA]
```

#### Day 7 - Follow-up #2 (Social Proof)
Lead with a specific result from a similar company:

Template:
```
Quick update - [similar company] just [achieved specific result] using [our approach].

They [specific detail that resonates with prospect's situation].

Still think this could be relevant for {{company}}?
```

#### Day 14 - Follow-up #3 (Breakup)
The "breakup email" - paradoxically gets highest reply rate:

Template:
```
{{first_name}}, I'll assume the timing isn't right and won't take up more of your inbox.

If [their problem] ever becomes a priority, happy to pick this up.

[Optional: link to free public resource]
```

**Why breakup works:** Loss aversion + pressure removal. Recipients feel free to respond honestly.

### Step 5: Output Format

Present the email + sequence as:

```
## Cold Email: [Company/Person]

**Framework:** [which one]
**Personalization hook:** [what makes this specific to them]
**Trigger:** [event that prompted outreach, if any]

### Email 1 (Day 1)
Subject: [subject line]
---
[email body]
---

### Follow-up 1 (Day 3)
Subject: [subject line]
---
[email body]
---

### Follow-up 2 (Day 7)
Subject: [subject line]
---
[email body]
---

### Follow-up 3 - Breakup (Day 14)
Subject: [subject line]
---
[email body]
---

**Send time:** [Tue-Thu, 7-9 AM recipient timezone]
**Notes:** [any strategic notes, what to watch for]
```

### Step 6: Approval

**ALWAYS present to the user for approval before any sending.**
If asked to batch-create for a campaign, present all as HTML view for review.

## Frameworks Reference

### 1. PAS - Problem → Agitate → Solve
**Structure:** Name their pain → Amplify consequences → Present solution with proof
**Best for:** When you know their specific problem
**Example pain points** (substitute with pains your product actually solves):
- Manual, slow workflows the prospect is running today
- Data blind spots that cost them money or risk
- Compliance or coverage gaps
- Bottlenecks in a process they own

### 2. AIDA - Attention → Interest → Desire → Action
**Structure:** Shocking fact → Connect to them → Show what they get → Soft CTA
**Best for:** When you have a WOW stat

### 3. BAB - Before → After → Bridge
**Structure:** Current painful state → Ideal outcome → How to get there
**Best for:** Selling transformation

### 4. 3Ps - Praise → Picture → Push
**Structure:** Specific compliment → Bigger opportunity → Clear next step
**Best for:** C-level outreach, when they have a public achievement to reference

### 5. 3C (Alex Berman) - Compliment → Case Study → CTA
**Structure:** Super-personal compliment → 1 sentence case study with number → 1 question
**Results:** 10-25% reply rate
**Rules:** 3-5 lines total. Compliment must be SPECIFIC. Case study = 1 sentence + 1 number.

### 6. Trigger-Based / Intent-Based
**Structure:** Reference event → Explain relevance → Offer value
**Best for:** When there's a concrete trigger (new hire, expansion, funding, regulatory event)
**Generic triggers worth monitoring** (adapt to your ICP):
- Prospect hired into a role that owns your use case (e.g. Head of Data, Compliance, Security)
- Regulatory or industry event that makes your category urgent
- Expansion, funding, or M&A activity
- Public statement about a priority that aligns with your product
- Competitor win or loss in their space

### 7. Goated One-Liner
**Structure:** 1 powerful line → 1 context line → "Worth a call?"
**Best for:** Volume outreach without deep personalization

### 8. Sharing Asset
**Structure:** Context → Describe asset → Offer to send free
**Best for:** When you have a report/data/case study to give away
**Tip:** If you sell a data product, create mini-reports scoped to each prospect's industry or market

### 9. Customized Visual
**Structure:** Personalized visual → Key insights → Discussion invite
**Best for:** When you can create an audit/mockup/sample for them
**Tip:** Personalized audits and mockups convert dramatically better than generic collateral

### 10. Straight to Business
**Structure:** What we do → Who we help → Proof → Direct question
**Best for:** Clear ICP, obvious problem

## Credibility Stack

Use these as social proof (choose what's relevant):
- "Our data has been cited in academic research papers"
- "Used by investigative journalists at major publications"
- "Coverage across 180+ corporate jurisdictions"
- "Mapped X entities / discovered Y previously unknown connections" (use real numbers from deals)
- Published article citations
- Case studies with verified metrics (if appropriate to mention)

**Sensitive info rules:**
- NEVER mention specific client names (say "a major AI lab", "a major publication")
- NEVER mention pricing from other deals
- NEVER mention intermediary or referrer names

## C-Level / Enterprise Rules

When targeting VP+ at companies >500 employees:
- **Shorter = better.** Max 5 sentences
- **Outcome > Features.** "Reduce compliance review time by 80%" not "AI-powered entity resolution"
- **6-9 AM send time.** They check email before the day starts
- **Understated tone.** No hype, no exclamation marks, no CAPS
- **Multi-thread:** Also email 2-3 other people in the org (different angles)
- **Enable forwarding:** Add "If this sits with someone else on your team, I'd be grateful for a pointer"
- **Low-commitment CTA:** "Worth exploring?" or "Can I send a 2-min case study?"

## Segment Playbooks

| Segment | Framework | Pain Point | CTA Style |
|---------|-----------|------------|-----------|
| Compliance teams | PAS | Manual screening, false positives, fines | "Would it make sense to show you?" |
| Journalists / researchers | Sharing Asset | Lack of data, opacity | "Happy to send a data summary" |
| Intelligence / Government | Trigger-based | Threat monitoring, geopolitical events | "Is this something your team tracks?" |
| Hedge funds / PE | BAB | Due diligence blind spots | "Worth a quick look?" |
| Law firms | 3C | Asset tracing across jurisdictions | "Would this be relevant?" |
| AI Labs | Sharing Asset | Training data quality, diversity | "Want me to send a sample?" |

## Key Stats Reference

- **Average reply rate:** 5.8% (2024). Top performers: 15-25%
- **Optimal length:** 60-100 words, 6-8 sentences
- **Follow-up lift:** +49% with 1st follow-up, +65% with 2-3
- **Best days:** Tue-Thu. Best time: 7-11 AM. Peak: Wed 9-11 AM
- **Subject line:** Personalized = 46% open vs 35% generic
- **Breakup email:** Often highest reply rate in sequence
- **Plain text > HTML** for deliverability and perceived authenticity

## Anti-Patterns (never do these)

- "I hope this email finds you well"
- "My name is X and I work at Y"
- Starting with "I" or "We"
- Multiple CTAs in one email
- Links in first email
- "Just following up" without new value
- HTML formatting, images, logos
- Subject with CAPS, numbers, emoji, urgency words
- Sending from your primary domain (use aged secondaries instead)
- >50 emails/day from one inbox
- Not validating email addresses before sending

## Infrastructure Checklist (for campaigns)

Before launching any campaign, verify:
- [ ] Secondary domains purchased and aged 30+ days
- [ ] SPF + DKIM + DMARC configured on all sending domains
- [ ] Inboxes warmed up (2-4 weeks, 10-50 emails/day ramp)
- [ ] Email list validated (ZeroBounce/NeverBounce)
- [ ] Sending tool configured (Instantly/Smartlead)
- [ ] Google Postmaster monitoring set up
- [ ] Unsubscribe header included
- [ ] No links in first email of sequence
- [ ] A/B test variants prepared (2-3 subject lines minimum)
- [ ] CRM tracking ready (pipeline from cold email)
