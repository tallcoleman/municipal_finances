# How to Use

## Get and process data

```bash
# download data files
uv run src/municipal_finances/app.py get-fir-data data/source_data

# fix known errors in csvs
uv run src/municipal_finances/app.py fix-csvs data/source_data data/cleaned_data

# combine data files into one
uv run src/municipal_finances/app.py combine-data data/cleaned_data data/output_data
```

## Development

```bash
# run tests
uv run pytest
```