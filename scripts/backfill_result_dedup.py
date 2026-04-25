"""One-shot backfill: collapse multi-pending RESULT clusters in the live Deck.

Strategy:
- Cluster pending RESULT cards in the last 7 days using the same topic
  matcher that runs in `create_result()`.
- For each cluster with 2+ pending: keeper = oldest pending. Append every
  other pending card's body as a `## Update <ts>` section, then mark the
  others done so they drop off the Deck.
- Done/REJECTED cards are never touched.

Run with --dry-run first; without it, applies for real.
"""

import sys
import argparse
from datetime import datetime, timezone, timedelta

from tasks.queue import (
    list_tasks, _topic_similar, _list_id,
    update_task_notes, complete_task,
)


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def cluster_pending(window_days=7):
    tasks = list_tasks(include_completed=True)
    results = [t for t in tasks if t.type == "result"]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    annotated = []
    for t in results:
        ts = parse_ts(t.completed_at or t.created)
        if not ts or ts < cutoff:
            continue
        annotated.append((t, ts))
    annotated.sort(key=lambda x: x[1])

    clusters = []
    for t, ts in annotated:
        placed = False
        for cluster in clusters:
            rep_t, _ = cluster[0]
            same_parent = (
                t.result_of is not None
                and rep_t.result_of is not None
                and t.result_of == rep_t.result_of
            )
            if same_parent or _topic_similar(t.title or "", rep_t.title or ""):
                cluster.append((t, ts))
                placed = True
                break
        if not placed:
            clusters.append([(t, ts)])
    return clusters


def merge_cluster(cluster, *, dry_run, lid):
    pendings = [(t, ts) for t, ts in cluster if t.status == "pending"]
    if len(pendings) < 2:
        return None
    pendings.sort(key=lambda x: x[1])
    keeper, keeper_ts = pendings[0]
    others = pendings[1:]

    new_body = (keeper.body or "").rstrip()
    for t, ts in others:
        section_ts = ts.strftime("%Y-%m-%d %H:%M UTC")
        addition = (t.body or "").strip()
        if addition.startswith("#result"):
            addition = addition[len("#result"):].lstrip()
        if not addition:
            addition = f"(merged from {t.id} — empty body)"
        new_body += (
            f"\n\n## Update {section_ts}"
            f"\n_(merged from card `{t.id}` — original title: {t.title!r})_\n\n"
            f"{addition}"
        )

    keeper.body = new_body.strip()
    keeper.result_status = "new"
    keeper.status = "pending"

    plan = {
        "keeper_id": keeper.id,
        "keeper_title": keeper.title,
        "merged_ids": [t.id for t, _ in others],
        "merged_titles": [t.title for t, _ in others],
    }

    if not dry_run:
        update_task_notes(keeper.id, keeper.to_notes(), list_id=lid)
        for t, _ in others:
            try:
                complete_task(t.id, list_id=lid)
            except Exception as e:
                print(f"  WARN: failed to complete {t.id}: {e}", file=sys.stderr)

    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change without writing.")
    ap.add_argument("--window-days", type=int, default=7)
    args = ap.parse_args()

    lid = _list_id()
    clusters = cluster_pending(window_days=args.window_days)

    plans = []
    for cluster in clusters:
        plan = merge_cluster(cluster, dry_run=args.dry_run, lid=lid)
        if plan is not None:
            plans.append(plan)

    print(f"Mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    print(f"Clusters merged: {len(plans)}")
    print(f"Cards collapsed: {sum(len(p['merged_ids']) for p in plans)}")
    print()
    for i, p in enumerate(plans, 1):
        print(f"{i}. KEEPER {p['keeper_id']}")
        print(f"   {p['keeper_title']}")
        for mid, mt in zip(p["merged_ids"], p["merged_titles"]):
            print(f"   ↳ MERGED  {mid}")
            print(f"            {mt}")
        print()


if __name__ == "__main__":
    main()
