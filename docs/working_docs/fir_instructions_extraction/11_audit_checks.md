# Task 11: Automated Audit Checks

## Goal

Implement the automated checks from the extraction plan's Audit Plan section as runnable scripts or CLI commands. These checks validate the completeness and correctness of extracted metadata.

## Prerequisites

- Tasks 01–09 complete (all metadata tables populated)
- `firrecord` data loaded for verification

## Task List

- [ ] Create `src/municipal_finances/fir_instructions/audit.py` module
- [ ] Implement coverage check (lines)
- [ ] Implement column coverage check (columns in data not documented in `fir_column_meta`)
- [ ] Implement orphan check
- [ ] Implement format validation
- [ ] Implement non-overlapping version range check
- [ ] Implement SLC cross-reference check
- [ ] Implement changelog completeness check
- [ ] Implement inferred-vs-documented reconciliation check
- [ ] Add `audit-instructions` CLI command
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### CLI Command

```bash
# Run all audit checks
uv run src/municipal_finances/app.py audit-instructions

# Run a specific check
uv run src/municipal_finances/app.py audit-instructions --check coverage
uv run src/municipal_finances/app.py audit-instructions --check orphan
uv run src/municipal_finances/app.py audit-instructions --check format
uv run src/municipal_finances/app.py audit-instructions --check version-ranges
uv run src/municipal_finances/app.py audit-instructions --check cross-reference
uv run src/municipal_finances/app.py audit-instructions --check changelog
uv run src/municipal_finances/app.py audit-instructions --check column-coverage
uv run src/municipal_finances/app.py audit-instructions --check reconciliation
```

### Check Implementations

**1. Coverage Check**
Query `firrecord` for all distinct (schedule, line) pairs per year. Every pair should have a matching `fir_line_meta` row for that year. Flag gaps.

```sql
SELECT DISTINCT
    -- parse schedule and line from slc
    r.marsyear,
    parsed_schedule,
    parsed_line
FROM firrecord r
WHERE NOT EXISTS (
    SELECT 1 FROM fir_line_meta m
    WHERE m.schedule = parsed_schedule
    AND m.line_id = parsed_line
    AND (m.valid_from_year IS NULL OR m.valid_from_year <= r.marsyear)
    AND (m.valid_to_year IS NULL OR m.valid_to_year >= r.marsyear)
)
```

**2. Orphan Check**
Every `fir_line_meta` row should have corresponding `firrecord` rows in at least one year within its valid range. Flag entries with zero data matches.

**3. Format Validation**
- `line_id` matches `/^\d{4}$/`
- `column_id` matches `/^\d{2}$/`
- `schedule` is in the known schedule list for that year

**4. Non-overlapping Version Ranges**
For each (schedule, line_id) pair, verify no two rows have overlapping valid year ranges. Same for (schedule, column_id).

**5. SLC Cross-Reference**
Where `carry_forward_from` is populated, verify the referenced SLC exists in the data for the relevant year.

**6. Changelog Completeness**
Every `fir_instruction_changelog` row with `source = "pdf_changelog"` should have produced at least one versioned row (with non-null `valid_from_year`) in the corresponding metadata table.

**7. Column Coverage Check**
Analogous to the line coverage check (#1), but for columns. Query `firrecord` for all distinct (schedule, column) pairs per year. Every pair should have a matching `fir_column_meta` row for that year. Flag gaps.

**8. Inferred-vs-Documented Reconciliation**
For years where both PDF changelogs and data-inferred changes exist (2019–2025), compare the two sets. Flag:
- Inferred changes not in the PDF changelog (potential data anomalies or missed extractions)
- PDF changelog entries not detected by inference (potential inference gaps or non-structural changes)

This check implements item 6 of the Human Review Protocol in the extraction plan ("Inferred vs. documented reconciliation"). The reconciliation queries from Task 08b's verification section can be reused here.

### Output Format

Each check should return a structured result:

```python
@dataclass
class AuditResult:
    check_name: str
    passed: bool
    total_checked: int
    issues_found: int
    issues: list[dict]  # Details of each issue
```

The CLI should print a summary table and optionally write detailed results to a file.

### Exit Code

The CLI command should exit with code 0 if all checks pass, code 1 if any check fails. This supports CI integration.

## Tests

- [ ] Test each check function with controlled data:
  - Seed data that should pass all checks → verify all pass
  - Seed data with specific violations → verify correct check fails
- [ ] Test coverage check catches a (schedule, line) pair in `firrecord` with no metadata match
- [ ] Test orphan check catches metadata with no data match
- [ ] Test format validation catches invalid `line_id` (e.g., `"41"` instead of `"0041"`)
- [ ] Test version range overlap detection
- [ ] Test cross-reference check catches invalid `carry_forward_from`
- [ ] Test changelog completeness catches unmatched changelog entries
- [ ] Test column coverage check catches (schedule, column) in `firrecord` with no `fir_column_meta` match
- [ ] Test reconciliation check identifies inferred changes not in PDF changelog
- [ ] Test reconciliation check identifies PDF changelog entries not detected by inference
- [ ] Test CLI exit codes (0 for pass, 1 for fail)
- [ ] Test `--check` flag runs only the specified check

## Documentation Updates

- [ ] Add `audit-instructions` command to `CLAUDE.md` "Common commands"

## Success Criteria

- All eight automated checks are implemented and runnable via CLI
- Each check produces clear, actionable output identifying specific issues
- The CLI provides both summary and detailed views
- Exit codes support CI integration
- Tests verify both passing and failing scenarios for each check

## Verification

```bash
# Run all checks (should pass if extraction is complete and correct)
uv run src/municipal_finances/app.py audit-instructions

# Expected output format:
# ✓ Coverage check: 0 gaps found (checked 5,432 schedule/line pairs)
# ✓ Orphan check: 0 orphans found (checked 847 metadata rows)
# ✓ Format validation: 0 issues found
# ✓ Version ranges: 0 overlaps found
# ✓ SLC cross-reference: 0 broken references (checked 42 references)
# ✓ Changelog completeness: 0 unmatched entries (checked 107 changelog rows)
# ✓ Column coverage: 0 gaps found (checked 1,234 schedule/column pairs)
# ✓ Reconciliation: 0 unmatched entries (checked 85 inferred + 107 documented)
#
# All 8 checks passed.
```

## Additional Considerations

1. The audit checks should not be blocking (stop on first failure) -- they should run all checks and report. This is preferable since issues are often related and seeing the full picture helps prioritize fixes.
2. For the coverage check, if there are `firrecord` rows where the SLC can't be parsed (malformed data), report them separately as "unparseable SLCs" rather than coverage gaps.
3. The audit output should be machine-readable (JSON) in addition to human-readable, since this would support automated pipelines. Add a `--format json` flag to enable this.
4. For the orphan check, some metadata rows may intentionally have no data matches — e.g., lines that exist in the instructions but no municipality has ever reported on them. If this is the case, add an exclusion mechanism (e.g., an `expected_orphans.csv` file).
5. Audit checks should not run automatically after `load-instructions` or `export-instructions`, but the recommended workflow should be documented as `load-instructions` → `audit-instructions`.
