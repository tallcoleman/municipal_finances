# Task 07: Apply Documented Changes Backwards (Phase 2)

## Goal

Using the changelog from Task 03, create versioned rows in the metadata tables by reading the older PDFs (2024, 2023, 2022, 2021, 2020, and 2019) and extracting prior-version descriptions for anything that changed.

## Prerequisites

- Task 03 (changelog extraction) complete — provides the list of what changed each year
- Tasks 04–06 (FIR2025 baseline) complete — provides the current-version rows to version
- Task 02 (SLC parsing) complete

## Task List

- [ ] Conduct a light-weight check to determine if there are format differences in the PDFs in `fir_instructions/source_files/` that need to be handled for the changes to be properly parsed and processed. Try to avoid reading and parsing whole PDFs - focus instead on the table of contents, headings, and sampling a small number of pages from each relevant section.
- [ ] Process FIR2024 changes (~10 entries, minor)
  - [ ] For each changelog entry: read the relevant section in FIR2024 PDF
  - [ ] Create prior-version rows with old descriptions
  - [ ] Update existing (2025) rows' `valid_from_year` to 2025
  - [ ] Set new (prior) rows' `valid_from_year` and `valid_to_year` appropriately
- [ ] Process FIR2023 changes (~50+ entries, major)
  - [ ] Handle new schedules: 71, 74E (set `valid_from_year = 2023`)
  - [ ] Handle deleted schedules: 51C, 79, 80B (create rows with `valid_to_year = 2022`)
  - [ ] For each line/column change: extract prior-version from FIR2022 PDF
- [ ] Process FIR2022 changes (~40 entries)
  - [ ] For each changelog entry: read the relevant section in FIR2022 or FIR2021 PDF
  - [ ] Create prior-version rows
- [ ] Process FIR2021 changes - assess changelog entries to determine sub-steps required
- [ ] Process FIR2020 changes - assess changelog entries to determine sub-steps required
- [ ] Process FIR2019 changes - assess changelog entries to determine sub-steps required
- [ ] Set `change_notes` on all versioned rows from the changelog description
- [ ] Export updated CSVs
- [ ] Verify version ranges don't overlap

## Implementation Details

### Versioning Procedure

For each changelog entry documenting a change in year Y:

**Line/column updated in year Y:**
1. Read the prior version's PDF (year Y-1 or the most recent available) to extract the old description
2. Create a new metadata row with the old content and `valid_to_year = Y - 1`
3. Update the existing row's `valid_from_year = Y`
4. Copy `change_notes` from the changelog `description` to both rows

**Line/column added in year Y:**
1. Update the existing baseline row's `valid_from_year = Y`
2. Set `change_notes` from the changelog

**Line/column deleted in year Y:**
1. Update the existing baseline row's `valid_to_year = Y - 1`
2. Set `change_notes` from the changelog

**Schedule added in year Y:**
1. Update `fir_schedule_meta` row's `valid_from_year = Y`
2. Update all associated line and column rows' `valid_from_year = Y`

**Schedule deleted in year Y:**
1. Set `valid_to_year = Y - 1` on the schedule meta row
2. Create line/column rows from the older PDF with `valid_to_year = Y - 1`

### Work Order

Process changes in reverse chronological order (most recent first):
1. **2025 changes**: Already captured in baseline. Only need to mark `valid_from_year = 2025` on affected rows.
2. **2024 changes**: ~10 entries. Read FIR2024 PDF for prior versions.
3. **2023 changes**: ~50+ entries. The largest set. Includes schedule-level changes. Read FIR2022 PDF for prior versions.
4. **2022 changes**: ~40 entries. Read FIR2021 PDF for prior versions.
5. **2021 changes:** scope of changes not yet assessed
6. **2020 changes:** scope of changes not yet assessed
7. **2019 changes:** scope of changes not yet assessed

### Handling FIR2023 Major Changes

FIR2023 had structural changes driven by PSAB standards PS 3280 and PS 3450:
- **New schedules**: 71 (Remeasurement Gains & Losses), 74E (Long Term Liabilities detail)
- **Deleted schedules**: 51C, 79, 80B
- These require both schedule-level and line/column-level version entries

### Deleted Schedule Extraction

For schedules that were deleted (51C, 79, 80B in 2023), we need to:
1. Read the FIR2022 PDF to extract the full schedule metadata, line metadata, and column metadata
2. Create rows with `valid_to_year = 2022`
3. These lines/columns won't exist in the 2025 baseline, so they're entirely new rows

## Tests

- [ ] Test that version ranges don't overlap for any (schedule, line_id) pair
- [ ] Test that `valid_from_year` is set correctly on updated baseline rows
- [ ] Test that new prior-version rows have correct `valid_to_year`
- [ ] Test that `change_notes` is populated on all versioned rows
- [ ] Test the version range query logic: `WHERE (valid_from_year IS NULL OR valid_from_year <= Y) AND (valid_to_year IS NULL OR valid_to_year >= Y)` returns exactly one row per (schedule, line_id) for each year 2019–2025

## Documentation Updates

- [ ] None expected

## Success Criteria

- For every changelog entry, the corresponding metadata row has been versioned
- No overlapping version ranges for the same (schedule, line_id) or (schedule, column_id)
- Deleted schedules (51C, 79, 80B) have complete metadata with `valid_to_year = 2022`
- New schedules (71, 74E) have `valid_from_year = 2023`
- Querying for any year 2019–2025 returns a consistent, non-overlapping set of metadata

## Verification

```sql
-- Check for overlapping version ranges (should return 0)
SELECT a.schedule, a.line_id, a.valid_from_year, a.valid_to_year,
       b.valid_from_year as b_from, b.valid_to_year as b_to
FROM fir_line_meta a
JOIN fir_line_meta b ON a.schedule = b.schedule AND a.line_id = b.line_id AND a.id < b.id
WHERE (a.valid_from_year IS NULL OR a.valid_from_year <= COALESCE(b.valid_to_year, 9999))
  AND (a.valid_to_year IS NULL OR a.valid_to_year >= COALESCE(b.valid_from_year, 0));

-- Verify deleted schedules have valid_to_year
SELECT * FROM fir_schedule_meta WHERE schedule IN ('51C', '79', '80B');

-- Verify new schedules have valid_from_year
SELECT * FROM fir_schedule_meta WHERE schedule IN ('71', '74E');

-- Count versioned rows (should be > 0 for each year)
SELECT valid_from_year, count(*) FROM fir_line_meta WHERE valid_from_year IS NOT NULL GROUP BY valid_from_year;

-- Changelog entries without corresponding versioned rows (should be empty after this task)
SELECT cl.* FROM fir_instruction_changelog cl
WHERE cl.source = 'pdf_changelog'
AND NOT EXISTS (
    SELECT 1 FROM fir_line_meta lm
    WHERE lm.schedule = cl.schedule
    AND lm.valid_from_year IS NOT NULL
    AND lm.change_notes IS NOT NULL
)
AND cl.line_id IS NOT NULL;
```

## Additional Considerations

1. When a line's description has changed but its `includes`/`excludes` did not change (or vice versa), the prior-version row can copy the unchanged fields from the current version.
2. For changes described as "updated" in the changelog — some may be trivial (typo fixes, wording tweaks). Versioned rows should still be created for these changes, since the change is specifically noted in the change log.
3. The overlap check query above handles NULLs in version ranges. Consider whether it would be feasible to add an application-level check to prevent overlap (adding the constraint in Postgres directly may be too complex). If an application-level check is added, make sure that it actually runs when the CLI is used to load or update rows.
