# Ontario Municipal Finances Explorer

## Project Goals

Make it easier for researchers, interested citizens, and policy-makers to explore the data available from [Ontario Municipal Financial Information Returns](https://efis.fma.csc.gov.on.ca/fir/index.php/en/financial-information-return-en/) ("FIR").

The FIR system includes data on "municipal financial position and activities, such as assets, liabilities, revenue, expenses, over the course of the previous fiscal year (based on the audited financial statements), as well as municipal statistical information."

See additional notes in the `docs/` folder

## How to use

### Get and process data

```bash
# download data files
uv run src/municipal_finances/app.py get-fir-data data/source_data

# fix known errors in csvs
uv run src/municipal_finances/app.py fix-csvs data/source_data data/cleaned_data

# combine data files into one
uv run src/municipal_finances/app.py combine-data data/cleaned_data data/output_data

# start containers (add -d for detach if you don't want to see the logs)
# web API will run at localhost:8000 (data needs to be loaded first - see notes below)
docker compose up

# stop and remove containers
docker compose down

# start database
uv run src/municipal_finances/app.py init-db

# load data into database
uv run src/municipal_finances/app.py load-data data/output_data/fir_data_all_years.parquet
```

## Development

```bash
# run tests
uv run pytest
```