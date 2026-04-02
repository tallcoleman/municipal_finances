# Ontario Municipal Finances Explorer

## Project Goals

Make it easier for researchers, interested citizens, and policy-makers to explore the data available from [Ontario Municipal Financial Information Returns](https://efis.fma.csc.gov.on.ca/fir/index.php/en/financial-information-return-en/) ("FIR").

The FIR system includes data on "municipal financial position and activities, such as assets, liabilities, revenue, expenses, over the course of the previous fiscal year (based on the audited financial statements), as well as municipal statistical information."

See additional notes in the `docs/` folder

## How to use

### Get and process data

```bash
# start containers (add -d to detach)
# web API will be available at localhost:8000 once data is loaded
docker compose up

# stop and remove containers
docker compose down

# create database tables
uv run src/municipal_finances/app.py init-db

# download, clean, and load all available years in one step
uv run src/municipal_finances/app.py load-years

# load a specific year, or restrict to a year range
uv run src/municipal_finances/app.py load-years --year 2023
uv run src/municipal_finances/app.py load-years --min-year 2020 --max-year 2023
```

### Granular pipeline steps

For less common use cases (e.g. working with pre-downloaded files or building a combined parquet for analysis), the individual pipeline steps are available separately:

```bash
# download source data files and update firdatasource table
uv run src/municipal_finances/app.py get-fir-data data/source_data

# fix known CSV formatting errors
uv run src/municipal_finances/app.py fix-csvs data/source_data data/cleaned_data

# combine cleaned CSVs into a single parquet file
uv run src/municipal_finances/app.py combine-data data/cleaned_data data/output_data

# load data from a parquet file into the database
uv run src/municipal_finances/app.py load-data data/output_data/fir_data_all_years.parquet
```

## Development

```bash
# run tests
uv run pytest

# delete all data from all tables (prompts for confirmation)
uv run src/municipal_finances/app.py clear-db
uv run src/municipal_finances/app.py clear-db --yes  # skip confirmation
```

### Database migrations

Schema migrations are managed with [Alembic](https://alembic.sqlalchemy.org/). Migration scripts live in `alembic/versions/`. The `env.py` reads `DATABASE_URL` from the environment (or `.env`) and uses `SQLModel.metadata` for autogenerate support.

```bash
# Apply all pending migrations to bring the database up to date
uv run alembic upgrade head

# Roll back the most recent migration
uv run alembic downgrade -1

# Check current migration state
uv run alembic current

# View migration history
uv run alembic history
```

**Creating a new migration after changing models:**

1. Edit the relevant model(s) in `src/municipal_finances/models.py`.
2. Autogenerate a migration script (replace `<description>` with a short snake_case summary):

   ```bash
   uv run alembic revision --autogenerate -m "<description>"
   ```

3. Review the generated file in `alembic/versions/` — autogenerate is not perfect and may miss some changes (e.g. check constraints, custom types). Adjust as needed.
4. Apply the migration:

   ```bash
   uv run alembic upgrade head
   ```

5. Commit both the model change and the migration script together.