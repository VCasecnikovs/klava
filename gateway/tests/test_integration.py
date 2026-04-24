"""Integration tests for chat flow, session lifecycle, and WebSocket state sync.

Tests the three paths that break most often:
1. Chat flow: send message -> routing -> state update -> broadcast
2. Session lifecycle: create -> rename -> draft -> recover
3. WebSocket sync: multi-client state consistency

Uses flask_socketio test client with mocked Claude SDK to avoid real processes.
"""

import os
import sys
import json
import time
import threading
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure gateway is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("WEBHOOK_TOKEN", "test-token-12345")


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset all global mutable state before each test."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "webhook_server",
        os.path.join(os.path.dirname(__file__), "..", "webhook-server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["webhook_server"] = mod
    spec.loader.exec_module(mod)

    # Reset globals
    mod.CHAT_SESSIONS.clear()
    mod.SOCKET_TO_SESSIONS.clear()
    mod.SESSION_WATCHERS.clear()

    yield mod

    # Cleanup
    mod.CHAT_SESSIONS.clear()
    mod.SOCKET_TO_SESSIONS.clear()
    mod.SESSION_WATCHERS.clear()


@pytest.fixture
def ws(_reset_global_state):
    """Return the webhook_server module."""
    return _reset_global_state


@pytest.fixture
def app_sio(ws):
    """Create Flask app + SocketIO for testing."""
    ws.app.config["TESTING"] = True
    return ws.app, ws.socketio


@pytest.fixture
def client1(app_sio):
    """First SocketIO test client."""
    app, sio = app_sio
    return sio.test_client(app, namespace="/chat")


@pytest.fixture
def client2(app_sio):
    """Second SocketIO test client."""
    app, sio = app_sio
    return sio.test_client(app, namespace="/chat")


@pytest.fixture
def http_client(app_sio):
    """HTTP test client."""
    app, _ = app_sio
    return app.test_client()


@pytest.fixture
def state_file(tmp_path, ws):
    """Override CHAT_UI_STATE_FILE to use tmp_path."""
    f = tmp_path / "chat-ui.json"
    f.write_text(json.dumps({
        "version": 2,
        "active_sessions": [],
        "session_names": {},
        "unread_sessions": [],
        "drafts": {},
        "updated_at": "",
    }))
    ws.CHAT_UI_STATE_FILE = f
    ws._load_chat_ui_state()
    return f


@pytest.fixture
def stream_file(tmp_path, ws):
    """Override CHAT_STREAM_STATE to use tmp_path."""
    f = tmp_path / "streaming.json"
    f.write_text("{}")
    ws.CHAT_STREAM_STATE = f
    ws.CHAT_STREAM_DIR = tmp_path
    return f


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_sid(ws, client):
    """Get the namespace SID for a test client."""
    return ws.socketio.server.manager.sid_from_eio_sid(client.eio_sid, "/chat")


def get_events(client, name):
    """Get all received events of a given type."""
    return [r for r in client.get_received("/chat") if r["name"] == name]


def last_state_sync(client):
    """Get the most recent chat_state_sync event data."""
    events = get_events(client, "chat_state_sync")
    return events[-1]["args"][0] if events else None


def make_session(ws, tab_id, claude_session_id=None, done=False, idle=False):
    """Populate CHAT_SESSIONS to simulate a session."""
    import asyncio
    with ws._chat_lock:
        ws.CHAT_SESSIONS[tab_id] = {
            "sdk_client": MagicMock() if not done else None,
            "sdk_loop": MagicMock() if not done else None,
            "sdk_queue": None,
            "incoming_queue": asyncio.Queue() if not done else None,
            "process": None,
            "socket_sids": set(),
            "blocks": [{"type": "user", "id": 0, "text": "test", "files": []}],
            "buffer": [],
            "started": time.time(),
            "process_done": done,
            "session_idle": idle,
            "claude_session_id": claude_session_id,
            "message_queue": [],
            "last_activity_ts": time.time(),
        }


def subscribe_client(ws, client, tab_id):
    """Subscribe a test client socket to a tab."""
    sid = get_sid(ws, client)
    with ws._chat_lock:
        ws.CHAT_SESSIONS[tab_id]["socket_sids"].add(sid)
        ws.SOCKET_TO_SESSIONS.setdefault(sid, set()).add(tab_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CHAT FLOW
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatFlow:
    """Test message routing, queuing, and block emission."""

    def test_connect_receives_state_sync(self, client1, state_file):
        """On connect, client receives chat_state_sync with current state."""
        state = last_state_sync(client1)
        assert state is not None
        assert "active_sessions" in state
        assert "streaming_sessions" in state
        assert "session_names" in state
        assert "drafts" in state

    def test_new_message_spawns_thread(self, ws, client1, state_file):
        """New message to unknown tab_id spawns _run_claude thread."""
        with patch.object(ws.ChatNamespace, "_run_claude") as mock_run:
            client1.emit("send_message", {
                "prompt": "Hello world",
                "tab_id": "new-tab-00000001",
                "model": "sonnet",
            }, namespace="/chat")
            time.sleep(0.1)

            # _run_claude should have been called (in a thread)
            assert mock_run.called
            args = mock_run.call_args[0]
            assert args[1] == "Hello world"  # prompt
            assert args[2] == "new-tab-00000001"  # tab_id

    def test_message_to_idle_session_wakes_it(self, ws, client1, state_file):
        """Message to idle persistent session wakes it via incoming_queue."""
        tab_id = "idle-tab-00000001"
        make_session(ws, tab_id, idle=True)
        subscribe_client(ws, client1, tab_id)

        # The idle session's incoming_queue should receive the message
        client1.emit("send_message", {
            "prompt": "Wake up",
            "tab_id": tab_id,
            "model": "sonnet",
        }, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            # Session should no longer be idle
            assert sess["session_idle"] is False

    def test_message_to_busy_session_queues(self, ws, client1, state_file):
        """Message to busy session goes to message_queue."""
        tab_id = "busy-tab-00000001"
        make_session(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        client1.emit("send_message", {
            "prompt": "Follow up",
            "tab_id": tab_id,
            "model": "sonnet",
        }, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_lock:
            queue = ws.CHAT_SESSIONS[tab_id]["message_queue"]
            assert len(queue) == 1
            assert queue[0]["prompt"] == "Follow up"

    def test_queued_message_emits_block_add(self, ws, client1, state_file):
        """Queuing a message emits pending user block to subscribers."""
        tab_id = "queue-block-tab-01"
        make_session(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        # Clear events from connect
        client1.get_received("/chat")

        client1.emit("send_message", {
            "prompt": "Queued msg",
            "tab_id": tab_id,
            "model": "sonnet",
        }, namespace="/chat")
        time.sleep(0.05)

        blocks = get_events(client1, "realtime_block_add")
        assert len(blocks) >= 1
        assert blocks[0]["args"][0]["block"]["type"] == "user"
        assert blocks[0]["args"][0]["block"]["pending"] is True

    def test_block_add_emits_to_all_subscribers(self, ws, client1, client2, state_file):
        """_block_add emits realtime_block_add to all subscribed sockets."""
        tab_id = "multi-sub-tab-001"
        make_session(ws, tab_id)
        subscribe_client(ws, client1, tab_id)
        subscribe_client(ws, client2, tab_id)

        client1.get_received("/chat")
        client2.get_received("/chat")

        ns = ws.ChatNamespace("/chat")
        ns._block_add(tab_id, {"type": "text", "text": "Hello"})

        b1 = get_events(client1, "realtime_block_add")
        b2 = get_events(client2, "realtime_block_add")
        assert len(b1) >= 1
        assert len(b2) >= 1
        assert b1[0]["args"][0]["block"]["text"] == "Hello"
        assert b2[0]["args"][0]["block"]["text"] == "Hello"

    def test_block_update_patches_existing(self, ws, client1, state_file):
        """_block_update patches an existing block and emits to subscribers."""
        tab_id = "update-block-tab-1"
        make_session(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        ns = ws.ChatNamespace("/chat")
        ns._block_add(tab_id, {"type": "text", "text": "partial"})

        client1.get_received("/chat")
        ns._block_update(tab_id, 1, {"text": "complete text"})

        updates = get_events(client1, "realtime_block_update")
        assert len(updates) >= 1
        assert updates[0]["args"][0]["patch"]["text"] == "complete text"

    def test_http_send_to_busy_session_queues(self, ws, http_client, state_file):
        """HTTP POST /api/chat/send queues to busy session."""
        tab_id = "http-busy-tab-001"
        make_session(ws, tab_id)

        resp = http_client.post("/api/chat/send", json={
            "prompt": "HTTP follow up",
            "tab_id": tab_id,
            "model": "sonnet",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["routed"] is True

        with ws._chat_lock:
            queue = ws.CHAT_SESSIONS[tab_id]["message_queue"]
            assert len(queue) == 1
            assert queue[0]["prompt"] == "HTTP follow up"

    def test_http_send_new_session_spawns_thread(self, ws, http_client, state_file):
        """HTTP POST /api/chat/send spawns thread for new session."""
        with patch.object(ws.ChatNamespace, "_run_claude") as mock_run:
            resp = http_client.post("/api/chat/send", json={
                "prompt": "Hello via HTTP",
                "tab_id": "http-new-tab-001",
                "model": "sonnet",
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["routed"] is False
            time.sleep(0.1)
            assert mock_run.called

    def test_empty_prompt_rejected(self, ws, client1, state_file):
        """Empty prompt returns error event."""
        client1.get_received("/chat")

        client1.emit("send_message", {
            "prompt": "",
            "tab_id": "empty-tab",
            "model": "sonnet",
        }, namespace="/chat")

        errors = get_events(client1, "error")
        assert len(errors) >= 1

    def test_missing_model_rejected(self, ws, client1, state_file):
        """Missing model returns error event."""
        client1.get_received("/chat")

        client1.emit("send_message", {
            "prompt": "Hello",
            "tab_id": "no-model-tab",
            "model": "",
        }, namespace="/chat")

        errors = get_events(client1, "error")
        assert len(errors) >= 1

    def test_queue_remove(self, ws, client1, state_file):
        """Removing from queue works correctly."""
        tab_id = "queue-rm-tab-0001"
        make_session(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        # Add two messages to queue
        with ws._chat_lock:
            ws.CHAT_SESSIONS[tab_id]["message_queue"] = [
                {"prompt": "first", "model": "sonnet", "effort": "high", "files": []},
                {"prompt": "second", "model": "sonnet", "effort": "high", "files": []},
            ]

        client1.emit("queue_remove", {"tab_id": tab_id, "index": 0}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_lock:
            queue = ws.CHAT_SESSIONS[tab_id]["message_queue"]
            assert len(queue) == 1
            assert queue[0]["prompt"] == "second"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SESSION LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionLifecycle:
    """Test rename, draft, mark read, recovery, and corruption handling."""

    def test_rename_session(self, ws, http_client, state_file):
        """Renaming updates session_names in state and on disk."""
        sid = "rename-session-001"

        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"].append({"tab_id": "t1", "session_id": sid})
            ws._save_chat_ui_state()

        resp = http_client.post("/api/chat/state/name", json={
            "session_id": sid,
            "name": "Custom Name",
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            assert ws._chat_ui_state["session_names"][sid] == "Custom Name"

        disk = json.loads(state_file.read_text())
        assert disk["session_names"][sid] == "Custom Name"

    def test_draft_save_persists(self, ws, client1, state_file):
        """Drafts persist to disk and survive reload."""
        session_id = "draft-session-001"

        client1.emit("draft_save", {
            "session_id": session_id,
            "text": "Work in progress",
        }, namespace="/chat")
        time.sleep(0.05)

        # In memory
        with ws._chat_ui_lock:
            assert ws._chat_ui_state["drafts"][session_id] == "Work in progress"

        # On disk
        disk = json.loads(state_file.read_text())
        assert disk["drafts"][session_id] == "Work in progress"

        # Survives reload
        ws._load_chat_ui_state()
        with ws._chat_ui_lock:
            assert ws._chat_ui_state["drafts"][session_id] == "Work in progress"

    def test_draft_clear_on_empty(self, ws, client1, state_file):
        """Empty draft text removes the key."""
        session_id = "draft-clear-001"

        with ws._chat_ui_lock:
            ws._chat_ui_state["drafts"][session_id] = "old draft"
            ws._save_chat_ui_state()

        client1.emit("draft_save", {
            "session_id": session_id,
            "text": "",
        }, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            assert session_id not in ws._chat_ui_state.get("drafts", {})

    def test_send_clears_draft(self, ws, client1, state_file):
        """Sending a message clears the draft for that tab."""
        tab_id = "draft-send-tab-01"

        with ws._chat_ui_lock:
            ws._chat_ui_state["drafts"][tab_id] = "my draft"
            ws._save_chat_ui_state()

        with patch.object(ws.ChatNamespace, "_run_claude"):
            client1.emit("send_message", {
                "prompt": "Final",
                "tab_id": tab_id,
                "model": "sonnet",
            }, namespace="/chat")
            time.sleep(0.1)

        with ws._chat_ui_lock:
            assert tab_id not in ws._chat_ui_state.get("drafts", {})

    def test_mark_read(self, ws, http_client, state_file):
        """POST /api/chat/state/read removes session from unread list."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["unread_sessions"] = ["sess-a", "sess-b"]
            ws._save_chat_ui_state()

        resp = http_client.post("/api/chat/state/read", json={"session_id": "sess-a"})
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            assert "sess-a" not in ws._chat_ui_state["unread_sessions"]
            assert "sess-b" in ws._chat_ui_state["unread_sessions"]

    def test_recover_dead_process(self, ws, stream_file, state_file):
        """Dead processes cleaned from streaming.json on recovery."""
        stream_file.write_text(json.dumps({
            "dead-tab": {
                "pid": 99999999,
                "stdout": "/tmp/nonexistent_stdout.log",
                "stderr": "/tmp/nonexistent_stderr.log",
                "started": time.time() - 100,
                "claude_session_id": "dead-session",
                "prompt": "old prompt",
            }
        }))

        ws._recover_chat_streams()

        assert "dead-tab" not in ws.CHAT_SESSIONS
        state = json.loads(stream_file.read_text())
        assert state == {}

    def test_corrupt_state_file_handled(self, ws, state_file):
        """Corrupt chat-ui.json doesn't crash."""
        state_file.write_text("not valid json {{{")
        ws._load_chat_ui_state()

        with ws._chat_ui_lock:
            assert isinstance(ws._chat_ui_state, dict)
            assert "active_sessions" in ws._chat_ui_state

    def test_state_save_atomic(self, ws, state_file):
        """_save_chat_ui_state writes atomically (no partial writes on disk)."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["session_names"]["test"] = "Atomic Test"
            ws._save_chat_ui_state()

        disk = json.loads(state_file.read_text())
        assert disk["session_names"]["test"] == "Atomic Test"
        assert "updated_at" in disk

    def test_stream_state_save_and_clear(self, ws, stream_file):
        """Stream state save/clear lifecycle works."""
        tab_id = "stream-tab-001"

        ws.ChatNamespace._save_stream_state(tab_id, {
            "pid": 12345,
            "stdout": "/tmp/test.log",
            "started": time.time(),
        })

        state = json.loads(stream_file.read_text())
        assert tab_id in state
        assert state[tab_id]["pid"] == 12345

        ws.ChatNamespace._clear_stream_state(tab_id)

        state = json.loads(stream_file.read_text())
        assert tab_id not in state


# ═══════════════════════════════════════════════════════════════════════════════
# 3. WEBSOCKET STATE SYNC
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketStateSync:
    """Test multi-client state consistency and broadcast correctness."""

    def test_both_clients_get_state_on_connect(self, client1, client2, state_file):
        """Both clients receive chat_state_sync on connect."""
        assert last_state_sync(client1) is not None
        assert last_state_sync(client2) is not None

    def test_rename_broadcasts_to_all(self, ws, client1, client2, http_client, state_file):
        """Renaming a session broadcasts to all connected clients."""
        sid = "sync-rename-sess"
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"].append({"tab_id": "t", "session_id": sid})
            ws._save_chat_ui_state()

        client1.get_received("/chat")
        client2.get_received("/chat")

        http_client.post("/api/chat/state/name", json={"session_id": sid, "name": "Renamed"})

        s1 = last_state_sync(client1)
        s2 = last_state_sync(client2)
        assert s1 is not None and s1["session_names"].get(sid) == "Renamed"
        assert s2 is not None and s2["session_names"].get(sid) == "Renamed"

    def test_mark_read_broadcasts(self, ws, client1, client2, http_client, state_file):
        """Mark read broadcasts updated unread list."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["unread_sessions"] = ["x", "y"]
            ws._save_chat_ui_state()

        client1.get_received("/chat")
        client2.get_received("/chat")

        http_client.post("/api/chat/state/read", json={"session_id": "x"})

        s1 = last_state_sync(client1)
        s2 = last_state_sync(client2)
        assert s1 is not None and "x" not in s1["unread_sessions"]
        assert s2 is not None and "x" not in s2["unread_sessions"]

    def test_draft_update_sent_to_other_client(self, ws, client1, client2, state_file):
        """Draft save emits draft_update to OTHER clients only."""
        client1.get_received("/chat")
        client2.get_received("/chat")

        client1.emit("draft_save", {
            "session_id": "draft-sync",
            "text": "typing...",
        }, namespace="/chat")
        time.sleep(0.05)

        # Client 2 receives draft_update
        d2 = get_events(client2, "draft_update")
        assert len(d2) >= 1
        assert d2[-1]["args"][0]["text"] == "typing..."

    def test_disconnect_cleans_subscriptions(self, ws, app_sio, state_file):
        """Disconnecting removes socket from all subscriptions."""
        app, sio = app_sio
        c = sio.test_client(app, namespace="/chat")
        sid = get_sid(ws, c)

        tab_id = "dc-tab-001"
        make_session(ws, tab_id)
        with ws._chat_lock:
            ws.CHAT_SESSIONS[tab_id]["socket_sids"].add(sid)
            ws.SOCKET_TO_SESSIONS[sid] = {tab_id}

        c.disconnect(namespace="/chat")

        with ws._chat_lock:
            assert sid not in ws.SOCKET_TO_SESSIONS
            assert sid not in ws.CHAT_SESSIONS[tab_id]["socket_sids"]

    def test_reconnect_gets_fresh_state(self, ws, app_sio, state_file):
        """New connection gets latest state, not stale."""
        app, sio = app_sio

        with ws._chat_ui_lock:
            ws._chat_ui_state["session_names"]["s1"] = "First"
            ws._save_chat_ui_state()

        c1 = sio.test_client(app, namespace="/chat")
        s = last_state_sync(c1)
        assert s["session_names"]["s1"] == "First"
        c1.disconnect(namespace="/chat")

        # Modify while disconnected
        with ws._chat_ui_lock:
            ws._chat_ui_state["session_names"]["s2"] = "Second"
            ws._save_chat_ui_state()

        c2 = sio.test_client(app, namespace="/chat")
        s = last_state_sync(c2)
        assert s["session_names"]["s1"] == "First"
        assert s["session_names"]["s2"] == "Second"
        c2.disconnect(namespace="/chat")

    def test_snapshot_matches_disk(self, ws, state_file):
        """In-memory snapshot matches persisted state."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [{"tab_id": "t1", "session_id": "s1"}]
            ws._chat_ui_state["session_names"] = {"s1": "Test"}
            ws._chat_ui_state["drafts"] = {"t1": "draft"}
            ws._save_chat_ui_state()

        snap = ws._get_chat_state_snapshot()
        disk = json.loads(state_file.read_text())

        assert snap["active_sessions"] == disk["active_sessions"]
        assert snap["session_names"] == disk["session_names"]
        assert snap["drafts"] == disk["drafts"]

    def test_streaming_sessions_includes_active(self, ws, state_file):
        """Active sessions appear in streaming_sessions snapshot."""
        tab_id = "streaming-tab-001"
        make_session(ws, tab_id, claude_session_id="claude-001")

        snap = ws._get_chat_state_snapshot()
        streaming_tabs = [s["tab_id"] for s in snap["streaming_sessions"]]
        assert tab_id in streaming_tabs

    def test_done_sessions_not_in_streaming(self, ws, state_file):
        """Completed sessions don't appear in streaming_sessions."""
        tab_id = "done-tab-001"
        make_session(ws, tab_id, done=True)

        snap = ws._get_chat_state_snapshot()
        streaming_tabs = [s["tab_id"] for s in snap["streaming_sessions"]]
        assert tab_id not in streaming_tabs

    def test_idle_sessions_not_in_streaming(self, ws, state_file):
        """Idle persistent sessions don't appear in streaming_sessions."""
        tab_id = "idle-tab-001"
        make_session(ws, tab_id, idle=True)

        snap = ws._get_chat_state_snapshot()
        streaming_tabs = [s["tab_id"] for s in snap["streaming_sessions"]]
        assert tab_id not in streaming_tabs


# ═══════════════════════════════════════════════════════════════════════════════
# 4. THREAD SAFETY
# ═══════════════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    """Test concurrent operations don't corrupt state."""

    def test_concurrent_draft_saves(self, ws, state_file):
        """Multiple threads saving drafts don't corrupt state."""
        errors = []

        def save_draft(i):
            try:
                with ws._chat_ui_lock:
                    ws._chat_ui_state.setdefault("drafts", {})[f"s-{i}"] = f"d-{i}"
                    ws._save_chat_ui_state()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_draft, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        with ws._chat_ui_lock:
            for i in range(20):
                assert f"s-{i}" in ws._chat_ui_state["drafts"]

    def test_concurrent_block_add(self, ws, state_file):
        """Multiple threads adding blocks don't corrupt or lose IDs."""
        tab_id = "concurrent-blocks"
        make_session(ws, tab_id)
        errors = []

        ns = ws.ChatNamespace("/chat")

        def add_block(i):
            try:
                ns._block_add(tab_id, {"type": "text", "text": f"b-{i}"})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_block, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        with ws._chat_lock:
            blocks = ws.CHAT_SESSIONS[tab_id]["blocks"]
            assert len(blocks) == 21  # 1 original + 20 added
            ids = [b["id"] for b in blocks]
            assert len(ids) == len(set(ids))  # all unique

    def test_concurrent_send_to_same_tab_queues(self, ws, state_file):
        """Two rapid sends to the same busy session both queue correctly."""
        tab_id = "rapid-tab-001"
        make_session(ws, tab_id)

        errors = []

        def send_http(prompt):
            try:
                with ws.app.test_client() as c:
                    resp = c.post("/api/chat/send", json={
                        "prompt": prompt,
                        "tab_id": tab_id,
                        "model": "sonnet",
                    })
                    assert resp.status_code == 200
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=send_http, args=("first",))
        t2 = threading.Thread(target=send_http, args=("second",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors
        with ws._chat_lock:
            queue = ws.CHAT_SESSIONS[tab_id]["message_queue"]
            assert len(queue) == 2
            prompts = {m["prompt"] for m in queue}
            assert "first" in prompts
            assert "second" in prompts

    def test_concurrent_state_save_no_corruption(self, ws, state_file):
        """Concurrent saves produce valid JSON on disk."""
        errors = []

        def save_state(i):
            try:
                with ws._chat_ui_lock:
                    ws._chat_ui_state["session_names"][f"s-{i}"] = f"n-{i}"
                    ws._save_chat_ui_state()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_state, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        # File should be valid JSON
        disk = json.loads(state_file.read_text())
        assert isinstance(disk, dict)
        assert "session_names" in disk


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CANCEL & REMOVE
# ═══════════════════════════════════════════════════════════════════════════════

class TestCancelAndRemove:
    """Test cancellation and active session removal."""

    def test_ws_cancel_marks_done(self, ws, client1, state_file):
        """WebSocket cancel event triggers cancellation flow."""
        tab_id = "cancel-ws-tab-01"
        make_session(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        client1.get_received("/chat")

        client1.emit("cancel", {"tab_id": tab_id}, namespace="/chat")
        time.sleep(0.05)

        cancelled = get_events(client1, "cancelled")
        assert len(cancelled) >= 1

    def test_http_cancel_by_session_id(self, ws, http_client, state_file):
        """POST /api/chat/state/cancel finds session by claude_session_id."""
        tab_id = "cancel-http-tab"
        make_session(ws, tab_id, claude_session_id="claude-cancel-001")

        resp = http_client.post("/api/chat/state/cancel", json={
            "session_id": "claude-cancel-001",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_http_cancel_nonexistent(self, ws, http_client, state_file):
        """Cancelling nonexistent session returns ok but not cancelled."""
        resp = http_client.post("/api/chat/state/cancel", json={
            "session_id": "nonexistent-session",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["cancelled"] is False

    def test_remove_active_by_tab_id(self, ws, client1, state_file):
        """on_remove_active removes session from active list by tab_id."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": "keep-tab", "session_id": "keep-sess"},
                {"tab_id": "remove-tab", "session_id": "remove-sess"},
            ]
            ws._save_chat_ui_state()

        client1.emit("remove_active", {"tab_id": "remove-tab"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            tabs = [e["tab_id"] for e in ws._chat_ui_state["active_sessions"]]
            assert "remove-tab" not in tabs
            assert "keep-tab" in tabs

        # Persisted to disk
        disk = json.loads(state_file.read_text())
        assert len(disk["active_sessions"]) == 1

    def test_remove_active_by_session_id(self, ws, client1, state_file):
        """on_remove_active removes session by session_id."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s-remove"},
                {"tab_id": "t2", "session_id": "s-keep"},
            ]
            ws._save_chat_ui_state()

        client1.emit("remove_active", {"session_id": "s-remove"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            sids = [e["session_id"] for e in ws._chat_ui_state["active_sessions"]]
            assert "s-remove" not in sids
            assert "s-keep" in sids

    def test_add_active_prevents_duplicates(self, ws, client1, state_file):
        """on_add_active doesn't create duplicates."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": None, "session_id": "existing-sess"},
            ]
            ws._save_chat_ui_state()

        client1.emit("add_active", {"session_id": "existing-sess"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            assert len(ws._chat_ui_state["active_sessions"]) == 1

    def test_add_active_inserts_at_front(self, ws, client1, state_file):
        """on_add_active inserts new session at front of list."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": None, "session_id": "old-sess"},
            ]
            ws._save_chat_ui_state()

        client1.emit("add_active", {"session_id": "new-sess"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            assert ws._chat_ui_state["active_sessions"][0]["session_id"] == "new-sess"
            assert len(ws._chat_ui_state["active_sessions"]) == 2

    def test_http_remove_active(self, ws, http_client, state_file):
        """POST /api/chat/state/active action=remove works."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s1"},
                {"tab_id": "t2", "session_id": "s2"},
            ]
            ws._save_chat_ui_state()

        resp = http_client.post("/api/chat/state/active", json={
            "session_id": "s1",
            "action": "remove",
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            sids = [e["session_id"] for e in ws._chat_ui_state["active_sessions"]]
            assert "s1" not in sids
            assert "s2" in sids

    def test_http_add_active(self, ws, http_client, state_file):
        """POST /api/chat/state/active action=add works."""
        resp = http_client.post("/api/chat/state/active", json={
            "session_id": "new-s",
            "action": "add",
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            sids = [e["session_id"] for e in ws._chat_ui_state["active_sessions"]]
            assert "new-s" in sids


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MIGRATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestMigration:
    """Test state migration and format conversion."""

    def test_migrate_from_localstorage(self, ws, http_client, state_file):
        """POST /api/chat/state/migrate imports v1 string sessions."""
        resp = http_client.post("/api/chat/state/migrate", json={
            "active_sessions": ["sess-a", "sess-b"],
            "session_names": {"sess-a": "Session A"},
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["migrated"] is True

        with ws._chat_ui_lock:
            sids = [e["session_id"] for e in ws._chat_ui_state["active_sessions"]]
            assert "sess-a" in sids
            assert "sess-b" in sids
            assert ws._chat_ui_state["session_names"]["sess-a"] == "Session A"

    def test_migrate_skips_existing(self, ws, http_client, state_file):
        """Migration doesn't create duplicates for already-existing sessions."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": None, "session_id": "existing"},
            ]
            ws._save_chat_ui_state()

        resp = http_client.post("/api/chat/state/migrate", json={
            "active_sessions": ["existing", "new-one"],
            "session_names": {},
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            count = sum(1 for e in ws._chat_ui_state["active_sessions"]
                       if e.get("session_id") == "existing")
            assert count == 1  # not duplicated

    def test_migrate_caps_at_20(self, ws, http_client, state_file):
        """Migration doesn't exceed 20 active sessions."""
        resp = http_client.post("/api/chat/state/migrate", json={
            "active_sessions": [f"s-{i}" for i in range(30)],
            "session_names": {},
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            assert len(ws._chat_ui_state["active_sessions"]) <= 20

    def test_v1_to_v2_migration_on_load(self, ws, state_file):
        """Loading v1 format (string array) auto-converts to v2 (object array)."""
        state_file.write_text(json.dumps({
            "active_sessions": ["sess-1", "sess-2", "_pending_skip"],
            "session_names": {},
            "unread_sessions": [],
            "drafts": {},
        }))

        ws._load_chat_ui_state()

        with ws._chat_ui_lock:
            active = ws._chat_ui_state["active_sessions"]
            # Should be objects, not strings
            for entry in active:
                assert isinstance(entry, dict)
            # _pending_ entries should be filtered
            sids = [e["session_id"] for e in active]
            assert "_pending_skip" not in sids
