"""E2E browser tests for dashboard chat.

Runs against a LIVE server at localhost:18788 with real Claude SDK (haiku, low effort).
These tests are slow (~15-60s each) and cost real money - run sparingly.

Usage:
    cd gateway
    python -m pytest tests/test_e2e_chat.py -v --headed   # watch in browser
    python -m pytest tests/test_e2e_chat.py -v             # headless
    python -m pytest tests/test_e2e_chat.py -v -k new_session  # single test

Requires:
    pip install pytest-playwright
    Server running at localhost:18788

NOTE: Skipped by default during normal pytest runs.
      Uses real Claude API = real tokens = real money.
      Run explicitly: pytest tests/test_e2e_chat.py -m e2e
"""

import re
import pytest

# Skip by default - these hit real Claude API and cost money
pytestmark = pytest.mark.skip(reason="E2E test - hits real Claude API. Run explicitly with: pytest tests/test_e2e_chat.py")

from playwright.sync_api import Page

BASE_URL = "http://localhost:18788"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1920, "height": 1080}}


@pytest.fixture(scope="session")
def _check_server():
    """Skip all tests if server is not running."""
    import urllib.request
    try:
        urllib.request.urlopen(f"{BASE_URL}/health", timeout=3)
    except Exception:
        pytest.skip("Server not running at localhost:18788")


@pytest.fixture
def chat_page(page: Page, _check_server):
    """Navigate to dashboard, wait for React + WebSocket, configure haiku/low."""
    page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")
    # Wait for React to mount
    page.wait_for_function(
        "() => document.getElementById('root')?.children.length > 0",
        timeout=15000,
    )
    # Wait for chat textarea to exist in DOM
    page.wait_for_function(
        "() => !!document.querySelector('textarea.chat-input')",
        timeout=10000,
    )
    # Set model=haiku, effort=low via JS (avoids visibility issues)
    page.evaluate("""() => {
        const selects = document.querySelectorAll('select.chat-select');
        if (selects[0]) {
            const s0 = selects[0];
            const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
            setter.call(s0, 'haiku');
            s0.dispatchEvent(new Event('change', { bubbles: true }));
        }
        if (selects[1]) {
            const s1 = selects[1];
            const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
            setter.call(s1, 'low');
            s1.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }""")
    return page


# --- Helpers ---

def send_message(page: Page, text: str):
    """Send message via React-compatible JS."""
    page.evaluate("""(text) => {
        const ta = document.querySelector('textarea.chat-input');
        if (!ta) throw new Error('textarea.chat-input not found');
        const setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value'
        ).set;
        setter.call(ta, text);
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        ta.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
        }));
    }""", text)


def wait_for_cost_block(page: Page, n: int = 1, timeout: int = 60000):
    """Wait for n cost blocks (pattern: $X.XXXX) to appear in body text."""
    page.wait_for_function(
        f"() => (document.body.innerText.match(/\\$\\d+\\.\\d+/g) || []).length >= {n}",
        timeout=timeout,
    )


def get_body(page: Page) -> str:
    return page.inner_text("body")


def click_plus_button(page: Page):
    """Click the + button to create a new session."""
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.trim() === '+') { b.click(); return true; }
        }
        return false;
    }""")
    page.wait_for_timeout(500)


# =========================================================================
# TESTS
# =========================================================================

class TestNewSession:
    """Create a new chat session and verify the full flow."""

    def test_send_and_receive(self, chat_page: Page):
        """Send message -> user block + assistant response + cost block."""
        send_message(chat_page, "Reply with exactly one word: pong")

        # User message appears
        chat_page.wait_for_function(
            "() => document.body.innerText.includes('Reply with exactly one word: pong')",
            timeout=10000,
        )

        # Wait for response completion
        wait_for_cost_block(chat_page)

        body = get_body(chat_page)
        assert re.search(r"\$\d+\.\d+", body), "Cost block not found"

    def test_session_id_in_page(self, chat_page: Page):
        """After response, session ID (hex) appears somewhere in page."""
        send_message(chat_page, "Reply: yes")
        wait_for_cost_block(chat_page)

        body = get_body(chat_page)
        # Session IDs are UUIDs - look for hex pattern
        assert re.search(r"[0-9a-f]{8}", body, re.IGNORECASE), \
            "No session ID (hex) found in page"


class TestMultiTurn:
    """Multi-turn conversation in same session."""

    def test_second_message(self, chat_page: Page):
        """Send two messages - both visible, two cost blocks."""
        send_message(chat_page, "Remember: banana")
        wait_for_cost_block(chat_page, n=1)

        # Wait for session to become idle before sending second message
        chat_page.wait_for_timeout(2000)

        send_message(chat_page, "What word did I say?")
        wait_for_cost_block(chat_page, n=2, timeout=90000)

        body = get_body(chat_page)
        assert "banana" in body.lower()


class TestCancel:
    """Cancel a streaming response."""

    def test_cancel_and_recover(self, chat_page: Page):
        """Cancel mid-stream, then send another message successfully."""
        send_message(chat_page, "Write a very long 1000 word essay about space exploration history")

        # Wait for some streaming to start
        chat_page.wait_for_function(
            "() => document.body.innerText.includes('space') || document.body.innerText.length > 300",
            timeout=30000,
        )
        chat_page.wait_for_timeout(1500)

        # Cancel via JS (find cancel/stop button or use Escape)
        chat_page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = b.textContent.toLowerCase();
                if (t.includes('cancel') || t.includes('stop')) { b.click(); return 'clicked'; }
            }
            // Fallback: press Escape
            document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
            return 'escape';
        }""")
        chat_page.wait_for_timeout(2000)

        # Should still be able to chat
        send_message(chat_page, "Say: recovered")
        chat_page.wait_for_function(
            "() => document.body.innerText.includes('recovered') || (document.body.innerText.match(/\\$\\d+\\.\\d+/g) || []).length >= 1",
            timeout=60000,
        )


class TestSessionManagement:
    """Session sidebar operations."""

    def test_new_session_via_plus(self, chat_page: Page):
        """Click + creates a new empty session."""
        send_message(chat_page, "Reply: first")
        wait_for_cost_block(chat_page)

        click_plus_button(chat_page)

        body = get_body(chat_page)
        assert "Start a new conversation" in body or "Claude Code" in body
