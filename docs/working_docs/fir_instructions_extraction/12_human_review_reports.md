# Task 12: Human Review Report Generation

## Goal

Generate reports that facilitate the human review steps in the extraction plan's Audit Plan section. These reports do not pass/fail automatically — they produce structured output for a human reviewer to verify against the source PDFs.

## Prerequisites

- Tasks 01–09 complete (all metadata tables populated)
- Task 11 (automated audit checks) complete or in progress
- `firrecord` data loaded for verification

## Task List

- [ ] Create `src/municipal_finances/fir_instructions/review_reports.py` module
- [ ] Implement random sample review report
- [ ] Implement section boundary report
- [ ] Implement completeness-by-schedule report
- [ ] Implement column description review report
- [ ] Implement version boundary spot-check report
- [ ] Implement year-over-year diff report
- [ ] Add `review-instructions` CLI command
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### CLI Command

```bash
# Generate all review reports
uv run src/municipal_finances/app.py review-instructions --output-dir reports/

# Generate a specific report
uv run src/municipal_finances/app.py review-instructions --report sample
uv run src/municipal_finances/app.py review-instructions --report section-boundaries
uv run src/municipal_finances/app.py review-instructions --report completeness
uv run src/municipal_finances/app.py review-instructions --report columns
uv run src/municipal_finances/app.py review-instructions --report version-boundaries
uv run src/municipal_finances/app.py review-instructions --report year-diff --year 2025
```

### Report Implementations

**1. Random Sample Review**
Generate a CSV with 30–50 randomly sampled (schedule, line, year) entries showing `line_name`, `description`, and `includes`. The reviewer opens the PDF to the cited schedule and confirms accuracy. Target: 100% name agreement, ≥90% description completeness.

Output columns: `schedule`, `line_id`, `year`, `line_name`, `description`, `includes`, `pdf_page_hint` (approximate page range for the schedule in the relevant PDF, if derivable from schedule order)

**2. Section Boundary Check**
For each schedule, list the first and last `fir_line_meta` row in each `section` group, ordered by `line_id`. The reviewer verifies that section transitions are correct at the boundaries.

Output columns: `schedule`, `section`, `boundary` (first/last), `line_id`, `line_name`

**3. Completeness by Schedule**
For each schedule, report the count of line entries in `fir_line_meta` for each year. The reviewer compares these counts against a manual count of line headings in the PDF's table of contents. Flag discrepancies > 2 lines.

Output columns: `schedule`, `year`, `line_count`

**4. Column Description Review**
For schedules with complex column structures (12, 40, 51A, 51B), generate a review sheet listing each column name and description. The reviewer verifies against the PDF.

Output columns: `schedule`, `column_id`, `column_name`, `description`, `year`

**5. Version Boundary Spot Check**
Pick 10–15 lines that appear in `fir_instruction_changelog` as having changed. For each, show the prior-version row and the new-version row side by side with their `valid_from_year`, `valid_to_year`, and `change_notes`. The reviewer verifies boundaries are set correctly and `change_notes` matches the PDF.

Output columns: `schedule`, `line_id`, `changelog_year`, `changelog_description`, `old_valid_from`, `old_valid_to`, `old_description_excerpt`, `new_valid_from`, `new_valid_to`, `new_description_excerpt`

**6. Year-over-Year Diff**
When a new FIR year's PDF becomes available, generate a diff of extracted metadata against the prior year's. List new lines, deleted lines, and changed descriptions. This catches extraction errors and genuine policy changes simultaneously.

Output columns: `schedule`, `line_id`, `change_type` (new/deleted/changed), `old_value`, `new_value`

### Output Format

All reports are written as CSV files to the specified output directory. The filenames follow the pattern `review_{report_name}.csv`.

## Tests

- [ ] Test that each report generates a non-empty CSV when data exists
- [ ] Test that the random sample report produces the requested number of rows (default 50)
- [ ] Test that the section boundary report includes both first and last lines per section
- [ ] Test that the version boundary spot-check samples from the changelog correctly
- [ ] Test that the year-over-year diff detects known differences in controlled test data
- [ ] Test `--report` flag runs only the specified report
- [ ] Test `--output-dir` flag

## Documentation Updates

- [ ] Add `review-instructions` command to `CLAUDE.md` "Common commands"

## Success Criteria

- All six reports generate correct output from populated metadata tables
- Reports are structured enough to guide efficient human review
- The random sample report uses a fixed seed for reproducibility (configurable)
- Reports can be regenerated after corrections to verify fixes
