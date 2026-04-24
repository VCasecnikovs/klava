#!/usr/bin/env python3
"""Webhook server for Claude Code Gateway.

Provides HTTP endpoints for external triggers:
- GET /health - health check
- GET /status - system status (authenticated)
- POST /trigger/{job_id} - trigger job (authenticated)
- POST /message/{session} - send to session (authenticated)

A2A (Agent-to-Agent) Communication:
- GET /sessions/list - list all active sessions
- POST /sessions/<key>/send - send message to session
- GET /sessions/<key>/history - get session history
Browser GUI:
- WebSocket /chat namespace - real-time Claude Code chat
- GET /api/sessions - list recent CC sessions
"""

import asyncio
import os
import re
import sys
import json
import time
import logging
import mimetypes
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from functools import wraps
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import yaml
from flask import Flask, request, jsonify, send_file
from flask_socketio import SocketIO, emit, Namespace

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))
from lib.claude_executor import ClaudeExecutor
from lib.session_registry import register_session
from lib.process_reaper import start_reaper_thread

# Claude Code SDK for bidirectional streaming
from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, UserMessage, ResultMessage,
    TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock,
    PermissionResultAllow,
    PermissionResultDeny,
    HookMatcher,
)
from claude_agent_sdk._internal.message_parser import StreamEvent

# RateLimitEvent added in SDK 0.1.49 - import defensively so older pinned versions
# still work, even though we now require >= 0.1.62.
try:
    from claude_agent_sdk import RateLimitEvent  # type: ignore
except ImportError:  # pragma: no cover - belt and braces for downgrade
    RateLimitEvent = None  # type: ignore[assignment, misc]

# Native Task* lifecycle messages (SDK 0.1.55+). Used alongside AgentBlockTracker:
# tracker still consumes streamed subagent content for live rendering, but these
# typed messages give authoritative start/progress/done signals with task_id,
# usage, and status — nicer than parsing raw stream events.
try:
    from claude_agent_sdk import (  # type: ignore
        TaskStartedMessage, TaskProgressMessage, TaskNotificationMessage,
    )
except ImportError:  # pragma: no cover
    TaskStartedMessage = TaskProgressMessage = TaskNotificationMessage = None  # type: ignore


_COMMS_MCP_TOOLS = {
    "mcp__telegram__reply": "Telegram",
    "mcp__telegram__edit_message": "Telegram",
    "mcp__google__draft_gmail_message": "Gmail",
    "mcp__whatsapp__send_message": "WhatsApp",
}
_COMMS_BASH_PATTERNS = [
    ("signal-cli send", "Signal"),
    ("signal-cli -a", "Signal"),
    ("wacli send", "WhatsApp"),
]


def _detect_outbound_comms(tool_name: str, input_data: dict) -> dict | None:
    if tool_name in _COMMS_MCP_TOOLS:
        channel = _COMMS_MCP_TOOLS[tool_name]
        message = (input_data.get("text") or input_data.get("message")
                   or input_data.get("body") or str(input_data)[:500])
        recipient = input_data.get("chat_id") or input_data.get("to") or input_data.get("recipient") or ""
        return {"channel": channel, "recipient": str(recipient), "message": str(message)[:1000]}
    if tool_name == "Bash":
        cmd = input_data.get("command", "")
        for pattern, channel in _COMMS_BASH_PATTERNS:
            if pattern in cmd:
                return {"channel": channel, "recipient": "", "message": cmd[:1000]}
    return None


def _execute_artifact_tool(tool_name: str, tool_input: dict) -> dict:
    import subprocess as _sp
    if tool_name in ("mcp__ch-primary__run_select_query", "mcp__ch-secondary__run_select_query"):
        sql = tool_input.get("query") or tool_input.get("sql", "")
        if not sql:
            raise ValueError("Missing query/sql parameter")
        from lib import config as _cfg
        ch = _cfg.clickhouse()
        port = str(ch.get("port", 8443))
        cluster_key = "primary" if tool_name == "mcp__ch-primary__run_select_query" else "secondary"
        cluster = ch.get(cluster_key, {})
        cmd = ["clickhouse-client",
               "--host", cluster.get("host", ""),
               "--port", port, "--secure", "--user", cluster.get("user", ""),
               "--password", cluster.get("password", ""),
               "--query", sql, "--format", "JSON"]
        proc = _sp.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[:500])
        import json as _json
        try:
            return _json.loads(proc.stdout)
        except _json.JSONDecodeError:
            return {"raw": proc.stdout[:2000]}

    raise ValueError(f"Tool '{tool_name}' is not available in artifact mode. "
                     f"Available: mcp__ch-primary__run_select_query, mcp__ch-secondary__run_select_query")


app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Register Blueprints (extracted from this monolith)
from routes.dashboard_api import dashboard_bp, init_dashboard_bp
from routes.a2a import a2a_bp, init_a2a_bp
from routes.agents import agents_bp
from routes.wizard import wizard_bp
from lib.auth import install_mutation_gate
# NOTE: routes/daemons.py used to register /api/daemons + /api/daemons/<label>/
# restart, but dashboard_bp owns those URLs and (because it's registered first)
# was silently shadowing daemons_bp. Removed the registration to delete the
# dead code path; the live implementation in dashboard_api.py includes the
# webhook-server self-kill SIGKILL handling that daemons.py lacked.
app.register_blueprint(dashboard_bp)
app.register_blueprint(a2a_bp)
app.register_blueprint(agents_bp)
app.register_blueprint(wizard_bp)

# Auth gate for state-mutating verbs. Reads webhook.require_auth from
# config.yaml — "auto" (default) lets loopback through unauth'd so the
# local dashboard keeps working with zero ceremony, and refuses the
# same writes from any non-loopback caller. a2a_bp routes already enforce
# token auth via _check_auth(); the gate skips them by endpoint prefix.
# See gateway/lib/auth.py.
install_mutation_gate(app)

# Global config
CONFIG = {}
EXECUTOR = None
SESSIONS_DIR = None  # Set from config in main()

# Centralized config
from lib import config as _gateway_config

# Claude CLI path (from config)
CLAUDE_CLI = _gateway_config.claude_cli()
MCP_CONFIG = str(_gateway_config.mcp_servers_file())

# Directory for Chat CLI output files (detached streaming)
CHAT_STREAM_DIR = Path("/tmp/claude_chat")
CHAT_STREAM_STATE = CHAT_STREAM_DIR / "streaming.json"

# Chat state lock - protects CHAT_SESSIONS, SOCKET_TO_SESSIONS, SESSION_WATCHERS
# LOCK ORDERING: always acquire _chat_lock BEFORE _chat_ui_lock (never reverse)
_chat_lock = threading.RLock()
# Active chat sessions keyed by tab_id (stable frontend UUID, never changes):
# {tab_id: {"process": Popen, "socket_sids": set(), "blocks": [], "started": float,
#            "claude_session_id": str|None, "process_done": bool, "message_queue": []}}
CHAT_SESSIONS = {}
# Map socket_sid -> set of tab_ids this socket is subscribed to (1:many)
SOCKET_TO_SESSIONS = {}
# Session file watchers: {session_id: {"thread": Thread, "socket_sid": str, "stop": Event, "offset": int}}
SESSION_WATCHERS = {}

# Chat UI state (active sessions, names) - persisted to file, synced to all clients
# active_sessions: [{"tab_id": str|null, "session_id": str|null}, ...]
_chat_ui_lock = threading.Lock()
CHAT_UI_STATE_FILE = _gateway_config.state_dir() / "chat-ui.json"
_chat_ui_state = {"version": 2, "active_sessions": [], "session_names": {}, "unread_sessions": [], "drafts": {}, "updated_at": ""}

# Rate limiting (in-memory)
rate_limit_store = defaultdict(list)
MAX_REQUESTS_PER_HOUR = _gateway_config.load().get("webhook", {}).get("rate_limit_per_hour", 100)


def load_config():
    """Load gateway config (raw YAML dict). Use lib.config helpers for typed access."""
    return _gateway_config.load()


def _build_mcp_servers(claude_cli_path: str) -> dict:
    """Build MCP server config from gateway config. Skips entries with missing creds."""
    servers = {
        "browser": {"command": claude_cli_path, "args": ["--claude-in-chrome-mcp"]},
    }
    grafana = _gateway_config.grafana()
    if grafana.get("enabled") and grafana.get("token") and grafana.get("url"):
        servers["grafana"] = {
            "command": grafana.get("mcp_binary", "mcp-grafana"),
            "args": ["--disable-write"],
            "env": {
                "GRAFANA_URL": grafana["url"],
                "GRAFANA_SERVICE_ACCOUNT_TOKEN": grafana["token"],
            },
        }
    return servers


def check_rate_limit(identifier: str) -> bool:
    """Check if request is within rate limit"""
    now = time.time()
    hour_ago = now - 3600

    # Clean old requests
    rate_limit_store[identifier] = [
        ts for ts in rate_limit_store[identifier] if ts > hour_ago
    ]

    # Check limit
    if len(rate_limit_store[identifier]) >= MAX_REQUESTS_PER_HOUR:
        return False

    # Add current request
    rate_limit_store[identifier].append(now)
    return True


def _load_chat_ui_state():
    """Load chat UI state from file."""
    global _chat_ui_state
    with _chat_ui_lock:
        try:
            if CHAT_UI_STATE_FILE.exists():
                with open(CHAT_UI_STATE_FILE) as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return
                data.setdefault("unread_sessions", [])
                data["session_names"] = {k: v for k, v in data.get("session_names", {}).items() if not k.startswith("_pending_")}
                data["unread_sessions"] = [s for s in data.get("unread_sessions", []) if not s.startswith("_pending_")]

                # Migrate v1 (string array) -> v2 (object array)
                raw_active = data.get("active_sessions", [])
                if raw_active and isinstance(raw_active[0], str):
                    app.logger.info(f"Migrating {len(raw_active)} active_sessions from v1 (strings) to v2 (objects)")
                    migrated = []
                    for s in raw_active:
                        if s.startswith("_pending_"):
                            continue
                        migrated.append({"tab_id": None, "session_id": s})
                    data["active_sessions"] = migrated
                    data["version"] = 2

                # Validate: entries with session_id must have file on disk
                valid_active = []
                for entry in data["active_sessions"]:
                    if not isinstance(entry, dict):
                        continue
                    sid = entry.get("session_id")
                    if sid and _find_session_file(sid):
                        valid_active.append(entry)
                    elif not sid and entry.get("tab_id"):
                        # Tab-only entry: only keep if there's an active streaming process
                        # At startup, no CHAT_SESSIONS exist, so these are always orphans
                        tab_id = entry.get("tab_id")
                        if tab_id in CHAT_SESSIONS and not CHAT_SESSIONS[tab_id].get("process_done"):
                            valid_active.append(entry)
                        # else: orphan tab_id without session file, prune
                    # else: orphan, skip

                removed = len(data["active_sessions"]) - len(valid_active)
                if removed:
                    app.logger.info(f"Pruned {removed} orphan active sessions (no file on disk)")
                data["active_sessions"] = valid_active
                data["version"] = 2
                _chat_ui_state = data
                if removed:
                    _save_chat_ui_state()
        except (json.JSONDecodeError, OSError) as e:
            app.logger.warning(f"Failed to load chat UI state: {e}")


def _recover_chat_streams():
    """Recover orphaned Chat CLI processes from previous server instance.

    Reads streaming.json, checks if processes are alive, and registers
    them in CHAT_SESSIONS so frontend can reconnect via watch_session.
    Dead processes just get cleaned up.
    """
    if not CHAT_STREAM_STATE.exists():
        return
    try:
        state = json.loads(CHAT_STREAM_STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if not state:
        return

    recovered = 0
    cleaned = 0
    for tab_id, info in list(state.items()):
        pid = info.get("pid")
        stdout_path = Path(info.get("stdout", ""))
        stderr_path = Path(info.get("stderr", ""))
        started = info.get("started", time.time())
        claude_sid = info.get("claude_session_id")
        prompt = info.get("prompt", "")

        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except (OSError, ProcessLookupError):
                pass

        if alive:
            # Process survived restart - register in CHAT_SESSIONS
            # Frontend will reconnect via watch_session and see realtime blocks
            app.logger.info(f"Recovery: Chat process {tab_id[:12]} (PID {pid}) still alive, registering")
            with _chat_lock:
                CHAT_SESSIONS[tab_id] = {
                    "process": None,  # Can't reattach to Popen object, but PID is tracked
                    "socket_sids": set(),
                    "blocks": [{"type": "user", "id": 0, "text": prompt[:200], "files": []}],
                    "started": started,
                    "last_activity_ts": time.time(),  # Prevent stuck detection from killing recovered sessions
                    "process_done": False,
                    "claude_session_id": claude_sid,
                    "message_queue": [],
                    "_detached_pid": pid,
                    "_stdout_path": str(stdout_path),
                }
            recovered += 1
        else:
            # Process dead - clean up files
            for f in (stdout_path, stderr_path):
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
            cleaned += 1

    # Clear the state file
    try:
        CHAT_STREAM_STATE.write_text("{}")
    except Exception:
        pass

    if recovered or cleaned:
        app.logger.info(f"Chat stream recovery: {recovered} alive, {cleaned} dead/cleaned")


def _save_chat_ui_state():
    """Save chat UI state to file. Caller must hold _chat_ui_lock."""
    _chat_ui_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        CHAT_UI_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(CHAT_UI_STATE_FILE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_chat_ui_state, f, indent=2)
        os.replace(tmp, str(CHAT_UI_STATE_FILE))
    except OSError as e:
        app.logger.error(f"Failed to save chat UI state: {e}")


_cron_ids_cache = {"ids": set(), "ts": 0}

def _get_cron_session_ids():
    """Get set of cron session IDs from registry, cached for 60s."""
    now = time.time()
    if now - _cron_ids_cache["ts"] < 60:
        return _cron_ids_cache["ids"]
    try:
        from lib.session_registry import list_sessions as list_registry
        _cron_ids_cache["ids"] = {e["session_id"] for e in list_registry(session_type="cron", limit=500)}
    except Exception:
        pass
    _cron_ids_cache["ts"] = now
    return _cron_ids_cache["ids"]


def _get_chat_state_snapshot():
    """Get current chat UI state + streaming sessions. Thread-safe."""
    # Heal active_sessions: any currently-live tab in CHAT_SESSIONS should be in
    # active_sessions before we emit. Without this, page reload shows only what
    # was persisted to disk; remaining live sessions trickle in one-by-one as
    # each emits its next event (see auto-insert around line 1369).
    live_tabs = []
    with _chat_lock:
        for _tab_id, _sess in CHAT_SESSIONS.items():
            _is_live = (
                ((_sess.get("process") or _sess.get("sdk_client"))
                 and not _sess.get("process_done")
                 and not _sess.get("session_idle"))
                or (_sess.get("_detached_pid") and not _sess.get("process_done"))
            )
            if _is_live:
                live_tabs.append((_tab_id, _sess.get("claude_session_id")))

    with _chat_ui_lock:
        healed = False
        existing_tabs = {e.get("tab_id") for e in _chat_ui_state["active_sessions"] if e.get("tab_id")}
        for _tab_id, _sid in live_tabs:
            if _tab_id in existing_tabs:
                continue
            matched = False
            if _sid:
                for entry in _chat_ui_state["active_sessions"]:
                    if entry.get("session_id") == _sid and not entry.get("tab_id"):
                        entry["tab_id"] = _tab_id
                        existing_tabs.add(_tab_id)
                        matched = True
                        healed = True
                        break
            if not matched:
                _chat_ui_state["active_sessions"].insert(0, {"tab_id": _tab_id, "session_id": _sid})
                existing_tabs.add(_tab_id)
                healed = True
        if healed:
            if len(_chat_ui_state["active_sessions"]) > 20:
                _chat_ui_state["active_sessions"] = _chat_ui_state["active_sessions"][:20]
            try:
                _save_chat_ui_state()
            except Exception:
                pass
        state = {
            "active_sessions": [dict(e) for e in _chat_ui_state["active_sessions"]],
            "session_names": dict(_chat_ui_state["session_names"]),
            "unread_sessions": list(_chat_ui_state.get("unread_sessions", [])),
            "drafts": dict(_chat_ui_state.get("drafts", {})),
        }
    streaming = []
    with _chat_lock:
        for tab_id, sess in CHAT_SESSIONS.items():
            is_active = (
                (sess.get("process") or sess.get("sdk_client"))
                and not sess.get("process_done")
                and not sess.get("session_idle")
            ) or (sess.get("_detached_pid") and not sess.get("process_done")) or (
                # Startup grace: session just created, SDK not connected yet
                not sess.get("process_done")
                and not sess.get("session_idle")
                and not sess.get("sdk_client")
                and not sess.get("process")
                and (time.time() - sess.get("started", 0)) < 30
            )
            if is_active:
                blocks = sess.get("blocks", [])
                last_event = blocks[-1] if blocks else {}
                elapsed = int(time.time() - sess.get("started", time.time()))
                streaming.append({
                    "id": sess.get("claude_session_id") or tab_id,
                    "tab_id": tab_id,
                    "started": sess.get("started"),
                    "last_event": last_event if isinstance(last_event, dict) else {"type": str(last_event)},
                    "elapsed": elapsed,
                })
    # Also detect external/terminal Claude sessions by scanning JSONL files
    streaming_ids = {s["id"] for s in streaming}
    # Also include all known Chat session IDs (active or recently done) so the
    # scanner doesn't re-add them as "terminal" right after they complete.
    # Also collect start times of active tabs with unresolved claude_session_id
    # so we can skip JSONL files created during their window (they own those files).
    _active_tab_start_times = []
    with _chat_lock:
        for _sess in CHAT_SESSIONS.values():
            _cid = _sess.get("claude_session_id")
            if _cid:
                streaming_ids.add(_cid)
            if _sess.get("sdk_client") and not _sess.get("process_done") and not _cid:
                _active_tab_start_times.append(_sess.get("started", 0))
    external_sids = []
    try:
        claude_config = _gateway_config.claude_config_dir()
        now = time.time()
        for projects_dir in claude_config.glob("projects/*/"):
            if not projects_dir.is_dir():
                continue
            for jsonl_file in projects_dir.glob("*.jsonl"):
                try:
                    mtime = jsonl_file.stat().st_mtime
                    if (now - mtime) < 30:
                        sid = jsonl_file.stem
                        # Skip sessions that only have file-history-snapshot (no real messages)
                        # Read only first 50 lines to avoid hanging on large active JSONL files
                        try:
                            has_real_messages = False
                            with open(jsonl_file, 'r', errors='replace') as _jf:
                                for _line_no, _line in enumerate(_jf):
                                    if _line_no >= 50:
                                        has_real_messages = True  # large file = real session
                                        break
                                    if '"type":"user"' in _line or '"type":"assistant"' in _line:
                                        has_real_messages = True
                                        break
                            if not has_real_messages:
                                continue
                        except OSError:
                            pass
                        if sid not in streaming_ids:
                            stat = jsonl_file.stat()
                            created = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_ctime
                            # Skip JSONL files created during an active Chat tab's window -
                            # they belong to that tab (claude_session_id not yet resolved).
                            if any(created >= t - 2 for t in _active_tab_start_times):
                                continue
                            streaming.append({
                                "id": sid,
                                "tab_id": None,
                                "started": created,
                                "last_event": {"type": "external"},
                                "elapsed": int(now - created),
                                "external": True,
                            })
                            external_sids.append(sid)
                except OSError:
                    continue
    except Exception:
        pass

    # Auto-add external sessions disabled: caused ghost entries and double-streaming.
    # External (terminal) sessions appear in streaming_sessions for the indicator
    # but are NOT auto-inserted into active_sessions sidebar list.

    state["streaming_sessions"] = streaming
    return state


def _broadcast_chat_state():
    """Broadcast current chat UI state to all /chat clients."""
    state = _get_chat_state_snapshot()
    socketio.emit("chat_state_sync", state, namespace="/chat")


def _auto_name_session(session_id: str, prompt_text: str):
    """Generate a short session name via Haiku and save it. Runs in background thread."""
    try:
        # Skip if already named
        with _chat_ui_lock:
            if session_id in _chat_ui_state.get("session_names", {}):
                return

        # Truncate prompt for naming, strip system prefixes
        text = prompt_text.replace("\n", " ").strip()
        if text.startswith("<local-command-caveat>") or text.startswith("<system"):
            # Extract user content after system tags
            for tag_end in ("</local-command-caveat>", "</system>"):
                idx = text.find(tag_end)
                if idx >= 0:
                    text = text[idx + len(tag_end):].strip()
                    break
        text = text[:500]
        if not text or len(text) < 5:
            return

        naming_prompt = (
            "Generate a short title (max 6 words) for this chat session based on the user's first message. "
            "Use sentence case. Reply with ONLY the title, nothing else.\n\n"
            f"User message: {text}"
        )

        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions as SDKOptions, ResultMessage as SDKResult

        async def _query_haiku():
            result_msg = None
            async with ClaudeSDKClient(SDKOptions(
                model="haiku",
                allowed_tools=[],
                cwd=Path.home(),
            )) as client:
                await client.connect()
                await client.query(naming_prompt)
                async for msg in client.receive_response():
                    if isinstance(msg, SDKResult):
                        result_msg = msg
            return result_msg

        result_msg = asyncio.run(_query_haiku())
        if not result_msg or result_msg.is_error:
            app.logger.warning(f"Auto-name failed for {session_id[:12]}")
            return

        title = (result_msg.result or "").strip().strip('"').strip("'")
        if not title or len(title) > 100:
            return

        with _chat_ui_lock:
            # Don't overwrite manual renames
            if session_id not in _chat_ui_state.get("session_names", {}):
                _chat_ui_state.setdefault("session_names", {})[session_id] = title
                _save_chat_ui_state()

        _broadcast_chat_state()
        app.logger.info(f"Auto-named session {session_id[:12]}: {title}")

    except Exception as e:
        app.logger.warning(f"Auto-name error for {session_id[:12]}: {e}")



def rate_limit(f):
    """Decorator to enforce rate limiting"""
    @wraps(f)
    def decorated(*args, **kwargs):
        identifier = request.remote_addr

        if not check_rate_limit(identifier):
            return jsonify({
                "error": "Rate limit exceeded",
                "limit": MAX_REQUESTS_PER_HOUR,
                "period": "1 hour"
            }), 429

        return f(*args, **kwargs)

    return decorated


def require_auth(f):
    """Decorator to require bearer token authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            return jsonify({"error": "Missing Authorization header"}), 401

        if not auth_header.startswith('Bearer '):
            return jsonify({"error": "Invalid Authorization header"}), 401

        token = auth_header[7:]  # Remove 'Bearer '
        expected_token = os.environ.get("WEBHOOK_TOKEN", CONFIG.get("webhook", {}).get("token"))

        if not expected_token or token != expected_token:
            return jsonify({"error": "Invalid token"}), 401

        return f(*args, **kwargs)

    return decorated


# ============================================================
# BROWSER GUI - CHAT WEBSOCKET
# ============================================================

async def _safe_sdk_disconnect(client, timeout=5.0):
    """Disconnect SDK client safely - kill subprocess first to unblock anyio tasks.

    The SDK's disconnect() can hang forever due to anyio task group
    _deliver_cancellation spinning at 100% CPU when subprocess I/O tasks
    can't exit cleanly. Killing the process first unblocks those tasks.
    """
    transport = getattr(getattr(client, "_query", None), "transport", None)
    proc = getattr(transport, "_process", None)
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        await asyncio.wait_for(client.disconnect(), timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        pass


class ChatNamespace(Namespace):
    """WebSocket namespace for real-time Claude Code chat.

    Sessions keyed by session_id (not socket_sid) so they survive reconnects.
    Events are buffered server-side; on reconnect, client can request replay.
    1:many mapping: each socket can subscribe to multiple sessions, each session
    can have multiple listener sockets. SOCKET_TO_SESSIONS maps socket_sid -> set
    of session_ids; CHAT_SESSIONS[sid]["socket_sids"] is a set of socket IDs.
    All shared state (CHAT_SESSIONS, SOCKET_TO_SESSIONS, SESSION_WATCHERS) is
    protected by _chat_lock.
    """

    # --- Stream state persistence for restart recovery ---

    @staticmethod
    def _save_stream_state(tab_id, info):
        """Persist streaming session info for restart recovery."""
        try:
            CHAT_STREAM_DIR.mkdir(parents=True, exist_ok=True)
            state = {}
            if CHAT_STREAM_STATE.exists():
                try:
                    state = json.loads(CHAT_STREAM_STATE.read_text())
                except (json.JSONDecodeError, IOError):
                    state = {}  # Reset on corruption
            state[tab_id] = info
            tmp = str(CHAT_STREAM_STATE) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f)
            os.replace(tmp, str(CHAT_STREAM_STATE))
        except Exception as e:
            app.logger.warning(f"Failed to save stream state for {tab_id[:12]}: {e}")

    @staticmethod
    def _clear_stream_state(tab_id):
        """Remove a session from stream recovery state."""
        try:
            if CHAT_STREAM_STATE.exists():
                try:
                    state = json.loads(CHAT_STREAM_STATE.read_text())
                except (json.JSONDecodeError, IOError):
                    state = {}
                state.pop(tab_id, None)
                tmp = str(CHAT_STREAM_STATE) + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(state, f)
                os.replace(tmp, str(CHAT_STREAM_STATE))
        except Exception:
            pass

    def on_connect(self):
        app.logger.info(f"Chat client connected: {request.sid}")
        # Send current UI state to the new client
        state = _get_chat_state_snapshot()
        emit("chat_state_sync", state)

    def on_disconnect(self):
        sid = request.sid
        app.logger.info(f"Chat client disconnected: {sid}")
        with _chat_lock:
            # Remove this socket from all sessions it was subscribed to
            subscribed = SOCKET_TO_SESSIONS.pop(sid, set())
            for sess_id in subscribed:
                if sess_id in CHAT_SESSIONS:
                    CHAT_SESSIONS[sess_id].get("socket_sids", set()).discard(sid)
                    app.logger.info(f"Session {sess_id[:12]} detached from socket {sid}, process continues")
            # Stop watchers for this socket
            for wid, w in list(SESSION_WATCHERS.items()):
                if w.get("socket_sid") == sid:
                    w["stop"].set()
                    del SESSION_WATCHERS[wid]

    def on_klava_subscribe(self, data):
        """Subscribe this socket to receive live updates from klava task sessions."""
        sid = request.sid
        tab_ids = data.get("tab_ids", [])
        with _chat_lock:
            for tab_id in tab_ids:
                if tab_id in CHAT_SESSIONS:
                    CHAT_SESSIONS[tab_id].setdefault("socket_sids", set()).add(sid)
                    SOCKET_TO_SESSIONS.setdefault(sid, set()).add(tab_id)
        app.logger.info(f"Klava subscribe: socket {sid} -> {len(tab_ids)} tasks")

    def _prepare_prompt(self, prompt, files):
        """Prepend file references to prompt if files attached."""
        if files:
            file_refs = []
            for f in files:
                fpath = f.get("path", "")
                fname = f.get("name", "")
                ftype = f.get("type", "")
                if ftype.startswith("image/"):
                    file_refs.append(f"[Image attached: {fpath}]")
                else:
                    file_refs.append(f"[File attached: {fpath} ({fname})]")
            return "\n".join(file_refs) + "\n\n" + (prompt or "Analyze the attached files.")
        return prompt

    def _emit_queue_update(self, tab_id):
        """Emit current queue state to all subscribed sockets (thread-safe, no request context needed)."""
        with _chat_lock:
            sess = CHAT_SESSIONS.get(tab_id)
            if not sess:
                return
            queue = sess.get("message_queue", [])
            target_sids = set(sess.get("socket_sids", set()))
            queue_data = [{"text": m["prompt"][:80], "index": i} for i, m in enumerate(queue)]

        app.logger.info(f"Emitting queue_update for {tab_id[:12]}: {len(queue_data)} items to {len(target_sids)} sockets")
        for tsid in target_sids:
            try:
                socketio.emit("queue_update", {"queue": queue_data, "tab_id": tab_id}, namespace="/chat", to=tsid)
            except Exception as e:
                app.logger.error(f"Failed to emit queue_update to {tsid}: {e}")

    def _route_message(self, prompt, tab_id, resume_session_id, model, effort, mode, files, socket_sid=None):
        """Core message routing logic shared by WS and HTTP paths.

        Tries to route to an existing session (wake idle, queue to busy).
        If routed, updates state and returns True. If not, returns False
        and caller should spawn _run_claude thread.

        Args:
            socket_sid: WebSocket SID if called from WS handler, None for HTTP.
        """
        msg_data = {"prompt": prompt, "model": model, "effort": effort, "mode": mode, "files": files}
        routed = False
        pending_block = None
        need_broadcast = False

        with _chat_lock:
            if tab_id in CHAT_SESSIONS:
                sess = CHAT_SESSIONS[tab_id]
                proc = sess.get("process")
                sdk_client = sess.get("sdk_client")
                incoming = sess.get("incoming_queue")
                is_alive = not sess.get("process_done") and (
                    sdk_client is not None or (proc and proc.poll() is None)
                )

                if is_alive and incoming:
                    # Register socket SID so it receives realtime events
                    if socket_sid:
                        sess.setdefault("socket_sids", set()).add(socket_sid)
                        SOCKET_TO_SESSIONS.setdefault(socket_sid, set()).add(tab_id)

                    if sess.get("session_idle"):
                        loop = sess.get("sdk_loop")
                        if loop:
                            try:
                                loop.call_soon_threadsafe(incoming.put_nowait, msg_data)
                                sess["session_idle"] = False
                                app.logger.info(f"Woke persistent session for tab {tab_id[:12]}")
                                routed = True
                                sess.setdefault("blocks", []).append({"type": "user", "id": 0, "text": prompt, "files": []})
                            except RuntimeError:
                                app.logger.warning(f"SDK loop closed for tab {tab_id[:12]}, starting new session")
                    else:
                        sess.setdefault("message_queue", []).append(msg_data)
                        app.logger.info(f"Queued message for tab {tab_id[:12]}, queue size: {len(sess['message_queue'])}")
                        routed = True
                        pending_block = {"type": "user", "id": 0, "text": prompt, "files": [], "pending": True}
                        need_broadcast = True

                elif is_alive:
                    # Legacy path: alive but no incoming_queue
                    if socket_sid:
                        sess.setdefault("socket_sids", set()).add(socket_sid)
                        SOCKET_TO_SESSIONS.setdefault(socket_sid, set()).add(tab_id)
                    sess.setdefault("message_queue", []).append(msg_data)
                    app.logger.info(f"Queued message (legacy) for tab {tab_id[:12]}")
                    routed = True
                    pending_block = {"type": "user", "id": 0, "text": prompt, "files": [], "pending": True}
                    need_broadcast = True

        # Emit OUTSIDE lock to avoid nested lock deadlock
        if pending_block:
            self._block_add(tab_id, pending_block)

        # Clear draft BEFORE broadcasting so chat_state_sync arrives with empty draft.
        # Without this, the sender receives chat_state_sync with the old draft value
        # and the frontend restores it after the input was already cleared.
        draft_key = resume_session_id or tab_id
        with _chat_ui_lock:
            _chat_ui_state.setdefault("drafts", {}).pop(draft_key, None)
            if need_broadcast:
                # Auto-add to active list so frontend never sees a streaming entry
                # without a matching active_sessions entry.
                already = any(e.get("tab_id") == tab_id for e in _chat_ui_state["active_sessions"])
                if not already and resume_session_id:
                    for entry in _chat_ui_state["active_sessions"]:
                        if entry.get("session_id") == resume_session_id:
                            entry["tab_id"] = tab_id
                            already = True
                            break
                if not already:
                    _chat_ui_state["active_sessions"].insert(0, {"tab_id": tab_id, "session_id": resume_session_id})
                    if len(_chat_ui_state["active_sessions"]) > 20:
                        _chat_ui_state["active_sessions"] = _chat_ui_state["active_sessions"][:20]
            _save_chat_ui_state()

        emit_kwargs = {"namespace": "/chat"}
        if socket_sid:
            emit_kwargs["skip_sid"] = socket_sid
        socketio.emit("draft_update", {"session_id": draft_key, "text": ""}, **emit_kwargs)

        if need_broadcast:
            _broadcast_chat_state()

        if routed:
            self._emit_queue_update(tab_id)

        return routed

    def on_send_message(self, data):
        """Handle incoming chat message from browser.

        Wire protocol: {prompt, tab_id, resume_session_id?, model, files?}
        - tab_id: stable frontend UUID (required, never changes per chat slot)
        - resume_session_id: real Claude UUID for --resume (optional)
        """
        sid = request.sid
        prompt = data.get("prompt", "").strip()
        tab_id = data.get("tab_id")
        resume_session_id = data.get("resume_session_id")
        model = data.get("model")
        effort = data.get("effort", "high")
        mode = data.get("mode", "bypass")
        files = data.get("files", [])

        app.logger.info(f"Chat send_message: sid={sid}, tab_id={tab_id and tab_id[:12]}, resume={resume_session_id and resume_session_id[:12]}, model={model}, effort={effort}, prompt_len={len(prompt)}, files={len(files)}")

        if not prompt and not files:
            emit("error", {"message": "Empty prompt"})
            return
        if not model:
            emit("error", {"message": "model is required"})
            return
        if not tab_id:
            emit("error", {"message": "tab_id required"})
            return

        prompt = self._prepare_prompt(prompt, files)

        routed = self._route_message(prompt, tab_id, resume_session_id, model, effort, mode, files, socket_sid=sid)
        if routed:
            return

        thread = threading.Thread(
            target=self._run_claude,
            args=(sid, prompt, tab_id, resume_session_id, model, effort, mode),
            daemon=True
        )
        thread.start()

    def on_queue_remove(self, data):
        """Remove a message from the queue by index."""
        index = data.get("index")
        tab_id = data.get("tab_id")
        if index is None or not tab_id:
            return
        with _chat_lock:
            if tab_id in CHAT_SESSIONS:
                queue = CHAT_SESSIONS[tab_id].get("message_queue", [])
                if 0 <= index < len(queue):
                    removed = queue.pop(index)
                    app.logger.info(f"Removed queued message {index} from tab {tab_id[:12]}: {removed['prompt'][:40]}")
        self._emit_queue_update(tab_id)

    def on_draft_save(self, data):
        """Save draft text for a session. {session_id: str, text: str}"""
        session_id = (data or {}).get("session_id")
        text = (data or {}).get("text", "")
        if not session_id:
            return
        with _chat_ui_lock:
            drafts = _chat_ui_state.setdefault("drafts", {})
            if text:
                drafts[session_id] = text
            else:
                drafts.pop(session_id, None)
            _save_chat_ui_state()
        # Broadcast to other clients
        sid = request.sid
        socketio.emit("draft_update", {"session_id": session_id, "text": text},
                       namespace="/chat", skip_sid=sid)

    def on_resume_stream(self, data):
        """Client reconnected - replay buffered events for a tab."""
        sid = request.sid
        tab_id = data.get("tab_id")

        with _chat_lock:
            if not tab_id or tab_id not in CHAT_SESSIONS:
                emit("error", {"message": "No active session to resume"})
                return

            sess = CHAT_SESSIONS[tab_id]
            sess.setdefault("socket_sids", set()).add(sid)
            SOCKET_TO_SESSIONS.setdefault(sid, set()).add(tab_id)
            events_to_replay = list(sess.get("buffer", [])[data.get("buffer_offset", 0):])

        for evt in events_to_replay:
            socketio.emit(evt["event"], evt["data"], namespace="/chat", to=sid)

        app.logger.info(f"Resumed tab {tab_id[:12]} for socket {sid}, replayed {len(events_to_replay)} events")

    def on_cancel(self, data=None):
        """Cancel active request. If data has tab_id, cancel that; otherwise cancel all."""
        sid = request.sid
        target_tab = (data or {}).get("tab_id")
        with _chat_lock:
            if target_tab and target_tab in CHAT_SESSIONS:
                tabs_to_cancel = [target_tab]
            else:
                subscribed = SOCKET_TO_SESSIONS.get(sid, set())
                tabs_to_cancel = list(subscribed)
            targets = []
            for tab_id in tabs_to_cancel:
                if tab_id in CHAT_SESSIONS:
                    sess = CHAT_SESSIONS[tab_id]
                    targets.append((
                        tab_id,
                        sess.get("sdk_client"),
                        sess.get("sdk_loop"),
                        sess.get("process"),
                        sess.get("_detached_pid"),
                    ))

        for tab_id, sdk_client, sdk_loop, proc, detached_pid in targets:
            try:
                if sdk_client and sdk_loop:
                    asyncio.run_coroutine_threadsafe(_safe_sdk_disconnect(sdk_client), sdk_loop)
                    app.logger.info(f"Cancelled SDK session for tab {tab_id[:12]}")
                elif proc and proc.poll() is None:
                    proc.terminate()
                    app.logger.info(f"Cancelled chat process for tab {tab_id[:12]}")
                elif detached_pid:
                    import os as _os, signal as _signal
                    _os.kill(detached_pid, _signal.SIGTERM)
                    app.logger.info(f"Cancelled detached process {detached_pid} for tab {tab_id[:12]}")
                    with _chat_lock:
                        if tab_id in CHAT_SESSIONS:
                            CHAT_SESSIONS[tab_id]["process_done"] = True
                            CHAT_SESSIONS[tab_id].pop("_detached_pid", None)
            except Exception as e:
                app.logger.error(f"Failed to cancel {tab_id[:12]}: {e}")
        emit("cancelled", {})
        _broadcast_chat_state()

    def on_remove_active(self, data):
        """Remove a session from the active list. Matches by tab_id or session_id."""
        tab_id = (data or {}).get("tab_id")
        session_id = (data or {}).get("session_id")
        if not tab_id and not session_id:
            return
        with _chat_ui_lock:
            _chat_ui_state["active_sessions"] = [
                e for e in _chat_ui_state["active_sessions"]
                if not (
                    (tab_id and e.get("tab_id") == tab_id) or
                    (session_id and e.get("session_id") == session_id)
                )
            ]
            _save_chat_ui_state()
        _broadcast_chat_state()

    def on_add_active(self, data):
        """Add an existing session to the active list (e.g. opening from All tab)."""
        session_id = (data or {}).get("session_id")
        if not session_id:
            return
        with _chat_ui_lock:
            # Check both session_id and tab_id fields to avoid duplicates with tab-created sessions
            already = any(
                e.get("session_id") == session_id or e.get("tab_id") == session_id
                for e in _chat_ui_state["active_sessions"]
            )
            if not already:
                _chat_ui_state["active_sessions"].insert(0, {"tab_id": None, "session_id": session_id})
                if len(_chat_ui_state["active_sessions"]) > 20:
                    _chat_ui_state["active_sessions"] = _chat_ui_state["active_sessions"][:20]
                _save_chat_ui_state()
        _broadcast_chat_state()

    def _get_session_process(self, sid, session_id=None):
        """Get the process for a session linked to this socket. Thread-safe.
        If session_id given, return that session's process. Otherwise return
        the first active process from any subscribed session.
        """
        with _chat_lock:
            subscribed = SOCKET_TO_SESSIONS.get(sid, set())
            candidates = [session_id] if session_id and session_id in subscribed else list(subscribed)
            for sess_id in candidates:
                if sess_id in CHAT_SESSIONS:
                    sess = CHAT_SESSIONS[sess_id]
                    proc = sess.get("process")
                    if proc and proc.poll() is None and not sess.get("process_done"):
                        return proc
        return None

    def on_permission_response(self, data):
        """Handle permission response from browser.

        Writes y/n to the Claude CLI process stdin.
        With --dangerously-skip-permissions this is rarely needed,
        but provides a fallback if permissions are re-enabled.
        """
        sid = request.sid
        allow = data.get("allow", False)

        proc = None
        with _chat_lock:
            tab_ids = SOCKET_TO_SESSIONS.get(sid, set())
            for tid in tab_ids:
                sess = CHAT_SESSIONS.get(tid)
                if sess and sess.get("process") and not sess.get("process_done"):
                    proc = sess["process"]
                    break

        if proc and proc.stdin and proc.poll() is None:
            try:
                response = "y\n" if allow else "n\n"
                proc.stdin.write(response.encode())
                proc.stdin.flush()
                app.logger.info(f"Sent permission response to stdin: {response.strip()}")
            except Exception as e:
                app.logger.error(f"Failed to write permission response to stdin: {e}")
        else:
            app.logger.warning("Permission response received but no active process found")

    def on_question_response(self, data):
        """Handle AskUserQuestion response - resolves can_use_tool future or falls back to client.query()."""
        sid = request.sid
        answer = data.get("answer", "")

        question_future = None
        question_input = None
        sdk_client = None
        sdk_loop = None
        with _chat_lock:
            tab_ids = SOCKET_TO_SESSIONS.get(sid, set())
            explicit_tab = data.get("tab_id")
            if explicit_tab:
                tab_ids = {explicit_tab} | (tab_ids or set())
            for tid in tab_ids:
                sess = CHAT_SESSIONS.get(tid)
                if sess and not sess.get("process_done"):
                    question_future = sess.get("_question_future")
                    question_input = sess.get("_question_input")
                    sdk_client = sess.get("sdk_client")
                    sdk_loop = sess.get("sdk_loop")
                    break

        # Primary path: resolve the can_use_tool future with structured answer
        if question_future and sdk_loop and not question_future.done():
            answers_dict = data.get("answers")
            questions_list = data.get("questions")
            qi = question_input or {}
            qs = qi.get("questions", [])

            if answers_dict and questions_list:
                result = PermissionResultAllow(
                    updated_input={"questions": questions_list, "answers": answers_dict}
                )
            elif answer:
                first_q = qs[0].get("question", "Question") if qs else "Question"
                result = PermissionResultAllow(
                    updated_input={"questions": qs, "answers": {first_q: answer}}
                )
            else:
                app.logger.warning("Question response with no answers")
                return
            sdk_loop.call_soon_threadsafe(question_future.set_result, result)
            app.logger.info(f"Resolved question future via can_use_tool")
        # Fallback: send as user message (for sessions without can_use_tool)
        elif sdk_client and sdk_loop and answer:
            asyncio.run_coroutine_threadsafe(sdk_client.query(answer), sdk_loop)
            app.logger.info(f"Sent question response via SDK client.query(): {answer[:50]}")
        else:
            app.logger.warning("Question response received but no active session found")

    def on_plan_approval(self, data):
        """Handle plan approval/rejection from frontend - resolves ExitPlanMode future."""
        sid = request.sid
        approved = data.get("approved", False)
        changes_text = data.get("changes", "")

        plan_future = None
        sdk_loop = None
        with _chat_lock:
            tab_ids = SOCKET_TO_SESSIONS.get(sid, set())
            explicit_tab = data.get("tab_id")
            if explicit_tab:
                tab_ids = {explicit_tab} | (tab_ids or set())
            for tid in tab_ids:
                sess = CHAT_SESSIONS.get(tid)
                if sess and not sess.get("process_done"):
                    plan_future = sess.get("_plan_future")
                    sdk_loop = sess.get("sdk_loop")
                    break

        if plan_future and sdk_loop and not plan_future.done():
            # Update the plan block's answered state for persistence
            resolved_tab = None
            with _chat_lock:
                tab_ids_check = SOCKET_TO_SESSIONS.get(sid, set())
                if explicit_tab:
                    tab_ids_check = {explicit_tab} | (tab_ids_check or set())
                for tid in tab_ids_check:
                    s = CHAT_SESSIONS.get(tid)
                    if s:
                        for blk in reversed(s.get("blocks", [])):
                            if blk.get("type") == "plan" and not blk.get("active"):
                                blk["answered"] = approved
                                resolved_tab = tid
                                plan_block_id = blk.get("id")
                                break
                        break
            if resolved_tab and plan_block_id is not None:
                self._block_update(resolved_tab, plan_block_id, {"answered": approved})

            if approved:
                result = PermissionResultAllow(updated_input=data.get("input", {}))
                sdk_loop.call_soon_threadsafe(plan_future.set_result, result)
                app.logger.info("Plan approved by user via plan_approval event")
            else:
                result = PermissionResultDeny(reason=changes_text or "User rejected the plan")
                sdk_loop.call_soon_threadsafe(plan_future.set_result, result)
                app.logger.info(f"Plan rejected by user: {changes_text[:100]}")
        else:
            app.logger.warning("Plan approval received but no active plan future found")

    def on_comms_approval(self, data):
        """Handle outbound comms approval/rejection from frontend."""
        sid = request.sid
        approved = data.get("approved", False)
        edited_message = data.get("edited_message", "")

        comms_future = None
        comms_input = None
        sdk_loop = None
        with _chat_lock:
            tab_ids = SOCKET_TO_SESSIONS.get(sid, set())
            explicit_tab = data.get("tab_id")
            if explicit_tab:
                tab_ids = {explicit_tab} | (tab_ids or set())
            for tid in tab_ids:
                sess = CHAT_SESSIONS.get(tid)
                if sess and not sess.get("process_done"):
                    comms_future = sess.get("_comms_future")
                    comms_input = sess.get("_comms_input")
                    sdk_loop = sess.get("sdk_loop")
                    break

        if comms_future and sdk_loop and not comms_future.done():
            if approved:
                updated = comms_input or {}
                if edited_message:
                    for key in ("text", "message", "body", "command"):
                        if key in updated:
                            updated[key] = edited_message
                            break
                result = PermissionResultAllow(updated_input=updated)
                sdk_loop.call_soon_threadsafe(comms_future.set_result, result)
                app.logger.info(f"Comms approved by user")
            else:
                result = PermissionResultDeny(reason="User rejected outbound message")
                sdk_loop.call_soon_threadsafe(comms_future.set_result, result)
                app.logger.info("Comms rejected by user")
        else:
            app.logger.warning("Comms approval received but no active comms future found")

    def on_artifact_tool_call(self, data):
        """Proxy MCP tool calls from artifact iframes."""
        call_id = data.get("call_id", "")
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        tab_id = data.get("tab_id")

        def _run():
            try:
                result = _execute_artifact_tool(tool_name, tool_input)
                self._emit_buffered(tab_id, "artifact_tool_result", {
                    "call_id": call_id, "result": result,
                })
            except Exception as e:
                self._emit_buffered(tab_id, "artifact_tool_result", {
                    "call_id": call_id, "error": str(e),
                })

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _emit_buffered(self, tab_id, event, data):
        """Emit to ALL subscribed clients and buffer for replay on reconnect.

        Every event includes tab_id so the frontend can route events to
        the correct chat slot even when the user is viewing a different one.
        """
        tagged_data = {**data, "tab_id": tab_id}
        with _chat_lock:
            sess = CHAT_SESSIONS.get(tab_id)
            if not sess:
                return
            buf = sess.setdefault("buffer", [])
            buf.append({"event": event, "data": tagged_data})
            if len(buf) > 500:
                sess["buffer"] = buf[-500:]
            target_sids = set(sess.get("socket_sids", set()))

        for target_sid in target_sids:
            try:
                socketio.emit(event, tagged_data, namespace="/chat", to=target_sid)
            except Exception:
                pass  # Socket may have disconnected

    def _block_add(self, tab_id, block):
        """Add block to realtime Ground Truth and emit to all subscribed clients."""
        with _chat_lock:
            sess = CHAT_SESSIONS.get(tab_id)
            if not sess:
                return
            sess["last_activity_ts"] = time.time()
            blocks = sess.setdefault("blocks", [])
            block["id"] = len(blocks)
            blocks.append(block)
            target_sids = set(sess.get("socket_sids", set()))
        for sid in target_sids:
            try:
                socketio.emit("realtime_block_add", {"block": block, "tab_id": tab_id}, namespace="/chat", to=sid)
            except Exception:
                pass

    def _block_update(self, tab_id, block_id, patch):
        """Update existing block in realtime GT and emit patch to clients."""
        with _chat_lock:
            sess = CHAT_SESSIONS.get(tab_id)
            if not sess or block_id >= len(sess.get("blocks", [])):
                return
            sess["last_activity_ts"] = time.time()
            sess["blocks"][block_id].update(patch)
            target_sids = set(sess.get("socket_sids", set()))
        for sid in target_sids:
            try:
                socketio.emit("realtime_block_update", {"id": block_id, "patch": patch, "tab_id": tab_id}, namespace="/chat", to=sid)
            except Exception:
                pass

    def _run_claude(self, sid, prompt, tab_id, resume_session_id, model, effort="high", mode="bypass", fork_session=False):
        """Run claude via SDK and stream results via WebSocket."""
        try:
            app.logger.info(f"Starting SDK session for tab {tab_id[:12]}, resume={resume_session_id and resume_session_id[:12]}, model={model}, mode={mode}, fork={fork_session}")
            asyncio.run(self._run_claude_sdk(sid, prompt, tab_id, resume_session_id, model, effort, mode, fork_session=fork_session))
        except BaseException as e:
            # Must catch BaseException: asyncio.CancelledError is BaseException in Python 3.9+
            # and anyio/SDK disconnect bugs propagate it through asyncio.run()
            if not isinstance(e, (KeyboardInterrupt, SystemExit)):
                app.logger.error(f"SDK session crashed for tab {tab_id[:12]}: {e}", exc_info=True)
                self._block_add(tab_id, {"type": "error", "message": str(e)})
            self._clear_stream_state(tab_id)
            with _chat_lock:
                if tab_id in CHAT_SESSIONS:
                    CHAT_SESSIONS[tab_id]["process_done"] = True
            _broadcast_chat_state()
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise

    # Idle timeout for persistent sessions (seconds).
    # After this period with no new messages, the SDK process is shut down.
    PERSISTENT_IDLE_TIMEOUT = 300

    async def _run_claude_sdk(self, sid, prompt, tab_id, resume_session_id, model, effort="high", mode="bypass", fork_session=False):
        """Async implementation using claude-code-sdk for bidirectional streaming.

        Runs as a persistent session: after processing a turn, waits for the next
        message via incoming_queue instead of disconnecting. This avoids re-spawning
        the SDK subprocess (and re-initializing MCP servers) for every message.
        """
        import time as _time

        # ── CHAT_SESSIONS init ─────────────────────────────────────────────
        incoming = asyncio.Queue()  # Thread-safe via loop.call_soon_threadsafe

        with _chat_lock:
            existing = CHAT_SESSIONS.get(tab_id)
            existing_queue     = existing.get("message_queue", []) if existing else []
            existing_sids      = existing.get("socket_sids", set()) if existing else set()
            existing_claude_id = resume_session_id or (existing.get("claude_session_id") if existing else None)

            CHAT_SESSIONS[tab_id] = {
                "sdk_client":    None,
                "sdk_loop":      None,
                "sdk_queue":     None,
                "last_activity_ts": _time.time(),
                "incoming_queue": incoming,
                "process":       None,
                "socket_sids":   existing_sids | {sid},
                "blocks":        [{"type": "user", "id": 0, "text": prompt, "files": []}],
                "buffer":        [],
                "started":       _time.time(),
                "process_done":  False,
                "session_idle":  False,
                "claude_session_id": existing_claude_id,
                "message_queue": existing_queue,
            }
            SOCKET_TO_SESSIONS.setdefault(sid, set()).add(tab_id)

        # ── Bridge SESSION_WATCHERS ────────────────────────────────────────
        bridged_sids = []
        if existing_claude_id:
            with _chat_lock:
                watcher = SESSION_WATCHERS.pop(existing_claude_id, None)
                if watcher:
                    watcher["stop"].set()
                    watcher_sid = watcher.get("socket_sid")
                    if watcher_sid:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            sess["socket_sids"].add(watcher_sid)
                            SOCKET_TO_SESSIONS.setdefault(watcher_sid, set()).add(tab_id)
                            bridged_sids.append(watcher_sid)
                            app.logger.info(f"Bridged watcher {watcher_sid} to tab {tab_id[:12]}")

        user_block = {"type": "user", "id": 0, "text": prompt, "files": []}
        for bsid in bridged_sids:
            try:
                socketio.emit("realtime_block_add", {"block": user_block, "tab_id": tab_id},
                              namespace="/chat", to=bsid)
            except Exception:
                pass

        # Auto-add to active sidebar list BEFORE broadcasting so frontend never
        # sees a streaming entry without a matching active_sessions entry (prevents
        # synthetic tab_id ghost entries in allSessions).
        app.logger.info(f"Auto-add to active: tab={tab_id[:12]}, resume={resume_session_id and resume_session_id[:12]}")
        with _chat_ui_lock:
            already = any(e.get("tab_id") == tab_id for e in _chat_ui_state["active_sessions"])
            if not already and resume_session_id:
                for entry in _chat_ui_state["active_sessions"]:
                    if entry.get("session_id") == resume_session_id:
                        entry["tab_id"] = tab_id
                        already = True
                        break
            if not already:
                _chat_ui_state["active_sessions"].insert(0, {"tab_id": tab_id, "session_id": resume_session_id})
                app.logger.info(f"Inserted tab={tab_id[:12]} into active_sessions, now {len(_chat_ui_state['active_sessions'])} entries")
                if len(_chat_ui_state["active_sessions"]) > 20:
                    _chat_ui_state["active_sessions"] = _chat_ui_state["active_sessions"][:20]
            else:
                app.logger.info(f"Tab {tab_id[:12]} already in active_sessions")
            _save_chat_ui_state()
        _broadcast_chat_state()

        # ── Tracking state ─────────────────────────────────────────────────
        result_data          = None
        last_thinking_len    = 0
        last_text_len        = 0
        last_tool_ids        = set()
        tool_id_to_name      = {}
        current_thinking_id  = None
        current_assistant_id = None
        pending_tools        = []
        tool_flush_timer     = None
        tool_name            = ""
        tool_input           = {}
        loading_block_id     = None

        # Agent block tracker for nested subagent rendering
        from lib.agent_blocks import AgentBlockTracker

        def _agent_on_add(block):
            self._block_add(tab_id, block)
            with _chat_lock:
                s = CHAT_SESSIONS.get(tab_id)
                if s:
                    return len(s.get("blocks", [])) - 1
            return 0

        def _agent_on_update(block_id, patch):
            self._block_update(tab_id, block_id, patch)

        agent_tracker = AgentBlockTracker(on_add=_agent_on_add, on_update=_agent_on_update)

        self._block_add(tab_id, {"type": "loading"})
        with _chat_lock:
            sess = CHAT_SESSIONS.get(tab_id)
            if sess:
                loading_block_id = len(sess.get("blocks", [])) - 1

        def _flush_tools():
            nonlocal pending_tools
            if not pending_tools:
                return
            if len(pending_tools) > 1:
                self._block_add(tab_id, {
                    "type":  "tool_group",
                    "label": f"{len(pending_tools)} parallel calls",
                    "tools": list(pending_tools),
                })
            else:
                self._block_add(tab_id, pending_tools[0])
            pending_tools = []

        # ── SDK setup ──────────────────────────────────────────────────────
        env = {}

        # extra_args keys must NOT have -- prefix (SDK adds it)
        # No mcp-config override - SDK reads from CLAUDE_CONFIG_DIR by default
        extra_args = {}

        # Use resume_session_id if provided (the real Claude session UUID)
        real_resume = resume_session_id if resume_session_id else None

        # Prevent "cannot be launched inside another Claude Code session" error:
        # SDK merges os.environ into subprocess env, and CLAUDECODE may leak
        # from parent process or shell init. Force-unset it.
        env["CLAUDECODE"] = ""
        # Clean PATH: remove pyenv shims that cause shell-init getcwd() EINTR
        local_bin = str(Path.home() / ".local" / "bin")
        nvm_bin = str(_gateway_config.node_bin())
        brew_bin = str(_gateway_config.homebrew_bin())
        env["PATH"] = f"{local_bin}:{nvm_bin}:{brew_bin}:/usr/local/bin:/usr/bin:/bin"
        perm_mode = "plan" if mode == "plan" else "bypassPermissions"

        # AskUserQuestion + ExitPlanMode support: use can_use_tool callback to
        # intercept these tools and wait for frontend answers/approval.
        question_future: asyncio.Future | None = None
        plan_future: asyncio.Future | None = None

        async def _can_use_tool(tool_name: str, input_data: dict, context):
            nonlocal question_future, plan_future
            if tool_name == "AskUserQuestion":
                # Store future in session so on_question_response can resolve it
                question_future = asyncio.get_running_loop().create_future()
                with _chat_lock:
                    sess = CHAT_SESSIONS.get(tab_id)
                    if sess:
                        sess["_question_future"] = question_future
                        sess["_question_input"] = input_data
                # Notify Klava tab if this is a klava task
                if tab_id.startswith("klava-"):
                    try:
                        from lib.klava_manager import get_task as _klava_get
                        km = _klava_get(tab_id)
                        if km:
                            socketio.emit("klava_question", {
                                "task_id": km["task_id"],
                                "tab_id": tab_id,
                                "title": km["title"],
                                "questions": input_data.get("questions", []),
                            }, namespace="/chat")
                    except Exception:
                        pass
                # Wait for frontend to answer (timeout 5 min)
                try:
                    result = await asyncio.wait_for(question_future, timeout=300)
                    return result
                except asyncio.TimeoutError:
                    return PermissionResultAllow(updated_input=input_data)
                finally:
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            sess.pop("_question_future", None)
                            sess.pop("_question_input", None)
            elif tool_name == "ExitPlanMode":
                plan_future = asyncio.get_running_loop().create_future()
                with _chat_lock:
                    sess = CHAT_SESSIONS.get(tab_id)
                    if sess:
                        sess["_plan_future"] = plan_future
                # Emit plan_approval_request so frontend shows Approve/Reject UI
                self._emit_buffered(tab_id, "plan_approval_request", {"tab_id": tab_id})
                try:
                    result = await asyncio.wait_for(plan_future, timeout=600)
                    return result
                except asyncio.TimeoutError:
                    return PermissionResultAllow(updated_input=input_data)
                finally:
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            sess.pop("_plan_future", None)
            # Comms gate: intercept outbound messages for user approval
            comms_info = _detect_outbound_comms(tool_name, input_data)
            if comms_info:
                comms_future = asyncio.get_running_loop().create_future()
                with _chat_lock:
                    sess = CHAT_SESSIONS.get(tab_id)
                    if sess:
                        sess["_comms_future"] = comms_future
                        sess["_comms_input"] = input_data
                self._emit_buffered(tab_id, "comms_approval_request", {
                    "tab_id": tab_id,
                    "channel": comms_info["channel"],
                    "recipient": comms_info["recipient"],
                    "message": comms_info["message"],
                    "tool_name": tool_name,
                })
                try:
                    result = await asyncio.wait_for(comms_future, timeout=600)
                    return result
                except asyncio.TimeoutError:
                    return PermissionResultDeny(reason="Comms approval timed out")
                finally:
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            sess.pop("_comms_future", None)
                            sess.pop("_comms_input", None)
            # Auto-allow all other tools
            return PermissionResultAllow(updated_input=input_data)

        # Parse 1M context flag from model string (e.g. "opus[1m]" -> model="opus", betas=[...])
        chat_betas = None
        if model and "[1m]" in model:
            model = model.replace("[1m]", "")
            chat_betas = ["context-1m-2025-08-07"]

        # Map UI effort → SDK thinking / effort kwargs.
        #
        # Opus 4.7 changed the defaults: thinking is omitted from responses
        # unless the caller opts in with `display: "summarized"`. Without it
        # CLI opens a thinking content-block but emits zero thinking_delta
        # events, so the UI sees long pauses but no thinking bubble.
        # https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
        #
        # The `enabled` thinking config with budget_tokens is no longer
        # supported on 4.7+ — docs say only `adaptive` is accepted. Stick
        # to adaptive everywhere except when the user explicitly disables.
        #
        #   "none"     → thinking disabled, no effort
        #   "adaptive" → adaptive thinking with display=summarized, no effort
        #   low/medium/high/max → effort kwarg + adaptive+summarized thinking
        #
        # Requires SDK ≥ 0.1.66 (introduces ThinkingConfigAdaptive.display)
        # and CLI ≥ 2.1.119 (proper 4.7 alias resolution).
        effort_kwarg = effort
        thinking_kwarg = None
        if effort == "none":
            thinking_kwarg = {"type": "disabled"}
            effort_kwarg = None
        elif effort == "adaptive":
            thinking_kwarg = {"type": "adaptive", "display": "summarized"}
            effort_kwarg = None
        else:
            thinking_kwarg = {"type": "adaptive", "display": "summarized"}

        # SubagentStart / SubagentStop hooks: observability on subagent
        # lifecycle — separate signal from the TaskStarted/Notification
        # messages (those tell us *that* a task started; hooks give us
        # agent_id + agent_type + transcript_path, useful for linking
        # to on-disk session files and for budget/resource accounting).
        async def _hook_subagent_start(input_data, _tool_use_id, _ctx):
            try:
                app.logger.info(
                    f"[subagent_start] tab={tab_id[:12]} "
                    f"agent_id={input_data.get('agent_id')} "
                    f"type={input_data.get('agent_type')}"
                )
            except Exception:
                pass
            return {}

        async def _hook_subagent_stop(input_data, _tool_use_id, _ctx):
            try:
                app.logger.info(
                    f"[subagent_stop] tab={tab_id[:12]} "
                    f"agent_id={input_data.get('agent_id')} "
                    f"type={input_data.get('agent_type')} "
                    f"transcript={input_data.get('agent_transcript_path')}"
                )
            except Exception:
                pass
            return {}

        # can_use_tool intercepts AskUserQuestion and waits for frontend answer.
        # For all other tools, auto-allow immediately.
        # permission_mode stays bypassPermissions so normal tools aren't blocked.
        # SDK adds --permission-prompt-tool stdio automatically for control protocol.
        options = ClaudeAgentOptions(
            model=model,  # required from frontend, no fallback
            allowed_tools=["*"],
            resume=real_resume,
            fork_session=fork_session,
            permission_mode=perm_mode,
            can_use_tool=_can_use_tool if perm_mode != "plan" else None,
            include_partial_messages=True,
            cwd=Path.home(),
            env=env,
            extra_args=extra_args,
            # Use local CLI instead of SDK-bundled binary to avoid version mismatch.
            # Bundled CLI (2.1.71) has session path resolution bugs vs local (2.1.77+).
            cli_path=CLAUDE_CLI,
            setting_sources=["user", "project"],
            # Explicitly load browser (claude-in-chrome) MCP via --mcp-config flag.
            # This bypasses the claudeInChromeDefaultEnabled built-in handling which
            # silently fails in SDK subprocess context.
            mcp_servers=_build_mcp_servers(CLAUDE_CLI),
            hooks={
                "SubagentStart": [HookMatcher(hooks=[_hook_subagent_start])],
                "SubagentStop":  [HookMatcher(hooks=[_hook_subagent_stop])],
            },
            **({"effort": effort_kwarg} if effort_kwarg else {}),
            **({"thinking": thinking_kwarg} if thinking_kwarg else {}),
            **({"betas": chat_betas} if chat_betas else {}),
        )

        loop = asyncio.get_running_loop()
        client = ClaudeSDKClient(options)
        msg_queue = asyncio.Queue()

        async def _message_stream():
            """Async generator: yields initial prompt, then keeps stdin open (keepalive).

            Queued messages are sent via client.query() in the ResultMessage handler,
            not through this generator (subprocess batches pre-loaded stdin into one turn).
            Generator stays alive until sentinel to prevent stdin from closing.
            """
            yield {"type": "user", "message": {"role": "user", "content": prompt}, "parent_tool_use_id": None, "session_id": "default"}
            # Block until sentinel - keeps stdin open for client.query() calls
            await msg_queue.get()  # Only None (sentinel) comes here

        with _chat_lock:
            if tab_id in CHAT_SESSIONS:
                CHAT_SESSIONS[tab_id]["sdk_client"] = client
                CHAT_SESSIONS[tab_id]["sdk_loop"]   = loop
                CHAT_SESSIONS[tab_id]["sdk_queue"]  = msg_queue

        _broadcast_chat_state()
        app.logger.info(f"SDK connecting: model={model}, resume={real_resume and real_resume[:12]}")

        try:
            # Connect with streaming input generator (Anthropic recommended pattern).
            # Messages yielded by _message_stream() go directly to Claude's stdin.
            await client.connect(prompt=_message_stream())

            # ── Message processing loop (one receive_response per turn) ──
            new_session_id = None
            deferred_pending = []  # Pending user blocks removed during queue processing
            while True:
                async for message in client.receive_response():
                    # Native Task* lifecycle messages (SDK 0.1.55+). Hand to the
                    # agent tracker first so it can annotate the existing block
                    # with task_id, usage, status. Not a replacement for stream
                    # events — those still drive live rendering.
                    if TaskStartedMessage is not None and isinstance(message, TaskStartedMessage):
                        agent_tracker.handle_task_started(message)
                        continue
                    if TaskProgressMessage is not None and isinstance(message, TaskProgressMessage):
                        agent_tracker.handle_task_progress(message)
                        continue
                    if TaskNotificationMessage is not None and isinstance(message, TaskNotificationMessage):
                        agent_tracker.handle_task_notification(message)
                        continue

                    if isinstance(message, StreamEvent):
                        # Route subagent stream events into agent block
                        if agent_tracker.handle_stream_event(message):
                            continue
                        event = message.event
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})

                            if delta.get("type") == "text_delta":
                                text_chunk = delta.get("text", "")
                                if loading_block_id is not None:
                                    self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                                    loading_block_id = None
                                if current_thinking_id is not None:
                                    current_thinking_id = None
                                if current_assistant_id is None:
                                    self._block_add(tab_id, {"type": "assistant", "text": ""})
                                    with _chat_lock:
                                        s = CHAT_SESSIONS.get(tab_id)
                                        if s:
                                            current_assistant_id = len(s.get("blocks", [])) - 1
                                last_text_len += len(text_chunk)
                                accumulated = ""
                                with _chat_lock:
                                    s = CHAT_SESSIONS.get(tab_id)
                                    if s and current_assistant_id is not None:
                                        blk = s["blocks"][current_assistant_id]
                                        blk["text"] = blk.get("text", "") + text_chunk
                                        accumulated = blk["text"]
                                self._block_update(tab_id, current_assistant_id, {"text": accumulated})

                            elif delta.get("type") == "thinking_delta":
                                thinking_chunk = delta.get("thinking", "")
                                if loading_block_id is not None:
                                    self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                                    loading_block_id = None
                                if current_thinking_id is None:
                                    self._block_add(tab_id, {"type": "thinking", "text": "", "words": 0, "preview": ""})
                                    with _chat_lock:
                                        s = CHAT_SESSIONS.get(tab_id)
                                        if s:
                                            current_thinking_id = len(s.get("blocks", [])) - 1
                                last_thinking_len += len(thinking_chunk)
                                full_t = ""
                                words_t = 0
                                preview_t = ""
                                with _chat_lock:
                                    s = CHAT_SESSIONS.get(tab_id)
                                    if s and current_thinking_id is not None:
                                        blk = s["blocks"][current_thinking_id]
                                        blk["text"] = blk.get("text", "") + thinking_chunk
                                        full_t    = blk["text"]
                                        words_t   = len(full_t.split())
                                        preview_t = full_t[:60].replace("\n", " ")
                                self._block_update(tab_id, current_thinking_id, {
                                    "text": full_t, "words": words_t, "preview": preview_t,
                                })

                    elif isinstance(message, AssistantMessage):
                        # Route subagent messages into parent agent block
                        if agent_tracker.handle_message(message):
                            continue

                        for block in message.content:

                            if isinstance(block, TextBlock):
                                full_text = block.text
                                if len(full_text) > last_text_len:
                                    if loading_block_id is not None:
                                        self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                                        loading_block_id = None
                                    current_thinking_id = None
                                    if current_assistant_id is None:
                                        self._block_add(tab_id, {"type": "assistant", "text": ""})
                                        with _chat_lock:
                                            s = CHAT_SESSIONS.get(tab_id)
                                            if s:
                                                current_assistant_id = len(s.get("blocks", [])) - 1
                                    with _chat_lock:
                                        s = CHAT_SESSIONS.get(tab_id)
                                        if s and current_assistant_id is not None:
                                            s["blocks"][current_assistant_id]["text"] = full_text
                                    self._block_update(tab_id, current_assistant_id, {"text": full_text})
                                    last_text_len = len(full_text)

                            elif isinstance(block, ThinkingBlock):
                                full_thinking = block.thinking
                                if len(full_thinking) > last_thinking_len:
                                    if loading_block_id is not None:
                                        self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                                        loading_block_id = None
                                    if current_thinking_id is None:
                                        self._block_add(tab_id, {"type": "thinking", "text": "", "words": 0, "preview": ""})
                                        with _chat_lock:
                                            s = CHAT_SESSIONS.get(tab_id)
                                            if s:
                                                current_thinking_id = len(s.get("blocks", [])) - 1
                                    words   = len(full_thinking.split())
                                    preview = full_thinking[:60].replace("\n", " ")
                                    with _chat_lock:
                                        s = CHAT_SESSIONS.get(tab_id)
                                        if s and current_thinking_id is not None:
                                            blk = s["blocks"][current_thinking_id]
                                            blk["text"]    = full_thinking
                                            blk["words"]   = words
                                            blk["preview"] = preview
                                    self._block_update(tab_id, current_thinking_id, {
                                        "text": full_thinking, "words": words, "preview": preview,
                                    })
                                    last_thinking_len = len(full_thinking)

                            elif isinstance(block, ToolUseBlock):
                                tool_id = block.id
                                if tool_id in last_tool_ids:
                                    continue
                                last_tool_ids.add(tool_id)
                                tool_name  = block.name
                                tool_input = block.input
                                tool_id_to_name[tool_id] = tool_name

                                if pending_tools:
                                    _flush_tools()
                                current_assistant_id = None
                                current_thinking_id  = None
                                if loading_block_id is not None:
                                    self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                                    loading_block_id = None

                                # Agent (Task) tools get special nested block
                                if agent_tracker.handle_tool_use(block):
                                    last_text_len        = 0
                                    last_thinking_len    = 0
                                    continue

                                if tool_name == "AskUserQuestion":
                                    self._block_add(tab_id, {
                                        "type":      "question",
                                        "questions": tool_input.get("questions", []),
                                        "answered":  False,
                                    })
                                    last_text_len        = 0
                                    last_thinking_len    = 0
                                    current_assistant_id = None
                                    current_thinking_id  = None
                                elif tool_name == "EnterPlanMode":
                                    self._block_add(tab_id, {"type": "plan", "active": True})
                                elif tool_name == "ExitPlanMode":
                                    self._block_add(tab_id, {"type": "plan", "active": False})
                                else:
                                    tool_block = {
                                        "type":       "tool_use",
                                        "tool":       tool_name,
                                        "input":      tool_input,
                                        "running":    True,
                                        "start_time": _time.time(),
                                    }
                                    pending_tools.append(tool_block)
                                    if tool_flush_timer:
                                        tool_flush_timer.cancel()
                                    tool_flush_timer = threading.Timer(0.15, _flush_tools)
                                    tool_flush_timer.start()

                    elif isinstance(message, UserMessage):
                        # Route subagent messages into parent agent block
                        if agent_tracker.handle_message(message):
                            continue

                        # Tool results arrive as UserMessage with ToolResultBlock content
                        if tool_flush_timer:
                            tool_flush_timer.cancel()
                            tool_flush_timer = None
                        if pending_tools:
                            _flush_tools()

                        content_list = message.content if isinstance(message.content, list) else []
                        for block in content_list:
                            if not isinstance(block, ToolResultBlock):
                                continue

                            # Check if this is an agent completion result
                            if agent_tracker.handle_tool_result(block):
                                continue

                            result_tool_name = tool_id_to_name.get(block.tool_use_id, tool_name)
                            content = block.content
                            if isinstance(content, list):
                                content = "\n".join(
                                    c.get("text", "") for c in content
                                    if isinstance(c, dict) and c.get("type") == "text"
                                )
                            content = str(content or "")

                            tool_update_patch    = None
                            tool_update_block_id = None
                            with _chat_lock:
                                s = CHAT_SESSIONS.get(tab_id)
                                if s:
                                    for blk in reversed(s.get("blocks", [])):
                                        if blk.get("type") == "tool_use" and blk.get("running"):
                                            dm = int((_time.time() - blk.get("start_time", _time.time())) * 1000)
                                            blk["running"]     = False
                                            blk["duration_ms"] = dm
                                            tool_update_block_id = blk["id"]
                                            tool_update_patch    = {"running": False, "duration_ms": dm}
                                            break
                                        elif blk.get("type") == "tool_group":
                                            for t in blk.get("tools", []):
                                                if t.get("running"):
                                                    t["running"]     = False
                                                    t["duration_ms"] = int((_time.time() - t.get("start_time", _time.time())) * 1000)
                                                    tool_update_block_id = blk["id"]
                                                    tool_update_patch    = {"tools": [dict(tt) for tt in blk["tools"]]}
                                                    break
                                            break
                            if tool_update_patch is not None:
                                self._block_update(tab_id, tool_update_block_id, tool_update_patch)

                            # For ExitPlanMode, inject plan content into the plan block
                            # instead of creating a separate tool_result
                            if result_tool_name == "EnterPlanMode":
                                pass  # No tool_result block for EnterPlanMode
                            elif result_tool_name == "ExitPlanMode":
                                # Find the plan block and inject content
                                plan_block_id = None
                                with _chat_lock:
                                    s = CHAT_SESSIONS.get(tab_id)
                                    if s:
                                        for blk in reversed(s.get("blocks", [])):
                                            if blk.get("type") == "plan" and not blk.get("active"):
                                                blk["content"] = content[:5000]
                                                plan_block_id = blk.get("id")
                                                break
                                if plan_block_id is not None:
                                    self._block_update(tab_id, plan_block_id, {"content": content[:5000]})
                            else:
                                self._block_add(tab_id, {
                                    "type":    "tool_result",
                                    "tool":    result_tool_name,
                                    "content": content[:2000],
                                })

                            if result_tool_name == "Write" and isinstance(tool_input, dict):
                                file_path = tool_input.get("file_path", "")
                                if "/Views/" in file_path and file_path.endswith(".html"):
                                    artifact_filename = file_path.rsplit("/", 1)[-1]
                                    socketio.emit("artifact_updated",
                                                  {"filename": artifact_filename},
                                                  namespace="/chat")

                            last_text_len        = 0
                            last_thinking_len    = 0
                            current_assistant_id = None

                    elif RateLimitEvent is not None and isinstance(message, RateLimitEvent):
                        info = getattr(message, "rate_limit_info", None)
                        if info is not None:
                            status = getattr(info, "status", None)
                            # Only surface transitions the user should see.
                            # "allowed" is the steady state - ignore it.
                            if status and status != "allowed":
                                self._block_add(tab_id, {
                                    "type":              "rate_limit",
                                    "status":            str(status),
                                    "rate_limit_type":   str(getattr(info, "rate_limit_type", "") or ""),
                                    "utilization":       getattr(info, "utilization", None),
                                    "resets_at":         getattr(info, "resets_at", None),
                                    "overage_status":    str(getattr(info, "overage_status", "") or ""),
                                    "overage_resets_at": getattr(info, "overage_resets_at", None),
                                    "overage_disabled_reason": getattr(info, "overage_disabled_reason", None),
                                })

                    elif isinstance(message, ResultMessage):
                        error_subtype     = getattr(message, "subtype", None)
                        stop_reason       = getattr(message, "stop_reason", None)
                        num_turns         = getattr(message, "num_turns", None)
                        duration_ms       = getattr(message, "duration_ms", None)
                        duration_api_ms   = getattr(message, "duration_api_ms", None)
                        usage             = getattr(message, "usage", None)
                        permission_denials = getattr(message, "permission_denials", None) or []
                        sdk_errors        = getattr(message, "errors", None) or []
                        # Per-model usage split (SDK 0.1.62+: ResultMessage.model_usage dict)
                        result_model      = getattr(message, "model", None)
                        model_usage_raw   = getattr(message, "model_usage", None) or {}
                        def _as_plain(obj):
                            if isinstance(obj, dict):
                                return obj
                            # pydantic / dataclass-ish
                            try:
                                return {k: getattr(obj, k) for k in getattr(obj, "__dict__", {})}
                            except Exception:
                                return {}
                        model_usage       = {
                            str(k): _as_plain(v) for k, v in model_usage_raw.items()
                        } if isinstance(model_usage_raw, dict) else {}

                        # Check for SDK errors (e.g. session compaction failure,
                        # context overflow, bundled CLI crash)
                        if getattr(message, "is_error", False):
                            app.logger.error(
                                f"SDK ResultMessage error for tab {tab_id[:12]}: "
                                f"subtype={error_subtype} stop_reason={stop_reason} "
                                f"errors={sdk_errors[:3]}"
                            )
                            if loading_block_id is not None:
                                self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                                loading_block_id = None
                            error_msg = "Claude session error"
                            if error_subtype == "error_during_execution":
                                error_msg = "Session failed to resume. The conversation may be too large. Try starting a new chat."
                            elif error_subtype == "error_max_turns":
                                error_msg = f"Hit max turns ({num_turns}). Start a new chat or raise the limit."
                            self._block_add(tab_id, {
                                "type":        "error",
                                "message":     error_msg,
                                "subtype":     error_subtype,
                                "stop_reason": stop_reason,
                                "errors":      [str(e)[:500] for e in sdk_errors[:5]],
                            })
                            result_data = {
                                "session_id":        message.session_id,
                                "cost_usd":          0,
                                "total_cost_usd":    0,
                                "subtype":           error_subtype,
                                "stop_reason":       stop_reason,
                                "num_turns":         num_turns,
                                "duration_ms":       duration_ms,
                                "duration_api_ms":   duration_api_ms,
                                "usage":             usage,
                                "permission_denials": permission_denials,
                                "model":             result_model,
                                "model_usage":       model_usage,
                            }
                            break  # Exit receive_response loop → will exit while loop via result_data check

                        result_data = {
                            "session_id":        message.session_id,
                            "cost_usd":          message.total_cost_usd or 0,
                            "total_cost_usd":    message.total_cost_usd or 0,
                            "subtype":           error_subtype,
                            "stop_reason":       stop_reason,
                            "num_turns":         num_turns,
                            "duration_ms":       duration_ms,
                            "duration_api_ms":   duration_api_ms,
                            "usage":             usage,
                            "permission_denials": permission_denials,
                            "model":             result_model,
                            "model_usage":       model_usage,
                        }

                        # ── Post-turn processing (inline) ─────────────────────
                        if tool_flush_timer:
                            tool_flush_timer.cancel()
                        if pending_tools:
                            _flush_tools()

                        # Force-clear stale running tool blocks
                        stale_updates = []
                        with _chat_lock:
                            sess = CHAT_SESSIONS.get(tab_id)
                            if sess:
                                for blk in sess.get("blocks", []):
                                    if blk.get("type") == "tool_use" and blk.get("running"):
                                        dm = int((_time.time() - blk.get("start_time", _time.time())) * 1000)
                                        blk["running"]     = False
                                        blk["duration_ms"] = dm
                                        stale_updates.append((blk["id"], {"running": False, "duration_ms": dm}))
                                    elif blk.get("type") == "tool_group":
                                        any_stale = False
                                        for t in blk.get("tools", []):
                                            if t.get("running"):
                                                t["running"]     = False
                                                t["duration_ms"] = int((_time.time() - t.get("start_time", _time.time())) * 1000)
                                                any_stale = True
                                        if any_stale:
                                            stale_updates.append((blk["id"], {"tools": [dict(tt) for tt in blk["tools"]]}))
                        for block_id, patch in stale_updates:
                            self._block_update(tab_id, block_id, patch)

                        # ── Result / cost block ───────────────────────────────
                        new_session_id = None
                        if result_data:
                            new_session_id = result_data.get("session_id")
                            if new_session_id:
                                with _chat_lock:
                                    if tab_id in CHAT_SESSIONS:
                                        CHAT_SESSIONS[tab_id]["claude_session_id"] = new_session_id
                                with _chat_ui_lock:
                                    if new_session_id not in _chat_ui_state.get("unread_sessions", []):
                                        _chat_ui_state.setdefault("unread_sessions", []).append(new_session_id)
                                    for entry in _chat_ui_state["active_sessions"]:
                                        if entry.get("tab_id") == tab_id:
                                            entry["session_id"] = new_session_id
                                            break
                                    seen = False
                                    deduped = []
                                    for entry in _chat_ui_state["active_sessions"]:
                                        if entry.get("session_id") == new_session_id:
                                            if seen:
                                                continue
                                            seen = True
                                        deduped.append(entry)
                                    _chat_ui_state["active_sessions"] = deduped
                                    sns = _chat_ui_state.get("session_names", {})
                                    if tab_id in sns:
                                        sns[new_session_id] = sns.pop(tab_id)
                                    drf = _chat_ui_state.get("drafts", {})
                                    if tab_id in drf:
                                        drf[new_session_id] = drf.pop(tab_id)
                                    urs = _chat_ui_state.get("unread_sessions", [])
                                    _chat_ui_state["unread_sessions"] = [
                                        new_session_id if s == tab_id else s for s in urs
                                    ]
                                    _save_chat_ui_state()
                            if loading_block_id is not None:
                                self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                            elapsed = int(_time.time() - CHAT_SESSIONS.get(tab_id, {}).get("started", _time.time()))
                            cost_usd = result_data.get("cost_usd", 0)
                            session_id_for_cost = result_data.get("session_id")
                            usage_obj = result_data.get("usage") or {}
                            denials = result_data.get("permission_denials") or []
                            self._block_add(tab_id, {
                                "type":              "cost",
                                "seconds":           elapsed,
                                "cost":              cost_usd,
                                "session_id":        session_id_for_cost,
                                "subtype":           result_data.get("subtype"),
                                "stop_reason":       result_data.get("stop_reason"),
                                "num_turns":         result_data.get("num_turns"),
                                "duration_ms":       result_data.get("duration_ms"),
                                "duration_api_ms":   result_data.get("duration_api_ms"),
                                "usage":             usage_obj if isinstance(usage_obj, dict) else None,
                                "model":             result_data.get("model"),
                                "model_usage":       result_data.get("model_usage") or {},
                                "permission_denials": [
                                    {
                                        "tool":   (d.get("tool_name") if isinstance(d, dict) else getattr(d, "tool_name", None)),
                                        "reason": (d.get("reason") if isinstance(d, dict) else getattr(d, "reason", None)),
                                    }
                                    for d in denials[:10]
                                ],
                            })
                            _write_result_to_jsonl(session_id_for_cost or new_session_id, cost_usd, elapsed, model)
                            if new_session_id:
                                if not resume_session_id:
                                    register_session(session_id=new_session_id, session_type="user", source="dashboard")
                                _broadcast_chat_state()
                                if not resume_session_id:
                                    threading.Thread(target=_auto_name_session, args=(new_session_id, prompt), daemon=True).start()
                        else:
                            if loading_block_id is not None:
                                self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                            elapsed = int(_time.time() - CHAT_SESSIONS.get(tab_id, {}).get("started", _time.time()))
                            self._block_add(tab_id, {
                                "type":       "cost",
                                "seconds":    elapsed,
                                "cost":       0,
                                "session_id": resume_session_id,
                            })
                            _write_result_to_jsonl(resume_session_id, 0, elapsed, model)

                # ── receive_response() ended ─────────────────────────────────
                # If no ResultMessage was received, the SDK died silently
                # (e.g. session expired on backend: "No conversation found")
                if result_data is None:
                    app.logger.error(f"SDK returned no ResultMessage for tab {tab_id[:12]}, session likely expired")
                    if loading_block_id is not None:
                        self._block_update(tab_id, loading_block_id, {"type": "_removed"})
                        loading_block_id = None
                    self._block_add(tab_id, {
                        "type": "error",
                        "message": "Session expired on Claude's backend. Please start a new chat session.",
                    })
                    break  # Exit while True → cleanup in finally

                # Restore deferred pending blocks (removed during queue processing)
                if deferred_pending:
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            for blk in deferred_pending:
                                blk["id"] = len(sess["blocks"])
                                sess["blocks"].append(blk)
                            restore_snap = list(sess["blocks"])
                            restore_sids = set(sess.get("socket_sids", set()))
                    for sid in restore_sids:
                        try:
                            socketio.emit("realtime_snapshot", {
                                "blocks": restore_snap,
                                "streaming": True,
                                "queue": [],
                                "tab_id": tab_id,
                            }, namespace="/chat", to=sid)
                        except Exception:
                            pass
                    deferred_pending = []

                # Check queue for next message
                next_msg = None
                target_sids_for_done = set()
                with _chat_lock:
                    if tab_id in CHAT_SESSIONS:
                        sess = CHAT_SESSIONS[tab_id]
                        target_sids_for_done = set(sess.get("socket_sids", set()))
                        queue = sess.get("message_queue", [])
                        if queue:
                            next_msg = queue.pop(0)
                            app.logger.info(f"Next queued message for tab {tab_id[:12]}, {len(queue)} remaining")

                for tsid in target_sids_for_done:
                    try:
                        socketio.emit("realtime_done", {"has_next": bool(next_msg), "tab_id": tab_id},
                                      namespace="/chat", to=tsid)
                    except Exception:
                        pass

                if not next_msg:
                    # ── No queued messages. Wait for next user message. ──
                    # Mark session as idle so on_send_message puts into incoming_queue
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            sess["session_idle"] = True
                    _broadcast_chat_state()  # Tell frontend we're no longer "active"
                    try:
                        next_msg = await asyncio.wait_for(
                            incoming.get(), timeout=self.PERSISTENT_IDLE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        app.logger.info(f"Persistent session idle timeout for tab {tab_id[:12]}")
                        break  # Exit while True → proceed to finally cleanup
                    if next_msg is None:
                        app.logger.info(f"Persistent session shutdown for tab {tab_id[:12]}")
                        break  # Shutdown sentinel
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            sess["session_idle"] = False
                    _broadcast_chat_state()  # Tell frontend we're active again
                    app.logger.info(f"Persistent session got new message for tab {tab_id[:12]}")

                # ── Prepare UI for next turn ──────────────────────────
                self._emit_queue_update(tab_id)

                # Switch model if queued message requests a different one
                next_model = next_msg.get("model") or model
                if next_model != model:
                    await client.set_model(next_model)
                    model = next_model

                if new_session_id:
                    resume_session_id = new_session_id

                # Reset per-turn tracking state
                result_data          = None
                last_thinking_len    = 0
                last_text_len        = 0
                current_thinking_id  = None
                current_assistant_id = None
                pending_tools        = []
                tool_flush_timer     = None
                tool_name            = ""
                tool_input           = {}

                # Mark FIRST pending user block as confirmed.
                # Remove remaining pending blocks so response blocks append
                # in correct order. They'll be restored after turn completes.
                deferred_pending = []
                snapshot_sids = set()
                with _chat_lock:
                    sess = CHAT_SESSIONS.get(tab_id)
                    if sess:
                        blocks = sess.get("blocks", [])
                        first_pending_idx = None
                        for idx, blk in enumerate(blocks):
                            if blk.get("type") == "user" and blk.get("pending"):
                                first_pending_idx = idx
                                break
                        if first_pending_idx is not None:
                            blocks[first_pending_idx]["pending"] = False
                            # Remove remaining pending user blocks, store for later
                            new_blocks = []
                            for blk in blocks:
                                if blk.get("type") == "user" and blk.get("pending"):
                                    deferred_pending.append(blk)
                                else:
                                    new_blocks.append(blk)
                            # Re-index blocks after removal
                            for i, b in enumerate(new_blocks):
                                b["id"] = i
                            sess["blocks"] = new_blocks
                            snapshot_sids = set(sess.get("socket_sids", set()))
                # Send full snapshot if blocks were reordered
                if deferred_pending:
                    snap = None
                    with _chat_lock:
                        sess = CHAT_SESSIONS.get(tab_id)
                        if sess:
                            snap = list(sess["blocks"])
                    if snap is not None:
                        for sid in snapshot_sids:
                            try:
                                socketio.emit("realtime_snapshot", {
                                    "blocks": snap,
                                    "streaming": True,
                                    "queue": [],
                                    "tab_id": tab_id,
                                }, namespace="/chat", to=sid)
                            except Exception:
                                pass
                self._block_add(tab_id, {"type": "loading"})
                with _chat_lock:
                    sess = CHAT_SESSIONS.get(tab_id)
                    if sess:
                        loading_block_id = len(sess.get("blocks", [])) - 1
                _broadcast_chat_state()

                # Send message via client.query() then loop for fresh receive_response()
                await client.query(next_msg["prompt"])
                app.logger.info(f"Sent message via client.query() for tab {tab_id[:12]}, starting new receive_response() loop")

        except BaseException as e:
            if not isinstance(e, (KeyboardInterrupt, SystemExit)):
                app.logger.error(f"Chat error for tab {tab_id}: {e}")
                self._block_add(tab_id, {"type": "error", "message": str(e)})
        finally:
            # Stop the message generator, then disconnect
            try:
                await msg_queue.put(None)  # Sentinel stops _message_stream generator
            except BaseException:
                pass
            try:
                await _safe_sdk_disconnect(client)
            except BaseException:
                pass
            self._clear_stream_state(tab_id)

            target_sids_for_done = set()
            _klava_result_text = ""  # Extract last assistant text for Klava tasks
            with _chat_lock:
                if tab_id in CHAT_SESSIONS:
                    sess = CHAT_SESSIONS[tab_id]
                    target_sids_for_done = set(sess.get("socket_sids", set()))
                    # Extract last assistant text before cleanup for Klava task results
                    for blk in reversed(sess.get("blocks", [])):
                        if blk.get("type") == "assistant" and blk.get("text", "").strip():
                            _klava_result_text = blk["text"].strip()
                            break
                    sess["sdk_client"]     = None
                    sess["sdk_loop"]       = None
                    sess["sdk_queue"]      = None
                    sess["incoming_queue"] = None
                    sess["session_idle"]   = False
                    sess["process"]        = None
                    sess["process_done"]   = True
                    sess.pop("_detached_pid", None)
                cutoff       = _time.time() - 300
                stuck_cutoff = _time.time() - 14400  # 4 hours - tool calls can run for hours
                for k in list(CHAT_SESSIONS.keys()):
                    s = CHAT_SESSIONS[k]
                    should_clean = False
                    if s.get("process_done") and s.get("started", 0) < cutoff:
                        should_clean = True
                    else:
                        last_act = s.get("last_activity_ts") or s.get("started", 0)
                        if not s.get("process_done") and last_act < stuck_cutoff:
                            sdk_c = s.get("sdk_client")
                            sdk_l = s.get("sdk_loop")
                            if sdk_c and sdk_l:
                                try:
                                    asyncio.run_coroutine_threadsafe(_safe_sdk_disconnect(sdk_c), sdk_l)
                                except Exception:
                                    pass
                            app.logger.warning(f"[chat] Cleaning stuck session {k[:12]} ({int(_time.time() - last_act)}s since last activity)")
                            for sock_sid in s.get("socket_sids", set()):
                                socketio.emit("realtime_block_add", {
                                    "block": {"type": "error", "message": "Session became unresponsive and was cleaned up. Start a new message to continue."},
                                    "tab_id": k
                                }, namespace="/chat", to=sock_sid)
                            should_clean = True
                    if should_clean:
                        for sock_sid in s.get("socket_sids", set()):
                            sub = SOCKET_TO_SESSIONS.get(sock_sid)
                            if sub is not None:
                                sub.discard(k)
                                if not sub:
                                    del SOCKET_TO_SESSIONS[sock_sid]
                        del CHAT_SESSIONS[k]

            # Klava task completion: update GTasks and notify dashboard
            try:
                from lib.klava_manager import pop_task as _klava_pop, complete_task as _klava_complete
                klava_meta = _klava_pop(tab_id)
                if klava_meta:
                    error_str = None
                    if not result_data:
                        error_str = "Session ended without result"
                    # Attach extracted assistant text to result_data for GTasks storage
                    if result_data and _klava_result_text:
                        result_data["result_text"] = _klava_result_text
                    threading.Thread(
                        target=_klava_complete,
                        args=(klava_meta["task_id"], result_data, error_str),
                        daemon=True,
                    ).start()
                    socketio.emit("klava_done", {
                        "task_id": klava_meta["task_id"],
                        "tab_id": tab_id,
                        "title": klava_meta["title"],
                        "success": error_str is None,
                        "cost": result_data.get("cost_usd", 0) if result_data else 0,
                    }, namespace="/chat")
                    app.logger.info(f"Klava task completed: {klava_meta['title'][:40]} (tab={tab_id[:12]})")
                    # Clean up dummy socket entry
                    dummy_sid = f"__klava__{klava_meta['task_id'][:8]}"
                    with _chat_lock:
                        SOCKET_TO_SESSIONS.pop(dummy_sid, None)
            except Exception as _ke:
                app.logger.error(f"Klava completion error: {_ke}", exc_info=True)

            # Emit final realtime_done (covers error/crash case;
            # normal flow already emitted from ResultMessage handler)
            for tsid in target_sids_for_done:
                try:
                    socketio.emit("realtime_done", {"has_next": False, "tab_id": tab_id},
                                  namespace="/chat", to=tsid)
                except Exception:
                    pass

            with _chat_ui_lock:
                sess_data   = CHAT_SESSIONS.get(tab_id) if tab_id in CHAT_SESSIONS else None
                has_real_id = bool(sess_data and sess_data.get("claude_session_id")) if sess_data else False
                if not has_real_id:
                    before = len(_chat_ui_state["active_sessions"])
                    _chat_ui_state["active_sessions"] = [
                        e for e in _chat_ui_state["active_sessions"]
                        if e.get("tab_id") != tab_id or e.get("session_id")
                    ]
                    if len(_chat_ui_state["active_sessions"]) < before:
                        _save_chat_ui_state()

            _broadcast_chat_state()

    # --- Session file watching (live tail) ---

    def on_detach_all(self, data=None):
        """Detach this socket from all sessions (keeps processes running, buffers events)."""
        sid = request.sid
        with _chat_lock:
            subscribed = SOCKET_TO_SESSIONS.pop(sid, set())
            for sess_id in subscribed:
                if sess_id in CHAT_SESSIONS:
                    CHAT_SESSIONS[sess_id].get("socket_sids", set()).discard(sid)
                    app.logger.info(f"Detached socket {sid} from session {sess_id[:12]}")

    def _build_blocks_from_entry(self, entry, start_id):
        """Parse a single JSONL entry into blocks."""
        blocks = []
        block_id = start_id
        entry_type = entry.get("type")

        if entry_type == "user":
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
            text = str(content).strip()

            # Extract file references injected by _prepare_prompt
            files = []
            _img_re = re.compile(r'\[Image attached: (.+?)\]')
            _file_re = re.compile(r'\[File attached: (.+?) \((.+?)\)\]')
            for m in _img_re.finditer(text):
                fpath = m.group(1)
                fname = os.path.basename(fpath)
                ftype = mimetypes.guess_type(fpath)[0] or "image/png"
                files.append({"name": fname, "path": fpath, "url": f"/api/chat/files/{fname}", "type": ftype, "size": 0})
            for m in _file_re.finditer(text):
                fpath = m.group(1)
                fname_orig = m.group(2)
                fname = os.path.basename(fpath)
                ftype = mimetypes.guess_type(fpath)[0] or "application/octet-stream"
                files.append({"name": fname_orig, "path": fpath, "url": f"/api/chat/files/{fname}", "type": ftype, "size": 0})
            # Strip file markers from displayed text
            clean = _img_re.sub('', text)
            clean = _file_re.sub('', clean).strip()

            # Strip SDK/CLI system scaffolding that would otherwise render as
            # content inside a user bubble: slash-command envelope, skill
            # invocation wrapper, system reminders (CLAUDE.md injections and
            # skill metadata), and caveats. When the user invokes /skill-creator
            # or any other slash command, the SDK writes a user-typed JSONL
            # entry containing <command-name>/skill-creator</command-name>;
            # without this strip the Chat tab shows a UserBlock made entirely
            # of SDK plumbing. See GH #6.
            clean = re.sub(r"<system-reminder>.*?</system-reminder>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<local-command-caveat>.*?</local-command-caveat>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<command-name>.*?</command-name>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<command-message>.*?</command-message>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<command-args>.*?</command-args>", "", clean, flags=re.DOTALL)
            clean = clean.strip()

            if clean or files:
                blocks.append({"type": "user", "id": block_id, "text": clean, "files": files})
                block_id += 1

        elif entry_type == "assistant":
            msg = entry.get("message", {})
            for item in msg.get("content", []):
                if item.get("type") == "thinking":
                    text = item.get("thinking", "")[:1000]
                    if text:
                        words = len(text.split())
                        preview = text[:60].replace("\n", " ")
                        blocks.append({"type": "thinking", "id": block_id, "text": text, "words": words, "preview": preview})
                        block_id += 1
                elif item.get("type") == "text":
                    text = item.get("text", "")
                    if text.strip():
                        blocks.append({"type": "assistant", "id": block_id, "text": text})
                        block_id += 1
                elif item.get("type") == "tool_use":
                    tool_name = item.get("name", "")
                    tool_input = item.get("input", {})
                    if tool_name == "AskUserQuestion":
                        blocks.append({"type": "question", "id": block_id, "questions": tool_input.get("questions", []), "answered": True})
                        block_id += 1
                    elif tool_name == "EnterPlanMode":
                        blocks.append({"type": "plan", "id": block_id, "active": True})
                        block_id += 1
                    elif tool_name == "ExitPlanMode":
                        blocks.append({"type": "plan", "id": block_id, "active": False})
                        block_id += 1
                    elif tool_name in ("Agent", "Task"):
                        blocks.append({"type": "agent", "id": block_id, "tool": tool_name, "input": tool_input, "running": False, "agent_blocks": []})
                        block_id += 1
                    else:
                        blocks.append({"type": "tool_use", "id": block_id, "tool": tool_name, "input": tool_input, "running": False})
                        block_id += 1

        elif entry_type == "tool_result":
            content = entry.get("content", "")
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                content = "\n".join(text_parts)
            blocks.append({"type": "tool_result", "id": block_id, "tool": "", "content": str(content)[:2000]})
            block_id += 1

        elif entry_type == "result":
            cost = entry.get("cost_usd", 0)
            duration = entry.get("duration_seconds", 0)
            blocks.append({"type": "cost", "id": block_id, "seconds": int(duration), "cost": cost, "session_id": entry.get("session_id", "")})
            block_id += 1

        return blocks

    def _build_blocks_from_jsonl(self, file_path):
        """Parse a complete JSONL session file into blocks.
        Returns (blocks, metadata) where metadata includes detected model."""
        blocks = []
        block_id = 0
        detected_model = None
        try:
            with open(file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Track model from assistant messages or result entries
                    if entry.get("type") == "assistant" and entry.get("message", {}).get("model"):
                        detected_model = entry["message"]["model"]
                    elif entry.get("type") == "result" and entry.get("model"):
                        detected_model = entry["model"]
                    new_blocks = self._build_blocks_from_entry(entry, block_id)
                    blocks.extend(new_blocks)
                    if new_blocks:
                        block_id = new_blocks[-1]["id"] + 1
        except Exception as e:
            app.logger.error(f"Error building blocks from JSONL: {e}")

        # Post-process: merge plan content from tool_result into plan blocks
        i = 0
        while i < len(blocks) - 1:
            if blocks[i].get("type") == "plan" and not blocks[i].get("active"):
                nxt = blocks[i + 1]
                if nxt.get("type") == "tool_result":
                    blocks[i]["content"] = nxt.get("content", "")
                    blocks.pop(i + 1)
            i += 1

        return blocks, detected_model

    def on_watch_session(self, data):
        """Watch a session's JSONL file for real-time updates.

        Accepts {session_id, tab_id?}. If the session is currently streaming
        under some tab_id, joins that stream and replays its buffer.
        Otherwise starts a file watcher.
        """
        sid = request.sid
        session_id = data.get("session_id")
        if not session_id:
            emit("error", {"message": "session_id required"})
            return

        # Check if this session is currently streaming under some tab_id
        streaming_tab_id = None
        with _chat_lock:
            self._stop_watcher_for_socket_locked(sid)
            self._stop_watcher_for_session_locked(session_id)
            # Remove socket from ALL streaming session subscriptions
            # to prevent events from old sessions leaking to this socket
            old_subs = SOCKET_TO_SESSIONS.pop(sid, set())
            for old_tid in old_subs:
                old_sess = CHAT_SESSIONS.get(old_tid)
                if old_sess:
                    old_sess.get("socket_sids", set()).discard(sid)
            for tid, sess in CHAT_SESSIONS.items():
                if sess.get("claude_session_id") == session_id or tid == session_id:
                    is_active = ((sess.get("process") or sess.get("sdk_client")) and not sess.get("process_done") and not sess.get("session_idle")) or (sess.get("_detached_pid") and not sess.get("process_done"))
                    if is_active:
                        streaming_tab_id = tid
                        # Add this socket to the streaming session
                        sess.setdefault("socket_sids", set()).add(sid)
                        SOCKET_TO_SESSIONS.setdefault(sid, set()).add(tid)
                        break

        if streaming_tab_id:
            # Two-entity split: history from JSONL (previous turns), realtime from CHAT_SESSIONS (current turn)
            history_blocks = []
            # Resolve real claude_session_id for JSONL lookup (session_id may be frontend tab UUID)
            with _chat_lock:
                _sess = CHAT_SESSIONS.get(streaming_tab_id)
                real_claude_id = _sess.get("claude_session_id") if _sess else None
            file_path = _find_session_file(real_claude_id) if real_claude_id else None
            if not file_path:
                file_path = _find_session_file(session_id)
            history_model = None
            if file_path:
                # All JSONL blocks are completed turns = history
                # (current streaming turn lives only in CHAT_SESSIONS, not yet in JSONL)
                history_blocks, history_model = self._build_blocks_from_jsonl(file_path)

            with _chat_lock:
                sess = CHAT_SESSIONS.get(streaming_tab_id)
                realtime_blocks = list(sess["blocks"]) if sess else []
                queue = sess.get("message_queue", []) if sess else []
                queue_data = [{"text": m["prompt"][:80], "index": i} for i, m in enumerate(queue)]

            emit("watch_started", {"session_id": session_id, "tab_id": streaming_tab_id})
            snapshot_data = {
                "blocks": history_blocks,
                "session_id": session_id,
            }
            if history_model:
                snapshot_data["model"] = history_model
            emit("history_snapshot", snapshot_data)
            started = sess.get("started", time.time()) if sess else time.time()
            emit("realtime_snapshot", {
                "blocks": realtime_blocks,
                "streaming": True,
                "queue": queue_data,
                "tab_id": streaming_tab_id,
                "elapsed": int(time.time() - started),
            })
            app.logger.info(f"Sent history+realtime snapshot for streaming tab {streaming_tab_id[:12]}, history={len(history_blocks)}, realtime={len(realtime_blocks)}")
            return

        # Not streaming - all blocks are history
        file_path = _find_session_file(session_id)

        # Ghost session: no file on disk and not streaming -> notify frontend immediately
        if not file_path:
            # Check if there's a pending process that might create the file soon
            # (e.g. just-launched session). If not in CHAT_SESSIONS, it's truly dead.
            has_pending = False
            with _chat_lock:
                for tid, sess in CHAT_SESSIONS.items():
                    if sess.get("claude_session_id") == session_id or tid == session_id:
                        if (sess.get("process") or sess.get("sdk_client")) and not sess.get("process_done"):
                            has_pending = True
                            break
            if not has_pending:
                app.logger.warning(f"Session {session_id[:12]} has no file and no pending process - ghost session")
                emit("session_not_found", {"session_id": session_id})
                # Don't remove from active_sessions here - the user explicitly selected
                # this session. Aggressive cleanup causes the session to vanish from
                # the sidebar immediately after clicking it.
                return

        blocks, detected_model = self._build_blocks_from_jsonl(file_path) if file_path else ([], None)
        emit("watch_started", {"session_id": session_id})
        hist_data = {
            "blocks": blocks,
            "session_id": session_id,
        }
        if detected_model:
            hist_data["model"] = detected_model
        emit("history_snapshot", hist_data)
        emit("realtime_snapshot", {
            "blocks": [],
            "streaming": False,
            "queue": [],
            "tab_id": session_id,
        })

        # Start file watcher for live updates (also handles file-not-yet-created)
        stop_event = threading.Event()
        initial_offset = os.path.getsize(file_path) if file_path else 0
        watcher = {
            "thread": None,
            "socket_sid": sid,
            "stop": stop_event,
            "offset": initial_offset,
            "file_path": file_path,
            "next_block_id": len(blocks),
        }
        with _chat_lock:
            SESSION_WATCHERS[session_id] = watcher

        thread = threading.Thread(
            target=self._watch_file,
            args=(session_id, file_path, sid, stop_event, initial_offset),
            daemon=True,
        )
        watcher["thread"] = thread
        thread.start()
        if file_path:
            app.logger.info(f"Sent history_snapshot for session {session_id[:12]}, {len(blocks)} blocks")
        else:
            app.logger.info(f"Session {session_id[:12]} file not yet on disk, watcher will poll")

    def on_unwatch_session(self, data=None):
        """Stop watching a session.

        Also detaches this socket from any streaming CHAT_SESSIONS it was
        subscribed to, so realtime events for the previous session don't
        leak into whatever the frontend shows next.
        """
        sid = request.sid
        session_id = (data or {}).get("session_id")
        with _chat_lock:
            self._stop_watcher_for_socket_locked(sid)
            if session_id:
                self._stop_watcher_for_session_locked(session_id)
            old_subs = SOCKET_TO_SESSIONS.pop(sid, set())
            for old_tid in old_subs:
                old_sess = CHAT_SESSIONS.get(old_tid)
                if old_sess:
                    old_sess.get("socket_sids", set()).discard(sid)
        emit("watch_stopped", {})

    def _stop_watcher_for_socket_locked(self, sid):
        """Stop any active watcher for this socket. Must hold _chat_lock."""
        for sess_id, w in list(SESSION_WATCHERS.items()):
            if w.get("socket_sid") == sid:
                w["stop"].set()
                del SESSION_WATCHERS[sess_id]

    def _stop_watcher_for_session_locked(self, session_id):
        """Stop watcher for a specific session_id. Must hold _chat_lock."""
        w = SESSION_WATCHERS.pop(session_id, None)
        if w:
            w["stop"].set()

    def _watch_file(self, session_id, file_path, sid, stop_event, offset):
        """Poll JSONL file for new lines and emit history_block_add events."""
        import time as _time

        # If file doesn't exist yet, poll _find_session_file until it appears
        if not file_path:
            for _ in range(60):  # wait up to ~60s
                if stop_event.is_set():
                    return
                file_path = _find_session_file(session_id)
                if file_path:
                    with _chat_lock:
                        if session_id in SESSION_WATCHERS:
                            SESSION_WATCHERS[session_id]["file_path"] = file_path
                    app.logger.info(f"Session {session_id[:12]} file appeared: {file_path}")
                    break
                stop_event.wait(1.0)
            else:
                app.logger.warning(f"Session {session_id[:12]} file never appeared, giving up")
                try:
                    socketio.emit("session_not_found", {"session_id": session_id}, namespace="/chat", to=sid)
                except Exception:
                    pass
                return

        while not stop_event.is_set():
            try:
                file_size = os.path.getsize(file_path)
                if file_size > offset:
                    with open(file_path, "r") as f:
                        f.seek(offset)
                        new_data = f.read()
                        offset = f.tell()

                    with _chat_lock:
                        if session_id in SESSION_WATCHERS:
                            SESSION_WATCHERS[session_id]["offset"] = offset
                            sid = SESSION_WATCHERS[session_id].get("socket_sid", sid)
                            next_id = SESSION_WATCHERS[session_id].get("next_block_id", 0)
                        else:
                            next_id = 0  # Session watcher removed while we were reading

                    for line in new_data.strip().split("\n"):
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                            new_blocks = self._build_blocks_from_entry(entry, next_id)
                            for block in new_blocks:
                                try:
                                    socketio.emit("history_block_add", {"block": block, "tab_id": session_id}, namespace="/chat", to=sid)
                                except Exception:
                                    pass
                                next_id = block["id"] + 1
                        except json.JSONDecodeError:
                            continue

                    with _chat_lock:
                        if session_id in SESSION_WATCHERS:
                            SESSION_WATCHERS[session_id]["next_block_id"] = next_id

            except FileNotFoundError:
                break
            except Exception as e:
                app.logger.error(f"Watch error for {session_id[:12]}: {e}")
                break

            stop_event.wait(1.0)


def _write_result_to_jsonl(session_id, cost_usd, duration_seconds, model_name):
    """Append a synthetic result entry to the session's JSONL file for historical cost blocks."""
    if not session_id:
        return
    file_path = _find_session_file(session_id)
    if not file_path:
        return
    try:
        entry = {
            "type": "result",
            "cost_usd": cost_usd,
            "duration_seconds": duration_seconds,
            "session_id": session_id,
            "model": model_name or "",
        }
        with open(file_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        app.logger.warning(f"Failed to write result to JSONL {session_id[:12]}: {e}")


def _find_session_file(session_id):
    """Find JSONL file path for a session ID."""
    claude_config = _gateway_config.claude_config_dir()

    # Check sessions-index.json first
    for proj_dir in claude_config.glob("projects/*/"):
        index_path = proj_dir / "sessions-index.json"
        if index_path.exists():
            try:
                with open(index_path) as f:
                    index = json.load(f)
                entries = index.get("entries", []) if isinstance(index, dict) else index
                for entry in entries:
                    if entry.get("sessionId") == session_id:
                        fp = entry.get("fullPath")
                        if fp and os.path.exists(fp):
                            return fp
            except Exception:
                pass

        # Direct file check
        jsonl_path = proj_dir / f"{session_id}.jsonl"
        if jsonl_path.exists():
            return str(jsonl_path)

    return None


def _parse_session_entry(entry):
    """Parse a JSONL session entry into a display-friendly format."""
    entry_type = entry.get("type")
    ts = entry.get("timestamp", "")

    if entry_type == "user":
        msg = entry.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
        text = str(content).strip()
        # Strip SDK scaffolding so session-history views don't surface raw
        # <command-name> / <system-reminder> tags as user messages. See GH #6.
        text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
        text = re.sub(r"<local-command-caveat>.*?</local-command-caveat>", "", text, flags=re.DOTALL)
        text = re.sub(r"<command-name>.*?</command-name>", "", text, flags=re.DOTALL)
        text = re.sub(r"<command-message>.*?</command-message>", "", text, flags=re.DOTALL)
        text = re.sub(r"<command-args>.*?</command-args>", "", text, flags=re.DOTALL)
        text = text.strip()
        if not text:
            return None
        return {"role": "user", "text": text, "timestamp": ts}

    elif entry_type == "assistant":
        msg = entry.get("message", {})
        content_items = msg.get("content", [])
        parts = []

        for item in content_items:
            if item.get("type") == "text":
                parts.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "tool_use":
                tool_name = item.get("name", "")
                tool_input = item.get("input", {})
                parts.append({
                    "type": "tool_use",
                    "tool": tool_name,
                    "input": tool_input,  # Keep as dict for frontend rendering
                })
                # Emit interactive tool markers for watching mode
                if tool_name == "AskUserQuestion":
                    parts.append({
                        "type": "question",
                        "questions": tool_input.get("questions", []),
                    })
                elif tool_name == "EnterPlanMode":
                    parts.append({"type": "plan_mode", "active": True})
                elif tool_name == "ExitPlanMode":
                    parts.append({"type": "plan_mode", "active": False})
            elif item.get("type") == "thinking":
                parts.append({
                    "type": "thinking",
                    "text": item.get("thinking", "")[:1000],
                })

        if not parts:
            return None
        # Filter out text-only parts that are empty
        meaningful = [p for p in parts if not (p["type"] == "text" and not p.get("text", "").strip())]
        if not meaningful:
            return None

        usage = entry.get("usage", {})
        return {
            "role": "assistant",
            "content": meaningful,
            "model": msg.get("model", ""),
            "usage": {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
            },
            "timestamp": ts,
        }

    elif entry_type == "result":
        return {
            "role": "result",
            "text": entry.get("result", "")[:2000],
            "session_id": entry.get("session_id", ""),
            "cost": entry.get("cost_usd", 0),
            "duration": entry.get("duration_seconds", 0),
            "timestamp": ts,
        }

    elif entry_type == "progress":
        return {"role": "progress", "timestamp": ts}

    return None


_chat_ns = ChatNamespace("/chat")
socketio.on_namespace(_chat_ns)


# ============================================================
# CHAT FILE UPLOAD
# ============================================================

CHAT_UPLOAD_DIR = Path(tempfile.gettempdir()) / "chat_uploads"
CHAT_UPLOAD_DIR.mkdir(exist_ok=True)

@app.route('/api/chat/upload', methods=['POST'])
def api_chat_upload():
    """Upload files for chat - saved to temp dir, returns paths."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    uploaded = []
    for f in request.files.getlist('file'):
        if not f.filename:
            continue
        # Sanitize filename
        safe_name = f"{int(time.time()*1000)}_{Path(f.filename).name}"
        dest = CHAT_UPLOAD_DIR / safe_name
        f.save(str(dest))
        uploaded.append({
            "name": f.filename,
            "path": str(dest),
            "url": f"/api/chat/files/{safe_name}",
            "size": dest.stat().st_size,
            "type": f.content_type or "application/octet-stream",
        })

    return jsonify({"files": uploaded})


@app.route('/api/chat/files/<filename>', methods=['GET'])
def api_chat_files(filename):
    """Serve uploaded chat files (images, documents)."""
    if '..' in filename or '/' in filename:
        return "Forbidden", 403
    fpath = CHAT_UPLOAD_DIR / filename
    if not fpath.exists():
        return "Not found", 404
    ct = mimetypes.guess_type(str(fpath))[0] or 'application/octet-stream'
    return send_file(str(fpath), mimetype=ct)


# ============================================================
# SESSIONS API
# ============================================================

@app.route('/api/sessions', methods=['GET'])
def api_sessions():
    """List recent Claude Code sessions - no auth required (localhost only)."""
    try:
        claude_config = _gateway_config.claude_config_dir()
        sessions = []
        indexed_ids = set()

        for projects_dir in claude_config.glob("projects/*/"):
            if not projects_dir.is_dir():
                continue

            # Read sessions-index.json if it exists
            index_file = projects_dir / "sessions-index.json"
            if index_file.exists():
                try:
                    with open(index_file) as f:
                        index = json.load(f)
                    entries = index.get("entries", []) if isinstance(index, dict) else index
                    for entry in entries:
                        sid = entry.get("sessionId", "")
                        indexed_ids.add(sid)
                        # Check if session is currently active (file modified < 60s ago)
                        is_active = False
                        fp = entry.get("fullPath")
                        if not fp:
                            fp = str(projects_dir / f"{sid}.jsonl")
                        try:
                            if os.path.exists(fp):
                                is_active = (time.time() - os.path.getmtime(fp)) < 60
                        except OSError:
                            pass
                        sessions.append({
                            "id": sid,
                            "project": projects_dir.name,
                            "date": entry.get("modified", entry.get("created", "")),
                            "preview": entry.get("summary", entry.get("firstPrompt", ""))[:120],
                            "messages": entry.get("messageCount", 0),
                            "is_active": is_active,
                        })
                except (json.JSONDecodeError, KeyError):
                    pass

            # Also scan JSONL files not in index (index can be stale)
            for jsonl_file in sorted(projects_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:30]:
                sid = jsonl_file.stem
                if sid in indexed_ids:
                    continue
                try:
                    mtime = jsonl_file.stat().st_mtime
                    # Read first few lines to get preview
                    preview = ""
                    with open(jsonl_file) as f:
                        for i, line in enumerate(f):
                            if i > 10:
                                break
                            try:
                                data = json.loads(line.strip())
                                if data.get("type") == "summary":
                                    preview = data.get("summary", "")[:120]
                                    break
                                elif data.get("type") == "user":
                                    msg = data.get("message", {})
                                    content = msg.get("content", "")
                                    if isinstance(content, str):
                                        preview = content[:120]
                                    elif isinstance(content, list):
                                        for c in content:
                                            if isinstance(c, dict) and c.get("type") == "text":
                                                preview = c.get("text", "")[:120]
                                                break
                                    if preview:
                                        break
                            except json.JSONDecodeError:
                                continue
                    sessions.append({
                        "id": sid,
                        "project": projects_dir.name,
                        "date": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                        "preview": preview or "(no preview)",
                        "messages": 0,
                        "is_active": (time.time() - mtime) < 60,
                    })
                except Exception:
                    continue

        # Enrich with registry metadata (type, job_id, source)
        from lib.session_registry import list_sessions as list_registry
        registry = {e["session_id"]: e for e in list_registry(limit=200)}
        for s in sessions:
            reg = registry.get(s["id"])
            if reg:
                s["type"] = reg.get("type")
                s["job_id"] = reg.get("job_id")
                s["source"] = reg.get("source")

        # Sort by date descending
        sessions.sort(key=lambda s: s.get("date", ""), reverse=True)
        return jsonify({"sessions": sessions[:50]})

    except Exception as e:
        app.logger.error(f"Sessions API failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sessions/search', methods=['GET'])
def api_sessions_search():
    """Full-text search across session content (user/assistant messages only)."""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({"sessions": []})

    try:
        claude_config = _gateway_config.claude_config_dir()
        query_lower = query.lower()
        results = []

        # Collect all session JSONL files sorted by mtime (newest first)
        all_files = []
        for projects_dir in claude_config.glob("projects/*/"):
            if not projects_dir.is_dir():
                continue
            for f in projects_dir.glob("*.jsonl"):
                if f.stem == "sessions-index":
                    continue
                try:
                    all_files.append((f, f.stat().st_mtime))
                except OSError:
                    continue
        all_files.sort(key=lambda x: x[1], reverse=True)

        # Search through recent sessions (cap at 200 files for speed)
        for jsonl_path, mtime in all_files[:200]:
            sid = jsonl_path.stem
            project = jsonl_path.parent.name
            preview = ""
            snippet = ""
            msg_count = 0
            found = False

            try:
                with open(jsonl_path) as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            msg_type = data.get("type")
                            if msg_type not in ("user", "assistant"):
                                continue

                            msg_count += 1

                            # Extract text from message (skip system-reminder tags)
                            text = ""
                            if msg_type == "user":
                                content = data.get("message", {}).get("content", "")
                                if isinstance(content, str):
                                    text = content
                                elif isinstance(content, list):
                                    text = " ".join(
                                        c.get("text", "") for c in content
                                        if isinstance(c, dict) and c.get("type") == "text"
                                    )
                            elif msg_type == "assistant":
                                parts = data.get("message", {}).get("content", [])
                                text = " ".join(
                                    c.get("text", "") for c in parts
                                    if isinstance(c, dict) and c.get("type") == "text"
                                )

                            if not text:
                                continue

                            # Skip system-reminder content (embedded CLAUDE.md etc)
                            if "<system-reminder>" in text:
                                import re
                                text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)

                            # Get preview from first real user message
                            if not preview and msg_type == "user" and text.strip():
                                preview = text.strip()[:120]

                            # Check for query match
                            if not found:
                                idx = text.lower().find(query_lower)
                                if idx >= 0:
                                    found = True
                                    start = max(0, idx - 40)
                                    end = min(len(text), idx + len(query) + 60)
                                    snippet = ("..." if start > 0 else "") + text[start:end].strip() + ("..." if end < len(text) else "")

                        except json.JSONDecodeError:
                            continue

                    # Only include if query was found in actual content
                    if found:
                        results.append({
                            "id": sid,
                            "project": project,
                            "date": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                            "preview": preview or "(no preview)",
                            "messages": msg_count,
                            "is_active": False,
                            "snippet": snippet,
                        })
                        if len(results) >= 30:
                            break

            except Exception:
                continue

        return jsonify({"sessions": results})

    except Exception as e:
        app.logger.error(f"Session search failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sessions/registry', methods=['GET'])
def api_sessions_registry():
    """List sessions from gateway registry with type/job metadata."""
    from lib.session_registry import list_sessions as list_registry
    session_type = request.args.get('type')
    job_id = request.args.get('job_id')
    limit = int(request.args.get('limit', 50))
    entries = list_registry(session_type=session_type, job_id=job_id, limit=limit)
    return jsonify({"sessions": entries})


@app.route('/api/sessions/<session_id>', methods=['GET'])
def api_session_detail(session_id):
    """Get session conversation history - no auth required (localhost only)."""
    try:
        claude_config = _gateway_config.claude_config_dir()
        messages = []

        # Find JSONL file
        jsonl_path = None
        for projects_dir in claude_config.glob("projects/*/"):
            candidate = projects_dir / f"{session_id}.jsonl"
            if candidate.exists():
                jsonl_path = candidate
                break

        if not jsonl_path:
            return jsonify({"error": "Session not found"}), 404

        with open(jsonl_path) as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    msg_type = data.get("type")

                    if msg_type == "user":
                        content = data.get("message", {}).get("content", "")
                        text = ""
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            parts = []
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    parts.append(c.get("text", ""))
                            text = "\n".join(parts)
                        if text:
                            # Strip leading "- \n" or "-\n" from terminal input format
                            text = text.lstrip("- \n").lstrip("\n") if text.startswith("-") else text.strip()
                            if text:
                                messages.append({"role": "user", "text": text[:2000]})

                    elif msg_type == "assistant":
                        msg = data.get("message", {})
                        for item in msg.get("content", []):
                            if item.get("type") == "text":
                                messages.append({"role": "assistant", "text": item.get("text", "")[:2000]})
                            elif item.get("type") == "thinking":
                                messages.append({"role": "thinking", "text": item.get("thinking", "")[:2000]})
                            elif item.get("type") == "tool_use":
                                raw_input = item.get("input", {})
                                messages.append({
                                    "role": "tool",
                                    "tool": item.get("name", ""),
                                    "input": raw_input if isinstance(raw_input, dict) else str(raw_input)[:500],
                                })

                except json.JSONDecodeError:
                    continue

        return jsonify({"session_id": session_id, "messages": messages})

    except Exception as e:
        app.logger.error(f"Session detail failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sessions/<session_id>/fork', methods=['POST'])
def api_session_fork(session_id):
    """Fork a session - copy JSONL with new UUID and update index."""
    try:
        source_path = _find_session_file(session_id)
        if not source_path:
            return jsonify({"error": "Session not found"}), 404

        source_path = Path(source_path)
        project_dir = source_path.parent
        new_id = str(uuid.uuid4())
        new_path = project_dir / f"{new_id}.jsonl"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Copy JSONL, updating sessionId in every line
        first_prompt = ""
        msg_count = 0
        with open(source_path) as src, open(new_path, "w") as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry["sessionId"] = new_id
                    if entry.get("type") == "user":
                        msg_count += 1
                        if not first_prompt:
                            msg = entry.get("message", {})
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
                            first_prompt = str(content)[:200]
                    elif entry.get("type") == "assistant":
                        msg_count += 1
                    dst.write(json.dumps(entry) + "\n")
                except json.JSONDecodeError:
                    dst.write(line + "\n")

        # Update sessions-index.json
        index_path = project_dir / "sessions-index.json"
        if index_path.exists():
            try:
                with open(index_path) as f:
                    index = json.load(f)
                entries = index.get("entries", []) if isinstance(index, dict) else index
                # Find source entry for metadata
                source_entry = next((e for e in entries if e.get("sessionId") == session_id), None)
                new_entry = {
                    "sessionId": new_id,
                    "fullPath": str(new_path),
                    "fileMtime": int(time.time() * 1000),
                    "firstPrompt": first_prompt or (source_entry or {}).get("firstPrompt", ""),
                    "messageCount": msg_count,
                    "created": now_iso,
                    "modified": now_iso,
                    "gitBranch": (source_entry or {}).get("gitBranch", ""),
                    "projectPath": (source_entry or {}).get("projectPath", str(Path.home())),
                    "isSidechain": False,
                }
                entries.append(new_entry)
                if isinstance(index, dict):
                    index["entries"] = entries
                else:
                    index = {"version": 1, "entries": entries}
                with open(index_path, "w") as f:
                    json.dump(index, f, indent=2)
            except Exception as idx_err:
                app.logger.warning(f"Failed to update sessions-index: {idx_err}")

        # Auto-name the fork in chat UI state
        source_name = _chat_ui_state.get("session_names", {}).get(session_id, "")
        fork_name = f"{source_name} (fork)" if source_name else f"Fork of {first_prompt[:60]}..." if first_prompt else f"Fork {new_id[:8]}"
        _chat_ui_state.setdefault("session_names", {})[new_id] = fork_name
        _save_chat_ui_state()

        app.logger.info(f"Forked session {session_id[:12]} -> {new_id[:12]}")
        return jsonify({
            "session_id": new_id,
            "source_id": session_id,
            "name": fork_name,
            "messages": msg_count,
        })

    except Exception as e:
        app.logger.error(f"Session fork failed: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================
# CHAT UI STATE API
# ============================================================

@app.route('/api/chat/state', methods=['GET'])
def api_chat_state():
    """Get chat UI state (active sessions, names, streaming)."""
    return jsonify(_get_chat_state_snapshot())


@app.route('/api/chat/state/active', methods=['POST'])
def api_chat_state_active():
    """Add or remove a session from the active list (v2 object format)."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    action = data.get("action")
    if not session_id or action not in ("add", "remove"):
        return jsonify({"error": "session_id and action (add/remove) required"}), 400

    with _chat_ui_lock:
        if action == "add":
            already = any(e.get("session_id") == session_id for e in _chat_ui_state["active_sessions"])
            if not already:
                _chat_ui_state["active_sessions"].insert(0, {"tab_id": None, "session_id": session_id})
                if len(_chat_ui_state["active_sessions"]) > 20:
                    _chat_ui_state["active_sessions"] = _chat_ui_state["active_sessions"][:20]
        elif action == "remove":
            _chat_ui_state["active_sessions"] = [
                e for e in _chat_ui_state["active_sessions"]
                if e.get("session_id") != session_id and e.get("tab_id") != session_id
            ]
        _save_chat_ui_state()

    _broadcast_chat_state()
    return jsonify({"ok": True})


@app.route('/api/chat/state/name', methods=['POST'])
def api_chat_state_name():
    """Set or clear a session's custom name."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    name = data.get("name")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    with _chat_ui_lock:
        if name:
            _chat_ui_state["session_names"][session_id] = name
        else:
            _chat_ui_state["session_names"].pop(session_id, None)
        _save_chat_ui_state()

    _broadcast_chat_state()
    return jsonify({"ok": True})


@app.route('/api/chat/state/migrate', methods=['POST'])
def api_chat_state_migrate():
    """One-time migration from localStorage data (v1 string format -> v2 objects)."""
    data = request.get_json(silent=True) or {}
    active = data.get("active_sessions", [])
    names = data.get("session_names", {})

    with _chat_ui_lock:
        existing_sids = {e.get("session_id") for e in _chat_ui_state["active_sessions"] if e.get("session_id")}
        for sid in reversed(active):
            if isinstance(sid, str) and sid not in existing_sids:
                _chat_ui_state["active_sessions"].insert(0, {"tab_id": None, "session_id": sid})
                existing_sids.add(sid)
        _chat_ui_state["active_sessions"] = _chat_ui_state["active_sessions"][:20]

        for sid, name in names.items():
            if sid not in _chat_ui_state["session_names"]:
                _chat_ui_state["session_names"][sid] = name
        _save_chat_ui_state()

    _broadcast_chat_state()
    return jsonify({"ok": True, "migrated": True})


@app.route('/api/chat/compaction', methods=['POST'])
def api_chat_compaction():
    """Emit a compaction event block into matching Chat tab(s).

    Called by gateway/hooks/compaction-notify.py (PreCompact) and
    gateway/hooks/compaction-done.py (SessionStart:compact) so the dashboard
    Chat tab can show that context was summarized.

    Body: {session_id, event: "start"|"done", trigger?, duration_sec?}
    Matches by claude_session_id[:16] == session_id[:16].
    Localhost-only; no auth (binds to 127.0.0.1 in prod, 0.0.0.0 in config but
    endpoint is idempotent and writes only a UI block).
    """
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()
    event = (data.get("event") or "").strip()
    if not session_id or event not in ("start", "done"):
        return jsonify({"error": "session_id and event (start|done) required"}), 400

    short = session_id[:16]
    trigger = data.get("trigger") or "auto"
    duration_sec = data.get("duration_sec")

    matched_tabs = []
    with _chat_lock:
        for tab_id, sess in CHAT_SESSIONS.items():
            cid = sess.get("claude_session_id") or ""
            if cid and cid[:16] == short:
                matched_tabs.append(tab_id)

    if not matched_tabs:
        return jsonify({"ok": True, "matched": 0})

    for tab_id in matched_tabs:
        if event == "start":
            block = {
                "type": "compaction",
                "state": "running",
                "trigger": trigger,
                "start_time": time.time(),
            }
            _chat_ns._block_add(tab_id, block)
            with _chat_lock:
                sess = CHAT_SESSIONS.get(tab_id)
                if sess is not None:
                    sess["_compaction_block_id"] = block.get("id")
        else:
            with _chat_lock:
                sess = CHAT_SESSIONS.get(tab_id)
                block_id = sess.get("_compaction_block_id") if sess else None
                if sess is not None:
                    sess.pop("_compaction_block_id", None)
            patch = {"state": "done"}
            if isinstance(duration_sec, (int, float)):
                patch["duration_sec"] = duration_sec
            if block_id is not None:
                _chat_ns._block_update(tab_id, block_id, patch)
            else:
                # No matching start block (e.g. server restarted mid-compaction) -
                # emit a standalone "done" block so the event is still visible.
                block = {"type": "compaction", "state": "done", "trigger": trigger}
                if isinstance(duration_sec, (int, float)):
                    block["duration_sec"] = duration_sec
                _chat_ns._block_add(tab_id, block)

    return jsonify({"ok": True, "matched": len(matched_tabs)})


@app.route('/api/chat/state/cancel', methods=['POST'])
def api_chat_state_cancel():
    """Cancel a streaming session by session_id (searches by claude_session_id or tab_id)."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    proc = None
    detached_pid = None
    found_tab = None
    with _chat_lock:
        # Search by claude_session_id or tab_id
        for tab_id, sess in CHAT_SESSIONS.items():
            if sess.get("claude_session_id") == session_id or tab_id == session_id:
                proc = sess.get("process")
                detached_pid = sess.get("_detached_pid")
                found_tab = tab_id
                break

    cancelled = False
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            app.logger.info(f"Cancelled session {session_id[:12]} (tab {(found_tab or '')[:12]}) via API")
            cancelled = True
        except Exception as e:
            app.logger.error(f"Failed to cancel session {session_id[:12]}: {e}")
            return jsonify({"error": str(e)}), 500
    elif detached_pid:
        try:
            import os as _os, signal as _signal
            _os.kill(detached_pid, _signal.SIGTERM)
            app.logger.info(f"Cancelled detached pid {detached_pid} for session {session_id[:12]} via API")
            with _chat_lock:
                if found_tab and found_tab in CHAT_SESSIONS:
                    CHAT_SESSIONS[found_tab]["process_done"] = True
                    CHAT_SESSIONS[found_tab].pop("_detached_pid", None)
            cancelled = True
        except Exception as e:
            app.logger.error(f"Failed to cancel detached session {session_id[:12]}: {e}")
            return jsonify({"error": str(e)}), 500

    if cancelled:
        _broadcast_chat_state()
        return jsonify({"ok": True, "cancelled": True})
    else:
        return jsonify({"ok": True, "cancelled": False, "reason": "not streaming"})


@app.route('/api/chat/state/read', methods=['POST'])
def api_chat_state_read():
    """Mark a session as read (remove from unread list)."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    with _chat_ui_lock:
        _chat_ui_state["unread_sessions"] = [
            s for s in _chat_ui_state.get("unread_sessions", []) if s != session_id
        ]
        _save_chat_ui_state()

    _broadcast_chat_state()
    return jsonify({"ok": True})



@app.route('/api/chat/context-usage', methods=['GET'])
def api_chat_context_usage():
    """Live context-window usage for a chat tab, via SDK get_context_usage().

    Returns: { ok, tab_id, tokens, total, percent, limit, model, tools_count, ... }
    Falls back to 404 if the tab has no active SDK client.
    """
    tab_id = request.args.get("tab_id", "").strip()
    if not tab_id:
        return jsonify({"error": "tab_id required"}), 400

    with _chat_lock:
        sess = CHAT_SESSIONS.get(tab_id)
        if not sess:
            return jsonify({"error": "tab not found"}), 404
        client = sess.get("sdk_client")
        loop = sess.get("sdk_loop")

    if client is None or loop is None:
        return jsonify({"error": "no active SDK client for tab"}), 404

    try:
        fut = asyncio.run_coroutine_threadsafe(client.get_context_usage(), loop)
        resp = fut.result(timeout=5)
    except Exception as e:
        app.logger.warning(f"context_usage failed for tab {tab_id[:12]}: {e}")
        return jsonify({"error": f"context_usage failed: {e}"}), 500

    # SDK returns a ContextUsageResponse dataclass-ish object. Marshal to dict.
    def _pluck(obj, *names):
        for n in names:
            v = getattr(obj, n, None)
            if v is not None:
                return v
        return None

    tokens_total = _pluck(resp, "total_tokens", "tokens_used", "tokens") or 0
    limit = _pluck(resp, "context_window", "limit", "total") or 0
    model = _pluck(resp, "model") or ""
    percent = None
    if isinstance(limit, int) and limit > 0:
        percent = round((tokens_total / limit) * 100, 1)

    # Best-effort full dump for debugging / UI extension
    try:
        raw = resp.__dict__ if hasattr(resp, "__dict__") else {}
    except Exception:
        raw = {}

    return jsonify({
        "ok": True,
        "tab_id": tab_id,
        "tokens": tokens_total,
        "limit": limit,
        "percent": percent,
        "model": model,
        "raw": {k: v for k, v in raw.items() if isinstance(v, (int, float, str, bool, type(None)))},
    })


@app.route('/api/chat/fork', methods=['POST'])
def api_chat_fork():
    """Fork a chat session from a specific user message.

    Creates a new tab that resumes the parent session (the one that existed
    right before the selected user message was sent) with fork_session=True,
    then re-sends the selected user message as the initial prompt. Result:
    a parallel timeline branching at that message.
    """
    import uuid as _uuid
    data = request.get_json(silent=True) or {}
    source_tab_id = data.get("source_tab_id")
    from_block_id = data.get("from_block_id")
    model = data.get("model")
    effort = data.get("effort", "high")
    session_mode = data.get("session_mode", "bypass")

    if not source_tab_id or from_block_id is None or not model:
        return jsonify({"error": "source_tab_id, from_block_id, model required"}), 400

    with _chat_lock:
        sess = CHAT_SESSIONS.get(source_tab_id)
        if not sess:
            return jsonify({"error": "source session not found"}), 404
        blocks = list(sess.get("blocks", []))

    target_idx = None
    target_text = ""
    target_files = []
    for i, b in enumerate(blocks):
        if b.get("type") == "user" and b.get("id") == from_block_id:
            target_idx = i
            target_text = b.get("text", "")
            target_files = b.get("files", []) or []
            break
    if target_idx is None:
        return jsonify({"error": "user block not found in source session"}), 404

    # Parent session = most recent session_id before the selected user message
    parent_session_id = None
    for b in reversed(blocks[:target_idx]):
        sid = b.get("session_id")
        if sid:
            parent_session_id = sid
            break

    prompt = _chat_ns._prepare_prompt(target_text, target_files)
    new_tab_id = _uuid.uuid4().hex

    app.logger.info(
        f"Forking chat: source={source_tab_id[:12]} block_id={from_block_id} "
        f"parent_session={parent_session_id and parent_session_id[:12]} -> new_tab={new_tab_id[:12]}"
    )

    threading.Thread(
        target=_chat_ns._run_claude,
        args=(None, prompt, new_tab_id, parent_session_id, model, effort, session_mode),
        kwargs={"fork_session": True},
        daemon=True,
    ).start()

    return jsonify({
        "ok": True,
        "tab_id": new_tab_id,
        "parent_session_id": parent_session_id,
    })


@app.route('/api/chat/send', methods=['POST'])
def api_chat_send():
    """HTTP fallback for sending chat messages when Socket.IO is unavailable (e.g. mobile)."""
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    tab_id = data.get("tab_id")
    resume_session_id = data.get("resume_session_id")
    model = data.get("model")
    effort = data.get("effort", "high")
    files = data.get("files", [])

    if not prompt and not files:
        return jsonify({"error": "Empty prompt"}), 400
    if not tab_id:
        return jsonify({"error": "tab_id required"}), 400
    if not model:
        return jsonify({"error": "model is required"}), 400

    app.logger.info(f"HTTP chat/send: tab_id={tab_id[:12]}, resume={resume_session_id and resume_session_id[:12]}, model={model}, effort={effort}, prompt_len={len(prompt)}")

    prompt = _chat_ns._prepare_prompt(prompt, files)

    routed = _chat_ns._route_message(prompt, tab_id, resume_session_id, model, effort, "bypass", files)
    if routed:
        return jsonify({"ok": True, "routed": True})

    thread = threading.Thread(
        target=_chat_ns._run_claude,
        args=(None, prompt, tab_id, resume_session_id, model, effort),
        daemon=True
    )
    thread.start()

    return jsonify({"ok": True, "routed": False})


def main():
    """Main entry point."""
    global CONFIG, EXECUTOR

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler("/tmp/webhook-server.log"),
            logging.StreamHandler()
        ]
    )

    # Load config
    global CONFIG, SESSIONS_DIR
    CONFIG = load_config()
    webhook_config = CONFIG.get("webhook", {})
    SESSIONS_DIR = _gateway_config.sessions_dir()

    if not webhook_config.get("enabled", True):
        print("Webhook server is disabled in config")
        sys.exit(0)

    # Load chat UI state
    _load_chat_ui_state()
    app.logger.info(f"Chat UI state loaded: {len(_chat_ui_state['active_sessions'])} active sessions")

    # Recover orphaned streaming Chat sessions from previous instance
    _recover_chat_streams()

    # Start background reaper to kill orphaned Claude SDK subprocesses.
    # Chat sessions are persistent, allow 3hr lifetime before force-kill.
    start_reaper_thread(max_age_seconds=10800)

    # Initialize executor
    EXECUTOR = ClaudeExecutor(log_callback=app.logger.info)

    # Wire up blueprints with runtime dependencies
    init_dashboard_bp(socketio, EXECUTOR, chat_ns=_chat_ns, chat_sessions=CHAT_SESSIONS, chat_lock=_chat_lock)
    init_a2a_bp(CONFIG, EXECUTOR, SESSIONS_DIR, require_auth, rate_limit)

    # Run server
    host = webhook_config.get("host", "127.0.0.1")
    port = webhook_config.get("port", 18788)

    app.logger.info(f"Webhook server starting on {host}:{port}")
    app.logger.info(f"Endpoints:")
    app.logger.info(f"  GET  /health (no auth)")
    app.logger.info(f"  GET  /dashboard (no auth)")
    app.logger.info(f"  GET  /api/dashboard (no auth)")
    app.logger.info(f"  GET  /api/files (no auth)")
    app.logger.info(f"  GET  /api/pipelines (no auth)")
    app.logger.info(f"  GET  /api/tasks (no auth)")
    app.logger.info(f"  POST /api/tasks/update (no auth)")
    app.logger.info(f"  GET  /api/deals (no auth)")
    app.logger.info(f"  GET  /api/people (no auth)")
    app.logger.info(f"  GET  /api/followups (no auth)")
    app.logger.info(f"  GET  /api/calendar (no auth)")
    app.logger.info(f"  GET  /status")
    app.logger.info(f"  POST /trigger/<job_id>")
    app.logger.info(f"  POST /message/<session>")
    app.logger.info(f"A2A Endpoints:")
    app.logger.info(f"  GET  /sessions/list")
    app.logger.info(f"  POST /sessions/<key>/send")
    app.logger.info(f"  GET  /sessions/<key>/history")
    app.logger.info(f"  POST /sessions/spawn")
    app.logger.info(f"Browser GUI:")
    app.logger.info(f"  WS  /chat (Socket.IO namespace)")
    app.logger.info(f"  GET /api/sessions (no auth)")
    app.logger.info(f"Rate limit: {MAX_REQUESTS_PER_HOUR} req/hour")

    socketio.run(
        app,
        host=host,
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
