# Task 04b: Extract FIR2025 Baseline — Schedule Metadata (v2, markdown_clean)

## Goal

Re-implement Task 04 to use the verified `markdown_clean/` source files and expand the
schedule catalogue from 32 to 35 codes (adding 74A, 74B, 74C).

## Changes from Task 04

| Area | Old | New |
|---|---|---|
| Source directory | `markdown/` | `markdown_clean/` |
| Schedule count | 32 | 35 |
| New codes | — | 74A, 74B, 74C |
| 74x extractor | `_extract_schedule_74d` + `_extract_schedule_74e` | `_extract_schedule_74x` (unified) |
| S71 | treated as having no source file | extracts normally as a regular schedule |

## Task List

- [x] Add 74A, 74B, 74C to `SCHEDULE_CATEGORIES`
- [x] Remove `"74E": "74"` from `_MD_PARENT_FILE`; simplify `SUB_SCHEDULE_PARENTS = dict(_MD_PARENT_FILE)`
- [x] Add `_74X_CODES` frozenset
- [x] Change `_DEFAULT_MARKDOWN_DIR` to `markdown_clean`
- [x] Remove `_extract_schedule_74d` and `_extract_schedule_74e`
- [x] Add `_extract_schedule_74x`
- [x] Update dispatcher in `extract_schedule_record`
- [x] Update docstrings (32 → 35)
- [x] Update tests (imports, counts, new/removed test classes)
- [x] Regenerate `fir_instructions/exports/baseline_schedule_meta.csv` (35 rows)

## Implementation Details

### Schedules to Extract

The FIR system now has 35 distinct schedule codes tracked in `fir_schedule_meta`.

| Category | Schedules |
|---|---|
| Revenue | 10, 12 |
| Taxation | 20, 22, 22A, 22B, 22C, 24, 26, 28, 72 |
| Expense | 40, 42 |
| Tangible Capital Assets | 51A, 51B |
| Net Financial Assets / Net Debt | 53 |
| Cash Flow | 54 |
| Reserves & Reserve Funds | 60, 61A, 61B, 62 |
| Financial Position | 70 |
| Remeasurement Gains & Losses | 71 |
| Long Term Liabilities | 74, 74A, 74B, 74C, 74D, 74E |
| Other Information | 76, 77, 80, 80D, 81, 83 |

> **Note on sub-schedules**: 22A/22B/22C, 51A/51B, and 61A/61B do not have their own
> markdown files. Their instructions appear within the parent schedule's file (22, 51,
> and 61 respectively). 74A–74E are also embedded within `FIR2025 S74.md`.

### Extraction Approach

The extractor dispatches to one of four extractors based on the schedule code:

1. **Regular schedules** (`_extract_regular_schedule`): Reads `FIR2025 S{code}.md`, finds the
   schedule name from the `SCHEDULE {code}: Name` body heading, and extracts the `General
   Information` / `General Instructions` section content as the description.

2. **Schedule 53** (`_extract_schedule_53`): Special case — no General Information heading.
   Uses the content of the first section following the `SCHEDULE 53:` body heading.

3. **Schedules 74A–74E** (`_extract_schedule_74x`): All five are embedded in `FIR2025 S74.md`.
   Locates the `## Schedule 74X` heading (exact match, case-insensitive), then extracts the
   first subsection that follows it. `schedule_name` is derived from that subsection's heading
   by stripping a leading `Section N –` or `Section N -` prefix
   (`r"^Section\s+\d+\s*[–\-]\s*"`). For 74E the subsection heading has no such prefix and
   is used as-is.

4. **Sub-schedules** (`_extract_sub_schedule`): Reads the parent's `.md` file, finds the
   section whose heading starts with the sub-schedule's prefix (e.g. `"Schedule 51A:"`), and
   uses that section's body as the description. If the section has no body text, falls back to
   the parent schedule's General Information section.

### Why markdown_clean/ Simplifies Extraction

The original `markdown/` files had several heading irregularities that required workarounds:

- **74D "second occurrence"**: The old file had two `Schedule 74D` headings (one in an
  overview, one marking the actual content). `_extract_schedule_74d` skipped the first. The
  clean file has exactly one `## **Schedule 74D**`; no skip logic is needed.
- **74E "exact match"**: The old file had a variant heading `"Schedule 74E - Asset Retirement
  Obligation Liability"` that required exact matching to avoid false hits. The clean file has
  only `## **Schedule 74E**`; this variant no longer exists.

The unified `_extract_schedule_74x` is simpler than the two functions it replaces.

### Storage

Unchanged from Task 04: application-layer deduplication before inserting, because PostgreSQL's
unique constraint on `(schedule, valid_from_year, valid_to_year)` does not treat `NULL = NULL`.

The extracted data is saved as a CSV at `fir_instructions/exports/baseline_schedule_meta.csv`.

## Tests

**Schedule metadata extraction**
- [x] `TestExtractSchedule74X` — name derivation with/without `Section N` prefix, missing
  heading, missing subsection, null year fields
- [x] `TestExtractScheduleRecordDispatcher` — 74A, 74D, and 74E all route to `_extract_schedule_74x`
- [x] `TestExtractAllScheduleMeta.test_returns_35_records_from_real_files` — uses `markdown_clean/`

**Baseline CSV content**
- [x] `test_exactly_35_records` (was 32)

**Schedule metadata insertion**
- [x] `test_insert_all_35_baseline_records` (was 32)
- [x] `test_all_35_codes_in_db` (was 32)

## Verification

```bash
# Unit + integration tests
uv run pytest tests/fir_instructions/test_extract_schedule_meta.py -v

# Extract and check row count
uv run src/municipal_finances/app.py extract-baseline-schedule-meta \
  --markdown-dir fir_instructions/source_files/2025/markdown_clean \
  --no-load-db

# CSV should have header + 35 data rows
wc -l fir_instructions/exports/baseline_schedule_meta.csv
```
