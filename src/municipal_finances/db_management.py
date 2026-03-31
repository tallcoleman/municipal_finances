from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import typer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from municipal_finances.database import create_db_and_tables, get_engine
from municipal_finances.models import FIRDataSource, FIRRecord, Municipality

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


@app.command()
def init_db():
    """Creates all database tables using DATABASE_URL from environment."""
    create_db_and_tables()
    typer.echo("Database initialized.")


@app.command()
def load_data(
    parquet_path: Path,
    chunk_size: int = typer.Option(50_000, help="Rows per insert batch"),
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

    # 3. Mark FIRDataSource rows as loaded
    years = df["MARSYEAR"].unique().tolist()
    loaded_at = datetime.now(timezone.utc)
    with Session(engine) as session:
        for year in years:
            source = session.get(FIRDataSource, int(year))
            if source:
                source.loaded_into_db = True
                source.loaded_at = loaded_at
                session.add(source)
        session.commit()
    typer.echo(f"Marked {len(years)} FIRDataSource years as loaded.")
