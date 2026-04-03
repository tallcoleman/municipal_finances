# Task 06: Extract FIR2025 Baseline — Column Metadata (Phase 1c)

## Goal

Extract column-level metadata for all schedules from the FIR2025 Instructions PDF and populate `fir_column_meta`.

## Prerequisites

- Task 01 (database models) complete
- Task 04 (schedule metadata) complete — need `fir_schedule_meta` rows (for the `schedule_id` FK and `schedule` text values)

## Task List

- [ ] For each of the 26 schedules, extract column descriptions from the schedule's instruction section
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

- Column descriptions are typically found after the line descriptions in each schedule's instruction section
- Some schedules have very few columns (2–3), while others like Schedule 12 have many (10+)
- Column descriptions tend to be shorter than line descriptions
- Schedules 12 and 40 have particularly complex column structures worth extra attention

### Expected Volume

Most schedules have 3–10 columns. Total: likely 100–200 column metadata rows.

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

## Questions

1. Some schedules may have columns that are described only by their heading (no narrative description). Should `description` be NULL in these cases, or should the column name serve as the description?
2. Are there columns that exist in `firrecord` data but are not described in the instructions PDF? This would be caught by the audit coverage check in Task 11, but worth noting here.
