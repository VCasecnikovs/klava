---
user_invocable: true
name: migration
description: Guide for migrating Claude Code settings to a new machine. Use when user mentions new machine, backup settings, restore, or move to new Mac
triggers:
  - migration
  - migrate
  - перемещение
  - переезд
  - новый компьютер
  - new pc
---

# Claude Code Migration Guide

When user asks about migrating Claude Code settings to a new machine, provide this guide.

## What to Copy

### 1. Main Claude Config (REQUIRED)

```
~/.claude/
├── settings.json          # MCP servers, permissions, global settings
├── settings.local.json    # Local overrides (may contain secrets)
├── CLAUDE.md              # Global instructions, memory
└── skills/                # Custom skills
```

**Command:**
```bash
# On OLD machine - create archive
tar -czvf claude-config.tar.gz -C ~ .claude

# On NEW machine - extract
tar -xzvf claude-config.tar.gz -C ~
```

### 2. Project-specific Configs (if any)

Check your projects for:
```
project-folder/
├── .claude/
│   └── settings.json      # Project-specific settings
└── CLAUDE.md              # Project instructions
```

### 3. Related Tool Configs

**ClickHouse CLI** (if used):
```
~/.clickhouse-client/
├── config.xml             # Default config
├── prod.xml               # Named configs (examples)
└── staging.xml
```

**Shell aliases** (check for claude-related):
```bash
grep -E "(ch-prod|ch-staging|claude)" ~/.zshrc ~/.bashrc 2>/dev/null
```

### 4. MCP Server Dependencies

Check `settings.json` for MCP servers and install their dependencies:
- Python packages: `pip install <package>`
- Node packages: `npm install -g <package>`
- Local scripts: copy from paths in settings.json

## Migration Checklist

1. [ ] Copy `~/.claude/` folder
2. [ ] Copy project `.claude/` folders and `CLAUDE.md` files
3. [ ] Copy `~/.clickhouse-client/` (if exists)
4. [ ] Copy shell aliases from `.zshrc`/`.bashrc`
5. [ ] Install Claude Code: `npm install -g @anthropic-ai/claude-code`
6. [ ] Install MCP server dependencies
7. [ ] Re-authenticate: `claude auth`
8. [ ] Test: `claude` in terminal

## Secrets to Re-configure

These are NOT in config files - need manual setup on new machine:
- API keys (Anthropic, OpenAI, etc.)
- Database credentials (may be in MCP configs)
- OAuth tokens (Google, GitHub - re-auth needed)

## Quick One-Liner

```bash
# Export everything on OLD machine
tar -czvf claude-migration.tar.gz -C ~ .claude .clickhouse-client 2>/dev/null

# Import on NEW machine
tar -xzvf claude-migration.tar.gz -C ~
npm install -g @anthropic-ai/claude-code
claude auth
```
