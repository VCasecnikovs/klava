"""Scope-aware session context.

A `scope` is an Obsidian folder path (e.g. `"Astrum/"` or `"Vox Lab/Deals/Apple — Video Images/"`).
Every task / result / session can carry one. When a session boots with a scope,
`build_scope_context()` returns a markdown block (hub frontmatter + recent notes
+ open tasks + recent results + recent sessions + cross-refs) that the consumer
prepends to the executor doctrine. The session opens already knowing the world
of that folder instead of re-deriving it from MEMORY.md every time.

Naming: "scope" not "folder" because vadimgest already overloads "folder" for
TG source folders (`--exclude-folder null` in heartbeat).
"""
from __future__ import annotations

import os
import re
import logging
from collections import Counter
from pathlib import Path
from typing import Optional, List, Dict

log = logging.getLogger(__name__)

# Scope map config (cron/scopes.yaml).
_SCOPE_MAP_PATH = Path(__file__).resolve().parent.parent / "cron" / "scopes.yaml"
_SCOPE_MAP_CACHE: Dict[str, object] = {"loaded_at": 0.0, "data": None}
_SCOPE_MAP_TTL = 60.0  # seconds

# Per-section caps (rough char counts; ~4 chars per token).
_NOTES_LIMIT = 5
_RESULTS_LIMIT = 5
_SESSIONS_LIMIT = 5
_TASKS_LIMIT = 10
_PEOPLE_LIMIT = 8
_ORGS_LIMIT = 8
_NOTE_PREVIEW_CHARS = 120
_SECTION_CAP_CHARS = 1200  # ~300 tokens per section
_VAULT_GLOB_DEPTH = 3      # don't walk deeper than this for "recent notes"


def vault_root() -> Path:
    """Resolve the Obsidian vault root, following the same env var consumer.py uses."""
    raw = os.environ.get("OBSIDIAN_VAULT", "~/Documents/MyBrain")
    return Path(raw).expanduser()


def validate_scope(s: Optional[str]) -> Optional[str]:
    """Normalize a scope string, or return None if invalid/empty.

    Rules: non-empty, ends with `/`, no `..`, no leading `/`. We do not require
    the folder to exist on disk — scopes for not-yet-created folders are valid
    (the context block will just be sparse).
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    if not s.endswith("/"):
        s = s + "/"
    if s.startswith("/") or ".." in s:
        return None
    return s


def parent_scope(s: Optional[str]) -> Optional[str]:
    """Return the parent of a scope, or None if already at root."""
    s = validate_scope(s)
    if not s or s == "/":
        return None
    parts = s.rstrip("/").split("/")
    if len(parts) <= 1:
        return None
    return "/".join(parts[:-1]) + "/"


def scope_chain(s: Optional[str]) -> List[str]:
    """Return the scope and all its ancestors, narrowest first.

    >>> scope_chain("Vox Lab/Deals/Apple/")
    ['Vox Lab/Deals/Apple/', 'Vox Lab/Deals/', 'Vox Lab/']
    """
    chain: List[str] = []
    cur = validate_scope(s)
    while cur:
        chain.append(cur)
        cur = parent_scope(cur)
    return chain


def load_scope_map() -> Dict[str, object]:
    """Read `cron/scopes.yaml`. Cached for `_SCOPE_MAP_TTL` seconds.

    Returns dict with keys `tg_topics`, `entity_to_scope`, `known_scopes`.
    Empty dict on missing file / parse error / missing PyYAML.
    """
    import time
    now = time.time()
    if _SCOPE_MAP_CACHE.get("data") is not None and (
        now - float(_SCOPE_MAP_CACHE.get("loaded_at", 0)) < _SCOPE_MAP_TTL
    ):
        return _SCOPE_MAP_CACHE["data"]  # type: ignore

    data: Dict[str, object] = {"tg_topics": {}, "entity_to_scope": {}, "known_scopes": []}
    try:
        if _SCOPE_MAP_PATH.exists():
            import yaml  # type: ignore
            with _SCOPE_MAP_PATH.open("r", encoding="utf-8") as f:
                parsed = yaml.safe_load(f) or {}
            if isinstance(parsed, dict):
                data["tg_topics"] = parsed.get("tg_topics") or {}
                data["entity_to_scope"] = parsed.get("entity_to_scope") or {}
                data["known_scopes"] = parsed.get("known_scopes") or []
    except Exception as e:
        log.debug(f"load_scope_map failed: {e}")

    _SCOPE_MAP_CACHE["data"] = data
    _SCOPE_MAP_CACHE["loaded_at"] = now
    return data


def list_known_scopes() -> List[str]:
    """Return sorted list of scopes worth showing in a picker.

    Sources, deduped:
      1. `known_scopes` from `cron/scopes.yaml`.
      2. Every folder under the vault containing a `_project.md` hub note.
      3. Top-level vault folders (depth 1) excluding `.obsidian`, `Templates`, `Inbox`.
      4. `Vox Lab/Deals/*/` (deal sub-folders are first-class scopes).
    """
    out: set[str] = set()
    cfg = load_scope_map()
    for s in cfg.get("known_scopes") or []:
        v = validate_scope(str(s))
        if v:
            out.add(v)

    vault = vault_root()
    if vault.exists() and vault.is_dir():
        # _project.md hub notes anywhere
        for hub in vault.rglob("_project.md"):
            rel = hub.parent.relative_to(vault).as_posix()
            v = validate_scope(rel)
            if v:
                out.add(v)
        # Top-level dirs
        # Catch-all folders are not scopes themselves — they contain by-entity
        # notes (one file per person/org) or transient lenses, never a project.
        # Sub-folders inside them might still be scopes if they have _project.md.
        EXCLUDE_TOP = {
            ".obsidian", ".trash", ".smart-env", "Templates", "Inbox", "Views",
            "Attachments", "People", "Organizations", "Topics", "Meetings",
            "knowledge", "archive", "_artifacts",
        }
        for entry in vault.iterdir():
            if entry.is_dir() and entry.name not in EXCLUDE_TOP and not entry.name.startswith("."):
                v = validate_scope(entry.name + "/")
                if v:
                    out.add(v)
        # Vox Lab/Deals/* — every deal is a scope
        deals = vault / "Vox Lab" / "Deals"
        if deals.exists() and deals.is_dir():
            for entry in deals.iterdir():
                if entry.is_dir() and not entry.name.startswith("_") and not entry.name.startswith("."):
                    v = validate_scope(f"Vox Lab/Deals/{entry.name}/")
                    if v:
                        out.add(v)

    return sorted(out)


def infer_scope(text: str, default: Optional[str] = None) -> Optional[str]:
    """Guess the scope for a free-form task title+body.

    Strategy:
      1. Match against `entity_to_scope` (case-insensitive substring).
         Longest entity wins so "Vox Harbor" beats "Vox".
      2. Match against deal folder names (last path segment of every
         known scope). Same longest-wins rule.
      3. Return `default` (or None).

    No LLM, no fuzzy matching — keep it deterministic and cheap. The
    user can always override via the picker; misroutes are easy to fix.
    """
    if not text:
        return default
    lo = text.lower()
    cfg = load_scope_map()

    candidates: List[tuple[str, str]] = []  # (token, scope)
    for token, scope in (cfg.get("entity_to_scope") or {}).items():
        if not token or not scope:
            continue
        if str(token).lower() in lo:
            v = validate_scope(str(scope))
            if v:
                candidates.append((str(token), v))

    for scope in list_known_scopes():
        last = scope.rstrip("/").rsplit("/", 1)[-1]
        if len(last) >= 3 and last.lower() in lo:
            candidates.append((last, scope))

    if not candidates:
        return default

    candidates.sort(key=lambda kv: -len(kv[0]))
    return candidates[0][1]


def matches_scope(task_scope: Optional[str], target: str) -> bool:
    """True if a task's `task_scope` belongs to the `target` scope subtree.

    A task tagged `Vox Lab/Deals/Apple/` matches `Vox Lab/`, `Vox Lab/Deals/`,
    and `Vox Lab/Deals/Apple/`.
    """
    ts = validate_scope(task_scope)
    tg = validate_scope(target)
    if not ts or not tg:
        return False
    return ts == tg or ts.startswith(tg)


# ------------------------------------------------------------------
#  Hub note frontmatter (extends queue.parse_frontmatter to handle list values)
# ------------------------------------------------------------------

_LIST_RE = re.compile(r"^\[(.*)\]$")


def _parse_hub_frontmatter(text: str) -> Dict[str, object]:
    """Like queue.parse_frontmatter but also recognizes `key: [a, b, c]`.

    Returns dict; values are str or list[str].
    """
    if not text or not text.strip().startswith("---"):
        return {}
    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}
    out: Dict[str, object] = {}
    for line in lines[1:end_idx]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ": " not in line:
            if line.endswith(":"):
                out[line[:-1].strip()] = ""
            continue
        key, _, value = line.partition(": ")
        key = key.strip()
        value = value.strip()
        m = _LIST_RE.match(value)
        if m:
            inner = m.group(1).strip()
            items = [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
            out[key] = items
        else:
            out[key] = value
    return out


def _read_hub(scope: str) -> Optional[Dict[str, object]]:
    """Read `<vault>/<scope>_project.md` and return parsed frontmatter."""
    vault = vault_root()
    hub_path = vault / scope.rstrip("/") / "_project.md"
    try:
        if not hub_path.exists():
            return None
        text = hub_path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm = _parse_hub_frontmatter(text)
    return fm or None


# ------------------------------------------------------------------
#  Recent notes within scope subtree
# ------------------------------------------------------------------

def _recent_notes(scope: str, limit: int = _NOTES_LIMIT) -> List[tuple[Path, float, str]]:
    """Return up to `limit` most-recently-modified .md files under the scope.

    Each entry is (path_relative_to_vault, mtime, first_nonempty_line_preview).
    Walks at most `_VAULT_GLOB_DEPTH` levels deep to keep this cheap on big trees.
    """
    vault = vault_root()
    base = vault / scope.rstrip("/")
    if not base.exists() or not base.is_dir():
        return []

    candidates: List[tuple[Path, float]] = []

    def walk(d: Path, depth: int) -> None:
        if depth > _VAULT_GLOB_DEPTH:
            return
        try:
            for entry in os.scandir(d):
                if entry.is_file() and entry.name.endswith(".md"):
                    candidates.append((Path(entry.path), entry.stat().st_mtime))
                elif entry.is_dir() and not entry.name.startswith("."):
                    walk(Path(entry.path), depth + 1)
        except OSError:
            return

    walk(base, 0)
    candidates.sort(key=lambda pm: -pm[1])
    out: List[tuple[Path, float, str]] = []
    for path, mtime in candidates[:limit]:
        preview = ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                # Skip frontmatter, take first substantive line.
                in_fm = False
                for i, line in enumerate(f):
                    if i == 0 and line.strip() == "---":
                        in_fm = True
                        continue
                    if in_fm:
                        if line.strip() == "---":
                            in_fm = False
                        continue
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    preview = s[:_NOTE_PREVIEW_CHARS]
                    break
        except OSError:
            pass
        rel = path.relative_to(vault)
        out.append((rel, mtime, preview))
    return out


# ------------------------------------------------------------------
#  Cross-references — people + orgs wikilinked from recent notes
# ------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")


def _cross_refs(notes: List[tuple[Path, float, str]]) -> tuple[List[str], List[str]]:
    """Scan note bodies for `[[People/X]]` and `[[Organizations/Y]]` links.

    Returns (people_top_N, orgs_top_N), ranked by frequency.
    """
    vault = vault_root()
    people: Counter[str] = Counter()
    orgs: Counter[str] = Counter()
    for rel, _mtime, _preview in notes:
        path = vault / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _WIKILINK_RE.finditer(text):
            target = m.group(1).strip()
            if target.startswith("People/"):
                name = target[len("People/"):].rsplit("/", 1)[-1]
                people[name] += 1
            elif target.startswith("Organizations/"):
                name = target[len("Organizations/"):].rsplit("/", 1)[-1]
                orgs[name] += 1
    return (
        [name for name, _ in people.most_common(_PEOPLE_LIMIT)],
        [name for name, _ in orgs.most_common(_ORGS_LIMIT)],
    )


# ------------------------------------------------------------------
#  Open tasks + recent results — filtered by scope chain
# ------------------------------------------------------------------

_VIEW_TITLE_RE = re.compile(r"<title>([^<]{1,200})</title>", re.IGNORECASE)
_VIEW_H1_RE = re.compile(r"<h1[^>]*>([^<]{1,200})</h1>", re.IGNORECASE)
_VIEWS_LIMIT = 20


def views_for_scope(scope: str, limit: int = _VIEWS_LIMIT) -> List[Dict[str, object]]:
    """Return HTML view files in `<vault>/Views/` whose scope matches.

    Strategy: the Views/ folder is flat and conventionally uses date-slug
    filenames (`20260221-1430-genpeach-contract-review.html`). We infer the
    scope of each file from its filename + first 2KB of content (caches the
    inferred scope by mtime to avoid re-scanning every request).

    Returns most-recent-first list of {filename, title, mtime, scope}.
    """
    scope = validate_scope(scope)
    if not scope:
        return []
    vault = vault_root()
    views_dir = vault / "Views"
    if not views_dir.exists() or not views_dir.is_dir():
        return []

    out: List[tuple[float, Dict[str, object]]] = []
    for path in views_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".html":
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        # Infer scope from filename (cheap) + small content peek (more signal).
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            head = ""
        inferred = infer_scope(path.stem + " " + head)
        if not inferred or not matches_scope(inferred, scope):
            continue
        title = path.stem
        m = _VIEW_TITLE_RE.search(head)
        if m:
            title = m.group(1).strip() or title
        else:
            mh1 = _VIEW_H1_RE.search(head)
            if mh1:
                title = mh1.group(1).strip() or title
        out.append((mtime, {
            "filename": path.name,
            "title": title,
            "mtime": mtime,
            "scope": inferred,
        }))

    out.sort(key=lambda kv: -kv[0])
    return [v for _m, v in out[:limit]]


def _filtered_tasks(scope: str) -> tuple[List[object], List[object]]:
    """Return (open_tasks, recent_results) for this scope (or any ancestor).

    Imports queue lazily to avoid circular import (queue may import scope later).
    Failures swallowed and returned as empty lists — context block degrades
    gracefully if GTasks is unreachable.
    """
    try:
        from tasks.queue import list_tasks  # local import to avoid cycle
    except Exception as e:
        log.debug(f"scope: queue import failed: {e}")
        return [], []

    try:
        # include_completed=True so we can show recently-finished result cards
        all_tasks = list_tasks(include_completed=True)
    except Exception as e:
        log.debug(f"scope: list_tasks failed: {e}")
        return [], []

    open_tasks = []
    results = []
    for t in all_tasks:
        if not matches_scope(getattr(t, "scope", None), scope):
            continue
        if t.type == "result":
            if t.gtask_status != "completed" or (t.completed_at or ""):
                results.append(t)
        else:
            if t.status in ("pending", "running") and t.gtask_status != "completed":
                if (t.title or "").lstrip().startswith("[PROPOSAL]"):
                    continue
                open_tasks.append(t)

    open_tasks.sort(key=lambda t: ({"high": 0, "medium": 1, "low": 2}.get(t.priority, 1), t.created or ""))
    results.sort(key=lambda t: t.completed_at or t.created or "", reverse=True)
    return open_tasks[:_TASKS_LIMIT], results[:_RESULTS_LIMIT]


# ------------------------------------------------------------------
#  Recent sessions — read from session log
# ------------------------------------------------------------------

def _recent_sessions(scope: str, limit: int = _SESSIONS_LIMIT) -> List[Dict[str, object]]:
    """Tail the session log for entries matching this scope (or any ancestor)."""
    try:
        # Lazy import; gateway/lib lives in a different package.
        import sys
        gw_lib = str(Path(__file__).resolve().parent.parent / "gateway")
        if gw_lib not in sys.path:
            sys.path.insert(0, gw_lib)
        from lib import session_log  # type: ignore
        return session_log.tail_for_scope(scope, limit=limit)
    except Exception as e:
        log.debug(f"scope: session_log unavailable: {e}")
        return []


# ------------------------------------------------------------------
#  Markdown rendering
# ------------------------------------------------------------------

def _truncate(s: str, cap: int = _SECTION_CAP_CHARS) -> str:
    if len(s) <= cap:
        return s
    return s[: cap - 20].rstrip() + "\n…(truncated)"


def _render_hub(hub: Dict[str, object]) -> str:
    lines = []
    for k, v in hub.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _render_notes(notes: List[tuple[Path, float, str]]) -> str:
    if not notes:
        return "_(no notes in this scope)_"
    from datetime import datetime
    lines = []
    for rel, mtime, preview in notes:
        date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        suffix = f" — {preview}" if preview else ""
        lines.append(f"- {rel} ({date}){suffix}")
    return "\n".join(lines)


def _render_tasks(tasks: List[object]) -> str:
    if not tasks:
        return "_(no open tasks)_"
    lines = []
    for t in tasks:
        prio = (t.priority or "medium").upper()
        age = ""
        if t.created:
            try:
                from datetime import datetime, timezone
                created = datetime.fromisoformat(t.created.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - created).days
                age = f", {days}d old" if days else ", today"
            except Exception:
                pass
        lines.append(f"- [{prio}{age}] {t.title}")
    return "\n".join(lines)


def _render_results(results: List[object]) -> str:
    if not results:
        return "_(no recent results)_"
    lines = []
    for r in results:
        when = (r.completed_at or r.created or "")[:10]
        title = (r.title or "").replace("[RESULT] ", "")
        lines.append(f"- {when}  {title}")
    return "\n".join(lines)


def _render_sessions(sessions: List[Dict[str, object]]) -> str:
    if not sessions:
        return "_(no recorded sessions in this scope yet)_"
    lines = []
    for s in sessions:
        ts = str(s.get("ts", ""))[:16].replace("T", " ")
        trigger = s.get("trigger", "?")
        summary = s.get("summary", "")
        lines.append(f"- {ts}  [{trigger}]  {summary}")
    return "\n".join(lines)


def _render_xrefs(people: List[str], orgs: List[str]) -> str:
    if not people and not orgs:
        return "_(no cross-references in recent notes)_"
    parts = []
    if people:
        parts.append(f"People: {', '.join(people)}")
    if orgs:
        parts.append(f"Orgs: {', '.join(orgs)}")
    return "\n".join(parts)


def build_scope_context(scope: Optional[str]) -> str:
    """Build the markdown context block for a scoped session.

    Returns "" if scope is empty/invalid. Returns a multi-section markdown block
    otherwise; sections with no content render as muted placeholders.
    """
    scope = validate_scope(scope)
    if not scope:
        return ""

    hub = _read_hub(scope) or {}
    notes = _recent_notes(scope, _NOTES_LIMIT)
    open_tasks, results = _filtered_tasks(scope)
    sessions = _recent_sessions(scope, _SESSIONS_LIMIT)
    people, orgs = _cross_refs(notes)

    sections: List[str] = []
    sections.append(f"# Scope: {scope}")

    if hub:
        sections.append(f"## Hub (from {scope}_project.md)\n{_truncate(_render_hub(hub))}")

    sections.append(f"## Recent notes (top {_NOTES_LIMIT} by mtime)\n{_truncate(_render_notes(notes))}")
    sections.append(f"## Open tasks ({len(open_tasks)})\n{_truncate(_render_tasks(open_tasks))}")
    sections.append(f"## Recent results (last {_RESULTS_LIMIT})\n{_truncate(_render_results(results))}")
    sections.append(f"## Recent sessions (last {_SESSIONS_LIMIT} in this scope)\n{_truncate(_render_sessions(sessions))}")
    sections.append(f"## Cross-references in scope\n{_truncate(_render_xrefs(people, orgs))}")

    return "\n\n".join(sections) + "\n"
