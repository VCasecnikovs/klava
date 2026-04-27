"""One-shot manual cleanup of [RESULT] backlog as of 2026-04-27.

Decisions are hardcoded based on a manual review of all 77 pending RESULT
cards in the live Klava Deck — Jaccard alone missed real duplicates (same
person under different aliases, same intent worded differently, multi-card
clusters around one event), so this script ships a curated decision list
instead of trying to be clever.

Run:
    python3 scripts/cleanup_result_backlog_apr27.py --dry-run
    python3 scripts/cleanup_result_backlog_apr27.py --apply

Each entry is one of:
    ("merge", keeper_id, [closed_id, ...], short_reason)
    ("cancel", task_id, short_reason)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from tasks.queue import (
    list_tasks,
    update_task_notes,
    complete_task,
    cancel_task,
)


# --- curated decisions ------------------------------------------------------

MERGES = [
    # Same person under two aliases, same intent (ESTA + Wynne follow-up).
    (
        "blh4bFZtMzFadk",  # keeper: "Reply Rich Bro on Signal — Wynne thanks + ESTA approved + asks back"
        ["MGYxVmV1R09IYV"],  # "Александр Орлов (Rich Bro) - ESTA status + Wynne WeChat follow-up"
        "Same person (Rich Bro = Александр Орлов), same topic",
    ),
    # Eldil pricing reply — two cards, same draft.
    (
        "bVdCcEF1b19DYX",  # keeper: "[REPLY] Eldil AI (Shawn) — draft pricing reply using framework"
        ["SzFPSkpBdzI0Zj"],  # "Draft Shawn Schneider Signal reply - 100B religious books pricing"
        "Same draft (Shawn Schneider = Eldil AI, religious books = pricing reply)",
    ),
    # Babel Street — two cards, same wait state.
    (
        "SkZoNFJlWDY5N3",  # keeper: "Babel Street - watch for partnerships team intro email"
        ["V21kMEhCd0NGLT"],  # "[DEAL] Babel Street — check partnerships intro email"
        "Same task (watch for partnerships intro email)",
    ),
    # Apr 30 21:00 EEST conflict cluster — three cards, one decision.
    (
        "M0M1LWdMTVlaQ0",  # keeper: "Resolve Apr 30 21:00 EEST calendar conflict — Lucas Blakeslee+Cyris vs Lucas Chu"
        [
            "MVVkWDZqbTliZ2",  # "Lucas Chu (Lightyear) - Apr 30 21:00 call"
            "Y2FPODB6R2RaOW",  # "Signal Lev/Lucas Blakeslee/Cyris to lock real call time"
        ],
        "Same Apr 30 21:00 conflict — keep the resolve card",
    ),
    # Klim Kireev — plan + follow-up email, one thread.
    (
        "d3hpeU9senktc0",  # keeper: "Klim Kireev (EPFL) - follow up USENIX collab email if silent"
        ["LS05VVlNZmk1WE"],  # "Plan: Klim Kireev (EPFL) - propose Telegram follow-up paper collab"
        "Same Kireev thread — keep the live follow-up",
    ),
]

CANCELS = [
    # SF flight booking — already booked Apr 26 per MEMORY.md (AF7983).
    ("WmE5ZXZwUGpYTU", "SF flight booked Apr 26 (AF7983) — obsolete"),
    ("SzNUYTA1RHJlQU", "SF flight booked Apr 26 (AF7983) — obsolete"),
    ("bTkxX1U2cHNhYz", "Already done — Diana SF dates message sent"),

    # Klava-internal fixes — already shipped to main.
    ("Q3BweXNZd0ZiYV", "Shipped: c606861 (create_task title dedup) covers re-queue loops"),
    ("TlFpbkNfNXlJUz", "Shipped: c606861 + 080771e (consumer + result dedup)"),
    ("bTNRQzBFMjVXT2", "Shipped: c76f49a (block automated sources from execution-tag prefixes)"),

    # Past-deadline prep / sync cards.
    ("Mzl3RjMtU25JVV", "Past: Pufit + Lev sync was Apr 20 21:00"),
    ("dHJwN0dsdVFjWn", "Past: Wallet (EA) call was Apr 21 20:00"),
    ("UVN3dmw5VWZ6Yz", "Past: XOV team sync invite was for Apr 21"),
    ("dmVLMnhFVndHWU", "Past: HighTower call was Apr 24 16:30"),
    ("S2w0YWlZSmRQLU", "Past: SF Apr 23 registration window — done"),
    ("RDhYQW1FQlFMRC", "Past: Physical AI Industry Night was Thu Apr 23 17:30"),

    # Past urgent / one-shot.
    ("Z05pTjBkNlJKMG", "Past: astrum.trade renewal deadline was Apr 21 — verify standalone if needed"),
    ("a21telJXemRSNk", "Stale: meta-cleanup task — ENGY/Milan dupes already gone"),

    # Pulse cards — already past, by-design periodic.
    ("T3lSU1hEWl9pYU", "Pulse Apr 25 14:00 — periodic, past"),
    ("VjNNekw1eFJmaW", "Pulse Apr 25 20:00 — periodic, past"),
]


# --- execution --------------------------------------------------------------

def _index_by_id(tasks):
    return {t.id: t for t in tasks}


def _resolve(prefix: str, tasks) -> str | None:
    """Curated decisions list 14-char prefixes; resolve to full GTasks IDs."""
    for t in tasks:
        if t.id.startswith(prefix):
            return t.id
    return None


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main():
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    tasks = list_tasks(include_completed=False)
    by_id = _index_by_id(tasks)

    print("=" * 78)
    print(f"PLAN — {'APPLY' if args.apply else 'DRY-RUN'} — {_ts()}")
    print("=" * 78)

    plan_merges = []
    plan_cancels = []
    skipped = []

    for keeper_prefix, closed_prefixes, reason in MERGES:
        keeper_id = _resolve(keeper_prefix, tasks)
        keeper = by_id.get(keeper_id) if keeper_id else None
        if not keeper:
            skipped.append(("merge", keeper_prefix, "keeper not in pending list"))
            continue
        live_closed = []
        for cp in closed_prefixes:
            cid = _resolve(cp, tasks)
            t = by_id.get(cid) if cid else None
            if not t:
                skipped.append(("merge-closed", cp, "already gone"))
                continue
            live_closed.append(t)
        if not live_closed:
            skipped.append(("merge", keeper_prefix, "no closable siblings left"))
            continue
        plan_merges.append((keeper, live_closed, reason))

    for cp, reason in CANCELS:
        cid = _resolve(cp, tasks)
        t = by_id.get(cid) if cid else None
        if not t:
            skipped.append(("cancel", cp, "already gone"))
            continue
        plan_cancels.append((t, reason))

    print(f"\nMERGE clusters: {len(plan_merges)}")
    for keeper, closed, reason in plan_merges:
        print(f"\n  KEEP   {keeper.id[:14]}  {keeper.title}")
        for c in closed:
            print(f"  CLOSE  {c.id[:14]}  {c.title}")
        print(f"  WHY    {reason}")

    print(f"\nCANCEL stale: {len(plan_cancels)}")
    for t, reason in plan_cancels:
        print(f"  {t.id[:14]}  {t.title}")
        print(f"      WHY: {reason}")

    if skipped:
        print(f"\nSKIPPED (already gone or not found): {len(skipped)}")
        for kind, tid, why in skipped:
            print(f"  [{kind}] {tid[:14]}  {why}")

    print("\n" + "=" * 78)
    n_close = sum(len(c) for _, c, _ in plan_merges) + len(plan_cancels)
    print(f"TOTAL cards to remove from Deck: {n_close}")
    print("=" * 78)

    if not args.apply:
        print("\nDry run only. Re-run with --apply to execute.")
        return 0

    print("\nApplying...")
    for keeper, closed, reason in plan_merges:
        merge_note = (keeper.body or "").rstrip()
        merged_ids = []
        for c in closed:
            merged_ids.append(c.id)
            sibling_body = (c.body or "").strip()
            section = (
                f"\n\n## Merged from {c.id[:14]} — {_ts()}\n"
                f"_{c.title}_\n\n"
                f"{sibling_body if sibling_body else '(no body)'}\n"
            )
            merge_note = merge_note + section
        merge_note = merge_note + (
            f"\n\n## Cleanup note — {_ts()}\n"
            f"Merged sibling cards into this one. Reason: {reason}.\n"
        )
        try:
            update_task_notes(keeper.id, merge_note)
            print(f"  merged into {keeper.id[:14]}: {keeper.title}")
        except Exception as e:
            print(f"  ERROR updating keeper {keeper.id[:14]}: {e}")
            continue
        for c in closed:
            try:
                complete_task(c.id)
                print(f"    closed {c.id[:14]}: {c.title}")
            except Exception as e:
                print(f"    ERROR closing {c.id[:14]}: {e}")

    for t, reason in plan_cancels:
        try:
            cancel_task(t.id)
            print(f"  cancelled {t.id[:14]}: {t.title}  [{reason}]")
        except Exception as e:
            print(f"  ERROR cancelling {t.id[:14]}: {e}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
