"""Integration tests for deeper chat flows: Q&A, cancel, resume, upload, active management.

Covers gaps not in test_integration.py - focused on interactive flows that
involve question resolution, session cancellation, buffer replay, and HTTP state endpoints.

Uses same patterns: mocked SDK, Flask-SocketIO test client, direct CHAT_SESSIONS manipulation.
"""

import os
import sys
import json
import time
import asyncio
import threading
import io
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

    mod.CHAT_SESSIONS.clear()
    mod.SOCKET_TO_SESSIONS.clear()
    mod.SESSION_WATCHERS.clear()

    yield mod

    mod.CHAT_SESSIONS.clear()
    mod.SOCKET_TO_SESSIONS.clear()
    mod.SESSION_WATCHERS.clear()


@pytest.fixture
def ws(_reset_global_state):
    return _reset_global_state


@pytest.fixture
def app_sio(ws):
    ws.app.config["TESTING"] = True
    return ws.app, ws.socketio


@pytest.fixture
def client1(app_sio):
    app, sio = app_sio
    return sio.test_client(app, namespace="/chat")


@pytest.fixture
def client2(app_sio):
    app, sio = app_sio
    return sio.test_client(app, namespace="/chat")


@pytest.fixture
def http_client(app_sio):
    app, _ = app_sio
    return app.test_client()


@pytest.fixture
def state_file(tmp_path, ws):
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
    f = tmp_path / "streaming.json"
    f.write_text("{}")
    ws.CHAT_STREAM_STATE = f
    ws.CHAT_STREAM_DIR = tmp_path
    return f


# --- Helpers ---

def get_sid(ws, client):
    return ws.socketio.server.manager.sid_from_eio_sid(client.eio_sid, "/chat")


def get_events(client, name):
    return [r for r in client.get_received("/chat") if r["name"] == name]


def last_state_sync(client):
    events = get_events(client, "chat_state_sync")
    return events[-1]["args"][0] if events else None


def make_session(ws, tab_id, claude_session_id=None, done=False, idle=False):
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
    sid = get_sid(ws, client)
    with ws._chat_lock:
        ws.CHAT_SESSIONS[tab_id]["socket_sids"].add(sid)
        ws.SOCKET_TO_SESSIONS.setdefault(sid, set()).add(tab_id)


def make_session_with_future(ws, tab_id, question_input=None):
    """Create session with active _question_future on a real background asyncio loop."""
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    future = loop.create_future()

    make_session(ws, tab_id)
    with ws._chat_lock:
        sess = ws.CHAT_SESSIONS[tab_id]
        sess["sdk_loop"] = loop
        sess["sdk_client"] = MagicMock()
        sess["_question_future"] = future
        sess["_question_input"] = question_input or {
            "questions": [{"question": "Pick one", "options": ["A", "B"]}]
        }
    return future, loop


def populate_buffer(ws, tab_id, n_events):
    """Fill session buffer with n synthetic events."""
    with ws._chat_lock:
        sess = ws.CHAT_SESSIONS[tab_id]
        sess["buffer"] = [
            {"event": "realtime_block_add", "data": {"block": {"type": "text", "id": i, "text": f"msg-{i}"}, "tab_id": tab_id}}
            for i in range(n_events)
        ]


# =========================================================================
# 1. QUESTION/ANSWER FLOW
# =========================================================================

class TestQuestionAnswerFlow:
    """Test AskUserQuestion via can_use_tool -> question block -> question_response."""

    def test_question_response_resolves_future(self, ws, client1, state_file):
        """Single answer resolves _question_future with PermissionResultAllow."""
        tab_id = "qa-resolve-001"
        future, loop = make_session_with_future(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        client1.emit("question_response", {
            "answer": "Option A",
            "tab_id": tab_id,
        }, namespace="/chat")
        time.sleep(0.1)

        assert future.done()
        result = future.result()
        assert result.updated_input["answers"]["Pick one"] == "Option A"

        loop.call_soon_threadsafe(loop.stop)

    def test_question_response_structured_answers(self, ws, client1, state_file):
        """Multi-question answers dict resolves with full structure."""
        tab_id = "qa-struct-001"
        q_input = {"questions": [{"question": "Q1"}, {"question": "Q2"}]}
        future, loop = make_session_with_future(ws, tab_id, question_input=q_input)
        subscribe_client(ws, client1, tab_id)

        client1.emit("question_response", {
            "answers": {"Q1": "A1", "Q2": "A2"},
            "questions": [{"question": "Q1"}, {"question": "Q2"}],
            "tab_id": tab_id,
        }, namespace="/chat")
        time.sleep(0.1)

        assert future.done()
        result = future.result()
        assert result.updated_input["answers"] == {"Q1": "A1", "Q2": "A2"}
        assert len(result.updated_input["questions"]) == 2

        loop.call_soon_threadsafe(loop.stop)

    def test_question_response_no_session_safe(self, ws, client1, state_file):
        """No crash when session doesn't exist."""
        client1.emit("question_response", {
            "answer": "orphan",
            "tab_id": "nonexistent-tab",
        }, namespace="/chat")
        # Should not raise

    def test_question_response_empty_answer_ignored(self, ws, client1, state_file):
        """Empty answer doesn't resolve future."""
        tab_id = "qa-empty-001"
        future, loop = make_session_with_future(ws, tab_id)
        subscribe_client(ws, client1, tab_id)

        client1.emit("question_response", {
            "answer": "",
            "tab_id": tab_id,
        }, namespace="/chat")
        time.sleep(0.1)

        assert not future.done()

        loop.call_soon_threadsafe(loop.stop)

    def test_question_response_fallback_to_query(self, ws, client1, state_file):
        """When no future but sdk_client exists, falls back to client.query()."""
        tab_id = "qa-fallback-001"
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

        make_session(ws, tab_id)
        mock_client = MagicMock()
        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            sess["sdk_client"] = mock_client
            sess["sdk_loop"] = loop
            # No _question_future set
        subscribe_client(ws, client1, tab_id)

        with patch("asyncio.run_coroutine_threadsafe") as mock_rcts:
            client1.emit("question_response", {
                "answer": "fallback text",
                "tab_id": tab_id,
            }, namespace="/chat")
            time.sleep(0.1)

            mock_rcts.assert_called_once()
            args = mock_rcts.call_args[0]
            assert args[1] is loop  # second arg is the loop

        loop.call_soon_threadsafe(loop.stop)


# =========================================================================
# 2. CANCEL FLOW
# =========================================================================

class TestCancelFlow:
    """Test cancel via WebSocket and HTTP."""

    def test_cancel_tab_disconnects_sdk(self, ws, client1, state_file):
        """on_cancel with tab_id schedules SDK disconnect."""
        tab_id = "cancel-sdk-001"
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

        make_session(ws, tab_id)
        with ws._chat_lock:
            ws.CHAT_SESSIONS[tab_id]["sdk_loop"] = loop
        subscribe_client(ws, client1, tab_id)

        with patch("asyncio.run_coroutine_threadsafe") as mock_rcts:
            client1.emit("cancel", {"tab_id": tab_id}, namespace="/chat")
            time.sleep(0.05)
            mock_rcts.assert_called_once()

        cancelled = get_events(client1, "cancelled")
        assert len(cancelled) >= 1

        loop.call_soon_threadsafe(loop.stop)

    def test_cancel_without_tab_cancels_all_subscribed(self, ws, client1, state_file):
        """on_cancel with no tab_id cancels all subscribed sessions."""
        loop = asyncio.new_event_loop()
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

        make_session(ws, "tab-a")
        make_session(ws, "tab-b")
        with ws._chat_lock:
            ws.CHAT_SESSIONS["tab-a"]["sdk_loop"] = loop
            ws.CHAT_SESSIONS["tab-b"]["sdk_loop"] = loop
        subscribe_client(ws, client1, "tab-a")
        subscribe_client(ws, client1, "tab-b")

        with patch("asyncio.run_coroutine_threadsafe") as mock_rcts:
            client1.emit("cancel", {}, namespace="/chat")
            time.sleep(0.05)
            assert mock_rcts.call_count == 2

        loop.call_soon_threadsafe(loop.stop)

    def test_cancel_process_based_session(self, ws, client1, state_file):
        """Cancel terminates subprocess when no SDK client."""
        tab_id = "cancel-proc-001"
        make_session(ws, tab_id)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            sess["sdk_client"] = None
            sess["sdk_loop"] = None
            sess["process"] = mock_proc
        subscribe_client(ws, client1, tab_id)

        client1.emit("cancel", {"tab_id": tab_id}, namespace="/chat")
        time.sleep(0.05)

        mock_proc.terminate.assert_called_once()

    def test_http_cancel_by_session_id(self, ws, http_client, state_file):
        """POST /state/cancel finds session by claude_session_id."""
        tab_id = "http-cancel-001"
        make_session(ws, tab_id, claude_session_id="claude-xyz")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        with ws._chat_lock:
            ws.CHAT_SESSIONS[tab_id]["process"] = mock_proc

        resp = http_client.post("/api/chat/state/cancel", json={"session_id": "claude-xyz"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["cancelled"] is True
        mock_proc.terminate.assert_called_once()

    def test_http_cancel_by_tab_id(self, ws, http_client, state_file):
        """POST /state/cancel fallback to tab_id."""
        tab_id = "http-cancel-tab-01"
        make_session(ws, tab_id)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        with ws._chat_lock:
            ws.CHAT_SESSIONS[tab_id]["process"] = mock_proc

        resp = http_client.post("/api/chat/state/cancel", json={"session_id": tab_id})
        assert resp.status_code == 200
        assert resp.get_json()["cancelled"] is True

    def test_http_cancel_missing_id(self, ws, http_client, state_file):
        """POST /state/cancel without session_id returns 400."""
        resp = http_client.post("/api/chat/state/cancel", json={})
        assert resp.status_code == 400


# =========================================================================
# 3. RESUME STREAM / BUFFER REPLAY
# =========================================================================

class TestResumeStreamBufferReplay:
    """Test resume_stream replaying buffered events to reconnecting clients."""

    def test_resume_replays_all_buffered(self, ws, app_sio, state_file):
        """All buffered events replayed in order."""
        app, sio = app_sio
        tab_id = "resume-all-001"
        make_session(ws, tab_id)
        populate_buffer(ws, tab_id, 3)

        c = sio.test_client(app, namespace="/chat")
        c.get_received("/chat")  # clear connect events

        c.emit("resume_stream", {"tab_id": tab_id, "buffer_offset": 0}, namespace="/chat")
        time.sleep(0.05)

        blocks = get_events(c, "realtime_block_add")
        assert len(blocks) == 3
        texts = [b["args"][0]["block"]["text"] for b in blocks]
        assert texts == ["msg-0", "msg-1", "msg-2"]

        c.disconnect(namespace="/chat")

    def test_resume_with_offset_skips_seen(self, ws, app_sio, state_file):
        """buffer_offset=2 skips first 2 events."""
        app, sio = app_sio
        tab_id = "resume-offset-001"
        make_session(ws, tab_id)
        populate_buffer(ws, tab_id, 5)

        c = sio.test_client(app, namespace="/chat")
        c.get_received("/chat")

        c.emit("resume_stream", {"tab_id": tab_id, "buffer_offset": 2}, namespace="/chat")
        time.sleep(0.05)

        blocks = get_events(c, "realtime_block_add")
        assert len(blocks) == 3
        texts = [b["args"][0]["block"]["text"] for b in blocks]
        assert texts == ["msg-2", "msg-3", "msg-4"]

        c.disconnect(namespace="/chat")

    def test_resume_subscribes_socket(self, ws, app_sio, state_file):
        """resume_stream adds socket to session's socket_sids."""
        app, sio = app_sio
        tab_id = "resume-sub-001"
        make_session(ws, tab_id)

        c = sio.test_client(app, namespace="/chat")
        sid = get_sid(ws, c)

        c.emit("resume_stream", {"tab_id": tab_id, "buffer_offset": 0}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_lock:
            assert sid in ws.CHAT_SESSIONS[tab_id]["socket_sids"]
            assert tab_id in ws.SOCKET_TO_SESSIONS.get(sid, set())

        c.disconnect(namespace="/chat")

    def test_resume_nonexistent_tab_error(self, ws, client1, state_file):
        """Error event for unknown tab_id."""
        client1.get_received("/chat")

        client1.emit("resume_stream", {"tab_id": "nonexistent"}, namespace="/chat")
        time.sleep(0.05)

        errors = get_events(client1, "error")
        assert len(errors) >= 1

    def test_buffer_caps_at_500(self, ws, state_file):
        """_emit_buffered trims buffer to 500 entries."""
        tab_id = "buffer-cap-001"
        make_session(ws, tab_id)

        ns = ws.ChatNamespace("/chat")
        for i in range(510):
            ns._emit_buffered(tab_id, "realtime_block_add", {"block": {"id": i}})

        with ws._chat_lock:
            buf = ws.CHAT_SESSIONS[tab_id]["buffer"]
            assert len(buf) == 500
            # Oldest events trimmed, newest kept
            assert buf[0]["data"]["block"]["id"] == 10
            assert buf[-1]["data"]["block"]["id"] == 509


# =========================================================================
# 4. ACTIVE SESSION MANAGEMENT
# =========================================================================

class TestActiveSessionManagement:
    """Test add_active / remove_active WebSocket events."""

    def test_add_active_inserts(self, ws, client1, state_file):
        """add_active inserts session at position 0."""
        client1.emit("add_active", {"session_id": "new-sess"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            entries = ws._chat_ui_state["active_sessions"]
            assert len(entries) == 1
            assert entries[0]["session_id"] == "new-sess"
            assert entries[0]["tab_id"] is None

    def test_add_active_deduplicates(self, ws, client1, state_file):
        """No duplicate entries."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [{"tab_id": None, "session_id": "dup-sess"}]
            ws._save_chat_ui_state()

        client1.emit("add_active", {"session_id": "dup-sess"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            assert len(ws._chat_ui_state["active_sessions"]) == 1

    def test_add_active_caps_at_20(self, ws, client1, state_file):
        """Max 20 sessions."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": None, "session_id": f"s-{i}"} for i in range(20)
            ]
            ws._save_chat_ui_state()

        client1.emit("add_active", {"session_id": "overflow"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            entries = ws._chat_ui_state["active_sessions"]
            assert len(entries) == 20
            assert entries[0]["session_id"] == "overflow"
            # Last entry dropped
            assert entries[-1]["session_id"] == "s-18"

    def test_new_session_added_to_active(self, ws, client1, state_file):
        """New session (not routed) gets added to active_sessions.

        Simulates the auto-add logic from _run_claude_sdk that runs after
        CHAT_SESSIONS is populated for a brand new session.
        """
        tab_id = "new-tab-001"
        resume_session_id = None

        # Simulate what _run_claude_sdk does after creating session
        with ws._chat_ui_lock:
            already = any(e.get("tab_id") == tab_id for e in ws._chat_ui_state["active_sessions"])
            if not already:
                ws._chat_ui_state["active_sessions"].insert(0, {"tab_id": tab_id, "session_id": resume_session_id})
            ws._save_chat_ui_state()

        with ws._chat_ui_lock:
            entries = ws._chat_ui_state["active_sessions"]
            assert len(entries) == 1
            assert entries[0]["tab_id"] == tab_id

    def test_new_session_deduplicates_by_resume_id(self, ws, client1, state_file):
        """If resume_session_id already in active, update its tab_id."""
        tab_id = "new-tab-002"
        resume_session_id = "existing-claude-uuid"

        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": None, "session_id": "existing-claude-uuid"},
            ]
            ws._save_chat_ui_state()

        # Simulate _run_claude_sdk auto-add logic
        with ws._chat_ui_lock:
            already = any(e.get("tab_id") == tab_id for e in ws._chat_ui_state["active_sessions"])
            if not already and resume_session_id:
                for entry in ws._chat_ui_state["active_sessions"]:
                    if entry.get("session_id") == resume_session_id:
                        entry["tab_id"] = tab_id
                        already = True
                        break
            if not already:
                ws._chat_ui_state["active_sessions"].insert(0, {"tab_id": tab_id, "session_id": resume_session_id})
            ws._save_chat_ui_state()

        with ws._chat_ui_lock:
            entries = ws._chat_ui_state["active_sessions"]
            assert len(entries) == 1
            assert entries[0]["tab_id"] == tab_id
            assert entries[0]["session_id"] == resume_session_id

    def test_remove_active_by_tab_id(self, ws, client1, state_file):
        """Removes by tab_id."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s1"},
                {"tab_id": "t2", "session_id": "s2"},
            ]
            ws._save_chat_ui_state()

        client1.emit("remove_active", {"tab_id": "t1"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            entries = ws._chat_ui_state["active_sessions"]
            assert len(entries) == 1
            assert entries[0]["tab_id"] == "t2"

    def test_remove_active_by_session_id(self, ws, client1, state_file):
        """Removes by session_id."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [
                {"tab_id": "t1", "session_id": "s1"},
            ]
            ws._save_chat_ui_state()

        client1.emit("remove_active", {"session_id": "s1"}, namespace="/chat")
        time.sleep(0.05)

        with ws._chat_ui_lock:
            assert len(ws._chat_ui_state["active_sessions"]) == 0

    def test_remove_active_broadcasts(self, ws, client1, client2, state_file):
        """Both clients get state_sync after removal."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [{"tab_id": "t1", "session_id": "s1"}]
            ws._save_chat_ui_state()

        client1.get_received("/chat")
        client2.get_received("/chat")

        client1.emit("remove_active", {"tab_id": "t1"}, namespace="/chat")
        time.sleep(0.05)

        s1 = last_state_sync(client1)
        s2 = last_state_sync(client2)
        assert s1 is not None
        assert s2 is not None
        assert len(s1["active_sessions"]) == 0
        assert len(s2["active_sessions"]) == 0


# =========================================================================
# 5. FILE UPLOAD
# =========================================================================

class TestFileUpload:
    """Test POST /api/chat/upload."""

    def test_upload_single_file(self, ws, http_client, tmp_path):
        """Returns path, name, size, type."""
        ws.CHAT_UPLOAD_DIR = tmp_path
        data = {"file": (io.BytesIO(b"hello world"), "test.txt")}
        resp = http_client.post(
            "/api/chat/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        files = resp.get_json()["files"]
        assert len(files) == 1
        assert files[0]["name"] == "test.txt"
        assert files[0]["size"] == 11
        assert "path" in files[0]

    def test_upload_multiple_files(self, ws, http_client, tmp_path):
        """Multiple files returned."""
        ws.CHAT_UPLOAD_DIR = tmp_path
        data = {
            "file": [
                (io.BytesIO(b"aaa"), "a.txt"),
                (io.BytesIO(b"bbb"), "b.txt"),
            ]
        }
        resp = http_client.post(
            "/api/chat/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        files = resp.get_json()["files"]
        assert len(files) == 2

    def test_upload_no_file_400(self, ws, http_client):
        """400 on empty request."""
        resp = http_client.post("/api/chat/upload")
        assert resp.status_code == 400

    def test_upload_sanitizes_filename(self, ws, http_client, tmp_path):
        """Path traversal in filename is stripped."""
        ws.CHAT_UPLOAD_DIR = tmp_path
        data = {"file": (io.BytesIO(b"data"), "../../evil.txt")}
        resp = http_client.post(
            "/api/chat/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        files = resp.get_json()["files"]
        assert len(files) == 1
        # Path should be within tmp_path
        assert str(tmp_path) in files[0]["path"]
        assert ".." not in files[0]["path"]


# =========================================================================
# 6. HTTP STATE ENDPOINTS
# =========================================================================

class TestHTTPStateEndpoints:
    """Test GET /api/chat/state, POST /api/chat/state/active."""

    def test_get_state_snapshot(self, ws, http_client, state_file):
        """GET /api/chat/state returns current state."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["session_names"]["s1"] = "Test"
            ws._save_chat_ui_state()

        resp = http_client.get("/api/chat/state")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["session_names"]["s1"] == "Test"
        assert "active_sessions" in data

    def test_post_active_add(self, ws, http_client, state_file):
        """POST /api/chat/state/active action=add inserts session."""
        resp = http_client.post("/api/chat/state/active", json={
            "session_id": "new-api-sess",
            "action": "add",
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            sids = [e["session_id"] for e in ws._chat_ui_state["active_sessions"]]
            assert "new-api-sess" in sids

    def test_post_active_remove(self, ws, http_client, state_file):
        """POST /api/chat/state/active action=remove removes session."""
        with ws._chat_ui_lock:
            ws._chat_ui_state["active_sessions"] = [{"tab_id": None, "session_id": "rm-sess"}]
            ws._save_chat_ui_state()

        resp = http_client.post("/api/chat/state/active", json={
            "session_id": "rm-sess",
            "action": "remove",
        })
        assert resp.status_code == 200

        with ws._chat_ui_lock:
            assert len(ws._chat_ui_state["active_sessions"]) == 0

    def test_post_active_invalid_action(self, ws, http_client, state_file):
        """400 on bad action."""
        resp = http_client.post("/api/chat/state/active", json={
            "session_id": "x",
            "action": "invalid",
        })
        assert resp.status_code == 400


# =========================================================================
# 7. PLAN MODE BLOCKS
# =========================================================================

class TestPlanModeBlocks:
    """Test plan block creation from EnterPlanMode/ExitPlanMode."""

    def test_enter_plan_active_block(self, ws, state_file):
        """Block with type=plan, active=True."""
        tab_id = "plan-enter-001"
        make_session(ws, tab_id)

        ns = ws.ChatNamespace("/chat")
        ns._block_add(tab_id, {"type": "plan", "active": True})

        with ws._chat_lock:
            blocks = ws.CHAT_SESSIONS[tab_id]["blocks"]
            plan_block = blocks[-1]
            assert plan_block["type"] == "plan"
            assert plan_block["active"] is True

    def test_exit_plan_inactive_block(self, ws, state_file):
        """Block with active=False."""
        tab_id = "plan-exit-001"
        make_session(ws, tab_id)

        ns = ws.ChatNamespace("/chat")
        ns._block_add(tab_id, {"type": "plan", "active": False})

        with ws._chat_lock:
            blocks = ws.CHAT_SESSIONS[tab_id]["blocks"]
            assert blocks[-1]["active"] is False

    def test_plan_content_via_update(self, ws, state_file):
        """_block_update adds content to plan block."""
        tab_id = "plan-content-001"
        make_session(ws, tab_id)

        ns = ws.ChatNamespace("/chat")
        ns._block_add(tab_id, {"type": "plan", "active": False})

        with ws._chat_lock:
            block_id = ws.CHAT_SESSIONS[tab_id]["blocks"][-1]["id"]

        ns._block_update(tab_id, block_id, {"content": "## My Plan\n1. Step one"})

        with ws._chat_lock:
            block = ws.CHAT_SESSIONS[tab_id]["blocks"][block_id]
            assert block["content"] == "## My Plan\n1. Step one"
            assert block["type"] == "plan"


class TestQueuedBlockReorder:
    """When processing queued messages, pending user blocks are temporarily
    removed so response blocks appear in the correct order."""

    def _simulate_queue_confirm(self, ws, tab_id):
        """Simulate the confirm + defer logic from _run_claude_sdk.

        Returns deferred_pending list (blocks removed from array).
        """
        deferred_pending = []
        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            blocks = sess.get("blocks", [])
            first_pending_idx = None
            for idx, blk in enumerate(blocks):
                if blk.get("type") == "user" and blk.get("pending"):
                    first_pending_idx = idx
                    break
            if first_pending_idx is not None:
                blocks[first_pending_idx]["pending"] = False
                new_blocks = []
                for blk in blocks:
                    if blk.get("type") == "user" and blk.get("pending"):
                        deferred_pending.append(blk)
                    else:
                        new_blocks.append(blk)
                for i, b in enumerate(new_blocks):
                    b["id"] = i
                sess["blocks"] = new_blocks
        return deferred_pending

    def _restore_deferred(self, ws, tab_id, deferred_pending):
        """Simulate restore of deferred pending blocks after turn completes."""
        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            for blk in deferred_pending:
                blk["id"] = len(sess["blocks"])
                sess["blocks"].append(blk)

    def test_single_pending_confirmed_no_defer(self, ws, state_file):
        """Single pending block gets confirmed, nothing deferred."""
        tab_id = "reorder-single-001"
        make_session(ws, tab_id)

        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            sess["blocks"] = [
                {"type": "user", "id": 0, "text": "msg1"},
                {"type": "cost", "id": 1},
                {"type": "user", "id": 2, "text": "msg2", "pending": True},
            ]

        deferred = self._simulate_queue_confirm(ws, tab_id)
        assert deferred == []

        with ws._chat_lock:
            blocks = ws.CHAT_SESSIONS[tab_id]["blocks"]
            assert len(blocks) == 3
            assert blocks[2]["text"] == "msg2"
            assert blocks[2].get("pending") is False

    def test_multiple_pending_defers_remaining(self, ws, state_file):
        """Multiple pending blocks: first confirmed, rest deferred (removed)."""
        tab_id = "reorder-multi-001"
        make_session(ws, tab_id)

        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            sess["blocks"] = [
                {"type": "user", "id": 0, "text": "msg1"},
                {"type": "cost", "id": 1},
                {"type": "user", "id": 2, "text": "msg2", "pending": True},
                {"type": "user", "id": 3, "text": "msg3", "pending": True},
                {"type": "user", "id": 4, "text": "msg4", "pending": True},
            ]

        deferred = self._simulate_queue_confirm(ws, tab_id)
        assert len(deferred) == 2
        assert deferred[0]["text"] == "msg3"
        assert deferred[1]["text"] == "msg4"

        with ws._chat_lock:
            blocks = ws.CHAT_SESSIONS[tab_id]["blocks"]
            # Only msg1, cost, msg2(confirmed) remain
            assert len(blocks) == 3
            assert blocks[2]["text"] == "msg2"
            assert blocks[2].get("pending") is False
            # IDs re-indexed
            assert [b["id"] for b in blocks] == [0, 1, 2]

    def test_response_blocks_before_deferred(self, ws, state_file):
        """After defer + loading + response, restore puts pending at end."""
        tab_id = "reorder-response-001"
        make_session(ws, tab_id)
        ns = ws.ChatNamespace("/chat")

        with ws._chat_lock:
            sess = ws.CHAT_SESSIONS[tab_id]
            sess["blocks"] = [
                {"type": "user", "id": 0, "text": "msg1"},
                {"type": "cost", "id": 1},
                {"type": "user", "id": 2, "text": "msg2", "pending": True},
                {"type": "user", "id": 3, "text": "msg3", "pending": True},
            ]

        deferred = self._simulate_queue_confirm(ws, tab_id)
        assert len(deferred) == 1

        # Loading + response blocks append correctly (no pending in the way)
        ns._block_add(tab_id, {"type": "loading"})
        ns._block_add(tab_id, {"type": "assistant", "text": "response to msg2"})
        ns._block_add(tab_id, {"type": "cost", "seconds": 5})

        # Restore deferred pending
        self._restore_deferred(ws, tab_id, deferred)

        with ws._chat_lock:
            blocks = ws.CHAT_SESSIONS[tab_id]["blocks"]
            types = [b["type"] for b in blocks]
            # msg1, cost1, msg2(confirmed), loading, assistant, cost2, msg3(pending)
            assert types == ["user", "cost", "user", "loading", "assistant", "cost", "user"]
            assert blocks[2]["text"] == "msg2"
            assert blocks[2].get("pending") is False
            assert blocks[6]["text"] == "msg3"
            assert blocks[6].get("pending") is True
            # Response blocks are BEFORE msg3, not after - this is the fix
            assert blocks[4]["text"] == "response to msg2"
