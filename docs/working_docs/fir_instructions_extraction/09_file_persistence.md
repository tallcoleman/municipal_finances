# Task 09: File-Based Persistence (Export/Load CLI Commands)

## Goal

Add `export-instructions` and `load-instructions` CLI commands so that extracted metadata can be shared via version-controlled CSV files without repeating the extraction process.

## Prerequisites

- Task 01 (database models) complete
- At least some data in the metadata tables (from Tasks 03–08) to test export

## Task List

- [ ] Create `src/municipal_finances/fir_instructions_management.py` module with export and load logic
- [ ] Implement `export-instructions` CLI command
- [ ] Implement `load-instructions` CLI command
- [ ] Register the new Typer sub-app in `app.py`
- [ ] Create `fir_instructions/exports/` directory (add `.gitkeep` if needed)
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Export Command

```bash
uv run src/municipal_finances/app.py export-instructions
uv run src/municipal_finances/app.py export-instructions --output-dir path/to/dir
```

**Behavior:**
1. Query all rows from each of the four tables
2. Exclude the `id` (serial PK) column
3. Write each table to a CSV file with headers
4. Nullable fields exported as empty strings
5. Log row counts per table on completion

**Output files:**
```
fir_instructions/exports/
    fir_schedule_meta.csv
    fir_line_meta.csv
    fir_column_meta.csv
    fir_instruction_changelog.csv
```

**Columns to exclude from export:**
Exclude `id` (serial PK) and `schedule_id` (serial FK) from all exports. The `schedule_id` FK is database-internal — its value depends on the `id` assigned to `fir_schedule_meta` rows in a particular database instance and cannot be transferred portably. It is re-derived during load (see below).

**Implementation approach:**
Use pandas `read_sql` + `to_csv` for simplicity:

```python
import pandas as pd
from municipal_finances.database import get_engine

EXCLUDE_COLUMNS = {
    "fir_schedule_meta": ["id"],
    "fir_line_meta": ["id", "schedule_id"],
    "fir_column_meta": ["id", "schedule_id"],
    "fir_instruction_changelog": ["id"],
}

def export_table(engine, table_name: str, output_path: Path):
    df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
    df = df.drop(columns=EXCLUDE_COLUMNS[table_name])
    df.to_csv(output_path, index=False)
    return len(df)
```

### Load Command

```bash
uv run src/municipal_finances/app.py load-instructions
uv run src/municipal_finances/app.py load-instructions --input-dir path/to/dir
```

**Behavior:**
1. Check that target tables exist; if not, run `init-db` implicitly
2. Read each CSV file
3. For `fir_line_meta` and `fir_column_meta`: resolve `schedule_id` FK by joining against the newly-loaded `fir_schedule_meta` rows on the `schedule` text value
4. Insert rows using `INSERT ... ON CONFLICT DO NOTHING` (match on unique constraint / natural key)
5. Log rows inserted vs. skipped per table
6. Load order: `fir_schedule_meta` first (required before FK resolution), then `fir_line_meta`, `fir_column_meta`, then `fir_instruction_changelog`

**Natural keys for conflict detection:**
- `fir_schedule_meta`: (`schedule`, `valid_from_year`, `valid_to_year`)
- `fir_line_meta`: (`schedule`, `line_id`, `valid_from_year`, `valid_to_year`)
- `fir_column_meta`: (`schedule`, `column_id`, `valid_from_year`, `valid_to_year`)
- `fir_instruction_changelog`: (`year`, `schedule`, `slc_pattern`, `change_type`, `source`) — or all non-id columns

**Implementation approach:**
Use pandas `read_csv` + SQLAlchemy Core `pg_insert` with `on_conflict_do_nothing`. For tables with a `schedule_id` FK, resolve it before inserting:

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

def resolve_schedule_ids(engine, df: pd.DataFrame) -> pd.DataFrame:
    """Add schedule_id FK column by matching each line/column to the correct schedule version.

    A line/column's valid_from_year/valid_to_year is its OWN version range, which is
    independent of the schedule's version range. For example, a line added in 2023
    (valid_from_year=2023) may belong to a schedule that has existed since before 2019
    (valid_from_year=NULL). Joining on (schedule, valid_from_year, valid_to_year) would
    fail in this case.

    Instead, match each line/column to the schedule version whose time range covers
    the line/column's valid_from_year (or valid_to_year if valid_from is NULL). If
    multiple schedule versions match, pick the one with the latest valid_from_year
    (the most current version that covers the line's start).
    """
    schedule_map = pd.read_sql(
        "SELECT id AS schedule_id, schedule, valid_from_year, valid_to_year FROM fir_schedule_meta",
        engine,
    )
    # For each row in df, find the schedule_meta row where:
    #   1. schedule text matches
    #   2. The schedule's valid range covers the line/column's valid_from_year
    #      (or valid_to_year if valid_from is NULL, or any version if both are NULL)
    # This requires a range-overlap join rather than an equality join.
    # Implementation should handle the NULL semantics from the versioning conventions.

def load_table(engine, table_name: str, model_class, csv_path: Path, natural_key_columns: list[str]):
    df = pd.read_csv(csv_path)
    df = df.where(df.notna(), None)  # Convert NaN back to None

    if table_name in ("fir_line_meta", "fir_column_meta"):
        df = resolve_schedule_ids(engine, df)

    records = df.to_dict(orient="records")
    stmt = pg_insert(model_class).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=natural_key_columns)

    with engine.begin() as conn:
        result = conn.execute(stmt)
    return result.rowcount
```

### Default Paths

- Export default: `fir_instructions/exports/` (relative to project root)
- Load default: same directory
- Both commands accept `--output-dir` / `--input-dir` to override

### App Registration

In `app.py`, register the new sub-app:

```python
from municipal_finances.fir_instructions_management import fir_instructions_app
app.add_typer(fir_instructions_app)
```

## Tests

- [ ] Test export writes correct CSV files with expected columns (no `id` or `schedule_id` columns)
- [ ] Test export produces correct row counts
- [ ] Test load inserts rows into all four tables
- [ ] Test load correctly resolves `schedule_id` FK for `fir_line_meta` and `fir_column_meta` from `schedule` text value
- [ ] Test load resolves `schedule_id` FK correctly when a line/column's version range differs from the schedule's version range (e.g., line with `valid_from_year=2023` matched to a schedule with `valid_from_year=NULL`)
- [ ] Test load raises an error (or logs a warning) if `schedule` in a line/column CSV has no matching row in `fir_schedule_meta`
- [ ] Test load is idempotent (loading same CSV twice doesn't duplicate rows)
- [ ] Test load handles empty CSV (just headers, no data rows)
- [ ] Test load implicitly creates tables if they don't exist
- [ ] Test round-trip: export then load into a fresh database produces identical data
- [ ] Test `--output-dir` / `--input-dir` flags
- [ ] Test load handles NULL values correctly (empty strings in CSV → NULL in database)

## Documentation Updates

- [ ] Add `export-instructions` and `load-instructions` to `CLAUDE.md` "Common commands"
- [ ] Update `CLAUDE.md` "Project structure" to mention `fir_instructions_management.py` and `fir_instructions/exports/`
- [ ] Update `README.md` with the recommended setup workflow: `init-db` → `load-instructions` → `load-years`

## Success Criteria

- `export-instructions` produces four CSV files with all rows, no `id` or `schedule_id` columns
- `load-instructions` loads all rows and is idempotent
- Round-trip preserves all data (export → clear → load → export → compare: files identical)
- CLI output logs row counts for each table
- Works with default and custom paths

## Verification

```bash
# Export
uv run src/municipal_finances/app.py export-instructions

# Check files exist and have data
wc -l fir_instructions/exports/*.csv

# Clear and reload
uv run src/municipal_finances/app.py clear-db --yes
uv run src/municipal_finances/app.py load-instructions

# Export again and compare
uv run src/municipal_finances/app.py export-instructions --output-dir /tmp/fir_exports
diff fir_instructions/exports/ /tmp/fir_exports/
```

## Additional Considerations

1. The `load-instructions` should use use `ON CONFLICT DO NOTHING` by default with a `--overwrite` flag for `ON CONFLICT DO UPDATE`. `DO NOTHING` is safer (won't overwrite manual corrections), but `DO UPDATE` is more convenient for re-extraction workflows. 
2. The exported CSVs should be committed to version control; make sure they're not accidentally covered by `.gitignore`.
3. Handling CSV files that have columns not in the model (e.g., if the CSV was exported from an older schema): ignore extra columns (but raise a warning); raise an error on missing required columns.
