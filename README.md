# Klava

A personal AI assistant for founders, BD, sales, and CEOs - built on top of [Claude Code](https://claude.com/claude-code).


If you're a developer, Claude Code is already a superpower. If your work is mostly deals, meetings, research, and operations - the CLI alone doesn't cut it. Klava is what I built for myself over 9 months to make Claude actually useful for non-code work: a dashboard, a task queue, a knowledge base, proactive jobs, and 40+ skills for real workflows.

> Full story and design rationale: [blog post](#todo-link-to-blog) _(ToDo: add link)_.

## Install

Two steps, plus a short setup wizard.

```bash
git clone https://github.com/VCasecnikovs/klava.git
cd klava
./setup.sh
```

`setup.sh` handles submodules, Python venv, Node build for the dashboard, LaunchAgents, config templates, Claude Code authentication, and opens the dashboard at `http://localhost:18788/dashboard`. On first run it walks you through a short wizard: your name, timezone, Telegram bot token (optional), Obsidian vault path.

That's it. Cron jobs and the Telegram bot stay off until you explicitly enable them from the Settings tab.

## What you get

### A dashboard with chat, tasks, and proactive surfaces

The primary interface. Left side - chat with Klava. Right side - supporting tabs: Deck, Tasks, Health, Views, Skills.


Markdown, tables, and SVG render natively. You can quote any part of an agent message like in WhatsApp.

### A Deck of cards for tasks

Every task - proposal, action, result - shows up as a card. One at a time. Done, Skip, Snooze, or open a Session to work on it with Klava.


When Klava finishes a delegated task, she drops a Result card back on the Deck.


### Views for interactive reports

Some things don't fit in a chat - design prototypes, long research, comparison matrices. Klava generates them as interactive HTML pages you can open as views.


### Vadimgest for reacting to the world

Vadimgest is a separate submodule that collects updates from 19 sources (messages, emails, calendar, browser history, etc.) and turns them into LLM-readable feeds. A heartbeat job reads it every 30 minutes and decides what to do: create tasks, update the knowledge base, or act without you.


## How it's built

| Component | Purpose |
|-----------|---------|
| Webhook server (`gateway/webhook-server.py`) | Dashboard, API, real-time chat via WebSocket |
| CRON scheduler (`gateway/cron-scheduler.py`) | Heartbeat, reflection, health checks |
| Telegram bot (`gateway/tg-bot.py`) | Proactive notifications and mobile access |
| Watchdog (`gateway/cron-watchdog.py`) | Monitors daemons, restarts stale processes |
| Klava consumer (`tasks/consumer.py`) | Executes delegated tasks from the Klava queue |

Scheduled jobs:

- **Heartbeat** (every 30 min) - reads Vadimgest, triages new data, creates tasks, updates knowledge base.
- **Reflection** (nightly) - cleans up Inbox, cross-links entities, dedupes tasks, detects silence on deals.
- **Klava consumer** (every 5 min) - picks one task off the async queue, runs it, writes a Result card back to the Deck.

## Skills

Skills are markdown files in `.claude/skills/*/SKILL.md` that teach Klava specific workflows - how to draft a cold email, how to record a deal, how to generate a pitch deck. Claude can create and edit its own skills.

40+ shipped skills including: `autoplan`, `autoresearch`, `cold-email`, `comms`, `heartbeat`, `reflection`, `meeting-processing`, `language-coach`, `voice`, `html-view`, `pdf`, `xlsx`, `docx`, `pptx`, `codex-cli`, `gemini-cli`, `mcp-builder`, `skill-creator`.

Create your own:

```bash
mkdir .claude/skills/my-skill
cat > .claude/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: What this skill does in one line
user_invocable: true
---

# My Skill

Instructions for Claude go here...
EOF
```

Skills hot-reload - no restart needed. Use `/my-skill` in chat to invoke.

### Personal vs shipped skills

For skills with private data (API keys, personal workflows), use `.claude/skills/personal/` - it's gitignored. Link them in with:

```bash
./scripts/link-personal-skills.sh
```

## Configuration

### `gateway/config.yaml`

Central config. Edit via the Settings tab or directly. Key sections: `identity`, `you`, `telegram`, `models`, `cron`, `paths`.

### `cron/jobs.json`

Scheduled job definitions. Each job has `schedule` (cron or interval), `execution` (Claude session or bash), `retry`, `catch_up`. See `cron/jobs.json.example`.

### Memory tiers

1. **Raw data** - Vadimgest (append-only JSONL, 19 sources)
2. **Structured knowledge** - Obsidian vault (People, Organizations, Deals, Topics) + skills
3. **CLAUDE.md + MEMORY.md** - high-frequency system instructions loaded every session

`CLAUDE.md` is tracked and generic. `MEMORY.md` is gitignored and personal.

## Prerequisites

- macOS (LaunchAgents for daemon management - Linux support via systemd is welcome as a PR)
- Python 3.11+
- Node.js 18+ (dashboard build)
- [Claude Code](https://claude.com/claude-code) installed and authenticated
- Obsidian vault (optional, knowledge graph)
- Telegram bot token (optional, proactive notifications)

## Directory structure

```
.claude/
  CLAUDE.md              # Generic system instructions (tracked)
  MEMORY.md              # Personal overlay (gitignored)
  skills/                # Generic skills (tracked)
    personal/            # Personal skills (gitignored)
  pipelines/             # Workflow state machines

gateway/
  webhook-server.py      # Dashboard + API
  cron-scheduler.py      # Job scheduler
  tg-bot.py              # Telegram bot
  cron-watchdog.py       # Health monitor
  lib/                   # Shared libraries
  hooks/                 # Event hooks

tools/
  dashboard/react-app/   # React + TypeScript + Vite

cron/
  jobs.json              # Job definitions

tasks/
  queue.py               # Klava task queue
  consumer.py            # Queue executor

vadimgest/               # Data-lake submodule (optional, private)
```

## Contributing

Started as a personal project, now being open-sourced incrementally. PRs welcome on:

- Linux support (systemd instead of LaunchAgents)
- Alternative notification channels (Discord, Slack, email)
- New generic skills
- Dashboard improvements
- Documentation

## License

[Apache License 2.0](LICENSE)
