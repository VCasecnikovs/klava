import json
from unittest.mock import patch

from lib import session_requests


def test_build_prompt_from_result_card():
    prompt = session_requests.build_prompt_from_card({
        "id": "abc123",
        "title": "[RESULT] Update CRM",
        "type": "result",
        "result": "Done and verified.",
        "scope": "Vox Lab/Deals/Acme/",
    })

    assert "Let's discuss this Klava result in Codex." in prompt
    assert "**Result:** Update CRM" in prompt
    assert "**Card id:** abc123" in prompt
    assert "Vox Lab/Deals/Acme/" in prompt
    assert "Done and verified." in prompt


def test_create_session_request_persists_json_and_index(tmp_path, monkeypatch):
    request_dir = tmp_path / "session-requests"
    monkeypatch.setattr(session_requests, "SESSION_REQUEST_DIR", request_dir)
    monkeypatch.setattr(session_requests, "SESSION_REQUEST_INDEX", request_dir / "requests.jsonl")

    req = session_requests.create_session_request({
        "id": "card1",
        "title": "[PROPOSAL] Follow up",
        "type": "proposal",
        "proposal_plan": "Send a short note.",
    }, cwd="/tmp/project")

    saved = json.loads((request_dir / f"{req.id}.json").read_text())
    lines = (request_dir / "requests.jsonl").read_text().splitlines()

    assert saved["id"] == req.id
    assert saved["title"] == "Follow up"
    assert saved["card_id"] == "card1"
    assert saved["card_type"] == "proposal"
    assert saved["cwd"] == "/tmp/project"
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == req.id


def test_codex_session_request_route(client):
    with (
        patch("routes.dashboard_api.create_session_request") as mock_create,
        patch("routes.dashboard_api.copy_prompt_to_clipboard", return_value=(True, None)),
        patch("routes.dashboard_api.open_codex_app", return_value=(True, None)),
    ):
        mock_create.return_value = session_requests.SessionRequest(
            id="sr_test",
            created_at="2026-05-16T00:00:00+00:00",
            title="Test",
            prompt="Prompt body",
            cwd="/tmp/project",
            card_id="card1",
            card_type="result",
        )

        resp = client.post("/api/codex/session-requests", json={
            "id": "card1",
            "title": "[RESULT] Test",
            "type": "result",
            "result": "ok",
        })

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["request"]["id"] == "sr_test"
    assert data["request"]["card_id"] == "card1"
    assert data["copied"] is True
    assert data["opened"] is True
