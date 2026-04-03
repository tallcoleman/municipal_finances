# Architecture and Technology Stack

## Overview

The app has two main components: a **data pipeline** (CLI tools for downloading and loading data) and a **web API** for querying it. Both run locally using Docker for the database and API server.

## Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.14 | |
| Package manager | [uv](https://docs.astral.sh/uv/) | Dependency locking, virtual envs, script running |
| CLI | [Typer](https://typer.tiangolo.com/) | Data pipeline commands |
| Web API | [FastAPI](https://fastapi.tiangolo.com/) | Served via uvicorn |
| ORM / models | [SQLModel](https://sqlmodel.tiangolo.com/) | Combines SQLAlchemy and Pydantic |
| Database | PostgreSQL 17 | Runs in Docker |
| Containers | Docker Compose | PostgreSQL + API service |
| Data processing | pandas + pyarrow | CSV cleaning and parquet output |
| HTML scraping | BeautifulSoup4 | FIR download page |
| Testing | pytest | |

## Key Design Decisions

### Single CLI entry point

All data pipeline commands are exposed through a single Typer app (`src/municipal_finances/app.py`) that composes sub-apps from each module. This keeps the interface consistent and easy to extend.

### SQLModel for database models

SQLModel was chosen because it unifies SQLAlchemy (for database access) and Pydantic (for API serialization) in a single model definition. This avoids maintaining separate ORM models and API schemas.

### PostgreSQL over SQLite

PostgreSQL was chosen over SQLite to better handle the scale of the dataset (~13.5M rows across 26 years) and to support future multi-user or hosted deployments.

### Bulk inserts via SQLAlchemy Core

Loading 13.5M rows via the ORM (`session.add()` in a loop) is too slow. The `load-years` and `load-data` commands use SQLAlchemy Core bulk inserts (`pg_insert().values(...)`) in chunks of 5,000 rows. This chunk size is constrained by PostgreSQL's limit of 65,535 bound parameters per query — with 11 columns per `FIRRecord` row, that gives a maximum of ~5,957 rows per insert.

### DATABASE_URL from environment

The database connection string is read from a `DATABASE_URL` environment variable (loaded from a `.env` file via python-dotenv). This keeps credentials out of source code and makes it straightforward to point the app at different databases (local, staging, production) without code changes.

### Docker Compose for local development

Docker Compose runs two services: `db` (PostgreSQL with a named volume for persistence) and `api` (the FastAPI app). PostgreSQL's port 5432 is forwarded to the host so the data pipeline CLI can connect directly without running inside Docker.

### Data pipeline runs on the host

The data download, cleaning, and loading steps run on the host machine rather than inside Docker, since the raw data files live in the local `data/` directory. The pipeline connects to the Dockerized PostgreSQL via the forwarded port.

The primary workflow is the `load-years` command, which runs the full pipeline (download → clean → load) in a single step and skips years that are already up to date. The individual steps (`get-fir-data`, `fix-csvs`, `combine-data`, `load-data`) remain available for working with pre-downloaded files or producing a combined parquet for analysis.

### Database schema

The database has seven tables:

**Core FIR data (three tables):**

- **`FIRDataSource`** — one row per FIR reporting year; tracks download metadata and whether the year's data has been loaded into the database. Replaces the earlier `fir_status.json` file.
- **`Municipality`** — one row per unique municipality (`munid` as primary key); stores identifying fields like name, assessment code, tier, and type.
- **`FIRRecord`** — the main fact table (~13.5M rows); stores each individual data point with a foreign key to `Municipality`.

This structure avoids repeating municipality metadata on every one of the millions of data rows.

**FIR instruction metadata (four tables):**

Extracted from the annual FIR Instructions PDFs and versioned using `valid_from_year` / `valid_to_year` fields (NULL means "before our earliest PDF" or "still current" respectively).

- **`FIRScheduleMeta`** (`fir_schedule_meta`) — one row per (schedule, version); schedule name, category, and description paragraph.
- **`FIRLineMeta`** (`fir_line_meta`) — one row per (schedule, line, version); the richest table, covering narrative reporting rules, includes/excludes, subtotal flags, and carry-forward references.
- **`FIRColumnMeta`** (`fir_column_meta`) — one row per (schedule, column, version); column name and description.
- **`FIRInstructionChangelog`** (`fir_instruction_changelog`) — one row per documented or inferred change event across all years; the source of truth for setting `valid_from_year` / `valid_to_year` on the metadata tables. `source` distinguishes PDF-documented changes (`"pdf_changelog"`) from data-inferred ones (`"data_inferred"`).

`FIRLineMeta` and `FIRColumnMeta` each carry a `schedule_id` FK to `fir_schedule_meta` and a denormalized `schedule` text field. The FK is database-internal and is excluded from exported CSVs; it is re-derived during load by joining on the `schedule` text value.
