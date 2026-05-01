# Task 01b: Update Data Model for Schedule Structure

## Context

The `firrecord` table has an `slc` column in the format
`slc.<schedule>.L<line>.C<column_section>.<column_id>`.  To query or filter records by
schedule you currently have to parse this string.  In addition, base schedules
use a trailing `X` suffix in the SLC code (e.g. `12X`) that needs to be
stripped before matching against schedule metadata.

The `firrecord` table also has `schedule_desc` and `sub_schedule_desc` columns
that are populated from the raw FIR source CSVs, but these are free-text and
not suitable for joining to the schedule metadata tables.

This task adds indexed columns that expose the parsed schedule components
directly, making it straightforward to filter, group, and join without string
manipulation.

## Notes on Column and database/csv slc Formats

### SLC Formats

In the open data CSVs and the database, the SLC (Schedule, Line, Column) format is `slc.<schedule>.L<line>.C<column_section>.<column_id>`.

Components:

- `<schedule>`: two digits and a letter, either representing a schedule or one of its sub-schedules. Sub-schedules use a letter suffix (e.g. "A", "B", "C", etc.), and when a base schedule is represented, the letter suffix "X" is added to the schedule code.
- `<line>`: four alphanumeric characters, usually all digits (e.g. `9930`). Schedules 76X, 80C, and 81X use codes like `000A` and `000B`.
- `<column_section>`: two digits; denotes a group of columns within a schedule or sub-schedule that all have the same column headings. Some schedules or sub-schedules have more than one column sections, and some only have one. In `slc.py`, `parse_slc()` captures this as the `column_section` field.
- `<column_id>`: two characters, generally two digits or one digit and one letter; identifies a specific column or fill-in label within the column section. Two-digit values (e.g. `01`, `02`) are used for normal "value" fields, whereas the one-digit-one-letter form (e.g. `0A`, `0B`) is used for fill-in label columns. In `slc.py`, `parse_slc()` captures this as the `column_id` field. This field is never empty in real data.

Not recorded:

- Lines are also organized into their own sections. This is described in the documentation and in the Excel reports, but is not part of the SLC structure used by the CSV/database data.
- Null values are simply omitted from the CSV records (and the database, in the current implementation), instead of recording an SLC with a null value.
### Supporting Observations

In the Excel report for Toronto C 2024, `slc.10X.L1891.C01.01` and `slc.10X.L1891.C01.0A` appear on the same row. `C01.01` is the main column with currency values and `C01.0A` is the fill-in text description on the same row.

In the Excel report for Toronto C 2024, schedule 12 has row sub-headings, e.g. "Protection Services" for lines 0410 to 0499. These row sub-headings are not reflected in the database at all, though I believe they are part of the structure of the documentation. All of the columns are `C01.XX`, and all of the column headers are the same throughout.

In the Excel report for Toronto C 2024, schedule 20 has sections of columns that have different column headings. Here, you start to see the pattern change: every time there is a new set of column headings, the first part of the column identifier goes up (e.g. `C01.XX`, then `C02.XX`, then `C03.XX`, etc.) The implied layout of columns generally matches the layout in the Excel report.

When values are left blank in the Excel report, there is no database row at all.

### How the FIR CSV documentation describes the SLC format

From `'fir_instructions/source_files/Documentation for CSV files.pdf'` (cleaned up for formatting).

SLC identifies the datapoint including Schedule, Line and Column. The SLC takes the following format: `slc.02X.L0020.C01.02`

- all slc references begin with "slc."
- 02X refers to the schedule number. In this example it is referring to Schedule 02. In most cases, the schedule number is followed by an X. i.e. Schedule 10 would be slc.10X. 
- However, where a schedule is divided into different parts (i.e. Schedule 26 is divided into two tabs in the FIR template; Schedule 26A and Schedule 26B) the schedule portion of the slc will be slc.26A and slc.26B. Other schedules where this applies include: Schedule 51, Schedule 72 , Schedule 74, Schedule 77 andSchedule 80.
- L0020 refers to the line number. In this example the line number is 0020.
- C01.02 refers to the section and column number. In most cases the section will [be] 01. However where a schedule has distinct sections, the section number will change. For example, Schedule 20 is divided into different sections with varying number of columns in each section.
- [shows an image of what schedule 20 looks like]
- Line 0202 in section 1 would have an slc number of slc.20X.L0202.C01.02 (C01.02 = section 1 , column 02) 
- Line 0320 Column 5 would have an slc number of slc.20X.L0320.C02.05 (Schedule 20, Line 0320, Section 2, Column 5)

### SLC format used by the instructions documentation

The FIR instructions documents use a different SLC format:

> In the FIR, each data point is identified by a unique SLC Number.  The SLC Number identifies the Schedule, Line and Column where a data point is located.  SLC means “Schedule-Line-Column”. 
 > 
 > For example, SLC 10 9930 01 refers to Schedule 10, Line 9930, Column 1. 
 > 
 > Each Schedule is identified with a 2-Digit Number, which is displayed in the top righthand corner of each Schedule. 
 > 
 > Each Line is identified with a 4-Digit Line ID, which is displayed in the left margin beside every line on every Schedule. 
 > 
 > Each Column is identified with a 2-Digit Column Number, which is displayed in every column heading. 

This format appears to omit the column section information that the CSV and database SLCs encode.

The instructions documents also use a wildcard format in some cases to refer to an entire line or column, e.g. "SLC 40 xxxx 01" to refer to all values in column 01 in schedule 40.
## Goal

Add `schedule_code`, `base_schedule_code`, `sub_schedule_code`, `line_id`,
`column_section`, and `column_id` as pre-parsed columns to `firrecord` so that:

- Querying all records for a given schedule (including all its sub-schedules) is
  a simple `WHERE base_schedule_code = '12'`
- Querying records for a specific sub-schedule is a simple `WHERE schedule_code = '74A'`
- Joining `firrecord` to `fir_schedule_meta` is a direct equality on `schedule_code`
  with no runtime string parsing
- Validation queries (e.g. `validate-schedule-coverage`) do not need SQL string
  functions

## Proposed Changes

### New columns on `firrecord`

The raw SLC encodes the base schedule and sub-schedule together (e.g. `22D` is schedule
22, sub-schedule D; `10X` is base schedule 10 with no sub-schedule). Three columns split
this into independently queryable parts:

| Column               | Type         | Derivation                                                                                                                     |
| -------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `schedule_code`      | `VARCHAR(3)` | `split_part(slc, '.', 2)` with trailing `X` stripped (e.g. `10X` → `"10"`, `22D` → `"22D"`). Joins to `fir_schedule_meta.schedule`. |
| `base_schedule_code` | `VARCHAR(2)` | First two characters of `schedule_code` — always the 2-digit numeric portion (e.g. `"10"`, `"22"`).                           |
| `sub_schedule_code`  | `VARCHAR(1)` | Third character of `split_part(slc, '.', 2)` if not `X`, else NULL (e.g. `"D"` for `22D`, NULL for `10X`).                   |
| `line_id`            | `VARCHAR(4)` | `split_part(slc, '.', 3)` with leading `L` stripped.                                                                          |
| `column_section`     | `VARCHAR(2)` | `split_part(slc, '.', 4)` with leading `C` stripped.                                                                          |
| `column_id`          | `VARCHAR(2)` | `split_part(slc, '.', 5)`.                                                                                                     |

All columns except `sub_schedule_code` should be NOT NULL (all valid records have an SLC
with every component present). Indexed: `base_schedule_code` (primary filter for broad
schedule queries) and `schedule_code` (joins to `fir_schedule_meta`, sub-schedule exact
lookups). `sub_schedule_code` is not indexed separately — too few distinct values to be
selective, and it is always covered by the other two indexes for any real query.

**Query patterns:**

```sql
-- All records for schedule 74, including all sub-schedules
WHERE base_schedule_code = '74'

-- Records for sub-schedule 74A specifically
WHERE schedule_code = '74A'

-- Join to fir_schedule_meta (direct equality, no string functions)
JOIN fir_schedule_meta ON firrecord.schedule_code = fir_schedule_meta.schedule
```

### Migration

1. Update `models.py` to add the six new columns to `FIRRecord`.
2. Generate a migration: `uv run alembic revision --autogenerate -m "add schedule columns to firrecord"`
3. Review the generated migration file. Autogenerate produces the `ADD COLUMN` statements but does **not** generate the backfill or custom indexes, so add manually:
   - A backfill `UPDATE firrecord SET schedule_code = ..., base_schedule_code = ..., sub_schedule_code = ...` (and the other columns) using the same string logic as `validate_schedule_coverage.py`
   - `CREATE INDEX ix_firrecord_base_schedule_code ON firrecord (base_schedule_code)`
   - `CREATE INDEX ix_firrecord_schedule_code ON firrecord (schedule_code)`
4. Apply: `uv run alembic upgrade head`
5. Update `db_management.py` / `load-data` pipeline to populate the new columns during future bulk loads (so re-loads do not need a separate migration step).

## Impact

- `validate_schedule_coverage.py` can be simplified to query
  `SELECT DISTINCT base_schedule_code ...` instead of parsing `slc` in SQL
- `validate_column_coverage.py` similarly
- Future API endpoints can filter by `base_schedule_code` (all sub-schedules included)
  or `schedule_code` (specific sub-schedule), both using indexed equality predicates
- Joins to `fir_schedule_meta` become a direct `ON schedule_code = fir_schedule_meta.schedule`

## Task List

- [ ] Add Alembic migration script
- [ ] Update `models.py` (`FIRRecord` class)
- [ ] Update `db_management.py` to populate new columns during `load-data`
- [ ] Simplify `validate_schedule_coverage.py` to use `base_schedule_code`
- [ ] Simplify `validate_column_coverage.py` to use `base_schedule_code`
- [ ] Update `CLAUDE.md` database section
- [ ] Add tests for new column population logic
