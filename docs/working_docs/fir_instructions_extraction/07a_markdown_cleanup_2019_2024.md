# Task 07a: Clean Up FIR Markdown Files for 2019–2024

## Context

The `markdown_clean/` source files for 2025 were produced by a PDF-to-markdown
conversion pipeline that used the PDF's embedded table-of-contents (TOC)
metadata to fix heading levels.  This process is documented in the `06b`
revisit notes.

For years 2019–2024, the same PDF-to-markdown conversion was applied, but the
TOC-based heading correction was not.  As a result, those files may have
incorrect heading levels, missing section markers, or other artefacts that
would cause the extractors (schedule meta, line meta, column meta) to fail or
produce wrong results when applied to earlier years.

This task produces clean, validated markdown files for 2019–2024 so that task
07b (apply metadata extraction backwards) can proceed reliably.

## Approach

The correction strategy depends on whether a given year's PDF has usable TOC
metadata.

### Step 1: Identify which years have TOC metadata

Run the TOC extraction check (or inspect the PDF properties) for each year
2019–2024.  A couple of years reportedly have TOC metadata that can be used
with the same approach as 2025.  For those years:

1. Re-run the PDF conversion with TOC-based heading correction
2. Validate the output using the column/line/schedule coverage checks

### Step 2: Use 2025 structures to correct remaining years

For years without usable TOC metadata, the validated 2025 heading structures
can serve as a reference.  The approach:

1. Identify the heading pattern for each schedule in the 2025 clean files
   (section names, heading levels, ordering)
2. Apply these patterns to the corresponding year's markdown using a script or
   manual comparison
3. The script should flag sections that don't match any known 2025 heading so
   they can be reviewed manually

Known differences between years (e.g. schedules added or retired, renamed
sections) should be handled explicitly rather than assuming the 2025 structure
applies verbatim.

### Step 3: Manual review

After automated correction, run the coverage validators for each year and
manually review any residual gaps or anomalies.  A checklist of schedules to
verify for each year should be maintained in `markdown_files_to_check.md` (or a
new year-specific equivalent).

## Prerequisites

- Task 04c complete (50-code schedule metadata catalogue)
- Task 05b revisit line meta validated against DB
- Task 06b revisit column meta validated against DB (done in current branch)
- Optionally: task 04d (FIR source data investigation) complete

## Deliverables

- `fir_instructions/source_files/{year}/markdown_clean/` directories for
  2019–2024, analogous to the 2025 directory
- Updated `extract_schedule_meta.py`, `extract_line_meta.py`, and
  `extract_column_meta.py` to accept a year parameter (or a markdown directory
  path) so they can be run against any year's clean files
- Coverage check outputs for each year 2019–2024 (analogous to
  `schedule_coverage_check.txt` and `column_coverage_check.txt`)

## Task List

- [ ] Check each year 2019–2024 for TOC metadata in source PDFs
- [ ] Re-run PDF conversion with TOC correction for years where it is available
- [ ] Write a heading-structure comparison script (2025 as reference)
- [ ] Apply automated heading correction to years without TOC metadata
- [ ] Run coverage validators for each year and document gaps
- [ ] Manual review of flagged gaps
- [ ] Update extractor entry points to support multi-year use

## Notes

- The `markdown_files_to_check.md` file already tracks specific files that need
  review; update it with findings from each year as this task progresses.
- Heading artefacts that appear in multiple years likely indicate a systematic
  issue with the PDF conversion; these should be fixed in the conversion
  pipeline rather than corrected manually in each year's output.
