"""Evidence-driven auto-close runner.

Walks every pending card on the Deck of the requested types
(default `result`, can include `proposal`), asks the evidence_closer
whether vadimgest contains evidence the user already acted on it, and
either prints what it would do (`--dry-run`) or actually closes
(`--apply`).

Default is `--dry-run`. Apply only after reviewing dry-run output.

The runner emits a digest [RESULT] card on the Deck so the user can
see the closure decisions without watching a log file. The digest is
published with `digest=True`, `source=f"evidence-closer-{types}"`, so
runs over different type sets supersede their own prior digests rather
than each other (proposal-runs don't clobber result-runs).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from tasks.queue import (
    list_tasks, complete_task, update_task_notes, create_result, _list_id,
)
from tasks.evidence_closer import evaluate_card, ClosureDecision


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


_VALID_TYPES = ("result", "proposal", "task")


def main() -> int:
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true",
                     help="Print decisions without writing (default).")
    grp.add_argument("--apply", action="store_true",
                     help="Close cards with evidence; write digest card.")
    ap.add_argument("--limit", type=int, default=200,
                    help="Max pending cards to evaluate.")
    ap.add_argument("--no-digest", action="store_true",
                    help="Skip writing the summary digest card to the Deck.")
    ap.add_argument("--types", type=str, default="result",
                    help=("Comma-separated card types to evaluate. "
                          f"Valid: {','.join(_VALID_TYPES)}. Default: result. "
                          "For proposals, evidence-driven closure means the user "
                          "already actioned it on a real channel."))
    args = ap.parse_args()

    apply_mode = bool(args.apply)
    if not apply_mode and not args.dry_run:
        # default is dry-run
        args.dry_run = True

    types = tuple(
        t.strip() for t in (args.types or "").split(",") if t.strip()
    )
    bad = [t for t in types if t not in _VALID_TYPES]
    if bad:
        print(f"error: unknown --types value(s) {bad}; "
              f"valid: {_VALID_TYPES}", file=sys.stderr)
        return 2
    if not types:
        types = ("result",)
    types_label = ",".join(types)

    lid = _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    pending_results = [
        t for t in tasks
        if t.type in types and t.status == "pending"
    ][: args.limit]

    print(f"=== EVIDENCE CLOSER {_ts()} — types={types_label} "
          f"{'APPLY' if apply_mode else 'DRY-RUN'} ===")
    print(f"pending cards: {len(pending_results)}")
    print()

    decisions: list[ClosureDecision] = []
    for card in pending_results:
        d = evaluate_card(card)
        decisions.append(d)
        icon = {
            "close": "CLOSE   ",
            "skip-no-evidence": "  skip  ",
            "skip-not-actionable": "  digest",
            "skip-no-target": "  fail  ",
        }.get(d.decision, "  ?     ")
        print(f"{icon} {card.id[:14]} {(card.title or '')[:80]}")
        if d.decision == "close" and d.evidence:
            for h in d.evidence[:2]:
                excerpt = h.excerpt[:80]
                print(f"          [{h.source}@{h.date}] {excerpt}")

    closed = [d for d in decisions if d.decision == "close"]
    skipped_no_ev = [d for d in decisions if d.decision == "skip-no-evidence"]
    digest_marked = [d for d in decisions if d.decision == "skip-not-actionable"]
    extract_failed = [d for d in decisions if d.decision == "skip-no-target"]

    print()
    print(
        f"Summary: would-close={len(closed)} "
        f"no-evidence={len(skipped_no_ev)} "
        f"digest-class={len(digest_marked)} "
        f"extract-failed={len(extract_failed)}"
    )

    if apply_mode and closed:
        print("\nApplying closures...")
        for d in closed:
            try:
                ev_summary = "; ".join(
                    f"{h.source}@{h.date}: {h.excerpt[:60]}"
                    for h in (d.evidence or [])[:3]
                )
                audit = (
                    f"## Auto-closed by evidence-closer at {_ts()}\n\n"
                    f"Evidence found in vadimgest after card was created:\n\n"
                    f"{ev_summary}\n"
                )
                # Append the audit note to the existing body before completing,
                # so the closure reason is preserved on the card.
                card = next(t for t in pending_results if t.id == d.card_id)
                new_body = (card.body or "") + "\n\n" + audit
                update_task_notes(d.card_id, _build_full_notes(card, new_body), list_id=lid)
                complete_task(d.card_id, list_id=lid)
                print(f"  closed {d.card_id[:14]}: {d.card_title[:70]}")
            except Exception as e:
                print(f"  ERROR closing {d.card_id[:14]}: {e}", file=sys.stderr)

    if not args.no_digest:
        try:
            _write_digest_card(decisions, apply_mode, types_label)
        except Exception as e:
            print(f"[digest] failed to write digest card: {e}", file=sys.stderr)

    return 0


def _build_full_notes(card, new_body: str) -> str:
    """Re-serialize the task with mutated body, keeping all frontmatter."""
    card.body = new_body
    return card.to_notes()


def _write_digest_card(decisions: list, apply_mode: bool,
                       types_label: str = "result") -> None:
    closed = [d for d in decisions if d.decision == "close"]
    skipped = [d for d in decisions if d.decision == "skip-no-evidence"]
    digest_marked = [d for d in decisions if d.decision == "skip-not-actionable"]

    mode_label = "applied" if apply_mode else "dry-run"
    title = (
        f"Klava evidence-closer [{types_label}] ({mode_label}) — "
        f"{datetime.now(timezone.utc).strftime('%b %d %H:%M UTC')}"
    )

    lines = [
        "#result",
        "",
        f"## Summary (types={types_label})",
        f"- Closed: **{len(closed)}**" + (" (applied)" if apply_mode else " (would close)"),
        f"- Skipped (no evidence yet): {len(skipped)}",
        f"- Marked digest-class: {len(digest_marked)}",
        "",
    ]
    if closed:
        lines.append("## Closed cards")
        for d in closed:
            lines.append(f"- `{d.card_id[:14]}` {d.card_title}")
            for h in (d.evidence or [])[:2]:
                lines.append(f"  - [{h.source}@{h.date}] {h.excerpt[:120]}")
        lines.append("")
    if digest_marked:
        lines.append("## Marked digest-class (not auto-closed; informational)")
        for d in digest_marked:
            lines.append(f"- `{d.card_id[:14]}` {d.card_title}")
        lines.append("")

    # Source carries the types_label so a proposal-only run doesn't supersede
    # the result-only run's digest (and vice versa). Each type-set keeps its
    # own digest history on the Deck.
    create_result(
        parent_task_id=None,
        title=title,
        body="\n".join(lines),
        priority="low",
        source=f"evidence-closer-{types_label}",
        digest=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
