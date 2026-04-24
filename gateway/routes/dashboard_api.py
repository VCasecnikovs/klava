"""Dashboard data API routes - no auth required (localhost only).

Extracted from webhook-server.py. These routes serve the React dashboard
with data from status_collector and various file-based state.
"""

import json
import os
import subprocess
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, jsonify, send_from_directory

from lib import config as _cfg
from lib.status_collector import (
    collect_dashboard_data, collect_files_data, collect_pipelines_data,
    collect_tasks_data, update_task, collect_heartbeat_data,
    collect_deals_data, collect_people_data, collect_followups_data,
    collect_calendar_data, collect_views_data, collect_feed_data,
    read_md_library_file,
)
from lib.klava_manager import (
    KLAVA_TASKS, register_task, list_running,
    build_klava_prompt, complete_task as klava_complete_task,
)

dashboard_bp = Blueprint('dashboard', __name__)

# These are set by init_dashboard_bp() from webhook-server.py
_socketio = None
_executor = None
_chat_ns = None  # ChatNamespace instance for launching klava sessions
_chat_sessions = None  # Reference to CHAT_SESSIONS dict
_chat_lock = None  # Reference to _chat_lock


def init_dashboard_bp(socketio, executor, chat_ns=None, chat_sessions=None, chat_lock=None):
    """Wire up references that live in webhook-server.py."""
    global _socketio, _executor, _chat_ns, _chat_sessions, _chat_lock
    _socketio = socketio
    _executor = executor
    _chat_ns = chat_ns
    _chat_sessions = chat_sessions
    _chat_lock = chat_lock


# ------------------------------------------------------------------
# Static / health
# ------------------------------------------------------------------

@dashboard_bp.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


@dashboard_bp.route('/dashboard', methods=['GET'])
def dashboard():
    dist_dir = Path(__file__).parent.parent.parent / "tools" / "dashboard" / "dist"
    react_index = dist_dir / "index.html"
    if react_index.exists():
        return react_index.read_text(), 200, {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        }
    return "Dashboard not found. Run: cd tools/dashboard/react-app && npm run build", 404


@dashboard_bp.route('/dashboard/assets/<path:filename>', methods=['GET'])
def dashboard_assets(filename):
    assets_dir = Path(__file__).parent.parent.parent / "tools" / "dashboard" / "dist" / "assets"
    return send_from_directory(str(assets_dir), filename)


# ------------------------------------------------------------------
# Native SDK session + subagent endpoints. Wraps the claude-agent-sdk
# session functions so the dashboard can enumerate / annotate / delete
# claude sessions without re-implementing the on-disk scan.
#
# Session files live in ~/.claude/projects/<slugified-cwd>/<uuid>.jsonl.
# SDK knows how to find them; we just surface the calls.
# ------------------------------------------------------------------

@dashboard_bp.route('/api/claude/sessions', methods=['GET'])
def api_claude_sessions():
    """List claude sessions. Query params: directory (str), limit (int), offset (int)."""
    try:
        from claude_agent_sdk import list_sessions
    except ImportError:
        return jsonify({"error": "claude-agent-sdk too old (need >=0.1.55)"}), 500
    directory = request.args.get("directory")
    limit     = request.args.get("limit", type=int)
    offset    = request.args.get("offset", default=0, type=int)
    try:
        sessions = list_sessions(directory=directory, limit=limit, offset=offset)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # SDKSessionInfo is a dataclass; convert via __dict__
    def _ser(s):
        if hasattr(s, "__dict__"):
            return {k: v for k, v in s.__dict__.items() if not k.startswith("_")}
        return s
    return jsonify({"sessions": [_ser(s) for s in sessions]})


@dashboard_bp.route('/api/claude/sessions/<session_id>/rename', methods=['POST'])
def api_claude_session_rename(session_id: str):
    """Rename a session's summary."""
    try:
        from claude_agent_sdk import rename_session
    except ImportError:
        return jsonify({"error": "claude-agent-sdk too old"}), 500
    body     = request.get_json(silent=True) or {}
    new_name = (body.get("name") or "").strip()
    directory = body.get("directory")
    if not new_name:
        return jsonify({"ok": False, "error": "name required"}), 400
    try:
        rename_session(session_id=session_id, new_name=new_name, directory=directory)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "session_id": session_id, "name": new_name})


@dashboard_bp.route('/api/claude/sessions/<session_id>/tag', methods=['POST'])
def api_claude_session_tag(session_id: str):
    """Tag a session with a list of string labels."""
    try:
        from claude_agent_sdk import tag_session
    except ImportError:
        return jsonify({"error": "claude-agent-sdk too old"}), 500
    body      = request.get_json(silent=True) or {}
    tags      = body.get("tags", [])
    directory = body.get("directory")
    if not isinstance(tags, list):
        return jsonify({"ok": False, "error": "tags must be a list"}), 400
    try:
        tag_session(session_id=session_id, tags=tags, directory=directory)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "session_id": session_id, "tags": tags})


@dashboard_bp.route('/api/claude/sessions/<session_id>', methods=['DELETE'])
def api_claude_session_delete(session_id: str):
    """Delete a session's on-disk jsonl + subagent state."""
    try:
        from claude_agent_sdk import delete_session
    except ImportError:
        return jsonify({"error": "claude-agent-sdk too old"}), 500
    directory = request.args.get("directory")
    try:
        delete_session(session_id=session_id, directory=directory)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "session_id": session_id})


@dashboard_bp.route('/api/claude/sessions/<session_id>/subagents', methods=['GET'])
def api_claude_subagents(session_id: str):
    """List subagents spawned by this parent session (native SDK scan)."""
    try:
        from claude_agent_sdk import list_subagents
    except ImportError:
        return jsonify({"error": "claude-agent-sdk too old"}), 500
    directory = request.args.get("directory")
    try:
        subs = list_subagents(parent_session_id=session_id, directory=directory)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    def _ser(s):
        if hasattr(s, "__dict__"):
            return {k: v for k, v in s.__dict__.items() if not k.startswith("_")}
        return s
    return jsonify({"subagents": [_ser(s) for s in subs]})


@dashboard_bp.route('/api/claude/sessions/<session_id>/subagents/<subagent_id>/messages', methods=['GET'])
def api_claude_subagent_messages(session_id: str, subagent_id: str):
    """Get messages for a specific subagent. Used to replay subagent history
    into a Task agent block when resuming a session."""
    try:
        from claude_agent_sdk import get_subagent_messages
    except ImportError:
        return jsonify({"error": "claude-agent-sdk too old"}), 500
    directory = request.args.get("directory")
    try:
        msgs = get_subagent_messages(
            parent_session_id=session_id,
            subagent_id=subagent_id,
            directory=directory,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # Messages are likely dicts already (raw jsonl rows) — pass through.
    return jsonify({"messages": msgs})


# ------------------------------------------------------------------
# launchd daemon control — list + restart (kickstart -k) known agents.
#
# Allowlist is derived from installed plists in ~/Library/LaunchAgents
# matching <prefix>.*.plist. Strict prefix match prevents arbitrary
# label injection from the POST body. webhook-server needs detached
# execution because restarting it kills the Flask process serving the
# request — we'd never return a response otherwise.
# ------------------------------------------------------------------

_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def _installed_plists() -> list[Path]:
    prefix = _cfg.launchd_prefix()
    if not _LAUNCH_AGENTS_DIR.is_dir():
        return []
    return sorted(_LAUNCH_AGENTS_DIR.glob(f"{prefix}.*.plist"))


def _daemon_state(label: str) -> dict:
    """Query launchctl for a single label. Returns loaded/running/pid/last_exit.
    All fields best-effort — any parse failure collapses to unknown.
    """
    uid = os.getuid()
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{label}"],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return {"loaded": False, "running": False, "pid": None, "last_exit": None}

    # Non-zero return typically means "service is not loaded"
    if r.returncode != 0:
        return {"loaded": False, "running": False, "pid": None, "last_exit": None}

    pid = None
    last_exit: int | None = None
    state = ""
    for line in r.stdout.splitlines():
        s = line.strip()
        if s.startswith("pid ="):
            try: pid = int(s.split("=", 1)[1].strip())
            except Exception: pass
        elif s.startswith("state ="):
            state = s.split("=", 1)[1].strip()
        elif s.startswith("last exit code ="):
            raw = s.split("=", 1)[1].strip()
            try: last_exit = int(raw)
            except Exception: last_exit = None
    return {
        "loaded":    True,
        "running":   (state == "running") or (pid is not None and pid > 0),
        "pid":       pid,
        "last_exit": last_exit,
    }


# Suffixes that restart their own serving process — hitting restart via
# dashboard kills the socket that made the request. Backend flags these
# so the UI can warn + require extra confirmation.
_SELF_KILLING_SUFFIXES = {"webhook-server"}


@dashboard_bp.route('/api/daemons', methods=['GET'])
def api_daemons():
    prefix = _cfg.launchd_prefix()
    daemons = []
    for plist in _installed_plists():
        label = plist.stem
        name  = label[len(prefix) + 1:] if label.startswith(prefix + ".") else label
        state = _daemon_state(label)
        daemons.append({
            "label": label,
            "name":  name,
            "path":  str(plist),
            **state,
        })
    return jsonify({
        "daemons":           daemons,
        "prefix":            prefix,
        "launch_agents_dir": str(_LAUNCH_AGENTS_DIR),
    })


@dashboard_bp.route('/api/daemons/<label>/restart', methods=['POST'])
def api_daemon_restart(label: str):
    allowed = {p.stem for p in _installed_plists()}
    if label not in allowed:
        return jsonify({"ok": False, "error": f"label not in allowlist: {label}"}), 400

    uid    = os.getuid()
    suffix = label.rsplit(".", 1)[-1]

    if suffix in _SELF_KILLING_SUFFIXES:
        # Webhook-server is special: synchronous kickstart would SIGTERM
        # ourselves before the response goes out. Also, `kickstart -k`
        # sends SIGTERM first — if the Flask+SocketIO process is stuck on
        # socket cleanup (we've seen this repeatedly), it doesn't die in
        # time and the new instance fails to bind :18788 (Port in use).
        # Observed in /tmp/webhook-server.stderr.log after every GUI
        # Restart click: "Port 18788 is in use by another program".
        #
        # Use SIGKILL directly. launchd re-spawns via KeepAlive=true.
        # Guaranteed port release, guaranteed fresh process.
        try:
            subprocess.Popen(
                ["launchctl", "kill", "KILL", f"gui/{uid}/{label}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": f"detached spawn failed: {e}"}), 500
        return jsonify({
            "ok":       True,
            "label":    label,
            "detached": True,
            "note":     f"{suffix} force-killed (SIGKILL); launchd is respawning it — reconnect in ~5s",
        })

    cmd = ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception as e:
        return jsonify({"ok": False, "error": f"kickstart failed: {e}"}), 500
    if r.returncode != 0:
        return jsonify({
            "ok":         False,
            "error":      (r.stderr or r.stdout or "launchctl non-zero exit").strip(),
            "returncode": r.returncode,
        }), 500
    return jsonify({"ok": True, "label": label, "detached": False})


# ------------------------------------------------------------------
# Data endpoints
# ------------------------------------------------------------------

@dashboard_bp.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    try:
        data = collect_dashboard_data()
        data["assistant_name"] = _cfg.assistant_name()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/files', methods=['GET'])
def api_files():
    try:
        date = request.args.get('date')
        return jsonify(collect_files_data(date=date))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/files/md', methods=['GET'])
def api_files_md():
    """Return a single .md file's content. Path must be in the md_library allowlist."""
    try:
        rel_path = request.args.get('path', '')
        data = read_md_library_file(rel_path)
        if data is None:
            return jsonify({"error": "not found or not allowed"}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/plans', methods=['GET'])
def api_plans():
    try:
        plans_dir = _cfg.plans_dir()
        plans = []
        if plans_dir.exists():
            for f in sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                stat = f.stat()
                plans.append({
                    "name": f.stem,
                    "content": f.read_text(errors="replace"),
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "size": stat.st_size,
                })
        return jsonify({"plans": plans})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/pipelines', methods=['GET'])
def api_pipelines():
    try:
        return jsonify(collect_pipelines_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/tasks', methods=['GET'])
def api_tasks():
    try:
        return jsonify(collect_tasks_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/tasks/update', methods=['POST'])
def api_tasks_update():
    try:
        body = request.get_json(force=True)
        task_id = body.get("task_id", "")
        action = body.get("action", "")
        note = body.get("note", "")
        days = int(body.get("days") or 7)
        if not task_id or not action:
            return jsonify({"success": False, "message": "Missing task_id or action"}), 400
        result = update_task(task_id, action, note, days=days)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@dashboard_bp.route('/api/heartbeat', methods=['GET'])
def api_heartbeat():
    try:
        return jsonify(collect_heartbeat_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/feed', methods=['GET'])
def api_feed():
    try:
        limit = request.args.get('limit', 100, type=int)
        topic = request.args.get('topic', None)
        return jsonify(collect_feed_data(limit=limit, topic=topic))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Self-evolve backlog
# ------------------------------------------------------------------

def _parse_backlog_full(text):
    """Parse backlog.md into metrics + items (split by section)."""
    import re as _re
    metrics = {"added": 0, "fixed": 0, "avg_days": "-", "last_run": "never"}
    for line in text.split("\n"):
        if line.startswith("- Items added"):
            m = _re.search(r":\s*(\d+)", line)
            if m: metrics["added"] = int(m.group(1))
        elif line.startswith("- Items fixed"):
            m = _re.search(r":\s*(\d+)", line)
            if m: metrics["fixed"] = int(m.group(1))
        elif line.startswith("- Avg days open"):
            m = _re.search(r":\s*(.+)", line)
            if m: metrics["avg_days"] = m.group(1).strip()
        elif line.startswith("- Last run"):
            m = _re.search(r":\s*(.+)", line)
            if m: metrics["last_run"] = m.group(1).strip()

    items_section = []
    done_section = []
    sections = _re.split(r"^## (Items|Done)", text, flags=_re.MULTILINE)
    items_text = ""
    done_text = ""
    for i, s in enumerate(sections):
        if s == "Items" and i + 1 < len(sections):
            items_text = sections[i + 1]
        elif s == "Done" and i + 1 < len(sections):
            done_text = sections[i + 1]

    def _parse_items(block_text):
        result = []
        item_blocks = _re.split(r"^### ", block_text, flags=_re.MULTILINE)[1:]
        for block in item_blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue
            date_match = _re.match(r"\[(\d{4}-\d{2}-\d{2})\]\s*(.*)", lines[0].strip())
            if not date_match:
                continue
            item = {
                "date": date_match.group(1), "title": date_match.group(2),
                "source": "", "priority": "medium", "status": "open",
                "seen": 1, "description": "", "fix_hint": "", "resolved": "",
                "session_id": "",
            }
            for line in lines[1:]:
                line = line.strip()
                for field in ("source", "priority", "status", "description", "fix-hint", "resolved", "session"):
                    if line.startswith(f"- **{field}:**"):
                        val = line.split(":**", 1)[1].strip()
                        key = field.replace("-", "_")
                        if key == "session":
                            item["session_id"] = val
                        else:
                            item[key] = val
                if line.startswith("- **seen:**"):
                    try: item["seen"] = int(line.split(":**", 1)[1].strip())
                    except (ValueError, IndexError): pass
            result.append(item)
        return result

    items_section = _parse_items(items_text)
    done_section = _parse_items(done_text)
    return metrics, items_section, done_section


def _serialize_backlog(metrics, items_section, done_section):
    """Serialize backlog data back to markdown."""
    lines = [
        "# Self-Evolve Backlog\n",
        "<!-- Writers: reflection, heartbeat, interactive sessions, self-evolve -->",
        "<!-- Reader: self-evolve (4 AM daily, picks top items, fixes, marks done) -->",
        "<!-- Dislike capture: when user expresses frustration, session context → here -->\n",
        "## Metrics",
        f"- Items added (30d): {metrics.get('added', 0)}",
        f"- Items fixed (30d): {metrics.get('fixed', 0)}",
        f"- Avg days open: {metrics.get('avg_days', 0)}",
        f"- Last run: {metrics.get('last_run', 'never')}\n",
        "---\n",
        "## Items\n",
    ]
    for item in items_section:
        lines.append(f"### [{item['date']}] {item['title']}")
        lines.append(f"- **source:** {item.get('source', '')}")
        lines.append(f"- **priority:** {item.get('priority', 'medium')}")
        lines.append(f"- **status:** {item.get('status', 'open')}")
        lines.append(f"- **seen:** {item.get('seen', 1)}")
        if item.get('session_id'):
            lines.append(f"- **session:** {item['session_id']}")
        lines.append(f"- **description:** {item.get('description', '')}")
        if item.get('fix_hint'):
            lines.append(f"- **fix-hint:** {item['fix_hint']}")
        if item.get('resolved'):
            lines.append(f"- **resolved:** {item['resolved']}")
        lines.append("")
    lines.append("---\n")
    lines.append("## Done\n")
    lines.append("<!-- Items moved here after 7 days in done state, then pruned after 30 days -->\n")
    for item in done_section:
        lines.append(f"### [{item['date']}] {item['title']}")
        lines.append(f"- **source:** {item.get('source', '')}")
        lines.append(f"- **priority:** {item.get('priority', 'medium')}")
        lines.append(f"- **status:** {item.get('status', 'done')}")
        lines.append(f"- **seen:** {item.get('seen', 1)}")
        if item.get('session_id'):
            lines.append(f"- **session:** {item['session_id']}")
        lines.append(f"- **description:** {item.get('description', '')}")
        if item.get('fix_hint'):
            lines.append(f"- **fix-hint:** {item['fix_hint']}")
        if item.get('resolved'):
            lines.append(f"- **resolved:** {item['resolved']}")
        lines.append("")
    return "\n".join(lines)


@dashboard_bp.route('/api/self-evolve', methods=['GET'])
def api_self_evolve():
    import re as _re
    try:
        backlog_path = _cfg.self_evolve_backlog()
        metrics = {"added": 0, "fixed": 0, "avg_days": "-", "last_run": "never"}
        items = []
        if backlog_path.exists():
            text = backlog_path.read_text()
            for line in text.split("\n"):
                if line.startswith("- Items added"):
                    m = _re.search(r":\s*(\d+)", line)
                    if m: metrics["added"] = int(m.group(1))
                elif line.startswith("- Items fixed"):
                    m = _re.search(r":\s*(\d+)", line)
                    if m: metrics["fixed"] = int(m.group(1))
                elif line.startswith("- Avg days open"):
                    m = _re.search(r":\s*(.+)", line)
                    if m: metrics["avg_days"] = m.group(1).strip()
                elif line.startswith("- Last run"):
                    m = _re.search(r":\s*(.+)", line)
                    if m: metrics["last_run"] = m.group(1).strip()
            item_blocks = _re.split(r"^### ", text, flags=_re.MULTILINE)[1:]
            for block in item_blocks:
                lines = block.strip().split("\n")
                if not lines:
                    continue
                date_match = _re.match(r"\[(\d{4}-\d{2}-\d{2})\]\s*(.*)", lines[0].strip())
                if not date_match:
                    continue
                item = {
                    "date": date_match.group(1), "title": date_match.group(2),
                    "source": "", "priority": "medium", "status": "open",
                    "seen": 1, "description": "", "fix_hint": "", "resolved": "",
                    "session_id": "",
                }
                for line in lines[1:]:
                    line = line.strip()
                    for field in ("source", "priority", "status", "description", "fix-hint", "resolved", "session"):
                        if line.startswith(f"- **{field}:**"):
                            val = line.split(":**", 1)[1].strip()
                            key = field.replace("-", "_")
                            if key == "session":
                                item["session_id"] = val
                            elif key == "seen":
                                try: item[key] = int(val)
                                except (ValueError, TypeError): pass
                            else:
                                item[key] = val
                    if line.startswith("- **seen:**"):
                        try: item["seen"] = int(line.split(":**", 1)[1].strip())
                        except (ValueError, TypeError): pass
                items.append(item)
        return jsonify({"metrics": metrics, "items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/self-evolve/item', methods=['PUT'])
def api_self_evolve_update():
    try:
        data = request.get_json() or {}
        title = data.get("title")
        if not title:
            return jsonify({"error": "title is required"}), 400

        backlog_path = _cfg.self_evolve_backlog()
        if not backlog_path.exists():
            return jsonify({"error": "Backlog file not found"}), 404

        text = backlog_path.read_text()
        metrics, items, done = _parse_backlog_full(text)

        found = False
        for section in [items, done]:
            for item in section:
                if item["title"] == title:
                    for field in ("title", "source", "priority", "status", "seen",
                                  "description", "fix_hint", "resolved", "session_id"):
                        if field in data.get("updates", {}):
                            item[field] = data["updates"][field]
                    found = True
                    break
            if found:
                break

        if not found:
            return jsonify({"error": f"Item not found: {title}"}), 404

        tmp = str(backlog_path) + ".tmp"
        with open(tmp, "w") as f:
            f.write(_serialize_backlog(metrics, items, done))
        os.replace(tmp, str(backlog_path))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/self-evolve/item', methods=['DELETE'])
def api_self_evolve_delete():
    try:
        data = request.get_json() or {}
        title = data.get("title")
        if not title:
            return jsonify({"error": "title is required"}), 400

        backlog_path = _cfg.self_evolve_backlog()
        if not backlog_path.exists():
            return jsonify({"error": "Backlog file not found"}), 404

        text = backlog_path.read_text()
        metrics, items, done = _parse_backlog_full(text)

        orig_count = len(items) + len(done)
        items = [i for i in items if i["title"] != title]
        done = [i for i in done if i["title"] != title]

        if len(items) + len(done) == orig_count:
            return jsonify({"error": f"Item not found: {title}"}), 404

        tmp = str(backlog_path) + ".tmp"
        with open(tmp, "w") as f:
            f.write(_serialize_backlog(metrics, items, done))
        os.replace(tmp, str(backlog_path))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/self-evolve/run', methods=['POST'])
def api_self_evolve_run():
    try:
        jobs_file = _cfg.cron_jobs_file()
        if not jobs_file.exists():
            return jsonify({"error": "Jobs file not found"}), 404

        with open(jobs_file) as f:
            data = json.load(f)

        job = None
        for j in data.get("jobs", []):
            if j["id"] == "self-evolve":
                job = j
                break

        if not job:
            return jsonify({"error": "self-evolve job not found"}), 404

        exec_config = job.get("execution", {})
        result = _executor.run(
            prompt=exec_config.get("prompt_template", ""),
            mode=exec_config.get("mode", "isolated"),
            session_id=exec_config.get("session_id"),
            model=exec_config.get("model", _cfg.default_model()),
            timeout=exec_config.get("timeout_seconds", 300),
            allowed_tools=exec_config.get("allowedTools", ["*"]),
            add_dirs=exec_config.get("add_dirs", []),
            skip_permissions=True
        )

        runs_log = _cfg.cron_runs_log()
        output = result.get("result", "")
        with open(runs_log, 'a') as f:
            f.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": "self-evolve",
                "status": "completed" if not result.get("error") else "failed",
                "trigger": "dashboard",
                "cost_usd": result.get("cost", 0.0),
                "error": result.get("error"),
                "output": output[:500] if output else None
            }) + '\n')

        return jsonify({
            "status": "executed",
            "output": output[:500] if output else "",
            "error": result.get("error"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/feedback/dislike', methods=['POST'])
def api_feedback_dislike():
    try:
        data = request.get_json() or {}
        comment = data.get("comment", "").strip()
        text_preview = (data.get("text_preview") or "")[:300]
        block_id = data.get("block_id")
        session_id = data.get("session_id", "")

        backlog_path = _cfg.self_evolve_backlog()
        if not backlog_path.exists():
            return jsonify({"error": "Backlog file not found"}), 404

        text = backlog_path.read_text()
        metrics, items, done = _parse_backlog_full(text)

        title = comment[:80] if comment else f"Dislike on block #{block_id}"
        today = datetime.now().strftime("%Y-%m-%d")

        items.append({
            "date": today,
            "title": title,
            "source": "dislike",
            "priority": "medium",
            "status": "open",
            "seen": 1,
            "session_id": session_id,
            "description": text_preview if text_preview else comment,
            "fix_hint": "",
            "resolved": "",
        })

        metrics["added"] = metrics.get("added", 0) + 1
        tmp = str(backlog_path) + ".tmp"
        with open(tmp, "w") as f:
            f.write(_serialize_backlog(metrics, items, done))
        os.replace(tmp, str(backlog_path))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Simple data proxies
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Klava task queue API
# ------------------------------------------------------------------

@dashboard_bp.route('/api/klava/tasks', methods=['GET'])
def api_klava_tasks():
    """List Klava tasks with live status from running sessions."""
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import list_tasks as queue_list_tasks

        tasks = queue_list_tasks(include_completed=True)
        running = list_running()  # tab_id -> metadata

        result = []
        for t in tasks:
            tab_id = f"klava-{t.id[:16]}"
            live = running.get(tab_id)
            # Parse result from body (appended by complete_task as ## Result)
            body_text = t.body or ""
            result_text = ""
            if "\n## Result\n" in body_text:
                parts = body_text.split("\n## Result\n", 1)
                body_text = parts[0].strip()
                result_text = parts[1].strip()
            elif "\n## Error\n" in body_text:
                parts = body_text.split("\n## Error\n", 1)
                body_text = parts[0].strip()
                result_text = parts[1].strip()
            item = {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "source": t.source,
                "body": body_text,
                "result": result_text,
                "created": t.created,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
                "session_id": t.session_id,
                "tab_id": tab_id if live else None,
                "has_question": False,
                # v2 unified-schema fields (plan: nifty-dreaming-lighthouse)
                "type": getattr(t, "type", "task"),
                "shape": getattr(t, "shape", None),
                "dispatch": getattr(t, "dispatch", None),
                "criticality": getattr(t, "criticality", None),
                "mode_tags": (
                    [s.strip() for s in t.mode_tags.split(",") if s.strip()]
                    if getattr(t, "mode_tags", None) else None
                ),
                "proposal_status": getattr(t, "proposal_status", None),
                "proposal_plan": getattr(t, "proposal_plan", None),
                "result_of": getattr(t, "result_of", None),
            }
            # Check if running session has pending question
            if live:
                item["status"] = "running"
                with _chat_lock:
                    sess = _chat_sessions.get(tab_id) if _chat_sessions else None
                    if sess and sess.get("_question_future") and not sess["_question_future"].done():
                        item["has_question"] = True
                        qi = sess.get("_question_input", {})
                        item["questions"] = qi.get("questions", [])
            result.append(item)

        return jsonify({"tasks": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks', methods=['POST'])
def api_klava_create():
    """Create a new Klava task."""
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import create_task
        from tasks.consumer import KlavaLaunchContention

        data = request.get_json(force=True) or {}
        title = (data.get("title") or "").strip()
        body = (data.get("body") or "").strip()
        priority = data.get("priority", "medium")
        source = data.get("source", "dashboard")
        auto_launch = data.get("auto_launch", True)
        # Optional origin id (heartbeat conversation_group, upstream GTask,
        # webhook request id) — used by the consumer to dedup two queue rows
        # that point at the same source event.
        raw_sgi = data.get("source_gtask_id")
        source_gtask_id = (raw_sgi or "").strip() if isinstance(raw_sgi, str) else None
        if not source_gtask_id:
            source_gtask_id = None

        if not title:
            return jsonify({"error": "title required"}), 400

        task_id = create_task(
            title=title,
            body=body,
            priority=priority,
            source=source,
            source_gtask_id=source_gtask_id,
        )

        result = {"task_id": task_id, "launched": False}

        # Auto-launch if requested and chat_ns available
        if auto_launch and _chat_ns and task_id:
            try:
                tab_id = _launch_klava(task_id, title, body, priority, source)
                if tab_id:
                    result["launched"] = True
                    result["tab_id"] = tab_id
            except KlavaLaunchContention as e:
                result["launch_error"] = str(e)
                return jsonify(result), 409

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/launch', methods=['POST'])
def api_klava_launch(task_id):
    """Launch a pending Klava task as a dashboard session."""
    try:
        if not _chat_ns:
            return jsonify({"error": "Chat namespace not available"}), 503

        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import list_tasks as queue_list_tasks
        from tasks.consumer import KlavaLaunchContention

        # Find the task
        tasks = queue_list_tasks()
        task = None
        for t in tasks:
            if t.id == task_id:
                task = t
                break

        if not task:
            return jsonify({"error": "Task not found"}), 404
        if task.status == "running":
            return jsonify({"error": "Task already running"}), 409

        data = request.get_json(force=True) if request.is_json else {}
        model = data.get("model", _cfg.default_model())

        try:
            tab_id = _launch_klava(task.id, task.title, task.body, task.priority, task.source, model)
        except KlavaLaunchContention as e:
            return jsonify({"error": str(e)}), 409
        if not tab_id:
            return jsonify({"error": "Failed to launch"}), 500

        return jsonify({"tab_id": tab_id, "task_id": task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/answer', methods=['POST'])
def api_klava_answer(task_id):
    """Answer a pending question on a running Klava task."""
    try:
        tab_id = f"klava-{task_id[:16]}"
        data = request.get_json(force=True) or {}
        answers = data.get("answers", {})

        if not answers:
            return jsonify({"error": "answers required"}), 400

        from claude_agent_sdk import PermissionResultAllow

        with _chat_lock:
            sess = _chat_sessions.get(tab_id) if _chat_sessions else None
            if not sess:
                return jsonify({"error": "No active session"}), 404
            question_future = sess.get("_question_future")
            question_input = sess.get("_question_input", {})
            sdk_loop = sess.get("sdk_loop")

        if not question_future or question_future.done() or not sdk_loop:
            return jsonify({"error": "No pending question"}), 404

        qs = question_input.get("questions", [])
        result = PermissionResultAllow(
            updated_input={"questions": qs, "answers": answers}
        )
        sdk_loop.call_soon_threadsafe(question_future.set_result, result)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/approve', methods=['POST'])
def api_klava_approve(task_id):
    """Approve a [PROPOSAL] task. Rewrites the tag, flips type, keeps status=pending.

    Next consumer tick picks it up through the normal execution path.
    """
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import approve_proposal

        t = approve_proposal(task_id)
        return jsonify({
            "ok": True,
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "proposal_status": t.proposal_status,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/reject', methods=['POST'])
def api_klava_reject(task_id):
    """Reject a [PROPOSAL] task. Marks skipped + completes the GTask."""
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import reject_proposal

        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        t = reject_proposal(task_id, reason=reason)
        return jsonify({
            "ok": True,
            "id": t.id,
            "status": t.status,
            "proposal_status": t.proposal_status,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/complete', methods=['POST'])
def api_klava_complete(task_id):
    """Mark a Klava list task as completed in GTasks.

    Used by Deck done/skip on raw Klava cards (IDs without `gtask_` prefix).
    Result cards, regular tasks, and approved proposals all close through
    this route.
    """
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import complete_task
        complete_task(task_id)
        return jsonify({"ok": True, "id": task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/cancel', methods=['POST'])
def api_klava_cancel(task_id):
    """Mark a Klava list task as `[CANCELLED]` — user said 'I won't do this'."""
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import cancel_task
        cancel_task(task_id)
        return jsonify({"ok": True, "id": task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/postpone', methods=['POST'])
def api_klava_postpone(task_id):
    """Push the Klava task's due date forward by `days` (default 7)."""
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import postpone_task
        data = request.get_json(silent=True) or {}
        days = int(data.get("days") or 7)
        postpone_task(task_id, days)
        return jsonify({"ok": True, "id": task_id, "days": days})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/tasks/<task_id>/reject-result', methods=['POST'])
def api_klava_reject_result(task_id):
    """Reject a `[RESULT]` card — ack it but decide not to act.

    Rewrites the title to `[REJECTED RESULT]`, appends the reason to the
    body under `## Rejection reason`, and closes the GTask.
    """
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import reject_result
        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        t = reject_result(task_id, reason=reason)
        return jsonify({"ok": True, "id": t.id, "title": t.title, "status": t.status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/klava/continue', methods=['POST'])
def api_klava_continue():
    """Continue a card's work in a new Klava task.

    Payload: `{card_id, mode, comment}` where `mode ∈ {execute,
    research-more, follow-up}`. The new task resumes the parent's session
    (if present) so the executor keeps context instead of cold-starting.
    """
    try:
        import sys
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from tasks.queue import create_continuation, reject_proposal
        data = request.get_json(silent=True) or {}
        card_id = (data.get("card_id") or "").strip()
        mode = (data.get("mode") or "").strip()
        comment = (data.get("comment") or "").strip()
        if not card_id or not mode:
            return jsonify({"error": "card_id and mode required"}), 400
        new_id = create_continuation(card_id, mode=mode, comment=comment)
        # For research-more on a proposal: reject the original so the Deck
        # doesn't show two competing cards. The rewrite lands as a new
        # [PROPOSAL] on the next refetch.
        if mode == "research-more":
            try:
                reject_proposal(card_id, reason=f"refine: {comment[:200]}")
            except Exception as e:
                # Non-fatal — the continuation still exists. Log and move on.
                import logging
                logging.getLogger(__name__).warning(
                    f"research-more: failed to reject parent {card_id}: {e}"
                )
        return jsonify({"ok": True, "parent_id": card_id, "new_task_id": new_id, "mode": mode})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _launch_klava(task_id: str, title: str, body: str,
                  priority: str, source: str, model: str | None = None) -> str | None:
    """Internal helper to launch a klava task session.

    The list/claim/spawn block runs under the consumer flock so the cron
    consumer (tasks.consumer.check_and_execute) can't race with the
    dashboard path. If the lock is held by a peer consumer or a prior
    dashboard launch, raises KlavaLaunchContention so the caller can
    surface a 409.
    """
    if model is None:
        model = _cfg.default_model()
    import threading
    from tasks.queue import update_task_notes, list_tasks as queue_list_tasks
    from tasks.consumer import consumer_lock, KlavaLaunchContention

    tab_id = f"klava-{task_id[:16]}"
    prompt = build_klava_prompt(title, body, priority)
    dummy_sid = f"__klava__{task_id[:8]}"

    with consumer_lock() as acquired:
        if not acquired:
            raise KlavaLaunchContention(
                "Klava consumer holds the queue lock; retry shortly."
            )

        # Re-read queue state under the lock. The cron consumer may have
        # already picked this task up between creation and launch.
        try:
            tasks = queue_list_tasks()
        except Exception:
            tasks = []
        task_obj = next((t for t in tasks if t.id == task_id), None)
        if task_obj is not None and (
            task_obj.status == "running"
            or task_obj.status == "done"
            or task_obj.gtask_status == "completed"
        ):
            raise KlavaLaunchContention(
                f"task {task_id} already {task_obj.status}; refusing to re-spawn."
            )

        # Claim the task: mark running before releasing the lock so a
        # concurrent consumer tick sees status=running and skips it.
        if task_obj is not None:
            task_obj.status = "running"
            task_obj.started_at = datetime.now(timezone.utc).isoformat()
            try:
                update_task_notes(task_obj.id, task_obj.to_notes())
            except Exception:
                pass

        register_task(tab_id, task_id, title, priority, source, body)

        thread = threading.Thread(
            target=_chat_ns._run_claude,
            args=(dummy_sid, prompt, tab_id, None, model, "high", "bypass"),
            daemon=True,
        )
        thread.start()

    # Emit to all dashboard clients so Klava tab can pick it up
    if _socketio:
        _socketio.emit("klava_launched", {
            "task_id": task_id,
            "tab_id": tab_id,
            "title": title,
        }, namespace="/chat")

    return tab_id


# ------------------------------------------------------------------
# Simple data proxies
# ------------------------------------------------------------------

@dashboard_bp.route('/api/deals', methods=['GET'])
def api_deals():
    try:
        return jsonify(collect_deals_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/people', methods=['GET'])
def api_people():
    try:
        return jsonify(collect_people_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/followups', methods=['GET'])
def api_followups():
    try:
        return jsonify(collect_followups_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/calendar', methods=['GET'])
def api_calendar():
    try:
        return jsonify(collect_calendar_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/views', methods=['GET'])
def api_views():
    try:
        return jsonify(collect_views_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/views/open', methods=['POST'])
def api_views_open():
    try:
        data = request.json or {}
        filename = data.get('filename')
        md_path = data.get('path')
        browser = data.get('browser', False)
        title = data.get('title')

        if md_path:
            if '..' in md_path:
                return jsonify({"error": "Invalid path"}), 400
            vault = _cfg.obsidian_vault()
            filepath = vault / md_path
            if not filepath.exists():
                return jsonify({"error": "File not found"}), 404
            url = '/api/markdown/render?path=' + urllib.parse.quote(md_path)
            title = title or filepath.stem
        elif filename:
            if '..' in filename or '/' in filename:
                return jsonify({"error": "Invalid filename"}), 400
            views_dir = _cfg.views_dir()
            filepath = views_dir / filename
            if not filepath.exists():
                return jsonify({"error": "File not found"}), 404
            url = '/api/views/serve/' + urllib.parse.quote(filename)
            title = title or filename
        else:
            return jsonify({"error": "Provide filename or path"}), 400

        if browser:
            subprocess.Popen(["open", str(filepath)])
        else:
            _socketio.emit("views_open", {"url": url, "title": title}, namespace="/chat")

        return jsonify({"status": "ok", "url": url, "title": title})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/views/serve/<filename>', methods=['GET'])
def api_views_serve(filename):
    try:
        if '..' in filename or '/' in filename:
            return "Invalid filename", 400
        views_dir = _cfg.views_dir()
        filepath = views_dir / filename
        if not filepath.exists():
            return "File not found", 404
        content = filepath.read_text(errors="ignore")
        return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        return str(e), 500


@dashboard_bp.route('/api/views/serve-static/<filename>', methods=['GET'])
def api_views_serve_static(filename):
    """Serve static assets (JS/CSS) from the html-view skill directory."""
    try:
        if '..' in filename or '/' in filename:
            return "Invalid filename", 400
        skills_dir = _cfg.html_view_skill_dir()
        filepath = skills_dir / filename
        if not filepath.exists():
            return "File not found", 404
        content = filepath.read_text(errors="ignore")
        mime = 'application/javascript' if filename.endswith('.js') else 'text/css'
        return content, 200, {'Content-Type': f'{mime}; charset=utf-8'}
    except Exception as e:
        return str(e), 500


@dashboard_bp.route('/api/markdown/render', methods=['GET'])
def api_markdown_render():
    try:
        try:
            import markdown as md_lib
        except ImportError:
            return jsonify({
                "error": "markdown package not installed",
                "hint": "pip install markdown (already in requirements.txt; re-run setup.sh)",
            }), 503
        import re as _re

        md_path = request.args.get('path', '')
        if not md_path or '..' in md_path:
            return "Invalid path", 400

        vault = _cfg.obsidian_vault()
        filepath = vault / md_path
        if not filepath.exists():
            return "File not found", 404
        if not str(filepath.resolve()).startswith(str(vault.resolve())):
            return "Path outside vault", 403

        raw = filepath.read_text(errors="ignore")

        if raw.startswith('---'):
            end = raw.find('---', 3)
            if end != -1:
                raw = raw[end + 3:].lstrip('\n')

        raw = _re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', raw)
        raw = _re.sub(r'\[\[([^\]]+)\]\]', r'\1', raw)

        html_body = md_lib.markdown(raw, extensions=['tables', 'fenced_code', 'toc', 'nl2br', 'sane_lists'])

        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{filepath.stem}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
  background: #fafafa; color: #1a1a1a; line-height: 1.7;
  padding: 2rem 2.5rem; max-width: 860px; margin: 0 auto;
}}
h1 {{ font-size: 1.75rem; font-weight: 600; margin: 1.5rem 0 0.75rem; color: #111; }}
h2 {{ font-size: 1.35rem; font-weight: 600; margin: 1.5rem 0 0.5rem; color: #222; }}
h3 {{ font-size: 1.1rem; font-weight: 600; margin: 1.25rem 0 0.4rem; color: #333; }}
h4, h5, h6 {{ font-size: 0.95rem; font-weight: 600; margin: 1rem 0 0.3rem; color: #444; }}
p {{ margin: 0.5rem 0; }}
a {{ color: #2563eb; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
ul, ol {{ padding-left: 1.5rem; margin: 0.5rem 0; }}
li {{ margin: 0.25rem 0; }}
blockquote {{
  border-left: 3px solid #d1d5db; padding: 0.5rem 1rem;
  margin: 0.75rem 0; color: #555; background: #f9fafb;
}}
table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }}
th {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 2px solid #e0e0e0; font-weight: 600; color: #555; font-size: 0.8rem; text-transform: uppercase; }}
td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid #f0f0f0; }}
tr:hover {{ background: #f8f8f8; }}
code {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.85em; background: #f3f4f6; padding: 0.15em 0.35em; border-radius: 3px; }}
pre {{ background: #1e1e1e; color: #d4d4d4; padding: 1rem; border-radius: 6px; overflow-x: auto; margin: 0.75rem 0; }}
pre code {{ background: none; padding: 0; color: inherit; }}
hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 1.5rem 0; }}
img {{ max-width: 100%; border-radius: 4px; }}
.tag {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.75rem; background: #e8f0fe; color: #1a56db; }}
</style>
</head>
<body>
{html_body}
</body>
</html>'''
        return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        return str(e), 500


# ------------------------------------------------------------------
# Sources API - vadimgest source manifests + sync stats
# ------------------------------------------------------------------

@dashboard_bp.route('/api/sources', methods=['GET'])
def api_sources():
    """Return all vadimgest source manifests with sync stats."""
    try:
        import sys
        vg_root = str(Path(__file__).parent.parent.parent)
        if vg_root not in sys.path:
            sys.path.insert(0, vg_root)

        from vadimgest.ingest.sources import get_all_manifests
        from vadimgest.config import load_config
        load_config.cache_clear()
        manifests = get_all_manifests()

        # Enrich with sync stats from JSONL files
        sources_dir = Path(vg_root) / "vadimgest" / "data" / "sources"
        for name, manifest in manifests.items():
            jsonl_file = sources_dir / f"{name}.jsonl"
            if jsonl_file.exists():
                stat = jsonl_file.stat()
                manifest["stats"] = {
                    "file_size": stat.st_size,
                    "last_modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "record_count": _count_jsonl_lines(jsonl_file),
                }
            else:
                manifest["stats"] = None

        return jsonify(manifests)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _count_jsonl_lines(path: Path, sample: bool = True) -> int:
    """Count lines in JSONL. Estimate for files >10MB."""
    size = path.stat().st_size
    if size == 0:
        return 0
    if size < 10_000_000:
        with open(path, 'rb') as f:
            return sum(1 for _ in f)
    with open(path, 'rb') as f:
        chunk = f.read(1_000_000)
        lines_in_chunk = chunk.count(b'\n')
        if lines_in_chunk == 0:
            return 1
        return int(lines_in_chunk * (size / len(chunk)))


# ------------------------------------------------------------------
# Habits API - daily routines tracker
# ------------------------------------------------------------------

HABITS_FILE = Path(__file__).parent.parent.parent / "data" / "habits.json"


def _load_habits() -> dict:
    if HABITS_FILE.exists():
        with open(HABITS_FILE) as f:
            return json.load(f)
    return {"habits": [], "log": {}}


def _save_habits(data: dict):
    HABITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HABITS_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@dashboard_bp.route('/api/habits', methods=['GET'])
def api_habits():
    try:
        data = _load_habits()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        habits = data.get("habits", [])
        log = data.get("log", {})
        today_done = log.get(today, [])

        # Compute streaks per habit
        from datetime import timedelta
        for h in habits:
            streak = 0
            check_date = datetime.now(timezone.utc).date()
            # If not done today, start checking from yesterday
            if h["id"] not in today_done:
                check_date -= timedelta(days=1)
            while True:
                ds = check_date.strftime('%Y-%m-%d')
                if h["id"] in log.get(ds, []):
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break
            h["streak"] = streak
            h["done_today"] = h["id"] in today_done

        # Build last 7 days heatmap
        heatmap = {}
        for i in range(7):
            d = (datetime.now(timezone.utc).date() - timedelta(days=6 - i)).strftime('%Y-%m-%d')
            heatmap[d] = log.get(d, [])

        return jsonify({
            "habits": habits,
            "today": today,
            "today_done": today_done,
            "heatmap": heatmap,
            "total_habits": len(habits),
            "done_count": len(today_done),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


HABITS_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "habits"


@dashboard_bp.route('/api/habits/video/<path:filename>', methods=['GET'])
def api_habits_video(filename):
    from flask import send_from_directory
    safe = HABITS_DATA_DIR.resolve()
    target = (safe / filename).resolve()
    if not str(target).startswith(str(safe)):
        return jsonify({"error": "invalid path"}), 403
    if not target.exists():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(str(safe), filename)


@dashboard_bp.route('/api/habits/toggle', methods=['POST'])
def api_habits_toggle():
    try:
        body = request.get_json() or {}
        habit_id = body.get("habit_id")
        date = body.get("date") or datetime.now(timezone.utc).strftime('%Y-%m-%d')

        if not habit_id:
            return jsonify({"error": "habit_id required"}), 400

        data = _load_habits()
        log = data.setdefault("log", {})
        day_list = log.setdefault(date, [])

        if habit_id in day_list:
            day_list.remove(habit_id)
            toggled = False
        else:
            day_list.append(habit_id)
            toggled = True

        if not day_list:
            del log[date]

        _save_habits(data)
        return jsonify({"ok": True, "habit_id": habit_id, "done": toggled, "date": date})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Settings (config.yaml editor)
# ------------------------------------------------------------------

REDACT_PLACEHOLDER = "•" * 8


@dashboard_bp.route('/api/settings', methods=['GET'])
def api_settings_get():
    """Return schema-driven settings: schema for UI rendering + current values."""
    try:
        return jsonify({
            "schema": _cfg.schema(),
            "config": _cfg.redacted(),
            "secret_paths": sorted(_cfg.SECRET_KEYS),
            "config_path": str(_cfg.DEFAULT_CONFIG_PATH),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/settings/browse', methods=['GET'])
def api_settings_browse():
    """List subdirectories of `path` (default HOME) for the folder picker."""
    import os
    raw = request.args.get("path") or "~"
    base = Path(os.path.expanduser(raw))
    if not base.is_absolute():
        base = Path.home() / raw
    try:
        base = base.resolve()
        if not base.exists() or not base.is_dir():
            return jsonify({"error": "not a directory", "path": str(base)}), 400
        entries = []
        for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith('.') and name not in {".claude"}:
                continue
            entries.append({"name": name, "path": str(child)})
        return jsonify({
            "path": str(base),
            "parent": str(base.parent) if base.parent != base else None,
            "entries": entries,
        })
    except PermissionError:
        return jsonify({"error": "permission denied", "path": str(base)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _set_dotted(target: dict, dotted_path: str, value):
    parts = dotted_path.split(".")
    node = target
    for key in parts[:-1]:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            node[key] = nxt
        node = nxt
    node[parts[-1]] = value


@dashboard_bp.route('/api/settings', methods=['PATCH'])
def api_settings_patch():
    """Apply a flat {dotted.path: value} dict to config.yaml.

    Rules:
    - Values equal to the redaction placeholder are ignored (no overwrite).
    - Empty string on a secret path clears it.
    - Reload happens after successful write so other helpers see the change.
    """
    try:
        import yaml
        payload = request.get_json(force=True, silent=True) or {}
        updates = payload.get("updates") or {}
        if not isinstance(updates, dict):
            return jsonify({"error": "updates must be an object"}), 400

        path = _cfg.DEFAULT_CONFIG_PATH
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        applied = []
        skipped_redacted = []
        for dotted, value in updates.items():
            if value == REDACT_PLACEHOLDER:
                skipped_redacted.append(dotted)
                continue
            _set_dotted(raw, dotted, value)
            applied.append(dotted)

        with open(path, "w") as f:
            yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)

        _cfg.reload()
        return jsonify({
            "ok": True,
            "applied": applied,
            "skipped_redacted": skipped_redacted,
            "config": _cfg.redacted(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Setup status (first-run wizard)
# ------------------------------------------------------------------

# Example-file sentinel values that mean "user hasn't touched this yet".
# Keep in sync with gateway/config.yaml.example.
_SETUP_PLACEHOLDERS = {
    "identity.user_name": {"User", ""},
    "identity.email": {"you@example.com", ""},
    "identity.github_login": {"your-github-username", ""},
}

# Fields that are strictly required before the gateway is usable.
_SETUP_REQUIRED = ("identity.user_name", "identity.email")

# Optional fields — reported as "missing" so the wizard can offer them,
# but not blocking.
_SETUP_OPTIONAL = ("identity.github_login", "telegram.bot_token", "telegram.chat_id")


def _dotted_get(data: dict, path: str):
    node = data
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


@dashboard_bp.route('/api/setup/status', methods=['GET'])
def api_setup_status():
    """Tell the dashboard whether first-run setup is still needed.

    Used by bootstrap.command → opens /dashboard#setup; the frontend
    can poll this to decide whether to surface the wizard.
    """
    try:
        cfg = _cfg.load()
        missing_required = []
        missing_optional = []

        for path in _SETUP_REQUIRED:
            value = _dotted_get(cfg, path)
            placeholders = _SETUP_PLACEHOLDERS.get(path, {""})
            if value is None or value in placeholders:
                missing_required.append(path)

        for path in _SETUP_OPTIONAL:
            value = _dotted_get(cfg, path)
            placeholders = _SETUP_PLACEHOLDERS.get(path, {""})
            if path == "telegram.chat_id":
                if not value or value == 0:
                    missing_optional.append(path)
                continue
            if value is None or value in placeholders:
                missing_optional.append(path)

        setup_section = cfg.get("setup") if isinstance(cfg.get("setup"), dict) else {}
        completed_at = setup_section.get("completed_at") if setup_section else None

        return jsonify({
            "configured": len(missing_required) == 0,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "config_path": str(_cfg.DEFAULT_CONFIG_PATH),
            "wizard_completed_at": completed_at,
        })
    except FileNotFoundError:
        return jsonify({
            "configured": False,
            "missing_required": list(_SETUP_REQUIRED),
            "missing_optional": list(_SETUP_OPTIONAL),
            "error": "config.yaml not found — run setup.sh",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
