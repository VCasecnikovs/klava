"""Regression tests for the activity-based session liveness check.

Before the fix, the dashboard's "session is streaming" indicator was gated on
the `session_idle` boolean only, which flipped to True the instant a
ResultMessage arrived. Any backend write between turns (Monitor-driven turn,
late server tool result, error block, etc.) left the indicator wrongly off.

The new `_session_is_active` helper uses a grace window: a session keeps
showing as live for `_SESSION_ACTIVITY_GRACE_S` seconds after the last
backend write, even if `session_idle` is True. Auto-resurrect inside
`_block_add` / `_block_update` then flips `session_idle` back to False the
moment any block lands.

These tests pin the behavior so the indicator can't silently regress.
"""

import os
import sys
import importlib.util


def _load_ws():
    spec = importlib.util.spec_from_file_location(
        "webhook_server",
        os.path.join(os.path.dirname(__file__), "..", "webhook-server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["webhook_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_session_alive_when_sdk_connected_and_not_idle():
    ws = _load_ws()
    sess = {
        "sdk_client": object(),
        "process_done": False,
        "session_idle": False,
        "last_activity_ts": 1000.0,
        "started": 900.0,
    }
    assert ws._session_is_active(sess, now=1010.0) is True


def test_session_alive_within_grace_window_after_idle():
    ws = _load_ws()
    sess = {
        "sdk_client": object(),
        "process_done": False,
        "session_idle": True,
        "last_activity_ts": 1000.0,
        "started": 900.0,
    }
    # 2 seconds after last write, still inside the 5s grace window
    assert ws._session_is_active(sess, now=1002.0) is True


def test_session_dead_after_grace_window_expires():
    ws = _load_ws()
    sess = {
        "sdk_client": object(),
        "process_done": False,
        "session_idle": True,
        "last_activity_ts": 1000.0,
        "started": 900.0,
    }
    # Past the 5s grace window — truly idle now
    assert ws._session_is_active(sess, now=1006.0) is False


def test_session_dead_when_process_done():
    ws = _load_ws()
    sess = {
        "sdk_client": object(),
        "process_done": True,
        "session_idle": False,
        "last_activity_ts": 1000.0,
        "started": 900.0,
    }
    assert ws._session_is_active(sess, now=1001.0) is False


def test_detached_pid_keeps_session_alive():
    ws = _load_ws()
    sess = {
        "_detached_pid": 12345,
        "process_done": False,
        "session_idle": True,
        "last_activity_ts": 0.0,
        "started": 0.0,
    }
    assert ws._session_is_active(sess, now=99999.0) is True


def test_startup_grace_for_session_without_runtime():
    ws = _load_ws()
    sess = {
        "process_done": False,
        "session_idle": False,
        "started": 1000.0,
        "last_activity_ts": 1000.0,
    }
    # Within startup grace
    assert ws._session_is_active(sess, now=1010.0) is True
    # Past startup grace
    assert ws._session_is_active(sess, now=1040.0) is False


def test_block_add_resurrects_idle_session():
    """Any backend write while idle should flip the session back to live."""
    ws = _load_ws()
    tab_id = "tab-resurrect-test"
    sdk_client = object()
    ws.CHAT_SESSIONS[tab_id] = {
        "sdk_client": sdk_client,
        "process_done": False,
        "session_idle": True,
        "last_activity_ts": 0.0,
        "started": 1000.0,
        "socket_sids": set(),
        "blocks": [],
    }
    try:
        ns = ws.ChatNamespace("/chat")
        ns._block_add(tab_id, {"type": "tool_result", "content": "ok"})
        assert ws.CHAT_SESSIONS[tab_id]["session_idle"] is False
        assert ws.CHAT_SESSIONS[tab_id]["last_activity_ts"] > 0
    finally:
        ws.CHAT_SESSIONS.pop(tab_id, None)


def test_block_update_resurrects_idle_session():
    ws = _load_ws()
    tab_id = "tab-resurrect-update-test"
    ws.CHAT_SESSIONS[tab_id] = {
        "sdk_client": object(),
        "process_done": False,
        "session_idle": True,
        "last_activity_ts": 0.0,
        "started": 1000.0,
        "socket_sids": set(),
        "blocks": [{"id": 0, "type": "assistant", "text": ""}],
    }
    try:
        ns = ws.ChatNamespace("/chat")
        ns._block_update(tab_id, 0, {"text": "hello"})
        assert ws.CHAT_SESSIONS[tab_id]["session_idle"] is False
        assert ws.CHAT_SESSIONS[tab_id]["blocks"][0]["text"] == "hello"
    finally:
        ws.CHAT_SESSIONS.pop(tab_id, None)
