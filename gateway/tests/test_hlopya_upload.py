"""Tests for Hlopya watch recording ingestion."""

from __future__ import annotations

import io
import wave


def _wav_bytes(duration_seconds: float = 0.1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * int(16_000 * duration_seconds))
    return buf.getvalue()


def test_watch_upload_creates_hlopya_session(client, auth_headers, tmp_path, monkeypatch):
    import routes.hlopya as hlopya

    monkeypatch.setattr(hlopya.Path, "home", lambda: tmp_path)

    response = client.post(
        "/api/hlopya/watch/upload",
        headers=auth_headers,
        data={
            "title": "Walk call",
            "source": "apple-watch",
            "recorded_at": "2026-05-18T10:00:00",
            "file": (io.BytesIO(_wav_bytes()), "recording.wav"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    session_dir = tmp_path / "recordings" / data["session_id"]
    assert (session_dir / "mic.wav").exists()
    assert (session_dir / "system.wav").exists()
    assert (session_dir / "meta.json").exists()
    assert (session_dir / "watch-original.wav").exists()


def test_watch_upload_rejects_missing_file(client, auth_headers):
    response = client.post(
        "/api/hlopya/watch/upload",
        headers=auth_headers,
        data={"title": "No file"},
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False
