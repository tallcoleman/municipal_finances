from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import typer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from municipal_finances.data_cleanup import _fix_csv
from municipal_finances.database import create_db_and_tables, get_engine
from municipal_finances.models import FIRDataSource, FIRRecord, Municipality
from municipal_finances.resources import download_fir_csv, get_fir_status_table

app = typer.Typer()

MUNI_COLUMN_MAP = {
    "MUNID": "munid",
    "ASSESSMENT_CODE": "assessment_code",
    "MUNICIPALITY_DESC": "municipality_desc",
    "MSO_NUMBER": "mso_number",
    "SGC_CODE": "sgc_code",
    "UT_NUMBER": "ut_number",
    "MTYPE_CODE": "mtype_code",
    "TIER_CODE": "tier_code",
}

RECORD_COLUMN_MAP = {
    "MUNID": "munid",
    "MARSYEAR": "marsyear",
    "SCHEDULE_DESC": "schedule_desc",
    "SUB_SCHEDULE_DESC": "sub_schedule_desc",
    "SCHEDULE_LINE_DESC": "schedule_line_desc",
    "SCHEDULE_COLUMN_DESC": "schedule_column_desc",
    "SLC": "slc",
    "DATATYPE_DESC": "datatype_desc",
    "AMOUNT": "amount",
    "VALUE_TEXT": "value_text",
    "LAST_UPDATE_DATE": "last_update_date",
}


def _load_csv_into_db(csv_path: Path, engine, chunk_size: int) -> int:
    """Upsert municipalities and insert FIR records from a single cleaned CSV.
    Returns total number of FIR rows loaded."""
    df = pd.read_csv(csv_path, encoding="utf-8", escapechar="\\")
    total_rows = len(df)

    # Upsert municipalities
    muni_cols = list(MUNI_COLUMN_MAP.keys())
    muni_df = df[muni_cols].drop_duplicates(subset=["MUNID"]).rename(columns=MUNI_COLUMN_MAP)
    muni_df = muni_df.where(pd.notna(muni_df), None)
    muni_records = muni_df.to_dict("records")
    with Session(engine) as session:
        stmt = pg_insert(Municipality).values(muni_records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["munid"])
        session.execute(stmt)
        session.commit()

    # Chunk-insert FIR records
    record_cols = list(RECORD_COLUMN_MAP.keys())
    records_df = df[record_cols].rename(columns=RECORD_COLUMN_MAP)
    for i in range(0, total_rows, chunk_size):
        chunk = records_df.iloc[i : i + chunk_size]
        chunk = chunk.where(pd.notna(chunk), None)
        records = chunk.to_dict("records")
        with Session(engine) as session:
            session.execute(pg_insert(FIRRecord).values(records))
            session.commit()
        loaded = min(i + chunk_size, total_rows)
        typer.echo(f"  {loaded:,} / {total_rows:,} rows loaded\r", nl=False)

    return total_rows


@app.command()
def init_db():
    """Creates all database tables using DATABASE_URL from environment."""
    create_db_and_tables()
    typer.echo("Database initialized.")


@app.command()
def load_data(
    parquet_path: Path,
    chunk_size: int = typer.Option(5_000, help="Rows per insert batch"),
):
    """Load FIR data from parquet file into the database using DATABASE_URL from environment."""
    engine = get_engine()

    typer.echo(f"Reading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    total_rows = len(df)
    typer.echo(f"Loaded {total_rows:,} rows.")

    # 1. Upsert municipalities
    typer.echo("Upserting municipalities...")
    muni_cols = list(MUNI_COLUMN_MAP.keys())
    muni_df = df[muni_cols].drop_duplicates(subset=["MUNID"]).rename(columns=MUNI_COLUMN_MAP)
    muni_df = muni_df.where(pd.notna(muni_df), None)
    muni_records = muni_df.to_dict("records")

    with Session(engine) as session:
        stmt = pg_insert(Municipality).values(muni_records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["munid"])
        session.execute(stmt)
        session.commit()
    typer.echo(f"  {len(muni_records)} municipalities upserted.")

    # 2. Chunk-insert FIR records
    typer.echo("Loading FIR records...")
    record_cols = list(RECORD_COLUMN_MAP.keys())
    records_df = df[record_cols].rename(columns=RECORD_COLUMN_MAP)

    for i in range(0, total_rows, chunk_size):
        chunk = records_df.iloc[i : i + chunk_size]
        chunk = chunk.where(pd.notna(chunk), None)
        records = chunk.to_dict("records")
        with Session(engine) as session:
            session.execute(pg_insert(FIRRecord).values(records))
            session.commit()
        loaded = min(i + chunk_size, total_rows)
        typer.echo(f"  {loaded:,} / {total_rows:,} rows loaded", nl=False)
        typer.echo("\r", nl=False)

    typer.echo(f"\n  Done. {total_rows:,} rows loaded.")

    # 3. Upsert FIRDataSource rows (create skeleton if missing)
    years = df["MARSYEAR"].unique().tolist()
    loaded_at = datetime.now(timezone.utc)
    with Session(engine) as session:
        for year in years:
            source = session.get(FIRDataSource, int(year))
            if source:
                source.loaded_into_db = True
                source.loaded_at = loaded_at
            else:
                source = FIRDataSource(
                    year=int(year),
                    loaded_into_db=True,
                    loaded_at=loaded_at,
                )
            session.add(source)
        session.commit()
    typer.echo(f"Marked {len(years)} FIRDataSource years as loaded.")


@app.command()
def load_years(
    year: Optional[int] = typer.Option(None, help="Load a single year"),
    min_year: Optional[int] = typer.Option(None, help="Minimum year to load (inclusive)"),
    max_year: Optional[int] = typer.Option(None, help="Maximum year to load (inclusive)"),
    source_data_path: Path = typer.Option(Path("data/source_data"), help="Directory for downloaded zip/CSV files"),
    cleaned_data_path: Path = typer.Option(Path("data/cleaned_data"), help="Directory for cleaned CSV files"),
    chunk_size: int = typer.Option(5_000, help="Rows per insert batch"),
):
    """Download, clean, and load FIR data for one or more years.

    By default checks and loads all available years. Use --year to load a single
    year, or --min-year / --max-year to restrict the range."""

    if year is not None and (min_year is not None or max_year is not None):
        typer.echo("Error: --year cannot be combined with --min-year or --max-year.", err=True)
        raise typer.Exit(code=1)

    engine = get_engine()

    typer.echo("Fetching FIR status table...")
    current_status = get_fir_status_table()

    # Filter to target years
    if year is not None:
        if str(year) not in current_status:
            typer.echo(f"Error: year {year} not found in FIR status table.", err=True)
            raise typer.Exit(code=1)
        target_years = {str(year): current_status[str(year)]}
    else:
        lo = min_year if min_year is not None else 0
        hi = max_year if max_year is not None else 9999
        target_years = {k: v for k, v in current_status.items() if lo <= v["year"] <= hi}

    if not target_years:
        typer.echo("No matching years found.")
        raise typer.Exit(code=0)

    source_data_path.mkdir(exist_ok=True, parents=True)
    cleaned_data_path.mkdir(exist_ok=True, parents=True)

    for _, entry in sorted(target_years.items(), key=lambda kv: kv[1]["year"]):
        yr = entry["year"]
        remote_last_updated = date.fromisoformat(entry["last_updated"])

        # Skip if already up to date
        with Session(engine) as session:
            db_source = session.get(FIRDataSource, yr)
        if db_source is not None and db_source.loaded_into_db and db_source.last_updated == remote_last_updated:
            typer.echo(f"Year {yr}: already up to date, skipping.")
            continue

        # Download
        typer.echo(f"Year {yr}: downloading...")
        unzipped_files = download_fir_csv(entry, source_data_path)

        csv_files = [f for f in unzipped_files if f.endswith(".csv")]
        if not csv_files:
            typer.echo(f"Year {yr}: no CSV found in zip, skipping.", err=True)
            continue
        source_csv = source_data_path / csv_files[0]

        # Clean
        typer.echo(f"Year {yr}: cleaning CSV...")
        _fix_csv(source_csv, cleaned_data_path)
        cleaned_csv = cleaned_data_path / source_csv.name

        # Load into DB
        typer.echo(f"Year {yr}: loading into database...")
        total_rows = _load_csv_into_db(cleaned_csv, engine, chunk_size)
        typer.echo(f"\nYear {yr}: {total_rows:,} rows loaded.")

        # Upsert FIRDataSource with full metadata
        loaded_at = datetime.now(timezone.utc)
        with Session(engine) as session:
            source = session.get(FIRDataSource, yr)
            if source:
                source.last_updated = remote_last_updated
                source.date_posted = date.fromisoformat(entry["date_posted"])
                source.file_url = entry["file_url"]
                source.loaded_into_db = True
                source.loaded_at = loaded_at
            else:
                source = FIRDataSource(
                    year=yr,
                    last_updated=remote_last_updated,
                    date_posted=date.fromisoformat(entry["date_posted"]),
                    file_url=entry["file_url"],
                    loaded_into_db=True,
                    loaded_at=loaded_at,
                )
            session.add(source)
            session.commit()

        typer.echo(f"Year {yr}: done.")
