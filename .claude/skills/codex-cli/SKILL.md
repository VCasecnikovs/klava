---
user_invocable: true
name: codex-cli
description: Run tasks via OpenAI Codex CLI. Use for code review, terminal-heavy tasks, or non-interactive scripting with GPT-5.3
---

# Codex CLI

OpenAI Codex CLI - best model for terminal tasks and code review. GPT-5.3 Codex scores 77.3% on Terminal-Bench (vs Claude 65.4%).

**Installed:** `codex` v0.107.0

## When to Use

- **Code review** - `codex exec review` built-in, catches edge cases Claude misses
- **Terminal-heavy tasks** - best model for shell scripting, system admin, CI/CD
- **Non-interactive scripting** - `codex exec` works reliably (unlike gemini -p)
- **Token-efficient tasks** - 2-4x more efficient than Opus on same tasks
- **Literal instruction following** - when you need EXACT execution, no interpretation

## When NOT to Use

- Creative development / greenfield features (Claude better)
- Multi-file refactoring with complex dependencies (Claude better)
- Long-context tasks >200K tokens (Claude has 1M)
- Agent teams / coordinated multi-agent work (Claude only)

## Non-interactive Mode (exec)

```bash
# Simple task
codex exec "Review this file for security issues" -C /path/to/repo

# Full auto (no confirmations)
codex exec --full-auto "Fix the failing tests" -C /path/to/repo

# Specific model
codex exec -m gpt-5.3-codex "Your prompt"

# Output to file
codex exec -o result.txt "Analyze the architecture"

# JSON output (for scripting)
codex exec --json "List all API endpoints" -C /path/to/repo

# With image input
codex exec -i screenshot.png "What's wrong with this UI?"
```

## Code Review (built-in)

```bash
# Review current repo
codex exec review -C /path/to/repo

# Review with specific focus
codex exec review -C /path/to/repo "Focus on security and error handling"
```

## Interactive Mode

```bash
# Start interactive session
codex "Help me refactor the auth module"

# With specific sandbox mode
codex -s workspace-write "Fix the build"

# Resume previous session
codex resume --last
```

## As MCP Server

Codex can serve as MCP server for other tools:

```bash
codex mcp-server  # starts stdio MCP server
codex mcp list    # list configured MCP servers
codex mcp add <name> -- <command>
```

## Sandbox Modes

| Mode | Permissions |
|---|---|
| read-only | Can only read files |
| workspace-write | Can write to workspace dir |
| danger-full-access | Full system access (DANGEROUS) |

## Key Flags

| Flag | What |
|---|---|
| `--full-auto` | No confirmations, sandboxed write |
| `--json` | JSONL event stream to stdout |
| `-o file.txt` | Save last message to file |
| `-C dir` | Set working directory |
| `-m model` | Override model |
| `--ephemeral` | Don't persist session |

## Key Limitations

- xhigh effort = ~2 min time to first token (slow start)
- Can be lazy: modifies tests to pass vacuously if not watched
- Very literal - "fix this" does minimal changes, won't refactor surrounding code
- No agent teams capability
- Context window smaller than Claude (not 1M)
