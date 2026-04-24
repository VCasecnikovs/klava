"""In-memory + file-persisted snapshot of Google Tasks lists.

Replaces the per-call `gog tasks list` subprocess that was burning 25-45k
Google Tasks API quota/day. The pattern:

  - First read of a list: bootstrap with one full `gog tasks list --all`
    call. Persist to `/tmp/klava-snapshot-<list_id>.json`.
  - Subsequent reads (within `SNAPSHOT_MAX_AGE`): return in-memory copy.
  - Stale reads: do a delta call (`--updated-min=<last_sync>
    --show-completed --show-hidden --show-deleted`) to merge changes.
  - Writes (create/update/complete/cancel/postpone): caller invokes
    `apply_local_*` so the snapshot reflects the change immediately
    without waiting for the next refresh tick.

Cross-process: webhook-server and the 5-minute cron consumer share the
same file. Each process keeps its own in-memory copy and rechecks the
file mtime on every read so the consumer sees the dashboard's mutations.
Atomic write via tmp + os.rename keeps cross-process reads consistent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


SNAPSHOT_MAX_AGE = 30  # seconds — refresh-on-read threshold
BOOTSTRAP_MAX_AGE = 6 * 3600  # 6 hours — re-bootstrap to defend against drift
SNAPSHOT_DIR = Path("/tmp")
SNAPSHOT_PREFIX = "klava-snapshot-"


# Per-process cache: list_id -> {"data": dict, "file_mtime": float}
_mem: Dict[str, Dict] = {}


def _snapshot_path(list_id: str) -> Path:
    return SNAPSHOT_DIR / f"{SNAPSHOT_PREFIX}{list_id}.json"


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gog_bin() -> str:
    """Locate gog binary (mirrors tasks.queue._gog_bin)."""
    try:
        gw = str(Path(__file__).resolve().parent.parent / "gateway")
        if gw not in sys.path:
            sys.path.insert(0, gw)
        from lib import config as _cfg
        path = _cfg.google_cli()
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
    try:
        gw = str(Path(__file__).resolve().parent.parent / "gateway")
        if gw not in sys.path:
            sys.path.insert(0, gw)
        from lib import config as _cfg
        return _cfg.email() or ""
    except Exception:
        return os.environ.get("GTASKS_ACCOUNT", "")


def _gog_call(*extra_args: str, list_id: str, timeout: int = 30) -> str:
    """Run `gog tasks list <list_id> --json --results-only --all <extra...>`."""
    cmd = [
        _gog_bin(), "tasks", "list", list_id,
        "--json", "--results-only", "--all",
        "-a", _account(),
    ] + list(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"gog tasks list {list_id} failed: {(result.stderr or '').strip()[:300]}"
        )
    return result.stdout


def _atomic_write(path: Path, data: str) -> None:
    """Write atomically via tmp + rename so concurrent readers never see torn JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.rename(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _empty_snapshot(list_id: str) -> Dict:
    return {
        "list_id": list_id,
        "bootstrapped_at": "",
        "last_sync": "",
        "items": {},
    }


def _load_from_disk(list_id: str) -> Optional[Dict]:
    path = _snapshot_path(list_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[snapshot] failed to load {path}: {e}", file=sys.stderr)
        return None


def _persist(list_id: str, data: Dict) -> None:
    path = _snapshot_path(list_id)
    _atomic_write(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    # Refresh mtime tracker so we don't immediately reload our own write.
    if list_id in _mem:
        try:
            _mem[list_id]["file_mtime"] = path.stat().st_mtime
        except OSError:
            pass


def _get_mem(list_id: str) -> Dict:
    """Return the in-memory snapshot, reloading from disk if the file changed."""
    path = _snapshot_path(list_id)
    file_mtime = 0.0
    try:
        file_mtime = path.stat().st_mtime
    except OSError:
        pass

    cached = _mem.get(list_id)
    if cached and cached.get("file_mtime", 0.0) >= file_mtime:
        return cached["data"]

    disk = _load_from_disk(list_id) if file_mtime else None
    data = disk or _empty_snapshot(list_id)
    _mem[list_id] = {"data": data, "file_mtime": file_mtime}
    return data


def _age_seconds(rfc3339: str) -> float:
    if not rfc3339:
        return float("inf")
    try:
        ts = datetime.strptime(rfc3339, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            ts = datetime.fromisoformat(rfc3339.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _bootstrap(list_id: str) -> Dict:
    """Full fetch — used on first access or when bootstrap is older than 6h."""
    raw = _gog_call(list_id=list_id, timeout=60)
    items_list = json.loads(raw) or []
    if isinstance(items_list, dict):
        items_list = items_list.get("items", [])

    items = {}
    for item in items_list:
        tid = item.get("id")
        if tid:
            items[tid] = item

    now = _now_rfc3339()
    data = {
        "list_id": list_id,
        "bootstrapped_at": now,
        "last_sync": now,
        "items": items,
    }
    _persist(list_id, data)
    _mem[list_id] = {"data": data, "file_mtime": _snapshot_path(list_id).stat().st_mtime}
    return data


def _delta_refresh(list_id: str, data: Dict) -> Dict:
    """Incremental refresh — merges changes since last_sync."""
    since = data.get("last_sync") or ""
    if not since:
        return _bootstrap(list_id)

    raw = _gog_call(
        f"--updated-min={since}",
        "--show-completed", "--show-hidden", "--show-deleted",
        list_id=list_id,
        timeout=30,
    )
    items_list = json.loads(raw) or []
    if isinstance(items_list, dict):
        items_list = items_list.get("items", [])

    items = dict(data.get("items", {}))
    for item in items_list:
        tid = item.get("id")
        if not tid:
            continue
        if item.get("deleted") or item.get("hidden"):
            items.pop(tid, None)
            continue
        items[tid] = item

    data = {
        "list_id": list_id,
        "bootstrapped_at": data.get("bootstrapped_at") or _now_rfc3339(),
        "last_sync": _now_rfc3339(),
        "items": items,
    }
    _persist(list_id, data)
    return data


def _ensure_fresh(list_id: str) -> Dict:
    data = _get_mem(list_id)

    bootstrap_age = _age_seconds(data.get("bootstrapped_at", ""))
    last_sync_age = _age_seconds(data.get("last_sync", ""))

    if bootstrap_age > BOOTSTRAP_MAX_AGE:
        try:
            return _bootstrap(list_id)
        except Exception as e:
            print(f"[snapshot] bootstrap failed for {list_id}: {e}", file=sys.stderr)
            if data.get("items"):
                return data
            raise

    if last_sync_age > SNAPSHOT_MAX_AGE:
        try:
            return _delta_refresh(list_id, data)
        except Exception as e:
            print(f"[snapshot] delta refresh failed for {list_id}: {e}", file=sys.stderr)
            return data

    return data


def get_all(list_id: str, include_completed: bool = False) -> List[Dict]:
    """Return all tasks from the snapshot, refreshing if stale.

    Filter to needsAction by default. Set `include_completed=True` to
    include tasks transitioned to completed since the snapshot bootstrap.
    """
    data = _ensure_fresh(list_id)
    items = list(data.get("items", {}).values())
    if not include_completed:
        items = [i for i in items if i.get("status") != "completed"]
    return items


def force_refresh(list_id: str) -> List[Dict]:
    """Force a delta refresh now, ignoring SNAPSHOT_MAX_AGE."""
    data = _get_mem(list_id)
    if not data.get("last_sync") or _age_seconds(data.get("bootstrapped_at", "")) > BOOTSTRAP_MAX_AGE:
        data = _bootstrap(list_id)
    else:
        data = _delta_refresh(list_id, data)
    return list(data.get("items", {}).values())


def apply_local_mutation(list_id: str, task_id: str, **fields) -> None:
    """Patch a task in the snapshot in-place after a successful write to GT.

    Use after `gog tasks update` calls so callers see the new state without
    waiting for the next refresh. Unknown task_id is a no-op (the next
    refresh will pick it up).
    """
    data = _get_mem(list_id)
    items = dict(data.get("items", {}))
    item = dict(items.get(task_id) or {"id": task_id})
    item.update(fields)
    items[task_id] = item
    data = dict(data)
    data["items"] = items
    _mem[list_id] = {"data": data, "file_mtime": _mem.get(list_id, {}).get("file_mtime", 0.0)}
    _persist(list_id, data)


def apply_local_insert(list_id: str, task: Dict) -> None:
    """Add a freshly-created task to the snapshot."""
    tid = task.get("id")
    if not tid:
        return
    data = _get_mem(list_id)
    items = dict(data.get("items", {}))
    items[tid] = task
    data = dict(data)
    data["items"] = items
    _mem[list_id] = {"data": data, "file_mtime": _mem.get(list_id, {}).get("file_mtime", 0.0)}
    _persist(list_id, data)


def apply_local_delete(list_id: str, task_id: str) -> None:
    """Drop a task from the snapshot (for completes/cancels that hide the task)."""
    data = _get_mem(list_id)
    items = dict(data.get("items", {}))
    if task_id not in items:
        return
    items.pop(task_id, None)
    data = dict(data)
    data["items"] = items
    _mem[list_id] = {"data": data, "file_mtime": _mem.get(list_id, {}).get("file_mtime", 0.0)}
    _persist(list_id, data)


def apply_local_complete(list_id: str, task_id: str) -> None:
    """Mark a snapshot task as completed (transition status, set completed timestamp).

    Use when the snapshot should still surface the completed task (e.g.
    Deck shows recently-done items). For pure removal use apply_local_delete.
    """
    apply_local_mutation(
        list_id, task_id,
        status="completed",
        completed=_now_rfc3339(),
    )


def reset_for_tests() -> None:
    """Drop all in-memory state. Tests use this between cases."""
    _mem.clear()
