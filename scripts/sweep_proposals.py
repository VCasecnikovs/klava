"""One-time sweep of pending [PROPOSAL] cards.

Run after Fix 1 (semantic dedup at write time) ships, to clean up
the backlog of proposals that piled up before the dedup was in place.

What it does, non-destructive:
  1. Loads every pending `type=proposal` card from the Klava list.
  2. Greedy-clusters them via the same LLM matcher that dedups results.
     For each unclustered head, asks Claude haiku which other titles
     are about the same topic. Matches form a cluster.
  3. For each proposal, runs `evidence_closer.evaluate_card` to check
     whether vadimgest already shows the user acted (Signal / Telegram /
     Gmail / Hlopya / etc dated after the card was created).
  4. Writes a single [RESULT] digest card on the Deck with three sections:
       - Duplicate clusters (2+ proposals on the same topic)
       - Proposals with action evidence (suggest closing)
       - Stale informational (extract said non-actionable)
     Plus a "Singletons with no evidence" tail so the user can see what's
     genuinely still open.

Default is review-only: no proposals are closed, no other writes happen
besides the digest card. The user reviews and clicks complete on what's
done.

Pass `--apply` to additionally close (a) every proposal in a duplicate
cluster except the most-recent (the survivor), and (b) every proposal
where evidence_closer found a hit. Closures get an audit note appended
to the proposal body before complete_task is called.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import List, Optional

from tasks.queue import (
    list_tasks, complete_task, update_task_notes, create_result, _list_id, Task,
)
from tasks.evidence_closer import evaluate_card, ClosureDecision
from tasks.llm_matcher import topic_matches_llm


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _cluster_proposals(props: List[Task]) -> List[List[Task]]:
    """Greedy LLM-based clustering. Returns a list of clusters.

    For each unclustered head, asks the matcher which of the remaining
    proposals are same-topic. Match set forms the cluster. Repeats until
    every proposal is in a cluster (size 1 = singleton).
    """
    by_id = {p.id: p for p in props}
    remaining_ids = [p.id for p in props]
    clusters: List[List[Task]] = []

    while remaining_ids:
        head_id = remaining_ids.pop(0)
        head = by_id[head_id]
        if not remaining_ids:
            clusters.append([head])
            break
        candidate_pairs = [(pid, by_id[pid].title or "") for pid in remaining_ids]
        try:
            matched_ids = set(topic_matches_llm(head.title or "", candidate_pairs))
        except Exception as e:
            print(f"[sweep] LLM matcher failed for head {head_id[:14]}: {e}",
                  file=sys.stderr)
            matched_ids = set()
        cluster = [head] + [by_id[pid] for pid in remaining_ids if pid in matched_ids]
        remaining_ids = [pid for pid in remaining_ids if pid not in matched_ids]
        clusters.append(cluster)

    return clusters


def _pick_survivor(cluster: List[Task]) -> Task:
    """Choose which proposal to keep from a cluster. Most-recently-created
    wins — it's likely the freshest framing of the topic."""
    return max(cluster, key=lambda t: t.created or "")


def _cluster_line(p: Task) -> str:
    when = (p.created or "")[:10] or "?"
    title = (p.title or "").replace("[PROPOSAL]", "").strip()
    return f"  - `{p.id[:14]}` _{when}_ {title}"


def main() -> int:
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--review-only", action="store_true",
                     help="Just write the digest card; no proposals closed (default).")
    grp.add_argument("--apply", action="store_true",
                     help="Close non-survivor cluster members and evidenced proposals.")
    ap.add_argument("--limit", type=int, default=200,
                    help="Max pending proposals to evaluate.")
    ap.add_argument("--no-digest", action="store_true",
                    help="Skip writing the summary digest card to the Deck.")
    args = ap.parse_args()

    apply_mode = bool(args.apply)
    if not apply_mode and not args.review_only:
        args.review_only = True

    lid = _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    proposals = [
        t for t in tasks
        if t.type == "proposal" and t.status == "pending"
        and (t.proposal_status or "pending") != "rejected"
    ][: args.limit]

    print(f"=== PROPOSAL SWEEP {_ts()} — {'APPLY' if apply_mode else 'REVIEW-ONLY'} ===")
    print(f"pending proposals: {len(proposals)}")
    print()

    if not proposals:
        print("nothing to do.")
        return 0

    print("clustering via LLM matcher...")
    clusters = _cluster_proposals(proposals)
    multi_clusters = [c for c in clusters if len(c) > 1]
    singletons = [c[0] for c in clusters if len(c) == 1]
    print(f"  -> {len(clusters)} clusters total, "
          f"{len(multi_clusters)} duplicate clusters, "
          f"{len(singletons)} singletons")
    print()

    print("evaluating evidence...")
    decisions: dict[str, ClosureDecision] = {}
    for p in proposals:
        try:
            d = evaluate_card(p)
        except Exception as e:
            print(f"  [{p.id[:14]}] evaluate failed: {e}", file=sys.stderr)
            continue
        decisions[p.id] = d
    closed_by_evidence = [p for p in proposals
                          if decisions.get(p.id) and decisions[p.id].decision == "close"]
    digest_marked = [p for p in proposals
                     if decisions.get(p.id) and decisions[p.id].decision == "skip-not-actionable"]
    print(f"  -> {len(closed_by_evidence)} with action evidence, "
          f"{len(digest_marked)} marked not-actionable")
    print()

    # Build closure plan
    cluster_closures: list[tuple[Task, Task]] = []  # (loser, survivor)
    for cluster in multi_clusters:
        survivor = _pick_survivor(cluster)
        for p in cluster:
            if p.id != survivor.id:
                cluster_closures.append((p, survivor))

    # Don't double-close: if a proposal is BOTH in a dup cluster (loser)
    # AND has evidence, the cluster closure path takes precedence; remove
    # from the evidence list so we don't process it twice.
    cluster_loser_ids = {loser.id for loser, _ in cluster_closures}
    evidence_closures = [p for p in closed_by_evidence
                         if p.id not in cluster_loser_ids]

    print(f"PLAN: would close {len(cluster_closures)} duplicates "
          f"+ {len(evidence_closures)} evidence-backed = "
          f"{len(cluster_closures) + len(evidence_closures)} total")

    if apply_mode:
        print("\napplying closures...")
        for loser, survivor in cluster_closures:
            try:
                audit = (
                    f"## Auto-closed by sweep_proposals at {_ts()}\n\n"
                    f"Duplicate of `{survivor.id[:14]}` "
                    f"({(survivor.title or '').replace('[PROPOSAL]', '').strip()}). "
                    f"Survivor kept; this card closed as redundant.\n"
                )
                _append_audit_and_close(loser, audit, lid)
                print(f"  closed dup {loser.id[:14]}: {(loser.title or '')[:70]}")
            except Exception as e:
                print(f"  ERROR closing dup {loser.id[:14]}: {e}", file=sys.stderr)
        for p in evidence_closures:
            try:
                d = decisions[p.id]
                ev_summary = "; ".join(
                    f"{h.source}@{h.date}: {h.excerpt[:60]}"
                    for h in (d.evidence or [])[:3]
                )
                audit = (
                    f"## Auto-closed by sweep_proposals at {_ts()}\n\n"
                    f"Evidence found in vadimgest after card was created:\n\n"
                    f"{ev_summary}\n"
                )
                _append_audit_and_close(p, audit, lid)
                print(f"  closed evidenced {p.id[:14]}: {(p.title or '')[:70]}")
            except Exception as e:
                print(f"  ERROR closing evidenced {p.id[:14]}: {e}",
                      file=sys.stderr)

    if not args.no_digest:
        try:
            _write_review_card(
                proposals=proposals,
                clusters=clusters,
                decisions=decisions,
                cluster_closures=cluster_closures,
                evidence_closures=evidence_closures,
                apply_mode=apply_mode,
            )
        except Exception as e:
            print(f"[digest] failed to write digest card: {e}", file=sys.stderr)

    return 0


def _append_audit_and_close(card: Task, audit: str, lid: str) -> None:
    new_body = (card.body or "") + "\n\n" + audit
    card.body = new_body
    update_task_notes(card.id, card.to_notes(), list_id=lid)
    complete_task(card.id, list_id=lid)


def _write_review_card(
    proposals: list,
    clusters: list,
    decisions: dict,
    cluster_closures: list,
    evidence_closures: list,
    apply_mode: bool,
) -> None:
    multi_clusters = [c for c in clusters if len(c) > 1]
    singletons = [c[0] for c in clusters if len(c) == 1]
    digest_marked = [p for p in proposals
                     if decisions.get(p.id) and decisions[p.id].decision == "skip-not-actionable"]
    no_evidence_singletons = [
        p for p in singletons
        if not (decisions.get(p.id) and decisions[p.id].decision == "close")
        and not (decisions.get(p.id) and decisions[p.id].decision == "skip-not-actionable")
    ]

    mode_label = "applied" if apply_mode else "review-only"
    title = (
        f"Proposal sweep ({mode_label}) — "
        f"{datetime.now(timezone.utc).strftime('%b %d %H:%M UTC')}"
    )

    lines: List[str] = [
        "#result",
        "",
        f"## Summary",
        f"- Total pending proposals: **{len(proposals)}**",
        f"- Duplicate clusters (2+): **{len(multi_clusters)}** "
        f"covering {sum(len(c) for c in multi_clusters)} cards",
        f"- Proposals with action evidence: **{len(evidence_closures)}**",
        f"- Marked not-actionable (informational): **{len(digest_marked)}**",
        f"- Genuine singletons with no evidence: **{len(no_evidence_singletons)}**",
        "",
        f"Mode: **{mode_label}**" + (
            f" — closed {len(cluster_closures) + len(evidence_closures)} cards"
            if apply_mode else
            " — no proposals were closed; review and act manually, "
            "or rerun with `--apply`"
        ),
        "",
    ]

    if multi_clusters:
        lines.append("## Duplicate clusters")
        lines.append("Survivor (most recent) marked with **SURVIVE**.")
        lines.append("")
        for i, cluster in enumerate(sorted(multi_clusters, key=len, reverse=True), 1):
            survivor = max(cluster, key=lambda t: t.created or "")
            lines.append(f"### Cluster {i} ({len(cluster)} cards)")
            for p in sorted(cluster, key=lambda t: t.created or "", reverse=True):
                marker = "**SURVIVE**" if p.id == survivor.id else "         "
                line = _cluster_line(p)
                lines.append(f"{marker} {line.lstrip()}")
            lines.append("")

    if evidence_closures:
        lines.append("## Proposals with action evidence")
        for p in evidence_closures:
            d = decisions[p.id]
            lines.append(_cluster_line(p))
            for h in (d.evidence or [])[:2]:
                lines.append(f"    [{h.source}@{h.date}] {h.excerpt[:120]}")
        lines.append("")

    if digest_marked:
        lines.append("## Marked not-actionable (informational)")
        for p in digest_marked:
            lines.append(_cluster_line(p))
        lines.append("")

    if no_evidence_singletons:
        lines.append(f"## Singletons with no evidence ({len(no_evidence_singletons)})")
        lines.append("These appear to be genuinely open. Triage manually.")
        lines.append("")
        for p in sorted(no_evidence_singletons, key=lambda t: t.created or "", reverse=True):
            lines.append(_cluster_line(p))
        lines.append("")

    create_result(
        parent_task_id=None,
        title=title,
        body="\n".join(lines),
        priority="low",
        source="proposal-sweep",
        digest=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
