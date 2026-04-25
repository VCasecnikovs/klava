"""Apply the 25 manually-curated merge clusters from the chat session.

Each entry: keeper_id → list of merge_ids. For each cluster:
- Read keeper + all mergees from snapshot.
- Append each mergee's body as a `## Update <ts>` section to the keeper.
- Mark each mergee done so it drops off the Deck.
- Bump keeper's result_status to "new" so the Deck re-surfaces it.
"""

import sys
from datetime import datetime, timezone

from tasks.queue import (
    list_tasks, _list_id, update_task_notes, complete_task,
)


# (keeper_id, [merge_ids], short_label_for_log)
MERGES = [
    # 1. Wallet (EA) Apr 21 call — 8 cards into 1
    ("dHJwN0dsdVFjWnB5VE5YNA", [
        "eWM3ejRRYkoxUUZXVjJ0Sw",
        "OGhBOUp5aUNNMTE2Y1pWcg",
        "V2RVMnVSRWdMeFFJNm96dQ",
        "TURRSHVmZ1ZkN1RNVmNfdg",
        "T0U0R0JLOU8xbkliX3pPcw",
        "LWI5cWlEcnpTaTkzRWxpVw",
        "RFNPWTVpLVI2cVZPTkZHQw",
    ], "Wallet (EA) Apr 21 call coordination"),

    # 2. SF housing decision — 4 cards into 1
    ("c29YckRWYk9mNnlOS3AwaQ", [
        "V3FwNWt3cHhpM0RMRW8zYg",
        "em9Rdi1fMGhNUERONXBNbw",
        "b1h2d040VHZwc0VQR2NzRA",
    ], "SF housing decision"),

    # 3. HighTower-Ilya call (extends prior backfill keeper)
    ("dmVLMnhFVndHWURGaHFoTA", [
        "S1Rkdk9pTC0wZ1RGd3owcA",
        "WHFDRXhlMi1QaklRUVZxcQ",
    ], "HighTower-Ilya call (extend)"),

    # 4. Reuters AP non-Western catalogue
    ("Z2I2NktPQkV4enRRRDN2YQ", [
        "ZnY0SEkxbDBlMXhvUDZNSQ",
        "ajJPUHNobFRqMzZGaDlMZw",
    ], "Reuters AP non-Western catalogue"),

    # 5. Monda/Datarade May 4
    ("TXZqSTczV2pBaE1tVHQ4TQ", [
        "cmZxb255WFpPUDBwMzZqdw",
        "ZmRFRWlFUHJQVG5tRTc5dw",
    ], "Monda/Datarade May 4"),

    # 6. Klava blog launch
    ("TGFOSzNNZFItNUgtN1VpZA", [
        "cHNLRVJTcnJrUDMxRUNHZg",
        "TFpGOVQ0U2d5cVRjdk4tSA",
    ], "Klava blog launch"),

    # 7. Timur Olevskiy O-1 article
    ("Q3R4Sl9vTXpsWTlFYTg4Xw", [
        "eVEzWmduOUFTNkdJZ0luVA",
    ], "Timur Olevskiy O-1"),

    # 8. ClawCamp May 11 Human+Tech
    ("NldmVG5ZM0VHbFdnVGlWSg", [
        "S1JoQm4ybkFUTEYyZ05udw",
    ], "ClawCamp May 11"),

    # 9. Backblaze B2 billing
    ("MmRuTmRSQTlSd3F1RFZ1OA", [
        "dHlBT1dDSTdxbjFNWmwwNA",
    ], "Backblaze B2 billing"),

    # 10. Klava settings.json wildcard
    ("NEJjRlkxOTZvM2R3YTM2OA", [
        "TTB5MmZDVzdCenFrSTVrSg",
    ], "settings.json wildcard"),

    # 11. Tiana data export
    ("anZadGxHUXR5eFJJek9kZg", [
        "U3B2QTcyb1pVNk5rZXVnSQ",
    ], "Tiana data export"),

    # 12. self-evolve exit 143
    ("dUVIaWI1UEtXOWZEdUpXTw", [
        "enF6QkNtbm5NOXhHcENWTw",
    ], "self-evolve exit 143"),

    # 13. Vasiliy blog critical review
    ("MkwyZnN2YXl0T3k0cXh1RA", [
        "TjNMT1AyOEJudDZUOXBzdg",
    ], "Vasiliy blog review"),

    # 14. Lucas Blakeslee XOV/HCI
    ("c3IzTmt3OGs1aUppamRrdw", [
        "ZThENG9mTnNsOU85anp6VQ",
    ], "Lucas Blakeslee"),

    # 15. SpaceX data head intro
    ("bEhQcEVkeU1pNVFUUDQ1Vg", [
        "MllZUnNRWF80UUd3SDdudQ",
    ], "SpaceX data head"),

    # 16. XOV WULPUS Vostrikov
    ("cTg1VWJEQ1lMc25VeTdQVQ", [
        "d1FwVi1FZ2IzcDRsVW8taw",
    ], "XOV WULPUS Vostrikov"),

    # 17. Vadimgest visibility (Vlad Dombrovsky)
    ("eHVRMWFSNWxCa1JKeC1BSQ", [
        "eWhfdnhmMGg4b1ptbHV4dQ",
    ], "Vadimgest visibility"),

    # 18. Tyoma memcoin CH access
    ("dnUtMEJtbk5ZZlhYN3NURw", [
        "SkpfV21HM3hmNmhHcDRJUQ",
    ], "Tyoma memcoin CH"),

    # 19. Google security alerts
    ("WFc3eVpSOTBmSUpsbWxXSw", [
        "SEtlbW14UjNhdnJzTUdpcg",
    ], "Google security alerts"),

    # 20. Babel Street partnerships (Riff)
    ("V21kMEhCd0NGLTNfM3V6cg", [
        "SW5lYnRmLUdKNkFPbGhrVQ",
    ], "Babel Street partnerships"),

    # 21. Dima IC buyer push (DoD/IC)
    ("NnFCYlBoQm9UQ1NLUU9ZdQ", [
        "bHVBQnVGNlQ5a1lUMGhfNw",
    ], "Dima IC buyer push"),

    # 22. Mossad reactivation (extend prior backfill keeper)
    ("eVQ0d3A4RjR0TjhjSmpycQ", [
        "YWFfTzV5dUlIYVBMUEF1Vw",
    ], "Mossad reactivation (extend)"),

    # 23. ENGY group tags reply
    ("REFJZzYwQUtpckVDTFBPNA", [
        "UHdCQ094VDBfVEk2RmRYZQ",
    ], "ENGY group tags reply"),

    # 24. Apple sourcing explanation
    ("OUt4cVJDLU5vdkVYdjZVag", [
        "R29CWkxWejJSb2oxNERHRw",
    ], "Apple sourcing"),

    # 25. LeadBridge pricing send (extend prior backfill keeper)
    ("T29VS0czQUVPZDd1cERoWQ", [
        "ZW44aEp1ckZldTNnRDE2ZA",
    ], "LeadBridge pricing (extend)"),
]


# Google Tasks notes limit: 8192 chars. Keep keeper notes under 7000 to leave
# room for frontmatter + future appends.
NOTES_BUDGET = 7000
PER_MERGEE_BUDGET = 600  # truncate each mergee's body summary to this


def _summarize_merge_body(body: str, budget: int) -> str:
    """Trim a mergee body so it fits in the keeper without blowing the limit."""
    body = (body or "").strip()
    if body.startswith("#result"):
        body = body[len("#result"):].lstrip()
    if not body:
        return "(empty body)"
    if len(body) <= budget:
        return body
    return body[:budget].rstrip() + f"\n\n_(…truncated, original was {len(body)} chars)_"


def main():
    lid = _list_id()
    all_tasks = {t.id: t for t in list_tasks(include_completed=True)}

    cards_collapsed = 0
    for keeper_id, merge_ids, label in MERGES:
        keeper = all_tasks.get(keeper_id)
        if keeper is None:
            print(f"SKIP {label!r}: keeper {keeper_id} not found", file=sys.stderr)
            continue

        new_body = (keeper.body or "").rstrip()
        # Keeper body itself may already be huge (especially if it survived
        # earlier backfill). Truncate aggressively if so.
        if len(new_body) > NOTES_BUDGET // 2:
            new_body = new_body[:NOTES_BUDGET // 2].rstrip() + "\n\n_(…earlier content truncated)_"

        for mid in merge_ids:
            mtask = all_tasks.get(mid)
            if mtask is None:
                print(f"  WARN: merge target {mid} not found, skipping",
                      file=sys.stderr)
                continue
            if mtask.status not in ("pending",):
                print(f"  WARN: {mid} already status={mtask.status}, skipping",
                      file=sys.stderr)
                continue
            ts_iso = mtask.completed_at or mtask.created or ""
            try:
                ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                stamp = ts.strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                stamp = "unknown time"

            addition = _summarize_merge_body(mtask.body or "", PER_MERGEE_BUDGET)
            new_section = (
                f"\n\n## Update {stamp}"
                f"\n_(merged from `{mid}` — {mtask.title!r})_\n\n"
                f"{addition}"
            )
            # Hard stop if we'd exceed the budget — drop the body, keep the title
            if len(new_body) + len(new_section) > NOTES_BUDGET:
                short_section = (
                    f"\n\n## Update {stamp}"
                    f"\n_(merged from `{mid}` — {mtask.title!r}; body omitted, budget reached)_"
                )
                new_body += short_section
            else:
                new_body += new_section

        keeper.body = new_body.strip()
        keeper.result_status = "new"
        keeper.status = "pending"
        try:
            update_task_notes(keeper.id, keeper.to_notes(), list_id=lid)
        except Exception as e:
            print(f"FAIL {label!r}: keeper update failed ({e}); leaving cluster intact",
                  file=sys.stderr)
            continue

        for mid in merge_ids:
            mtask = all_tasks.get(mid)
            if mtask is None or mtask.status != "pending":
                continue
            try:
                complete_task(mid, list_id=lid)
                cards_collapsed += 1
            except Exception as e:
                print(f"  WARN: failed to complete {mid}: {e}",
                      file=sys.stderr)

        print(f"OK   {label}: keeper={keeper_id}, merged={len(merge_ids)}, "
              f"final_body={len(keeper.body)}c")

    print()
    print(f"Total cards collapsed: {cards_collapsed}")
    print(f"Total clusters: {len(MERGES)}")


if __name__ == "__main__":
    main()
