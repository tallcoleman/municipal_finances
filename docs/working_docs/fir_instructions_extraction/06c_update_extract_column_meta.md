# Task 06c: Update Column Metadata Extraction

## Dependencies

This task should be completed after:

- **04c** (`04c_extend_schedule_meta_50_codes.md`) — ensures the schedule catalogue covers all schedules whose column metadata will be validated
- **05c** (validate line meta against DB) — ensures line metadata is stable before revisiting column metadata

## Context

The column metadata extracted by `extract_column_meta.py` captures `section_name` as free text from
the FIR instructions documents, but does not record a `column_section` code. The `firrecord` table,
however, stores `column_section` as the two-digit numeric portion of the SLC (e.g. `"01"`, `"02"`),
derived directly from the source data.

Because `column_section` is not part of the FIR instructions SLC format (the instructions use a
simpler `Schedule Line Column` notation that omits section information), its numeric code cannot be
read from the documents directly. It must be inferred from the order in which distinct `section_name`
values appear within each schedule's extracted metadata: the first distinct section → `"01"`, the
second → `"02"`, and so on.

Adding this inferred `column_section` to the metadata enables a cross-validation against the
database: if the inference is correct, the count of `(column_section, column_id)` combinations per
schedule in the DB should match the count of `(section_name, column_id)` combinations per schedule
in the metadata. A mismatch signals either missing documentation coverage or a mis-inference that
needs human review.

## Goal

1. Add a `column_section` field to the column metadata CSV, populated by inferring the section order
   from the document.
2. Validate that the `(column_section, column_id)` counts per schedule match between the DB and the
   updated metadata.

## Proposed Changes

### `extract_column_meta.py`

- Add `column_section` to the CSV fieldnames list (after `column_id`, before `column_name`).
- In `extract_all_column_meta()` (or a post-processing step), assign `column_section` by ranking the
  order of first appearance of each distinct `section_name` within a schedule:

  ```python
  # Within each schedule, number sections in order of first appearance
  seen: dict[str | None, str] = {}
  for row in schedule_rows:
      sn = row["section_name"]
      if sn not in seen:
          seen[sn] = f"{len(seen) + 1:02d}"
      row["column_section"] = seen[sn]
  ```

  Schedules with a single section (or no `section_name`) get `"01"` throughout.

- Update `save_to_csv()` and `load_from_csv()` to include the new field.
- Update the `fir_column_meta` database model and `insert_column_meta()` if `column_section` is to
  be stored in the DB as well (coordinate with `models.py`).

### Validation script (new or integrated into `validate_column_coverage.py`)

Compare, per schedule:

- **DB side**: `SELECT schedule_code, column_section, column_id, COUNT(*) FROM firrecord WHERE marsyear = :year GROUP BY schedule_code, column_section, column_id`
- **Metadata side**: distinct `(schedule, column_section, column_id)` triples from the updated CSV

Report schedules where the set of `(column_section, column_id)` pairs differs between DB and
metadata. For each mismatch, print:

- Pairs present in DB but absent from metadata → possible documentation gap or inference error
- Pairs present in metadata but absent from DB → possibly valid (column exists in docs but has no
  recorded values for the chosen year) — lower priority

## Notes on Edge Cases

- Schedules with no `section_name` values in the extracted metadata should be assigned `"01"` for all
  rows.
- The S51A/S51B inherited-column synthesis in `_synthesize_s51b_inherited_columns()` may need to
  copy the `column_section` field from the S51A source rows.
- Schedules 76X, 80C, and 81X use non-numeric line IDs (`000A`, `000B`) — this does not affect
  column section inference, but worth keeping in mind during testing.
- If a schedule's `section_name` values in the document don't align with the DB's `column_section`
  codes (e.g. because a section was split or merged between document versions and the DB data), the
  mismatch report will flag it for human review.

## Task List

- [ ] Add `column_section` field to `extract_column_meta.py` CSV schema and fieldnames list
- [ ] Implement section-order inference in `extract_all_column_meta()`
- [ ] Handle S51B inherited-column synthesis for the new field
- [ ] Update `save_to_csv()` and `load_from_csv()`
- [ ] Re-run extraction and regenerate `fir_instructions/exports/baseline_column_meta.csv`
- [ ] Add or extend validation to cross-check `(column_section, column_id)` counts between DB and metadata
- [ ] Review and triage any mismatches flagged by the validation
- [ ] Update `CLAUDE.md` if the database model or CSV schema changes
