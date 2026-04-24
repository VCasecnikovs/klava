# Plan: Enhanced Tool Visualization in Dashboard Chat

## Problem

All tool calls in the web chat look identical - same yellow card, gear icon, plain text results. No visual differentiation between Read/Grep/Bash/WebSearch. No "running" state. No rich rendering. Hard to follow what's happening.

## Scope

- **Single file:** `tools/dashboard/live.html` (CSS + JS)
- No backend changes needed
- No new dependencies
- Pure CSS + vanilla JS

## Changes

### 1. Per-Tool Icons & Colors (highest visual impact, simplest)

Replace generic gear icon with tool-specific icons and accent colors.

| Tool | Icon | Color |
|------|------|-------|
| Read | 📄 | blue |
| Write | ✍️ | green |
| Edit | ✏️ | green |
| Grep | 🔍 | orange |
| Glob | 📂 | orange |
| Bash | 💻 | red |
| WebSearch | 🌐 | cyan |
| WebFetch | 🌐 | cyan |
| Task | 🤖 | purple |
| TodoWrite | ☑️ | yellow |
| AskUserQuestion | ❓ | pink |
| ToolSearch | 🔌 | gray |

**How:**
- Add `TOOL_META` JS object mapping tool names to `{icon, color}`
- Update `renderToolUseBlock()` to use per-tool icon/color
- CSS: per-tool color accents via `data-tool` attribute

### 2. Running State Animation

Show spinner/pulse while tool executes (between `tool_use` and `tool_result`).

- Add `.chat-tool.running` CSS with pulsing border animation
- `handleToolUse()`: add `running` class, store ref to element
- `handleToolResult()`: remove `running` class
- `@keyframes tool-pulse` - subtle border glow

### 3. Better Tool Summaries

More informative collapsed-state summaries.

- `Bash`: show command (truncated)
- `Edit`: file path + "replacing X chars"
- `Task`: description + subagent_type badge
- Extend `getToolSummary()` with more cases

### 4. Rich Result Rendering (most complex, highest value)

Different rendering for different result types.

| Result Type | Detection | Rendering |
|-------------|-----------|-----------|
| File content | Line numbers `1→` | Code block with line numbers, mono font |
| File list | Multiple lines, each a path | Compact list with file icons |
| JSON | Valid JSON | Formatted collapsible tree |
| Search results | "Found N files" | Match list with counts |
| Error | "error" / stack trace | Red-accented block |
| Plain text | Default | Current behavior |

- `detectResultType(content)` dispatcher
- Specialized renderers per type
- Simple heuristics, no heavy parsing

### 5. Result Size Indicator

Show result size (e.g., "2.1 KB", "47 lines") as small badge before expanding.

- Calculate in `renderToolResultBlock()`
- `.chat-tool-result-meta` span

### 6. Parallel Tool Grouping (nice-to-have)

When multiple tools fire within 100ms, group visually in flex row.

- Track timestamps between `tool_use` events
- Wrap in `.tool-group { display: flex; gap: 8px; flex-wrap: wrap; }`
- Compact card rendering per tool

## Implementation Order

1. Per-tool icons & colors
2. Running state animation
3. Better tool summaries
4. Rich result rendering
5. Result size indicator
6. Parallel tool grouping
