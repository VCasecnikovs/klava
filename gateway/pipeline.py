#!/usr/bin/env python3
"""Pipeline state machine CLI - validated state transitions for Claude execution pipelines."""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

BASE_DIR = Path.home() / "Documents" / "GitHub" / "claude"
PIPELINES_DIR = BASE_DIR / ".claude" / "pipelines"
STATE_DIR = BASE_DIR / ".claude" / "state" / "sessions"
COMPLETED_DIR = BASE_DIR / ".claude" / "state" / "completed"

MAX_HISTORY = 50


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_pipeline(name: str) -> dict:
    """Load a pipeline YAML definition by name."""
    path = PIPELINES_DIR / f"{name}.yaml"
    if not path.exists():
        print(f"Error: Pipeline '{name}' not found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def list_pipelines() -> list[dict]:
    """List all available pipeline definitions."""
    result = []
    if not PIPELINES_DIR.exists():
        return result
    for p in sorted(PIPELINES_DIR.glob("*.yaml")):
        with open(p) as f:
            data = yaml.safe_load(f)
        result.append({
            "name": data.get("name", p.stem),
            "description": data.get("description", ""),
            "states": list(data.get("states", {}).keys()),
            "initial_state": data.get("settings", {}).get("initial_state", ""),
        })
    return result


def state_file_path(sid: str) -> Path:
    """Get the state file path for a session ID (uses first 16 chars as prefix)."""
    prefix = sid[:16] if len(sid) > 16 else sid
    return STATE_DIR / f"{prefix}.json"


def load_state(sid: str) -> dict | None:
    """Load session state, return None if not found."""
    path = state_file_path(sid)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_state(sid: str, state: dict):
    """Atomically save session state (write tmp then rename)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = state_file_path(sid)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.rename(path)


def get_valid_transitions(pipeline: dict, current_state: str) -> list[dict]:
    """Get valid transitions from current state."""
    transitions = pipeline.get("transitions", [])
    return [t for t in transitions if t["from"] == current_state]


def cmd_start(args):
    """Start a new pipeline for a session."""
    sid = args.sid
    if not sid:
        print("Error: --sid required", file=sys.stderr)
        sys.exit(1)

    existing = load_state(sid)
    if existing and not args.force:
        pipeline_name = existing.get("pipeline", "?")
        current = existing.get("current_state", "?")
        print(
            f"Error: Session {sid[:16]} already has active pipeline '{pipeline_name}' in state '{current}'.\n"
            f"Use --force to override.",
            file=sys.stderr,
        )
        sys.exit(1)

    pipeline = load_pipeline(args.name)
    settings = pipeline.get("settings", {})
    initial = settings.get("initial_state", "match")

    # Validate initial state exists
    if initial not in pipeline.get("states", {}):
        print(f"Error: Initial state '{initial}' not found in pipeline", file=sys.stderr)
        sys.exit(1)

    context = {}
    if args.context:
        try:
            context = json.loads(args.context)
        except json.JSONDecodeError:
            print("Error: --context must be valid JSON", file=sys.stderr)
            sys.exit(1)

    ts = now_iso()
    instance_id = f"{args.name[:2]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    state = {
        "session_id": sid,
        "pipeline": args.name,
        "instance_id": instance_id,
        "current_state": initial,
        "started_at": ts,
        "state_entered_at": ts,
        "retry_count": 0,
        "context": context,
        "history": [{"from": None, "to": initial, "at": ts}],
    }

    save_state(sid, state)

    # Print confirmation with state instructions
    state_def = pipeline["states"].get(initial, {})
    instructions = state_def.get("instructions", "")
    sub_pipeline = state_def.get("sub_pipeline")
    print(f"Pipeline '{args.name}' started in state '{initial}'")
    if sub_pipeline:
        print(f"\n[SUB-PIPELINE: {sub_pipeline}] Start with: python3 gateway/pipeline.py --sid {sid[:16]} start {sub_pipeline}")
    if instructions:
        print(f"\n--- Instructions ---\n{instructions.strip()}")


def cmd_transition(args):
    """Transition to a new state."""
    sid = args.sid
    if not sid:
        print("Error: --sid required", file=sys.stderr)
        sys.exit(1)

    state = load_state(sid)
    if not state:
        print(f"Error: No active pipeline for session {sid[:16]}", file=sys.stderr)
        sys.exit(1)

    pipeline = load_pipeline(state["pipeline"])
    current = state["current_state"]
    target = args.state

    # Check if current state is terminal
    current_def = pipeline["states"].get(current, {})
    if current_def.get("terminal"):
        print(f"Error: Pipeline is in terminal state '{current}'. No transitions possible.", file=sys.stderr)
        sys.exit(1)

    # Check if target state exists
    if target not in pipeline.get("states", {}):
        print(f"Error: State '{target}' not found in pipeline '{state['pipeline']}'", file=sys.stderr)
        valid_states = list(pipeline["states"].keys())
        print(f"Valid states: {', '.join(valid_states)}", file=sys.stderr)
        sys.exit(1)

    # Find valid transitions
    valid = get_valid_transitions(pipeline, current)
    matching = [t for t in valid if t["to"] == target]

    # If label specified, filter further
    if args.label:
        matching = [t for t in matching if t.get("label") == args.label]

    if not matching:
        valid_targets = [f"{t['to']}" + (f" (--label {t['label']})" if t.get("label") else "") for t in valid]
        print(
            f"Error: Cannot transition from '{current}' to '{target}'.\n"
            f"Valid transitions from '{current}': {', '.join(valid_targets) or 'none'}",
            file=sys.stderr,
        )
        sys.exit(1)

    transition = matching[0]
    settings = pipeline.get("settings", {})

    # Check retry counter
    retry_transitions = settings.get("retry_counter_transitions", [])
    is_retry = any(
        rt["from"] == current and rt["to"] == target for rt in retry_transitions
    )

    if is_retry:
        state["retry_count"] = state.get("retry_count", 0) + 1
        max_retries = settings.get("max_retries", 5)
        if state["retry_count"] > max_retries:
            # Auto-transition to failed
            ts = now_iso()
            state["current_state"] = "failed"
            state["state_entered_at"] = ts
            history = state.get("history", [])
            history.append({
                "from": current,
                "to": "failed",
                "at": ts,
                "label": "max_retries",
                "retry_count": state["retry_count"],
            })
            state["history"] = history[-MAX_HISTORY:]
            save_state(sid, state)
            print(
                f"Max retries ({max_retries}) exceeded. Auto-transitioned to 'failed'.\n"
                f"Retry count: {state['retry_count']}"
            )
            return

    # Perform transition
    ts = now_iso()
    history_entry = {"from": current, "to": target, "at": ts}
    if transition.get("label"):
        history_entry["label"] = transition["label"]
    if is_retry:
        history_entry["retry_count"] = state["retry_count"]

    state["current_state"] = target
    state["state_entered_at"] = ts
    history = state.get("history", [])
    history.append(history_entry)
    state["history"] = history[-MAX_HISTORY:]

    save_state(sid, state)

    # Check if new state is terminal
    target_def = pipeline["states"].get(target, {})
    if target_def.get("terminal"):
        # Move to completed
        _complete_session(sid, state)
        print(f"Transitioned: {current} -> {target} (terminal)")
        return

    # Print confirmation with instructions
    instructions = target_def.get("instructions", "")
    sub_pipeline = target_def.get("sub_pipeline")
    retry_info = f" | Retries: {state['retry_count']}/{settings.get('max_retries', 5)}" if state.get("retry_count", 0) > 0 else ""
    print(f"Transitioned: {current} -> {target}{retry_info}")
    if sub_pipeline:
        print(f"\n[SUB-PIPELINE: {sub_pipeline}] Start with: python3 gateway/pipeline.py --sid {sid[:16]} start {sub_pipeline}")
    if instructions:
        print(f"\n--- Instructions ---\n{instructions.strip()}")


def _complete_session(sid: str, state: dict):
    """Move a completed session state to the completed directory."""
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
    src = state_file_path(sid)
    if src.exists():
        prefix = sid[:16] if len(sid) > 16 else sid
        dst = COMPLETED_DIR / f"{prefix}_{state.get('instance_id', 'unknown')}.json"
        try:
            shutil.move(str(src), str(dst))
        except OSError:
            # If move fails, just delete source
            src.unlink(missing_ok=True)


def cmd_status(args):
    """Show current pipeline status for a session."""
    sid = args.sid
    if not sid:
        print("Error: --sid required", file=sys.stderr)
        sys.exit(1)

    state = load_state(sid)
    if not state:
        print(f"No active pipeline for session {sid[:16]}")
        return

    pipeline = load_pipeline(state["pipeline"])
    settings = pipeline.get("settings", {})
    current = state["current_state"]
    current_def = pipeline["states"].get(current, {})

    # Duration
    started = datetime.fromisoformat(state["started_at"])
    state_entered = datetime.fromisoformat(state["state_entered_at"])
    now = datetime.now(timezone.utc)
    total_dur = now - started
    state_dur = now - state_entered

    print(f"Pipeline: {state['pipeline']}")
    print(f"Instance: {state['instance_id']}")
    print(f"State:    {current} ({current_def.get('description', '')})")
    print(f"Duration: {_fmt_duration(total_dur)} total, {_fmt_duration(state_dur)} in current state")

    retry_count = state.get("retry_count", 0)
    max_retries = settings.get("max_retries", 0)
    if max_retries > 0:
        print(f"Retries:  {retry_count}/{max_retries}")

    if state.get("context"):
        ctx_str = json.dumps(state["context"], ensure_ascii=False)
        if len(ctx_str) > 100:
            ctx_str = ctx_str[:97] + "..."
        print(f"Context:  {ctx_str}")

    # Valid next transitions
    if not current_def.get("terminal"):
        valid = get_valid_transitions(pipeline, current)
        if valid:
            targets = [f"{t['to']}" + (f" ({t['label']})" if t.get("label") else "") for t in valid]
            print(f"Next:     {', '.join(targets)}")


def cmd_end(args):
    """Force-end a pipeline for a session."""
    sid = args.sid
    if not sid:
        print("Error: --sid required", file=sys.stderr)
        sys.exit(1)

    state = load_state(sid)
    if not state:
        print(f"No active pipeline for session {sid[:16]}")
        return

    reason = args.reason or "manual"
    ts = now_iso()
    state["current_state"] = "done"
    state["state_entered_at"] = ts
    history = state.get("history", [])
    history.append({"from": state.get("current_state", "?"), "to": "done", "at": ts, "label": f"force_end:{reason}"})
    state["history"] = history[-MAX_HISTORY:]

    _complete_session(sid, state)
    # Also save final state in completed
    save_state(sid, state)
    # Clean up active session file
    state_file_path(sid).unlink(missing_ok=True)

    print(f"Pipeline '{state['pipeline']}' ended. Reason: {reason}")


def cmd_list(args):
    """List available pipelines."""
    pipelines = list_pipelines()
    if not pipelines:
        print("No pipelines found.")
        return

    print("Available Pipelines")
    print("=" * 50)
    for p in pipelines:
        states_str = " -> ".join(p["states"])
        print(f"  {p['name']:<20} {p['description']}")
        print(f"  {'':20} States: {states_str}")
        print()


def cmd_show(args):
    """Show a pipeline definition."""
    pipeline = load_pipeline(args.name)
    print(f"Pipeline: {pipeline['name']}")
    print(f"Description: {pipeline.get('description', '')}")
    print()

    settings = pipeline.get("settings", {})
    print(f"Initial state: {settings.get('initial_state', '?')}")
    print(f"Max retries: {settings.get('max_retries', 0)}")
    print()

    print("States:")
    for name, sdef in pipeline.get("states", {}).items():
        terminal = " [TERMINAL]" if sdef.get("terminal") else ""
        print(f"  {name}{terminal}: {sdef.get('description', '')}")

    print()
    print("Transitions:")
    for t in pipeline.get("transitions", []):
        label = f" ({t['label']})" if t.get("label") else ""
        print(f"  {t['from']} -> {t['to']}{label}")


def cmd_history(args):
    """Show transition history for a session."""
    sid = args.sid
    if not sid:
        print("Error: --sid required", file=sys.stderr)
        sys.exit(1)

    state = load_state(sid)
    if not state:
        print(f"No active pipeline for session {sid[:16]}")
        return

    print(f"Pipeline: {state['pipeline']} ({state['instance_id']})")
    print(f"History ({len(state.get('history', []))} entries):")
    print()

    for entry in state.get("history", []):
        from_state = entry.get("from") or "(start)"
        to_state = entry.get("to", "?")
        at = entry.get("at", "?")
        label = f" [{entry['label']}]" if entry.get("label") else ""
        retry = f" retry:{entry['retry_count']}" if entry.get("retry_count") else ""
        # Parse time for readable format
        try:
            dt = datetime.fromisoformat(at)
            at_fmt = dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            at_fmt = at
        print(f"  {at_fmt}  {from_state} -> {to_state}{label}{retry}")


def cmd_dashboard(args):
    """Show all active pipeline sessions."""
    if not STATE_DIR.exists():
        print("No active sessions.")
        return

    sessions = []
    for f in sorted(STATE_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                s = json.load(fh)
            sessions.append(s)
        except (json.JSONDecodeError, OSError):
            continue

    # Count completed today
    completed_today = 0
    if COMPLETED_DIR.exists():
        today = datetime.now().strftime("%Y%m%d")
        for f in COMPLETED_DIR.glob("*.json"):
            try:
                with open(f) as fh:
                    s = json.load(fh)
                if today in s.get("started_at", ""):
                    completed_today += 1
            except (json.JSONDecodeError, OSError):
                continue

    if not sessions:
        print(f"No active sessions. | {completed_today} completed today")
        return

    now = datetime.now(timezone.utc)

    print("Active Pipeline Sessions")
    print("=" * 80)
    print(f"{'SID':<14} {'Pipeline':<16} {'State':<10} {'Duration':<10} {'Retries':<8} {'Task'}")
    print("-" * 80)

    for s in sessions:
        sid = s.get("session_id", "?")[:12] + "..."
        pipeline = s.get("pipeline", "?")
        current = s.get("current_state", "?").upper()
        retry_count = s.get("retry_count", 0)

        try:
            started = datetime.fromisoformat(s["started_at"])
            dur = _fmt_duration(now - started)
        except (ValueError, KeyError):
            dur = "?"

        # Load pipeline for max_retries
        try:
            pdef = load_pipeline(s.get("pipeline", ""))
            max_retries = pdef.get("settings", {}).get("max_retries", 0)
            retries_str = f"{retry_count}/{max_retries}" if max_retries > 0 else "-"
        except SystemExit:
            retries_str = str(retry_count)

        ctx = s.get("context", {})
        task = ctx.get("task", "-")
        if len(task) > 25:
            task = task[:22] + "..."

        print(f"{sid:<14} {pipeline:<16} {current:<10} {dur:<10} {retries_str:<8} {task}")

    print("=" * 80)
    print(f"{len(sessions)} active | {completed_today} completed today")


def cmd_cleanup(args):
    """Remove stale session files."""
    threshold_str = args.older_than or "24h"
    hours = _parse_duration_hours(threshold_str)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    removed = 0

    # Clean active sessions
    if STATE_DIR.exists():
        for f in STATE_DIR.glob("*.json"):
            try:
                with open(f) as fh:
                    s = json.load(fh)
                started = datetime.fromisoformat(s["started_at"])
                if started < cutoff:
                    f.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                # Corrupt file, remove it
                f.unlink()
                removed += 1

    # Clean completed sessions
    if COMPLETED_DIR.exists():
        for f in COMPLETED_DIR.glob("*.json"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                f.unlink()
                removed += 1

    print(f"Cleaned up {removed} stale session files (older than {threshold_str})")


def _fmt_duration(td: timedelta) -> str:
    """Format timedelta as human-readable string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "0s"
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins:02d}m"


def _parse_duration_hours(s: str) -> float:
    """Parse duration string like '24h', '2d', '1w' to hours."""
    s = s.strip().lower()
    if s.endswith("h"):
        return float(s[:-1])
    if s.endswith("d"):
        return float(s[:-1]) * 24
    if s.endswith("w"):
        return float(s[:-1]) * 24 * 7
    return float(s)


def main():
    parser = argparse.ArgumentParser(description="Pipeline state machine CLI")
    parser.add_argument("--sid", help="Session ID (or set CLAUDE_SESSION_ID env var)",
                        default=os.environ.get("CLAUDE_SESSION_ID", ""))

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # start
    p_start = subparsers.add_parser("start", help="Start a pipeline")
    p_start.add_argument("name", help="Pipeline name")
    p_start.add_argument("--context", help="JSON context")
    p_start.add_argument("--force", action="store_true", help="Override existing pipeline")

    # transition
    p_trans = subparsers.add_parser("transition", help="Transition to a new state")
    p_trans.add_argument("state", help="Target state")
    p_trans.add_argument("--label", help="Transition label (for disambiguating)")

    # status
    subparsers.add_parser("status", help="Show current pipeline status")

    # end
    p_end = subparsers.add_parser("end", help="Force-end a pipeline")
    p_end.add_argument("--reason", help="Reason for ending")

    # list
    subparsers.add_parser("list", help="List available pipelines")

    # show
    p_show = subparsers.add_parser("show", help="Show pipeline definition")
    p_show.add_argument("name", help="Pipeline name")

    # history
    subparsers.add_parser("history", help="Show transition history")

    # dashboard
    subparsers.add_parser("dashboard", help="Show all active sessions")

    # cleanup
    p_cleanup = subparsers.add_parser("cleanup", help="Remove stale sessions")
    p_cleanup.add_argument("--older-than", default="24h", help="Threshold (e.g. 24h, 2d)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "start": cmd_start,
        "transition": cmd_transition,
        "status": cmd_status,
        "end": cmd_end,
        "list": cmd_list,
        "show": cmd_show,
        "history": cmd_history,
        "dashboard": cmd_dashboard,
        "cleanup": cmd_cleanup,
    }

    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
