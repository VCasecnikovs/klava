"""Shared fixtures for gateway tests."""

import os
import sys
import json
import pytest

# Ensure gateway directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def flask_app():
    """Create a Flask test app with minimal config."""
    # Set required env vars before importing
    os.environ.setdefault("WEBHOOK_TOKEN", "test-token-12345")

    # Import inline to avoid side effects at module level
    from importlib import import_module
    # We need to import the app from webhook-server.py (has a hyphen)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "webhook_server",
        os.path.join(os.path.dirname(__file__), "..", "webhook-server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    # Don't execute the full module - just get the app object
    # Instead, we'll use a simpler approach: patch and import
    # Register in sys.modules so @patch("webhook_server.xxx") works
    sys.modules["webhook_server"] = mod
    spec.loader.exec_module(mod)
    app = mod.app
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()


@pytest.fixture
def auth_headers():
    """Authorization headers with the test bearer token."""
    return {"Authorization": "Bearer test-token-12345"}


@pytest.fixture
def sample_deal_md(tmp_path):
    """Create a sample deal markdown file with frontmatter."""
    def _make(filename="TestDeal.md", frontmatter=None):
        if frontmatter is None:
            frontmatter = {
                "stage": "5-proposal",
                "value": "50000",
                "deal_size": "medium",
                "deal_type": "data-sale",
                "last_contact": "2026-02-20",
                "follow_up": "2026-02-25",
                "lead": "[[John Doe]]",
                "owner": "user",
            }
        lines = ["---"]
        for k, v in frontmatter.items():
            lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")
        lines.append("# Deal notes")
        filepath = tmp_path / filename
        filepath.write_text("\n".join(lines))
        return filepath
    return _make


@pytest.fixture
def sample_person_md(tmp_path):
    """Create a sample person markdown file with frontmatter."""
    def _make(filename="John Doe (Acme).md", frontmatter=None):
        if frontmatter is None:
            frontmatter = {
                "handle": "@johndoe",
                "email": "john@acme.com",
                "company": "Acme Corp",
                "role": "CTO",
                "tags": "[contact, tech]",
                "last_contact": "2026-02-15",
            }
        lines = ["---"]
        for k, v in frontmatter.items():
            lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")
        lines.append("## Background")
        lines.append("Some info")
        filepath = tmp_path / filename
        filepath.write_text("\n".join(lines))
        return filepath
    return _make


@pytest.fixture
def sample_jsonl(tmp_path):
    """Create a sample JSONL file."""
    def _make(filename="test.jsonl", records=None):
        if records is None:
            records = [
                {"job_id": "heartbeat", "status": "completed", "timestamp": "2026-02-23T10:00:00+00:00"},
                {"job_id": "reflection", "status": "failed", "timestamp": "2026-02-23T11:00:00+00:00", "error": "timeout"},
            ]
        filepath = tmp_path / filename
        with open(filepath, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return filepath
    return _make
