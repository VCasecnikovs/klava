"""Tests for _safe_json_load in status_collector.py.

Tests: valid JSON, default on bad JSON, retry behavior, file not found, empty file.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from lib.status_collector import _safe_json_load


class TestSafeJsonLoad:
    def test_valid_json(self, tmp_path):
        filepath = tmp_path / "valid.json"
        filepath.write_text('{"key": "value", "count": 42}')
        result = _safe_json_load(filepath)
        assert result == {"key": "value", "count": 42}

    def test_valid_json_array(self, tmp_path):
        filepath = tmp_path / "array.json"
        filepath.write_text('[1, 2, 3]')
        result = _safe_json_load(filepath)
        assert result == [1, 2, 3]

    def test_bad_json_with_default(self, tmp_path):
        filepath = tmp_path / "bad.json"
        filepath.write_text('not valid json {{{')
        result = _safe_json_load(filepath, default={})
        assert result == {}

    def test_bad_json_without_default_raises(self, tmp_path):
        filepath = tmp_path / "bad.json"
        filepath.write_text('{invalid')
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _safe_json_load(filepath)

    def test_file_not_found_raises(self, tmp_path):
        filepath = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            _safe_json_load(filepath)

    def test_empty_file_with_default(self, tmp_path):
        filepath = tmp_path / "empty.json"
        filepath.write_text("")
        result = _safe_json_load(filepath, default={"fallback": True})
        assert result == {"fallback": True}

    def test_retry_on_decode_error(self, tmp_path):
        """Verify that _safe_json_load retries on JSONDecodeError."""
        filepath = tmp_path / "retry.json"
        filepath.write_text('{"ok": true}')

        call_count = 0
        original_open = open

        def flaky_open(path, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call returns bad data
                from io import StringIO
                return StringIO("{bad json")
            return original_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=flaky_open):
            result = _safe_json_load(filepath, retries=2)
        assert result == {"ok": True}
        assert call_count >= 2

    def test_default_list(self, tmp_path):
        filepath = tmp_path / "bad.json"
        filepath.write_text("corrupted")
        result = _safe_json_load(filepath, default=[])
        assert result == []
