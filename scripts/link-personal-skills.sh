#!/bin/bash
# Link personal skills into the main skills directory.
#
# Personal skills live at .claude/skills/personal/NAME/SKILL.md (gitignored).
# Claude Code only discovers skills at .claude/skills/NAME/SKILL.md (one level),
# so this script symlinks skills/NAME -> ./personal/NAME for each personal skill
# that doesn't already have a tracked dir with the same name.
#
# Run after cloning, or any time you add new personal skills.
# Usage: ./scripts/link-personal-skills.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO_DIR/.claude/skills"
PERSONAL_DIR="$SKILLS_DIR/personal"

if [ ! -d "$PERSONAL_DIR" ]; then
  echo "No .claude/skills/personal/ directory found. Nothing to link."
  exit 0
fi

count=0

for skill_dir in "$PERSONAL_DIR"/*/; do
  [ -d "$skill_dir" ] || continue
  name="$(basename "$skill_dir")"
  target="$SKILLS_DIR/$name"

  if [ -L "$target" ]; then
    continue
  elif [ -d "$target" ]; then
    echo "SKIP: $name (tracked skill exists, won't overwrite)"
    continue
  fi

  ln -sf "./personal/$name" "$target"
  count=$((count + 1))
done

# Regenerate skills/.gitignore: every symlink at depth 1 is a personal shadow
# and must not be committed. personal/ is gitignored via the root .gitignore.
gitignore="$SKILLS_DIR/.gitignore"
{
  echo "# Personal skill symlinks (auto-generated, local-only)"
  echo "# Created by: scripts/link-personal-skills.sh"
  for entry in $(find "$SKILLS_DIR" -maxdepth 1 -type l -exec basename {} \; | sort); do
    echo "$entry"
  done
} > "$gitignore"

total=$(find "$SKILLS_DIR" -maxdepth 1 -type l | wc -l | tr -d ' ')
echo "Linked $count new personal skills. Total symlinks: $total"
