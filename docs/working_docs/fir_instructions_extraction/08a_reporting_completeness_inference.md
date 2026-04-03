# Task 08a: Infer number of municipalities who have completed reporting

## Rough Notes

For more recent years, some Municipalities may not have reported, or may have only reported a partial set of schedules. This should be assessed so that it can be factored into the inference of changes to schedules, lines, and columns from year to year.

Following the task template (including headings below), make a plan to assess the completeness of reporting by municipalities by seeing which values are present or not present in the database once the data has been loaded.

This assessment should include:
* Has each municipality reported for the relevant year? (Relevant years: 2022, 2023, 2024, and 2025)
* Has each municipality reported all of the expected schedules for the relevant year? This may be more challenging to assess, since it may be normal for a municipality to report a certain schedule one year and not the other, based on whether they have activity that relates to that schedule. However, if a municipality has consistently reported a schedule for e.g. the three years prior, it may be safe to assume that if it is missing in the relevant year, their reporting of that schedule may still be pending.

To help with validation, I have extracted the percentage of reports loaded from one of the summary reports on the FIR website and saved it to `data/fir_reports/multi_year_provincial_summary/percent_of_reports_loaded_as_of_2026-04-02.csv`.

Since users may want to understand the completeness of reporting for a particular year, assess how computationally expensive it is to analyze reporting completeness. If it is reasonably feasible to do so, add this analysis as a tool that users can request via the CLI, the API, or both.

## Goal



## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- Task 07 (Phase 2 versioning) complete
- `firrecord` data loaded for the years being compared

## Task List


## Implementation Details


## Tests


## Documentation Updates


## Success Criteria


## Verification


## Questions



