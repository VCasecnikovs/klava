"""Tests for tasks/evidence_closer.py.

Regression: 2026-04-30 — RESULT cards stuck pending forever even when
the user had clearly acted on them. Evidence closer searches vadimgest
for evidence the action happened and closes safe matches.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from tasks import evidence_closer as ec
from tasks.evidence_closer import (
    Target, Evidence,
    _fts_query, _extract_doc_date,
    find_evidence, evaluate_card,
)


@dataclass
class FakeCard:
    id: str
    title: str
    body: str = ""
    created: Optional[str] = "2026-04-25T00:00:00+00:00"


# ------------------------------------------------------------------
#  _fts_query
# ------------------------------------------------------------------

class TestFtsQuery:
    def test_quotes_phrases(self):
        assert _fts_query(["Timur Olevskiy"]) == '"Timur Olevskiy"'

    def test_quotes_single_word_with_hyphen(self):
        # Regression: 2026-04-30 — `O-1` was passed unquoted and FTS5
        # parsed `-` as NOT, returning zero hits + cryptic errors.
        q = _fts_query(["O-1"])
        assert q == '"O-1"'

    def test_combines_with_and(self):
        q = _fts_query(["Timur Olevskiy", "Insider"])
        assert q == '"Timur Olevskiy" AND "Insider"'

    def test_strips_quotes_inside_terms(self):
        q = _fts_query(['Bob "the boss" Smith'])
        assert q == '"Bob the boss Smith"'

    def test_empty_terms(self):
        assert _fts_query([]) == ""
        assert _fts_query([""]) == ""
        assert _fts_query(["", "  "]) == ""


# ------------------------------------------------------------------
#  _extract_doc_date
# ------------------------------------------------------------------

class TestExtractDocDate:
    def test_signal_format(self):
        assert _extract_doc_date("/Timur Olevskiy Insider 2026-04-29") == "2026-04-29"

    def test_no_date(self):
        assert _extract_doc_date("Some doc with no date") is None

    def test_empty(self):
        assert _extract_doc_date("") is None
        assert _extract_doc_date(None) is None


# ------------------------------------------------------------------
#  find_evidence (real sqlite + FTS5)
# ------------------------------------------------------------------

@pytest.fixture
def fake_index(tmp_path):
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE VIRTUAL TABLE docs USING fts5(
            path, source, title, content,
            chat UNINDEXED, folder UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    rows = [
        # (path, source, title, content)
        ("signal:1", "signal", "/Timur Olevskiy Insider 2026-04-26",
         "Me: вот темы для статьи"),
        ("signal:2", "signal", "/Timur Olevskiy Insider 2026-03-01",
         "Me: старое сообщение"),
        ("signal:3", "signal", "/Diana Skorinkina 2026-04-29",
         "Diana: ok пиши"),
        ("gmail:1", "gmail", "RE: book inventory 2026-04-28",
         "Hi Shawn, here is the ISBN list..."),
        # off-channel — must not be matched by signal-only target
        ("claude:1", "claude", "/heartbeat 2026-04-29",
         "Saw a message about Timur Olevskiy"),
    ]
    conn.executemany(
        "INSERT INTO docs(path, source, title, content) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db


def test_find_evidence_returns_recent_signal_hit(fake_index):
    target = Target(
        actionable=True, person="Timur Olevskiy",
        search_terms=["Timur Olevskiy"], channels=["signal"],
    )
    hits = find_evidence(target, "2026-04-25T00:00:00+00:00", db_path=fake_index)
    assert len(hits) == 1
    assert hits[0].date == "2026-04-26"
    assert hits[0].source == "signal"


def test_find_evidence_filters_old_dates(fake_index):
    target = Target(
        actionable=True, person="Timur Olevskiy",
        search_terms=["Timur Olevskiy"], channels=["signal"],
    )
    hits = find_evidence(target, "2026-05-01T00:00:00+00:00", db_path=fake_index)
    assert hits == []


def test_find_evidence_respects_channels(fake_index):
    """Searching only `gmail` channel must not return signal/claude docs."""
    target = Target(
        actionable=True, person="Timur Olevskiy",
        search_terms=["Timur Olevskiy"], channels=["gmail"],
    )
    hits = find_evidence(target, "2026-04-25T00:00:00+00:00", db_path=fake_index)
    assert hits == []


def test_find_evidence_excludes_self_authored_sources(fake_index):
    """Even if `claude` source has a hit, it must not count as evidence
    when channel list is messaging-only.
    """
    target = Target(
        actionable=True, person="Timur Olevskiy",
        search_terms=["Timur Olevskiy"], channels=["signal", "telegram"],
    )
    hits = find_evidence(target, "2026-04-25T00:00:00+00:00", db_path=fake_index)
    assert all(h.source != "claude" for h in hits)


def test_find_evidence_phrase_match(fake_index):
    """Hyphenated phrase must match exactly without FTS5 NOT-parsing."""
    # Add a row with O-1 in content
    conn = sqlite3.connect(fake_index)
    conn.execute(
        "INSERT INTO docs(path, source, title, content) VALUES (?,?,?,?)",
        ("signal:99", "signal", "/Timur 2026-04-29", "Me: про O-1 визу"),
    )
    conn.commit()
    conn.close()

    target = Target(
        actionable=True, person="Timur",
        search_terms=["O-1"], channels=["signal"],
    )
    hits = find_evidence(target, "2026-04-25T00:00:00+00:00", db_path=fake_index)
    assert len(hits) == 1


# ------------------------------------------------------------------
#  evaluate_card branches
# ------------------------------------------------------------------

class TestEvaluateCard:
    def test_no_created_skips(self, monkeypatch):
        monkeypatch.setattr(ec, "extract_target", lambda *a, **k: None)
        card = FakeCard(id="x", title="Title", created=None)
        d = evaluate_card(card)
        assert d.decision == "skip-no-evidence"

    def test_extract_failure_skips(self, monkeypatch):
        monkeypatch.setattr(ec, "extract_target", lambda *a, **k: None)
        card = FakeCard(id="x", title="Title")
        d = evaluate_card(card)
        assert d.decision == "skip-no-target"

    def test_not_actionable_marked_digest(self, monkeypatch):
        monkeypatch.setattr(
            ec, "extract_target",
            lambda *a, **k: Target(
                actionable=False, person=None, search_terms=[], channels=[],
            ),
        )
        card = FakeCard(id="x", title="Pulse digest")
        d = evaluate_card(card)
        assert d.decision == "skip-not-actionable"

    def test_evidence_found_yields_close(self, monkeypatch, fake_index):
        monkeypatch.setattr(ec, "VADIMSEARCH_DB", fake_index)
        monkeypatch.setattr(
            ec, "extract_target",
            lambda *a, **k: Target(
                actionable=True, person="Timur Olevskiy",
                search_terms=["Timur Olevskiy"], channels=["signal"],
            ),
        )
        card = FakeCard(id="x", title="Send Timur Olevskiy article",
                        created="2026-04-25T00:00:00+00:00")
        d = evaluate_card(card)
        assert d.decision == "close"
        assert d.evidence and d.evidence[0].source == "signal"

    def test_no_evidence_yields_skip(self, monkeypatch, fake_index):
        monkeypatch.setattr(ec, "VADIMSEARCH_DB", fake_index)
        monkeypatch.setattr(
            ec, "extract_target",
            lambda *a, **k: Target(
                actionable=True, person="Random Person",
                search_terms=["Nobody"], channels=["signal"],
            ),
        )
        card = FakeCard(id="x", title="Reach out to Random Person")
        d = evaluate_card(card)
        assert d.decision == "skip-no-evidence"
