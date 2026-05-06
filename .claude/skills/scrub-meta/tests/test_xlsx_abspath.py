#!/usr/bin/env python3
"""Regression test: xlsx absPath must never survive scrub.

Background: Office for Mac embeds the original file's absolute path in
xl/workbook.xml as <x15ac:absPath url="/Users/.../..." />. This is invisible
in Excel UI but trivially extractable by unzip + grep. Klava once shipped a
manual scrub that missed it (May 5 2026, Eldil book deal); this test exists
so that miss can never silently regress.

Construction: build a synthetic xlsx that contains a known-bad absPath in
workbook.xml, run it through scrub.py, assert the output is clean.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRUB = REPO / "scripts" / "scrub.py"

LEAKY_PATH = "/Users/dimaabramov/Library/CloudStorage/Dropbox-DataEngine/Dmitry Abramov/!Grably/!Partners/ASAP Publishers/test/"
LEAK_TERMS = ["dimaabramov", "abramov", "grably", "asap publishers", "cloudstorage", "dropbox-dataengine", "absPath"]


def build_leaky_xlsx(out: Path) -> None:
    """Create a minimal but valid xlsx that contains absPath + AAYUSH creator."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "List"
    ws.append(["ISBN", "Title", "Author"])
    ws.append([9789988891482, "Test Title", "Test Author"])
    wb.properties.creator = "AAYUSH"
    wb.properties.lastModifiedBy = "Elina Abramova"
    wb.save(out)

    # Inject the absPath block into workbook.xml — openpyxl never writes it,
    # so we patch it in to simulate Office-for-Mac output.
    inject = (
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        '<mc:Choice Requires="x15">'
        f'<x15ac:absPath url="{LEAKY_PATH}" xmlns:x15ac="http://schemas.microsoft.com/office/spreadsheetml/2010/11/ac"/>'
        '</mc:Choice></mc:AlternateContent>'
    )
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(out, "r") as z:
            z.extractall(td)
        wb_xml = Path(td) / "xl" / "workbook.xml"
        text = wb_xml.read_text()
        # insert immediately after <workbookPr/>
        text = text.replace("<workbookPr/>", "<workbookPr/>" + inject, 1)
        wb_xml.write_text(text)
        # repack
        out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in Path(td).rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(td))


def scan_archive(path: Path, terms: list[str]) -> dict[str, list[str]]:
    """Return {term: [filenames where it appeared]} across all archive entries."""
    hits: dict[str, list[str]] = {t: [] for t in terms}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            try:
                blob = z.read(name).decode("utf-8", errors="ignore").lower()
            except Exception:
                continue
            for t in terms:
                if t.lower() in blob:
                    # ignore false positives that are book content (not relevant for this test fixture)
                    hits[t].append(name)
    return hits


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        leaky = Path(td) / "leaky.xlsx"
        clean = Path(td) / "clean.xlsx"
        build_leaky_xlsx(leaky)

        # Sanity: leaky file actually has the leaks before scrub
        pre = scan_archive(leaky, LEAK_TERMS)
        for term, files in pre.items():
            if not files:
                print(f"FAIL setup: leaky fixture missing term '{term}' — fixture broken", file=sys.stderr)
                return 2
        print(f"setup ok: leaky fixture contains all {len(LEAK_TERMS)} terms")

        # Run the skill
        cp = subprocess.run(
            [sys.executable, str(SCRUB), str(leaky), "--out", str(clean)],
            capture_output=True, text=True,
        )
        if cp.returncode != 0:
            print(f"FAIL: scrub.py exited {cp.returncode}", file=sys.stderr)
            print(cp.stdout, file=sys.stderr)
            print(cp.stderr, file=sys.stderr)
            return 1

        # Post: clean output must have zero hits for any term
        post = scan_archive(clean, LEAK_TERMS)
        failures = [(t, f) for t, f in post.items() if f]
        if failures:
            print("FAIL: scrub output still contains leak terms:", file=sys.stderr)
            for t, files in failures:
                print(f"  '{t}' in: {files}", file=sys.stderr)
            return 1

        print(f"PASS: all {len(LEAK_TERMS)} leak terms removed from output")
        return 0


if __name__ == "__main__":
    sys.exit(main())
