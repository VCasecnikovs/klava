"""Tests for frontmatter parsing functions in status_collector.py.

Uses tmp_path to create sample markdown files with various frontmatter formats.
"""

import pytest
from pathlib import Path

from lib.status_collector import _parse_deal_frontmatter, _parse_people_frontmatter


# ── _parse_deal_frontmatter ────────────────────────────────────────────

class TestParseDealFrontmatter:
    def test_valid_frontmatter(self, sample_deal_md):
        filepath = sample_deal_md()
        result = _parse_deal_frontmatter(filepath)
        assert result is not None
        assert result["stage"] == "5-proposal"
        assert result["value"] == "50000"
        assert result["deal_size"] == "medium"

    def test_quoted_values(self, tmp_path):
        filepath = tmp_path / "quoted.md"
        filepath.write_text('---\nstage: "5-proposal"\nvalue: \'50000\'\n---\n')
        result = _parse_deal_frontmatter(filepath)
        assert result is not None
        assert result["stage"] == "5-proposal"
        assert result["value"] == "50000"

    def test_null_values(self, tmp_path):
        filepath = tmp_path / "nulls.md"
        filepath.write_text('---\nstage: 5-proposal\nvalue: null\nmrr: ~\nnotes:\n---\n')
        result = _parse_deal_frontmatter(filepath)
        assert result is not None
        assert result["value"] is None
        assert result["mrr"] is None
        assert result["notes"] is None

    def test_missing_frontmatter(self, tmp_path):
        filepath = tmp_path / "no_fm.md"
        filepath.write_text("# Just a heading\nSome content\n")
        result = _parse_deal_frontmatter(filepath)
        assert result is None

    def test_file_not_found(self, tmp_path):
        filepath = tmp_path / "nonexistent.md"
        result = _parse_deal_frontmatter(filepath)
        assert result is None

    def test_comment_lines_skipped(self, tmp_path):
        filepath = tmp_path / "comments.md"
        filepath.write_text('---\n# comment\nstage: 3-meeting\n---\n')
        result = _parse_deal_frontmatter(filepath)
        assert result is not None
        assert "# comment" not in result
        assert result["stage"] == "3-meeting"

    def test_list_items_skipped(self, tmp_path):
        filepath = tmp_path / "lists.md"
        filepath.write_text('---\nstage: 1-prospecting\n- item1\n- item2\n---\n')
        result = _parse_deal_frontmatter(filepath)
        assert result is not None
        assert result["stage"] == "1-prospecting"

    def test_empty_frontmatter_returns_none(self, tmp_path):
        """Empty frontmatter (---\\n---) has no content between delimiters,
        so regex doesn't match and returns None."""
        filepath = tmp_path / "empty.md"
        filepath.write_text('---\n---\nContent\n')
        result = _parse_deal_frontmatter(filepath)
        assert result is None

    def test_whitespace_only_frontmatter(self, tmp_path):
        filepath = tmp_path / "ws.md"
        filepath.write_text('---\n\n---\nContent\n')
        result = _parse_deal_frontmatter(filepath)
        assert result is not None
        assert len(result) == 0


# ── _parse_people_frontmatter ─────────────────────────────────────────

class TestParsePeopleFrontmatter:
    def test_valid_frontmatter(self, sample_person_md):
        filepath = sample_person_md()
        result = _parse_people_frontmatter(filepath)
        assert result is not None
        assert result["handle"] == "@johndoe"
        assert result["email"] == "john@acme.com"
        assert result["company"] == "Acme Corp"

    def test_inline_list(self, tmp_path):
        filepath = tmp_path / "list.md"
        filepath.write_text('---\ntags: [contact, tech, vip]\n---\n')
        result = _parse_people_frontmatter(filepath)
        assert result is not None
        assert isinstance(result["tags"], list)
        assert "contact" in result["tags"]
        assert "tech" in result["tags"]
        assert "vip" in result["tags"]

    def test_yaml_list(self, tmp_path):
        filepath = tmp_path / "yaml_list.md"
        filepath.write_text('---\ntags:\n- contact\n- tech\n---\n')
        result = _parse_people_frontmatter(filepath)
        assert result is not None
        assert isinstance(result["tags"], list)
        assert "contact" in result["tags"]
        assert "tech" in result["tags"]

    def test_null_handling(self, tmp_path):
        filepath = tmp_path / "nulls.md"
        filepath.write_text('---\nhandle: @test\nemail: null\nphone: ~\nwebsite:\n---\n')
        result = _parse_people_frontmatter(filepath)
        assert result is not None
        assert result["email"] is None
        assert result["phone"] is None

    def test_missing_frontmatter(self, tmp_path):
        filepath = tmp_path / "no_fm.md"
        filepath.write_text("Just text, no frontmatter\n")
        result = _parse_people_frontmatter(filepath)
        assert result is None

    def test_read_error(self, tmp_path):
        filepath = tmp_path / "nonexistent.md"
        result = _parse_people_frontmatter(filepath)
        assert result is None

    def test_quoted_values(self, tmp_path):
        filepath = tmp_path / "quoted.md"
        filepath.write_text('---\nhandle: "@johndoe"\nemail: \'john@test.com\'\n---\n')
        result = _parse_people_frontmatter(filepath)
        assert result is not None
        assert result["handle"] == "@johndoe"
        assert result["email"] == "john@test.com"

    def test_empty_frontmatter_returns_none(self, tmp_path):
        """Empty frontmatter (---\\n---) has no content between delimiters,
        so regex doesn't match and returns None."""
        filepath = tmp_path / "empty.md"
        filepath.write_text('---\n---\n')
        result = _parse_people_frontmatter(filepath)
        assert result is None

    def test_whitespace_only_frontmatter(self, tmp_path):
        filepath = tmp_path / "ws.md"
        filepath.write_text('---\n\n---\n')
        result = _parse_people_frontmatter(filepath)
        assert result is not None
        assert len(result) == 0
