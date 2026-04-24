"""Agent Hub API routes - dispatch subagent management.

Extracted from webhook-server.py. Reads from dispatch subagent state.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify

agents_bp = Blueprint('agents', __name__)

SUBAGENT_STATE_FILE = Path.home() / "Documents" / "GitHub" / "claude" / "cron" / "subagents_state.json"
SUBAGENT_OUTPUT_DIR = Path("/tmp/claude_subagents")
CLAUDE_DIR = Path.home() / "Documents" / "GitHub" / "claude"


def _load_subagent_state():
    if SUBAGENT_STATE_FILE.exists():
        try:
            return json.loads(SUBAGENT_STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"active": {}, "pending_announces": [], "last_updated": None}


def _subagent_to_agent(job_id, sub):
    job = sub.get("job", {})
    execution = job.get("execution", {})
    started_iso = sub.get("started_at", "")

    started_epoch = None
    if started_iso:
        try:
            started_epoch = datetime.fromisoformat(started_iso).timestamp()
        except (ValueError, TypeError):
            pass

    output_file = SUBAGENT_OUTPUT_DIR / f"{job_id}.out"
    last_output = ""
    output_lines = 0
    if output_file.exists():
        try:
            text = output_file.read_text()
            lines = text.strip().split("\n") if text.strip() else []
            output_lines = len(lines)
            last_output = lines[-1][:200] if lines else ""
        except IOError:
            pass

    return {
        "id": job_id,
        "name": job.get("name", f"dispatch-{job_id[-8:]}"),
        "type": "dispatch",
        "status": sub.get("status", "running"),
        "session_id": sub.get("session_id"),
        "started": started_epoch,
        "parent": None,
        "model": execution.get("model", "sonnet"),
        "output_lines": output_lines,
        "inbox_size": 0,
        "last_output": last_output,
        "cost_usd": 0.0,
        "error": sub.get("failure_reason"),
    }


@agents_bp.route('/api/agents', methods=['GET'])
def api_agents_list():
    state = _load_subagent_state()
    agents = []
    for job_id, sub in state.get("active", {}).items():
        agents.append(_subagent_to_agent(job_id, sub))
    for announce in state.get("pending_announces", []):
        sub = announce.get("subagent", {})
        job_id = announce.get("job_id", "unknown")
        agents.append(_subagent_to_agent(job_id, sub))
    max_concurrent = 3
    try:
        import yaml as _yaml
        cfg_path = CLAUDE_DIR / "gateway" / "config.yaml"
        if cfg_path.exists():
            cfg = _yaml.safe_load(cfg_path.read_text()) or {}
            max_concurrent = cfg.get("subagents", {}).get("max_concurrent", 3)
    except Exception:
        pass
    return jsonify({"agents": agents, "max_concurrent": max_concurrent})


@agents_bp.route('/api/agents/<agent_id>', methods=['GET'])
def api_agent_detail(agent_id):
    state = _load_subagent_state()
    sub = state.get("active", {}).get(agent_id)
    if not sub:
        for announce in state.get("pending_announces", []):
            if announce.get("job_id") == agent_id:
                sub = announce.get("subagent", {})
                break
    if not sub:
        return jsonify({"error": "Agent not found"}), 404

    result = _subagent_to_agent(agent_id, sub)

    output_file = SUBAGENT_OUTPUT_DIR / f"{agent_id}.out"
    output = []
    todos = []
    if output_file.exists():
        try:
            text = output_file.read_text()
            if text.strip():
                try:
                    parsed = json.loads(text.strip())
                    if isinstance(parsed, dict):
                        todos = parsed.get("todos", [])
                        result_text = parsed.get("result", "")
                        output = result_text.splitlines() if result_text else []
                    else:
                        output = text.strip().split("\n")
                except (json.JSONDecodeError, ValueError):
                    output = text.strip().split("\n")
        except IOError:
            pass
    result["output"] = output
    result["todos"] = todos
    result["inbox"] = []
    return jsonify(result)


@agents_bp.route('/api/agents/<agent_id>/kill', methods=['POST'])
def api_agent_kill(agent_id):
    state = _load_subagent_state()
    sub = state.get("active", {}).get(agent_id)
    if not sub:
        return jsonify({"error": "Agent not found"}), 404
    pid = sub.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            os.kill(pid, 15)
            return jsonify({"status": "killed"})
        except (OSError, ProcessLookupError):
            return jsonify({"status": "not_running"})
    return jsonify({"status": "no_pid"})
