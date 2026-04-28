# Task 06b: Revisit extract_column_meta.py for Cleaned Markdown Files

## Goal

Update `extract_column_meta.py` to use the cleaned markdown files in
`fir_instructions/source_files/2025/markdown_clean/` (instead of `markdown/`),
fix an empty-string section name bug exposed by the switch, simplify the
`_NON_SECTION_RE` filter that was guarding against heading-formatting errors now
corrected in the clean files, fix a TOC-extraction bug, and add a coverage
validation tool.

## Prerequisite

Task 06 complete — the extraction module and its test suite must already exist.

## Background

The FIR2025 instruction PDFs were converted to markdown twice:

- `markdown/` — original conversion; formula text, examples, and boilerplate
  were sometimes incorrectly formatted as `##` headings
- `markdown_clean/` — corrected version with verified heading hierarchies

`extract_schedule_meta.py` and `extract_line_meta.py` were already updated to
use `markdown_clean/` in tasks 04b and 05b. This task brings
`extract_column_meta.py` in line.

### What changed in the cleaned files relevant to column extraction

| File | Original issue | Cleaned state |
|---|---|---|
| All schedules | Formula and boilerplate text formatted as `##` headings | Demoted to body text |
| `FIR2025 S28.md` | Column 05 was plain text (no heading) | Now a proper `###` heading |

The net record count after switching to `markdown_clean/` and applying all fixes
is **239** (down from 245 in `markdown/`). The apparent decrease is entirely
explained by corrections:

| Schedule | old | new | diff | Explanation |
|---|---|---|---|---|
| S26 | 38 | 37 | −1 | Old markdown had formula headings as section names; column 01 appeared twice under two spurious sections, now once under its real section |
| S40 | 12 | 11 | −1 | Same pattern — a column collapsed from two bogus sections to one real section |
| S74D | 12 | 8 | −4 | Old `_find_section` matched the TOC occurrence of "Schedule 74D" and accidentally included S74C columns; clean markdown has no duplicate headings so only S74D's 8 real columns are captured |

## Changes Made

### 1. Updated default markdown directory

`_DEFAULT_MARKDOWN_DIR` changed from `markdown/` to `markdown_clean/`. The
module docstring usage example updated to match.

**File:** `src/municipal_finances/fir_instructions/extract_column_meta.py`

### 2. Fixed empty-string section name bug

`_parse_md_sections` initialises `current_heading = ""` so the very first
section (before any heading) carries `heading=""`. Without the fix, the
`_extract_per_schedule_columns` loop would set `current_section_name = ""`
(empty string) instead of leaving it `None`, attaching an empty string as the
section for all columns found before the first heading.

**Before:**
```python
if not _NON_SECTION_RE.match(heading.strip()):
    current_section_name = heading.strip()
```

**After:**
```python
if heading.strip() and not _NON_SECTION_RE.match(heading.strip()):
    current_section_name = heading.strip()
```

This bug was latent in the old markdown because no column headings appeared
before the first `##` heading in those files. The clean markdown exposed it.

### 3. Simplified `_NON_SECTION_RE`

The old pattern had 8 alternatives to block formula/boilerplate headings that
appeared as `##` headings in the original markdown. The cleaned files demote
those to body text, so only the "Description of Columns/Lines" pattern — which
still appears as a `###` heading in S26 — remains necessary.

**Before (8 patterns):**
```python
_NON_SECTION_RE = re.compile(
    r"^(Description of (Columns|Lines)|Descriptions of (Columns|Lines)|"
    r"This section will be automatically pre-populated|"
    r"Only .* municipalities should have values|"
    r"IMPORTANT:|Note:|Please note|Total is automatically|"
    r".*automatically calculated|.*should equal)",
    re.IGNORECASE,
)
```

**After (1 pattern):**
```python
_NON_SECTION_RE = re.compile(
    r"^(Description of (Columns|Lines)|Descriptions of (Columns|Lines))",
    re.IGNORECASE,
)
```

### 4. Fixed TOC-entry extraction bug

Cleaned markdown files include an in-text table of contents where column entries
appear as body lines matching the column heading regex, e.g.:

```
Column 1 - Ontario Conditional Grants .................................................................................. 4
```

`_scan_body_for_columns` was picking these up, inflating counts and producing
spurious records (e.g. S12 Column 01 named "Ontario Conditional Grants
.................................................................................. 4").

Fix: added a guard in `_parse_column_heading` that rejects any match whose
captured column name contains `"...."` (four or more consecutive dots):

```python
if "...." in col_name:
    return None
```

Four dots is a reliable discriminator — real column names never contain dot
runs, while every TOC line uses a long dotted leader before the page number.

### 5. Updated `_scan_body_for_columns` docstring

S28 Column 05 is now a proper heading in the clean markdown, but
`_scan_body_for_columns` is retained as a **failsafe** in case any column
heading is inadvertently omitted from a cleaned file. The docstring was updated
to reflect this general purpose rather than the specific S28 example.

## Workarounds confirmed STILL NEEDED

- **`_scan_body_for_columns`**: Retained as a failsafe for plain-text column
  definitions that might be missed in the clean markdown.
- **`:?` in `_COLUMN_HEADING_RE`**: S51 still uses `Column N: - Name` format.
- **`_PAIRED_COLUMN_HEADING_RE`**: S74D still uses `Columns N & M: - GroupName`.
- **`(column_id, section_name)` dedup key**: Same column IDs still appear in
  multiple named sections (S20, S26, S80, S80D).

## New Tool: validate_column_coverage

Added `src/municipal_finances/fir_instructions/validate_column_coverage.py` and
wired it into the main CLI as `validate-column-coverage`. The tool:

1. Loads the baseline column metadata CSV.
2. Queries `firrecord` for all distinct `(schedule, column_id)` pairs in a
   given year (default 2025).
3. Reports any pairs present in the live data but absent from the metadata,
   grouped by schedule with record counts.

Each reported gap should be triaged as either:
- **[U] Genuinely undocumented** — the FIR instructions don't describe the
  column; no extractor fix needed.
- **[S] Script gap** — the column is documented but the extractor missed it;
  needs a fix to `extract_column_meta.py`.

### Coverage report for 2025 data

Running `uv run src/municipal_finances/app.py validate-column-coverage`
against 2025 data (239 metadata records) found **37 gaps across 23 schedules**.
All gaps are genuinely undocumented:

| Pattern | Schedules | Explanation |
|---|---|---|
| Base-schedule X-suffix, col 01 | 02X, 42X, 53X, 60X, 70X, 71X, 80C, 81X | All base schedules use a trailing X in the SLC field (e.g. `10X`); col 01 is undocumented for these schedules. For schedules whose col 01 *is* documented (e.g. `10`, `12`, `20`, `40`), the validator normalises `10X` → `10` and finds coverage, so no gap is reported. |
| "D"-suffix sub-schedules | 22D, 24D | Supplementary schedules; col 01 undocumented |
| "A"/"B" sub-schedules | 26A, 26B, 54B, 72A, 72B, 74A, 77A, 77B | Sub-schedules documented under parent code; separate DB entries have no metadata |
| S51A/S51B Column 99 | 51A, 51B | Administrative column; not described in instructions |
| S74C Column 03 | 74C | Sub-schedule of S74; instructions use "74" code, DB uses "74C" |
| S80A columns 01–05 | 80A | Sub-schedule; undocumented |
| S80D columns 05–14 | 80D | Beyond the 4 columns documented in S80D instructions |

## Tests Updated

- `test_spot_check_s72_columns` updated to `== 9` (9 columns × 1 named section).
  The prior version expected 18 (× 2 sections) due to TOC entries inflating the
  count; the correct number after the TOC fix is 9.
- `tests/fir_instructions/test_validate_column_coverage.py` added with full
  coverage of `validate_column_coverage.py` (34 tests, 100% branch coverage).

## Verification

```bash
# All tests pass
uv run pytest tests/fir_instructions/test_extract_column_meta.py -v
uv run pytest tests/fir_instructions/test_validate_column_coverage.py -v

# 239 records extracted
uv run src/municipal_finances/app.py extract-baseline-column-meta

# Coverage validation report
uv run src/municipal_finances/app.py validate-column-coverage
```
