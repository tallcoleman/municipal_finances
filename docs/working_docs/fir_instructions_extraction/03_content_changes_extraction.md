# Task 03: Load Content Changes Tables into Database (Phase 0)

## Goal

Load every row from the manually-extracted Content Changes CSVs (2019–2025) into the `fir_instruction_changelog` table with `source = "pdf_changelog"`. This is the fastest extraction step and determines the full scope of versioning work.

The manually-extracted CSVs are available in `fir_instructions/change_logs/semantic_extraction/`, one file per year (e.g., `FIR2025 Changes.csv`).

## Task List

- [ ] Create loading script/module at `src/municipal_finances/fir_instructions/extract_changelog.py`
- [ ] Parse and load `FIR2019 Changes.csv`
- [ ] Parse and load `FIR2020 Changes.csv`
- [ ] Parse and load `FIR2021 Changes.csv`
- [ ] Parse and load `FIR2022 Changes.csv`
- [ ] Parse and load `FIR2023 Changes.csv`
- [ ] Parse and load `FIR2024 Changes.csv`
- [ ] Parse and load `FIR2025 Changes.csv`
- [ ] Identify and tag entries that describe schedule-level changes (not specific lines/columns) — these should inform `fir_schedule_meta` versioning in Task 07
- [ ] Store all entries in `fir_instruction_changelog`
- [ ] Verify loaded data against the source CSVs
- [ ] Write tests for the storage/loading logic

## Implementation Details

### Source Data Format

The manually-extracted CSVs in `fir_instructions/change_logs/semantic_extraction/` have the following columns:

- `Schedule` — the schedule code (e.g., `10`, `22A`)
- `SLC` — the SLC pattern in PDF format (e.g., `10 6021 01`, `22 xxxx 01`)
- `Heading` — the line or column heading
- `Description` — what changed
- `Section Description` — the section header from the PDF (e.g., `Major Changes:`, `Minor Changes:`); used to populate the `severity` field

### Recommended Loading Workflow

1. Read each CSV from `fir_instructions/change_logs/semantic_extraction/`
2. Infer the `year` from the filename (e.g., `FIR2025 Changes.csv` → `2025`)
3. For each row, create a `FIRInstructionChangelog` record:
   - `year`: the FIR year (2019–2025)
   - `schedule`: from the `Schedule` column
   - `slc_pattern`: the raw SLC value from the `SLC` column
   - `line_id`: parsed from `slc_pattern` if deterministic (not `xxxx`)
   - `column_id`: parsed from `slc_pattern` if deterministic (not `xx`)
   - `heading`: from the `Heading` column
   - `change_type`: inferred from context — `new_schedule`, `deleted_schedule`, `new_line`, `deleted_line`, `updated_line`, `new_column`, `deleted_column`, `updated_column`
   - `severity`: `"major"` or `"minor"` — see **Severity Inference** below
   - `description`: verbatim from the `Description` column
   - `source`: `"pdf_changelog"`
4. Use `pdf_slc_to_components()` from `slc.py` (Task 02) to parse the SLC patterns. Entries with `xxxx` or `xx` wildcards are stored as-is with `line_id = None` or `column_id = None` respectively — see **Wildcard SLC Resolution** for how these are resolved in later tasks.

### Severity Inference

Only 2023–2025 have explicit major/minor labels. For 2019–2022 (and any rows in other years that lack a label), apply the following tiers in order, stopping at the first that yields a clear signal:

**Tier 1 — Explicit label in `Section Description`**

Scan `Section Description` (case-insensitive) for the words "major" or "minor". If found, use that label directly. This covers all 2023–2025 rows.

**Tier 2 — Structural scope of `change_type`**

Some change types are inherently high-impact regardless of year:

- `new_schedule` or `deleted_schedule` → **major**
- `new_line` or `deleted_line` where the SLC pattern uses `xxxx` (affects all lines on a schedule) → **major**
- `new_column` or `deleted_column` where the SLC pattern uses `xx` (affects all columns on a schedule) → **major**

**Tier 3 — Description keyword signals**

Scan the `Description` and `Section Description` fields for keywords:

| Signal | Severity |
|---|---|
| "eliminated", "new schedule", "replaced with", "adoption of new accounting standard", "new section" | major |
| "updated language", "referenced to", "linked from", "pre-populated", "calculated as", "restated as", "report the amount for", "is reported on" | minor |

Apply the stronger signal if both appear. If signals conflict, prefer **Tier 4**.

**Tier 4 — Cross-year consistency**

For entries where Tiers 1–3 do not resolve severity: look for entries in 2023–2025 with the same `change_type` and similar `heading` or description pattern. Use the most common label among those labeled entries as the prior. For example, if all analogous column-heading updates in 2023 are labeled minor, treat the 2022 version as minor as well.

**Tier 5 — Default**

If none of the above yields a clear signal, assign **minor**. The majority of changes across all years are minor (text clarifications, cross-references, pre-population notes), so this is a conservative and appropriate default.

Note that 2019–2021 have no `Section Description` values at all, so these years will rely entirely on Tiers 2–5. The entries in those years are predominantly line additions for new revenue categories and wording updates — consistent with minor severity.

### Wildcard SLC Resolution

Many changelog entries have wildcards in either the line or column position:

- **Line wildcard** (`xxxx`): specific column, all lines — e.g., `61 xxxx 17` (new column 17 added to all lines of schedule 61)
- **Column wildcard** (`xx`): specific line, all columns — e.g., `61 0206 xx` (new line 0206 across all columns of schedule 61)

No whole-schedule `xxxx xx` patterns appear in the actual data.

Wildcard entries are stored in `fir_instruction_changelog` with `line_id = None` or `column_id = None` as appropriate, preserving the original `slc_pattern`. Resolving wildcards to specific line/column IDs is **deferred to Tasks 04–07** when the metadata tables are being built, because the purpose of resolution is to link changelog entries to specific `fir_line_meta` or `fir_column_meta` records.

#### Resolution approach

Resolution queries `firrecord` to find all distinct line or column IDs matching the wildcard. The appropriate year to query depends on the `change_type`:

| `change_type` | Query year |
|---|---|
| `new_line`, `new_column`, `updated_line`, `updated_column` | `change_year` |
| `deleted_line`, `deleted_column` | `change_year - 1` |

Use `parse_slc()` from `slc.py` to extract components from the `slc` field when processing results.

**Line wildcard** (`line_id = None, column_id = "17"`):
```sql
SELECT DISTINCT slc
FROM firrecord
WHERE slc LIKE 'slc.{schedule}.L%.C{column_id}.%'
  AND marsyear = {query_year}
```
Then parse each `slc` value with `parse_slc()` to extract `line_id`.

**Column wildcard** (`line_id = "0206", column_id = None`):
```sql
SELECT DISTINCT slc
FROM firrecord
WHERE slc LIKE 'slc.{schedule}.L{line_id}.C%.%'
  AND marsyear = {query_year}
```
Then parse each `slc` value with `parse_slc()` to extract `column_id`.

#### Edge cases

- **New lines with column wildcard** (e.g., `61 0206 xx`): the line is new, so only appears in `firrecord` from `change_year` onward. Query `marsyear = change_year`.
- **Multi-schedule columns** (e.g., `22 xxxx 01` for schedules 22A, 22B, 22C): each CSV row already names a specific schedule (22A, 22B, 22C separately), so query each schedule individually.
- **`firrecord` not yet loaded for a year**: if `marsyear = query_year` returns no rows for a schedule, log the unresolved entry. It can be resolved manually or once the data is available (note: data for years 2000–2019 was still loading at the time Task 03 was written).
- **Schedule-level entries** (`slc_pattern = None`): these describe whole-schedule changes and map to `fir_schedule_meta`, not individual lines/columns. Do not attempt wildcard resolution for these.

### Storage Module

Create a function to insert changelog entries:

```python
def insert_changelog_entries(engine, entries: list[dict]):
    """Insert changelog entries, skipping duplicates."""
    # Use INSERT ... ON CONFLICT DO NOTHING with appropriate conflict target
```

### Data File Approach

The source CSVs in `fir_instructions/change_logs/semantic_extraction/` are the authoritative input. After loading, also save a combined export at `fir_instructions/exports/fir_instruction_changelog.csv` for human verification and as a reload artifact (avoiding re-processing the per-year files).

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

- All Content Changes entries from all seven CSVs are in `fir_instruction_changelog`
- `source` is `"pdf_changelog"` for all entries
- `severity` correctly reflects major vs. minor classification (where provided)
- `change_type` is assigned correctly based on the description context
- SLC patterns are parsed and `line_id`/`column_id` populated where deterministic
- Exported CSV contains all entries and can be reloaded cleanly
- Spot-check 10 entries per year against the source CSV

## Verification

After loading, run these validation queries:

```sql
-- Count by year
SELECT year, count(*) FROM fir_instruction_changelog WHERE source = 'pdf_changelog' GROUP BY year ORDER BY year;

-- Check severity distribution
SELECT year, severity, count(*) FROM fir_instruction_changelog WHERE source = 'pdf_changelog' GROUP BY year, severity ORDER BY year;

-- Check change_type distribution
SELECT change_type, count(*) FROM fir_instruction_changelog WHERE source = 'pdf_changelog' GROUP BY change_type;

-- Count wildcard entries by type (should match expectations from the source CSVs)
SELECT
  CASE WHEN line_id IS NULL AND column_id IS NULL THEN 'both wildcards'
       WHEN line_id IS NULL THEN 'line wildcard (xxxx)'
       WHEN column_id IS NULL THEN 'column wildcard (xx)'
       ELSE 'deterministic'
  END AS slc_type,
  count(*)
FROM fir_instruction_changelog
WHERE source = 'pdf_changelog'
GROUP BY slc_type;

-- Look for entries where SLC was not parseable (neither deterministic nor a recognized wildcard)
SELECT * FROM fir_instruction_changelog
WHERE source = 'pdf_changelog'
  AND slc_pattern IS NOT NULL
  AND line_id IS NULL AND slc_pattern NOT LIKE '%xxxx%'
  AND column_id IS NULL AND slc_pattern NOT LIKE '%xx%';
```

## Additional Considerations

1. Only 2023–2025 have explicit major/minor labels in `Section Description`. Years 2019–2021 have no `Section Description` values at all; 2022 has group-level section notes (e.g., "The following are new lines added to all columns of Schedule 61:") that describe the nature of the change group but do not label severity. Apply the multi-tier **Severity Inference** approach for all rows lacking an explicit label.
2. The manually-extracted CSVs already have one row per affected SLC (multi-line PDF table comments have been resolved). No further text-based splitting is required at load time. Wildcard patterns (`xxxx`, `xx`) are the remaining source of one-to-many relationships and are handled via the deferred **Wildcard SLC Resolution** approach.
3. Some Content Changes entries describe changes to schedule-level properties (not specific lines/columns). These should be reflected in the schedule versions tracked by the `fir_schedule_meta` table.
