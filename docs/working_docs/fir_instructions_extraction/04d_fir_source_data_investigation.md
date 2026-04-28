# Task 04d: Investigate FIR Source Data Gaps

## Context

`validate-schedule-coverage` identified several schedule codes present in the
database but absent from `baseline_schedule_meta.csv`, and vice versa.  While
most gaps were resolved by extending the catalogue to 50 codes (task 04c), two
questions remain open:

1. **22D / 24D encoding** — the raw FIR CSVs use `22D` and `24D` as the
   schedule code for *all* Schedule 22 and 24 records.  There are no `22`,
   `22A`, `22B`, `22C`, or `24` records in any loaded year.  The FIR website
   also distributes data in other formats (Excel, PDF).  It is unknown whether
   the letter-suffix discrepancy is an artifact of the CSV format specifically
   or reflects how the Ontario Ministry actually identifies these records.

2. **Schedule 62 absent** — Schedule 62 (Continuity of Reserve Fund
   Investments) appears in the metadata but has no records in any loaded year
   from 2000 to 2025.  It is unclear whether this schedule was discontinued,
   was always optional and simply unused by reporting municipalities, or whether
   the data was never included in the CSV exports.

## Investigation Steps

### 1. Compare FIR CSV format with Excel / PDF formats

The FIR website provides annual data in multiple formats.  Download the Excel
or PDF version for a year where CSV data is available (e.g. 2024 or 2025) and
check:

- Do the Excel/PDF files use `22D` / `24D` as schedule codes, or do they use
  `22`, `22A`, `22B`, `22C`?
- Are there any Schedule 62 rows in the Excel/PDF files?
- Are there other schedule-code differences between the CSV and Excel/PDF
  formats?

The goal is to determine whether the CSV encoding is a lossy transformation of
richer data, or whether it is the authoritative format.

### 2. Review 22D / 24D encoding decision

Based on the comparison above:

- **If CSV matches Excel/PDF** (i.e. `22D` is the real code): the current
  approach (documenting `22`, `22A-C`, `24` in metadata for reference but
  storing all data under `22D`/`24D`) is correct.  No change needed except
  possibly adding a note to the metadata description.

- **If CSV differs from Excel/PDF** (i.e. Excel uses `22`, `22A`, etc.): the
  CSV encoding is lossy.  Options include:
  - Loading data from the Excel format instead of CSV
  - Adding a post-load normalisation step that infers sub-schedule from other
    fields (line or column codes)
  - Documenting the limitation and proceeding with `22D`/`24D` as-is

### 3. Investigate Schedule 62 absence

Check:
- Are there any Schedule 62 rows in the Excel/PDF files for any year?
- Does the FIR instructions document for Schedule 62 indicate it is optional or
  was retired?
- Are there any loaded years (2000–2025) where Schedule 62 appears in the CSV?

Based on findings, either remove Schedule 62 from `baseline_schedule_meta.csv`
(if genuinely retired/unused) or identify how to populate it.

### 4. Spot-check other CSV-not-DB codes

The following codes appear in the metadata CSV but not the database for 2025
(some may just be missing from the 2025 data load):

| Code | Likely reason |
|---|---|
| 28 | Found in 2024 — probably just no 2025 data yet |
| 61A, 61B | Found in 2024 — probably just no 2025 data yet |
| 74B | Found in 2024 — probably just no 2025 data yet |
| 76 | Found in 2024 — probably just no 2025 data yet |
| 83 | Found in 2024 — probably just no 2025 data yet |
| 62 | Absent from all years — see investigation above |
| 22, 22A-C, 24 | Encoding difference — see investigation above |
| 26, 54, 72, 74, 77, 80 | Base codes; data is all in sub-schedule codes |

## Deliverables

- Updated notes in `docs/working_docs/fir_instructions_extraction/schedule_coverage_check.txt`
  (or a new `schedule_coverage_check_v2.txt`) documenting findings
- Decision recorded here on what to do about 22D/24D encoding
- If Schedule 62 is confirmed absent: update `baseline_schedule_meta.csv` to
  remove it or mark it as discontinued
- If additional data sources are to be loaded (e.g. Excel format): create a
  follow-on task document

## Task List

- [ ] Download FIR data in Excel or PDF format for at least one year
- [ ] Compare schedule codes in Excel vs. CSV for schedules 22, 24, 62
- [ ] Document findings and decision in this file
- [ ] Update `baseline_schedule_meta.csv` if Schedule 62 should be removed
- [ ] Create follow-on task if additional data loading is needed
