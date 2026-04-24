"""First-run wizard — /api/wizard/* endpoints.

The wizard is a thin guided overlay on top of the existing /api/settings
pipeline. It does not own the config; it just:

  - probes integrations (Telegram, Claude CLI, Obsidian vault) without
    touching config.yaml so users can verify before saving,
  - runs `launchctl load` on requested plists once the user is ready,
  - stamps `setup.completed_at` so /api/setup/status flips to done.

Everything else (writing values) goes through PATCH /api/settings.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import threading
import time

import yaml
from flask import Blueprint, Response, jsonify, request

from lib import config as _cfg

# Reuse vadimgest's pty-backed AuthSession — already battle-tested for gh,
# gog, wacli, bird. We just register a new command spec for `claude auth
# login`.
try:
    from vadimgest.web.setup import AuthSession, AuthSessionManager, AUTH_COMMANDS, check_auth_state  # type: ignore
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False
    AuthSession = None  # type: ignore
    AuthSessionManager = None  # type: ignore
    AUTH_COMMANDS = {}  # type: ignore
    check_auth_state = lambda method, account=None: {"signed_in": False, "detail": "", "account": None}  # type: ignore

_AUTH_MANAGER = AuthSessionManager() if _AUTH_AVAILABLE else None
_AUTH_LOCK = threading.Lock()

log = logging.getLogger("wizard")

wizard_bp = Blueprint("wizard", __name__)


# ── helpers ───────────────────────────────────────────────────────────

def _json() -> dict[str, Any]:
    data = request.get_json(force=True, silent=True) or {}
    return data if isinstance(data, dict) else {}


def _write_config(updates: dict[str, Any]) -> None:
    """Apply a {dotted.path: value} dict to config.yaml.

    Thin mirror of the PATCH /api/settings writer, local here so the wizard
    can stamp `setup.completed_at` without going through the secret-redaction
    path.
    """
    path = _cfg.DEFAULT_CONFIG_PATH
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    for dotted, value in updates.items():
        parts = dotted.split(".")
        node = raw
        for key in parts[:-1]:
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                node[key] = nxt
            node = nxt
        node[parts[-1]] = value
    with open(path, "w") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
    _cfg.reload()


# ── integration probes ────────────────────────────────────────────────

@wizard_bp.route("/api/wizard/test-telegram", methods=["POST"])
def wizard_test_telegram():
    """Send a test message to the provided bot_token + chat_id.

    Does NOT persist anything — caller passes values directly so we can
    verify before saving.
    """
    payload = _json()
    bot_token = (payload.get("bot_token") or "").strip()
    chat_id = payload.get("chat_id")

    if not bot_token:
        return jsonify({"ok": False, "error": "bot_token is required"}), 400
    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "chat_id must be a number"}), 400

    try:
        from lib.telegram_utils import _tg_api_call
    except ImportError as e:
        return jsonify({"ok": False, "error": f"telegram_utils unavailable: {e}"}), 500

    # 1. Validate the token via getMe — cheap, no side effects.
    me = _tg_api_call(
        f"https://api.telegram.org/bot{bot_token}/getMe",
        {}, timeout=8,
    )
    if not me.get("ok"):
        desc = me.get("description") or "token rejected by Telegram API"
        return jsonify({"ok": False, "stage": "getMe", "error": desc}), 200

    bot_username = me.get("result", {}).get("username") or "unknown"

    # 2. Send the test message.
    send = _tg_api_call(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        {"chat_id": chat_id_int,
         "text": f"✅ Klava wizard test — @{bot_username} can reach this chat."},
        timeout=8,
    )
    if not send.get("ok"):
        desc = send.get("description") or "send failed"
        return jsonify({
            "ok": False,
            "stage": "sendMessage",
            "error": desc,
            "hint": "Make sure you've started a conversation with the bot, "
                    "or that chat_id is correct.",
            "bot_username": bot_username,
        }), 200

    return jsonify({"ok": True, "bot_username": bot_username})


@wizard_bp.route("/api/wizard/test-claude", methods=["POST"])
def wizard_test_claude():
    """Check that the Claude Code CLI is installed and reports a version.

    We intentionally don't try to run a Claude session — that requires auth
    and burns tokens. `claude --version` is enough to confirm install + PATH.
    """
    payload = _json()
    cli = (payload.get("claude_cli") or "claude").strip()

    try:
        result = subprocess.run(
            [cli, "--version"],
            capture_output=True, text=True, timeout=8,
        )
    except FileNotFoundError:
        return jsonify({
            "ok": False,
            "error": f"`{cli}` not found on PATH",
            "hint": "Install with `npm install -g @anthropic-ai/claude-code`.",
        }), 200
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": f"`{cli} --version` timed out"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200

    if result.returncode != 0:
        return jsonify({
            "ok": False,
            "error": (result.stderr or result.stdout or "non-zero exit").strip(),
        }), 200

    version = (result.stdout or "").strip() or "unknown"
    return jsonify({"ok": True, "version": version, "cli": cli})


@wizard_bp.route("/api/wizard/test-obsidian", methods=["POST"])
def wizard_test_obsidian():
    """Verify that the Obsidian vault path exists and looks like a vault.

    If `create` is set on the payload, mkdir -p the path first — used by the
    wizard's "Create folder" button when the user hasn't set up Obsidian yet.
    """
    payload = _json()
    raw = (payload.get("vault_path") or "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "vault_path is required"}), 400

    vault = Path(os.path.expanduser(raw))
    if payload.get("create") and not vault.exists():
        try:
            vault.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({"ok": False, "error": f"mkdir failed: {e}"}), 200
    if not vault.exists():
        return jsonify({
            "ok": False,
            "error": f"{vault} does not exist",
            "path": str(vault),
            "can_create": True,
        }), 200
    if not vault.is_dir():
        return jsonify({"ok": False, "error": f"{vault} is not a directory"}), 200

    marker = vault / ".obsidian"
    has_marker = marker.is_dir()
    md_count = sum(1 for _ in vault.glob("*.md"))

    # Empty/new folder is a valid answer — Klava will populate it.
    # Surface the "doesn't look like a vault yet" state as a soft warning
    # via md_count=0 + has_obsidian_marker=false, but let the user continue.
    return jsonify({
        "ok": True,
        "path": str(vault),
        "has_obsidian_marker": has_marker,
        "md_count": md_count,
    })


# ── cron / launchd ────────────────────────────────────────────────────

@wizard_bp.route("/api/wizard/plists", methods=["GET"])
def wizard_list_plists():
    """List installed LaunchAgent plists matching the configured prefix.

    Returns each plist with its label and current load state so the wizard
    can offer checkboxes and show what's already running.
    """
    cfg = _cfg.load()
    prefix = cfg.get("identity", {}).get("launchd_prefix", "com.local")
    la_dir = Path.home() / "Library" / "LaunchAgents"
    if not la_dir.exists():
        return jsonify({"plists": [], "launch_agents_dir": str(la_dir)})

    try:
        loaded = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception:
        loaded = ""

    plists = []
    for plist in sorted(la_dir.glob(f"{prefix}.*.plist")):
        label = plist.stem
        is_loaded = bool(label) and any(
            line.endswith(f"\t{label}") or line.split("\t")[-1] == label
            for line in loaded.splitlines()
        )
        plists.append({
            "label": label,
            "path": str(plist),
            "loaded": is_loaded,
            "name": label.removeprefix(f"{prefix}."),
        })

    return jsonify({
        "plists": plists,
        "launch_agents_dir": str(la_dir),
        "prefix": prefix,
    })


@wizard_bp.route("/api/wizard/enable-crons", methods=["POST"])
def wizard_enable_crons():
    """Run `launchctl load` on the selected plist paths.

    Only touches plists inside ~/Library/LaunchAgents that match the
    configured `identity.launchd_prefix` — guards against path traversal.
    Also flips `cron.enabled: true` in config.yaml so the scheduler actually
    picks up jobs.
    """
    payload = _json()
    labels = payload.get("labels") or []
    if not isinstance(labels, list):
        return jsonify({"ok": False, "error": "labels must be a list"}), 400

    cfg = _cfg.load()
    prefix = cfg.get("identity", {}).get("launchd_prefix", "com.local")
    la_dir = (Path.home() / "Library" / "LaunchAgents").resolve()

    results = []
    for label in labels:
        if not isinstance(label, str) or not label.startswith(f"{prefix}."):
            results.append({"label": label, "ok": False,
                            "error": f"label must start with {prefix}."})
            continue

        plist = (la_dir / f"{label}.plist").resolve()
        if not str(plist).startswith(str(la_dir) + os.sep):
            results.append({"label": label, "ok": False,
                            "error": "path traversal rejected"})
            continue
        if not plist.exists():
            results.append({"label": label, "ok": False,
                            "error": f"{plist.name} not found"})
            continue

        # Best effort: unload first so we don't error on an already-loaded plist.
        subprocess.run(["launchctl", "unload", str(plist)],
                       capture_output=True, timeout=10)
        proc = subprocess.run(
            ["launchctl", "load", str(plist)],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            results.append({
                "label": label,
                "ok": False,
                "error": (proc.stderr or proc.stdout or "launchctl failed").strip(),
            })
        else:
            results.append({"label": label, "ok": True})

    # Flip cron.enabled = True if any scheduler plist loaded successfully.
    if any(r["ok"] for r in results
           if r["label"].endswith(".cron-scheduler")):
        try:
            _write_config({"cron.enabled": True})
        except Exception as e:
            log.warning(f"could not flip cron.enabled: {e}")

    any_ok = any(r["ok"] for r in results)
    return jsonify({"ok": any_ok, "results": results})


# ── Claude CLI auth (pty-backed login flow) ───────────────────────────
#
# The `claude auth` subcommand owns login state. We spawn `claude auth
# login` inside a pty, stream its output so the browser can show the
# OAuth URL / device code, and poll `claude auth status --json` to detect
# completion.

def _claude_cli() -> str:
    """Pick the claude binary, honoring any wizard-configured override."""
    payload = _json() if request.method == "POST" else {}
    cli = (payload.get("claude_cli") or "").strip()
    return cli or os.environ.get("CLAUDE_BIN", "claude")


def _claude_auth_status(cli: str = "claude") -> dict:
    """Return {installed, logged_in, raw} for the given claude binary.

    Runs `claude auth status --json` with a short timeout. Any failure
    => installed=False or logged_in=False (conservative).
    """
    try:
        r = subprocess.run(
            [cli, "auth", "status", "--json"],
            capture_output=True, text=True, timeout=8,
        )
    except FileNotFoundError:
        return {"installed": False, "logged_in": False, "raw": None, "error": f"{cli} not found"}
    except subprocess.TimeoutExpired:
        return {"installed": True, "logged_in": False, "raw": None, "error": "timeout"}
    except Exception as e:
        return {"installed": False, "logged_in": False, "raw": None, "error": str(e)}

    if r.returncode != 0 and not r.stdout.strip():
        return {"installed": True, "logged_in": False, "raw": None,
                "error": (r.stderr or r.stdout or "non-zero exit").strip()}

    try:
        parsed = json.loads(r.stdout)
    except Exception:
        return {"installed": True, "logged_in": False, "raw": r.stdout.strip(), "error": "unparseable JSON"}

    return {
        "installed": True,
        "logged_in": bool(parsed.get("loggedIn")),
        "raw": parsed,
        "error": None,
    }


@wizard_bp.route("/api/wizard/claude-auth-status", methods=["GET", "POST"])
def wizard_claude_auth_status():
    cli = _claude_cli()
    return jsonify({"cli": cli, **_claude_auth_status(cli)})


@wizard_bp.route("/api/wizard/claude-auth-start", methods=["POST"])
def wizard_claude_auth_start():
    """Spawn `claude auth login` in a pty. Returns a session id.

    Stream output via /api/wizard/claude-auth-stream/<sid>. Poll status via
    /api/wizard/claude-auth-status (which doesn't use the session — it
    asks the CLI directly).
    """
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({
            "ok": False,
            "error": "vadimgest.web.setup.AuthSession not importable — "
                     "reinstall vadimgest: pip install -e vadimgest[all]",
        }), 500

    cli = _claude_cli()
    already = _claude_auth_status(cli)
    if not already.get("installed"):
        return jsonify({
            "ok": False,
            "error": f"{cli} not found on PATH",
            "hint": "Run ./setup.sh (it auto-installs claude via npm).",
        }), 400

    try:
        sess = _AUTH_MANAGER.create(
            source_name="claude",
            command=[cli, "auth", "login"],
            parser="generic",
            env={"NO_COLOR": "1", "TERM": "dumb"},
        )
        return jsonify({"ok": True, "session": sess.snapshot()})
    except Exception as e:
        log.exception("claude auth session start failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@wizard_bp.route("/api/wizard/claude-auth-stream/<sid>")
def wizard_claude_auth_stream(sid: str):
    """Server-sent events: stream pty output as JSON snapshots."""
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"error": "auth sessions unavailable"}), 500
    sess = _AUTH_MANAGER.get(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404

    def stream():
        last = None
        while True:
            snap = sess.snapshot()
            key = (len(snap["lines"]), snap["done"], snap["device_code"],
                   snap["verification_url"], snap["summary"])
            if key != last:
                yield f"data: {json.dumps(snap)}\n\n"
                last = key
            if snap["done"]:
                return
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@wizard_bp.route("/api/wizard/claude-auth-snapshot/<sid>", methods=["GET"])
def wizard_claude_auth_snapshot(sid: str):
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"error": "auth sessions unavailable"}), 500
    sess = _AUTH_MANAGER.get(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404
    return jsonify(sess.snapshot())


@wizard_bp.route("/api/wizard/claude-auth-stop/<sid>", methods=["POST"])
def wizard_claude_auth_stop(sid: str):
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"error": "auth sessions unavailable"}), 500
    sess = _AUTH_MANAGER.get(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404
    sess.stop()
    return jsonify({"ok": True})


# ── generic CLI-auth (gh, gog, etc.) — reuses vadimgest's AUTH_COMMANDS ─
#
# Rather than duplicating `gh auth login`, `gog auth add`, `wacli auth`, etc.
# per-tool, we treat them uniformly: client posts {method: "gh"|"gog"|...},
# server spawns the right command in a pty, streams output. check_auth_state
# (from vadimgest) probes whether the user is already signed in so the UI
# can skip to green without re-running the CLI.

def _cli_method() -> str:
    payload = _json() if request.method == "POST" else {}
    return (payload.get("method") or request.args.get("method") or "").strip()


@wizard_bp.route("/api/wizard/cli-auth-status", methods=["GET", "POST"])
def wizard_cli_auth_status():
    method = _cli_method()
    if not method:
        return jsonify({"error": "method required"}), 400
    if not _AUTH_AVAILABLE:
        return jsonify({"method": method, "signed_in": False, "error": "vadimgest auth module unavailable"}), 500
    account = None
    if request.method == "POST":
        account = (_json().get("account") or "").strip() or None
    state = check_auth_state(method, account)
    return jsonify({"method": method, **state})


@wizard_bp.route("/api/wizard/cli-auth-start", methods=["POST"])
def wizard_cli_auth_start():
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"ok": False, "error": "auth sessions unavailable"}), 500
    payload = _json()
    method = (payload.get("method") or "").strip()
    account = (payload.get("account") or "").strip()
    if not method:
        return jsonify({"ok": False, "error": "method required"}), 400

    spec = AUTH_COMMANDS.get(method)
    if not spec:
        return jsonify({"ok": False, "error": f"unknown method: {method}"}), 400

    if "command_fn" in spec:
        if not account:
            return jsonify({"ok": False, "error": "account required for this method"}), 400
        command = spec["command_fn"](account)
    else:
        command = list(spec["command"])

    if not shutil.which(command[0]):
        return jsonify({
            "ok": False,
            "error": f"`{command[0]}` not on PATH",
            "needs_install": command[0],
            "hint": _install_hint(command[0]),
        }), 400

    try:
        env = dict(spec.get("env") or {})
        # gog's file-based keyring encrypts tokens at rest and prompts for a
        # password interactively — which hangs any subprocess without a TTY.
        # Provide a fixed passphrase via env so the write succeeds headlessly.
        # This is local-at-rest encryption only; the password doesn't need
        # to be secret (the keyring file is already protected by macOS
        # filesystem permissions on the user's home dir).
        if method == "gog":
            env.setdefault("GOG_KEYRING_PASSWORD", os.environ.get("GOG_KEYRING_PASSWORD", "klava-default-keyring"))
        sess = _AUTH_MANAGER.create(
            source_name=method,
            command=command,
            parser=spec.get("parser", "generic"),
            env=env,
        )
        return jsonify({"ok": True, "session": sess.snapshot()})
    except Exception as e:
        log.exception("cli-auth-start failed for %s", method)
        return jsonify({"ok": False, "error": str(e)}), 500


@wizard_bp.route("/api/wizard/cli-auth-snapshot/<sid>", methods=["GET"])
def wizard_cli_auth_snapshot(sid: str):
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"error": "auth sessions unavailable"}), 500
    sess = _AUTH_MANAGER.get(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404
    return jsonify(sess.snapshot())


@wizard_bp.route("/api/wizard/cli-auth-stream/<sid>")
def wizard_cli_auth_stream(sid: str):
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"error": "auth sessions unavailable"}), 500
    sess = _AUTH_MANAGER.get(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404

    def stream():
        last = None
        while True:
            snap = sess.snapshot()
            key = (len(snap["lines"]), snap["done"], snap["device_code"],
                   snap["verification_url"], snap["summary"])
            if key != last:
                yield f"data: {json.dumps(snap)}\n\n"
                last = key
            if snap["done"]:
                return
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@wizard_bp.route("/api/wizard/cli-auth-stop/<sid>", methods=["POST"])
def wizard_cli_auth_stop(sid: str):
    if not _AUTH_AVAILABLE or _AUTH_MANAGER is None:
        return jsonify({"error": "auth sessions unavailable"}), 500
    sess = _AUTH_MANAGER.get(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404
    sess.stop()
    return jsonify({"ok": True})


def _install_hint(tool: str) -> str:
    return {
        "gh": "Install with `brew install gh`.",
        "gog": "Install with `brew install gogcli`.",
        "bird": "Install with `brew install bird`.",
        "wacli": "Install with `brew install wacli`.",
        "claude": "Install with `npm install -g @anthropic-ai/claude-code`.",
    }.get(tool, "")


# ── gog credentials override ──────────────────────────────────────────
#
# The repo ships a default OAuth Desktop client in klava-shared/
# gog-credentials.json that setup.sh copies to the user's gogcli config.
# This endpoint lets power users paste their own client JSON at any time
# without touching the filesystem.

@wizard_bp.route("/api/wizard/gog-credentials", methods=["POST"])
def wizard_gog_credentials():
    """Overwrite ~/Library/Application Support/gogcli/credentials.json.

    Payload: {content: "<raw JSON string>"}. Content must parse as JSON
    and have either top-level client_id/client_secret (flat gog format)
    or nested under "installed" (Google Cloud download format).
    """
    payload = _json()
    content = (payload.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "content is required"}), 400

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"not valid JSON: {e}"}), 400

    # Normalize: gog expects flat {client_id, client_secret}. Google Cloud
    # Console downloads nest under {"installed": {...}} — unwrap that.
    if isinstance(parsed, dict) and "installed" in parsed and isinstance(parsed["installed"], dict):
        src = parsed["installed"]
        parsed = {
            "client_id": src.get("client_id", ""),
            "client_secret": src.get("client_secret", ""),
        }

    if not parsed.get("client_id") or not parsed.get("client_secret"):
        return jsonify({
            "ok": False,
            "error": "JSON must contain client_id and client_secret",
        }), 400

    gog_dir = os.path.expanduser("~/Library/Application Support/gogcli")
    try:
        os.makedirs(gog_dir, exist_ok=True)
        with open(os.path.join(gog_dir, "credentials.json"), "w") as f:
            json.dump(parsed, f, indent=2)
    except Exception as e:
        return jsonify({"ok": False, "error": f"write failed: {e}"}), 500

    return jsonify({"ok": True, "client_id": parsed["client_id"]})


# ── Google Tasks list selection ───────────────────────────────────────
#
# After `gog auth`, the user still needs to pick which Google Tasks list
# Klava should treat as its queue (and the consumer's source of truth).
# Without this, gateway/lib/config.py keeps reading the example placeholder
# `your-google-tasks-list-id` and every /api/klava/tasks request 500s.

@wizard_bp.route("/api/wizard/google-tasks-lists", methods=["GET"])
def wizard_google_tasks_lists():
    """Enumerate the user's Google Tasks lists via `gog tasks lists --json`.

    Query: ?account=<email> (falls back to identity.email from config).
    Returns: {ok, lists: [{id, title}, ...]} or {ok: false, error}.
    """
    account = (request.args.get("account") or _cfg.email() or "").strip()
    if not account:
        return jsonify({"ok": False, "error": "account email required"}), 400

    bin_path = _cfg.google_cli()
    if not bin_path or (bin_path != "gog" and not os.path.exists(bin_path)):
        # google_cli() falls back through ~/bin/gog -> shutil.which -> "gog";
        # if the result still isn't on disk, the gog CLI isn't installed.
        if not shutil.which("gog"):
            return jsonify({
                "ok": False,
                "error": "gog CLI not installed",
                "hint": "Install with `brew install gogcli`, then run the Google sign-in step.",
            }), 400

    env = dict(os.environ)
    env.setdefault("GOG_KEYRING_PASSWORD", "klava-default-keyring")
    try:
        result = subprocess.run(
            [bin_path, "-a", account, "tasks", "lists", "--json", "--results-only"],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except FileNotFoundError:
        return jsonify({"ok": False, "error": f"`{bin_path}` not found"}), 400
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "gog timed out (15s)"}), 504

    if result.returncode != 0:
        err = (result.stderr or "").strip()[:400] or "gog tasks lists failed"
        hint = None
        if "no token" in err.lower() or "not signed" in err.lower():
            hint = "Run the Google sign-in step first."
        return jsonify({"ok": False, "error": err, "hint": hint}), 200

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"gog returned non-JSON: {e}"}), 200

    # gog with --results-only on `tasks lists` returns either a list or
    # an object with `tasklists`. Normalize.
    raw_lists = payload if isinstance(payload, list) else payload.get("tasklists", [])
    lists = [
        {"id": item.get("id"), "title": item.get("title", "")}
        for item in raw_lists
        if item.get("id")
    ]
    return jsonify({"ok": True, "lists": lists, "account": account})


@wizard_bp.route("/api/wizard/google-tasks-list-select", methods=["POST"])
def wizard_google_tasks_list_select():
    """Persist the user's chosen Klava list to config.yaml.

    Payload: {name: "Klava", list_id: "Qm5u..."}. Writes
      tasks.gtasks_list = name
      integrations.google.tasks_lists = {name: list_id}

    Replaces the entire tasks_lists dict on purpose — the wizard is for
    the single-list common case. Power users with multiple lists can
    still edit gateway/config.yaml directly afterwards.
    """
    payload = _json()
    name = (payload.get("name") or "").strip()
    list_id = (payload.get("list_id") or "").strip()
    if not name or not list_id:
        return jsonify({"ok": False, "error": "name and list_id are required"}), 400

    try:
        path = _cfg.DEFAULT_CONFIG_PATH
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        raw.setdefault("tasks", {})["gtasks_list"] = name
        google = raw.setdefault("integrations", {}).setdefault("google", {}) or {}
        raw["integrations"]["google"] = google
        google["tasks_lists"] = {name: list_id}
        with open(path, "w") as f:
            yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
        _cfg.reload()
    except Exception as e:
        log.exception("google-tasks-list-select failed")
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "name": name, "list_id": list_id})


# ── .env writer (API keys the wizard asks for directly) ───────────────

@wizard_bp.route("/api/wizard/env-write", methods=["POST"])
def wizard_env_write():
    """Upsert KEY=VALUE pairs into the repo's .env file.

    Payload: {updates: {KEY: VALUE, ...}}. Only keys matching [A-Z_][A-Z0-9_]*
    are accepted — anything else is a typo. Empty VALUE removes the line so
    the user can blank out a stale key.
    """
    payload = _json()
    updates = payload.get("updates") or {}
    if not isinstance(updates, dict):
        return jsonify({"ok": False, "error": "updates must be an object"}), 400

    env_path = _cfg.DEFAULT_CONFIG_PATH.parent.parent / ".env"
    try:
        lines = env_path.read_text().splitlines() if env_path.exists() else []
    except Exception as e:
        return jsonify({"ok": False, "error": f"read .env: {e}"}), 500

    import re as _re
    key_re = _re.compile(r"^[A-Z_][A-Z0-9_]*$")
    bad = [k for k in updates if not key_re.match(k)]
    if bad:
        return jsonify({"ok": False, "error": f"invalid key names: {bad}"}), 400

    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        k = line.split("=", 1)[0].strip()
        if k in updates:
            seen.add(k)
            v = updates[k]
            if v == "" or v is None:
                continue  # drop the line
            out.append(f"{k}={v}")
        else:
            out.append(line)
    # Append any keys we didn't see in existing .env.
    for k, v in updates.items():
        if k in seen:
            continue
        if v == "" or v is None:
            continue
        out.append(f"{k}={v}")

    try:
        env_path.write_text("\n".join(out) + "\n")
    except Exception as e:
        return jsonify({"ok": False, "error": f"write .env: {e}"}), 500

    return jsonify({"ok": True, "written": [k for k, v in updates.items() if v]})


# ── completion ────────────────────────────────────────────────────────

@wizard_bp.route("/api/wizard/complete", methods=["POST"])
def wizard_complete():
    """Stamp setup.completed_at so the wizard stops auto-showing.

    Idempotent — safe to call multiple times. The timestamp reflects the
    most recent completion; re-running the wizard overwrites it.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        _write_config({
            "setup.completed_at": now,
            "setup.completed_by": "wizard",
        })
    except Exception as e:
        log.exception("wizard complete failed")
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "completed_at": now})


@wizard_bp.route("/api/wizard/reset", methods=["POST"])
def wizard_reset():
    """Clear setup.completed_at so the wizard shows again.

    Useful for the 'Run the wizard again' button in the Settings header.
    """
    try:
        cfg_path = _cfg.DEFAULT_CONFIG_PATH
        with open(cfg_path) as f:
            raw = yaml.safe_load(f) or {}
        if isinstance(raw.get("setup"), dict):
            raw["setup"].pop("completed_at", None)
            raw["setup"].pop("completed_by", None)
            if not raw["setup"]:
                raw.pop("setup")
        with open(cfg_path, "w") as f:
            yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
        _cfg.reload()
    except Exception as e:
        log.exception("wizard reset failed")
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})
