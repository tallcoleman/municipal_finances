# Task 06: Extract FIR2025 Baseline — Column Metadata (Phase 1c)

## Goal

Extract column-level metadata for all schedules from the FIR2025 Instructions PDF and populate `fir_column_meta`.

## Prerequisites

- Task 01 (database models) complete
- Task 04 (schedule metadata) complete — need `fir_schedule_meta` rows (for the `schedule_id` FK and `schedule` text values)

## Task List

- [ ] For each of the 31 schedules, open `FIR2025 S{code}.md` (or parent file for sub-schedules) and extract column descriptions using `_parse_md_sections`
- [ ] Create `fir_column_meta` rows for all columns
- [ ] Set all rows to `valid_from_year = NULL`, `valid_to_year = NULL`
- [ ] Export to CSV
- [ ] Verify against PDF

## Implementation Details

### Fields to Extract Per Column

| Field | Source |
|---|---|
| `schedule_id` | Serial FK to `fir_schedule_meta.id` |
| `schedule` | Text identifier (e.g., `"10"`, `"51A"`) — denormalized from schedule context |
| `column_id` | 2-digit code (e.g., `"01"`, `"03"`) |
| `column_name` | Column heading (e.g., `"Ontario Conditional Grants"`) |
| `description` | Narrative about what the column captures |
| `valid_from_year` | NULL (baseline) |
| `valid_to_year` | NULL (baseline) |
| `change_notes` | NULL (baseline) |

### Extraction Notes

- For each schedule, open `FIR2025 S{code}.md` (or the parent file for sub-schedules — see `_MD_PARENT_FILE` in `extract_schedule_meta.py`). Use the same `_parse_md_sections` helper developed for Task 04.
- Column descriptions are in sections whose headings match `Column N - Column Name` (e.g. `Column 1 - Ontario Conditional Grants`). Many schedules collect these under a `Description of Columns` section heading; scan for that heading first, then read forward.
- Some schedules have very few columns (2–3), while others like Schedule 12 have many (10+)
- Column descriptions tend to be shorter than line descriptions
- Schedules 12 and 40 have particularly complex column structures worth extra attention
- Some columns have no narrative description beyond their heading. Set `description = "No description provided."` for these columns rather than leaving the field NULL or empty.

### Expected Volume

Most schedules have 3–10 columns. Total: likely 100–200 column metadata rows.

### Data File Approach

Even with the markdown source files, extraction logic involves parsing heuristics that may need manual correction. Save the extracted data as a CSV at `fir_instructions/exports/baseline_column_meta.csv`. This allows re-loading without re-parsing and serves as the human-editable source of truth before DB insertion.

## Tests

- [ ] Test insertion of column metadata records
- [ ] Test that every schedule has at least one column in `fir_column_meta`
- [ ] Test `column_id` format validation (2-digit string)
- [ ] Test idempotent insertion

## Documentation Updates

- [ ] None expected

## Success Criteria

- Every schedule has column metadata entries
- `column_id` values are valid 2-digit strings
- Column names match the PDF headings exactly
- Spot-check columns for Schedules 12, 40, 51A, 51B (complex column structures)

## Verification

```sql
-- Columns per schedule
SELECT schedule, count(*) FROM fir_column_meta GROUP BY schedule ORDER BY schedule;

-- Schedules with no columns (should be empty)
SELECT sm.schedule FROM fir_schedule_meta sm
LEFT JOIN fir_column_meta cm ON sm.schedule = cm.schedule
WHERE cm.id IS NULL;

-- Validate column_id format
SELECT * FROM fir_column_meta WHERE column_id !~ '^\d{2}$';
```
