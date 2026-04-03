# Claude Code Guide

## Documentation

When making code changes, make sure that all key functions have descriptive docstrings. In addition, check whether any of the following need to be updated to reflect them and update as needed:

- `CLAUDE.md` — common commands, project structure, database notes
- `README.md` — user-facing usage instructions
- `docs/architecture.md` — design decisions and technology choices

## Environment

- Use `uv run` to run Python scripts and tools — do not use `python` directly.
- Dependencies are managed with `uv`. After changing `pyproject.toml`, run `uv sync` to update the lockfile.
- The app requires a `DATABASE_URL` environment variable pointing to a PostgreSQL database. Store it in a `.env` file (see `.env.example`); it is loaded automatically via python-dotenv.

## Common commands

```bash
# Install / sync dependencies
uv sync

# Run tests
uv run pytest

# Start PostgreSQL + API containers
docker compose up -d

# Stop containers
docker compose down

# Create database tables (requires DATABASE_URL in env or .env)
uv run src/municipal_finances/app.py init-db

# Delete all data from all tables (development use; prompts for confirmation)
uv run src/municipal_finances/app.py clear-db
uv run src/municipal_finances/app.py clear-db --yes  # skip confirmation

# Download, clean, and load all available years in one step (default workflow)
uv run src/municipal_finances/app.py load-years

# Load a specific year, or restrict by range
uv run src/municipal_finances/app.py load-years --year 2023
uv run src/municipal_finances/app.py load-years --min-year 2020 --max-year 2023

# --- Granular pipeline steps (less common) ---

# Download FIR source data (also updates firdatasource table)
uv run src/municipal_finances/app.py get-fir-data data/source_data

# Clean known CSV errors
uv run src/municipal_finances/app.py fix-csvs data/source_data data/cleaned_data

# Combine cleaned CSVs into a single parquet file
uv run src/municipal_finances/app.py combine-data data/cleaned_data data/output_data

# Load parquet into the database
uv run src/municipal_finances/app.py load-data data/output_data/fir_data_all_years.parquet
```

## Project structure

```
src/municipal_finances/
    app.py              # Typer CLI entry point — composes all sub-apps
    resources.py        # Download FIR data; update FIRDataSource table
    data_cleanup.py     # Fix known CSV formatting errors
    data_management.py  # Combine cleaned CSVs into a single parquet file
    models.py           # SQLModel database models
    database.py         # Engine / session factory (reads DATABASE_URL)
    db_management.py    # CLI commands: init-db, clear-db, load-data, load-years
    slc.py              # SLC parsing utilities (parse_slc, slc_to_pdf_format, pdf_slc_to_components)
    api/
        main.py         # FastAPI app
        routes/
            municipalities.py
            fir_records.py
            fir_sources.py
data/
    source_data/        # Raw downloaded zip + CSV files (not in version control)
    cleaned_data/       # Cleaned CSVs (not in version control)
    output_data/        # Combined parquet file (not in version control)
docs/                   # Project documentation
```

## Database

Seven tables (defined in `models.py`):

- **`firdatasource`** — one row per FIR reporting year; tracks download metadata and load status
- **`municipality`** — one row per unique municipality; primary key is `munid`
- **`firrecord`** — main fact table (~13.5M rows); foreign key to `municipality`
- **`fir_schedule_meta`** — one row per (schedule, version); describes each FIR schedule and its valid year range
- **`fir_line_meta`** — one row per (schedule, line, version); narrative reporting rules for each line
- **`fir_column_meta`** — one row per (schedule, column, version); describes what each column captures
- **`fir_instruction_changelog`** — one row per documented or inferred change event; source of truth for version boundaries in the metadata tables

Bulk inserts in `load-data` use SQLAlchemy Core (`pg_insert().values(...)`) in chunks of 5,000 rows. This chunk size is constrained by PostgreSQL's 65,535 bound parameter limit (11 columns × 5,000 rows = 55,000 parameters).

## API

FastAPI app served by uvicorn inside Docker on port 8000. Docs at `http://localhost:8000/docs`. Root `/` redirects to `/docs`.
