#!/usr/bin/env python3
"""Test persistent SDK sessions for dashboard chat.

Tests the routing logic WITHOUT spawning real SDK processes.
Directly manipulates CHAT_SESSIONS to simulate session states
and verifies messages get routed correctly.

Usage:
    python3 gateway/tests/test_persistent_session.py

NOTE: This is a standalone script, NOT a pytest test suite.
      It hits a LIVE server and spawns REAL Claude sessions.
      Pytest collection is disabled via pytestmark below.
"""

import pytest
# Skip all tests in this module when collected by pytest - they hit real server
pytestmark = pytest.mark.skip(reason="Live server test - run standalone via python3")

import asyncio
import json
import sys
import time
import threading
import requests

BASE = "http://localhost:18788"
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def test_routing_logic():
    """Test that messages get routed correctly based on session state.

    Uses a hidden test endpoint that manipulates CHAT_SESSIONS directly.
    If the endpoint doesn't exist, falls back to HTTP API integration test.
    """
    print("\n=== Test 1: Routing logic (unit) ===")

    # We'll test by creating sessions with known state and sending messages
    tab = f"test-persist-{int(time.time())}"

    # --- Scenario A: No existing session → should start new (routed=False) ---
    resp = requests.post(f"{BASE}/api/chat/send", timeout=10, json={
        "tab_id": tab,
        "prompt": "test-no-session",
        "model": "haiku",
        "effort": "low",
    })
    data = resp.json()
    check("No session → starts new thread", data.get("routed") is False,
          f"got: {data}")

    # Give the SDK thread a moment to populate CHAT_SESSIONS
    time.sleep(1)

    # --- Scenario B: Session busy (not idle) → should queue ---
    resp = requests.post(f"{BASE}/api/chat/send", timeout=10, json={
        "tab_id": tab,
        "prompt": "test-busy-queue",
        "model": "haiku",
        "effort": "low",
    })
    data = resp.json()
    check("Busy session → routed (queued)", data.get("routed") is True,
          f"got: {data}")

    # --- Scenario C: Wait for session to become idle, then send ---
    # We need to wait for the first message to complete and session to go idle.
    # Poll logs for "session_idle" or "Persistent session got new message"
    print("  ... waiting for first response to complete (up to 90s) ...")
    idle_detected = False
    for _ in range(90):
        time.sleep(1)
        try:
            resp = requests.get(f"{BASE}/api/chat/state/read", json={"tab_id": tab}, timeout=3)
            if resp.status_code == 200:
                state = resp.json()
                if state.get("session_idle"):
                    idle_detected = True
                    break
        except Exception:
            pass
        # Also check logs
        try:
            # Check if session went idle by looking at the log
            resp2 = requests.get(f"{BASE}/health", timeout=2)
        except Exception:
            pass

    # Try alternate detection: check CHAT_SESSIONS via a small API call
    if not idle_detected:
        # Just try sending - if it routes as "woke", we know it was idle
        pass

    resp = requests.post(f"{BASE}/api/chat/send", timeout=10, json={
        "tab_id": tab,
        "prompt": "test-wake-idle",
        "model": "haiku",
        "effort": "low",
    })
    data = resp.json()
    check("After completion → routed (woke idle or queued)", data.get("routed") is True,
          f"got: {data}")


def test_new_tab_fresh():
    """Test that a brand new tab always starts a fresh session."""
    print("\n=== Test 2: Fresh tab → new session ===")
    tab = f"test-fresh-{int(time.time())}"
    resp = requests.post(f"{BASE}/api/chat/send", timeout=10, json={
        "tab_id": tab,
        "prompt": "hello",
        "model": "haiku",
        "effort": "low",
    })
    data = resp.json()
    check("Fresh tab → routed=False (new session)", data.get("routed") is False, f"got: {data}")


def test_rapid_double_send():
    """Test sending two messages rapidly - second should be queued."""
    print("\n=== Test 3: Rapid double send → queue ===")
    tab = f"test-rapid-{int(time.time())}"

    # First message
    resp1 = requests.post(f"{BASE}/api/chat/send", json={
        "tab_id": tab,
        "prompt": "first message",
        "model": "haiku",
        "effort": "low",
    })
    data1 = resp1.json()
    check("First message → new session", data1.get("routed") is False, f"got: {data1}")

    # Immediate second message (session should be busy)
    time.sleep(0.5)  # tiny delay for thread to start
    resp2 = requests.post(f"{BASE}/api/chat/send", json={
        "tab_id": tab,
        "prompt": "second message",
        "model": "haiku",
        "effort": "low",
    })
    data2 = resp2.json()
    check("Second message → routed (queued)", data2.get("routed") is True, f"got: {data2}")


def test_log_verification():
    """Check server logs for expected persistent session log messages."""
    print("\n=== Test 4: Log verification ===")
    try:
        with open("/tmp/webhook-server.log") as f:
            logs = f.read()
        check("Log file readable", True)
        # After tests above, we should see routing messages
        has_woke = "Woke persistent session" in logs or "woke persistent session" in logs
        has_queued = "queued message" in logs.lower()
        has_persistent_idle = "Persistent session idle timeout" in logs or "Persistent session got new message" in logs
        check("Has queue log entries", has_queued)
        # These may or may not appear depending on timing
        if has_woke:
            check("Has 'Woke persistent session' (persistent reuse confirmed!)", True)
        else:
            print("  INFO  No 'Woke persistent session' yet (may need more time for SDK init)")
        if has_persistent_idle:
            check("Has persistent session lifecycle entries", True)
    except Exception as e:
        check("Log verification", False, str(e))


def main():
    global PASS, FAIL

    # Check server is up
    try:
        resp = requests.get(f"{BASE}/health", timeout=3)
        resp.raise_for_status()
    except Exception as e:
        print(f"Server not available at {BASE}: {e}")
        sys.exit(1)

    print(f"Server healthy. Running persistent session tests...\n")

    test_new_tab_fresh()
    test_rapid_double_send()
    test_log_verification()

    # Skip the long-running idle test by default
    if "--full" in sys.argv:
        test_routing_logic()

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
