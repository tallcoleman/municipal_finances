# How to Use

## Get and process data

```bash
# download data files
uv run src/municipal_finances/app.py get-fir-data data/source_data

# fix known errors in csvs
uv run src/municipal_finances/app.py fix-csvs data/source_data data/cleaned_data

# combine data files into one
uv run src/municipal_finances/app.py combine-data data/cleaned_data data/output_data

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