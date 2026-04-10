# Task 04: Extract FIR2025 Baseline — Schedule Metadata

## Goal

Extract schedule-level metadata from the FIR2025 Instructions PDF and populate `fir_schedule_meta` for all 31 schedules. This is the first part of the Phase 1 baseline extraction.

## Task List

- [x] Check that category assignments in the plan match the categories used in the PDFs; if differences exist, note them and suggest a normalization approach
- [x] For each schedule, locate and extract the General Information section from the per-schedule markdown files
- [x] Create `fir_schedule_meta` rows for all 31 schedule codes
- [x] Set `valid_from_year = NULL` and `valid_to_year = NULL` on all rows (baseline = "always current")
- [x] Write insertion logic
- [x] Export to CSV
- [x] Verify against PDF

## Implementation Details

### Schedules to Extract

The FIR system has 31 distinct schedule codes that warrant a row in `fir_schedule_meta`.
Some codes (22A, 22B, 22C, 51A, 51B, 61A, 61B) are sub-schedules that share a markdown file
with their parent; they have no independent file but are tracked as separate
metadata rows because municipalities report on them separately.

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
| Long Term Liabilities | 74, 74E |
| Other Information | 76, 77, 80, 80D, 81, 83 |

> **Note on sub-schedules**: 22A/22B/22C, 51A/51B, and 61A/61B do not have their own
> markdown files. Their instructions appear within the parent schedule's file (22, 51,
> and 61 respectively). Extraction for these codes locates the sub-schedule's section
> heading within the parent file.
>
> **Note on 80D**: Schedule 80D has its own markdown file and is treated as a
> first-class schedule.

### Fields to Extract Per Schedule

- `schedule`: From the schedule number (e.g., `"10"`, `"51A"`)
- `schedule_name`: Full title (e.g., `"Consolidated Statement of Operations: Revenue"`)
- `category`: From the table above
- `description`: The entire General Information section for the schedule. For sub-schedules
  (22A/B/C, 51A/B, 61A/61B), the description comes from the sub-schedule's own section body
  within the parent file; if that body is empty, the parent's General Information section is
  used as a fallback.
- `valid_from_year`: NULL (baseline)
- `valid_to_year`: NULL (baseline)
- `change_notes`: NULL (baseline, no changes to note)

### Source Files

Each schedule's instructions are stored as a per-schedule markdown file produced by the
`convert-folder` CLI command (one `.md` per PDF):

```
fir_instructions/source_files/2025/markdown/FIR2025 S{code}.md
```

Sub-schedules (22A/B/C, 51A/B, 61A/61B) and Schedule 74E are embedded within their
parent's file:

| Code | File |
|---|---|
| 22A, 22B, 22C | `FIR2025 S22.md` |
| 51A, 51B | `FIR2025 S51.md` |
| 61A, 61B | `FIR2025 S61.md` |
| 74E | `FIR2025 S74.md` |

### Extraction Approach

The extractor (`extract_schedule_meta.py`) dispatches to one of four extractors based on the schedule code:

1. **Regular schedules** (`_extract_regular_schedule`): Reads `FIR2025 S{code}.md`, finds the
   schedule name from the `SCHEDULE {code}: Name` body heading, and extracts the `General
   Information` / `General Instructions` section content as the description.

2. **Schedule 53** (`_extract_schedule_53`): Special case — no General Information heading.
   Uses the content of the first section following the `SCHEDULE 53:` body heading.

3. **Schedule 74E** (`_extract_schedule_74e`): Embedded in `FIR2025 S74.md`. Locates the
   exact `Schedule 74E` heading, then extracts the `Asset Retirement Obligation Liability`
   sub-section that follows.

4. **Sub-schedules** (`_extract_sub_schedule`): Reads the parent's `.md` file, finds the
   section whose heading starts with the sub-schedule's prefix (e.g. `"Schedule 51A:"`), and
   uses that section's body as the description. If the section has no body text, falls back to
   the parent schedule's General Information section.

Inline markdown formatting (e.g. `**bold**`) is preserved in description text.

### Storage

The `insert_schedule_meta` function uses application-layer deduplication before inserting,
because PostgreSQL's unique constraint on `(schedule, valid_from_year, valid_to_year)` does
not treat `NULL = NULL`, so `ON CONFLICT DO NOTHING` cannot deduplicate baseline rows where
both year columns are NULL.

The extracted data is saved as a CSV at `fir_instructions/exports/baseline_schedule_meta.csv`
to allow re-loading without re-extraction as well as human verification and editing.

## Tests

**Schedule metadata extraction**
- [x] Test `_parse_md_sections` correctly splits a markdown file into (heading, content) tuples
- [x] Test `_clean_md_content` normalises whitespace and preserves `**bold**` markers
- [x] Test `_find_section` prefix/exact matching, case-insensitivity, and start offset
- [x] Test `_extract_sub_schedule_name` strips `Schedule XX:` prefix and `(XX)` suffix
- [x] Test `_extract_regular_schedule` against synthetic markdown files
- [x] Test `_extract_schedule_53` against synthetic markdown files
- [x] Test `_extract_schedule_74e` against synthetic markdown files
- [x] Test `_extract_sub_schedule` against synthetic markdown files, including the GI fallback when the sub-schedule section has no body text
- [x] Test `extract_all_schedule_meta` returns 31 records from real files

**Baseline CSV content**
- [x] Test that all 31 schedule codes are present in the CSV
- [x] Test that no schedule names are empty (except S71, which has no source file)
- [x] Test that no descriptions are empty (except S71)
- [x] Test that all categories match the known set
- [x] Test that descriptions preserve `**bold**` markers

**Schedule metadata insertion**
- [x] Test insertion of schedule metadata records
- [x] Test that all 31 schedule codes are present after insertion
- [x] Test idempotent insertion (re-inserting same data doesn't create duplicates)
- [x] Test that `schedule` values match the known schedule list
- [x] Test that no required fields are NULL (schedule, schedule_name, category)

## Documentation Updates

- [x] None expected (no new CLI commands)

## Success Criteria

- `fir_schedule_meta` contains exactly 31 rows (one per schedule code)
- Every row has a non-empty `schedule_name`, `category`, and `description`
- `schedule` values match the known set of 31 codes for 2025
- `valid_from_year` and `valid_to_year` are both NULL on all baseline rows
- Spot-check 5 schedule descriptions against the FIR2025 PDF (10, 40, 22A, 74, 53)

## Verification

```sql
-- Should return 31
SELECT count(*) FROM fir_schedule_meta;

-- All categories should match expected set
SELECT DISTINCT category FROM fir_schedule_meta ORDER BY category;

-- No empty names or descriptions
SELECT * FROM fir_schedule_meta WHERE schedule_name IS NULL OR schedule_name = '' OR description IS NULL OR description = '';
```
