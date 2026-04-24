---
name: comms
description: Optimize messages for desired outcome - fix English, kill red flags, simulate recipient
user_invocable: true
auto_trigger: true
trigger_description: Load when the user pastes a message to review, asks to fix/optimize a message, or when drafting outbound comms in heartbeat
---

# Comms - Communication Optimizer

Optimize any message the user sends so the recipient does what they need.

**Not a grammar checker.** This is a 4-layer system that goes from fixing English all the way to simulating what the recipient will think, feel, and do.

**Related:** `english-coach` skill has the passive reference (slang, phrases, Russian mistakes).

---

## The 5 Layers

Run top to bottom. Each layer builds on the previous.

### Layer 0: HUMAN

**Does this look like a person typed it?**

This layer runs LAST as a final pass. It catches the #1 failure mode: output that's technically perfect but obviously AI-written. A message the user couldn't have typed themselves destroys trust.

**Medium-aware formatting:**

| Medium | Formatting rules |
|---|---|
| **TG / Signal / DM** | NO bold headers. NO bullet points. NO markdown. Paragraphs OK but keep them ragged. Dense blocks > structured sections. Occasional sentence fragment OK |
| **Email (casual)** | Light formatting. One bold max. Short paragraphs |
| **Email (formal)** | Clean structure OK. Headers OK. Still no over-formatting |
| **Proposal / doc** | Full formatting allowed |

**AI smell test - kill these patterns:**
- **Special characters nobody types:** `°` `→` `—` (em dash) `•` `≈` - replace with `deg`, `->`, `-`, `-`, `~`. Real people on phones don't have these
- **Perfect parallelism:** if every paragraph starts the same way (e.g. bold keyword + colon), break the pattern. Real writing is asymmetric
- **Zero typos from a non-native speaker:** if the user's English level wouldn't produce this level of polish, it's suspicious. Don't ADD typos, but don't fix every minor roughness either. A slightly awkward phrase that sounds like the user > a perfect phrase that sounds like Claude
- **Compliment sandwiching:** "great work! ... but have you considered... enjoy the trip!" - the praise-suggestion-praise structure is an AI tell. If the user would just say it, just say it
- **Over-praising the recipient:** "strong result, congrats!" on every message = performative. Real peers acknowledge good work briefly or not at all. One "nice" or "cool" is more believable than "impressive, congrats!"
- **Too many specific numbers in compliments:** citing their exact RMSE back to them in the opening line = showing off that you read it. One reference is smart. Three is AI
- **Hedging language clusters:** "could potentially", "it might be worth considering", "perhaps exploring" - real founders say "what about X?" or just state it

**The test:** Would the user's peer think "did they use ChatGPT for this?" If yes, rough it up. The goal is a message that's clearly the user but with better English - not a message that's clearly AI but with their name on it.

**Rule of thumb:** Fix errors that make the user look bad (grammar mistakes, wrong words). Keep roughness that makes the user look real (dense paragraphs, missing transitions, casual structure).

### Layer 1: NATURAL

Does it sound like a native speaker wrote it?

- Fix grammar, articles, prepositions
- Match register: **formal** (emails, proposals, enterprise) vs **casual** (DMs, Twitter, founder chats)
- Kill known Russian patterns (CLAUDE.md Top 5 errors):
  - "we are having" → "we have"
  - "I do believe" → delete or "I think"
  - "right now" overuse → cut it
  - "I were" → "I was"
  - "would love to" x5 → rotate alternatives
- Reference: `english-coach` skill for vocabulary and phrase library

### Layer 2: CLEAR

Am I saying what I mean? Would a native speaker understand instantly?

- One idea per sentence. Max 12-15 words
- Patch vocabulary gaps (when the user uses a sentence to describe what one word covers)
- Cut filler: "basically", "actually", "in terms of", "the thing is that"
- Lead with the point, not the context
- Kill nested clauses (Russian sentence structure leaking through)
- **BUT for casual mediums (TG/DM):** don't over-split. Dense paragraphs are normal in chat. A wall of text is more human than a perfectly structured outline

### Layer 3: SAFE

Would anything in this message hurt the user's position?

Scan for:
- **Weakness signals** - "unfortunately", "we don't have yet", "I'm not sure", unnecessary hedging, apologizing for nothing
- **Oversharing** - revealing pricing to wrong audience, internal struggles, team size, technical limitations, deal details with other clients
- **Desperation** - "I would be very grateful", "whenever works for you", too many exclamation marks, over-eagerness
- **Legal risk** - promises of exclusivity, guarantees, IP claims without basis
- **Status drops** - anything that makes the user look junior, small, or needy
- **Deal breakers** - mentioning competitors by name, admitting data gaps, price anchoring too low, revealing urgency
- **Confidentiality** - client names, revenue numbers, internal metrics that shouldn't be shared (check Obsidian Products `access:` field)

**Don't just remove - reframe.** Turn weaknesses into neutral or positive statements:
- ❌ "Unfortunately we don't have video data yet" → ✅ "Video is on our roadmap for Q2"
- ❌ "We're a small team" → ✅ "We move fast - small team, direct access to founders"
- ❌ "I'm not sure about the pricing" → ✅ "Let me get back to you with exact numbers by Friday"

### Layer 4: EFFECTIVE

What will the recipient DO after reading this?

This is the most important layer. The message exists to trigger an action.

**Process:**
1. **Identify recipient** - from context, or ask the user
2. **Pull context** - Obsidian People note, deal note, Organization note, past conversation
3. **Ask the user** (if not obvious): "What do you want them to DO?" - reply, schedule call, approve, sign, intro, buy, share info
4. **Model the recipient:**
   - What's their role? (decision-maker vs evaluator vs connector)
   - What do THEY want? (their incentives, pain points, KPIs)
   - What's their communication style? (fast/slow, formal/casual, detail-oriented/big-picture)
   - Where are we in the relationship? (cold → warm → hot → closing)
   - What's blocking them from doing what we want?
5. **Simulate reaction:** Given this person reads this message → what do they think? Feel? Do?
6. **Compare** simulated action vs desired action. If mismatch → rewrite
7. **Show simulation** to the user with confidence level

**Common recipient archetypes:**

| Type | Wants | What works | What kills it |
|---|---|---|---|
| Enterprise buyer | Risk reduction, ROI, compliance | Case studies, timelines, data | Hype, unproven claims |
| VC / investor | Traction, team, market | Numbers, confidence, vision | Desperation, vague metrics |
| Technical evaluator | Specs, benchmarks, integration | Detail, honesty about limits | Marketing speak |
| Founder / peer | Speed, mutual value | Directness, shared context | Formality, long emails |
| Connector | Easy ask, clear value | Brief context, specific request | Long background stories |
| Researcher | Methodology, data quality | Technical depth, reproducibility | Sales language |
| Government / intel | Capabilities, security, compliance | Formal proposals, references | Casual tone, overselling |

---

## How to Use

### Manual: `/comms`

The user pastes a message and says who it's for + what they want them to do.

**Output format:**

```
📝 ORIGINAL
[Original text]

🔄 REWRITE
[Optimized version]

📊 WHAT CHANGED
L0 Human: [AI patterns killed / roughness preserved]
L1 Natural: [fixes]
L2 Clear: [simplifications]
L3 Safe: [red flags killed]
L4 Effective: [strategic changes]

🧠 RECIPIENT SIMULATION
They read this and think: [...]
They feel: [...]
They do: [...]
Match with desired outcome: [✅ high / ⚠️ medium / ❌ low]

💡 ALTERNATIVES (if match < high)
Option A: [different angle]
Option B: [different angle]
```

### Auto-trigger: during heartbeat / message drafting

When drafting replies for the user:
- L1-L3 run silently (natural + clear + safe)
- L4 runs when recipient is known and goal is clear
- Flag L3 issues explicitly - never let a red flag through

### Practice mode

When the user writes to practice:
- Run all 4 layers
- Show original → rewrite with explanations per layer
- Rate naturalness 1-5
- Highlight which Top 5 patterns appeared
- Suggest one new phrase from english-coach reference that fits the context

---

## Key Principles

1. **Desired outcome drives everything.** Grammar is layer 1. The real value is layer 4.
2. **Every message has a job.** If a message doesn't move toward a goal, ask why it exists.
3. **Confidence > correctness.** A slightly wrong but confident message beats a perfectly correct but weak one.
4. **Short > long.** Busy people read short messages. Write less, say more.
5. **The recipient is an NPC.** Model their behavior. Optimize your input to get the output you want.
6. **Context is king.** A message to a cold lead vs a warm contact vs a closing deal = completely different strategies. Always pull context first.
7. **Human > perfect.** A message that sounds like the user wrote it beats a message that sounds like AI wrote it. Fix errors, keep voice. The rewrite should be something the user COULD have written - not something only an AI would produce.
8. **Minimal intervention for casual.** For TG/DM/Signal: fix the Top 5 errors, kill L3 red flags, leave the rest alone. Don't restructure, don't add headers, don't polish. The user's rough draft + 2-3 fixes > full AI rewrite.
