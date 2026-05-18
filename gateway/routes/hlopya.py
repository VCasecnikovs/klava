"""Hlopya ingestion endpoints.

The watch MVP records one ambient microphone track and uploads it here. This
route normalizes that file into Hlopya's existing on-disk session shape so the
Mac app can process it without a separate import flow.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Blueprint, jsonify, request


hlopya_bp = Blueprint("hlopya", __name__)

_ALLOWED_SUFFIXES = {".wav", ".m4a", ".mp3", ".aac", ".caf", ".aiff", ".aif"}
_SESSION_ID_RE = re.compile(r"[^0-9A-Za-z_.-]+")
_TARGET_SAMPLE_RATE = 16_000


def _recordings_dir() -> Path:
    root = Path.home() / "recordings"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parse_recorded_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now()
    cleaned = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).astimezone().replace(tzinfo=None)
    except ValueError:
        return datetime.now()


def _safe_session_id(recorded_at: datetime, source: str) -> str:
    stamp = recorded_at.strftime("%Y-%m-%d_%H-%M-%S")
    safe_source = _SESSION_ID_RE.sub("-", source.strip().lower() or "watch").strip("-")
    return f"{stamp}_{safe_source}-{uuid4().hex[:8]}"


def _duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        return frames / rate if rate else 0.0


def _write_silent_wav(path: Path, duration: float) -> None:
    frames = max(1, int(duration * _TARGET_SAMPLE_RATE))
    chunk = b"\x00\x00" * _TARGET_SAMPLE_RATE
    full_seconds, remainder = divmod(frames, _TARGET_SAMPLE_RATE)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_TARGET_SAMPLE_RATE)
        for _ in range(full_seconds):
            wav.writeframes(chunk)
        if remainder:
            wav.writeframes(b"\x00\x00" * remainder)


def _convert_to_mic_wav(src: Path, dest: Path) -> None:
    afconvert = shutil.which("afconvert")
    if not afconvert:
        raise RuntimeError("afconvert not found; cannot normalize uploaded audio")

    subprocess.run(
        [
            afconvert,
            "-f",
            "WAVE",
            "-d",
            f"LEI16@{_TARGET_SAMPLE_RATE}",
            "-c",
            "1",
            str(src),
            str(dest),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _write_meta(path: Path, payload: dict[str, Any], duration: float) -> None:
    title = (payload.get("title") or "").strip() or "Watch Recording"
    source = (payload.get("source") or "apple-watch").strip() or "apple-watch"
    meta = {
        "title": title,
        "duration": duration,
        "participants": ["Me"],
        "participant_names": {"Me": "Me"},
        "status": "recorded",
        "source": source,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    if payload.get("recorded_at"):
        meta["recorded_at"] = str(payload["recorded_at"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


@hlopya_bp.route("/api/hlopya/watch/upload", methods=["POST"])
def upload_watch_recording():
    """Accept one watch recording and create a Hlopya-compatible session."""
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "error": "missing multipart file field 'file'"}), 400

    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        return jsonify({
            "ok": False,
            "error": f"unsupported audio type '{suffix or '(none)'}'",
            "allowed": sorted(_ALLOWED_SUFFIXES),
        }), 400

    payload = {
        "title": request.form.get("title"),
        "source": request.form.get("source") or "apple-watch",
        "recorded_at": request.form.get("recorded_at"),
    }
    recorded_at = _parse_recorded_at(payload["recorded_at"])
    session_id = _safe_session_id(recorded_at, payload["source"])
    session_dir = _recordings_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=False)

    try:
        with tempfile.TemporaryDirectory(prefix="hlopya-watch-") as tmp:
            tmp_src = Path(tmp) / f"upload{suffix}"
            uploaded.save(str(tmp_src))

            original_path = session_dir / f"watch-original{suffix}"
            shutil.copyfile(tmp_src, original_path)

            mic_path = session_dir / "mic.wav"
            _convert_to_mic_wav(tmp_src, mic_path)
            duration = _duration_seconds(mic_path)
            _write_silent_wav(session_dir / "system.wav", duration)
            _write_meta(session_dir / "meta.json", payload, duration)

            note = (request.form.get("note") or "").strip()
            if note:
                (session_dir / "personal_notes.md").write_text(note, encoding="utf-8")

    except Exception as exc:
        shutil.rmtree(session_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "session_id": session_id,
        "path": str(session_dir),
        "duration": duration,
        "files": ["mic.wav", "system.wav", f"watch-original{suffix}", "meta.json"],
    })
