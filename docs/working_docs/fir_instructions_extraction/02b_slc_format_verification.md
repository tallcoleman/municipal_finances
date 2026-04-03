# Task 02b: SLC Format Verification Against Real Data

## Goal

Verify that the SLC parsing logic in `slc.py` (Task 02) correctly handles every SLC value
present in the `firrecord` table. Specifically, confirm whether non-empty `sub` fields or
non-standard SLC formats exist in the data, and update the parser if they do.

This task must be completed before Task 03 (content changes extraction) and any other task
that calls `parse_slc()` against real data.

## Prerequisites

- Task 02 complete (`slc.py` implemented and tested)
- `firrecord` data loaded for at least one year (`uv run src/municipal_finances/app.py load-years`)

## Task List

- [x] Run format verification query and review results
- [x] Run sub-field verification query and review results
- [x] Update `slc.py` if unexpected formats or sub values are found
- [x] Update tests if `slc.py` changes

## Verification Queries

Connect to the database and run these two queries:

```sql
-- 1. Check for SLC values that do not match the expected pattern.
--    Any rows returned indicate an unexpected format that the parser will reject.
SELECT slc, count(*) AS occurrences
FROM firrecord
WHERE slc IS NOT NULL
  AND slc NOT LIKE 'slc.%.L____%.C__.%'
GROUP BY slc
ORDER BY occurrences DESC
LIMIT 20;

-- 2. Check what values appear in the sub field (the trailing segment after the last dot).
--    The parser currently accepts any sub value; this tells us what values actually exist.
SELECT
    substring(slc FROM '[^.]+$') AS sub_value,
    count(*) AS occurrences
FROM firrecord
WHERE slc IS NOT NULL
GROUP BY sub_value
ORDER BY occurrences DESC
LIMIT 20;
```

The `LIKE` pattern `slc.%.L____%.C__.%` is a rough structural check. The stricter verification
is the regex in `_SLC_PATTERN` — to test every row against it, use:

```sql
-- 3. Count rows that would fail parse_slc() (no match for the strict regex).
SELECT count(*) AS failing_rows
FROM firrecord
WHERE slc IS NOT NULL
  AND slc !~ '^slc\.[^.]+\.L\d{4}\.C\d{2}\..*$';
```

## Expected Results

Based on the documented SLC format, the expected findings are:

| Query | Expected result |
|---|---|
| Query 1 (non-matching) | Zero rows |
| Query 2 (sub values) | Empty string `''` only, or a small set of known values |
| Query 3 (strict regex) | Zero failing rows |

## If Unexpected Formats Are Found

### Non-empty sub values

If sub values other than `''` appear, inspect a sample:

```sql
SELECT DISTINCT slc FROM firrecord
WHERE substring(slc FROM '[^.]+$') != ''
LIMIT 20;
```

Determine whether the sub field encodes meaningful data (e.g. a sub-schedule letter) or is
noise. Update `parse_slc()` accordingly and add targeted tests for any new values.

### Non-standard SLC formats

If Query 1 or Query 3 returns rows, inspect them:

```sql
SELECT DISTINCT slc FROM firrecord
WHERE slc !~ '^slc\.[^.]+\.L\d{4}\.C\d{2}\..*$'
LIMIT 20;
```

Determine whether the parser should:
- Accept the new format (extend `_SLC_PATTERN` with a named capture group variant)
- Reject and report it (document as a known data quality issue)

## Documentation Updates

- [x] Record findings (even if no changes needed) as a comment in `slc.py` near `_SLC_PATTERN`,
  citing the verification date and the data range checked.

## Success Criteria

- Both queries return the expected results, OR
- `slc.py` has been updated to handle any discovered formats, new tests cover them, and all
  tests pass with 100% branch coverage on the module
- Findings are documented in a comment in `slc.py`
