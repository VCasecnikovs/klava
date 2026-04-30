"""Evidence-driven auto-close for [RESULT] cards.

Why this module exists
----------------------
Klava's Deck accumulates [RESULT] cards faster than the user can ack
them. The bulk of the noise is "watch / status / awaiting" cards where
there's no explicit ack moment ("Reply Vasilii Tiselko - call time
today" — once the reply is sent, the card just lingers).

Time-based auto-close ("Apr 21 deadline passed → cancel") is unsafe
because Klava doesn't know if the action was actually done.

Evidence-driven auto-close is the safe alternative: if vadimgest
contains a hit on the relevant person/topic in messaging sources
*after* the card was created, the user clearly acted on it. Close.

Architecture
------------
1. extract_target() — tiny haiku LLM call turns a card title+body into a
   structured query: {action, person, search_terms, channels}. Cached on
   disk by (card_id, title-hash) so repeated runs over the same card
   don't repeat the LLM call.

2. find_evidence() — runs FTS5 query against vadimgest's index DB,
   restricted to messaging sources + filtered by date extracted from the
   doc title (signal/telegram/whatsapp/imessage/gmail/hlopya). Returns a
   list of evidence hits with their dates.

3. close_if_evidenced() — orchestrator. If find_evidence() returns
   anything dated *after* card.created, complete_task with an audit note.

The whole thing is gated by --apply on the runner. Default is dry-run.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import List, Optional

VADIMSEARCH_DB = Path(os.path.expanduser("~/.vadimsearch/index.db"))
EXTRACT_CACHE_DIR = Path("/tmp/klava-evidence-extract-cache")
EXTRACT_CACHE_TTL_SECONDS = 7 * 24 * 3600

# Sources that count as evidence of user action. Heartbeat / claude /
# obsidian / browser are EXCLUDED — Klava's own writes there don't prove
# anything happened.
EVIDENCE_SOURCES = (
    "signal",
    "telegram",
    "whatsapp",
    "imessage",
    "gmail",
    "hlopya",
    "calendar",
    "github",
)

import shutil as _shutil
CLAUDE_CLI = _shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
EXTRACT_TIMEOUT_S = 60
EXTRACT_MODEL = "haiku"
EXTRACT_BODY_CAP = 600

EXTRACT_PROMPT = """You are an evidence-extraction classifier. I'll show you a Klava task card title and body. Output a single JSON object describing how to find evidence the user acted on this card. No prose, no markdown — just the JSON.

Schema:
{
  "actionable": true|false,        // false if card is informational (digest, observation) with no follow-up; true if user is expected to do something
  "person": "<full person name>" | null,  // primary person/org the card concerns
  "search_terms": ["term1", "term2"],     // 1-3 specific phrases that would appear in messaging if the action was performed; NEVER include generic words like "Klava" / "follow up" / "pending"
  "channels": ["signal", "telegram", "whatsapp", "imessage", "gmail", "hlopya", "calendar", "github"]  // only the relevant ones; default to ["signal","telegram","whatsapp","imessage","gmail"] if unsure
}

CARD TITLE:
{title}

CARD BODY:
{body}

JSON:"""


@dataclass
class Target:
    actionable: bool
    person: Optional[str]
    search_terms: List[str]
    channels: List[str]


@dataclass
class Evidence:
    source: str
    title: str
    date: str  # ISO YYYY-MM-DD
    excerpt: str


# ------------------------------------------------------------------
#  Step 1: extract a target spec from the card
# ------------------------------------------------------------------

def _extract_cache_path(card_id: str, title: str, body: str) -> Path:
    h = sha256()
    h.update(card_id.encode("utf-8"))
    h.update(b"|")
    h.update(title.encode("utf-8"))
    h.update(b"|")
    h.update((body or "").encode("utf-8"))
    return EXTRACT_CACHE_DIR / f"{h.hexdigest()[:32]}.json"


def _load_cached_target(cache_path: Path) -> Optional[Target]:
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
        if time.time() - data.get("ts", 0) > EXTRACT_CACHE_TTL_SECONDS:
            return None
        spec = data.get("target") or {}
        return Target(
            actionable=bool(spec.get("actionable", True)),
            person=spec.get("person"),
            search_terms=list(spec.get("search_terms") or []),
            channels=list(spec.get("channels") or []),
        )
    except Exception:
        return None


def _save_cached_target(cache_path: Path, target: Target) -> None:
    try:
        EXTRACT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "ts": time.time(),
            "target": {
                "actionable": target.actionable,
                "person": target.person,
                "search_terms": target.search_terms,
                "channels": target.channels,
            },
        }))
    except Exception as e:
        print(f"[evidence_closer] cache save failed: {e}", file=sys.stderr)


def extract_target(
    card_id: str, title: str, body: str = "",
    timeout_s: int = EXTRACT_TIMEOUT_S, model: str = EXTRACT_MODEL,
) -> Optional[Target]:
    """Use a haiku LLM call to extract a structured evidence-search spec
    from the card's title + body. Cached on disk for 7 days.

    Returns None if the LLM call fails or output is unparseable —
    callers should treat that as "skip this card".
    """
    cache_path = _extract_cache_path(card_id, title, body or "")
    cached = _load_cached_target(cache_path)
    if cached is not None:
        return cached

    if not Path(CLAUDE_CLI).exists():
        return None

    short_body = (body or "")[:EXTRACT_BODY_CAP]
    prompt = EXTRACT_PROMPT.replace("{title}", title).replace("{body}", short_body)

    env = dict(os.environ)
    env.pop("CLAUDECODE", None)

    try:
        result = subprocess.run(
            [CLAUDE_CLI, "--print", "--model", model, prompt],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"[evidence_closer] extract subprocess failed: {e}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(f"[evidence_closer] claude exit {result.returncode}: {result.stderr[:200]}",
              file=sys.stderr)
        return None

    raw = (result.stdout or "").strip()
    # Take the first {...} block in case the model adds a comment.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        spec = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    target = Target(
        actionable=bool(spec.get("actionable", True)),
        person=spec.get("person") or None,
        search_terms=[s for s in (spec.get("search_terms") or []) if s and isinstance(s, str)],
        channels=[c for c in (spec.get("channels") or []) if c in EVIDENCE_SOURCES],
    )
    _save_cached_target(cache_path, target)
    return target


# ------------------------------------------------------------------
#  Step 2: find evidence in vadimgest
# ------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _extract_doc_date(title: str) -> Optional[str]:
    """vadimgest titles end with `... YYYY-MM-DD` for messaging sources."""
    if not title:
        return None
    m = _DATE_RE.search(title)
    return m.group(1) if m else None


def _fts_query(terms: List[str]) -> str:
    """Build an FTS5 query: AND of phrases. Always quote each term so
    that FTS5 operator characters (`-`, `*`, `:`, parens) don't get
    parsed as syntax — `O-1` becomes the phrase `"O-1"` rather than
    `O AND NOT 1`.
    """
    parts: List[str] = []
    for t in terms:
        t = (t or "").strip()
        if not t:
            continue
        t = t.replace('"', "").replace("'", "")
        if not t:
            continue
        parts.append(f'"{t}"')
    return " AND ".join(parts) if parts else ""


def find_evidence(
    target: Target,
    since_iso: str,
    db_path: Optional[Path] = None,
    limit: int = 25,
) -> List[Evidence]:
    """Find vadimgest hits matching `target` dated >= since_iso (date part).

    Returns a list of Evidence rows, deduped by (source, date, title).
    """
    # Resolve db_path at call time (not import time) so tests can rebind
    # `VADIMSEARCH_DB` via monkeypatch.
    if db_path is None:
        db_path = VADIMSEARCH_DB
    if not target.search_terms or not Path(db_path).exists():
        return []

    channels = target.channels or list(EVIDENCE_SOURCES)
    query = _fts_query(target.search_terms)
    if not query:
        return []

    since_date = since_iso[:10]  # YYYY-MM-DD
    placeholders = ",".join("?" * len(channels))

    # Doc titles encode the date suffix lexicographically (`... 2026-04-29`)
    # so ORDER BY title DESC reliably surfaces newest docs first. Without
    # an ORDER BY, FTS5 returns by rank and the LIMIT prunes recent docs
    # that would have passed the date filter — silent false-negative.
    sql = f"""
        SELECT source, title, content
        FROM docs
        WHERE source IN ({placeholders})
        AND docs MATCH ?
        ORDER BY title DESC
        LIMIT ?
    """

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(sql, [*channels, query, limit]).fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"[evidence_closer] sqlite query failed: {e}", file=sys.stderr)
        return []

    out: List[Evidence] = []
    seen = set()
    for source, title, content in rows:
        date = _extract_doc_date(title or "")
        if not date or date < since_date:
            continue
        key = (source, date, title)
        if key in seen:
            continue
        seen.add(key)
        excerpt = (content or "").strip().replace("\n", " ")[:160]
        out.append(Evidence(source=source, title=title, date=date, excerpt=excerpt))
    return out


# ------------------------------------------------------------------
#  Step 3: orchestration
# ------------------------------------------------------------------

@dataclass
class ClosureDecision:
    card_id: str
    card_title: str
    decision: str  # "close" | "skip-no-target" | "skip-no-evidence" | "skip-not-actionable"
    target: Optional[Target] = None
    evidence: Optional[List[Evidence]] = None
    note: str = ""


def evaluate_card(card) -> ClosureDecision:
    """Decide whether to close `card` based on evidence.

    `card` is a tasks.queue.Task (or any object with .id, .title, .body, .created).
    """
    title = card.title or ""
    body = card.body or ""
    created = card.created or ""

    if not created:
        return ClosureDecision(
            card_id=card.id, card_title=title,
            decision="skip-no-evidence",
            note="card has no `created` timestamp; cannot bound evidence search",
        )

    target = extract_target(card.id, title, body)
    if target is None:
        return ClosureDecision(
            card_id=card.id, card_title=title,
            decision="skip-no-target",
            note="LLM extract failed or unavailable",
        )

    if not target.actionable:
        return ClosureDecision(
            card_id=card.id, card_title=title, target=target,
            decision="skip-not-actionable",
            note="LLM marked card as not actionable (digest/observation)",
        )

    hits = find_evidence(target, created)
    if not hits:
        return ClosureDecision(
            card_id=card.id, card_title=title, target=target,
            decision="skip-no-evidence",
            note=f"no vadimgest hits in {target.channels} since {created[:10]}",
        )

    summary = "; ".join(
        f"{h.source}@{h.date}: {h.excerpt[:80]}" for h in hits[:3]
    )
    return ClosureDecision(
        card_id=card.id, card_title=title,
        target=target, evidence=hits,
        decision="close",
        note=f"evidence found in {len(hits)} doc(s): {summary}",
    )
