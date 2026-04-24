---
name: finder
description: Open Finder at relevant location. Use when user says open folder, show in Finder, or покажи файл
user_invocable: true
---

# Finder Skill

Opens Finder at a relevant location based on context.

## Usage

- `/finder` - open Finder at current working directory
- `/finder <path>` - open Finder at specified path
- `/finder obsidian` - open Obsidian vault
- `/finder skills` - open skills folder
- `/finder github` - open GitHub folder

## Shortcuts

- `obsidian` → ~/Documents/MyBrain
- `skills` → ~/.claude/skills
- `github` → ~/Documents/GitHub/claude
- `downloads` → ~/Downloads
- `desktop` → ~/Desktop

## Instructions

1. Parse the argument (if any)
2. Resolve shortcuts to full paths
3. If no argument, use current working directory
4. Run `open <path>` to open Finder at that location
5. Confirm to user what was opened
