"""Tests for tasks/alias_index.py.

Regression: 2026-04-27 — RESULT dedup matcher missed `Александр Орлов` vs
`Rich Bro` and `Eldil AI (Shawn)` vs `Shawn Schneider`. Alias index reads
Obsidian `People/*.md` frontmatter to feed canonical-entity hints into the
LLM dedup prompt.
"""

import textwrap
from pathlib import Path

import pytest

from tasks import alias_index


@pytest.fixture
def fake_people_dir(tmp_path, monkeypatch):
    people = tmp_path / "People"
    people.mkdir()
    monkeypatch.setattr(alias_index, "PEOPLE_DIR", people)
    cache = tmp_path / "alias-cache.json"
    monkeypatch.setattr(alias_index, "CACHE_FILE", cache)
    return people


def _write(p: Path, name: str, frontmatter: str) -> None:
    body = f"---\n{textwrap.dedent(frontmatter).strip()}\n---\n# {name}\n"
    (p / f"{name}.md").write_text(body, encoding="utf-8")


def test_filename_only(fake_people_dir):
    _write(fake_people_dir, "Bruno Sgambato (Imperial College London)", "")
    idx = alias_index.load_index(force=True)
    assert "Bruno Sgambato (Imperial College London)" in idx
    aliases = idx["Bruno Sgambato (Imperial College London)"]
    assert "Bruno Sgambato" in aliases
    assert "Imperial College London" in aliases


def test_aliases_handle_company_combined(fake_people_dir):
    _write(
        fake_people_dir,
        "Александр Орлов (yeeti.fun)",
        """
        handle: "@richbro.01"
        aliases: [Саша Орлов, Rich Bro, richgoy]
        company: yeeti.fun, ton.sg
        """,
    )
    idx = alias_index.load_index(force=True)
    aliases = set(idx["Александр Орлов (yeeti.fun)"])
    assert "Rich Bro" in aliases
    assert "richbro.01" in aliases  # leading @ stripped
    assert "Саша Орлов" in aliases
    assert "yeeti.fun" in aliases
    assert "ton.sg" in aliases
    assert "Александр Орлов" in aliases  # base name from filename


def test_company_wikilink_unwrapped(fake_people_dir):
    _write(
        fake_people_dir,
        "Shawn Schneider (Eldil AI)",
        """
        handle: "@shawns2759"
        aliases: []
        company: "[[Eldil AI]]"
        """,
    )
    aliases = set(alias_index.load_index(force=True)["Shawn Schneider (Eldil AI)"])
    assert "Eldil AI" in aliases  # wikilink stripped
    assert "Shawn Schneider" in aliases
    assert "shawns2759" in aliases


def test_relevant_aliases_finds_known_entities(fake_people_dir):
    _write(
        fake_people_dir,
        "Александр Орлов (yeeti.fun)",
        """
        handle: "@richbro.01"
        aliases: [Rich Bro]
        """,
    )
    _write(
        fake_people_dir,
        "Shawn Schneider (Eldil AI)",
        """
        handle: "@shawns2759"
        company: "[[Eldil AI]]"
        """,
    )
    _write(fake_people_dir, "Diana Random", "")

    titles = [
        "Reply Rich Bro on Signal — ESTA",
        "Александр Орлов (Rich Bro) - status",
        "Diana — SF dates message",
    ]
    hints = alias_index.relevant_aliases(titles)
    joined = "\n".join(hints)
    assert "Александр Орлов" in joined
    assert "Rich Bro" in joined
    # Eldil entity isn't mentioned in titles → no hint
    assert "Shawn Schneider" not in joined


def test_cache_invalidates_on_dir_mtime_change(fake_people_dir):
    _write(fake_people_dir, "Person A (Org A)", "")
    idx1 = alias_index.load_index(force=True)
    assert "Person A (Org A)" in idx1

    _write(fake_people_dir, "Person B (Org B)", "")
    import os
    os.utime(fake_people_dir, None)

    idx2 = alias_index.load_index()
    assert "Person B (Org B)" in idx2
