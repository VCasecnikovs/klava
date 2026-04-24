#!/usr/bin/env python3
"""Idle-research session — runs when the Klava queue is empty.

Spawns a short Claude session that reads recent context (heartbeat daily notes,
overdue Google Tasks, stale deals, recent Feed) and emits exactly one concrete
[PROPOSAL] task awaiting the user's approval.

Called by `tasks.consumer` when:
  - no pending tasks in the Klava queue
  - no active subagents (we don't pile on)
  - no existing [PROPOSAL] already waiting for approval
  - rate limit (1/hour) not exceeded

The prompt is deliberately narrow:
  "Find ONE concrete improvement the user would approve if asked."

The spawned session MUST call `create_proposal()` exactly once. Nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT))

from lib.claude_executor import ClaudeExecutor  # noqa: E402
from tasks.queue import recent_rejections  # noqa: E402

log = logging.getLogger("idle-research")

RATE_LIMIT_PATH = Path("/tmp/klava-idle-last.json")
RATE_LIMIT_SECONDS = 60 * 60  # 1 proposal per hour max
IDLE_MODEL = "sonnet"         # cheap — this is speculative work
IDLE_TIMEOUT = 15 * 60        # 15 min cap


# -----------------------------------------------------------------------------


def rate_limited() -> bool:
    """Return True if the last idle-research fired less than RATE_LIMIT_SECONDS ago."""
    try:
        data = json.loads(RATE_LIMIT_PATH.read_text())
        last = datetime.fromisoformat(data["last"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last
        return elapsed < timedelta(seconds=RATE_LIMIT_SECONDS)
    except Exception:
        return False


def stamp_rate_limit() -> None:
    try:
        RATE_LIMIT_PATH.write_text(json.dumps({
            "last": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception as e:
        log.warning(f"could not stamp rate-limit: {e}")


# -----------------------------------------------------------------------------


REJECTION_LIMIT = 15  # cap recent rejections we inject into the prompt
REJECTION_WINDOW_DAYS = 30


def _format_rejections(entries: list) -> str:
    """Format recent rejections as a markdown block for the prompt."""
    if not entries:
        return ""
    lines = [
        "## Recently rejected proposals — DO NOT RESURFACE",
        "",
        (
            "the user has already rejected the following proposals in the last "
            f"{REJECTION_WINDOW_DAYS} days. Do NOT propose the same idea, the "
            "same person/deal with the same angle, or a cosmetic rewording. "
            "If you find yourself drawn to one of these, pick a different angle "
            "or a different entity entirely."
        ),
        "",
    ]
    for rec in entries:
        title = rec.get("title", "(no title)")
        reason = (rec.get("reason") or "").strip() or "(no reason given)"
        tags = rec.get("mode_tags") or ""
        when = (rec.get("rejected_at") or "")[:10]
        lines.append(f"- [{when}] {title}  — reason: {reason}  (tags: {tags})")
    lines.append("")
    return "\n".join(lines)


IDLE_PROMPT_HEADER = """You are Klava running an IDLE-RESEARCH tick. The Klava queue is empty.

Your ONE job this tick: find a single concrete improvement the user would approve
if asked, and propose it by calling `tasks.queue.create_proposal()` exactly once.

## Sampling (in order of priority)

1. **Today and yesterday daily notes** —
   `~/.klava/memory/$(date +%Y-%m-%d).md`
   `~/.klava/memory/$(date -v-1d +%Y-%m-%d).md`
   Look for: open loops, unfinished threads, flagged blockers, "future me would need this" notes.

2. **Overdue / stale Google Tasks** —
   Use the `gog` skill to list the primary tasks list (100 results, results-only).
   Anything overdue by 7+ days is candidate material.

3. **Active deals in your notes vault** — e.g. `~/Documents/Notes/Deals/`.
   Silent deals, pending follow-ups, stages that haven't advanced in 10+ days.

4. **MEMORY.md context** — recurring blockers, key facts marked OVERDUE.

## Picking ONE proposal

Prefer proposals that are:
  - Concrete (specific file, person, deal — not "look into X")
  - Reversible (drafts, not sends; notes, not commits)
  - 15 min or less of work if approved
  - Directly tied to a named entity (person, deal, project)

Skip:
  - Broad research ("research the market")
  - Meta-work ("organize my notes")
  - Anything requiring live conversation

## Output — MANDATORY

Call `create_proposal()` exactly once. Do NOT create regular tasks, do NOT send messages,
do NOT edit code. Example (imports already wired):

```python
from tasks.queue import create_proposal
create_proposal(
    title="Jane Smith — draft company overview + product deck reply",
    plan=(
        "1. Open `People/Jane Smith.md`.\\n"
        "2. Draft a 2-paragraph reply framing the hardware prototype requirement.\\n"
        "3. Include company one-pager link.\\n"
        "4. Save reply into a new [REPLY] GTask (do NOT send)."
    ),
    shape="reply",
    mode_tags=["deal"],
    priority="medium",
    criticality=55,
)
```

After the call, output a short one-line confirmation ("proposed: <title>") and STOP.
Do not pick a second proposal even if others seem obvious — this tick belongs to one.
"""


def build_prompt() -> str:
    """Assemble the idle-research prompt with the current rejection memory."""
    try:
        rejections = recent_rejections(
            limit=REJECTION_LIMIT, max_days=REJECTION_WINDOW_DAYS
        )
    except Exception as e:
        log.warning(f"could not read rejection log: {e}")
        rejections = []
    rejection_block = _format_rejections(rejections)
    if rejection_block:
        return IDLE_PROMPT_HEADER + "\n\n" + rejection_block
    return IDLE_PROMPT_HEADER


def run_idle_research() -> dict:
    """Spawn the idle-research session. Returns the executor result dict."""
    log.info("idle-research: spawning session (model=%s)", IDLE_MODEL)
    executor = ClaudeExecutor(log_callback=log.info)
    result = executor.run(
        prompt=build_prompt(),
        mode="isolated",
        model=IDLE_MODEL,
        timeout=IDLE_TIMEOUT,
        skip_permissions=True,
        add_dirs=[
            p.strip() for p in os.environ.get(
                "IDLE_RESEARCH_ADD_DIRS",
                str(Path(__file__).resolve().parent.parent),
            ).split(":") if p.strip()
        ],
    )
    stamp_rate_limit()
    return result


if __name__ == "__main__":
    # Manual invocation path — lets the user kick a tick by hand for testing.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    out = run_idle_research()
    print(json.dumps({
        "cost": out.get("cost"),
        "duration": out.get("duration"),
        "error": out.get("error"),
        "session_id": out.get("session_id"),
    }, indent=2))
