# Task 03: Extract Content Changes Tables from PDFs (Phase 0)

## Goal

Extract every row from the "Content Changes" attachment in each FIR Instructions PDF (2019–2025) and store them in the `fir_instruction_changelog` table with `source = "pdf_changelog"`. This is the fastest extraction step and determines the full scope of versioning work.

## Task List

- [ ] Create extraction script/module at `src/municipal_finances/fir_instructions/extract_changelog.py`
- [ ] Extract Content Changes from FIR2025 PDF (~page 43, ~7 entries)
- [ ] Extract Content Changes from FIR2024 PDF (~page 30, ~10 entries)
- [ ] Extract Content Changes from FIR2023 PDF (~page 29, ~50+ entries)
- [ ] Extract Content Changes from FIR2022 PDF (~pages 29–31, ~40 entries)
- [ ] Extract Content Changes from FIR2021 PDF (pages 29-30)
- [ ] Extract Content Changes from FIR2020 PDF (page 29)
- [ ] Extract Content Changes from FIR2019 PDF (page 29)
- [ ] Store all entries in `fir_instruction_changelog`
- [ ] Verify extracted data against PDFs
- [ ] Write tests for the storage/loading logic

## Implementation Details

### Extraction Approach

The Content Changes sections are structured tables with consistent columns:
- Schedule
- SLC (the specific code affected)
- Heading (line or column name)
- Description (what changed)

The PDFs may also distinguish between "Major Changes" and "Minor Changes" sections, which maps to the `severity` field. If the PDFs do not distinguish between "Major Changes" and "Minor Changes", infer the severity based on the data from PDFs that do make this distinction.

### Recommended Extraction Workflow

1. Read the relevant pages from each PDF using Claude's PDF reading capability
2. For each row in the table, create a `FIRInstructionChangelog` record:
   - `year`: the FIR year (2022, 2023, 2024, or 2025)
   - `schedule`: parsed from the Schedule column
   - `slc_pattern`: the raw SLC value from the PDF (may contain wildcards like `xx`)
   - `line_id`: parsed from `slc_pattern` if deterministic (not `xxxx`)
   - `column_id`: parsed from `slc_pattern` if deterministic (not `xx`)
   - `heading`: the Heading column from the PDF
   - `change_type`: inferred from context — `new_schedule`, `deleted_schedule`, `new_line`, `deleted_line`, `updated_line`, `new_column`, `deleted_column`, `updated_column`
   - `severity`: `"major"` or `"minor"` based on which section it appeared in, or based on inference if not divided by "Major Changes" and "Minor Changes" sections or similar
   - `description`: verbatim from the Description column
   - `source`: `"pdf_changelog"`
3. Use `pdf_slc_to_components()` from `slc.py` (Task 02) to parse the SLC patterns

### Storage Module

Create a function to insert changelog entries:

```python
def insert_changelog_entries(engine, entries: list[dict]):
    """Insert changelog entries, skipping duplicates."""
    # Use INSERT ... ON CONFLICT DO NOTHING with appropriate conflict target
```

### Data File Approach

Since PDF extraction is expensive and non-deterministic, the extracted data should also be saved as a CSV file at `fir_instructions/exports/fir_instruction_changelog.csv` as part of this task. This allows re-loading without re-extraction as well as human verification and editing to make corrections.

### Known Change Volumes

- Change volumes for 2019–2021 have not been assessed.
- FIR2022: ~40 entries (new lines/columns in Schedules 61, 72B)
- FIR2023: ~50+ entries (major — new schedules 71, 74E; deleted 51C, 79, 80B)
- FIR2024: ~10 entries (minor)
- FIR2025: ~7 entries (minor)

Total: ~107+ changelog entries from assessed PDFs.

## Tests

- [ ] Test `insert_changelog_entries` with valid data
- [ ] Test idempotent insertion (inserting same data twice doesn't create duplicates)
- [ ] Test that `change_type` values are all from the allowed set
- [ ] Test SLC pattern parsing for wildcard patterns (e.g., `"40 xxxx 05"`)
- [ ] Test loading from exported CSV

## Documentation Updates

- [ ] Add a short description to the README about the folder structure that the output CSV files are stored in.

## Success Criteria

- All Content Changes entries from all four PDFs are in `fir_instruction_changelog`
- `source` is `"pdf_changelog"` for all entries
- `severity` correctly reflects major vs. minor classification
- `change_type` is assigned correctly based on the description context
- SLC patterns are parsed and `line_id`/`column_id` populated where deterministic
- Exported CSV contains all entries and can be reloaded cleanly
- Spot-check 10 entries per PDF against the actual PDF content

## Verification

After extraction, run these validation queries:

```sql
-- Count by year
SELECT year, count(*) FROM fir_instruction_changelog WHERE source = 'pdf_changelog' GROUP BY year ORDER BY year;

-- Check severity distribution
SELECT year, severity, count(*) FROM fir_instruction_changelog WHERE source = 'pdf_changelog' GROUP BY year, severity ORDER BY year;

-- Check change_type distribution
SELECT change_type, count(*) FROM fir_instruction_changelog WHERE source = 'pdf_changelog' GROUP BY change_type;

-- Look for entries with unparsed SLC patterns
SELECT * FROM fir_instruction_changelog WHERE line_id IS NULL AND slc_pattern NOT LIKE '%xxxx%';
```

## Additional Considerations

1. Assess whether the Content Changes tables in the PDFs are consistently formatted across all four years, or if there are differences in the layout between years. This affects whether a single extraction template works.
2. Entries where the description references multiple changes (e.g., "New lines 0410, 0420, 0430 added") should be split into separate rows, not kept as one row.
3. Some Content Changes entries describe changes to schedule-level properties (not specific lines/columns). These should be reflected in the schedule versions tracked by the `fir_schedule_meta` table.
4. Try different methods of PDF text extraction to determine what works best. First option would be to try a Python PDF library (e.g., pdfplumber), and if the success criteria are not met, then have Claude read the PDF pages directly.
