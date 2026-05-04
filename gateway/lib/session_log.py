"""Append-only log of closed Klava sessions, queryable per scope.

Lives at `~/.klava/sessions.jsonl` (outside the repo so heartbeat auto-commits
can't leak it). One JSON object per line:

    {
      "ts": "2026-05-04T14:22:11Z",
      "sid": "sess_xyz",
      "scope": "Astrum/",
      "trigger": "consumer",
      "summary": "PumpFun research; created acquisition-contact task",
      "artifacts": ["gtask:abc123"],
      "duration_s": 312
    }

`tail_for_scope(scope, limit=N)` returns the last N entries matching the scope
(or any descendant of it). Best-effort writer: failures are swallowed because
losing a log line is preferable to blocking session close.
"""
from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Iterable

log = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".klava" / "sessions.jsonl"


def _path() -> Path:
    raw = os.environ.get("KLAVA_SESSION_LOG")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_PATH


def append_session(
    sid: Optional[str],
    scope: Optional[str],
    trigger: str,
    summary: str = "",
    artifacts: Optional[List[str]] = None,
    duration_s: Optional[float] = None,
    ts: Optional[str] = None,
) -> None:
    """Append one entry to the log. All errors swallowed."""
    record: Dict[str, object] = {
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "sid": sid or "",
        "scope": scope or "",
        "trigger": trigger or "",
        "summary": (summary or "").strip()[:500],
    }
    if artifacts:
        record["artifacts"] = artifacts
    if duration_s is not None:
        try:
            record["duration_s"] = round(float(duration_s), 1)
        except (TypeError, ValueError):
            pass

    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"session_log append failed: {e}")


def _matches_scope(entry_scope: str, target: str) -> bool:
    """True if entry's scope falls under target (target is a prefix)."""
    if not target:
        return False
    if not entry_scope:
        return False
    target = target if target.endswith("/") else target + "/"
    es = entry_scope if entry_scope.endswith("/") else entry_scope + "/"
    return es == target or es.startswith(target)


def _iter_lines_reverse(path: Path) -> Iterable[str]:
    """Yield non-empty lines from `path` in reverse order.

    Reads the whole file; fine for an append-only log of size < a few MB.
    Switch to a tail-seeking reader if the log ever grows large.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in reversed(text.splitlines()):
        s = line.strip()
        if s:
            yield s


def tail_for_scope(scope: str, limit: int = 5) -> List[Dict[str, object]]:
    """Return up to `limit` most-recent entries whose scope is under `scope`.

    Empty list on missing file, empty scope, or read errors.
    """
    if not scope:
        return []
    path = _path()
    if not path.exists():
        return []
    out: List[Dict[str, object]] = []
    for line in _iter_lines_reverse(path):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not _matches_scope(rec.get("scope", ""), scope):
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out
