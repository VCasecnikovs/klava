"""Tests for collector functions in gateway/lib/status_collector.py.

Tests the data-collecting functions (deals, people, followups, calendar,
views, feed, failing_jobs) with monkeypatched directories and cleared caches.
"""

import json
import os
import sys
import time
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.status_collector as sc


def _clear_all_caches():
    """Reset all module-level caches."""
    for cache_name in ["_deals_cache", "_people_cache", "_followups_cache",
                       "_calendar_cache", "_views_cache", "_tasks_cache"]:
        cache = getattr(sc, cache_name, None)
        if cache:
            cache["data"] = None
            cache["ts"] = 0


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before each test."""
    _clear_all_caches()
    yield
    _clear_all_caches()


# ── collect_deals_data ──

class TestCollectDealsData:
    def _make_deal(self, deals_dir, name, stage="5-proposal", value="50000",
                   last_contact="2026-03-10", follow_up="2026-03-20", **extra):
        fm_lines = [
            "---",
            f"stage: {stage}",
            f"value: {value}",
            f"last_contact: {last_contact}",
        ]
        if follow_up:
            fm_lines.append(f"follow_up: {follow_up}")
        for k, v in extra.items():
            fm_lines.append(f"{k}: {v}")
        fm_lines.extend(["---", "", "# Notes"])
        (deals_dir / f"{name}.md").write_text("\n".join(fm_lines))

    def test_empty_deals_dir(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        result = sc.collect_deals_data()
        assert result["metrics"]["active_count"] == 0
        assert result["deals"] == []

    def test_no_deals_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        result = sc.collect_deals_data()
        assert result["metrics"]["active_count"] == 0

    def test_parses_deals(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_deal(deals_dir, "AcmeCorp", stage="7-evaluation", value="85000")
        self._make_deal(deals_dir, "Google", stage="3-outreach", value="20000")

        result = sc.collect_deals_data()
        assert result["metrics"]["active_count"] == 2
        assert result["metrics"]["total_pipeline"] == 105000
        names = [d["name"] for d in result["deals"]]
        assert "AcmeCorp" in names
        assert "Google" in names

    def test_priority_deals_flagged(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_deal(deals_dir, "AcmeCorp Data", stage="7-evaluation", value="85000")
        self._make_deal(deals_dir, "Random Corp", stage="5-proposal", value="10000")

        result = sc.collect_deals_data()
        ms = next(d for d in result["deals"] if d["name"] == "AcmeCorp Data")
        rnd = next(d for d in result["deals"] if d["name"] == "Random Corp")
        assert ms["is_priority"] is True
        assert rnd["is_priority"] is False

    def test_overdue_followup(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_deal(deals_dir, "OldDeal", stage="5-proposal",
                        value="10000", follow_up="2020-01-01")

        result = sc.collect_deals_data()
        deal = result["deals"][0]
        assert deal["overdue"] is True
        assert result["metrics"]["overdue_count"] == 1

    def test_pipeline_stages(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_deal(deals_dir, "A", stage="5-proposal", value="10000")
        self._make_deal(deals_dir, "B", stage="5-proposal", value="20000")
        self._make_deal(deals_dir, "C", stage="10-negotiation", value="50000")

        result = sc.collect_deals_data()
        stages = result["pipeline_stages"]
        stage5 = next(s for s in stages if s["stage_num"] == 5)
        assert stage5["count"] == 2
        assert stage5["total_value"] == 30000

    def test_weighted_pipeline(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        # Stage 1 = 0.10 weight, $100k = $10k weighted
        self._make_deal(deals_dir, "Early", stage="1-lead", value="100000")

        result = sc.collect_deals_data()
        assert result["metrics"]["weighted_pipeline"] == 10000.0

    def test_skips_no_stage(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        # File without stage
        (deals_dir / "NoStage.md").write_text("---\nvalue: 10000\n---\n# Notes")
        self._make_deal(deals_dir, "HasStage", stage="5-proposal", value="10000")

        result = sc.collect_deals_data()
        assert len(result["deals"]) == 1  # only the one with stage


# ── collect_people_data ──

class TestCollectPeopleData:
    def _make_person(self, people_dir, name, company="Acme", role="CTO",
                     last_contact="2026-03-10", tags="[contact, tech]"):
        fm = f"---\ncompany: {company}\nrole: {role}\nlast_contact: {last_contact}\ntags: {tags}\n---\n\n## Background\nInfo"
        (people_dir / f"{name}.md").write_text(fm)

    def test_empty_dir(self, tmp_path, monkeypatch):
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        result = sc.collect_people_data()
        assert result["metrics"]["total_contacts"] == 0

    def test_parses_people(self, tmp_path, monkeypatch):
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_person(people_dir, "John Doe (Acme)", company="Acme Corp")
        self._make_person(people_dir, "Jane Smith (Google)", company="Google")

        result = sc.collect_people_data()
        assert result["metrics"]["total_contacts"] == 2
        assert result["metrics"]["companies"] == 2
        names = [p["name"] for p in result["people"]]
        assert "John Doe (Acme)" in names

    def test_stale_contact(self, tmp_path, monkeypatch):
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_person(people_dir, "Old Contact", last_contact="2020-01-01")

        result = sc.collect_people_data()
        assert result["metrics"]["stale_30d"] == 1

    def test_recent_contact(self, tmp_path, monkeypatch):
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        today = datetime.now().strftime("%Y-%m-%d")
        self._make_person(people_dir, "Fresh Contact", last_contact=today)

        result = sc.collect_people_data()
        assert result["metrics"]["recent_7d"] == 1

    def test_no_last_contact_is_stale(self, tmp_path, monkeypatch):
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        (people_dir / "NoContact.md").write_text("---\ncompany: Corp\nrole: Dev\n---\n")

        result = sc.collect_people_data()
        assert result["metrics"]["stale_30d"] == 1

    def test_inline_list_tags(self, tmp_path, monkeypatch):
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_person(people_dir, "Tagged Person", tags="[vox, client, robotics]")

        result = sc.collect_people_data()
        person = result["people"][0]
        assert isinstance(person["tags"], list)
        assert "vox" in person["tags"]


# ── _parse_people_frontmatter ──

class TestParsePeopleFrontmatter:
    def test_basic(self, tmp_path):
        f = tmp_path / "Person.md"
        f.write_text("---\ncompany: Acme\nrole: CTO\n---\n\nNotes")
        result = sc._parse_people_frontmatter(f)
        assert result["company"] == "Acme"
        assert result["role"] == "CTO"

    def test_yaml_list(self, tmp_path):
        f = tmp_path / "Person.md"
        f.write_text("---\ntags:\n- client\n- vox\n- robotics\n---\n")
        result = sc._parse_people_frontmatter(f)
        assert result["tags"] == ["client", "vox", "robotics"]

    def test_inline_list(self, tmp_path):
        f = tmp_path / "Person.md"
        f.write_text("---\ntags: [a, b, c]\n---\n")
        result = sc._parse_people_frontmatter(f)
        assert result["tags"] == ["a", "b", "c"]

    def test_quoted_values(self, tmp_path):
        f = tmp_path / "Person.md"
        f.write_text('---\nname: "John Doe"\nrole: \'CTO\'\n---\n')
        result = sc._parse_people_frontmatter(f)
        assert result["name"] == "John Doe"
        assert result["role"] == "CTO"

    def test_null_values(self, tmp_path):
        f = tmp_path / "Person.md"
        f.write_text("---\nphone: null\nemail: ~\n---\n")
        result = sc._parse_people_frontmatter(f)
        assert result["phone"] is None
        assert result["email"] is None

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "Person.md"
        f.write_text("Just text no frontmatter")
        assert sc._parse_people_frontmatter(f) is None

    def test_missing_file(self, tmp_path):
        assert sc._parse_people_frontmatter(tmp_path / "missing.md") is None


# ── collect_followups_data ──

class TestCollectFollowupsData:
    def _make_deal(self, deals_dir, name, stage="5-proposal", value="50000",
                   follow_up=None, **extra):
        fm_lines = ["---", f"stage: {stage}", f"value: {value}"]
        if follow_up:
            fm_lines.append(f"follow_up: {follow_up}")
        for k, v in extra.items():
            fm_lines.append(f"{k}: {v}")
        fm_lines.extend(["---", ""])
        (deals_dir / f"{name}.md").write_text("\n".join(fm_lines))

    def test_empty(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        result = sc.collect_followups_data()
        assert result["metrics"]["overdue_count"] == 0
        assert result["metrics"]["upcoming_count"] == 0

    def test_overdue_followups(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_deal(deals_dir, "OverdueDeal", follow_up="2020-01-01")

        result = sc.collect_followups_data()
        assert result["metrics"]["overdue_count"] == 1
        assert result["overdue"][0]["deal"] == "OverdueDeal"
        assert result["overdue"][0]["overdue"] is True

    def test_upcoming_followups(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self._make_deal(deals_dir, "UpcomingDeal", follow_up=tomorrow)

        result = sc.collect_followups_data()
        assert result["metrics"]["upcoming_count"] == 1

    def test_far_future_excluded(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        far = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        self._make_deal(deals_dir, "FarDeal", follow_up=far)

        result = sc.collect_followups_data()
        assert result["metrics"]["overdue_count"] == 0
        assert result["metrics"]["upcoming_count"] == 0

    def test_inactive_deal_excluded(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self._make_deal(deals_dir, "LostDeal", stage="17-lost", follow_up=tomorrow)

        result = sc.collect_followups_data()
        assert result["metrics"]["upcoming_count"] == 0

    def test_no_followup_excluded(self, tmp_path, monkeypatch):
        deals_dir = tmp_path / "Deals"
        deals_dir.mkdir(parents=True)
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)

        self._make_deal(deals_dir, "NoFollowup")  # no follow_up field

        result = sc.collect_followups_data()
        assert len(result["overdue"]) == 0
        assert len(result["upcoming"]) == 0


# ── collect_calendar_data ──

class TestCollectCalendarData:
    def test_no_calendar_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path)

        result = sc.collect_calendar_data()
        assert result["status"] == "sync_pending"

    def test_empty_calendar(self, tmp_path, monkeypatch):
        cal_dir = tmp_path / "data" / "sources"
        cal_dir.mkdir(parents=True)
        (cal_dir / "calendar.jsonl").write_text("")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path)

        result = sc.collect_calendar_data()
        assert result["status"] == "empty"

    def test_parses_events(self, tmp_path, monkeypatch):
        cal_dir = tmp_path / "data" / "sources"
        cal_dir.mkdir(parents=True)
        today = datetime.now().strftime("%Y-%m-%d")
        events = [
            {"title": "Meeting", "start": f"{today}T10:00:00+00:00", "end": f"{today}T11:00:00+00:00"},
            {"summary": "Call", "start": f"{today}T14:00:00+00:00"},
        ]
        (cal_dir / "calendar.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path)

        result = sc.collect_calendar_data()
        assert result["status"] == "ok"
        assert result["metrics"]["today_count"] == 2

    def test_date_only_events(self, tmp_path, monkeypatch):
        cal_dir = tmp_path / "data" / "sources"
        cal_dir.mkdir(parents=True)
        today = datetime.now().strftime("%Y-%m-%d")
        events = [{"title": "All Day", "date": today}]
        (cal_dir / "calendar.jsonl").write_text(json.dumps(events[0]) + "\n")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path)

        result = sc.collect_calendar_data()
        assert result["metrics"]["today_count"] == 1

    def test_future_events_in_week(self, tmp_path, monkeypatch):
        cal_dir = tmp_path / "data" / "sources"
        cal_dir.mkdir(parents=True)
        future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        events = [{"title": "Future Event", "start": f"{future}T10:00:00+00:00"}]
        (cal_dir / "calendar.jsonl").write_text(json.dumps(events[0]) + "\n")
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path)

        result = sc.collect_calendar_data()
        assert result["metrics"]["week_count"] == 1
        assert result["metrics"]["today_count"] == 0


# ── collect_views_data ──

class TestCollectViewsData:
    def test_empty_dir(self, tmp_path, monkeypatch):
        tmp_path.mkdir(exist_ok=True)
        monkeypatch.setattr(sc, "VIEWS_DIR", tmp_path)

        result = sc.collect_views_data()
        assert result["status"] == "empty"
        assert result["views"] == []

    def test_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VIEWS_DIR", tmp_path / "nope")
        result = sc.collect_views_data()
        assert result["status"] == "empty"

    def test_finds_html_views(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VIEWS_DIR", tmp_path)
        (tmp_path / "report.html").write_text("<html><title>Test Report</title><body>Content</body></html>")
        (tmp_path / "other.html").write_text("<html><body>No title</body></html>")

        result = sc.collect_views_data()
        assert result["status"] == "ok"
        assert result["metrics"]["total"] == 2
        titles = [v["title"] for v in result["views"]]
        assert "Test Report" in titles

    def test_skips_dashboard_html(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VIEWS_DIR", tmp_path)
        (tmp_path / "dashboard.html").write_text("<html><body>Dashboard</body></html>")
        (tmp_path / "other.html").write_text("<html><body>Other</body></html>")

        result = sc.collect_views_data()
        assert result["metrics"]["total"] == 1
        names = [v["filename"] for v in result["views"]]
        assert "dashboard.html" not in names


# ── collect_feed_data ──

class TestCollectFeedData:
    def test_no_feed_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "FEED_LOG", tmp_path / "nonexistent.jsonl")
        result = sc.collect_feed_data()
        assert result["total"] == 0
        assert result["messages"] == []

    def test_reads_feed(self, tmp_path, monkeypatch):
        log = tmp_path / "messages.jsonl"
        entries = [
            {"topic": "Heartbeat", "text": "Update 1", "timestamp": "2026-03-16T10:00:00+00:00"},
            {"topic": "Alerts", "text": "Alert!", "timestamp": "2026-03-16T11:00:00+00:00"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        monkeypatch.setattr(sc, "FEED_LOG", log)

        result = sc.collect_feed_data()
        assert result["total"] == 2
        assert "Heartbeat" in result["topics"]
        assert "Alerts" in result["topics"]

    def test_topic_filter(self, tmp_path, monkeypatch):
        log = tmp_path / "messages.jsonl"
        entries = [
            {"topic": "Heartbeat", "text": "Update 1", "timestamp": "2026-03-16T10:00:00+00:00"},
            {"topic": "Alerts", "text": "Alert!", "timestamp": "2026-03-16T11:00:00+00:00"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        monkeypatch.setattr(sc, "FEED_LOG", log)

        result = sc.collect_feed_data(topic="Heartbeat")
        assert result["total"] == 1
        assert result["messages"][0]["topic"] == "Heartbeat"

    def test_limit(self, tmp_path, monkeypatch):
        log = tmp_path / "messages.jsonl"
        entries = [{"topic": "T", "text": str(i), "timestamp": f"2026-03-16T{i:02d}:00:00+00:00"}
                   for i in range(20)]
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        monkeypatch.setattr(sc, "FEED_LOG", log)

        result = sc.collect_feed_data(limit=5)
        assert result["total"] == 5


# ── _collect_failing_jobs ──

class TestCollectFailingJobs:
    def test_no_failures(self):
        runs = [
            {"job_id": "heartbeat", "status": "completed"},
            {"job_id": "reflection", "status": "completed"},
        ]
        result = sc._collect_failing_jobs(runs, {"heartbeat", "reflection"})
        assert result == []

    def test_finds_failing_job(self):
        runs = [
            {"job_id": "heartbeat", "status": "completed"},
            {"job_id": "heartbeat", "error": "timeout", "timestamp": "2026-03-16T10:00:00"},
        ]
        result = sc._collect_failing_jobs(runs, {"heartbeat"})
        assert len(result) == 1
        assert result[0]["job_id"] == "heartbeat"
        assert result[0]["consecutive"] == 1

    def test_consecutive_failures(self):
        runs = [
            {"job_id": "heartbeat", "status": "completed"},
            {"job_id": "heartbeat", "error": "err1", "timestamp": "2026-03-16T10:00:00"},
            {"job_id": "heartbeat", "error": "err2", "timestamp": "2026-03-16T10:30:00"},
            {"job_id": "heartbeat", "error": "err3", "timestamp": "2026-03-16T11:00:00"},
        ]
        result = sc._collect_failing_jobs(runs, {"heartbeat"})
        assert result[0]["consecutive"] == 3

    def test_skips_inactive_jobs(self):
        runs = [
            {"job_id": "old-job", "error": "fail", "timestamp": "2026-03-16T10:00:00"},
        ]
        result = sc._collect_failing_jobs(runs, {"heartbeat"})  # old-job not in active
        assert result == []

    def test_skips_system_jobs(self):
        runs = [
            {"job_id": "_healthcheck", "error": "fail", "timestamp": "2026-03-16T10:00:00"},
        ]
        result = sc._collect_failing_jobs(runs, {"_healthcheck"})
        assert result == []


# ── _extract_note_preview ──

class TestExtractNotePreview:
    def test_extracts_frontmatter_keys(self, tmp_path):
        f = tmp_path / "Note.md"
        f.write_text("---\ncompany: Acme\nrole: CTO\ntags: [tech]\nrandom: ignored\n---\n\n## Background\n## Deals\n")
        result = sc._extract_note_preview(f)
        assert "company: Acme" in result
        assert "role: CTO" in result
        assert "tags: [tech]" in result
        assert "random" not in result  # not in keep_keys

    def test_extracts_sections(self, tmp_path):
        f = tmp_path / "Note.md"
        f.write_text("---\ncompany: X\n---\n\n## Background\nSome info\n## Deals\nDeal info")
        result = sc._extract_note_preview(f)
        assert "## Background" in result
        assert "## Deals" in result

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "Note.md"
        f.write_text("## Section\nJust content")
        result = sc._extract_note_preview(f)
        assert "## Section" in result

    def test_missing_file(self, tmp_path):
        result = sc._extract_note_preview(tmp_path / "missing.md")
        assert result == ""


# ── _extract_skill_preview ──

class TestExtractSkillPreview:
    def test_extracts_description(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: A useful skill\nuser_invocable: true\n---\n\n# Usage")
        (skill_dir / "helper.py").write_text("# code")

        result = sc._extract_skill_preview(skill_dir)
        assert "description: A useful skill" in result
        assert "SKILL.md" in result
        assert "helper.py" in result

    def test_no_description(self, tmp_path):
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nuser_invocable: true\n---\n")
        result = sc._extract_skill_preview(skill_dir)
        assert isinstance(result, str)

    def test_missing_skill_file(self, tmp_path):
        result = sc._extract_skill_preview(tmp_path / "nonexistent")
        assert result == ""


# ── collect_files_data ──

class TestCollectFilesData:
    @pytest.fixture(autouse=True)
    def _clear_files_cache(self):
        if hasattr(sc, "_files_cache"):
            sc._files_cache["data"] = None
            sc._files_cache["ts"] = 0

    def test_with_daily_notes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        # Create memory dir with daily note
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("# Today\nSome notes")

        # Create CLAUDE.md
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# CLAUDE.md\nInstructions")

        result = sc.collect_files_data()
        assert result["claude_md"]["lines"] == 2
        assert today in result["daily_notes"]
        assert result["daily_notes"][today]["exists"] is True

    def test_specific_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "2026-03-15.md").write_text("# Yesterday\nNotes")

        result = sc.collect_files_data(date="2026-03-15")
        assert "2026-03-15" in result["daily_notes"]
        assert result["daily_notes"]["2026-03-15"]["exists"] is True

    def test_missing_daily_note(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        (tmp_path / "memory").mkdir()
        (tmp_path / ".claude").mkdir()

        result = sc.collect_files_data(date="2020-01-01")
        assert result["daily_notes"]["2020-01-01"]["exists"] is False

    def test_available_dates(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (tmp_path / ".claude").mkdir()
        for d in ["2026-03-14", "2026-03-15", "2026-03-16"]:
            (memory_dir / f"{d}.md").write_text(f"# {d}")

        result = sc.collect_files_data()
        assert len(result["available_dates"]) == 3


# ── collect_pipelines_data ──

class TestCollectPipelinesData:
    def test_no_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "PIPELINES_DIR", tmp_path / "p")
        monkeypatch.setattr(sc, "PIPELINE_STATE_DIR", tmp_path / "s")
        monkeypatch.setattr(sc, "PIPELINE_COMPLETED_DIR", tmp_path / "c")

        result = sc.collect_pipelines_data()
        assert result["stats"]["definition_count"] == 0
        assert result["stats"]["active_count"] == 0

    def test_reads_definitions(self, tmp_path, monkeypatch):
        import yaml
        pipelines_dir = tmp_path / "pipelines"
        pipelines_dir.mkdir()
        monkeypatch.setattr(sc, "PIPELINES_DIR", pipelines_dir)
        monkeypatch.setattr(sc, "PIPELINE_STATE_DIR", tmp_path / "s")
        monkeypatch.setattr(sc, "PIPELINE_COMPLETED_DIR", tmp_path / "c")

        pdef = {
            "name": "test-pipeline",
            "description": "A test",
            "settings": {"initial_state": "plan", "max_retries": 3},
            "states": {
                "plan": {"description": "Planning"},
                "execute": {"description": "Running"},
                "done": {"description": "Done", "terminal": True},
            },
            "transitions": [
                {"from": "plan", "to": "execute"},
                {"from": "execute", "to": "done"},
            ],
        }
        (pipelines_dir / "test-pipeline.yaml").write_text(yaml.dump(pdef))

        result = sc.collect_pipelines_data()
        assert result["stats"]["definition_count"] == 1
        defn = result["definitions"][0]
        assert defn["name"] == "test-pipeline"
        assert "plan" in defn["states"]
        assert defn["terminal_states"] == ["done"]
        assert defn["transition_count"] == 2

    def test_reads_active_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "PIPELINES_DIR", tmp_path / "p")
        state_dir = tmp_path / "sessions"
        state_dir.mkdir()
        monkeypatch.setattr(sc, "PIPELINE_STATE_DIR", state_dir)
        monkeypatch.setattr(sc, "PIPELINE_COMPLETED_DIR", tmp_path / "c")

        now = datetime.now(timezone.utc)
        state = {
            "session_id": "test-sess-12345678",
            "pipeline": "test-pipeline",
            "instance_id": "inst-1",
            "current_state": "execute",
            "started_at": (now - timedelta(minutes=5)).isoformat(),
            "state_entered_at": (now - timedelta(minutes=2)).isoformat(),
            "retry_count": 1,
            "history": [{"state": "plan"}, {"state": "execute"}],
        }
        (state_dir / "test.json").write_text(json.dumps(state))

        result = sc.collect_pipelines_data()
        assert result["stats"]["active_count"] == 1
        active = result["active"][0]
        assert active["current_state"] == "execute"
        assert active["retry_count"] == 1


# ── collect_heartbeat_data ──

class TestCollectHeartbeatData:
    @pytest.fixture(autouse=True)
    def _clear(self):
        if hasattr(sc, "_hb_cache"):
            sc._hb_cache["data"] = None
            sc._hb_cache["ts"] = 0

    def test_empty_runs(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        (cron_dir / "runs.jsonl").write_text("")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        result = sc.collect_heartbeat_data()
        assert result["kpis"]["runs_today"] == 0
        assert result["runs"] == []

    def test_no_runs_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        result = sc.collect_heartbeat_data()
        assert result["kpis"]["runs_today"] == 0

    def test_parses_heartbeat_runs(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {
                "job_id": "heartbeat",
                "status": "completed",
                "timestamp": f"{today}T10:00:00+00:00",
                "output": "HEARTBEAT_OK",
                "duration_seconds": 30,
            },
            {
                "job_id": "heartbeat",
                "status": "completed",
                "timestamp": f"{today}T10:30:00+00:00",
                "output": "Created task for user\nUpdated deal notes",
                "duration_seconds": 45,
            },
        ]
        (cron_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs) + "\n")

        result = sc.collect_heartbeat_data()
        assert result["kpis"]["runs_today"] == 2
        assert result["kpis"]["acted_today"] == 1  # second run has actions
        assert result["kpis"]["idle_today"] == 1   # first run is HEARTBEAT_OK

    def test_failed_runs(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {
                "job_id": "heartbeat",
                "status": "failed",
                "timestamp": f"{today}T10:00:00+00:00",
                "error": "timeout",
                "duration_seconds": 300,
            },
        ]
        (cron_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")

        result = sc.collect_heartbeat_data()
        assert result["kpis"]["failed_today"] == 1

    def test_deltas_parsing(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {
                "job_id": "heartbeat",
                "status": "completed",
                "timestamp": f"{today}T10:00:00+00:00",
                "output": "Did stuff",
                "deltas": [
                    {"type": "gtask_create", "title": "Follow up"},
                    {"type": "obsidian", "path": "People/John.md"},
                    {"type": "skipped", "count": 5},
                ],
                "duration_seconds": 30,
            },
        ]
        (cron_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")

        result = sc.collect_heartbeat_data()
        assert result["today_deltas"]["skipped"] == 5
        assert "gtask" in result["today_deltas"]

    def test_intake_structured(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {
                "job_id": "heartbeat",
                "status": "completed",
                "timestamp": f"{today}T10:00:00+00:00",
                "output": "HEARTBEAT_OK",
                "intake": {
                    "total_new": 15,
                    "stats": {"telegram": 10, "signal": 5},
                    "details": {"telegram": {"Acme HQ": 5, "Main": 5}, "signal": {"Inner Circle": 5}},
                },
                "duration_seconds": 20,
            },
        ]
        (cron_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")

        result = sc.collect_heartbeat_data()
        run = result["runs"][0]
        assert "15 msgs" in run["intake"]
        assert run["intake_details"] is not None

    def test_intake_old_format(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {
                "job_id": "heartbeat",
                "status": "completed",
                "timestamp": f"{today}T10:00:00+00:00",
                "output": "INTAKE: telegram=10, signal=5 (15 total new)\nHEARTBEAT_OK",
                "duration_seconds": 20,
            },
        ]
        (cron_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")

        result = sc.collect_heartbeat_data()
        run = result["runs"][0]
        assert "telegram" in run["intake"]

    def test_deltas_in_output(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {
                "job_id": "heartbeat",
                "status": "completed",
                "timestamp": f"{today}T10:00:00+00:00",
                "output": 'Action taken---DELTAS---[{"type":"gtask_create","title":"test"}]',
                "duration_seconds": 30,
            },
        ]
        (cron_dir / "runs.jsonl").write_text(json.dumps(runs[0]) + "\n")

        result = sc.collect_heartbeat_data()
        run = result["runs"][0]
        assert "---DELTAS---" not in run["output"]  # stripped
        assert run["deltas"] == [{"type": "gtask_create", "title": "test"}]

    def test_job_stats(self, tmp_path, monkeypatch):
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        runs = [
            {"job_id": "heartbeat", "status": "completed", "timestamp": f"{today}T{h:02d}:00:00+00:00",
             "output": "HEARTBEAT_OK", "duration_seconds": 20}
            for h in range(8, 13)
        ]
        (cron_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs) + "\n")

        result = sc.collect_heartbeat_data()
        assert "heartbeat" in result["job_stats"]
        assert result["job_stats"]["heartbeat"]["today"] == 5
        assert result["job_stats"]["heartbeat"]["avg_duration"] == 20

    def test_has_consumer_sources(self, tmp_path, monkeypatch):
        """Consumer sources reads from hardcoded Path.home() - just verify key exists."""
        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        (cron_dir / "runs.jsonl").write_text("")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)

        result = sc.collect_heartbeat_data()
        assert "consumer_sources" in result  # key always present


# ── _collect_skill_inventory ──

class TestCollectSkillInventory:
    def test_no_skills_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "nope")
        result = sc._collect_skill_inventory()
        assert result == []

    def test_finds_skills(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        # Create a skill
        s1 = skills_dir / "heartbeat"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\ndescription: Intake pipeline\nuser_invocable: true\n---\n\n# Heartbeat")

        s2 = skills_dir / "memory"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("---\ndescription: Memory sync\nuser_invocable: false\n---\n")

        # Mock subprocess-dependent functions
        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        assert len(result) == 2
        names = [s["name"] for s in result]
        assert "heartbeat" in names
        assert "memory" in names

        hb = next(s for s in result if s["name"] == "heartbeat")
        assert hb["description"] == "Intake pipeline"
        assert hb["user_invocable"] is True

    def test_with_errors_file(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        s1 = skills_dir / "broken-skill"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\ndescription: Broken\n---\n")
        (s1 / "errors.jsonl").write_text('{"err": "fail1"}\n{"err": "fail2"}\n')

        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        assert result[0]["error_count"] == 2

    def test_skips_non_dirs(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        # Create a regular file (not a skill dir)
        (skills_dir / "README.md").write_text("# Skills")

        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        assert result == []

    def test_skips_missing_skill_md(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        # Dir without SKILL.md
        empty = skills_dir / "empty-dir"
        empty.mkdir()

        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        assert result == []

    def test_scenario_counting(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)

        s1 = skills_dir / "heartbeat"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\ndescription: HB\n---\n")

        # Scenarios dir with matching scenarios
        scenarios = skills_dir / "scenarios"
        scenarios.mkdir()
        (scenarios / "heartbeat-basic").mkdir()
        (scenarios / "heartbeat-error").mkdir()
        (scenarios / "memory-test").mkdir()  # different skill

        with patch.object(sc, "_collect_skill_call_stats", return_value={}), \
             patch.object(sc, "_collect_skill_git_history", return_value={}):
            result = sc._collect_skill_inventory()

        hb = result[0]
        assert hb["scenario_count"] == 2  # heartbeat-basic and heartbeat-error


# ── _collect_agent_activity ──

class TestCollectAgentActivity:
    def test_empty_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "returncode": 0})()
            result = sc._collect_agent_activity()
        assert isinstance(result, list)

    def test_git_commits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        commit_line = "abc123|fix tests|2026-03-16 10:00:00 +0000"
        mock_main = type("R", (), {"stdout": commit_line, "returncode": 0})()
        mock_stat = type("R", (), {"stdout": " 2 files changed", "returncode": 0})()
        with patch("subprocess.run", side_effect=[mock_main, mock_stat]):
            result = sc._collect_agent_activity()
        git_items = [i for i in result if i["type"] == "git_commit"]
        assert len(git_items) == 1
        assert git_items[0]["summary"] == "fix tests"

    def test_recent_obsidian_notes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        people_dir = tmp_path / "Documents" / "MyBrain" / "People"
        people_dir.mkdir(parents=True)
        note = people_dir / "Jane Doe.md"
        note.write_text("---\ncompany: Acme\n---\n\n## Background\nSmart person")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "returncode": 0})()
            result = sc._collect_agent_activity()
        person_items = [i for i in result if i["type"] == "person"]
        assert len(person_items) == 1
        assert person_items[0]["summary"] == "Jane Doe"

    def test_recent_skills(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\ndescription: A skill\n---\n\n## How\nDo stuff")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "returncode": 0})()
            result = sc._collect_agent_activity()
        skill_items = [i for i in result if i["type"] == "skill"]
        assert len(skill_items) == 1
        assert skill_items[0]["summary"] == "my-skill"

    def test_daily_notes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (memory_dir / f"{today}.md").write_text("# Today\nDid some stuff\nMore things")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "returncode": 0})()
            result = sc._collect_agent_activity()
        note_items = [i for i in result if i["type"] == "daily_note"]
        assert len(note_items) == 1
        assert "3 lines" in note_items[0]["summary"]


# ── _collect_tool_calls ──

class TestCollectToolCalls:
    def test_no_log_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_tool_calls()
        assert result["sessions"] == []
        assert result["total_24h"] == 0

    def test_parses_records(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        log_dir = tmp_path / ".claude" / "logs"
        log_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        records = [
            {"ts": now.isoformat(), "tool": "Read", "sid": "s1", "ok": True, "summary": "read file"},
            {"ts": now.isoformat(), "tool": "Write", "sid": "s1", "ok": True, "summary": "wrote file"},
            {"ts": now.isoformat(), "tool": "Bash", "sid": "s2", "ok": False, "summary": "error"},
        ]
        with open(log_dir / "tool-calls.jsonl", "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        # Mock subprocess.run (tail command)
        tail_output = "\n".join(json.dumps(r) for r in records)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": tail_output, "returncode": 0})()
            result = sc._collect_tool_calls()
        assert result["total_24h"] == 3
        assert "Read" in result["by_tool"]
        assert result["by_tool"]["Read"] == 1
        assert len(result["sessions"]) == 2
        assert len(result["recent"]) == 3

    def test_groups_by_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        log_dir = tmp_path / ".claude" / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "tool-calls.jsonl").write_text("")  # just needs to exist
        now = datetime.now(timezone.utc)
        records = [
            {"ts": now.isoformat(), "tool": "Read", "sid": "s1", "ok": True},
            {"ts": now.isoformat(), "tool": "Read", "sid": "s1", "ok": True},
            {"ts": now.isoformat(), "tool": "Bash", "sid": "s1", "ok": True},
        ]
        tail_output = "\n".join(json.dumps(r) for r in records)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": tail_output, "returncode": 0})()
            result = sc._collect_tool_calls()
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["count"] == 3
        assert "2x Read" in result["sessions"][0]["tools_summary"]


# ── _collect_reply_queue ──

class TestCollectReplyQueue:
    def test_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "VADIMGEST_DIR", tmp_path / "vadimgest")
        result = sc._collect_reply_queue()
        assert result["items"] == []
        assert result["total"] == 0

    def test_parses_tasks(self, tmp_path, monkeypatch):
        vg_dir = tmp_path / "vadimgest"
        sources_dir = vg_dir / "data" / "sources"
        sources_dir.mkdir(parents=True)
        tasks = [
            {"id": "t1", "title": "[SIG] Reply to Alex about pricing", "status": "needsAction", "due": "2026-03-15T00:00:00Z"},
            {"id": "t2", "title": "[DEAL] Follow up AcmeCorp", "status": "needsAction", "due": "2026-03-20T00:00:00Z"},
            {"id": "t3", "title": "Random task", "status": "completed"},
        ]
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)
        with open(sources_dir / "gtasks.jsonl", "w") as f:
            for t in tasks:
                f.write(json.dumps(t) + "\n")
        result = sc._collect_reply_queue()
        assert result["total"] == 2  # completed task excluded
        assert result["by_type"]["signal"] == 1
        assert result["by_type"]["deal"] == 1
        # Check overdue detection
        overdue_items = [i for i in result["items"] if i["overdue"]]
        assert len(overdue_items) >= 1  # sig task is overdue (2026-03-15 < 2026-03-16)

    def test_deduplicates(self, tmp_path, monkeypatch):
        vg_dir = tmp_path / "vadimgest"
        sources_dir = vg_dir / "data" / "sources"
        sources_dir.mkdir(parents=True)
        # Same task ID appears twice, last one wins
        tasks = [
            {"id": "t1", "title": "Old title", "status": "needsAction"},
            {"id": "t1", "title": "New title", "status": "completed"},
        ]
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)
        with open(sources_dir / "gtasks.jsonl", "w") as f:
            for t in tasks:
                f.write(json.dumps(t) + "\n")
        result = sc._collect_reply_queue()
        assert result["total"] == 0  # last occurrence is completed

    def test_sorts_overdue_first(self, tmp_path, monkeypatch):
        vg_dir = tmp_path / "vadimgest"
        sources_dir = vg_dir / "data" / "sources"
        sources_dir.mkdir(parents=True)
        tasks = [
            {"id": "t1", "title": "[DEAL] Future deal", "status": "needsAction", "due": "2030-01-01T00:00:00Z"},
            {"id": "t2", "title": "[SIG] Overdue signal", "status": "needsAction", "due": "2020-01-01T00:00:00Z"},
        ]
        monkeypatch.setattr(sc, "VADIMGEST_DIR", vg_dir)
        with open(sources_dir / "gtasks.jsonl", "w") as f:
            for t in tasks:
                f.write(json.dumps(t) + "\n")
        result = sc._collect_reply_queue()
        assert result["items"][0]["overdue"] is True  # overdue first
        assert result["items"][1]["overdue"] is False


# ── _collect_services ──

class TestCollectServices:
    def test_no_launch_agents(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = sc._collect_services()
        assert result == []

    def test_discovers_services(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        launch_dir = tmp_path / "Library" / "LaunchAgents"
        launch_dir.mkdir(parents=True)
        # Create a plist file (minimal)
        import plistlib
        plist_data = {"Label": "com.local.test-service", "ProgramArguments": ["/usr/bin/true"]}
        with open(launch_dir / "com.local.test-service.plist", "wb") as f:
            plistlib.dump(plist_data, f)

        launchctl_output = "12345\t0\tcom.local.test-service\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": launchctl_output, "returncode": 0})()
            result = sc._collect_services()

        assert len(result) == 1
        assert result[0]["running"] is True
        assert result[0]["pid"] == "12345"
        assert "Test Service" in result[0]["name"]

    def test_service_not_running(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        launch_dir = tmp_path / "Library" / "LaunchAgents"
        launch_dir.mkdir(parents=True)
        import plistlib
        plist_data = {"Label": "com.local.offline", "ProgramArguments": ["/usr/bin/false"]}
        with open(launch_dir / "com.local.offline.plist", "wb") as f:
            plistlib.dump(plist_data, f)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "returncode": 0})()
            result = sc._collect_services()

        assert len(result) == 1
        assert result[0]["running"] is False

    def test_periodic_service_healthy(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        launch_dir = tmp_path / "Library" / "LaunchAgents"
        launch_dir.mkdir(parents=True)
        import plistlib
        plist_data = {"Label": "com.local.cron-watchdog", "ProgramArguments": ["/usr/bin/true"],
                      "StartInterval": 300}
        with open(launch_dir / "com.local.cron-watchdog.plist", "wb") as f:
            plistlib.dump(plist_data, f)

        launchctl_output = "-\t0\tcom.local.cron-watchdog\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": launchctl_output, "returncode": 0})()
            result = sc._collect_services()

        assert len(result) == 1
        assert result[0]["running"] is True  # periodic with exit 0 = healthy
        assert result[0]["pid"] == "periodic"


# ── _collect_obsidian_events ──

class TestCollectObsidianEvents:
    def test_empty_vault(self, tmp_path, monkeypatch):
        """No People/ or Organizations/ dirs -> empty list."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        result = sc._collect_obsidian_events()
        assert result == []

    def test_recent_people_notes(self, tmp_path, monkeypatch):
        """People notes created recently should appear as events."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        # Create some .md files (their birthtime will be "now")
        (people_dir / "Alice Smith.md").write_text("# Alice")
        (people_dir / "Bob Jones.md").write_text("# Bob")
        # Non-md file should be ignored
        (people_dir / "notes.txt").write_text("ignore")

        result = sc._collect_obsidian_events()
        assert len(result) == 1  # grouped by day
        ev = result[0]
        assert ev["category"] == "knowledge"
        assert ev["files_changed"] == 2
        assert "hash" in ev
        assert ev["details"]["note_type"] == "people"
        names = ev["details"]["notes"]
        assert "Alice Smith" in names
        assert "Bob Jones" in names

    def test_recent_orgs_notes(self, tmp_path, monkeypatch):
        """Organizations notes show up with type 'organizations'."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        org_dir = tmp_path / "Organizations"
        org_dir.mkdir()
        (org_dir / "Acme Corp.md").write_text("# Acme")

        result = sc._collect_obsidian_events()
        assert len(result) == 1
        assert result[0]["details"]["note_type"] == "organizations"
        assert result[0]["files_changed"] == 1

    def test_both_people_and_orgs(self, tmp_path, monkeypatch):
        """Both People and Organizations are collected."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        (tmp_path / "People").mkdir()
        (tmp_path / "People" / "Person.md").write_text("# P")
        (tmp_path / "Organizations").mkdir()
        (tmp_path / "Organizations" / "Org.md").write_text("# O")

        result = sc._collect_obsidian_events()
        assert len(result) == 2
        types = {ev["details"]["note_type"] for ev in result}
        assert types == {"people", "organizations"}

    def test_more_than_three_notes_shows_count(self, tmp_path, monkeypatch):
        """When >3 notes on one day, message shows count and top 3."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        for i in range(5):
            (people_dir / f"Person{i}.md").write_text(f"# P{i}")

        result = sc._collect_obsidian_events()
        assert len(result) == 1
        assert result[0]["files_changed"] == 5
        # Message should mention "5 new People notes"
        assert "5 new" in result[0]["message"] or "..." in result[0]["message"]

    def test_three_or_fewer_notes_lists_names(self, tmp_path, monkeypatch):
        """When <=3 notes, message lists all names."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        (people_dir / "Alice.md").write_text("# A")
        (people_dir / "Bob.md").write_text("# B")

        result = sc._collect_obsidian_events()
        assert len(result) == 1
        assert "Created" in result[0]["message"]


# ── _collect_evolution_timeline ──

class TestCollectEvolutionTimeline:
    def test_git_failure_returns_empty(self, monkeypatch):
        """When git command fails, returns empty list."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", Path("/nonexistent"))
        sc._evolution_cache["data"] = None
        sc._evolution_cache["ts"] = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 1, "stdout": "", "stderr": ""
            })()
            result = sc._collect_evolution_timeline()

        assert result == []

    def test_cache_hit(self, monkeypatch):
        """Cached data is returned within TTL."""
        sc._evolution_cache["data"] = [{"hash": "cached"}]
        sc._evolution_cache["ts"] = time.time()

        result = sc._collect_evolution_timeline()
        assert result == [{"hash": "cached"}]

    def test_filters_noise_commits(self, tmp_path, monkeypatch):
        """Commits with 'heartbeat: daily notes' are filtered out."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)  # empty vault
        sc._evolution_cache["data"] = None
        sc._evolution_cache["ts"] = 0

        git_log_output = (
            "abc123def456789012345678901234567890abcd|2026-03-15 10:00:00 +0200|heartbeat: daily notes update\n"
            "def456abc78901234567890123456789abcdef01|2026-03-15 09:00:00 +0200|fix: dashboard layout\n"
        )
        # Second call for diff-tree (stat for the non-noise commit)
        stat_output = "5\t2\tgateway/lib/status_collector.py\n"

        call_count = [0]

        def mock_subprocess_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            call_count[0] += 1
            if cmd[1] == "log":
                return type("R", (), {
                    "returncode": 0, "stdout": git_log_output, "stderr": ""
                })()
            elif cmd[1] == "diff-tree":
                return type("R", (), {
                    "returncode": 0, "stdout": stat_output, "stderr": ""
                })()
            elif cmd[1] == "diff":
                return type("R", (), {
                    "returncode": 0, "stdout": "", "stderr": ""
                })()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            result = sc._collect_evolution_timeline()

        # Only the "fix" commit should appear (noise filtered)
        commit_messages = [e["message"] for e in result if "hash" in e and len(e.get("hash", "")) == 8]
        assert "heartbeat: daily notes update" not in commit_messages
        assert any("fix: dashboard layout" in m for m in commit_messages)

    def test_filters_memory_only_commits(self, tmp_path, monkeypatch):
        """Commits that ONLY touch memory/*.md are filtered out."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        sc._evolution_cache["data"] = None
        sc._evolution_cache["ts"] = 0

        git_log_output = "aaa123def456789012345678901234567890abcd|2026-03-15 10:00:00 +0200|add daily context\n"
        stat_output = "10\t0\tmemory/2026-03-15.md\n"

        def mock_run(*args, **kwargs):
            cmd = args[0]
            if cmd[1] == "log":
                return type("R", (), {"returncode": 0, "stdout": git_log_output, "stderr": ""})()
            elif cmd[1] == "diff-tree":
                return type("R", (), {"returncode": 0, "stdout": stat_output, "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("subprocess.run", side_effect=mock_run):
            result = sc._collect_evolution_timeline()

        # Memory-only commit should be filtered
        commit_messages = [e["message"] for e in result if len(e.get("hash", "")) == 8]
        assert "add daily context" not in commit_messages

    def test_includes_obsidian_events(self, tmp_path, monkeypatch):
        """Obsidian events are merged into the timeline."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        sc._evolution_cache["data"] = None
        sc._evolution_cache["ts"] = 0
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        (people_dir / "Test Person.md").write_text("# Test")

        with patch("subprocess.run") as mock_run:
            # Git log succeeds but returns empty output so we fall through to obsidian merge
            mock_run.return_value = type("R", (), {
                "returncode": 0, "stdout": "\n", "stderr": ""
            })()
            result = sc._collect_evolution_timeline()

        # Should contain obsidian event
        assert len(result) >= 1
        assert any(e["category"] == "knowledge" for e in result)


# ── _collect_growth_metrics ──

class TestCollectGrowthMetrics:
    def test_empty_dirs(self, tmp_path, monkeypatch):
        """All empty directories -> zero counts."""
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        sc._growth_cache["data"] = None
        sc._growth_cache["ts"] = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 1, "stdout": "", "stderr": ""
            })()
            result = sc._collect_growth_metrics()

        assert result["skills"]["current"] == 0
        assert result["claude_md_lines"]["current"] == 0

    def test_counts_skills(self, tmp_path, monkeypatch):
        """Skills with SKILL.md are counted."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "foo").mkdir()
        (skills_dir / "foo" / "SKILL.md").write_text("# Foo skill")
        (skills_dir / "bar").mkdir()
        (skills_dir / "bar" / "SKILL.md").write_text("# Bar skill")
        (skills_dir / "baz").mkdir()  # no SKILL.md -> not counted

        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        sc._growth_cache["data"] = None
        sc._growth_cache["ts"] = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 1, "stdout": "", "stderr": ""
            })()
            result = sc._collect_growth_metrics()

        assert result["skills"]["current"] == 2

    def test_counts_claude_md_lines(self, tmp_path, monkeypatch):
        """CLAUDE.md line count is captured."""
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("line1\nline2\nline3\n")
        sc._growth_cache["data"] = None
        sc._growth_cache["ts"] = 0

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 1, "stdout": "", "stderr": ""
            })()
            result = sc._collect_growth_metrics()

        assert result["claude_md_lines"]["current"] == 4  # 3 lines + trailing newline split

    def test_cache_hit(self):
        """Cached data is returned within TTL."""
        sc._growth_cache["data"] = {"cached": True}
        sc._growth_cache["ts"] = time.time()

        result = sc._collect_growth_metrics()
        assert result == {"cached": True}

    def test_historical_git_data(self, tmp_path, monkeypatch):
        """Git history is parsed for historical data points."""
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        sc._growth_cache["data"] = None
        sc._growth_cache["ts"] = 0

        call_idx = [0]

        def mock_run(*args, **kwargs):
            cmd = args[0]
            call_idx[0] += 1
            if cmd[1] == "log" and "--reverse" in cmd:
                # Return two dates
                return type("R", (), {
                    "returncode": 0,
                    "stdout": "2026-01-01 00:00:00 +0000\n2026-03-15 00:00:00 +0000\n",
                    "stderr": ""
                })()
            elif cmd[1] == "log" and "--before=" in str(cmd):
                return type("R", (), {
                    "returncode": 0,
                    "stdout": "abc123\n",
                    "stderr": ""
                })()
            elif cmd[1] == "ls-tree":
                return type("R", (), {
                    "returncode": 0,
                    "stdout": ".claude/skills/foo\n.claude/skills/bar\n",
                    "stderr": ""
                })()
            elif cmd[1] == "show":
                return type("R", (), {
                    "returncode": 0,
                    "stdout": "line1\nline2\nline3\n",
                    "stderr": ""
                })()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        with patch("subprocess.run", side_effect=mock_run):
            result = sc._collect_growth_metrics()

        # Should have historical series data
        assert len(result["skills"]["series"]) > 0
        assert len(result["claude_md_lines"]["series"]) > 0


# ── _collect_daily_notes_status ──

class TestCollectDailyNotesStatus:
    def test_no_memory_dir(self, tmp_path, monkeypatch):
        """No memory/ directory -> today/yesterday don't exist."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_daily_notes_status()
        assert result["today"]["exists"] is False
        assert result["yesterday"]["exists"] is False
        assert result["week_notes"] == []

    def test_today_note_exists(self, tmp_path, monkeypatch):
        """Today's note is found and analyzed."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (mem_dir / f"{today}.md").write_text(
            "## Morning\nSome entry at 09:30\n\n### Task review\nDid stuff at 14:15\n"
        )

        result = sc._collect_daily_notes_status()
        assert result["today"]["exists"] is True
        assert result["today"]["lines"] > 0
        assert result["today"]["entries"] == 2  # ## Morning + ### Task review
        assert result["today"]["last_entry_time"] == "14:15"

    def test_yesterday_note_exists(self, tmp_path, monkeypatch):
        """Yesterday's note is found."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        (mem_dir / f"{yesterday}.md").write_text("## Evening summary\nWrap up\n")

        result = sc._collect_daily_notes_status()
        assert result["yesterday"]["exists"] is True
        assert result["yesterday"]["entries"] == 1

    def test_week_notes_collected(self, tmp_path, monkeypatch):
        """Notes from the past 7 days appear in week_notes."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        now = datetime.now(timezone.utc)
        for i in range(3):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            (mem_dir / f"{date}.md").write_text(f"## Day {i}\nContent\n")

        result = sc._collect_daily_notes_status()
        assert len(result["week_notes"]) == 3
        for note in result["week_notes"]:
            assert "date" in note
            assert note["lines"] > 0


# ── _collect_mcp_servers ──

class TestCollectMcpServers:
    def test_no_settings_file(self, tmp_path, monkeypatch):
        """No settings.json -> empty list."""
        monkeypatch.setattr(sc, "SETTINGS_FILE", tmp_path / "settings.json")
        result = sc._collect_mcp_servers()
        assert result == []

    def test_parses_servers(self, tmp_path, monkeypatch):
        """MCP servers are parsed from settings.json."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "mcpServers": {
                "browser": {
                    "command": "npx",
                    "args": ["-y", "@anthropic/browser-mcp"]
                },
                "postgres": {
                    "command": "uvx",
                    "args": ["mcp-postgres", "postgresql://localhost/db"]
                }
            },
            "permissions": {
                "allow": [
                    "mcp__browser__navigate",
                    "mcp__browser__read_page",
                    "mcp__postgres__query",
                ]
            }
        }))
        monkeypatch.setattr(sc, "SETTINGS_FILE", settings_file)

        result = sc._collect_mcp_servers()
        assert len(result) == 2
        names = {s["name"] for s in result}
        assert names == {"browser", "postgres"}

        browser = next(s for s in result if s["name"] == "browser")
        assert browser["tool_count"] == 2  # navigate + read_page
        assert browser["command"] == "npx @anthropic/browser-mcp"  # first non-flag arg

        postgres = next(s for s in result if s["name"] == "postgres")
        assert postgres["tool_count"] == 1

    def test_server_no_args(self, tmp_path, monkeypatch):
        """Server with no args shows just command."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "mcpServers": {
                "simple": {"command": "my-server"}
            },
            "permissions": {"allow": []}
        }))
        monkeypatch.setattr(sc, "SETTINGS_FILE", settings_file)

        result = sc._collect_mcp_servers()
        assert len(result) == 1
        assert result[0]["command"] == "my-server"
        assert result[0]["tool_count"] == 0

    def test_server_only_flag_args(self, tmp_path, monkeypatch):
        """Server with only flag args shows just command."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "mcpServers": {
                "flagged": {"command": "server", "args": ["--verbose", "--port"]}
            },
            "permissions": {"allow": []}
        }))
        monkeypatch.setattr(sc, "SETTINGS_FILE", settings_file)

        result = sc._collect_mcp_servers()
        assert len(result) == 1
        assert result[0]["command"] == "server"


# ── _collect_skill_changes ──

class TestCollectSkillChanges:
    def test_git_failure_returns_empty(self):
        """When git command fails, returns empty list."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 1, "stdout": "", "stderr": ""
            })()
            result = sc._collect_skill_changes()
        assert result == []

    def test_empty_output(self):
        """No skill commits -> empty list."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 0, "stdout": "", "stderr": ""
            })()
            result = sc._collect_skill_changes()
        assert result == []

    def test_parses_git_stat_output(self):
        """Parses git log --stat output correctly."""
        git_output = (
            "abc123456789012345678901234567890123abcd|2026-03-15 10:00:00 +0200|create skill: vox-crm\n"
            " .claude/skills/vox-crm/SKILL.md | 50 +\n"
            " 1 file changed, 50 insertions(+)\n"
        )

        call_count = [0]

        def mock_run(*args, **kwargs):
            cmd = args[0]
            call_count[0] += 1
            if cmd[1] == "log":
                return type("R", (), {"returncode": 0, "stdout": git_output, "stderr": ""})()
            elif cmd[1] == "show":
                # diff preview fetch
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("subprocess.run", side_effect=mock_run):
            result = sc._collect_skill_changes()

        assert len(result) == 1
        assert result[0]["hash"] == "abc123456789012345678901234567890123abcd"
        assert result[0]["message"] == "create skill: vox-crm"
        assert result[0]["files_changed"] == 1
        assert result[0]["insertions"] == 50
        assert ".claude/skills/vox-crm/SKILL.md" in result[0]["files"]

    def test_multiple_commits(self):
        """Multiple commits are parsed."""
        git_output = (
            "aaaa23456789012345678901234567890123abcd|2026-03-15 10:00:00 +0200|update skill: foo\n"
            " .claude/skills/foo/SKILL.md | 10 +\n"
            " 1 file changed, 10 insertions(+)\n"
            "bbbb23456789012345678901234567890123abcd|2026-03-14 09:00:00 +0200|add skill: bar\n"
            " .claude/skills/bar/SKILL.md | 30 +\n"
            " .claude/skills/bar/run.py   | 20 +\n"
            " 2 files changed, 50 insertions(+)\n"
        )

        def mock_run(*args, **kwargs):
            cmd = args[0]
            if cmd[1] == "log":
                return type("R", (), {"returncode": 0, "stdout": git_output, "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("subprocess.run", side_effect=mock_run):
            result = sc._collect_skill_changes()

        assert len(result) == 2
        assert result[0]["message"] == "update skill: foo"
        assert result[1]["message"] == "add skill: bar"
        assert result[1]["files_changed"] == 2
        assert result[1]["insertions"] == 50

    def test_diff_preview_fetched(self):
        """Diff previews are fetched for each commit."""
        git_output = (
            "cccc23456789012345678901234567890123abcd|2026-03-15 10:00:00 +0200|skill update\n"
            " .claude/skills/test/SKILL.md | 5 +\n"
            " 1 file changed, 5 insertions(+)\n"
        )
        diff_output = (
            "diff --git a/.claude/skills/test/SKILL.md b/.claude/skills/test/SKILL.md\n"
            "+new line added\n"
            "-old line removed\n"
        )

        def mock_run(*args, **kwargs):
            cmd = args[0]
            if cmd[1] == "log":
                return type("R", (), {"returncode": 0, "stdout": git_output, "stderr": ""})()
            elif cmd[1] == "show":
                return type("R", (), {"returncode": 0, "stdout": diff_output, "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("subprocess.run", side_effect=mock_run):
            result = sc._collect_skill_changes()

        assert len(result) == 1
        assert "diff_preview" in result[0]
        assert "+new line added" in result[0]["diff_preview"]


# ── _collect_obsidian_metrics ──

class TestCollectObsidianMetrics:
    def test_nonexistent_vault(self, tmp_path, monkeypatch):
        """Nonexistent vault -> all zeros."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path / "nonexistent")
        result = sc._collect_obsidian_metrics()
        assert result["total_notes"] == 0
        assert result["people"] == 0
        assert result["organizations"] == 0

    def test_counts_notes(self, tmp_path, monkeypatch):
        """Counts total notes, people, organizations."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        (tmp_path / "People").mkdir()
        (tmp_path / "People" / "Alice.md").write_text("# Alice")
        (tmp_path / "People" / "Bob.md").write_text("# Bob")
        (tmp_path / "Organizations").mkdir()
        (tmp_path / "Organizations" / "Acme.md").write_text("# Acme")
        (tmp_path / "Notes.md").write_text("# Random")

        result = sc._collect_obsidian_metrics()
        assert result["total_notes"] == 4
        assert result["people"] == 2
        assert result["organizations"] == 1

    def test_ignores_hidden_dirs(self, tmp_path, monkeypatch):
        """Files in hidden directories (.obsidian, etc) are ignored."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        hidden = tmp_path / ".obsidian"
        hidden.mkdir()
        (hidden / "config.md").write_text("# config")
        (tmp_path / "Visible.md").write_text("# Visible")

        result = sc._collect_obsidian_metrics()
        assert result["total_notes"] == 1  # only Visible.md

    def test_modified_24h(self, tmp_path, monkeypatch):
        """Recently modified files are counted."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        (tmp_path / "Recent.md").write_text("# Recent")
        # The file was just created, so it's within 24h

        result = sc._collect_obsidian_metrics()
        assert result["modified_24h"] == 1

    def test_recent_files_list(self, tmp_path, monkeypatch):
        """Top 5 most recent files are returned."""
        monkeypatch.setattr(sc, "OBSIDIAN_DIR", tmp_path)
        subfolder = tmp_path / "Deals"
        subfolder.mkdir()
        for i in range(7):
            (subfolder / f"Deal{i}.md").write_text(f"# Deal {i}")

        result = sc._collect_obsidian_metrics()
        assert len(result["recent_files"]) == 5
        for rf in result["recent_files"]:
            assert "name" in rf
            assert rf["folder"] == "Deals"


# ── _collect_claude_md_details ──

class TestCollectClaudeMdDetails:
    def test_no_file(self, tmp_path, monkeypatch):
        """No CLAUDE.md -> defaults."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        result = sc._collect_claude_md_details()
        assert result["memory_lines"] == 0
        assert result["last_modified_ago"] == "never"
        assert result["recent_changes"] == []

    def test_counts_memory_section(self, tmp_path, monkeypatch):
        """Counts lines between <MEMORY> and </MEMORY> tags."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text(
            "# Main config\n"
            "Some stuff\n"
            "<MEMORY>\n"
            "Key fact 1\n"
            "Key fact 2\n"
            "Key fact 3\n"
            "</MEMORY>\n"
            "End\n"
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 0, "stdout": "", "stderr": ""
            })()
            result = sc._collect_claude_md_details()

        assert result["memory_lines"] == 3
        assert result["last_modified"] is not None

    def test_no_memory_section(self, tmp_path, monkeypatch):
        """File without <MEMORY> tags -> 0 memory lines."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Just a file\nNo memory here\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 0, "stdout": "", "stderr": ""
            })()
            result = sc._collect_claude_md_details()

        assert result["memory_lines"] == 0
        assert result["last_modified"] is not None

    def test_recent_changes_from_git(self, tmp_path, monkeypatch):
        """Recent git changes for CLAUDE.md are parsed."""
        monkeypatch.setattr(sc, "CLAUDE_DIR", tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("# Config\n")

        git_output = (
            "2026-03-15 10:00:00 +0200|update memory section\n"
            "2026-03-14 09:00:00 +0200|add new skill reference\n"
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {
                "returncode": 0, "stdout": git_output, "stderr": ""
            })()
            result = sc._collect_claude_md_details()

        assert len(result["recent_changes"]) == 2
        assert result["recent_changes"][0]["message"] == "update memory section"
        assert result["recent_changes"][1]["message"] == "add new skill reference"


# ── _safe_json_load ──

class TestSafeJsonLoad:
    def test_loads_valid_json(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        result = sc._safe_json_load(f)
        assert result == {"key": "value"}

    def test_returns_default_on_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all")
        result = sc._safe_json_load(f, default={"fallback": True})
        assert result == {"fallback": True}

    def test_raises_on_invalid_json_no_default(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        with pytest.raises((json.JSONDecodeError, ValueError)):
            sc._safe_json_load(f)

    def test_loads_list(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text('[1, 2, 3]')
        result = sc._safe_json_load(f)
        assert result == [1, 2, 3]


# ── _format_timedelta ──

class TestFormatTimedelta:
    def test_seconds(self):
        assert sc._format_timedelta(timedelta(seconds=30)) == "30s"

    def test_minutes(self):
        assert sc._format_timedelta(timedelta(minutes=5)) == "5m"

    def test_hours(self):
        assert sc._format_timedelta(timedelta(hours=3)) == "3h"

    def test_days(self):
        assert sc._format_timedelta(timedelta(days=2)) == "2d"

    def test_negative_timedelta(self):
        result = sc._format_timedelta(timedelta(seconds=-120))
        assert result == "in 2m"

    def test_zero_seconds(self):
        assert sc._format_timedelta(timedelta(seconds=0)) == "0s"

    def test_boundary_60_seconds(self):
        assert sc._format_timedelta(timedelta(seconds=60)) == "1m"

    def test_boundary_3600_seconds(self):
        assert sc._format_timedelta(timedelta(seconds=3600)) == "1h"


# ── _time_ago ──

class TestTimeAgo:
    def test_none_returns_never(self):
        assert sc._time_ago(None) == "never"

    def test_none_string_returns_never(self):
        assert sc._time_ago("None") == "never"

    def test_empty_string_returns_never(self):
        assert sc._time_ago("") == "never"

    def test_recent_timestamp(self):
        now = datetime.now(timezone.utc)
        result = sc._time_ago(now.isoformat())
        assert "s ago" in result or "just now" in result

    def test_invalid_format_returns_string(self):
        result = sc._time_ago("not-a-date")
        assert result == "not-a-date"

    def test_future_timestamp(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = sc._time_ago(future)
        assert result == "just now"

    def test_hours_ago(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        result = sc._time_ago(ts)
        assert "h ago" in result

    def test_days_ago(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        result = sc._time_ago(ts)
        assert "d ago" in result


# ── _calculate_next_run ──

class TestCalculateNextRun:
    def test_every_minutes(self):
        job = {"schedule": {"type": "every", "interval_minutes": 30}}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is not None
        expected = datetime(2026, 3, 16, 10, 30, 0, tzinfo=timezone.utc)
        assert abs((result - expected).total_seconds()) < 1

    def test_every_hours(self):
        job = {"schedule": {"type": "every", "interval_hours": 2}}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is not None
        expected = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
        assert abs((result - expected).total_seconds()) < 1

    def test_every_days(self):
        job = {"schedule": {"type": "every", "interval_days": 1}}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is not None
        expected = datetime(2026, 3, 17, 10, 0, 0, tzinfo=timezone.utc)
        assert abs((result - expected).total_seconds()) < 1

    def test_every_no_interval_returns_none(self):
        job = {"schedule": {"type": "every"}}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is None

    def test_cron_returns_none(self):
        job = {"schedule": {"type": "cron", "cron": "0 */6 * * *"}}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is None

    def test_at_type(self):
        job = {"schedule": {"type": "at", "datetime": "2026-03-17T10:00:00+00:00"}}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is not None

    def test_no_schedule(self):
        job = {}
        from_time = datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc)
        result = sc._calculate_next_run(job, from_time)
        assert result is None


# ── _get_recent_runs ──

class TestGetRecentRuns:
    def test_reads_completed_runs(self, tmp_path):
        log = tmp_path / "runs.jsonl"
        runs = [
            {"job_id": "heartbeat", "status": "completed", "timestamp": "2026-03-16T10:00:00"},
            {"job_id": "heartbeat", "status": "failed", "timestamp": "2026-03-16T10:30:00"},
            {"job_id": "heartbeat", "status": "running", "timestamp": "2026-03-16T11:00:00"},
        ]
        log.write_text("\n".join(json.dumps(r) for r in runs) + "\n")
        result = sc._get_recent_runs(log, limit=10)
        assert len(result) == 2  # only completed and failed
        assert result[0]["status"] == "completed"
        assert result[1]["status"] == "failed"

    def test_respects_limit(self, tmp_path):
        log = tmp_path / "runs.jsonl"
        runs = [
            {"job_id": "heartbeat", "status": "completed", "timestamp": f"2026-03-16T{i:02d}:00:00"}
            for i in range(20)
        ]
        log.write_text("\n".join(json.dumps(r) for r in runs) + "\n")
        result = sc._get_recent_runs(log, limit=5)
        assert len(result) == 5
        # Should be the last 5
        assert result[-1]["timestamp"] == "2026-03-16T19:00:00"

    def test_handles_malformed_lines(self, tmp_path):
        log = tmp_path / "runs.jsonl"
        log.write_text('{"status": "completed"}\nnot json\n{"status": "failed"}\n')
        result = sc._get_recent_runs(log, limit=10)
        assert len(result) == 2

    def test_empty_file(self, tmp_path):
        log = tmp_path / "runs.jsonl"
        log.write_text("")
        result = sc._get_recent_runs(log, limit=10)
        assert result == []


# ── _categorize_commit ──

class TestCategorizeCommit:
    def test_fix_prefix(self):
        assert sc._categorize_commit("fix: broken tests", []) == "fix"

    def test_fix_with_qq(self):
        assert sc._categorize_commit("resolved qq issue in dashboard", []) == "fix"

    def test_learning_reflection(self):
        assert sc._categorize_commit("reflection: nightly grooming", []) == "learning"

    def test_claude_md_change(self):
        files = [".claude/CLAUDE.md"]
        assert sc._categorize_commit("update config", files) == "claude_md"

    def test_skill_change(self):
        files = [".claude/skills/heartbeat/SKILL.md"]
        assert sc._categorize_commit("update heartbeat skill", files) == "skill"

    def test_capability(self):
        assert sc._categorize_commit("feat: add new dashboard tab", []) == "capability"

    def test_implement_keyword(self):
        assert sc._categorize_commit("implement task queue", []) == "capability"

    def test_default_infra(self):
        assert sc._categorize_commit("random commit message", []) == "infra"

    def test_scenario_change(self):
        files = ["scenarios/heartbeat-basic/input.json"]
        # "scenario" keyword in message matches learning before files check
        assert sc._categorize_commit("add scenario", files) == "learning"

    def test_scenario_files_only(self):
        files = ["scenarios/heartbeat-basic/input.json"]
        assert sc._categorize_commit("update test data", files) == "skill"

    def test_claude_md_plus_skills_is_skill(self):
        files = [".claude/CLAUDE.md", ".claude/skills/foo/SKILL.md"]
        assert sc._categorize_commit("update both", files) == "skill"


# ── _parse_diff_sections ──

class TestParseDiffSections:
    def test_extracts_added_lines(self):
        diff = "diff --git a/file.md b/file.md\nindex abc..def\n--- a/file.md\n+++ b/file.md\n@@ -1,3 +1,4 @@\n+new line\n old line\n-removed line\n"
        sections, lines = sc._parse_diff_sections(diff)
        assert "+new line" in lines
        assert "-removed line" in lines

    def test_extracts_section_headers(self):
        diff = "+## New Section\n-## Old Section\n+some content\n"
        sections, lines = sc._parse_diff_sections(diff)
        assert "New Section" in sections
        assert "Old Section" in sections

    def test_skips_diff_headers(self):
        diff = "diff --git a/f b/f\nindex abc..def\n--- a/f\n+++ b/f\n+content\n"
        sections, lines = sc._parse_diff_sections(diff)
        assert len(lines) == 1
        assert lines[0] == "+content"

    def test_empty_diff(self):
        sections, lines = sc._parse_diff_sections("")
        assert sections == []
        assert lines == []

    def test_hunk_header_with_section(self):
        diff = "@@ -10,5 +10,6 @@ ## Memory System\n+new memory line\n"
        sections, lines = sc._parse_diff_sections(diff)
        assert "Memory System" in sections
        assert "+new memory line" in lines


# ── _build_session_starts ──

class TestBuildSessionStarts:
    def test_finds_earliest_per_session(self):
        records = [
            {"sid": "s1", "ts": "2026-03-16T10:00:00+00:00"},
            {"sid": "s1", "ts": "2026-03-16T09:00:00+00:00"},
            {"sid": "s2", "ts": "2026-03-16T11:00:00+00:00"},
        ]
        result = sc._build_session_starts(records)
        assert len(result) == 2
        assert result["s1"] < result["s2"]

    def test_skips_empty_sid(self):
        records = [
            {"sid": "", "ts": "2026-03-16T10:00:00+00:00"},
            {"sid": "s1", "ts": "2026-03-16T10:00:00+00:00"},
        ]
        result = sc._build_session_starts(records)
        assert len(result) == 1
        assert "s1" in result

    def test_empty_records(self):
        result = sc._build_session_starts([])
        assert result == {}

    def test_handles_bad_timestamps(self):
        records = [
            {"sid": "s1", "ts": "not-a-date"},
            {"sid": "s2", "ts": "2026-03-16T10:00:00+00:00"},
        ]
        result = sc._build_session_starts(records)
        assert "s2" in result
        assert "s1" not in result


# ── _files_for_run ──

class TestFilesForRun:
    def test_empty_run_ts(self):
        result = sc._files_for_run([], "", 0)
        assert result == []

    def test_none_run_ts(self):
        result = sc._files_for_run([], None, 0)
        assert result == []

    def test_finds_files_in_window(self):
        run_ts = "2026-03-16T10:05:00+00:00"
        duration = 300  # 5 minutes
        records = [
            {"tool": "Edit", "ts": "2026-03-16T10:02:00+00:00", "summary": "/Users/test/file.py", "sid": "s1"},
            {"tool": "Read", "ts": "2026-03-16T10:03:00+00:00", "summary": "/Users/test/other.py", "sid": "s1"},
            {"tool": "Bash", "ts": "2026-03-16T10:04:00+00:00", "summary": "git status", "sid": "s1"},
        ]
        result = sc._files_for_run(records, run_ts, duration)
        # Bash is not in file_tools, so only Edit and Read
        paths = [f["path"] for f in result]
        assert len(result) == 2

    def test_prefers_write_over_read(self):
        run_ts = "2026-03-16T10:05:00+00:00"
        duration = 300
        records = [
            {"tool": "Read", "ts": "2026-03-16T10:01:00+00:00", "summary": "/tmp/f.py", "sid": "s1"},
            {"tool": "Edit", "ts": "2026-03-16T10:02:00+00:00", "summary": "/tmp/f.py", "sid": "s1"},
        ]
        result = sc._files_for_run(records, run_ts, duration)
        assert len(result) == 1
        assert result[0]["action"] == "write"

    def test_filters_by_session(self):
        run_ts = "2026-03-16T10:05:00+00:00"
        duration = 300
        records = [
            {"tool": "Edit", "ts": "2026-03-16T10:01:00+00:00", "summary": "/tmp/a.py", "sid": "s1"},
            {"tool": "Edit", "ts": "2026-03-16T10:01:00+00:00", "summary": "/tmp/b.py", "sid": "s2"},
        ]
        session_starts = {
            "s1": datetime(2026, 3, 16, 10, 0, 0, tzinfo=timezone.utc),
            "s2": datetime(2026, 3, 16, 8, 0, 0, tzinfo=timezone.utc),  # started way before
        }
        result = sc._files_for_run(records, run_ts, duration, session_starts)
        paths = [f["path"] for f in result]
        assert len(result) == 1  # only s1, s2 started too early


# ── _fmt_seconds ──

class TestFmtSeconds:
    def test_seconds(self):
        assert sc._fmt_seconds(45) == "45s"

    def test_minutes_and_seconds(self):
        assert sc._fmt_seconds(125) == "2m05s"

    def test_hours_and_minutes(self):
        assert sc._fmt_seconds(3725) == "1h02m"

    def test_zero(self):
        assert sc._fmt_seconds(0) == "0s"

    def test_exact_minute(self):
        assert sc._fmt_seconds(60) == "1m00s"

    def test_exact_hour(self):
        assert sc._fmt_seconds(3600) == "1h00m"


# ── _parse_klava_frontmatter ──

class TestParseKlavaFrontmatter:
    def test_with_frontmatter(self):
        text = "---\nstatus: running\npriority: high\n---\nTask body here"
        result = sc._parse_klava_frontmatter(text)
        assert result["status"] == "running"
        assert result["priority"] == "high"
        assert result["_body"] == "Task body here"

    def test_without_frontmatter(self):
        text = "Just a plain note"
        result = sc._parse_klava_frontmatter(text)
        assert result["_body"] == "Just a plain note"

    def test_empty_text(self):
        result = sc._parse_klava_frontmatter("")
        assert result["_body"] == ""

    def test_none_text(self):
        result = sc._parse_klava_frontmatter(None)
        assert result["_body"] == ""

    def test_no_closing_frontmatter(self):
        text = "---\nstatus: running\nno closing marker"
        result = sc._parse_klava_frontmatter(text)
        assert result["_body"] == text

    def test_key_without_value(self):
        text = "---\nempty_key:\n---\nBody"
        result = sc._parse_klava_frontmatter(text)
        assert result["empty_key"] == ""


# ── _categorize_task ──

class TestCategorizeTask:
    def test_overdue_task(self):
        result = sc._categorize_task("[DEAL] Follow up", "2020-01-01T00:00:00Z", "2026-03-16", "gtasks")
        assert result["section"] == "overdue"
        assert result["overdue"] is True
        assert result["bold"] is True

    def test_today_task(self):
        result = sc._categorize_task("[DEAL] Follow up", "2026-03-16T00:00:00Z", "2026-03-16", "gtasks")
        assert result["section"] == "today"
        assert result["is_today"] is True

    def test_deal_tag(self):
        result = sc._categorize_task("[DEAL] AcmeCorp call", None, "2026-03-16", "gtasks")
        assert result["section"] == "deals"
        assert any(t["name"] == "DEAL" for t in result["tags"])

    def test_reply_tag(self):
        result = sc._categorize_task("[REPLY] Answer email", None, "2026-03-16", "gtasks")
        assert result["section"] == "replies"

    def test_signal_tag(self):
        result = sc._categorize_task("[SIG] Reply to chat", None, "2026-03-16", "gtasks")
        assert result["section"] == "replies"

    def test_critical_tag(self):
        result = sc._categorize_task("[CRITICAL] Fix bug now", None, "2026-03-16", "gtasks")
        assert result["section"] == "overdue"
        assert result["bold"] is True

    def test_github_source(self):
        result = sc._categorize_task("Some issue", None, "2026-03-16", "github")
        assert result["section"] == "primary-gh"

    def test_personal_fallback(self):
        result = sc._categorize_task("Buy groceries", None, "2026-03-16", "gtasks")
        assert result["section"] == "personal"

    def test_clean_title_strips_prefix(self):
        result = sc._categorize_task("[DEAL] AcmeCorp call", None, "2026-03-16", "gtasks")
        assert result["clean_title"] == "AcmeCorp call"


# ── _parse_deal_frontmatter ──

class TestParseDealFrontmatter:
    def test_basic_frontmatter(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("---\nstage: 5-proposal\nvalue: 50000\nlast_contact: 2026-03-10\n---\n# Notes")
        result = sc._parse_deal_frontmatter(f)
        assert result["stage"] == "5-proposal"
        assert result["value"] == "50000"

    def test_quoted_values(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text('---\nstage: "7-evaluation"\nproduct: \'data\'\n---\n')
        result = sc._parse_deal_frontmatter(f)
        assert result["stage"] == "7-evaluation"
        assert result["product"] == "data"

    def test_null_values(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("---\nvalue: null\nmrr: ~\nempty:\n---\n")
        result = sc._parse_deal_frontmatter(f)
        assert result["value"] is None
        assert result["mrr"] is None
        assert result["empty"] is None

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("Just some text without frontmatter")
        assert sc._parse_deal_frontmatter(f) is None

    def test_missing_file(self, tmp_path):
        assert sc._parse_deal_frontmatter(tmp_path / "missing.md") is None

    def test_skips_comments_and_list_items(self, tmp_path):
        f = tmp_path / "Deal.md"
        f.write_text("---\nstage: 5-proposal\n# comment\n- list item\nvalue: 10000\n---\n")
        result = sc._parse_deal_frontmatter(f)
        assert "stage" in result
        assert "value" in result
        assert len(result) == 2  # no comment or list item keys


# ── _parse_deal_stage ──

class TestParseDealStage:
    def test_standard_stage(self):
        num, name = sc._parse_deal_stage("5-proposal")
        assert num == 5
        assert name == "proposal"

    def test_number_only(self):
        num, name = sc._parse_deal_stage("7")
        assert num == 7

    def test_empty_string(self):
        num, name = sc._parse_deal_stage("")
        assert num == 0
        assert name == "unknown"

    def test_none(self):
        num, name = sc._parse_deal_stage(None)
        assert num == 0

    def test_non_numeric(self):
        num, name = sc._parse_deal_stage("active")
        assert num == 0


# ── _parse_deal_value ──

class TestParseDealValue:
    def test_integer(self):
        assert sc._parse_deal_value("50000") == 50000.0

    def test_with_commas(self):
        assert sc._parse_deal_value("1,000,000") == 1000000.0

    def test_with_dollar_sign(self):
        assert sc._parse_deal_value("$85000") == 85000.0

    def test_none(self):
        assert sc._parse_deal_value(None) is None

    def test_invalid(self):
        assert sc._parse_deal_value("not-a-number") is None

    def test_float(self):
        assert sc._parse_deal_value("99.99") == 99.99


# ── _parse_deal_date ──

class TestParseDealDate:
    def test_valid_date(self):
        result = sc._parse_deal_date("2026-03-16")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 16

    def test_none(self):
        assert sc._parse_deal_date(None) is None

    def test_invalid_format(self):
        assert sc._parse_deal_date("March 16, 2026") is None

    def test_empty(self):
        assert sc._parse_deal_date("") is None


# ── _clean_lead ──

class TestCleanLead:
    def test_wikilink(self):
        assert sc._clean_lead("[[John Doe]]") == "John Doe"

    def test_single_brackets(self):
        assert sc._clean_lead("[Name]") == "Name"

    def test_plain_text(self):
        assert sc._clean_lead("Jane Smith") == "Jane Smith"

    def test_none(self):
        assert sc._clean_lead(None) == "Unknown"

    def test_empty(self):
        assert sc._clean_lead("") == "Unknown"


# ── _get_deal_weight ──

class TestGetDealWeight:
    def test_early_stage(self):
        assert sc._get_deal_weight(1) == 0.10

    def test_mid_stage(self):
        assert sc._get_deal_weight(7) == 0.50

    def test_late_stage(self):
        assert sc._get_deal_weight(13) == 0.90

    def test_lost_stage(self):
        assert sc._get_deal_weight(17) == 0.0

    def test_zero_stage(self):
        assert sc._get_deal_weight(0) == 0.0

    def test_stage_boundaries(self):
        assert sc._get_deal_weight(3) == 0.10
        assert sc._get_deal_weight(4) == 0.25
        assert sc._get_deal_weight(6) == 0.25
        assert sc._get_deal_weight(9) == 0.50
        assert sc._get_deal_weight(10) == 0.75
        assert sc._get_deal_weight(12) == 0.75
        assert sc._get_deal_weight(15) == 0.90


# ── _collect_error_learning ──

class TestCollectErrorLearning:
    def test_with_no_errors_or_markers(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        result = sc._collect_error_learning(days=7, qq_markers=[], skill_changes=[])
        assert result["errors_found"] == 0
        assert result["qq_found"] == 0
        assert result["skills_modified"] == []
        assert result["skills_added"] == []
        assert result["scenarios_created"] == 0

    def test_counts_skill_errors(self, tmp_path, monkeypatch):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill = skills_dir / "buggy"
        skill.mkdir()
        now = datetime.now(timezone.utc)
        errors = [
            {"ts": now.isoformat(), "err": "timeout"},
            {"ts": now.isoformat(), "err": "crash"},
        ]
        with open(skill / "errors.jsonl", "w") as f:
            for e in errors:
                f.write(json.dumps(e) + "\n")
        monkeypatch.setattr(sc, "SKILLS_DIR", skills_dir)
        result = sc._collect_error_learning(days=7, qq_markers=[], skill_changes=[])
        assert result["errors_found"] == 2

    def test_counts_qq_markers(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        markers = [{"timestamp": "2026-03-16T10:00:00", "context": "qq something"}]
        result = sc._collect_error_learning(days=7, qq_markers=markers, skill_changes=[])
        assert result["qq_found"] == 1

    def test_detects_skills_modified(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        changes = [
            {
                "message": "update heartbeat",
                "files": [".claude/skills/heartbeat/SKILL.md"],
            }
        ]
        result = sc._collect_error_learning(days=7, qq_markers=[], skill_changes=changes)
        assert "heartbeat" in result["skills_modified"]

    def test_detects_skills_added(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        changes = [
            {
                "message": "create skill: vox-crm",
                "files": [".claude/skills/vox-crm/SKILL.md"],
            }
        ]
        result = sc._collect_error_learning(days=7, qq_markers=[], skill_changes=changes)
        assert "vox-crm" in result["skills_added"]

    def test_detects_scenarios_created(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "SKILLS_DIR", tmp_path / "skills")
        changes = [
            {
                "message": "add scenario for heartbeat",
                "files": ["scenarios/heartbeat-basic/input.json"],
            }
        ]
        result = sc._collect_error_learning(days=7, qq_markers=[], skill_changes=changes)
        assert result["scenarios_created"] == 1


# ── _format_job_summaries ──

class TestFormatJobSummaries:
    def test_basic_summary(self):
        jobs = [{"id": "heartbeat", "name": "Heartbeat", "enabled": True, "schedule": {"type": "every", "interval_minutes": 30}}]
        jobs_status = {"heartbeat": {"last_run": "2026-03-16T10:00:00+00:00", "status": "completed"}}
        result = sc._format_job_summaries(jobs, jobs_status)
        assert len(result) == 1
        assert result[0]["id"] == "heartbeat"
        assert result[0]["status"] == "completed"
        assert result[0]["time_since"] is not None

    def test_no_last_run(self):
        jobs = [{"id": "new-job", "name": "New Job", "schedule": {"type": "every", "interval_minutes": 60}}]
        jobs_status = {}
        result = sc._format_job_summaries(jobs, jobs_status)
        assert len(result) == 1
        assert result[0]["last_run"] is None
        assert result[0]["time_since"] is None
        assert result[0]["status"] == "pending"

    def test_multiple_jobs(self):
        jobs = [
            {"id": "j1", "name": "Job 1", "schedule": {"type": "every", "interval_minutes": 30}},
            {"id": "j2", "name": "Job 2", "enabled": False, "schedule": {"type": "cron", "cron": "0 5 * * *"}},
        ]
        jobs_status = {
            "j1": {"last_run": "2026-03-16T10:00:00+00:00", "status": "completed"},
        }
        result = sc._format_job_summaries(jobs, jobs_status)
        assert len(result) == 2
        j2 = next(s for s in result if s["id"] == "j2")
        assert j2["enabled"] is False


# ── collect_dashboard_data (cache) ──

class TestCollectDashboardDataCache:
    def test_returns_cached_data(self):
        """Cache hit returns same data without refreshing."""
        fake_data = {"cached": True, "test": "value"}
        sc._dashboard_cache["data"] = fake_data
        sc._dashboard_cache["ts"] = time.time()

        result = sc.collect_dashboard_data()
        assert result == fake_data

        # Cleanup
        sc._dashboard_cache["data"] = None
        sc._dashboard_cache["ts"] = 0
