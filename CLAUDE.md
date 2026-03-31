# Claude Code Guide

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

# Download FIR source data
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
    db_management.py    # CLI commands: init-db, load-data
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

Three tables (defined in `models.py`):

- **`firdatasource`** — one row per FIR reporting year; tracks download metadata and load status
- **`municipality`** — one row per unique municipality; primary key is `munid`
- **`firrecord`** — main fact table (~13.5M rows); foreign key to `municipality`

Bulk inserts in `load-data` use SQLAlchemy Core (`pg_insert().values(...)`) in chunks of 5,000 rows. This chunk size is constrained by PostgreSQL's 65,535 bound parameter limit (11 columns × 5,000 rows = 55,000 parameters).

## API

FastAPI app served by uvicorn inside Docker on port 8000. Docs at `http://localhost:8000/docs`. Root `/` redirects to `/docs`.
