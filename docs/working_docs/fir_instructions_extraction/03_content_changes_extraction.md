# Task 03: Extract Content Changes Tables from PDFs (Phase 0)

## Goal

Extract every row from the "Content Changes" attachment in each FIR Instructions PDF (2022–2025) and store them in the `fir_instruction_changelog` table with `source = "pdf_changelog"`. This is the fastest extraction step and determines the full scope of versioning work.

## Task List

- [ ] Create extraction script/module at `src/municipal_finances/fir_instructions/extract_changelog.py`
- [ ] Extract Content Changes from FIR2025 PDF (~page 43, ~7 entries)
- [ ] Extract Content Changes from FIR2024 PDF (~page 30, ~10 entries)
- [ ] Extract Content Changes from FIR2023 PDF (~page 29, ~50+ entries)
- [ ] Extract Content Changes from FIR2022 PDF (~pages 29–31, ~40 entries)
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

The PDFs also distinguish between "Major Changes" and "Minor Changes" sections, which maps to the `severity` field.

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
   - `severity`: `"major"` or `"minor"` based on which section it appeared in
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

Since PDF extraction is expensive and non-deterministic, the extracted data should also be saved as a CSV file at `fir_instructions/exports/fir_instruction_changelog.csv` as part of this task. This allows re-loading without re-extraction.

### Known Change Volumes

- FIR2022: ~40 entries (new lines/columns in Schedules 61, 72B)
- FIR2023: ~50+ entries (major — new schedules 71, 74E; deleted 51C, 79, 80B)
- FIR2024: ~10 entries (minor)
- FIR2025: ~7 entries (minor)

Total: ~107+ changelog entries.

## Tests

- [ ] Test `insert_changelog_entries` with valid data
- [ ] Test idempotent insertion (inserting same data twice doesn't create duplicates)
- [ ] Test that `change_type` values are all from the allowed set
- [ ] Test SLC pattern parsing for wildcard patterns (e.g., `"40 xxxx 05"`)
- [ ] Test loading from exported CSV

## Documentation Updates

- [ ] None expected for this task (no new CLI commands yet)

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

## Questions

1. The Content Changes tables in the PDFs — are they consistently formatted across all four years, or do older PDFs use a different layout? This affects whether a single extraction template works.
2. How should we handle entries where the description references multiple changes (e.g., "New lines 0410, 0420, 0430 added")? Split into separate rows or keep as one?
3. Some Content Changes entries describe changes to schedule-level properties (not specific lines/columns). Should these have `change_type = "updated_schedule"` even though the plan doesn't list that as an option? Or use the closest match?
4. What's the best approach for the actual PDF text extraction — Claude reading the PDF pages directly, a Python PDF library (e.g., pdfplumber), or manual transcription? Each has different accuracy/effort tradeoffs.
