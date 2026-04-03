# Task 08b: Infer Changes from Data (Phase 3)

## Goal

For FIR years without instructions PDFs, infer structural changes (new/deleted lines, label changes) by comparing adjacent years of `firrecord` data. Store inferred changes in `fir_instruction_changelog` with `source = "data_inferred"` and create corresponding metadata version rows.

## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- Task 07 (Phase 2 versioning) complete
- Task 08a (reporting completeness) complete — provides the set of municipalities that have reported for each year, used to filter inference queries
- `firrecord` data loaded for the years being compared

## Task List

- [ ] Create inference module at `src/municipal_finances/fir_instructions/infer_changes.py`
- [ ] Implement SQL-based diff logic for adjacent year pairs
- [ ] Run inference for all adjacent year pairs where at least one year lacks a PDF
- [ ] Insert inferred changes into `fir_instruction_changelog`
- [ ] Create metadata version rows for inferred changes
- [ ] Add CLI command to trigger inference
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Inference Logic

Three types of inferred changes:

**1. New SLCs** (present in year Y, absent in Y-1):
```sql
SELECT DISTINCT r.slc, r.schedule_line_desc, r.schedule_column_desc
FROM firrecord r
WHERE r.marsyear = :year
AND r.slc NOT IN (SELECT DISTINCT slc FROM firrecord WHERE marsyear = :prev_year)
```

**2. Deleted SLCs** (present in Y-1, absent in Y):
```sql
SELECT DISTINCT r.slc, r.schedule_line_desc, r.schedule_column_desc
FROM firrecord r
WHERE r.marsyear = :prev_year
AND r.slc NOT IN (SELECT DISTINCT slc FROM firrecord WHERE marsyear = :year)
```

**3. Label changes** (same SLC, different description):
```sql
SELECT a.slc, a.schedule_line_desc AS old_desc, b.schedule_line_desc AS new_desc
FROM (SELECT DISTINCT slc, schedule_line_desc FROM firrecord WHERE marsyear = :prev_year) a
JOIN (SELECT DISTINCT slc, schedule_line_desc FROM firrecord WHERE marsyear = :year) b
  ON a.slc = b.slc AND a.schedule_line_desc != b.schedule_line_desc
```

### Year Pairs to Process

Run for all adjacent years where data exists but no PDF is available. Assuming data exists for years 2009–2025 and PDFs exist for 2019–2025:
- 2009→2010, 2010→2011, ..., 2017→2018 (all pre-PDF years)
- Also run 2018→2019 to catch changes at the boundary

For years where PDFs exist (2019→2020, 2020→2021, 2021→2022, 2022→2023, 2023→2024, 2024→2025), inference should still run as a cross-check against the PDF changelog (reconciliation per the audit plan).

### CLI Command

```bash
# Infer changes for all year pairs without PDFs
uv run src/municipal_finances/app.py infer-changes

# Infer changes for a specific year transition
uv run src/municipal_finances/app.py infer-changes --year 2017

# Include cross-check years (where PDFs also exist)
uv run src/municipal_finances/app.py infer-changes --include-pdf-years
```

### Handling Noise

Per the plan's limitations section:
- A line absent in year Y might have no municipalities reporting, not a real deletion. **Mitigation**: restrict inference queries to municipalities that have reported for year Y (per Task 08a), then require the SLC to be present in at least N of those reporting municipalities (e.g., 3) to filter out single-municipality anomalies. Using reporting municipalities as the denominator avoids false deletions caused by whole-year non-reporters.
- Label drift in `schedule_line_desc` may be formatting changes. **Mitigation**: normalize whitespace and case before comparing. Only flag changes where the normalized text differs by more than minor formatting.

### Storing Inferred Changes

For each inferred change, create a `fir_instruction_changelog` row:
- `source = "data_inferred"`
- `change_type`: `inferred_new`, `inferred_deleted`, or `inferred_label_change`
- `severity`: NULL (not applicable for inferred changes)
- `description`: auto-generated (e.g., `"SLC 40 0410 01 appears in 2021 data but not 2020"`)

### Creating Metadata Rows

Per the plan:
- **Inferred new in year Y**: set `valid_from_year = Y` on the metadata row; `change_notes = "New in FIR{Y} (inferred from data)"`
- **Inferred deleted in year Y**: set `valid_to_year = Y - 1` on the metadata row; `change_notes = "Removed in FIR{Y} (inferred from data)"`
- **Label changes**: don't create new version rows — just log in changelog for review

## Tests

- [ ] Test inference with controlled test data (seed specific years with known differences)
- [ ] Test noise filtering (SLC in only 1 municipality is excluded)
- [ ] Test label normalization (whitespace-only changes are excluded)
- [ ] Test changelog insertion with `source = "data_inferred"`
- [ ] Test CLI command with `--year` flag
- [ ] Test idempotent execution (running twice doesn't create duplicates)

## Documentation Updates

- [ ] Add `infer-changes` command to `CLAUDE.md` "Common commands"
- [ ] Update `CLAUDE.md` "Database" section to mention inference workflow

## Success Criteria

- Inferred changes are stored in `fir_instruction_changelog` with correct `source` and `change_type`
- Noise filtering reduces false positives (SLC present in <3 municipalities, whitespace-only label changes)
- For PDF-covered years (2019–2025), inferred changes can be compared against `pdf_changelog` entries for reconciliation
- CLI command runs successfully and reports counts

## Verification

```sql
-- Inferred change counts by year
SELECT year, change_type, count(*)
FROM fir_instruction_changelog
WHERE source = 'data_inferred'
GROUP BY year, change_type
ORDER BY year, change_type;

-- Reconciliation: inferred changes that match PDF changelog
SELECT ic.year, ic.schedule, ic.slc_pattern, ic.change_type
FROM fir_instruction_changelog ic
WHERE ic.source = 'data_inferred'
AND ic.year BETWEEN 2019 AND 2025
AND EXISTS (
    SELECT 1 FROM fir_instruction_changelog pc
    WHERE pc.source = 'pdf_changelog'
    AND pc.year = ic.year
    AND pc.schedule = ic.schedule
);

-- Inferred changes NOT in PDF changelog (potential data anomalies)
SELECT ic.*
FROM fir_instruction_changelog ic
WHERE ic.source = 'data_inferred'
AND ic.year BETWEEN 2019 AND 2025
AND NOT EXISTS (
    SELECT 1 FROM fir_instruction_changelog pc
    WHERE pc.source = 'pdf_changelog'
    AND pc.year = ic.year
    AND pc.schedule = ic.schedule
    AND (pc.line_id = ic.line_id OR (pc.line_id IS NULL AND ic.line_id IS NULL))
);
```

## Additional Considerations

1. The municipality count threshold should be configurable in case it needs to be adjusted to get better results. 3 is a reasonable starting point, but some legitimate lines might only be used by a few municipalities (e.g., "City of Toronto only" lines).
2. The inference queries can be expensive on 13.5M+ rows. Add indexes to optimize; likely candidates: composite index on `(marsyear, slc)`.
3. For label changes, compute a similarity score (e.g., Levenshtein distance) to distinguish formatting changes from real renames. The score should be computed after normalization (e.g. removal of preceding or trailing whitespace).
4. Interaction of inferred changes interact with existing PDF-documented version rows: if the PDF says a line was added in 2023, but inference also detects it, the inferred entry should also be kept for completeness. Duplicates should then be flagged and resolved in the reconciliation audit step.
5. The full available year range for `firrecord` data should be loaded (2000-2025)
