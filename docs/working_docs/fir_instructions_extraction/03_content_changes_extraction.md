# Task 03: Extract Content Changes Tables from PDFs (Phase 0)

## Goal

Extract every row from the "Content Changes" extracts for each FIR Instructions PDF (2019–2025) and store them in the `fir_instruction_changelog` table with `source = "pdf_changelog"`. This is the fastest extraction step and determines the full scope of versioning work.

The content changes extracts are available in `fir_instructions/change_logs/`.

## Task List

- [ ] Create extraction script/module at `src/municipal_finances/fir_instructions/extract_changelog.py`
- [ ] Extract Content Changes from FIR2025 Changes PDF (~7 entries)
- [ ] Extract Content Changes from FIR2024 Changes PDF (~10 entries)
- [ ] Extract Content Changes from FIR2023 Changes PDF (~50+ entries)
- [ ] Extract Content Changes from FIR2022 Changes PDF (~40 entries)
- [ ] Extract Content Changes from FIR2021 Changes PDF
- [ ] Extract Content Changes from FIR2020 Changes PDF
- [ ] Extract Content Changes from FIR2019 Changes PDF
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
   - `year`: the FIR year (2019, 2020, 2021, 2022, 2023, 2024, or 2025)
   - `schedule`: parsed from the Schedule column
   - `slc_pattern`: the raw SLC value from the PDF (may contain wildcards like `xx`)
   - `line_id`: parsed from `slc_pattern` if deterministic (not `xxxx`)
   - `column_id`: parsed from `slc_pattern` if deterministic (not `xx`)
   - `heading`: the Heading column from the PDF
   - `change_type`: inferred from context — `new_schedule`, `deleted_schedule`, `new_line`, `deleted_line`, `updated_line`, `new_column`, `deleted_column`, `updated_column`
   - `severity`: `"major"` or `"minor"` based on which section it appeared in, or based on inference if not divided by "Major Changes" and "Minor Changes" sections
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

- All Content Changes entries from all seven PDFs are in `fir_instruction_changelog`
- `source` is `"pdf_changelog"` for all entries
- `severity` correctly reflects major vs. minor classification (where provided)
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

1. The content changes tables in the PDFs often start with some instructions that should not be parsed into change entries.
2. Values for the "Sch."/"Schedule", "SLC", and "Heading" columns in the PDF are sometimes only provided for the first row where the value is different from the prior rows, and not repeated for every applicable row. If the value in one of these columns is blank, it is likely meant to be the value from the first non-blank row prior. An exception to this may be schedule 22C in the 2022 PDF, where there is a much longer comment in the description column that appears to span multiple rows. The prior non-blank value for a column also does not apply in cases where a higher-level value has changed (e.g. SLC should not be inferred from the first non-blank value above when "Sch."/"Schedule" has changed).
3. Entries where the description references multiple changes (e.g., "New lines 0410, 0420, 0430 added") should be split into separate rows, not kept as one row.
4. Some Content Changes entries describe changes to schedule-level properties (not specific lines/columns). These should be reflected in the schedule versions tracked by the `fir_schedule_meta` table.
5. Try different methods of PDF text extraction to determine what works best. First option would be to try a Python PDF library (e.g., pdfplumber), and if the success criteria are not met, then have Claude read the PDF pages directly.
