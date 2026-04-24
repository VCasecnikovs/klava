#!/bin/bash
# Status line script - shows pipeline state alongside model and context usage
input=$(cat)

MODEL=$(echo "$input" | jq -r '.model.display_name // "?"')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
SID=$(echo "$input" | jq -r '.session_id // ""')
SID_PREFIX="${SID:0:16}"

STATE_FILE="$HOME/Documents/GitHub/claude/.claude/state/sessions/${SID_PREFIX}.json"

# Phase icons for quick scanning
declare -A ICONS=(
  [understand]="🔍"
  [match]="🎯"
  [think]="💭"
  [act]="⚡"
  [verify]="✅"
  [learn]="📝"
  [plan]="📋"
  [execute]="⚡"
  [result]="📊"
  [evaluate]="🔄"
  [intake]="📥"
  [output]="📤"
  [done]="✔"
  [failed]="✘"
)

# Check compaction state first
COMPACTING=""
if [ -f "$STATE_FILE" ]; then
  COMPACTING=$(jq -r '.compacting // false' "$STATE_FILE" 2>/dev/null)
fi

if [ "$COMPACTING" = "true" ]; then
  STARTED=$(jq -r '.compact_started // ""' "$STATE_FILE" 2>/dev/null)
  if [ -n "$STARTED" ] && [ "$STARTED" != "null" ]; then
    ELAPSED=$(( $(date +%s) - $(date -j -f "%Y-%m-%dT%H:%M:%S" "${STARTED%%.*}" +%s 2>/dev/null || echo 0) ))
    echo -e "[\033[36m${MODEL}\033[0m] \033[1;35m⏳ COMPACTING\033[0m \033[2m(${ELAPSED}s)\033[0m | ${PCT}% ctx"
  else
    echo -e "[\033[36m${MODEL}\033[0m] \033[1;35m⏳ COMPACTING\033[0m | ${PCT}% ctx"
  fi
  exit 0
fi

# Pipeline info - exact session match only (no fallback to other sessions)
FOUND=""

if [ -f "$STATE_FILE" ]; then
  PIPELINE=$(jq -r '.pipeline // ""' "$STATE_FILE" 2>/dev/null)
  if [ -n "$PIPELINE" ] && [ "$PIPELINE" != "null" ]; then
    FOUND="$STATE_FILE"
  fi
fi

if [ -n "$FOUND" ]; then
  PIPELINE=$(jq -r '.pipeline // ""' "$FOUND" 2>/dev/null)
  STATE=$(jq -r '.current_state // ""' "$FOUND" 2>/dev/null)
  RETRIES=$(jq -r '.retry_count // 0' "$FOUND" 2>/dev/null)
  ICON="${ICONS[$STATE]:-▶}"
  STATE_UPPER=$(echo "$STATE" | tr '[:lower:]' '[:upper:]')
  echo -e "[\033[36m${MODEL}\033[0m] ${ICON} \033[1;33m${STATE_UPPER}\033[0m \033[2m(${PIPELINE} ${RETRIES}/5)\033[0m | ${PCT}% ctx"
else
  echo -e "[\033[36m${MODEL}\033[0m] \033[2m— no loop —\033[0m ${PCT}% ctx"
fi
