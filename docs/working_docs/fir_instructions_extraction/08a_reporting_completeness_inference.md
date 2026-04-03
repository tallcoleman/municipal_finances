# Task 08a: Infer Reporting Completeness by Municipality

## Goal

For recent FIR years (2022–2025), assess the completeness of reporting across municipalities: which municipalities have submitted data, and which schedules each has reported. This analysis is a prerequisite for Task 08b (data inference), where it informs noise filtering. If the analysis is computationally cheap enough to run on demand, expose it as a CLI command and/or API endpoint so users can query reporting status directly.

## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- `firrecord` data loaded for years 2022–2025

## Task List

- [ ] Query `firrecord` to determine which municipalities have any rows for each of years 2022, 2023, 2024, and 2025 (municipality-level reporting status)
- [ ] Cross-check municipality-level counts against `data/fir_reports/multi_year_provincial_summary/percent_of_reports_loaded_as_of_2026-04-02.csv` to validate the count logic
- [ ] For each municipality × year pair where data is present, determine which schedules were reported (schedule-level reporting status)
- [ ] Identify schedules that are "expected but missing": if a municipality consistently reported a schedule for the three prior years, flag it as potentially pending if it is absent in the target year
- [ ] Assess the query execution time for the above analyses to determine whether on-demand execution is feasible
- [ ] If feasible, add a `reporting-completeness` CLI command that accepts an optional `--year` flag and prints a summary table
- [ ] If feasible, add a corresponding API endpoint (e.g. `GET /reporting-completeness?year=2024`)
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Municipality-Level Reporting Status

A municipality has "reported" for a given year if it has at least one row in `firrecord` for that year:

```sql
SELECT m.munid, m.munname, COUNT(*) AS record_count
FROM firrecord r
JOIN municipality m ON m.munid = r.munid
WHERE r.marsyear = :year
GROUP BY m.munid, m.munname
ORDER BY m.munname;
```

The set of municipalities with zero matching rows for year Y, but rows in at least one prior year (Y-1, Y-2, Y-3), are the "not yet reported" municipalities for that year.

### Schedule-Level Reporting Status

For municipalities that have reported for a given year, determine which schedules are present by extracting the schedule component from the `slc` field (using the existing `parse_slc` utility or a SQL expression). Group by `(munid, marsyear, schedule)`.

To identify schedules that are expected but missing:

1. For each municipality, find all schedules reported in each of the three prior years (Y-1, Y-2, Y-3).
2. A schedule is "expected" for year Y if the municipality reported it in all three of those prior years.
3. If an expected schedule is absent in year Y (despite the municipality having reported for year Y), flag it as "likely pending".

This analysis yields two categories of potentially incomplete data:
- **Whole-year non-reporters**: municipality has no rows for year Y
- **Partial reporters**: municipality has rows for year Y but is missing expected schedules

### Validation Against the Provincial Summary CSV

`data/fir_reports/multi_year_provincial_summary/percent_of_reports_loaded_as_of_2026-04-02.csv` contains one row per year with the province-wide percentage of reports loaded. Use this as a sanity check: the percentage of municipalities with at least one row for each year should be consistent with these figures.

Note: the CSV covers years 2009–2024 only. For 2025 (where data may still be loading as of the run date), the in-database count is the only available measure.

### Computational Cost Assessment

Run `EXPLAIN ANALYZE` on the key queries before deciding whether to expose them as on-demand endpoints. Likely mitigations if queries are slow:
- Add a composite index on `(marsyear, munid)` to `firrecord` (if not already present)
- Cache the results in a lightweight summary table (e.g. `fir_reporting_status`) populated by a CLI command and queried by the API

If per-request query time is under ~2 seconds on the full ~13.5M-row dataset, on-demand execution is feasible without caching. If it is materially slower, prefer a cached summary approach.

### Output Used by Task 08b

Task 08b (data inference) uses the completeness analysis in two ways:

1. **Restricting "present" SLCs**: when detecting new or deleted SLCs between years Y-1 and Y, only count SLCs as "present in year Y" if they appear in municipalities that have reported for year Y. This avoids flagging absent SLCs as "deleted" when in fact those municipalities simply haven't reported yet.

2. **Calibrating the municipality count threshold**: the minimum number of municipalities required before counting an SLC as "present" (default: 3 in Task 08b) should be interpreted as a fraction of reporting municipalities, not total municipalities. If only 50 municipalities have reported for year Y, a threshold of 3 out of 50 (~6%) has different implications than 3 out of 400 (~0.75%). The completeness analysis provides the denominator needed to interpret the threshold correctly.

### CLI Command

```bash
# Summary for a specific year
uv run src/municipal_finances/app.py reporting-completeness --year 2024

# Summary for all relevant years (2022–2025)
uv run src/municipal_finances/app.py reporting-completeness
```

Output format (example):

```
Year  Municipalities Reported  Expected  Missing  Partial Reporters
2022  443                      444       1        2
2023  430                      444       14       8
2024  386                      444       58       22
2025  (data not yet available)
```

### API Endpoint

If added, follow the pattern in `api/routes/`. Suggested path: `GET /reporting-completeness` with an optional `year` query parameter. Returns a JSON summary mirroring the CLI output.

## Tests

- [ ] Test that a municipality with rows for year Y appears in the "reported" set
- [ ] Test that a municipality with no rows for year Y but rows in Y-1 appears in the "not yet reported" set
- [ ] Test the "expected but missing" schedule logic with controlled test data (municipality reports schedule in Y-3, Y-2, Y-1 but not Y → flagged; municipality first reports schedule in Y-1 but not Y → not flagged as expected)
- [ ] Test that the provincial percentage computed from the database is consistent with the CSV values (within a small tolerance to allow for data loaded since the snapshot)
- [ ] Test CLI command with `--year` flag and without
- [ ] Test idempotent execution (running twice yields the same results)
- [ ] If a cached summary table is used, test that the cache is correctly populated and queried

## Documentation Updates

- [ ] Add `reporting-completeness` command to `CLAUDE.md` "Common commands" section
- [ ] If an API endpoint is added, update `README.md` with its path and parameters

## Success Criteria

- Municipality-level reporting status for years 2022–2025 is queryable from the database
- Database-derived percentages are consistent with the provincial summary CSV (within ±1% for fully loaded years 2022 and 2023)
- "Expected but missing" schedule flagging produces a plausible set of candidates (no false positives for mandatory schedules, reasonable coverage of optional ones)
- If the CLI command is added, it runs in a reasonable time and prints a clear summary
- Task 08b can consume the output of this analysis to filter its inference queries

## Verification

```sql
-- Count of municipalities who have reported by year (2022–2025)
SELECT marsyear, COUNT(DISTINCT munid) AS municipalities_reported
FROM firrecord
WHERE marsyear BETWEEN 2022 AND 2025
GROUP BY marsyear
ORDER BY marsyear;

-- Municipalities present in 2023 but absent in 2024
SELECT DISTINCT munid
FROM firrecord
WHERE marsyear = 2023
AND munid NOT IN (SELECT DISTINCT munid FROM firrecord WHERE marsyear = 2024);

-- Schedules reported by a given municipality in each year (example: munid = 1)
SELECT marsyear,
       regexp_replace(slc, '^slc\.(\S+)\..*', '\1') AS schedule,
       COUNT(*) AS record_count
FROM firrecord
WHERE munid = 1
AND marsyear BETWEEN 2022 AND 2025
GROUP BY marsyear, schedule
ORDER BY marsyear, schedule;
```

## Additional Considerations

1. The definition of "reported" at the schedule level may need refinement. Some schedules are only required for certain municipality tiers (e.g. upper-tier only). The `applicability` field in `fir_line_meta` (once populated) could be used to filter expected-schedule checks by municipality type. For now, the three-prior-years heuristic is a reasonable approximation.
2. For year 2025, the reporting window is still open as of the task run date. The completeness analysis should note the run date when reporting 2025 figures so users understand the numbers will change over time.
3. If a cached summary table approach is chosen, document the recommended refresh cadence (e.g. run weekly while recent years are still partially loaded).
