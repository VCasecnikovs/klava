#!/usr/bin/env python3
"""Create Klava tasks for stale vadimgest data sources.

Replaces the dashboard's yellow "Stale sources" toast. Runs daily via CRON
and turns each unhealthy source into a deduplicated Klava task so the user
sees it in Tasks with context instead of an overlay covering the nav.

Title format: "Data source stale: <name> (<ago>)"
Dedup: matches by "Data source stale: <name>" prefix on open tasks.
Auto-completes tasks whose source is healthy again.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "gateway"))

from tasks.queue import create_task, list_tasks, complete_task  # noqa: E402


TASK_PREFIX = "Data source stale:"


def _collect_stale_sources() -> list[dict]:
    """Use the dashboard's status snapshot and return only unhealthy data sources."""
    from lib.status_collector import collect_dashboard_data  # type: ignore

    snapshot = collect_dashboard_data()
    return [s for s in snapshot.get("data_sources", []) if not s.get("healthy")]


def _source_name(title: str) -> str | None:
    """Extract the source name from a task title. Returns None if not a stale-source task."""
    if not title.startswith(TASK_PREFIX):
        return None
    rest = title[len(TASK_PREFIX):].strip()
    # Drop the trailing "(ago)" if present.
    if " (" in rest:
        rest = rest.split(" (", 1)[0].strip()
    return rest or None


def sync() -> dict:
    stale = _collect_stale_sources()
    stale_names = {s["name"]: s for s in stale}

    existing = list_tasks()
    existing_by_name: dict[str, str] = {}
    for task in existing:
        name = _source_name(task.title or "")
        if name:
            existing_by_name[name] = task.id

    created = []
    for name, info in stale_names.items():
        if name in existing_by_name:
            continue
        ago = info.get("last_data_ago") or "never"
        records = info.get("records", 0)
        missing_deps = info.get("missing_deps") or []

        title = f"{TASK_PREFIX} {name} ({ago})"
        body_lines = [
            f"Source: {name}",
            f"Last data: {ago}",
            f"Records total: {records:,}",
        ]
        if missing_deps:
            body_lines.append(f"Missing deps: {', '.join(missing_deps)}")
        body_lines.append("")
        body_lines.append(
            "Fix or mark the source as deliberately dormant. "
            "When the source catches up, this task auto-completes."
        )

        create_task(
            title=title,
            priority="low",
            source="self",
            body="\n".join(body_lines),
            # Stable origin id keyed on the source name so the consumer's
            # source_gtask_id dedup prevents two overlapping cron runs from
            # queuing the same source twice before the title-prefix dedup
            # above has seen the freshly created row.
            source_gtask_id=f"stale-source:{name}",
        )
        created.append(name)

    completed = []
    for name, task_id in existing_by_name.items():
        if name not in stale_names:
            try:
                complete_task(task_id)
                completed.append(name)
            except Exception as exc:
                print(f"WARN failed to complete task for {name}: {exc}", file=sys.stderr)

    return {"stale": list(stale_names), "created": created, "completed": completed}


if __name__ == "__main__":
    result = sync()
    print(
        f"stale={len(result['stale'])} created={len(result['created'])} "
        f"completed={len(result['completed'])}"
    )
    if result["created"]:
        print("  new:", ", ".join(result["created"]))
    if result["completed"]:
        print("  resolved:", ", ".join(result["completed"]))
