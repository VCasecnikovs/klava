---
user_invocable: true
name: html-view
description: Render complex content as a styled HTML page and open in browser. Use when output is too large or complex for terminal - tables, reports, lists, comparisons, timelines, data summaries.
---

# HTML View Skill

Render complex, large, or visually dense content as a beautiful HTML page and open it in the browser. Terminal is great for short answers - but for big tables, long lists, reports, comparisons, and structured data, a browser page is much better.

Every view has **selection-based annotations** - user selects text, picks an intention (Fix/Add/Remove/Do/Note), writes a comment. Then exports as MD and pastes back to Claude for the next iteration.

## When to Use

Use this skill **proactively** when content would be hard to read in terminal:
- Large tables (5+ columns or 10+ rows)
- Long structured lists (20+ items)
- Reports with multiple sections
- Side-by-side comparisons
- Timelines, dashboards, status overviews
- Any output where formatting matters for comprehension
- **Multi-item reviews** - when there are many items/decisions for the user to comment on

Do NOT use for:
- Short answers (< 20 lines)
- Simple lists
- Code snippets
- Conversational responses

## Review Workflow (core pattern)

When a task produces multiple items that need user feedback:

1. **Create html-view** with all items clearly laid out
2. **Open in browser** - user reviews, selects text, adds annotations with intentions
3. **User copies feedback** via "Copy Feedback as MD" button
4. **User pastes feedback** back into Claude Code
5. **Claude processes annotations** grouped by intention and continues working

This is the primary feedback loop. Use it whenever there are 5+ items to review.

## How It Works

1. Generate a self-contained HTML file with inline CSS + feedback module
2. Save to `~/Documents/MyBrain/Views/{slug}.html` (in Obsidian vault, synced)
3. Open in dashboard Views tab via API call (or browser if requested)
4. Update dashboard
5. Tell the user what was rendered

**Feedback loop:** User adds comments inline -> clicks "Copy Feedback as MD" -> pastes back to Claude -> next iteration.

## File Locations

- **Views directory:** `~/Documents/MyBrain/Views/`
- **Feedback module:** `~/Documents/GitHub/claude/.claude/skills/html-view/feedback-module.html`
- **Artifact bridge:** `~/Documents/GitHub/claude/.claude/skills/html-view/artifact-bridge.html`
- **Dashboard script:** `~/Documents/GitHub/claude/.claude/skills/html-view/scripts/gen-dashboard.py`

## Instructions

1. Determine the best layout for the content (table, cards, list, mixed)
2. Generate complete HTML with:
   - All CSS inline in `<style>`
   - Content in `<body>`
   - **Artifact bridge + Feedback module injected before `</body>`** (see step 6)
3. No external dependencies - everything must work offline
4. Save file:
   ```bash
   FILE="$HOME/Documents/MyBrain/Views/$(date +%Y%m%d-%H%M)-{slug}.html"
   ```
5. Use the Write tool to create the HTML file
6. Before `</body>`, inject modules in this order:
   a. Read `~/.claude/skills/html-view/artifact-bridge.html` and APPEND (enables interactive communication with Chat tab)
   b. Read `~/.claude/skills/html-view/feedback-module.html` and APPEND (enables annotation + Send Feedback)
   Both modules are ALWAYS included - bridge auto-detects if it's in an iframe or standalone.
7. Open in dashboard Views tab:
   ```bash
   curl -s -X POST http://localhost:18788/api/views/open \
     -H 'Content-Type: application/json' \
     -d '{"filename": "SLUG.html"}'
   ```
   This sends the view to the dashboard's Views tab via SocketIO (no browser popup).
   To force browser opening instead, add `"browser": true` to the JSON body.
8. Regenerate dashboard: `python3 ~/.claude/skills/html-view/scripts/gen-dashboard.py`
9. Tell the user: "Opened in Views tab: {brief description}. Add comments inline, then Copy Feedback as MD."

**IMPORTANT:** Always read and inline BOTH modules. Do NOT skip them. Order matters: bridge first, then feedback (feedback detects bridge to show Send Feedback button).

## Opening Markdown Files

You can also open Obsidian markdown files in the dashboard Views tab (rendered as styled HTML):

```bash
curl -s -X POST http://localhost:18788/api/views/open \
  -H 'Content-Type: application/json' \
  -d '{"path": "People/John Smith.md", "title": "John Smith"}'
```

Or reference in chat as an artifact:

````
```artifact
{"path": "People/John Smith.md", "title": "John Smith"}
```
````

The path is relative to `~/Documents/MyBrain/`. Wikilinks are resolved, YAML frontmatter is stripped, and markdown is rendered with tables, code blocks, and lists.

## Artifacts (Interactive Views in Chat)

Views can also be rendered as **artifacts** inside the Chat tab. Artifacts are full HTML files that appear as clickable cards in chat, open full-screen in an iframe, and can communicate back to Claude via postMessage.

### Creating an Artifact

Same as a regular view (bridge + feedback modules are already included per step 6), but additionally:
1. **Reference in chat** using the ` ```artifact ` code fence format:

````
Here's the deal comparison:

```artifact
{"filename": "20260224-1430-deal-comparison.html", "title": "Deal Comparison Dashboard"}
```
````

This renders as a clickable card in the Chat tab. Clicking opens the artifact full-screen with a toolbar (Back, title, Open external).

### Interactive Buttons

For buttons that should send a message back to Claude:

```html
<button onclick="artifactMessage('User approved deal Acme for $250k')">
  Approve Deal
</button>
```

`artifactMessage(text)` sends the text as a chat message to Claude, who can then respond or update the artifact.

For buttons that don't need Claude interaction - use regular JavaScript:

```html
<button onclick="this.closest('.card').remove()">Dismiss</button>
```

### Artifact Bridge API

The bridge script (`artifact-bridge.html`) provides:

- **`window.artifactMessage(text)`** - send a message to Claude via the chat
- **`window.onArtifactCommand`** - optional callback for commands from the dashboard (e.g., refresh)
- Auto-reload when the artifact file is updated by Claude

### When to Use Artifacts vs Regular Views

- **Artifact**: interactive decisions, approvals, forms that need Claude to process input
- **Regular view**: read-only reports, dashboards, data tables with annotation feedback

## Applying Feedback - Exhaustive Updates

When applying user feedback to an existing HTML view:

1. **Grep for ALL instances** of the value being changed BEFORE editing. A single fact (e.g., "commission is 20%") may appear in 5+ places: flow diagrams, tables, card text, highlight boxes, party descriptions, risk matrix, action items.
2. **Fix every instance in one pass.** Don't fix the first match and move on.
3. **After all edits, grep again** with patterns like `(old_value|old_text)` to verify zero remaining occurrences.
4. **Common miss pattern:** User says "commission is 20% not 15%" - you fix the main mention but leave "15-20%" in a flow diagram, "15% fee" in a table row, and "$80-85K" in a revenue split. This wastes a feedback round.
5. **Rule:** When a fact changes, treat it like a find-and-replace across the entire file, not a single edit.

## HTML Template

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{TITLE}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #fafafa;
    color: #1a1a1a;
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
  }

  h1 {
    font-size: 1.75rem;
    font-weight: 600;
    margin-bottom: 0.25rem;
    color: #111;
  }

  .subtitle {
    color: #888;
    font-size: 0.85rem;
    margin-bottom: 2rem;
  }

  h2 {
    font-size: 1.15rem;
    font-weight: 600;
    margin: 1.5rem 0 0.75rem;
    color: #333;
  }

  /* Tables */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 1rem 0;
    font-size: 0.9rem;
  }

  th {
    text-align: left;
    padding: 0.6rem 0.8rem;
    border-bottom: 2px solid #e0e0e0;
    font-weight: 600;
    color: #555;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  td {
    padding: 0.6rem 0.8rem;
    border-bottom: 1px solid #f0f0f0;
  }

  tr:hover { background: #f8f8f8; }

  /* Cards */
  .card {
    background: #fff;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    padding: 1.25rem;
    margin: 0.75rem 0;
  }

  .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 0.75rem;
  }

  /* Tags / Badges */
  .tag {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .tag-green  { background: #e6f9e6; color: #1a7a1a; }
  .tag-yellow { background: #fff8e0; color: #8a6d00; }
  .tag-red    { background: #fde8e8; color: #b91c1c; }
  .tag-blue   { background: #e8f0fe; color: #1a56db; }
  .tag-gray   { background: #f0f0f0; color: #666; }

  /* Lists */
  ul, ol { padding-left: 1.5rem; margin: 0.5rem 0; }
  li { margin: 0.3rem 0; }

  /* Utility */
  .muted { color: #999; }
  .bold { font-weight: 600; }
  .mono { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.85em; }
  .right { text-align: right; }
  .center { text-align: center; }
  .nowrap { white-space: nowrap; }

  /* Responsive */
  @media (max-width: 768px) {
    body { padding: 1rem; }
    .card-grid { grid-template-columns: 1fr; }
    table { font-size: 0.8rem; }
  }
</style>
</head>
<body>
  <h1>{TITLE}</h1>
  <div class="subtitle">Generated by Claude - {DATE}</div>

  {CONTENT}

  <!-- FEEDBACK MODULE: read and paste contents of feedback-module.html here -->

</body>
</html>
```

## Content Patterns

### Table
```html
<table>
  <thead><tr><th>Column</th><th>Column</th></tr></thead>
  <tbody><tr><td>Value</td><td>Value</td></tr></tbody>
</table>
```

### Card Grid
```html
<div class="card-grid">
  <div class="card">
    <div class="bold">Title</div>
    <div class="muted">Description</div>
    <span class="tag tag-green">Status</span>
  </div>
</div>
```

### Sections
```html
<h2>Section Title</h2>
<div class="card">...</div>
```

## Annotation System

The feedback module (`feedback-module.html`) provides selection-based annotations:

### How it works

1. **User selects text** anywhere on the page (normal browser selection)
2. **Popup appears** with intention buttons: Fix | Add | Remove | Do | Note
3. **User picks intention** and writes a comment
4. **Text gets highlighted** in the matching color
5. **Hover tooltip** shows comment with edit/delete options
6. **localStorage persistence** - annotations survive page refresh

### Intentions

| Intention | Color | Meaning |
|-----------|-------|---------|
| **Fix** | Orange | Change this specific thing |
| **Add** | Blue | Add more detail/content here |
| **Remove** | Red | Take this out |
| **Do** | Purple | Action item to execute |
| **Note** | Gray | FYI, no action needed |

### Bottom Toolbar

- **Copy Feedback as MD** - exports annotations grouped by intention (Do > Fix > Add > Remove > Notes)
- **Copy Full Page as MD** - exports full page + annotations
- **Clear All** - removes all annotations

### Feedback MD Format (what user pastes back)

```markdown
## Feedback: {Page Title}

### DO
- "selected text" - user comment here
- "another selection" - another comment

### FIX
- "text to fix" - what to change

### ADD
- "context text" - what to add

### REMOVE
- "text to remove" - why

### NOTES
- "reference text" - FYI note
```

## Dashboard

Views are accessible in Mission Control: `http://localhost:18788/dashboard#views`

All views also indexed in standalone dashboard:

```bash
python3 ~/Documents/GitHub/claude/.claude/skills/html-view/scripts/gen-dashboard.py
open ~/Documents/MyBrain/Views/dashboard.html
```

## Style Guide

- Clean, minimal Apple-inspired aesthetic
- No heavy colors or gradients
- Use tags/badges for status indicators
- Generous whitespace
- Readable font sizes
- Works well on both light and dark (prefers-color-scheme aware if needed)
