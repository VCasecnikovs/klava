"""GTasks-backed task queue for Klava.

Most state lives in GTasks notes as YAML frontmatter. One exception:
rejected [PROPOSAL] cards are appended to `tasks/rejected_proposals.jsonl`
so the idle-research loop can see what the user already shot down and avoid
resurfacing the same ideas tick after tick.
"""

import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Dict

from . import snapshot as _snapshot

# Config - loaded from gateway config.yaml, falls back to env vars
_config_mod = None

def _config():
    """Lazy-load gateway config module (imported once, cached).

    Swallowing only ImportError lets genuine config-parse failures (bad
    YAML, missing keys) propagate instead of silently falling back to env
    vars. A fresh install without PyYAML now surfaces the actual cause
    rather than masking it as `empty tasklistId` downstream.
    """
    global _config_mod
    if _config_mod is not None:
        return _config_mod
    try:
        import sys
        gw = str(Path(__file__).resolve().parent.parent / "gateway")
        if gw not in sys.path:
            sys.path.insert(0, gw)
        from lib import config
        _config_mod = config
        return config
    except ImportError as e:
        import sys
        print(
            f"[tasks.queue] gateway config module unavailable, falling back to env: {e}",
            file=sys.stderr,
        )
        return None


def _gog_bin() -> str:
    """Locate the gog binary: config → $GOG_BIN env → ~/bin/gog → PATH."""
    c = _config()
    if c:
        try:
            path = c.google_cli()
            if path:
                return path
        except Exception:
            pass
    env_bin = os.environ.get("GOG_BIN")
    if env_bin:
        return env_bin
    fallback = Path.home() / "bin" / "gog"
    if fallback.exists():
        return str(fallback)
    return "gog"

def _account() -> str:
    c = _config()
    if c:
        return c.email() or ""
    return os.environ.get("GTASKS_ACCOUNT", "")

def _list_id() -> str:
    c = _config()
    if c:
        tasks_cfg = c.load().get("tasks", {})
        list_name = tasks_cfg.get("gtasks_list")
        lists = c.google_tasks_lists()
        if list_name and list_name in lists:
            return lists[list_name]
        if lists:
            return next(iter(lists.values()))
    return os.environ.get("GTASKS_LIST_ID", "")
STALE_TIMEOUT_MINUTES = 60

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Parse YAML frontmatter from text.

    Returns (metadata_dict, body_text).
    If no valid frontmatter found, returns ({}, original_text).
    """
    if not text or not text.strip().startswith("---"):
        return {}, text

    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    meta = {}
    for line in lines[1:end_idx]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ": " in line:
            key, _, value = line.partition(": ")
            meta[key.strip()] = value.strip()
        elif line.endswith(":"):
            meta[line[:-1].strip()] = ""

    body = "\n".join(lines[end_idx + 1:]).strip()
    return meta, body


def _extract_plan_from_body(body: str) -> Optional[str]:
    """Extract `## Plan\\n...` block from a body string, up to the next `## ` header."""
    if not body or "## Plan\n" not in body:
        return None
    after = body.split("## Plan\n", 1)[1]
    next_hdr = after.find("\n## ")
    return (after if next_hdr == -1 else after[:next_hdr]).strip() or None


def build_frontmatter(fields: Dict[str, str]) -> str:
    """Build YAML frontmatter string from dict."""
    lines = ["---"]
    for key, value in fields.items():
        if value is not None and value != "":
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


@dataclass
class Task:
    """A task from the Klava GTasks queue.

    Extended schema (backward-compatible):
      - type: task | proposal | signal | brief | result
      - shape: reply | approve | review | decide | act | read
      - dispatch: chat | session | self
      - criticality: 0-100 numeric score for Deck sort
      - mode_tags: comma-separated tags (e.g. "deal,xov")
      - proposal_status: pending | approved | rejected (for [PROPOSAL] cards)
      - proposal_plan: multi-line plan body (lives in .body, not frontmatter, for readability)
      - result_of: parent task ID this [RESULT] card reports on
      - result_status: new | seen | archived (Deck read-state for [RESULT] cards)
      - source_gtask_id: identifier of the external origin (source GTask,
        dashboard request, heartbeat conversation group) that spawned this
        Klava row. Used by the consumer to dedup overlapping duplicates so
        two Klava rows pointing at the same origin can't both execute.
      - execute_after: ISO datetime; consumer must skip the task until that
        moment has passed. Prevents the 5-minute re-queue storm that fired
        8 duplicate [ALERT] Result cards on 2026-04-20.
    """
    id: str
    title: str
    status: str = "pending"       # pending, running, done, failed, approved, skipped
    priority: str = "medium"      # high, medium, low
    source: str = "manual"        # chat, heartbeat, self, manual, feed, idle_research, pulse, consumer
    session_id: Optional[str] = None
    created: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    parent_id: Optional[str] = None
    body: str = ""
    gtask_status: str = "needsAction"
    # --- extended schema (v2) ---
    type: str = "task"             # task | proposal | signal | brief | result
    shape: Optional[str] = None    # reply | approve | review | decide | act | read
    dispatch: Optional[str] = None # chat | session | self
    criticality: Optional[int] = None  # 0-100
    mode_tags: Optional[str] = None    # "deal,xov"
    proposal_status: Optional[str] = None  # pending | approved | rejected
    proposal_plan: Optional[str] = None    # multi-line plan (optional; usually lives in body)
    result_of: Optional[str] = None        # parent task ID for [RESULT] cards
    result_status: Optional[str] = None    # new | seen | archived
    source_gtask_id: Optional[str] = None  # external origin id for consumer dedup
    execute_after: Optional[str] = None    # ISO datetime; consumer skips until after
    resume_session_id: Optional[str] = None  # session to resume when executing (continue-in-session)
    continue_mode: Optional[str] = None    # execute | research-more | follow-up — continuation intent

    @classmethod
    def from_gtask(cls, gtask: dict) -> "Task":
        """Parse a GTasks API item into a Task."""
        notes = gtask.get("notes") or ""
        frontmatter, body = parse_frontmatter(notes)

        gtask_status = gtask.get("status", "needsAction")
        status = frontmatter.get("status", "pending")
        if gtask_status == "completed":
            status = "done"

        # criticality: numeric in frontmatter, parse best-effort
        crit_raw = frontmatter.get("criticality")
        criticality = None
        if crit_raw:
            try:
                criticality = int(crit_raw)
            except (ValueError, TypeError):
                criticality = None

        return cls(
            id=gtask["id"],
            title=gtask.get("title", ""),
            status=status,
            priority=frontmatter.get("priority", "medium"),
            source=frontmatter.get("source", "manual"),
            session_id=frontmatter.get("session_id"),
            created=frontmatter.get("created"),
            started_at=frontmatter.get("started_at"),
            completed_at=frontmatter.get("completed_at"),
            result=frontmatter.get("result"),
            parent_id=gtask.get("parent"),
            body=body,
            gtask_status=gtask_status,
            type=frontmatter.get("type", "task"),
            shape=frontmatter.get("shape") or None,
            dispatch=frontmatter.get("dispatch") or None,
            criticality=criticality,
            mode_tags=frontmatter.get("mode_tags") or None,
            proposal_status=frontmatter.get("proposal_status") or None,
            proposal_plan=(
                frontmatter.get("proposal_plan")
                or _extract_plan_from_body(body)
                or None
            ),
            result_of=frontmatter.get("result_of") or None,
            result_status=frontmatter.get("result_status") or None,
            source_gtask_id=frontmatter.get("source_gtask_id") or None,
            execute_after=frontmatter.get("execute_after") or None,
            resume_session_id=frontmatter.get("resume_session_id") or None,
            continue_mode=frontmatter.get("continue_mode") or None,
        )

    def to_notes(self) -> str:
        """Generate full notes string (frontmatter + body).

        Only writes non-default fields so old consumers still parse cleanly.
        """
        fields = {
            "status": self.status,
            "priority": self.priority,
            "source": self.source,
        }
        # Always write type if non-default, so readers know the card's role
        if self.type and self.type != "task":
            fields["type"] = self.type
        if self.shape:
            fields["shape"] = self.shape
        if self.dispatch:
            fields["dispatch"] = self.dispatch
        if self.criticality is not None:
            fields["criticality"] = str(self.criticality)
        if self.mode_tags:
            fields["mode_tags"] = self.mode_tags
        if self.proposal_status:
            fields["proposal_status"] = self.proposal_status
        if self.result_of:
            fields["result_of"] = self.result_of
        if self.result_status:
            fields["result_status"] = self.result_status
        if self.source_gtask_id:
            fields["source_gtask_id"] = self.source_gtask_id
        if self.execute_after:
            fields["execute_after"] = self.execute_after
        if self.resume_session_id:
            fields["resume_session_id"] = self.resume_session_id
        if self.continue_mode:
            fields["continue_mode"] = self.continue_mode
        if self.session_id:
            fields["session_id"] = self.session_id
        if self.created:
            fields["created"] = self.created
        if self.started_at:
            fields["started_at"] = self.started_at
        if self.completed_at:
            fields["completed_at"] = self.completed_at
        if self.result:
            fields["result"] = self.result

        fm = build_frontmatter(fields)
        body = self.body or ""
        # If this is a proposal and proposal_plan is set but not embedded in body, append it.
        if self.type == "proposal" and self.proposal_plan and self.proposal_plan not in body:
            body = (body + ("\n\n" if body else "") + "## Plan\n" + self.proposal_plan).strip()
        if body:
            return f"{fm}\n{body}"
        return fm


def _run_gog(*args: str, timeout: int = 30) -> str:
    """Run a gog command and return stdout."""
    cmd = [_gog_bin()] + list(args) + ["-a", _account()]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"gog {' '.join(args[:3])} failed: {result.stderr[:200]}")
    return result.stdout


def list_tasks(list_id: str = None, include_completed: bool = False) -> List[Task]:
    """Read all tasks from the Klava GTasks list via the snapshot module.

    The snapshot bootstraps once with one full `gog tasks list` call, then
    refreshes incrementally via `--updated-min` deltas. Writes
    (create/update/complete/cancel/postpone) inline-mutate the snapshot so
    callers see their own changes immediately without burning an API call.
    """
    lid = list_id or _list_id()
    items = _snapshot.get_all(lid, include_completed=include_completed)
    return [Task.from_gtask(item) for item in items]


def update_task_notes(task_id: str, notes: str, list_id: str = None) -> None:
    """Update task notes in GTasks."""
    lid = list_id or _list_id()
    _run_gog("tasks", "update", lid, task_id, f"--notes={notes}")
    _snapshot.apply_local_mutation(lid, task_id, notes=notes)


def complete_task(task_id: str, list_id: str = None) -> None:
    """Mark task as completed in GTasks."""
    lid = list_id or _list_id()
    _run_gog("tasks", "done", lid, task_id)
    _snapshot.apply_local_complete(lid, task_id)


def cancel_task(task_id: str, list_id: str = None) -> None:
    """Mark task as `[CANCELLED]` — user decided not to do it. Preserves title
    prefix so the Deck can show a subtle state, then closes the GTask so it
    drops off the queue."""
    lid = list_id or _list_id()
    new_title = None
    try:
        raw = _run_gog("tasks", "get", lid, task_id)
        if raw:
            import json as _json
            data = _json.loads(raw)
            current_title = data.get("title", "")
            if not current_title.startswith("[CANCELLED]"):
                new_title = f"[CANCELLED] {current_title}"
                _run_gog("tasks", "update", lid, task_id,
                         f"--title={new_title}", "-y")
    except Exception:
        pass
    _run_gog("tasks", "done", lid, task_id)
    if new_title:
        _snapshot.apply_local_mutation(lid, task_id, title=new_title)
    _snapshot.apply_local_complete(lid, task_id)


def postpone_task(task_id: str, days: int, list_id: str = None) -> None:
    """Push the GTask `due` date `days` forward from now."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    lid = list_id or _list_id()
    new_due = (_dt.now(_tz.utc) + _td(days=days)).strftime("%Y-%m-%d")
    _run_gog("tasks", "update", lid, task_id, f"--due={new_due}", "-y")
    _snapshot.apply_local_mutation(lid, task_id, due=new_due)


_DEDUP_DASHES = str.maketrans({"\u2014": "-", "\u2013": "-", "\u2212": "-"})


def _normalize_title(title: str) -> str:
    """Fold a title to a canonical form for dedup comparisons.

    NFKC + dash folding + case + whitespace collapse. Catches the common
    drift that produced the 2026-04-23 Wallet-call flood (one session wrote
    `-`, the next wrote `—`, title-hash dedup missed it).
    """
    s = unicodedata.normalize("NFKC", title or "")
    s = s.translate(_DEDUP_DASHES)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


# Topic similarity for [RESULT] card dedup. Heartbeat re-emits the same
# observation each cycle and the consumer adds its own RESULT for the same
# parent — the Deck ends up with multiple cards on one topic. We collapse
# them by mutating the existing card instead of stacking another row.
_TOPIC_FILLER = frozenset({
    # English structural / filler verbs
    "reply", "to", "from", "with", "for", "the", "a", "an", "and", "or",
    "of", "on", "in", "at", "by", "via", "about", "post", "pre", "re",
    "follow", "followup", "ping", "check", "review", "send", "sent",
    "fix", "research", "investigate", "draft", "sign", "confirm", "create",
    "complete", "update", "call", "meet", "meeting", "discuss", "ask",
    "tell", "share", "schedule", "reschedule", "remind", "do", "make",
    "get", "got", "go", "let", "set", "ready", "done", "new", "old",
    "today", "tonight", "now", "asap", "late", "night", "morning",
    "evening", "afternoon", "tomorrow", "yesterday",
    # Russian filler
    "ответить", "напомнить", "проверить", "связаться", "отправить",
    "написать", "позвонить", "уточнить", "подтвердить", "согласовать",
    "обсудить", "сделать", "начать", "закончить", "финиш", "стоп",
    # Channel/source noise
    "tg", "telegram", "signal", "gmail", "email", "whatsapp", "imessage",
    "discord", "slack", "sms",
    # Months (timestamps in titles like "Apr 25" shouldn't drive matches)
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
    "nov", "dec",
    # Timezones / time-format noise
    "eet", "eest", "pst", "pdt", "est", "edt", "utc", "gmt", "msk",
    # Common adjectives that don't carry topic
    "good", "bad", "ok", "yes", "no", "maybe",
})

_TAG_RE = re.compile(r"^\[[A-Za-z][A-Za-z\s]*\]\s*")
# Latin + Russian word characters; digits are tokenized but filtered below.
_TOKEN_RE = re.compile(r"[\wЀ-ӿ]+", re.UNICODE)


def _extract_topic_tokens(title: str) -> set:
    """Pull substantive content tokens from a title for topic comparison.

    Drops [TAG] prefixes (possibly stacked), filler verbs, channel names,
    months, timezones, and pure-digit timestamps. Keeps entity tokens
    (people, companies) which are what actually identify a topic.
    """
    s = unicodedata.normalize("NFKC", title or "")
    s = s.translate(_DEDUP_DASHES)
    while True:
        new = _TAG_RE.sub("", s)
        if new == s:
            break
        s = new
    out = set()
    for tok in _TOKEN_RE.findall(s.lower()):
        if len(tok) <= 1:
            continue
        if tok.isdigit():
            continue
        if tok in _TOPIC_FILLER:
            continue
        out.add(tok)
    return out


def _topic_similar(a: str, b: str, threshold: float = 0.5,
                   min_shared: int = 2) -> bool:
    """True if titles `a` and `b` are about the same topic.

    Token Jaccard ≥ threshold over content tokens AND at least `min_shared`
    tokens in common. Two-token floor avoids false positives where titles
    happen to share one common word like an entity name in unrelated work.
    """
    ta = _extract_topic_tokens(a)
    tb = _extract_topic_tokens(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    if len(shared) < min_shared:
        return False
    union = ta | tb
    if not union:
        return False
    return len(shared) / len(union) >= threshold


def create_task(
    title: str,
    notes: str = "",
    priority: str = "medium",
    source: str = "manual",
    due: Optional[str] = None,
    parent_id: Optional[str] = None,
    list_id: str = None,
    body: str = "",
    # Extended schema (v2) — all optional, backward-compatible.
    type: str = "task",
    shape: Optional[str] = None,
    dispatch: Optional[str] = None,
    criticality: Optional[int] = None,
    mode_tags: Optional[str] = None,
    proposal_status: Optional[str] = None,
    result_of: Optional[str] = None,
    result_status: Optional[str] = None,
    source_gtask_id: Optional[str] = None,
    execute_after: Optional[str] = None,
    resume_session_id: Optional[str] = None,
    continue_mode: Optional[str] = None,
    session_id: Optional[str] = None,
    status: str = "pending",
    dedup: bool = True,
) -> str:
    """Create a new task in the Klava queue. Returns task ID.

    Args:
        body: alias for notes (body takes precedence if both provided)
        dedup: If True (default), refuse to create a task whose normalized
            title matches an existing non-completed non-result task; return
            the existing task's id instead. Pass `dedup=False` to force a
            fresh row (e.g. scripted bulk imports that manage their own
            uniqueness). Result cards skip dedup unconditionally — they are
            audit trails and duplicates there are cheap to archive.

    Regression: 2026-04-23 the Wallet preflight [ALERT] task encoded its
    defer as a prose instruction in the body instead of `execute_after`.
    The consumer kept executing it early; each run called `create_task`
    with the same title, producing 28 duplicate [ALERT] rows + matching
    [RESULT] cards. Title-level dedup here means that even if a session
    forgets `execute_after`, the self-re-queue is a no-op.
    """
    lid = list_id or _list_id()
    task_notes = body or notes

    if dedup and type != "result":
        try:
            existing = list_tasks(list_id=lid, include_completed=False)
        except Exception as e:
            # Snapshot unavailable — fall through to creating the task rather
            # than blocking the writer on a read failure.
            print(f"[tasks.queue] dedup read failed, creating anyway: {e}",
                  file=sys.stderr)
            existing = []
        needle = _normalize_title(title)
        for t in existing:
            if t.type == "result":
                continue
            if t.status in ("done", "skipped"):
                continue
            if _normalize_title(t.title) == needle:
                print(
                    f"[tasks.queue] dedup: title {title!r} matches pending "
                    f"task {t.id} (status={t.status}); returning existing id",
                    file=sys.stderr,
                )
                return t.id

    now = datetime.now(timezone.utc).isoformat()
    fields = {
        "status": status,
        "priority": priority,
        "source": source,
        "created": now,
    }
    if type and type != "task":
        fields["type"] = type
    if shape:
        fields["shape"] = shape
    if dispatch:
        fields["dispatch"] = dispatch
    if criticality is not None:
        fields["criticality"] = str(criticality)
    if mode_tags:
        fields["mode_tags"] = mode_tags
    if proposal_status:
        fields["proposal_status"] = proposal_status
    if result_of:
        fields["result_of"] = result_of
    if result_status:
        fields["result_status"] = result_status
    if source_gtask_id:
        fields["source_gtask_id"] = source_gtask_id
    if execute_after:
        fields["execute_after"] = execute_after
    if resume_session_id:
        fields["resume_session_id"] = resume_session_id
    if continue_mode:
        fields["continue_mode"] = continue_mode
    if session_id:
        fields["session_id"] = session_id

    full_notes = build_frontmatter(fields)
    if task_notes:
        full_notes += f"\n{task_notes}"

    args = ["tasks", "add", lid, "--title", title, f"--notes={full_notes}", "--json"]
    if due:
        args.extend(["--due", due])
    if parent_id:
        args.extend(["--parent", parent_id])

    raw = _run_gog(*args)
    data = json.loads(raw)
    # gog returns {task: {...}} or just {...}
    task_data = data.get("task", data)
    if task_data.get("id"):
        _snapshot.apply_local_insert(lid, task_data)
    return task_data.get("id", "")


# ------------------------------------------------------------------
#  Proposal helpers (idle-research → the user approval loop)
# ------------------------------------------------------------------

SHAPE_TO_TAG = {
    "reply": "REPLY",
    "approve": "APPROVE",
    "review": "REVIEW",
    "decide": "DECIDE",
    "act": "ACTION",
    "read": "READ",
}


def create_proposal(
    title: str,
    plan: str,
    shape: str = "act",
    mode_tags: Optional[List[str]] = None,
    priority: str = "medium",
    source: str = "idle_research",
    criticality: Optional[int] = None,
    list_id: str = None,
    parent_task_id: Optional[str] = None,
) -> str:
    """Create a `[PROPOSAL]` card awaiting the user's approval.

    Args:
        title: short human title (no tag prefix needed; [PROPOSAL] is added)
        plan: multi-line plan text — goes into body under `## Plan`.
        shape: the execution shape if approved (reply|approve|review|decide|act|read).
        mode_tags: list of mode/category tags (e.g. ["deal","xov"]).
        priority: high|medium|low
        source: default "idle_research" — the idle loop is the main producer.
        criticality: optional 0-100 score for Deck sort.
        parent_task_id: GTask ID of the source task this proposal replaces —
            set when the Deck's Proposal button is clicked so the new
            [PROPOSAL] card takes the original's place. The original is
            marked done by the caller; the `result_of` link is retained for
            audit (same field name is used for both result + proposal parents).

    Returns:
        The created GTask ID.
    """
    tag_title = title if title.startswith("[PROPOSAL]") else f"[PROPOSAL] {title}"
    body = f"## Plan\n{plan.strip()}\n" if plan else ""
    tags_joined = ",".join(mode_tags) if mode_tags else None
    return create_task(
        title=tag_title,
        body=body,
        priority=priority,
        source=source,
        type="proposal",
        shape=shape,
        dispatch="session",
        criticality=criticality,
        mode_tags=tags_joined,
        proposal_status="pending",
        status="pending",
        list_id=list_id,
        result_of=parent_task_id,
    )


def create_result(
    parent_task_id: Optional[str],
    title: str,
    body: str,
    shape: Optional[str] = None,
    mode_tags: Optional[List[str]] = None,
    priority: str = "low",
    source: str = "consumer",
    criticality: Optional[int] = None,
    session_id: Optional[str] = None,
    list_id: str = None,
    dedup_topic: bool = True,
) -> str:
    """Create a `[RESULT]` card reporting on finished work.

    Result cards land on the Deck so the user sees output without digging
    through the Lifeline/TG feed. Life-cycle:

      - `status: pending`, `gtask_status: needsAction` — stays uncompleted
        so the Deck treats it as actionable (read/acknowledge).
      - `type: result`, `result_status: new`, `dispatch: self`.
      - `result_of: <parent_task_id>` if reporting on a specific task;
        `None` for standalone informational cards (Pulse digest, reflection
        summary, ad-hoc findings).

    Topic dedup (default on): before creating a fresh row, scan recent
    RESULT cards for one on the same topic — same explicit parent or
    sufficient title-token overlap. If a pending match exists, append the
    new body as a timestamped Update section and refresh `result_status`
    to `new` instead of stacking another card. If a recently-acked match
    exists (user already completed it within 48h), skip creation entirely.
    Pass `dedup_topic=False` for cards that are inherently periodic and
    should always be fresh (Pulse digests, daily reflections, etc.).

    Args:
        parent_task_id: GTask ID of the finished task being reported on,
            or `None` for standalone informational cards.
        title: short human title (no tag prefix needed; [RESULT] is added).
        body: markdown summary (## What was done / ## Key findings / ...).
        shape: optional shape carried over from parent (informational).
        mode_tags: list of mode/category tags.
        priority: default "low" — results aren't urgent by default.
        source: default "consumer".
        criticality: optional 0-100 score.
        dedup_topic: if True (default), merge into an existing same-topic
            RESULT card instead of creating a duplicate. Set False for
            periodic digest cards that always want a fresh row.

    Returns:
        The created GTask ID, or the id of the existing card that was
        updated/skipped when topic dedup fires.
    """
    tag_title = title if title.startswith("[RESULT]") else f"[RESULT] {title}"
    tags_joined = ",".join(mode_tags) if mode_tags else None
    body_text = body or ""
    # Prepend #result hashtag so the Deck filter bar can pick these up via
    # extractHashtags() and vadimgest FTS can match on #result.
    if not body_text.lstrip().startswith("#result"):
        body_text = "#result\n\n" + body_text if body_text else "#result\n"

    if dedup_topic:
        match = _find_topic_match(parent_task_id, tag_title, list_id=list_id)
        if match is not None:
            existing_id, mode = match
            if mode == "skip":
                print(
                    f"[tasks.queue] result topic dedup: user already acked "
                    f"{existing_id} on same topic; skipping new {tag_title!r}",
                    file=sys.stderr,
                )
                return existing_id
            if mode == "update":
                try:
                    _append_to_result(existing_id, body_text, list_id=list_id)
                    print(
                        f"[tasks.queue] result topic dedup: appended to "
                        f"existing {existing_id} instead of new {tag_title!r}",
                        file=sys.stderr,
                    )
                    return existing_id
                except Exception as e:
                    print(
                        f"[tasks.queue] result topic dedup: append failed "
                        f"({e}); falling through to fresh create",
                        file=sys.stderr,
                    )

    return create_task(
        title=tag_title,
        body=body_text,
        priority=priority,
        source=source,
        type="result",
        shape=shape,
        dispatch="self",
        criticality=criticality,
        mode_tags=tags_joined,
        result_of=parent_task_id,
        result_status="new",
        session_id=session_id,
        status="pending",
        list_id=list_id,
    )


def _find_topic_match(
    parent_task_id: Optional[str],
    tag_title: str,
    list_id: Optional[str] = None,
    window_days: int = 7,
    skip_window_hours: int = 48,
) -> Optional[tuple]:
    """Find an existing RESULT card on the same topic.

    Returns `(existing_id, mode)` where mode is:
      - "update": pending RESULT card; caller should append to it.
      - "skip":   recently-completed RESULT card (within `skip_window_hours`);
                  user already acked, don't recreate.
    Returns None if no match.
    """
    try:
        existing = list_tasks(list_id=list_id, include_completed=True)
    except Exception as e:
        print(f"[tasks.queue] topic dedup read failed: {e}", file=sys.stderr)
        return None

    now = datetime.now(timezone.utc)
    window_cutoff = now - timedelta(days=window_days)
    skip_cutoff = now - timedelta(hours=skip_window_hours)

    for t in existing:
        if t.type != "result":
            continue
        ts_str = t.completed_at or t.created
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < window_cutoff:
            continue

        same_parent = (
            parent_task_id is not None
            and t.result_of is not None
            and t.result_of == parent_task_id
        )
        if not (same_parent or _topic_similar(tag_title, t.title or "")):
            continue

        if t.status == "pending":
            return (t.id, "update")
        if ts >= skip_cutoff:
            return (t.id, "skip")
        # Older completed match: user acked long enough ago that fresh
        # context warrants a new card. Fall through.
    return None


def _append_to_result(
    task_id: str,
    new_body: str,
    list_id: Optional[str] = None,
) -> None:
    """Append a timestamped Update section to an existing RESULT card.

    Reads the current task notes, appends `## Update <ISO>\\n<new_body>`,
    bumps `result_status` to `new` so the Deck re-surfaces it, and persists
    via `update_task_notes`.
    """
    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"task {task_id} not found in pending list")

    addition = (new_body or "").strip()
    # Drop the leading #result hashtag from the appended chunk; the parent
    # already carries it.
    if addition.startswith("#result"):
        addition = addition[len("#result"):].lstrip()
    if not addition:
        addition = "(no new content)"

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    update_block = f"\n\n## Update {stamp}\n\n{addition}"

    base_body = task.body or ""
    task.body = (base_body + update_block).strip()
    task.result_status = "new"
    task.status = "pending"

    update_task_notes(task_id, task.to_notes(), list_id=lid)


def convert_to_result(
    task_id: str,
    title: Optional[str] = None,
    body: str = "",
    mode_tags: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    list_id: str = None,
) -> Task:
    """Convert an existing Klava task into a `[RESULT]` card in place.

    Used by the Deck's Delegate flow: the dispatched `[ACTION]` task keeps
    its GTask id but transforms into the result, so the user sees one card
    evolve (source -> action running -> result) instead of three. Avoids
    the separate `create_result` + `complete_task` dance that produced a
    fresh `[RESULT]` card each time.

    The task keeps `status: pending` so the Deck treats it as actionable
    (read/acknowledge) — matching `create_result()` life-cycle.
    """
    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"task {task_id} not found")

    base_title = (title or task.title).strip()
    # Strip any leading tag prefix ([ACTION], [RESEARCH], [REPLY], ...)
    import re as _re
    base_title = _re.sub(r"^\[[A-Z]+\]\s*", "", base_title)
    new_title = f"[RESULT] {base_title}" if not base_title.startswith("[RESULT]") else base_title

    body_text = (body or "").strip()
    if not body_text.lstrip().startswith("#result"):
        body_text = "#result\n\n" + body_text if body_text else "#result\n"

    task.title = new_title
    task.body = body_text
    task.type = "result"
    task.dispatch = "self"
    task.result_status = "new"
    task.status = "pending"
    task.completed_at = datetime.now(timezone.utc).isoformat()
    if session_id:
        task.session_id = session_id
    if mode_tags:
        task.mode_tags = ",".join(mode_tags)
    # Clear continuation intent - this row is no longer a pending action.
    task.continue_mode = None
    task.resume_session_id = None

    notes = task.to_notes()
    _run_gog("tasks", "update", lid, task.id, f"--title={task.title}", f"--notes={notes}")
    _snapshot.apply_local_mutation(lid, task.id, title=task.title, notes=notes)
    return task


def convert_to_proposal(
    task_id: str,
    title: Optional[str] = None,
    plan: str = "",
    shape: Optional[str] = None,
    mode_tags: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    list_id: str = None,
) -> Task:
    """Convert an existing Klava task into a `[PROPOSAL]` card in place.

    Used by the Deck's Proposal flow: the dispatched `[RESEARCH]` task keeps
    its GTask id and transforms into the proposal awaiting approval. The
    user's original card position is preserved; no extra card is created.
    """
    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"task {task_id} not found")

    base_title = (title or task.title).strip()
    import re as _re
    base_title = _re.sub(r"^\[[A-Z]+\]\s*", "", base_title)
    new_title = f"[PROPOSAL] {base_title}" if not base_title.startswith("[PROPOSAL]") else base_title

    plan_text = (plan or "").strip()
    body_text = f"## Plan\n{plan_text}\n" if plan_text else ""

    task.title = new_title
    task.body = body_text
    task.type = "proposal"
    task.dispatch = "session"
    task.proposal_status = "pending"
    task.proposal_plan = plan_text or None
    task.status = "pending"
    task.completed_at = datetime.now(timezone.utc).isoformat()
    if shape:
        task.shape = shape
    if session_id:
        task.session_id = session_id
    if mode_tags:
        task.mode_tags = ",".join(mode_tags)
    task.continue_mode = None
    task.resume_session_id = None

    notes = task.to_notes()
    _run_gog("tasks", "update", lid, task.id, f"--title={task.title}", f"--notes={notes}")
    _snapshot.apply_local_mutation(lid, task.id, title=task.title, notes=notes)
    return task


def approve_proposal(task_id: str, list_id: str = None) -> Task:
    """Approve a pending `[PROPOSAL]`.

    - Rewrites title prefix `[PROPOSAL]` -> shape-implied execution tag.
    - Sets `proposal_status: approved`, keeps `status: pending` so the
      consumer picks it up on the next tick as a normal executable task.
    - Flips `type` from `proposal` back to `task` so readers treat it as one.

    Returns the updated Task.
    """
    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"proposal {task_id} not found")
    if task.type != "proposal":
        raise ValueError(f"task {task_id} is not a proposal (type={task.type})")

    # Rewrite title prefix
    exec_tag = SHAPE_TO_TAG.get((task.shape or "act"), "ACTION")
    new_title = task.title
    if new_title.startswith("[PROPOSAL]"):
        new_title = new_title[len("[PROPOSAL]"):].strip()
    new_title = f"[{exec_tag}] {new_title}"

    task.title = new_title
    task.type = "task"
    task.proposal_status = "approved"
    task.status = "pending"

    notes = task.to_notes()
    _run_gog("tasks", "update", lid, task.id, f"--title={task.title}", f"--notes={notes}")
    _snapshot.apply_local_mutation(lid, task.id, title=task.title, notes=notes)
    return task


REJECTED_PROPOSALS_PATH = Path(__file__).resolve().parent / "rejected_proposals.jsonl"


def log_rejection(task: "Task", reason: str = "", path: Optional[Path] = None) -> None:
    """Append a rejection record to the persistent JSONL log.

    The idle-research loop reads this before generating new proposals so it
    can avoid resurfacing the same pattern tick after tick. Best-effort:
    failures are swallowed so a dashboard action never blocks on disk IO.
    """
    target = path or REJECTED_PROPOSALS_PATH
    record = {
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task.id,
        "title": task.title,
        "shape": task.shape,
        "mode_tags": task.mode_tags,
        "priority": task.priority,
        "source": task.source,
        "plan": (task.proposal_plan or task.body or "")[:2000],
        "reason": reason or "",
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Log loss is preferable to a failed rejection flow.
        pass


def recent_rejections(
    limit: int = 20,
    max_days: int = 30,
    path: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """Return the most recent rejection records, newest first.

    - `limit` caps the number returned.
    - `max_days` filters out entries older than N days.
    Returns an empty list if the log is missing or malformed.
    """
    target = path or REJECTED_PROPOSALS_PATH
    if not target.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    records: List[Dict[str, str]] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_raw = rec.get("rejected_at", "")
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                ts = None
            if ts is None or ts >= cutoff:
                records.append(rec)
    except Exception:
        return []

    records.reverse()
    return records[:limit]


def reject_proposal(task_id: str, reason: str = "", list_id: str = None) -> Task:
    """Reject a pending `[PROPOSAL]`.

    Sets `proposal_status: rejected`, `status: skipped`, marks the GTask
    completed, and appends a record to `rejected_proposals.jsonl` so the
    idle-research loop can avoid resurfacing the same idea. Reason
    (optional) is written both into the task body and the rejection log.
    """
    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"proposal {task_id} not found")
    if task.type != "proposal" and not task.title.startswith("[PROPOSAL]"):
        raise ValueError(f"task {task_id} is not a proposal (type={task.type})")

    task.proposal_status = "rejected"
    task.status = "skipped"
    task.completed_at = datetime.now(timezone.utc).isoformat()
    if reason:
        task.body = (task.body + f"\n\n## Rejection reason\n{reason}").strip()

    log_rejection(task, reason=reason)

    update_task_notes(task.id, task.to_notes(), list_id=lid)
    complete_task(task.id, list_id=lid)
    return task


def reject_result(task_id: str, reason: str = "", list_id: str = None) -> Task:
    """Reject a `[RESULT]` card — user decided the work won't be acted on.

    Rewrites title to `[REJECTED RESULT]`, appends the reason into the body
    under `## Rejection reason`, and closes the GTask. Distinct from
    `cancel_task` (for live tasks) and `reject_proposal` (for proposals):
    results are already-finished work, so the semantic is "I acknowledge this
    result but won't act on it" + an audit breadcrumb.
    """
    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=False)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise ValueError(f"task {task_id} not found")

    new_title = task.title
    if new_title.startswith("[RESULT]"):
        new_title = new_title[len("[RESULT]"):].strip()
    if not new_title.startswith("[REJECTED RESULT]"):
        new_title = f"[REJECTED RESULT] {new_title}"
    task.title = new_title
    task.status = "skipped"
    task.completed_at = datetime.now(timezone.utc).isoformat()
    if reason:
        task.body = (task.body + f"\n\n## Rejection reason\n{reason}").strip()

    notes = task.to_notes()
    _run_gog("tasks", "update", lid, task.id,
             f"--title={task.title}", f"--notes={notes}", "-y")
    _snapshot.apply_local_mutation(lid, task.id, title=task.title, notes=notes)
    complete_task(task.id, list_id=lid)
    return task


def create_continuation(
    parent_task_id: str,
    mode: str,
    comment: str = "",
    list_id: str = None,
) -> str:
    """Create a follow-up task that continues a parent card's work.

    mode semantics:
      - execute: parent is a [PROPOSAL]; execute the plan. Emits a [RESULT].
      - research-more: parent is a [PROPOSAL]; rewrite/refine plan based on
        comment. Emits a new [PROPOSAL].
      - follow-up: parent is a [RESULT]; iterate on the result based on
        comment. Emits a new [RESULT].

    If the parent has a session_id, this continuation resumes that session so
    the executor keeps context (no re-reading the full Obsidian state).

    Returns the new task ID.
    """
    if mode not in ("execute", "research-more", "follow-up"):
        raise ValueError(f"unknown continuation mode: {mode}")

    lid = list_id or _list_id()
    tasks = list_tasks(list_id=lid, include_completed=True)
    parent = next((t for t in tasks if t.id == parent_task_id), None)
    if parent is None:
        raise ValueError(f"parent task {parent_task_id} not found")

    plain_title = parent.title
    for prefix in ("[PROPOSAL] ", "[RESULT] ", "[ACTION] ", "[REPLY] ",
                   "[APPROVE] ", "[REVIEW] ", "[DECIDE] ", "[READ] "):
        if plain_title.startswith(prefix):
            plain_title = plain_title[len(prefix):]
            break

    parent_body = (parent.body or "").strip()
    plan = parent.proposal_plan or parent_body
    comment_block = f"\n\n## Your comment\n{comment.strip()}" if comment.strip() else ""

    if mode == "execute":
        new_title = f"[ACTION] {plain_title}"
        new_type = "task"
        instructions = (
            "## Instructions\n"
            "Execute the plan above end-to-end. Produce a [RESULT] card with "
            "`## What was done / ## Key findings / ## Artifacts / ## Suggested next step`. "
            "Incorporate the user's comment (if any) as a steering nudge."
        )
    elif mode == "research-more":
        new_title = f"[PROPOSAL] Refine: {plain_title}"
        new_type = "proposal"
        instructions = (
            "## Instructions\n"
            "Do NOT execute. Produce a REVISED [PROPOSAL] that addresses the user's comment. "
            "Use `tasks/queue.py::create_proposal()` to emit the revision. "
            "Keep the same shape and mode_tags unless the comment clearly changes them."
        )
    else:  # follow-up
        new_title = f"[ACTION] Follow-up: {plain_title}"
        new_type = "task"
        instructions = (
            "## Instructions\n"
            "Continue from the earlier result. Address the user's comment and produce a new "
            "[RESULT] card with `## What was done / ## Key findings / ## Artifacts / "
            "## Suggested next step`."
        )

    body = (
        f"## Parent card: {parent.title}\n"
        f"parent_id: {parent.id}\n"
        f"continuation_mode: {mode}\n\n"
        f"## Parent content\n{plan}"
        f"{comment_block}\n\n"
        f"{instructions}"
    )

    shape = parent.shape or "act"
    mode_tags = parent.mode_tags
    resume_sid = parent.session_id or parent.resume_session_id

    kwargs = dict(
        title=new_title,
        body=body,
        priority=parent.priority or "medium",
        source="deck-continue",
        type=new_type,
        shape=shape,
        mode_tags=mode_tags,
        parent_id=None,
        resume_session_id=resume_sid,
        continue_mode=mode,
        list_id=lid,
    )
    if new_type == "proposal":
        kwargs["proposal_status"] = "pending"
        kwargs["dispatch"] = "session"

    return create_task(**kwargs)


def find_pending_proposal(tasks: List[Task]) -> Optional[Task]:
    """Return the first [PROPOSAL] with proposal_status=pending, if any."""
    for t in tasks:
        if t.type == "proposal" and (t.proposal_status or "pending") == "pending":
            return t
    return None


def is_deferred(task: Task, now: Optional[datetime] = None) -> bool:
    """True if the task's `execute_after` is set and still in the future.

    An unparseable timestamp falls back to "not deferred" so a corrupted
    field can never permanently strand a task.
    """
    raw = task.execute_after
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return ts > current


def get_pending(tasks: List[Task]) -> List[Task]:
    """Filter pending tasks and sort by priority (high first).

    Excludes:
      - [PROPOSAL] cards with `proposal_status: pending` — those need
        explicit approval before the consumer can execute them.
      - [RESULT] cards — those are Deck-only informational cards; the
        consumer should never try to "execute" a result report.
      - Tasks with `execute_after` still in the future — scheduled work
        is not yet ready to run. Prevents the 5-minute re-queue storm
        that produced duplicate [ALERT] Result cards on 2026-04-20.
    """
    pending = [
        t for t in tasks
        if t.status == "pending"
        and t.type != "result"
        and not (t.type == "proposal" and (t.proposal_status or "pending") == "pending")
        and not is_deferred(t)
    ]
    pending.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 1))
    return pending


def get_running(tasks: List[Task]) -> Optional[Task]:
    """Find the currently running task, if any."""
    for t in tasks:
        if t.status == "running":
            return t
    return None
