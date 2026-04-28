# Task 01b: Update Data Model for Schedule Structure

## Context

The `firrecord` table has an `slc` column in the format
`slc.<schedule>.L<line>.C<column_id>.<sub>`.  To query or filter records by
schedule you currently have to parse this string.  In addition, base schedules
use a trailing `X` suffix in the SLC code (e.g. `12X`) that needs to be
stripped before matching against schedule metadata.

The `firrecord` table also has `schedule_desc` and `sub_schedule_desc` columns
that are populated from the raw FIR source CSVs, but these are free-text and
not suitable for joining to the schedule metadata tables.

This task adds indexed columns that expose the parsed schedule components
directly, making it straightforward to filter, group, and join without string
manipulation.

## Goal

Add `schedule_code` and `sub_schedule_code` (and optionally `line_id`,
`column_id`) as pre-parsed columns to `firrecord` so that:

- Querying all records for a given schedule is a simple `WHERE schedule_code =
  '12'`
- Joining `firrecord` to `fir_schedule_meta` requires no runtime string parsing
- Validation queries (e.g. `validate-schedule-coverage`) do not need SQL string
  functions

## Proposed Changes

### New columns on `firrecord`

| Column | Type | Derivation |
|---|---|---|
| `schedule_code` | `VARCHAR(10)` | `split_part(slc, '.', 2)` with trailing `X` stripped |
| `line_id` | `VARCHAR(20)` | `split_part(slc, '.', 3)` with leading `L` stripped, or NULL if absent |
| `column_id` | `VARCHAR(20)` | `split_part(slc, '.', 4)` with leading `C` stripped, or NULL if absent |

`schedule_code` should be NOT NULL (all valid records have an SLC) and indexed.
`line_id` and `column_id` can be nullable.

### Migration

1. Add columns via `ALTER TABLE firrecord ADD COLUMN ...`
2. Populate with a single `UPDATE firrecord SET schedule_code = ...` using the
   same string logic currently in `validate_schedule_coverage.py`
3. Add index: `CREATE INDEX ix_firrecord_schedule_code ON firrecord (schedule_code)`
4. Update `models.py` to reflect the new columns
5. Update `db_management.py` / `load-data` pipeline to populate the columns
   during future bulk loads (so re-loads do not need a separate migration step)

### Optional: separate `schedule` and `sub_schedule`

The raw SLC encodes the base schedule and sub-schedule together (e.g. `22D` is
schedule 22, sub-schedule D).  If the data model needs to support filtering
independently on base schedule vs. sub-schedule letter, two columns can be used:

- `base_schedule_code` — numeric prefix (e.g. `"22"`)
- `sub_schedule_letter` — letter suffix (e.g. `"D"`, NULL for base schedules)

This decomposition can be deferred until there is a concrete query need.

## Impact

- `validate_schedule_coverage.py` can be simplified to query
  `SELECT DISTINCT schedule_code ...` instead of parsing `slc` in SQL
- `validate_column_coverage.py` similarly
- Future API endpoints that filter by schedule gain a clean, indexed column

## Task List

- [ ] Add migration script (Alembic or raw SQL)
- [ ] Update `models.py` (`FIRRecord` class)
- [ ] Update `db_management.py` to populate new columns during `load-data`
- [ ] Simplify `validate_schedule_coverage.py` to use `schedule_code`
- [ ] Simplify `validate_column_coverage.py` to use `schedule_code`
- [ ] Update `CLAUDE.md` database section
- [ ] Add tests for new column population logic
