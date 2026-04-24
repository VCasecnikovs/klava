"""Tests for gateway/lib/main_session.py - session ID persistence."""

import pytest
from pathlib import Path
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import main_session


@pytest.fixture(autouse=True)
def isolate_globals(tmp_path, monkeypatch):
    """Redirect session storage to tmp_path for every test."""
    monkeypatch.setattr(main_session, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(main_session, "MAIN_SESSION_TOPIC", 100002)
    monkeypatch.setattr(main_session, "MAIN_SESSION_KEY", "main")


class TestGetMainSessionFile:
    def test_returns_path_under_sessions_dir(self, tmp_path):
        p = main_session.get_main_session_file()
        assert p.parent == tmp_path
        assert p.name == "main_claude_session.txt"

    def test_custom_key(self, monkeypatch, tmp_path):
        monkeypatch.setattr(main_session, "MAIN_SESSION_KEY", "custom")
        p = main_session.get_main_session_file()
        assert p.name == "custom_claude_session.txt"


class TestGetMainSessionId:
    def test_returns_none_when_file_missing(self):
        assert main_session.get_main_session_id() is None

    def test_returns_valid_uuid(self, tmp_path):
        uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        (tmp_path / "main_claude_session.txt").write_text(uid)
        assert main_session.get_main_session_id() == uid

    def test_returns_none_for_invalid_content(self, tmp_path):
        (tmp_path / "main_claude_session.txt").write_text("not-a-uuid")
        assert main_session.get_main_session_id() is None

    def test_returns_none_for_empty_file(self, tmp_path):
        (tmp_path / "main_claude_session.txt").write_text("")
        assert main_session.get_main_session_id() is None

    def test_strips_whitespace(self, tmp_path):
        uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        (tmp_path / "main_claude_session.txt").write_text(f"  {uid}  \n")
        assert main_session.get_main_session_id() == uid

    def test_case_insensitive_uuid(self, tmp_path):
        uid = "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        (tmp_path / "main_claude_session.txt").write_text(uid)
        assert main_session.get_main_session_id() == uid


class TestSaveMainSessionId:
    def test_creates_file(self, tmp_path):
        uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        main_session.save_main_session_id(uid)
        assert (tmp_path / "main_claude_session.txt").read_text() == uid

    def test_creates_parent_dirs(self, monkeypatch, tmp_path):
        nested = tmp_path / "deep" / "dir"
        monkeypatch.setattr(main_session, "SESSIONS_DIR", nested)
        main_session.save_main_session_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert (nested / "main_claude_session.txt").exists()

    def test_overwrites_existing(self, tmp_path):
        f = tmp_path / "main_claude_session.txt"
        f.write_text("old-value")
        main_session.save_main_session_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert f.read_text() == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestClearMainSessionId:
    def test_removes_file(self, tmp_path):
        f = tmp_path / "main_claude_session.txt"
        f.write_text("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        main_session.clear_main_session_id()
        assert not f.exists()

    def test_noop_when_file_missing(self):
        main_session.clear_main_session_id()  # should not raise


class TestIsMainTopic:
    def test_true_for_main_topic(self):
        assert main_session.is_main_topic(100002) is True

    def test_false_for_other_topic(self):
        assert main_session.is_main_topic(12345) is False

    def test_false_for_none(self):
        assert main_session.is_main_topic(None) is False


class TestGetMainTopicId:
    def test_returns_default(self):
        assert main_session.get_main_topic_id() == 100002

    def test_returns_custom(self, monkeypatch):
        monkeypatch.setattr(main_session, "MAIN_SESSION_TOPIC", 99999)
        assert main_session.get_main_topic_id() == 99999


class TestInitMainSession:
    def test_overrides_sessions_dir(self, monkeypatch, tmp_path):
        config = {"sessions": {"dir": str(tmp_path / "custom")}}
        main_session.init_main_session(config)
        assert main_session.SESSIONS_DIR == tmp_path / "custom"

    def test_overrides_topic_and_key(self, monkeypatch):
        config = {"main_session": {"topic_id": 111, "session_key": "alt"}}
        main_session.init_main_session(config)
        assert main_session.MAIN_SESSION_TOPIC == 111
        assert main_session.MAIN_SESSION_KEY == "alt"

    def test_defaults_when_empty_config(self, monkeypatch):
        main_session.init_main_session({})
        assert main_session.MAIN_SESSION_TOPIC == 100002
        assert main_session.MAIN_SESSION_KEY == "main"
