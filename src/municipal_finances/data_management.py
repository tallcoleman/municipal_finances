from pathlib import Path

import pandas as pd

import typer

app = typer.Typer()


@app.command()
def combine_data(cleaned_data_path: Path, output_path: Path):
    """Combine multiple FIR data file CSVs into one"""

    fixed_source_files = list(cleaned_data_path.glob("*.csv"))
    source_dfs = []

    for fp in fixed_source_files:
        print(f"reading {fp.name}", end="\r", flush=True)
        source_dfs.append(pd.read_csv(fp, encoding="utf-8", escapechar="\\"))

    all_fir_data = pd.concat(source_dfs)

    # this takes a couple minutes
    output_path.mkdir(exist_ok=True)
    all_fir_data.to_parquet(output_path / "fir_data_all_years.parquet")
