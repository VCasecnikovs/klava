---
user_invocable: true
name: gemini-cli
description: Run tasks via Gemini CLI. Use for large context analysis (1M tokens), free-tier research, Reddit fetching, or when you need a second opinion from a different model
---

# Gemini CLI

Google Gemini CLI - alternative model with 1M token context window. Free tier: 60 req/min, 1000 req/day on Gemini 2.5 Pro.

**Installed:** `gemini` v0.32.0

## When to Use

- **Large context analysis** - feed entire codebase/dataset (1M tokens), way beyond what fits in Claude context
- **Free-tier research** - 1000 req/day free, good for bulk one-shot queries
- **Reddit/blocked sites** - Gemini has web access, can fetch content Claude can't (see reddit-fetch skill)
- **Second opinion** - get a different model's take on architecture/code decisions
- **Bulk data processing** - cheap ($2/M input) for mass analysis

## When NOT to Use

- Agentic workflows (breaks out of harness, tool use unreliable)
- Long iterative sessions (degrades, deletes code)
- Production scripting via `-p` (buggy, tools ignored in headless mode)
- Anything requiring reliable infrastructure (503 errors during peak)

## Non-interactive Mode (-p)

```bash
# Simple query
gemini -p "Analyze this error: $(cat error.log)"

# With file input
cat large_file.py | gemini -p "Review this code for security issues"

# Specific model
gemini -m gemini-2.5-pro -p "Your prompt"
```

**WARNING:** `-p` mode has known bugs - tools/extensions are ignored. Use for text-in/text-out only.

## Interactive Mode (via tmux)

For tasks needing tools (web search, file access):

```bash
# Start session
tmux new-session -d -s gemini_session -x 200 -y 50
tmux send-keys -t gemini_session 'gemini' Enter
sleep 3

# Send query
tmux send-keys -t gemini_session 'Your query here' Enter
sleep 30  # wait for response

# Capture output
tmux capture-pane -t gemini_session -p -S -500

# Cleanup
tmux kill-session -t gemini_session
```

## Available Models

| Model | Free? | Context | Best for |
|---|---|---|---|
| gemini-2.5-pro | Yes (1000/day) | 1M | Default, good all-around |
| gemini-3.1-pro | API key needed | 1M | Best reasoning, expensive |
| gemini-3-flash | Yes | 1M | Fast, cheap |

## MCP Support

Gemini CLI supports MCP servers (same format as Claude Code):

```bash
gemini mcp list
gemini mcp add <server-name> -- <command>
```

## Key Limitations

- `-p` mode ignores tools/extensions (bug, GH issues #1508, #5435)
- No vision in headless mode
- Infrastructure unstable for 3.1 Pro (~45% 503 errors at peak)
- Tries to "escape" agentic harnesses
- Loses context in long sessions
