"""Auth helper for dashboard mutating routes.

The dashboard's read endpoints are intentionally unauth'd — the user
needs them to render the UI and the listener defaults to 127.0.0.1.
Mutating routes (PATCH /api/settings, /api/self-evolve/run, daemon
restart, wizard env-write/gog-credentials, agents/kill, klava task
mutations, etc.) are riskier and must be gated when the listener is
exposed beyond the local host.

Policy is driven by `webhook.require_auth` in gateway/config.yaml:

  - "auto"   (default) — require token unless the request's remote
                          address is loopback (127.0.0.1 or ::1).
  - "always" — require token regardless of remote address.
  - "never"  — never check (legacy / single-user setups behind a
               trusted reverse proxy).

The token is `webhook.token` from the same config block. When auth is
required and the token is unset, every check fails closed — refusing
to mutate state on a misconfigured install is safer than allowing it.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import jsonify, request

from lib import config as _cfg


_LOOPBACK_ADDRS = {"127.0.0.1", "::1", "localhost"}


def _client_is_loopback() -> bool:
    addr = (request.remote_addr or "").strip()
    return addr in _LOOPBACK_ADDRS


def _extract_token() -> str:
    # Bearer header (preferred — matches a2a.py and the trigger endpoint).
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # X-Webhook-Token fallback for clients that can't set Authorization
    # (e.g. EventSource / SSE).
    return (request.headers.get("X-Webhook-Token") or "").strip()


def _check() -> tuple[bool, str | None]:
    """Returns (allowed, error_message). Error is None when allowed."""
    mode = _cfg.webhook_require_auth()
    if mode == "never":
        return True, None
    if mode == "auto" and _client_is_loopback():
        return True, None
    expected = _cfg.webhook_token()
    if not expected:
        return False, "auth required but webhook.token is not configured"
    presented = _extract_token()
    if not presented:
        return False, "missing Authorization: Bearer <token> header"
    if presented != expected:
        return False, "invalid token"
    return True, None


def require_auth(view: Callable) -> Callable:
    """Decorate a Flask view function to require auth per the policy above."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        ok, err = _check()
        if not ok:
            return jsonify({"error": err, "code": "auth_required"}), 401
        return view(*args, **kwargs)

    return wrapper


# Endpoints that bypass the blueprint-level mutating-method gate. The
# wizard auth probes need to run during initial setup before the user has
# set webhook.token; CLI auth flows write their own state via subprocess
# pty (no config writes). Listed by `request.endpoint` (= "<bp>.<func>").
_GATE_ALLOWLIST = {
    # Wizard probes that touch no persistent state
    "wizard.wizard_test_telegram",
    "wizard.wizard_test_claude",
    "wizard.wizard_test_obsidian",
    # Wizard CLI-auth pty management — needed during onboarding before
    # any token is configured. Each session is per-user keyed via the
    # subprocess sandbox; no persistent writes.
    "wizard.wizard_claude_auth_status",
    "wizard.wizard_claude_auth_start",
    "wizard.wizard_claude_auth_stop",
    "wizard.wizard_cli_auth_status",
    "wizard.wizard_cli_auth_start",
    "wizard.wizard_cli_auth_stop",
}


def install_mutation_gate(app) -> None:
    """Install an app-level before_request hook that gates POST/PATCH/DELETE/PUT.

    Applied at the Flask app level (not per-blueprint) so the order of
    blueprint registration doesn't matter — Flask refuses
    `before_request` on a blueprint after first registration. Read
    endpoints (GET) and a2a routes (which have their own token auth)
    are skipped by endpoint prefix or method.
    """
    from flask import request

    @app.before_request
    def _enforce():
        if request.method not in ("POST", "PATCH", "DELETE", "PUT"):
            return None
        ep = request.endpoint or ""
        # a2a routes already enforce auth via _check_auth() — skip to
        # avoid double-checking and duplicate 401 messages.
        if ep.startswith("a2a."):
            return None
        if ep in _GATE_ALLOWLIST:
            return None
        ok, err = _check()
        if not ok:
            return jsonify({"error": err, "code": "auth_required"}), 401
        return None
