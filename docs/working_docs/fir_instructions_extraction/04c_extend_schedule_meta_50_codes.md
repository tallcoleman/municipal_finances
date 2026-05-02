# Task 04c: Extend Baseline Schedule Metadata to 50 Codes

## TODO - add the following

The values for Schedule 22A, 22B, and 22C are definitely missing from the source CSVs. They will need to be loaded from another one of the open data sources on the FIR site. [add details]

Need to validate the source CSVs to make sure the cleaning is working.
## Context

`validate-schedule-coverage` revealed 12 schedule codes present in the 2025 `firrecord` DB
but absent from `baseline_schedule_meta.csv`.  An additional 3 codes (54A, 77C, 77D) appear
in 2024 data.  The root causes are:

- **Schedule 02** was never added to `SCHEDULE_CATEGORIES` (plain script gap — `S02.md`
  exists with a `### General Instructions` section).
- **Sub-schedules** (22D, 24D, 26A/B, 54A/B, 72A/B, 77A–D, 80A/C) appear as real SLC
  codes in the data but were never added to the metadata catalogue or extractor.
- **22, 22A–C, 24, 62 absent from DB**: 22 and 24 data is stored entirely under `22D` and
  `24D` in the source CSVs (encoding difference, not missing data); 62 is genuinely absent
  from all loaded years.  Existing CSV rows for 22, 22A–C, 24 are kept as documentation.
  Investigation of the 22/24 encoding difference is deferred to a separate task.

This task extends the catalogue from **35 → 50** entries and adds the extraction logic.

## Task List

- [ ] Add 15 new codes to `SCHEDULE_CATEGORIES`
- [ ] Add `_PARENT_GI_FILE` dict
- [ ] Add `_PARENT_GI_NAMES` dict
- [ ] Add `_EMBEDDED_PARENT_FILE` dict
- [ ] Add `_extract_parent_gi_sub_schedule`
- [ ] Add `_extract_embedded_sub_schedule`
- [ ] Update dispatcher in `extract_schedule_record`
- [ ] Update docstrings (35 → 50)
- [ ] Add tests (`TestExtractParentGiSubSchedule`, `TestExtractEmbeddedSubSchedule`, dispatcher routing)
- [ ] Update count-based tests (35 → 50)
- [ ] Regenerate `fir_instructions/exports/baseline_schedule_meta.csv` (50 rows)

## New Schedule Codes (15 total)

| Code | Category | Extraction approach |
|---|---|---|
| 02 | Other Information | Regular extractor (`S02.md` `### General Instructions`) |
| 22D | Taxation | Parent GI — `S22.md` `## General Information` |
| 24D | Taxation | Parent GI — `S24.md` `## General Information` |
| 26A | Taxation | Parent GI — `S26.md` `## General Information` |
| 26B | Taxation | Parent GI — `S26.md` `## General Information` |
| 54A | Cash Flow | Embedded — `S54.md` section whose heading contains `(Schedule 54A)` |
| 54B | Cash Flow | Embedded — `S54.md` section whose heading contains `(Schedule 54B)` |
| 72A | Taxation | Embedded — `S72.md` section whose heading contains `(Schedule 72A)` |
| 72B | Taxation | Embedded — `S72.md` section whose heading contains `(Schedule 72B)` |
| 77A | Other Information | Parent GI — `S77.md` `## General Information` |
| 77B | Other Information | Parent GI — `S77.md` `## General Information` |
| 77C | Other Information | Parent GI — `S77.md` `## General Information` |
| 77D | Other Information | Parent GI — `S77.md` `## General Information` |
| 80A | Other Information | Parent GI — `S80.md` `## General Information` |
| 80C | Other Information | Parent GI — `S80.md` `## General Information` |

## Implementation Details

### New Dicts

```python
# Codes that use the parent schedule's General Information verbatim.
# No section search; name is hardcoded in _PARENT_GI_NAMES.
_PARENT_GI_FILE: dict[str, str] = {
    "22D": "22", "24D": "24",
    "26A": "26", "26B": "26",
    "77A": "77", "77B": "77", "77C": "77", "77D": "77",
    "80A": "80", "80C": "80",
}

_PARENT_GI_NAMES: dict[str, str] = {
    "22D": "Municipal and School Board Taxation",
    "24D": "Payments-In-Lieu of Taxation",
    "26A": "Taxation and Payments-In-Lieu Summary – Sections 1 and 2",
    "26B": "Distribution of Entitlements",
    "77A": "District Social Services Administration Boards (DSSABs)",
    "77B": "Health Units",
    "77C": "Other Entities",
    "77D": "Other Entities (Consolidated Summary)",
    "80A": "Statistical Information",
    "80C": "Consolidated Local Boards",
}

# Codes whose section is embedded in a parent file and identified by
# "(Schedule {code})" appearing anywhere in the section heading.
_EMBEDDED_PARENT_FILE: dict[str, str] = {
    "54A": "54", "54B": "54",
    "72A": "72", "72B": "72",
}
```

### `_extract_parent_gi_sub_schedule(markdown_dir, code)`

- Reads `FIR2025 S{_PARENT_GI_FILE[code]}.md`
- Finds the first section whose heading (lowercased, stripped) is `"general information"` or
  `"general instructions"`
- Returns the standard record dict using `_PARENT_GI_NAMES[code]` and that section's
  content as description

### `_extract_embedded_sub_schedule(markdown_dir, code)`

- Reads `FIR2025 S{_EMBEDDED_PARENT_FILE[code]}.md`
- Finds the first section whose heading contains `f"(Schedule {code})"` (case-insensitive)
- Derives `schedule_name` by stripping the `(Schedule {code}):?` suffix (e.g. `"Direct Method"`
  from `"Direct Method (Schedule 54A):"`)
- Returns standard record dict with that section's content as description

Known headings for reference:
- `54A`: `## Direct Method (Schedule 54A):`  → name `"Direct Method"`
- `54B`: `## Indirect Method (Schedule 54B):`  → name `"Indirect Method"`
- `72A`: `## Continuity of Taxes Receivable (Schedule 72A)`  → name `"Continuity of Taxes Receivable"`
- `72B`: `## Tax Adjustments Applied to Taxation (Schedule 72B)`  → name `"Tax Adjustments Applied to Taxation"`

### Dispatcher Update

Add two new routing checks at the top of `extract_schedule_record`, before the existing checks:

```python
if code in _PARENT_GI_FILE:
    return _extract_parent_gi_sub_schedule(markdown_dir, code)
if code in _EMBEDDED_PARENT_FILE:
    return _extract_embedded_sub_schedule(markdown_dir, code)
# ... existing checks (SUB_SCHEDULE_PARENTS, "53", _74X_CODES, regular) follow
```

### Note on `22D` and `24D` SLC Encoding

The raw FIR source CSVs use `22D` and `24D` as the schedule codes for **all** Schedule 22 and
24 records — there are no `22X`, `22A`, `22B`, or `22C` records in any loaded year.  This means
the parent-level codes (22, 22A–C, 24) are documented in the instructions but not present as
SLC codes in the data.  Those CSV rows are kept for documentation purposes.  A separate
investigation task should compare the raw FIR CSVs against the Excel/PDF source files to
understand this encoding difference.

## Tests

**New test classes:**
- `TestExtractParentGiSubSchedule` — name derivation, GI content extraction, missing parent
  file, code not in `_PARENT_GI_NAMES`
- `TestExtractEmbeddedSubSchedule` — name stripping for 54A/54B and 72A/72B, missing heading,
  missing file
- Dispatcher routing tests for: 02 (regular), 22D (parent GI), 54A (embedded), 72B (embedded)

**Updated tests:**
- `TestExtractAllScheduleMeta.test_returns_35_records_from_real_files` → 50 records
- All count-based assertions in CSV and DB load tests: 35 → 50

## Verification

```bash
# Unit + integration tests
uv run pytest tests/fir_instructions/test_extract_schedule_meta.py -v

# Regenerate CSV (50 rows expected)
uv run src/municipal_finances/app.py extract-baseline-schedule-meta \
  --markdown-dir fir_instructions/source_files/2025/markdown_clean \
  --no-load-db

wc -l fir_instructions/exports/baseline_schedule_meta.csv  # should print 51 (header + 50 rows)

# Coverage check — gaps should be zero or only genuinely undocumented codes
uv run src/municipal_finances/app.py validate-schedule-coverage
uv run src/municipal_finances/app.py validate-schedule-coverage --year 2024
```
