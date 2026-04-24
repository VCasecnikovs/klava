"""A2A (Agent-to-Agent) and authenticated webhook routes.

Extracted from webhook-server.py. All routes require bearer token auth.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, jsonify

from lib import config as _cfg

a2a_bp = Blueprint('a2a', __name__)

# These are set by init_a2a_bp() from webhook-server.py
_config = None
_executor = None
_sessions_dir = None
_require_auth = None
_rate_limit = None


def init_a2a_bp(config, executor, sessions_dir, require_auth_fn, rate_limit_fn):
    """Wire up references that live in webhook-server.py."""
    global _config, _executor, _sessions_dir, _require_auth, _rate_limit
    _config = config
    _executor = executor
    _sessions_dir = sessions_dir
    _require_auth = require_auth_fn
    _rate_limit = rate_limit_fn


# ------------------------------------------------------------------
# Authenticated endpoints
# ------------------------------------------------------------------

@a2a_bp.route('/status', methods=['GET'])
def status():
    from lib.status_collector import collect_status
    # Auth check
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        return jsonify(collect_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@a2a_bp.route('/trigger/<job_id>', methods=['POST'])
def trigger_job(job_id):
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        jobs_file = _cfg.cron_jobs_file()
        if not jobs_file.exists():
            return jsonify({"error": "Jobs file not found"}), 404

        with open(jobs_file) as f:
            data = json.load(f)

        job = None
        for j in data.get("jobs", []):
            if j["id"] == job_id:
                job = j
                break

        if not job:
            return jsonify({"error": f"Job not found: {job_id}"}), 404

        if not job.get("enabled", True):
            return jsonify({"error": f"Job is disabled: {job_id}"}), 400

        exec_config = job.get("execution", {})
        session_id = exec_config.get("session_id")
        if session_id == "$main":
            from lib.main_session import get_main_session_id
            session_id = get_main_session_id()
            if not session_id:
                exec_config = dict(exec_config)
                exec_config["mode"] = "isolated"

        prompt = exec_config.get("prompt_template", "")
        now = datetime.now(timezone.utc)
        prompt = prompt.replace("{{now}}", now.isoformat())
        try:
            from zoneinfo import ZoneInfo
            tz_name = _cfg.timezone()
            now_local = now.astimezone(ZoneInfo(tz_name))
            prompt = prompt.replace("{{now_eet}}", now_local.strftime(f"%Y-%m-%d %H:%M {tz_name}"))
        except Exception:
            prompt = prompt.replace("{{now_eet}}", now.isoformat())

        result = _executor.run(
            prompt=prompt,
            mode=exec_config.get("mode", "isolated"),
            session_id=session_id,
            model=exec_config.get("model", _cfg.default_model()),
            timeout=exec_config.get("timeout_seconds", 300),
            allowed_tools=exec_config.get("allowedTools", ["*"]),
            add_dirs=exec_config.get("add_dirs", []),
            skip_permissions=True
        )

        if exec_config.get("session_id") == "$main" and result.get("session_id"):
            from lib.main_session import save_main_session_id
            save_main_session_id(result.get("session_id"))

        output = result.get("result", "")
        deltas = None
        clean_output = output
        if output and '---DELTAS---' in output:
            parts = output.split('---DELTAS---', 1)
            clean_output = parts[0].rstrip()
            try:
                deltas = json.loads(parts[1].strip())
            except (json.JSONDecodeError, IndexError):
                deltas = None

        duration = result.get("duration", 0)
        run_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": job_id,
            "status": "completed" if not result.get("error") else "failed",
            "trigger": "webhook",
            "duration_seconds": int(duration) if duration else 0,
            "cost_usd": result.get("cost", 0.0),
            "error": result.get("error"),
            "output": clean_output[:5000] if clean_output else None,
            "deltas": deltas,
            "session_id": result.get("session_id"),
        }

        runs_log = _cfg.cron_runs_log()
        with open(runs_log, 'a') as f:
            f.write(json.dumps(run_entry) + '\n')

        feed_topic = job.get("feed_topic") or job.get("telegram_topic_name") or "General"
        if clean_output and (job.get("telegram_topic") or job.get("feed_topic")):
            from lib.feed import send_feed
            if job_id == "heartbeat":
                report = _build_webhook_heartbeat_report(run_entry)
                if report:
                    send_feed(report, topic=feed_topic, parse_mode="HTML", job_id=job_id, session_id=result.get("session_id"), deltas=deltas)
            else:
                send_feed(clean_output, topic=feed_topic, parse_mode="HTML", job_id=job_id)

        return jsonify({
            "status": "executed",
            "job_id": job_id,
            "result": {
                "success": not result.get("error"),
                "cost": result.get("cost", 0.0),
                "duration": result.get("duration", 0),
                "error": result.get("error"),
                "output_preview": output[:200] if output else None
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@a2a_bp.route('/message/<session>', methods=['POST'])
def send_message(session):
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        data = request.get_json()
        if not data or "prompt" not in data:
            return jsonify({"error": "Missing 'prompt' in request body"}), 400

        prompt = data["prompt"]
        model = data.get("model", "sonnet")
        timeout = data.get("timeout", 300)

        result = _executor.run(
            prompt=prompt,
            mode="main",
            session_id=session,
            model=model,
            timeout=timeout
        )

        return jsonify({
            "status": "sent",
            "session": session,
            "result": {
                "success": not result.get("error"),
                "cost": result.get("cost", 0.0),
                "duration": result.get("duration", 0),
                "error": result.get("error")
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# A2A Session management
# ------------------------------------------------------------------

@a2a_bp.route('/sessions/list', methods=['GET'])
def sessions_list():
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        sessions = []
        if _sessions_dir.exists():
            for session_file in _sessions_dir.glob("*_claude_session.txt"):
                session_key = session_file.stem.replace("_claude_session", "")
                with open(session_file) as f:
                    full_session_id = f.read().strip()
                mtime = session_file.stat().st_mtime
                age_hours = (time.time() - mtime) / 3600
                sessions.append({
                    "key": session_key,
                    "session_id": full_session_id[:16] + "..." if len(full_session_id) > 16 else full_session_id,
                    "last_modified": datetime.fromtimestamp(mtime).isoformat(),
                    "age_hours": round(age_hours, 2)
                })
        return jsonify({"sessions": sessions, "total_count": len(sessions)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@a2a_bp.route('/sessions/<session_key>/send', methods=['POST'])
def sessions_send(session_key):
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"error": "Missing 'prompt' in request body"}), 400

        session_file = _sessions_dir / f"{session_key}_claude_session.txt"
        if not session_file.exists():
            return jsonify({"error": f"Session '{session_key}' not found"}), 404

        with open(session_file) as f:
            session_id = f.read().strip()

        start_time = time.time()
        result = _executor.run(
            prompt=data['prompt'],
            mode="main",
            session_id=session_id,
            model=data.get('model', 'sonnet'),
            timeout=data.get('timeout', 300),
            allowed_tools=["*"],
            add_dirs=[],
            skip_permissions=True
        )
        duration = time.time() - start_time

        return jsonify({
            "session_key": session_key,
            "status": "completed" if not result.get("error") else "failed",
            "duration_seconds": int(duration),
            "cost_usd": result.get("cost", 0.0),
            "result": result.get("result", ""),
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@a2a_bp.route('/sessions/<session_key>/history', methods=['GET'])
def sessions_history(session_key):
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        log_file = _sessions_dir / f"{session_key}_log.jsonl"
        if not log_file.exists():
            return jsonify({"session_key": session_key, "messages": [], "total_count": 0})

        messages = []
        with open(log_file) as f:
            for line in f:
                if line.strip():
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        limit = request.args.get('limit', type=int, default=50)
        messages = messages[-limit:]
        return jsonify({"session_key": session_key, "messages": messages, "total_count": len(messages)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@a2a_bp.route('/sessions/spawn', methods=['POST'])
def sessions_spawn():
    resp = _check_auth()
    if resp:
        return resp
    resp = _check_rate_limit()
    if resp:
        return resp
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"error": "Missing 'prompt' in request body"}), 400

        import uuid
        subagent_key = f"subagent_{uuid.uuid4().hex[:8]}"

        start_time = time.time()
        result = _executor.run(
            prompt=data['prompt'],
            mode="isolated",
            session_id=None,
            model=data.get('model', 'sonnet'),
            timeout=data.get('timeout', 300),
            allowed_tools=["*"],
            add_dirs=[],
            skip_permissions=True
        )
        duration = time.time() - start_time

        if result.get('session_id'):
            session_file = _sessions_dir / f"{subagent_key}_claude_session.txt"
            with open(session_file, 'w') as f:
                f.write(result['session_id'])

        return jsonify({
            "subagent_key": subagent_key,
            "session_id": result.get('session_id', ''),
            "description": data.get('description', 'Sub-agent'),
            "status": "completed" if not result.get("error") else "failed",
            "duration_seconds": int(duration),
            "cost_usd": result.get("cost", 0.0),
            "result": result.get("result", "")[:500],
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

import os

def _check_auth():
    """Check bearer token auth. Returns error response or None if OK."""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({"error": "Missing Authorization header"}), 401
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Invalid Authorization header"}), 401
    token = auth_header[7:]
    expected_token = os.environ.get("WEBHOOK_TOKEN", (_config or {}).get("webhook", {}).get("token"))
    if not expected_token or token != expected_token:
        return jsonify({"error": "Invalid token"}), 401
    return None


def _check_rate_limit():
    """Check rate limit. Returns error response or None if OK.

    Uses an in-blueprint store so this works regardless of how
    webhook-server.py was loaded (file with a hyphen in the name can't
    be imported as `webhook_server`). Limit is read from config so the
    user's `webhook.rate_limit_per_hour` still applies.
    """
    from collections import defaultdict
    identifier = request.remote_addr or "unknown"
    now = time.time()
    hour_ago = now - 3600
    store = _rate_limit_store
    store[identifier] = [ts for ts in store[identifier] if ts > hour_ago]
    cap = int(_cfg.load().get("webhook", {}).get("rate_limit_per_hour", 100))
    if len(store[identifier]) >= cap:
        return jsonify({"error": "Rate limit exceeded", "limit": cap, "period": "1 hour"}), 429
    store[identifier].append(now)
    return None


from collections import defaultdict
_rate_limit_store = defaultdict(list)


def _build_webhook_heartbeat_report(run_entry):
    """Build structured heartbeat report for webhook-triggered runs."""
    from zoneinfo import ZoneInfo
    import re as _re
    tz_name = _cfg.timezone()
    try:
        ts = datetime.fromisoformat(run_entry["timestamp"])
        ts_local = ts.astimezone(ZoneInfo(tz_name))
    except Exception:
        ts_local = datetime.now()
    duration = run_entry.get("duration_seconds", 0)

    lines = [f"<b>Heartbeat {ts_local.strftime('%H:%M')} {tz_name}</b> ({duration}s) [webhook]"]
    lines.append("")

    deltas = run_entry.get("deltas")
    action_deltas = [d for d in (deltas or []) if d.get("type") != "skipped"]
    if action_deltas:
        lines.append(f"<b>ACTIONS:</b> {len(action_deltas)}")
        for d in action_deltas:
            delta_type = d.get("type", "unknown")
            if "gtask" in delta_type:
                lines.append(f"  + GTask: {d.get('title', '?')}")
            elif "obsidian" in delta_type:
                lines.append(f"  + {d.get('path', '?')} {d.get('change', 'updated')}")
            elif "gmail" in delta_type:
                lines.append(f"  + Gmail draft: {d.get('subject', '?')}")
            elif "calendar" in delta_type:
                lines.append(f"  + Calendar: {d.get('title', '?')}")
            elif "deal" in delta_type:
                lines.append(f"  + Deal: {d.get('deal', '?')} - {d.get('change', '?')}")
            else:
                label = d.get("title") or d.get("path") or d.get("deal") or "?"
                lines.append(f"  + {delta_type}: {label}")

    clean_output = run_entry.get("output", "")
    if clean_output:
        filtered = [
            line for line in clean_output.split('\n')
            if line.strip()
            and not line.strip().startswith('INTAKE:')
            and not _re.match(r'HEARTBEAT[_\s-]*OK', line.strip(), _re.IGNORECASE)
        ]
        llm_text = '\n'.join(filtered).strip()
        if llm_text and len(llm_text) > 10:
            lines.append("")
            lines.append(llm_text)

    if len(lines) <= 2:
        return None
    return '\n'.join(lines)
