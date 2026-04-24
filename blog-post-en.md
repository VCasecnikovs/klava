# How I built a personal assistant for a CEO on top of Claude Code

ToDo Beautiful UI photo

If you're a developer, congratulations — you can now barely write code. Open a project, spin up 5 Claude Code sessions, and you're flying.

If you're a founder, BD lead, salesperson, or CEO — you're in trouble. There's no decent tool for you. You're stuck chatting with a model that forgets who you are every session, doing all the dirty work yourself — manually copy-pasting text from the chat into emails and back again.

Not finding anything that worked, I spent the last 9 months slowly sanding down Claude Code's rough edges until it became a useful tool for me specifically.

It's honestly surprising that nothing decent has appeared in 9 months in the most hyped industry of our generation.

So I decided to write this post, share everything I ran into, and open-source my assistant Klava — the one I use every day for sales, operations, and building demos.

ToDo add link to Klava and instructions how to install

## Context is all you need — telling Claude what you actually do

If you use AI interfaces regularly, you know the pattern: the more the model knows about you, your company, your tasks, and your tools, the better the output. If it knows nothing, welcome to the slop universe of identical AI-generated nothing.

ToDo Picture — a document in our style showing something specific we sell, vs the default AI-purple abstract document full of generic words that say nothing concrete

Giving context to a coding assistant is straightforward. Claude launches inside a project folder. All coding projects follow familiar patterns. Claude can study the structure, style, and business logic — and in the right hands, produce decent results within that system.

But when your work involves business development, sales, finance, or anything more complex than a single repository — Claude Code breaks as a tool. Facts get pulled from thin air, terrible assumptions get made. Instead of using your existing formats and styles, everything comes out in default AI-purple. And that's before you spend 10 minutes writing a context poem before each task, or 30 minutes correcting whatever Claude decided to do on its own.

> The more the model knows about you and your business, the better it handles your work.

Our goal is to push as much information as possible into the model's context.

I'd group that information into three types:

- System information
- State
- Capabilities

**System information** explains to Klava who she is and how she should operate. The most important aspects:

1. **Model identity** — the model needs to understand it's an autonomous agent that's also an assistant, and that it should actually solve problems. It also needs to be calibrated: not too serious, not too playful, or you'll go insane.
2. **Programmer lobotomy** — Claude Code comes with powerful tools out of the box, but every example points at code. In CLAUDE.md you need to explicitly state that those same tools apply to non-code work, with examples.
3. **Environment awareness** — the model should behave differently depending on context. In a live session with a human, it should ask when uncertain. Running autonomously on a complex task, it should be allowed to make more decisions without interrupting.
4. **Autonomy boundaries** — the biggest fear with AI agents is that the model sells your car because you joked in chat that you're tired of driving it. By default, Klava can only read information and create tasks and drafts. As you see it handle something well, you can loosen boundaries for that specific thing.

---

**State** should describe, in as much detail as possible, everything happening in your life and everything you're responsible for — from names of colleagues and social accounts to the specifics of your ClickHouse setup or your acoustic sensing patents. I recommend keeping this in `memory.md`, separate from the system prompt.

---

**Capabilities** — out of the box, Claude is quite limited. It can't write a Gmail, create a calendar event, open a browser, or check Twitter.

Fortunately, CLI tools exist for all of this. You just need to tell Claude they exist and how to call them.

---

Context windows aren't infinite, so you can't dump everything in there.

I solved this two ways:

- Move all interaction protocols into **skills**
- Move large knowledge bases into an **Obsidian knowledge base**

> Rule of thumb: if information is needed in fewer than 20% of sessions, move it to a skill.

I currently have 87+ skills. Some examples:

- **System skills** — keep Klava running correctly (how to handle tasks, how to format results, etc.)
- **External tool skills** — Gmail, Google Calendar, Twitter, WhatsApp, DOCX, PDF, PPTX, Reddit, Signal, Telegram, downloading paywalled papers, and more
- **Personal skills** — a deal-writing skill for my company, a skill that writes in my voice
- **Power skills**
  - `comms` — optimizes a message for maximum impact
  - `autoresearch` — Karpathy's algorithm for continuous autonomous optimization of any measurable metric
- **Utility skills** — you call these yourself
  - `finder` — opens the folder Klava is currently working in
  - `typora` — opens a `.md` file in Typora
  - `copy` — copies to clipboard
  - `web` — opens a URL in the browser

---

My entire knowledge base lives in Obsidian — plain `.md` files organized in folders.

- **Life** — things about me and my life (business structures, blockers, sleep, visas, personal stuff)
- **Organizations & People** — a note per person and organization I interact with
- **Vox Lab** — my company folder: deals, deliverables, case studies, legal, research, products, and more

---

Once you've split everything into data and skills, a new problem appears: the model doesn't know where anything is. You need to update your system prompt to map out where things live.

> I recommend writing most documents in two parts:
>
> 1. Current state of the entity
> 2. A chronological log of all interactions and what came of them

## Vadimgest — teaching Claude to react to the outside world

We now have a system that knows what I do and can roughly handle my problems. But every day something new happens — a new person, a deal update, a trip, whatever. Manually updating the knowledge base for all of this is a form of self-destruction.

What you want is a system that reads all incoming updates and, based on them, creates tasks for you, researches new people, updates deal statuses, and handles whatever it can on its own.

Vadimgest continuously collects new data from all the sources relevant to me and turns them into LLM-readable updates. Currently 19 sources (more coming).

> Vadimgest runs independently, so you can plug it into your own system too.

ToDo Vadimgest screenshot

Every 30 minutes, a job called **heartbeat** runs. It looks at what's new in Vadimgest and decides what to do with it — creating tasks in Google Tasks, updating the knowledge base, or handling things the model can resolve without my input.

Inside heartbeat, Klava answers 4 questions:

- What do I need to do?
- How can Klava help resolve these?
- What new facts did we learn about the world?
- What new dynamics or patterns are emerging? For example: I've started working more at night, or a friend is responding with noticeably less energy than before.

Klava then creates tasks and updates the knowledge base.

> My system runs every 30 minutes, not on every new message. Heartbeat also never continues a previous heartbeat session. This keeps token costs low.

As data keeps flowing in, things get messy — so at night, **reflection** runs. Reflection cleans up whatever heartbeat left rough: duplicate tasks, redundant knowledge base entries, stale notes.

> It's critical to track not just the current message, but the historical pattern of interaction with people. The same words mean completely different things depending on whether someone is in good spirits or in clinical depression.

## UI for Human, CLI for Klava — making it usable

We now have a system that knows enough about you, your work, and your processes to actually help. It updates continuously, creates tasks from what happened during your day, and writes useful information into the knowledge base.

ToDo meme — people fighting with plastic swords / "why aren't you working" / Claude Code is running

But now you're stuck with the Claude Code interface. You kick off a task and wait 10 minutes. You open several terminal windows, prompt Claude to think longer, try to context-switch between them fast enough to stay useful. You get walls of text in the terminal that are impossible to parse. No tables, no SVG diagrams, no interactive views.

CLI is just not a good interface for managing complex work.

To fix this, I built a custom UI dashboard for interacting with Klava.

On the left side you have the chat. On the right side, helper tabs.

ToDo Dashboard layout photo

Now you have native session tabs — you can see what each session is working on, and it'll notify you when it needs your attention.

When you work on tasks in batches, you get answers to multiple things at once. The chat supports quoting any part of an agent message — like WhatsApp or Telegram.

ToDo Quote photo

Visualization is also solved. The chat renders markdown text and tables natively.

When you need to understand a complex structure, Klava can draw you an SVG.

ToDo SVG + Markdown

Sometimes you need Klava to research a new industry and produce a report, or prototype a new design. Making that readable inside a chat thread is nearly impossible. So I added **Views** — interactive HTML pages Klava can generate for you, similar to Artifacts in Claude Desktop.

ToDo View example

---

The tabs hold a lot of supporting interfaces:

- **Lifeline, Heartbeat, Health** — monitor the system and let you quickly see if something's broken
- **Skills, Files, People** — browse supporting information
- **Views** — find every View Klava has ever generated
- **Settings** — configure the system from the UI

Three tabs deserve separate mention — they're the most important for daily work.

## J.A.R.V.I.S. makes no mistakes — working with Klava and delegating to her

We've built a system that tracks your life, creates tasks, and updates the knowledge base. The last remaining friction: how do you actually work through tasks with Klava, and how do you hand things off to her?

I tested more than 10 task management interfaces and landed on a SuperHuman-like UI as the most effective for real productivity.

ToDo Deck tab photo

Each task is a card. You get one card at a time and decide what to do with it.

For each card you can:

- Mark it done (Done)
- Dismiss it (Reject)
- Come back to it later (Snooze)

But often you'll want to work on it with Klava, or hand it off entirely.

For working together: press **Session**, and a new chat opens with the task's context already loaded.

For delegating: press **Delegate**, and the task goes into Klava's queue. When she finishes, a Result card appears on your Deck.

Or press **Proposal** if you want Klava to draft a plan first and show it to you before executing.

---

Klava tries not to interrupt you and handles as much as she can on her own. She has her own task list that she works through asynchronously.

When she finishes a task, she adds a **Result card**. You can read what was done, mark it done, or send Klava back to finish more — asynchronously or in a supervised session.

ToDo Result card photo

If a task is too complex to execute without your approval, Klava writes a **Proposal** instead — a plan you can approve or reject.

> Every task in Klava is a Google Task. You can create and close them manually in Google Calendar too.

If you want to see everything — tasks for you and tasks for Klava — check the **Tasks** and **Klava** tabs.

## Wrapping up

Klava gave me as many new capabilities as Cursor and Claude Code gave me for programming.

I built this for myself, with no intention of open-sourcing it. So there are rough edges, especially visual ones. I've cleaned up most of it, but PRs are always welcome.

The whole system is open source. I'd love to hear what you build with it.

ToDo add link to Klava

## P.S. Hlopya

Two months ago I realized there's no good app for recording conversations in non-English languages. So I built a local recorder called Hlopya.

Under the hood it runs Nvidia's Parakeet model, fully locally — your call recordings never leave your laptop. The transcription quality is also subjectively better than Granola.

Vadimgest natively supports Hlopya and has a dedicated call processing pipeline.

ToDo link to Hlopya
