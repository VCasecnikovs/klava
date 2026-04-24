---
name: typora
description: Open markdown files in Typora for editing. Use when user says edit in Typora, open markdown, or редактировать
user_invocable: true
---

# Open in Typora

Open a markdown file in Typora for viewing or editing.

## Behavior

1. Identify the file to open from conversation context:
   - User specifies a path directly
   - User references a recently created/edited file
   - User mentions an Obsidian note (resolve from vault path `~/Documents/MyBrain/`)
   - User mentions a file from `~/Documents/GitHub/` repos
2. Open with:
   ```bash
   open -a Typora "FILE_PATH"
   ```
3. Confirm briefly: "Открыл в Typora"

## Rules

- Works with `.md` files primarily
- If file path is ambiguous, search with Glob first
- For Obsidian notes: prepend `~/Documents/MyBrain/` if not a full path
- If Typora is not running, it will launch automatically
- If file doesn't exist, tell the user instead of creating it
