# Task 08a: Infer Reporting Completeness by Municipality

## Goal

For recent FIR years (2022–2025), assess the completeness of reporting across municipalities: which municipalities have submitted data, and which schedules each has reported. This analysis is a prerequisite for Task 08b (data inference), where it informs noise filtering. If the analysis is computationally cheap enough to run on demand, expose it as a CLI command and/or API endpoint so users can query reporting status directly.

## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- `firrecord` data loaded for years 2019–2025 (four years where data is still being reported plus three years prior)

## Task List

- [ ] Query `firrecord` to determine which municipalities have any rows for each of years 2022, 2023, 2024, and 2025 (municipality-level reporting status)
- [ ] Cross-check municipality-level counts against `data/fir_reports/multi_year_provincial_summary/percent_of_reports_loaded_as_of_2026-04-02.csv` to validate the count logic
- [ ] For each municipality × year pair where data is present, determine which schedules were reported (schedule-level reporting status)
- [ ] Identify schedules that are "expected but missing": if a municipality consistently reported a schedule for the three prior years, flag it as potentially pending if it is absent in the target year
- [ ] Assess the query execution time for the above analyses to determine whether on-demand execution is feasible
- [ ] If feasible, add a `reporting-completeness` CLI command with the following modes (see Implementation Details):
  - [ ] Province-wide summary table by year
  - [ ] Per-municipality breakdown for a given year
- [ ] If feasible, add corresponding API endpoints (see Implementation Details)
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

### Report Modes

Three report modes are supported, selectable by CLI flags and API parameters:

#### Mode 1: Province-wide summary (default)

Aggregated one row per year. Suitable for a quick overview across all relevant years.

```bash
# All relevant years (2022–2025)
uv run src/municipal_finances/app.py reporting-completeness

# Single year
uv run src/municipal_finances/app.py reporting-completeness --year 2024
```

Output format (example):

```
Year  Municipalities Reported  Total  Not Yet Reported  Partial Reporters
2022  443                      444    1                 2
2023  430                      444    14                8
2024  386                      444    58                22
2025  312                      444    132               8   (data still loading as of 2026-04-03)
```

For years where the reporting window is still open (typically the current and prior year), append a note with the data extraction date so users understand the figures will change as more municipalities submit. Use the current date at query time.

#### Mode 2: Per-municipality breakdown

One row per (municipality, year). Shows exactly which schedules each municipality has reported and which are expected but missing or newly reported. Intended for detailed investigation of a specific year or municipality. Because this output can be large, it is most useful filtered to a single year and optionally a single municipality.

```bash
# All municipalities for a given year
uv run src/municipal_finances/app.py reporting-completeness --year 2024 --by-municipality

# Single municipality (by munid or name substring)
uv run src/municipal_finances/app.py reporting-completeness --year 2024 --by-municipality --munid 123
```

Output format (example, one row per municipality):

```
munid  munname            Reported  Missing  Expected    New (not in prior n years)  Schedules Reported
101    Ajax               18        0                    0                           10, 12, 20, ...
102    Aurora             17        1        61B         0                           10, 12, 20, ...
103    Barrie             0         —                    —                           (not yet reported)
```

For each municipality × year, the breakdown includes:
- **Schedules reported**: count and list of schedule codes reported in this year
- **Missing**: count of schedules reported in all of the prior `n` years (default `n=3`) but absent in this year — likely still pending
- **Expected**: list of schedules reported in all of the prior `n` years (default `n=3`) but absent in this year — likely still pending
- **New (not in prior n years)**: schedules reported this year that were not reported in any of the prior `n` years — may indicate new activity or a structural change

The `n` look-back window defaults to 3 but is configurable:

```bash
uv run src/municipal_finances/app.py reporting-completeness --year 2024 --by-municipality --lookback 5
```

#### Handling Insufficient History

When fewer than `n` prior years of data are available in the database (e.g. requesting a breakdown for year 2000 with `n=3` but data only starts in 2000, or for 2001 where only one prior year exists), the schedule availability analysis degrades gracefully:

- Use however many prior years are actually available (0–n-1).
- If zero prior years are available, the "missing" and "new" columns cannot be computed; report them as `N/A` and note the limitation.
- If 1 or 2 prior years are available, compute the columns using only those years and annotate the output with the actual look-back window used (e.g. "Lookback: 1 year (requested 3; insufficient history)").
- The "expected" definition adjusts accordingly: a schedule is "expected" if it was reported in *all* available prior years (not necessarily all `n`). For very short histories this is a weaker signal, which the annotation makes clear.

This behaviour applies equally to the CLI, the API, and the internal logic used by Task 08b.

### API Endpoints

If added, follow the pattern in `api/routes/`. Two suggested endpoints:

| Endpoint                                     | Parameters                                                              | Returns                             |
| -------------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------- |
| `GET /reporting-completeness`                | `year` (optional)                                                       | Province-wide summary (Mode 1)      |
| `GET /reporting-completeness/municipalities` | `year` (required), `munid` (optional), `lookback` (optional, default 3) | Per-municipality breakdown (Mode 2) |

Both return JSON. The per-municipality endpoint should support pagination if the full result set is large.

## Tests

- [ ] Test that a municipality with rows for year Y appears in the "reported" set
- [ ] Test that a municipality with no rows for year Y but rows in Y-1 appears in the "not yet reported" set
- [ ] Test the "expected but missing" schedule logic with controlled test data:
  - Municipality reports schedule in Y-3, Y-2, Y-1 but not Y → flagged as missing
  - Municipality first reports schedule in Y-1 but not Y → not flagged (only 1 of 3 prior years)
  - Municipality reports schedule in Y-3 and Y-1 but not Y-2 or Y → not flagged (not present in all prior years)
- [ ] Test the "new schedules" logic: schedule reported in Y but not in any of Y-1, Y-2, Y-3 → flagged as new
- [ ] Test insufficient history handling:
  - Year Y with zero prior years available → "missing" and "new" columns are N/A
  - Year Y with one prior year available → lookback=1 is used, output annotated accordingly
  - Year Y with two prior years available → lookback=2 is used, output annotated accordingly
- [ ] Test that the `--lookback` flag (or `lookback` API parameter) changes the look-back window correctly
- [ ] Test that the provincial percentage computed from the database is consistent with the CSV values (within a small tolerance to allow for data loaded since the snapshot)
- [ ] Test CLI province-wide summary with `--year` flag and without
- [ ] Test CLI per-municipality breakdown with `--by-municipality` and with `--munid` filter
- [ ] Test idempotent execution (running twice yields the same results)
- [ ] If a cached summary table is used, test that the cache is correctly populated and queried

## Documentation Updates

- [ ] Add `reporting-completeness` command (both modes) to `CLAUDE.md` "Common commands" section
- [ ] If API endpoints are added, update `README.md` with paths, parameters, and example responses

## Success Criteria

- Municipality-level reporting status for years 2022–2025 is queryable from the database
- Database-derived percentages are consistent with the provincial summary CSV (within ±1% for fully loaded years 2022 and 2023)
- "Expected but missing" schedule flagging produces a plausible set of candidates (no false positives for mandatory schedules, reasonable coverage of optional ones)
- Per-municipality breakdown correctly identifies reported schedules, missing expected schedules, and newly reported schedules for each municipality × year combination
- Insufficient history is handled gracefully: the analysis runs without error for any year in the database and clearly annotates when fewer than `n` prior years were available
- If the CLI commands are added, both modes run in a reasonable time and print clear output
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
AND marsyear BETWEEN 2019 AND 2025
GROUP BY marsyear, schedule
ORDER BY marsyear, schedule;

-- Schedules reported in 2021–2023 but absent in 2024, for municipalities that have reported in 2024
-- (i.e. "expected but missing" with n=3 look-back)
WITH reported_2024 AS (
    SELECT DISTINCT munid FROM firrecord WHERE marsyear = 2024
),
prior_schedules AS (
    SELECT munid,
           regexp_replace(slc, '^slc\.(\S+)\..*', '\1') AS schedule,
           COUNT(DISTINCT marsyear) AS years_present
    FROM firrecord
    WHERE marsyear BETWEEN 2021 AND 2023
    GROUP BY munid, schedule
    HAVING COUNT(DISTINCT marsyear) = 3  -- present in all 3 prior years
),
current_schedules AS (
    SELECT DISTINCT munid,
           regexp_replace(slc, '^slc\.(\S+)\..*', '\1') AS schedule
    FROM firrecord
    WHERE marsyear = 2024
)
SELECT p.munid, m.munname, p.schedule
FROM prior_schedules p
JOIN reported_2024 r ON r.munid = p.munid
JOIN municipality m ON m.munid = p.munid
LEFT JOIN current_schedules c ON c.munid = p.munid AND c.schedule = p.schedule
WHERE c.schedule IS NULL
ORDER BY m.munname, p.schedule;
```

## Additional Considerations

1. The definition of "reported" at the schedule level may need refinement. Some schedules are only required for certain municipality tiers (e.g. upper-tier only). The `applicability` field in `fir_line_meta` (once populated) could be used to filter expected-schedule checks by municipality type. For now, the three-prior-years heuristic is a reasonable approximation.
2. If a cached summary table approach is chosen, document the recommended refresh cadence (e.g. run weekly while recent years are still partially loaded).
3. The insufficient-history degradation logic (see "Handling Insufficient History" above) also applies when Task 08b calls this analysis internally. For inference over very early year pairs (e.g. 2000→2001), zero or one prior year may be available; the inference should treat the completeness filter as best-effort and flag results accordingly rather than refusing to run.
