---
name: config
description: Read and modify Claude Code settings mid-conversation
user_invocable: true
---

# Config - Claude Code Settings Manager

Read and modify Claude Code configuration without leaving the conversation.

## Config File Hierarchy

Claude Code merges settings from multiple files (later overrides earlier):

| File | Scope | Agent access |
|------|-------|--------------|
| `~/.claude/settings.json` | Global user | WRITE |
| `~/.claude/settings.local.json` | Global local (gitignored) | WRITE |
| `<project>/.claude/settings.json` | Project shared | READ-ONLY by default |
| `<project>/.claude/settings.local.json` | Project local (gitignored) | WRITE |

**IMPORTANT:** Treat project `settings.json` as READ-ONLY unless the user has explicitly granted write access. It's version-controlled and changes affect everyone on the project. Suggest edits but don't apply.

## Usage

- `/config` - show current effective settings
- `/config model` - show/change model
- `/config model sonnet` - switch to sonnet
- `/config permissions` - show permission rules
- `/config compact` - toggle autoCompactEnabled
- `/config memory` - toggle autoMemoryEnabled
- `/config verbose` - toggle verbose mode
- `/config env` - show environment variables
- `/config <key> <value>` - set arbitrary key

## Supported Settings

From the Claude Code schema:

| Key | Type | Description |
|-----|------|-------------|
| `model` | string | Model to use (e.g. "opus", "sonnet", "opus[1m]") |
| `autoCompactEnabled` | bool | Auto-compact when context gets large |
| `autoMemoryEnabled` | bool | Auto-update CLAUDE.md memory |
| `verbose` | bool | Show verbose tool output |
| `cleanupPeriodDays` | number | Days before session cleanup |
| `env` | object | Environment variables passed to tools |
| `permissions.allow` | array | Auto-allowed tool patterns |
| `permissions.deny` | array | Denied tool patterns |

## Instructions

### Show current settings

```bash
echo "=== Global User ===" && cat ~/.claude/settings.json 2>/dev/null || echo "(empty)"
echo "=== Global Local ===" && cat ~/.claude/settings.local.json 2>/dev/null || echo "(empty)"
echo "=== Project Shared ===" && cat ~/Documents/GitHub/claude/.claude/settings.json 2>/dev/null || echo "(empty)"
echo "=== Project Local ===" && cat ~/Documents/GitHub/claude/.claude/settings.local.json 2>/dev/null || echo "(empty)"
```

Summarize the effective merged config to the user. Highlight conflicts between layers.

### Change model

Write to `~/.claude/settings.json` (global user level):

```bash
python3 -c "
import json
path = '$HOME/.claude/settings.json'
try:
    with open(path) as f: cfg = json.load(f)
except: cfg = {}
cfg['model'] = 'NEW_MODEL_HERE'
with open(path, 'w') as f: json.dump(cfg, f, indent=2)
print(f'Model set to: {cfg[\"model\"]}')
"
```

Model shortcuts: `opus` = claude-opus-4-6, `sonnet` = claude-sonnet-4-6. Append `[1m]` for extended thinking.

### Toggle boolean settings

Same pattern - read JSON, flip the boolean, write back. Target `~/.claude/settings.json` for user-level changes.

### Modify permissions

Permissions live in the `permissions.allow` and `permissions.deny` arrays. When adding a new permission:
1. Check if it already exists in any layer
2. Add to `~/.claude/settings.local.json` (local, not committed)
3. Never remove existing permissions without explicit request

### Safety

- Before any write: show the user what will change (old value -> new value)
- For project `settings.json`: only suggest the edit, tell user to apply manually
- After changing model: warn that it takes effect on next message (current session keeps current model until restart)
- After changing permissions: they take effect immediately for new tool calls
