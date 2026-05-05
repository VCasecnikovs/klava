#!/usr/bin/env python3
"""
Cloud-portability audit.

Walks Klava queue history and session transcripts and classifies each
piece of work by what physical resources it touched. Produces a report
on what fraction of Klava's actual work is cloud-portable today.

Buckets:
  CLOUD_NATIVE     — APIs, cloud services, web. Already location-agnostic.
  REPO_FS          — Reads/writes under ~/Documents/GitHub/. Fixable via cloud-mirror + git.
  OBSIDIAN         — Reads/writes under ~/Documents/MyBrain/. Fixable via Obsidian Sync.
  CHROME_MCP       — Browser automation. Fixable: cloud Chrome.
  MACOS_GUI        — Typora/Finder/peekaboo opens on the local desktop. Mostly avoidable.
  APPLE_ID         — iMessage / Hlopya — physically tied to laptop hardware.
  UNCLASSIFIED     — Couldn't tell.

Reads:
  - /tmp/task-consumer.log  (executed Klava queue tasks)
  - ~/.claude/projects/-/*.jsonl  (session transcripts with tool usage)
  - gateway/sessions/registry.jsonl  (session metadata: cron vs dashboard)
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REPO = HOME / "Documents" / "GitHub" / "claude"
PROJECTS = HOME / ".claude" / "projects" / "-"
REGISTRY = REPO / "gateway" / "sessions" / "registry.jsonl"
CONSUMER_LOG = Path("/tmp/task-consumer.log")
OUT = REPO / "drafts" / "cloud-portability-report.md"

# Classification rules. Order matters — first match wins per session.
# Each session can be tagged with multiple buckets, the "most-binding" wins.

BUCKET_PRIORITY = [
    "APPLE_ID",      # If it touches Apple-ID hardware, that's the binding constraint
    "MACOS_GUI",     # GUI app on a specific machine
    "CHROME_MCP",    # Browser automation
    "OBSIDIAN",      # Vault writes
    "REPO_FS",       # Repo reads/writes
    "CLOUD_NATIVE",  # Default if only cloud-y things touched
]

KEYWORD_RULES = {
    "APPLE_ID": [
        r"~/Library/Messages",
        r"chat\.db",
        r"hlopya",
        r"granola",
        r"dayflow",
        r"imessage",
    ],
    "MACOS_GUI": [
        r"\bopen -a ",
        r"\bopen \"/Applications",
        r"typora",
        r"peekaboo",
        r"osascript",
        r"\bFinder\b",
        r"pbcopy",
        r"pbpaste",
    ],
    "CHROME_MCP": [
        r"mcp__browser__",
        r"chrome.*extension",
    ],
    "OBSIDIAN": [
        r"Documents/MyBrain",
        r"MyBrain/",
    ],
    "REPO_FS": [
        r"Documents/GitHub/",
        r"~/Documents/GitHub",
        r"/Users/[^/]+/Documents/GitHub",
    ],
}

# Keywords for classifying queue task titles + bodies (no transcript available)
TITLE_RULES = {
    "APPLE_ID": [
        r"\biMessage\b",
        r"\bHlopya\b",
        r"\bGranola\b",
        r"\bDayflow\b",
        r"call recording",
        r"call transcript",
    ],
    "MACOS_GUI": [
        r"\bTypora\b",
        r"\bFinder\b",
        r"open in Typora",
        r"\bpeekaboo\b",
        r"screenshot the (app|desktop)",
        r"automate.*Mac UI",
    ],
    "CHROME_MCP": [
        r"capture screenshots?",
        r"verify.*UI",
        r"test.*dashboard.*UI",
        r"browse.*\bChrome\b",
        r"chrome[- ]mcp",
        r"render.*HTML",
        r"\bone[- ]pager\b.*screenshot",
    ],
    "OBSIDIAN": [
        r"\bObsidian\b",
        r"MyBrain",
        r"deal note",
        r"person note",
        r"Topics?/",
        r"People/",
        r"Vox Lab/Deals",
    ],
    "REPO_FS": [
        r"\brestart\b.*scheduler",
        r"\bdeploy\b",
        r"\bcommit\b",
        r"git push",
        r"cron-scheduler",
        r"webhook[- ]server",
        r"executor\.run",
        r"add (TG )?alert",
        r"circuit breaker",
        r"\bself-evolve\b",
        r"add.*feature",
        r"build.*(index|filter|pipeline)",
        r"build telegram",
    ],
}


def classify_text(text: str, rules: dict) -> set[str]:
    hits = set()
    for bucket, patterns in rules.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                hits.add(bucket)
                break
    return hits


def pick_dominant(buckets: set[str]) -> str:
    if not buckets:
        return "CLOUD_NATIVE"
    for b in BUCKET_PRIORITY:
        if b in buckets:
            return b
    return "CLOUD_NATIVE"


def classify_session_jsonl(path: Path) -> tuple[str, dict]:
    """Walk a session JSONL, look at every tool_use input, classify."""
    bucket_hits = set()
    tool_counts = Counter()
    first_user = None
    try:
        with open(path) as f:
            for line in f:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Capture first user prompt for the human-readable line
                if first_user is None and msg.get("type") == "user":
                    content = msg.get("message", {}).get("content")
                    if isinstance(content, str):
                        first_user = content[:200]
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                first_user = block.get("text", "")[:200]
                                break

                # Tool calls live inside assistant messages
                if msg.get("type") == "assistant":
                    content = msg.get("message", {}).get("content", [])
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            tool_counts[name] += 1
                            blob = json.dumps(block.get("input", {}))
                            bucket_hits |= classify_text(blob, KEYWORD_RULES)
                            bucket_hits |= classify_text(name, KEYWORD_RULES)
    except FileNotFoundError:
        pass

    return pick_dominant(bucket_hits), {
        "buckets_seen": sorted(bucket_hits),
        "tools": dict(tool_counts.most_common(8)),
        "first_user": first_user or "",
    }


def classify_queue_titles() -> list[tuple[str, str, str]]:
    """Classify Klava queue tasks from the full Google Tasks dump."""
    src = Path("/tmp/klava_queue_history.json")
    out = []
    if not src.exists():
        return out
    tasks = json.loads(src.read_text())
    for t in tasks:
        # Only real queue tasks, not result cards or proposals
        if t.get("type") != "task":
            continue
        title = t.get("title", "")
        body = t.get("body", "")
        text = f"{title}\n{body}"
        bucket = pick_dominant(classify_text(text, TITLE_RULES))
        out.append((bucket, title, t.get("source", "")))
    return out


def main():
    print("Walking session transcripts...")
    session_files = sorted(PROJECTS.glob("*.jsonl"))
    session_results = []
    for sf in session_files:
        bucket, meta = classify_session_jsonl(sf)
        session_results.append((sf.name, bucket, meta))

    print("Walking Klava queue history...")
    queue_results = classify_queue_titles()

    # Aggregate
    session_dist = Counter(r[1] for r in session_results)
    queue_dist = Counter(r[0] for r in queue_results)

    n_sess = len(session_results) or 1
    n_q = len(queue_results) or 1

    # Markdown report
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        f.write("# Cloud-portability audit\n\n")
        f.write(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n\n")
        f.write(f"Sessions analyzed: **{n_sess}** transcripts (`~/.claude/projects/-/`)\n\n")
        f.write(f"Klava queue tasks analyzed: **{n_q}** (from `/tmp/task-consumer.log`)\n\n")

        f.write("## Session-level breakdown\n\n")
        f.write("Each session is bucketed by the most-binding resource it touched.\n\n")
        f.write("| Bucket | Count | % | Cloud-portable? |\n")
        f.write("|---|---:|---:|---|\n")
        portable_map = {
            "CLOUD_NATIVE": "Already cloud",
            "REPO_FS": "Yes — git mirror",
            "OBSIDIAN": "Yes — Obsidian Sync",
            "CHROME_MCP": "Yes — cloud Chrome",
            "MACOS_GUI": "Mostly avoidable",
            "APPLE_ID": "No (laptop sensor)",
        }
        for bucket in BUCKET_PRIORITY + ["UNCLASSIFIED"]:
            cnt = session_dist.get(bucket, 0)
            if cnt == 0:
                continue
            pct = 100 * cnt / n_sess
            f.write(f"| {bucket} | {cnt} | {pct:.0f}% | {portable_map.get(bucket, '?')} |\n")
        f.write("\n")

        f.write("## Klava queue task breakdown\n\n")
        f.write("| Bucket | Count | % | Cloud-portable? |\n")
        f.write("|---|---:|---:|---|\n")
        for bucket in BUCKET_PRIORITY + ["UNCLASSIFIED"]:
            cnt = queue_dist.get(bucket, 0)
            if cnt == 0:
                continue
            pct = 100 * cnt / n_q
            f.write(f"| {bucket} | {cnt} | {pct:.0f}% | {portable_map.get(bucket, '?')} |\n")
        f.write("\n")

        # Aggregate score
        portable_sess = sum(
            session_dist.get(b, 0) for b in ("CLOUD_NATIVE", "REPO_FS", "OBSIDIAN", "CHROME_MCP")
        )
        portable_q = sum(
            queue_dist.get(b, 0) for b in ("CLOUD_NATIVE", "REPO_FS", "OBSIDIAN", "CHROME_MCP")
        )
        f.write("## Headline numbers\n\n")
        f.write(f"- **Sessions cloud-portable (with plumbing):** {portable_sess}/{n_sess} = **{100*portable_sess/n_sess:.0f}%**\n")
        f.write(f"- **Queue tasks cloud-portable (with plumbing):** {portable_q}/{n_q} = **{100*portable_q/n_q:.0f}%**\n")
        f.write(f"- **Hard laptop-local (APPLE_ID + MACOS_GUI):** "
                f"{session_dist.get('APPLE_ID',0)+session_dist.get('MACOS_GUI',0)}/{n_sess} sessions, "
                f"{queue_dist.get('APPLE_ID',0)+queue_dist.get('MACOS_GUI',0)}/{n_q} queue tasks\n\n")

        f.write("## Sample of laptop-local sessions (need closer look)\n\n")
        for name, bucket, meta in session_results:
            if bucket in ("APPLE_ID", "MACOS_GUI"):
                f.write(f"- `{name[:8]}…` **{bucket}** — tools: {list(meta['tools'])[:5]}\n")
                if meta["first_user"]:
                    f.write(f"  > {meta['first_user'][:160]}\n")
        f.write("\n")

        f.write("## Sample of laptop-local queue tasks\n\n")
        for bucket, title, source in queue_results:
            if bucket in ("APPLE_ID", "MACOS_GUI"):
                f.write(f"- **{bucket}** ({source}) — {title}\n")
        f.write("\n")

        # Per-source breakdown
        f.write("## Queue tasks by spawn source\n\n")
        f.write("| Source | Total | Cloud-portable | Hard laptop-local |\n|---|---:|---:|---:|\n")
        per_source = defaultdict(lambda: Counter())
        for bucket, _title, source in queue_results:
            per_source[source][bucket] += 1
        for src_name, dist in sorted(per_source.items(), key=lambda x: -sum(x[1].values())):
            total = sum(dist.values())
            portable = sum(dist.get(b, 0) for b in ("CLOUD_NATIVE", "REPO_FS", "OBSIDIAN", "CHROME_MCP"))
            hard = sum(dist.get(b, 0) for b in ("APPLE_ID", "MACOS_GUI"))
            f.write(f"| {src_name or '(unknown)'} | {total} | {portable} ({100*portable/total:.0f}%) | {hard} |\n")
        f.write("\n")

        f.write("## Tool usage histogram (sessions)\n\n")
        all_tools = Counter()
        for _, _, meta in session_results:
            all_tools.update(meta["tools"])
        f.write("| Tool | Calls |\n|---|---:|\n")
        for tool, n in all_tools.most_common(20):
            f.write(f"| {tool} | {n} |\n")
        f.write("\n")

    print(f"\nReport written: {OUT}")
    print(f"\nSession distribution: {dict(session_dist)}")
    print(f"Queue distribution: {dict(queue_dist)}")


if __name__ == "__main__":
    main()
