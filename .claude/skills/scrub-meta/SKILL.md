---
name: scrub-meta
description: Strip identifying metadata from any file before sharing externally - office docs, PDFs, images, video, audio, archives. Removes creator, paths, embeds, EXIF, GPS, hyperlinks, normalizes timestamps, verifies clean. Use when sending a file to a client or external party where you must not leak the source (path, user, partner names, software fingerprint, location data, embedded supplier links).
user_invocable: true
---

# Scrub Meta

Sanitize a file before sending it externally. Removes everything that fingerprints the originator: filesystem paths, author names, software signatures, embedded media, hyperlinks, EXIF/GPS, document GUIDs, archive timestamps. Verifies the output is clean against caller-supplied and standing leak terms.

Always writes to a fresh copy. The original is never modified.

> **Always invoke this skill — never roll a manual scrub.** A manual one-off scrub will reliably miss at least one leak vector. The most common silent miss is `<x15ac:absPath>` inside `xl/workbook.xml` of any Office-for-Mac xlsx — invisible in Excel UI, but one `unzip -p` away from leaking the original full path including username and folder names. The script's OOXML branch rebuilds the file from scratch via openpyxl, which structurally cannot emit absPath, and the verify step greps `xl/workbook.xml` for standing leak terms (see `~/Documents/GitHub/claude/.claude/skills/personal/scrub-meta/leak-terms.txt`) as a backstop. Regression test: `tests/test_xlsx_abspath.py`.

## Flow

1. Resolve input
2. Detect type via `file --mime-type`
3. Pre-scan with exiftool (snapshot)
4. Type-specific scrub (OOXML / PDF / image / video / audio / archive / iWork / legacy-Office / SVG / text / unknown)
5. Universal pass (exiftool fallback + xattr strip + delete `._*` resource forks)
6. Verify (exiftool diff + grep leak terms + sha256 round-trip)
7. Print markdown report
8. Reveal output in Finder
9. Print warning: do not open in native app before sending

## Invocation

```bash
python3 ~/Documents/GitHub/claude/.claude/skills/scrub-meta/scripts/scrub.py <file> [--out PATH] [--terms term1,term2,...]
```

Defaults:
- `--out` → `~/Downloads/<stem>_clean<ext>`
- `--terms` is merged with `~/Documents/GitHub/claude/.claude/skills/personal/scrub-meta/leak-terms.txt` (gitignored standing list)

## Step 1: Resolve input

Accept the file path as the first positional arg. Resolve to absolute. Fail loudly if missing.

**Execution:** Direct
**Verify:** `os.path.isfile(path)`

## Step 1b: Sanitize filename

The filename is a leak vector too — partner names, `[External]` markers, upload-session IDs, and copy suffixes all travel inside it and survive every content scrub. When `--out` is not provided, `sanitize_filename()` strips:

- Standing leak terms from `personal/scrub-meta/leak-terms.txt` (whole-token, case-insensitive) and any `--terms` extras
- Sensitivity markers in brackets or parens: `[External]`, `(Internal)`, `[Confidential]`, `[Draft]`, `[NDA]`, `[Client Copy]`
- Leading upload-session IDs: 10+ digit prefix followed by `_` / `-` / space (e.g. `1778551079623_…`)
- Trailing copy markers: ` (1)`, `(2)` from re-downloads
- Collapsed whitespace / separators, trimmed edges

Output goes to `~/Downloads/<sanitized>_clean.<ext>`. When the rename triggers, the report surfaces a `renamed:` note with the original filename so the user sees what was stripped. If the caller passes `--out` explicitly, that wins — no auto-rename. Fallback stem `document` is used if sanitization empties the string.

**Execution:** Direct
**Verify:** report shows `renamed:` note when stem differs from `<src.stem>_clean`

## Step 2: Detect type

`file --mime-type -b <path>` returns canonical MIME. Map to a category: `ooxml | pdf | image | video | audio | archive | iwork | legacy_office | svg | text | unknown`.

Never trust file extension alone. A `.xlsx` may be a renamed binary; an image may be mislabeled.

**Execution:** Direct
**Verify:** non-empty MIME string

## Step 3: Pre-scan

`exiftool -a -G1 -j <input>` → JSON snapshot. Used for the diff in Step 6.

**Execution:** Direct
**Produces:** in-memory JSON
**Verify:** parses as JSON

## Step 4: Type-specific scrub

Branch on detected category. All branches always write to `--out`, never modify input.

**OOXML (xlsx / docx / pptx):**
1. Load workbook/document with appropriate library (openpyxl / python-docx / python-pptx) in `read_only=True, data_only=True` mode.
2. Iterate values into a fresh document. Drops embedded images, hyperlinks, formulas, custom styles, defined names, comments, revision history.
3. Rename single sheets to `Sheet1`. Strip core properties: empty `creator` and `lastModifiedBy`, fixed neutral `created` / `modified` dates.
4. Save intermediate. Then re-package the resulting ZIP entry-by-entry with: `date_time=(1980,1,1,0,0,0)`, `external_attr = 0o644 << 16`, `create_system = 0` (MS-DOS, kills Unix uid/gid extras).
5. Replace `docProps/app.xml` with vanilla `<Application>Microsoft Excel</Application>` + `<AppVersion>16.0000</AppVersion>` (no Mac fingerprint, no openpyxl signature).
6. Replace `docProps/core.xml` with empty creator/lastModifiedBy + neutral fixed dates.

**PDF:**
1. `qpdf --linearize --object-streams=generate <in> <out>` → rebuild structure.
2. `exiftool -all= -overwrite_original_in_place <out>` → strip /Author /Creator /Producer /Title /Subject /Keywords /CreationDate /ModDate plus XMP packets.
3. Verify no embedded files / no JS / no form data with `pdftk dump_data` if available.

**Image (jpg / png / heic / tiff / webp):**
1. `exiftool -all= -overwrite_original_in_place <out>` after copying input to output path.
2. Explicit GPS check post-strip — fail if any `GPS*` field survives.

**Video (mp4 / mov / mkv):**
1. `ffmpeg -i <in> -map_metadata -1 -c copy <out>` → strip metadata atoms + location.
2. `exiftool -all= -overwrite_original_in_place <out>` → second pass for ID3-style sidecar tags.

**Audio (mp3 / m4a / flac / wav / ogg):** `exiftool -all= -overwrite_original_in_place` after copy.

**Archive (zip / tar):** Walk entries, repack with `(1980,1,1,0,0,0)` timestamps and zero uid/gid. Strip archive comment.

**iWork (numbers / pages / keynote):** LibreOffice headless `soffice --convert-to xlsx <in>` (or pdf for pages/keynote), then re-dispatch on the conversion output.

**Legacy Office (xls / doc / ppt):** Same — convert to OOXML via `soffice --convert-to`, then re-dispatch.

**SVG / HTML / Markdown:** Regex strip — remove `<metadata>...</metadata>` blocks, `sodipodi:` and `inkscape:` namespaces, HTML comments, YAML frontmatter when explicitly requested.

**Unknown:** Fall through to Step 5 universal pass only. Print a warning naming the detected MIME.

**Execution:** Direct
**Verify:** type-specific (see verify step)

## Step 5: Universal pass

Always run, regardless of category branch:

1. `exiftool -all= -overwrite_original_in_place <out>` — catches any EXIF/XMP that survived the type-specific scrub.
2. `xattr -cr <out>` — clears macOS extended attributes including `kMDItemWhereFroms` (download URL!), `kMDItemUserTags`, `quarantine`, `lastuseddate`. Note: `com.apple.provenance` may reattach automatically; that's macOS-applied, opaque (no PII), and does not survive transport (email / Signal / Drive / web upload all strip xattrs).
3. Delete sibling resource fork files: `os.remove(os.path.join(dir, '._' + name))` if present.

**Execution:** Direct
**Verify:** `xattr -l` shows only `com.apple.provenance` or empty

## Step 6: Verify

Three checks:

1. **Exiftool diff** — re-run `exiftool -a -G1 -j <out>`, compare to the Step 3 snapshot. Report what was removed by group (System, ZIP, XML, EXIF, XMP-dc, IPTC, GPS, etc.).
2. **Leak-term grep** — combine `--terms` arg with `~/Documents/GitHub/claude/.claude/skills/personal/scrub-meta/leak-terms.txt`. For OOXML/archives, unzip `<out>` to a temp dir and grep across **metadata files only** (`docProps/`, `*.rels`, `xl/workbook.xml`, equivalents for docx/pptx) — never grep across cell content / body content; legitimate data may match terms by coincidence. For other types, grep against the exiftool JSON output. Zero hits required.
3. **Round-trip integrity** — `base64 <out> | base64 -D | shasum -a 256` matches `shasum -a 256 <out>`. Confirms file content is fully self-contained (xattrs are not in the bytes).

**Execution:** Direct
**Verify:** all three pass

## Step 7: Report

Print a markdown table of what was removed, by category. Include the input path, output path, sha256, and any warnings (e.g. macOS `com.apple.provenance` re-attached, or unknown type fell through to universal pass).

## Step 8: Reveal in Finder

`open -R <out>` reveals and selects the scrubbed file in Finder.

## Step 9: Warn

Always print as the final line:

> Do not open this file in its native app before sending. Excel / Word / Preview / Keynote re-inject `creator`, `lastModifiedBy`, and absolute paths on save. Send as-is from the output location.

## Hard Rules

- **Never modify the input file.** Always copy to `--out`. Even `--in-place` writes to a temp + atomic rename.
- **Never trust the file extension** for type detection. `file --mime-type -b` is the source of truth.
- **Grep leak terms only in metadata files / metadata extracts**, never in body / cell / page content. Legitimate content can match terms by coincidence (e.g. an author named "Dmitrievna" matching "Dmitry"). Reporting false positives erodes trust in the scrub.
- **Standing leak terms live in the gitignored personal overlay** (`~/Documents/GitHub/claude/.claude/skills/personal/scrub-meta/leak-terms.txt`), never in this skill's tracked files. Names of partners and personal paths must not ship publicly.
- **`com.apple.provenance` is expected to reattach** after `xattr -cr`. Don't loop trying to strip it. It's opaque, contains no PII, and is removed by every network transport. Document the residual in the report.
- **Office apps re-inject metadata on save.** The user must be warned every time, on the final line of the report.
- **GPS in images is non-negotiable** — fail the verify step if any `GPS*` field survives an image scrub.
- **LibreOffice / qpdf / ffmpeg are required for some branches.** If `soffice` / `qpdf` / `ffmpeg` are not in `PATH`, fail loudly with the install hint (`brew install libreoffice qpdf ffmpeg`) instead of silently degrading.
