# Shared Instructions for FIR Instructions Extraction

These conventions apply to all tasks in this implementation plan.

---

## Coding Conventions

- **ORM**: Use SQLModel for all new database models, consistent with existing `models.py`.
- **CLI**: Use Typer for new CLI commands, registered as sub-apps on the main `app.py`.
- **Database access**: Use `get_engine()` from `database.py`. Bulk inserts should use SQLAlchemy Core (`pg_insert`) with chunking, not ORM `.add()`.
- **Imports**: Follow existing patterns — `from municipal_finances.database import get_engine`, etc.

## Testing Conventions

- All new code must have tests. Target 100% coverage (matching existing `pyproject.toml` config).
- Tests go in `tests/` with the naming pattern `test_<module>.py`. Where appropriate, organize the tests with directories in a structure that mirrors `src/`.
- Use `pytest-mock` (`mocker` fixture) for mocking, consistent with existing tests.
- Use session-scoped engine fixtures and function-scoped session fixtures from `conftest.py`.
- Add seed helper functions (e.g., `seed_schedule_meta()`) following the pattern in `test_api.py`.
- Test CLI commands via `typer.testing.CliRunner` and the app, as done in `test_db_management.py`.

## File Locations

- New models: add to `src/municipal_finances/models.py`
- New CLI commands: add to new module(s) under `src/municipal_finances/`, registered in `app.py`
- Extraction scripts/tooling: `src/municipal_finances/fir_instructions/`
- Source PDFs: `fir_instructions/source_files/`
- Exported CSVs: `fir_instructions/exports/`
- Tests: `tests/`

## Database Migration Strategy

New tables should be created via `SQLModel.metadata.create_all()` in the existing `init-db` command (which already calls `create_db_and_tables()`). No Alembic migration is needed for new tables since `create_all()` is additive — it won't modify existing tables. If existing tables need changes, use Alembic.

## Versioning Semantics

All metadata tables use `valid_from_year` / `valid_to_year` to express version ranges:

- `valid_from_year = NULL`: applies from before our earliest PDF (pre-2022)
- `valid_to_year = NULL`: still currently in effect
- Query for year Y: `(valid_from_year IS NULL OR valid_from_year <= Y) AND (valid_to_year IS NULL OR valid_to_year >= Y)`

## PDF Source Files

Available PDFs and their approximate page counts:

| File                     | Pages | Notes                                    |
| ------------------------ | ----- | ---------------------------------------- |
| FIR2025 Instructions.pdf | ~500  | Primary baseline source                  |
| FIR2024 Instructions.pdf | ~490  |                                          |
| FIR2023 Instructions.pdf | ~480  | Major changes year (PS 3280, PS 3450)    |
| FIR2022 Instructions.pdf | ~470  | Earliest with structured Content Changes |
| FIR2021 Instructions.pdf | 314   |                                          |
| FIR2020 Instructions.pdf | 324   |                                          |
| FIR2019 Instructions.pdf | 306   |                                          |
| FIR2018 Introduction.pdf | 28    | Introduction section only                |

Instructions documents from 2018–2021 have not yet been analyzed in detail to determine the significance of the changes and if there are differences in document structure compared to the 2022–2025 documents.

## SLC Format

The `slc` field on `firrecord` encodes schedule, line, and column as: `slc.{schedule_code}.L{line_4digits}.C{column_2digits}.{sub}`.

Example: `slc.10.L9930.C01.` = Schedule 10, Line 9930, Column 01.

The PDF references use a different format: `SLC 10 9930 01` (space-separated).

## Commit and PR Practices

- Changes for each task should be made on a new branch.
- Create a commit for each item in the task list or logical sub-step in accomplishing the task.
- Commit after each change is complete and tests pass.
- Each task should be a self-contained, reviewable unit of work.
- Once each task is done, open a pull request to merge the branch into main, with a concise, but informative description of the task and changes made.
- Do not combine multiple tasks into a single commit.
