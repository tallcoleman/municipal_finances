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