# Task 01: Database Models for Instruction Metadata

## Goal

Define the four new database tables (`fir_schedule_meta`, `fir_line_meta`, `fir_column_meta`, `fir_instruction_changelog`) as SQLModel models and ensure they are created by `init-db`.

## Task List

- [ ] Add `FIRScheduleMeta` model to `models.py` with all columns per the plan
- [ ] Add `FIRLineMeta` model to `models.py` with all columns per the plan
- [ ] Add `FIRColumnMeta` model to `models.py` with all columns per the plan
- [ ] Add `FIRInstructionChangelog` model to `models.py` with all columns per the plan
- [ ] Add unique constraints for natural keys:
  - `fir_schedule_meta`: (`schedule`, `valid_from_year`, `valid_to_year`)
  - `fir_line_meta`: (`schedule`, `line_id`, `valid_from_year`, `valid_to_year`)
  - `fir_column_meta`: (`schedule`, `column_id`, `valid_from_year`, `valid_to_year`)
  - `fir_instruction_changelog`: (`year`, `schedule`, `slc_pattern`, `change_type`, `source`) — needed by Task 09's `load-instructions` command for `ON CONFLICT DO NOTHING` idempotency
- [ ] Verify `init-db` creates the new tables (no code change needed — `create_db_and_tables()` uses `SQLModel.metadata.create_all()` which picks up all registered models)
- [ ] Update the `clear-db` command so that it does not need to manually specify which tables should be truncated
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Model Definitions

Follow existing patterns in `models.py`. Key decisions:

- Use `Optional[int]` for `valid_from_year` / `valid_to_year` (nullable).
- Use `bool` with `Field(default=False)` for `is_subtotal` and `is_auto_calculated`.
- `schedule` on `fir_schedule_meta` is `text` (natural key like `"10"`, `"51A"`). `fir_line_meta` and `fir_column_meta` each have both a `schedule_id` serial FK to `fir_schedule_meta.id` and a denormalized `schedule` text field matching the natural key. The `schedule_id` FK is database-internal and excluded from exported CSVs; it is re-derived during load by joining against `fir_schedule_meta` on the `schedule` text value.
- `change_type` on changelog should be a plain `str` field. Validation of allowed values (`new_schedule`, `deleted_schedule`, etc.) can be done at the application level rather than as a database constraint, consistent with how the existing models handle this.
- `source` on changelog is `str` — values are `"pdf_changelog"` or `"data_inferred"`.

### Unique Constraints

Use SQLModel's `__table_args__` with `UniqueConstraint`:

```python
from sqlalchemy import UniqueConstraint

class FIRScheduleMeta(SQLModel, table=True):
    __tablename__ = "fir_schedule_meta"
    __table_args__ = (
        UniqueConstraint("schedule", "valid_from_year", "valid_to_year"),
    )
    ...
```

### clear-db Update

In `db_management.py`, the `clear_db` function truncates tables. Change the function so that it does not rely on manually specifying which tables should be cleared. Order matters for foreign keys, but these tables currently have no FK relationships to each other or existing tables, so order is flexible.

## Tests

- [ ] Test that all four models can be instantiated with valid data
- [ ] Test that `init-db` creates the new tables (check table names exist in metadata)
- [ ] Test that `clear-db` truncates the new tables
- [ ] Test unique constraints by attempting duplicate inserts and verifying IntegrityError
- [ ] Test nullable fields accept None values
- [ ] Test default values for boolean fields

## Documentation Updates

- [ ] Update `CLAUDE.md` "Database" section to list the four new tables with brief descriptions
- [ ] Update `docs/architecture.md` if it describes the database schema
- [ ] Add code comments or a docstring to describe the purpose of each model

## Success Criteria

- `uv run src/municipal_finances/app.py init-db` creates all seven tables without errors
- `uv run src/municipal_finances/app.py clear-db --yes` truncates all seven tables
- All tests pass with 100% coverage on new code
- Models match the column specifications in the extraction plan exactly

## Additional Details

1. Consider adding indexes beyond the unique constraints. Likely candidates: `schedule` (text) on all three metadata tables, `year` on changelog. These would help query performance when joining to `firrecord`. The `schedule_id` serial FK on `fir_line_meta` and `fir_column_meta` will be indexed automatically by PostgreSQL as a FK.
2. The plan mentions `line_id` as a 4-digit string and `column_id` as a 2-digit string. Enforce `max_length` on these fields for consistency with the format validation in the audit plan.
3. The `fir_instruction_changelog` unique constraint includes `slc_pattern`, which is nullable. PostgreSQL treats NULLs as distinct in unique constraints, so two rows with identical `(year, schedule, NULL, change_type, source)` would both be allowed. If schedule-level changelog entries (where `slc_pattern` is NULL) can produce duplicates, consider using a `COALESCE(slc_pattern, '')` expression in a unique index, or handle deduplication at the application level during insertion.
