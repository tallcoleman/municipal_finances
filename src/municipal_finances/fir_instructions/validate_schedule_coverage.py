"""Check schedule metadata coverage against 2025 FIR database records.

Queries ``firrecord`` for all distinct schedule codes present in 2025 data
using the pre-parsed ``base_schedule_code`` column, then compares them against
the extracted schedule metadata CSV.  Reports:

- Schedules in the database but missing from the CSV (possible extractor gaps).
- Schedules in the CSV but absent from the database (may be unused or new codes
  not yet populated).

Usage::

    uv run src/municipal_finances/app.py validate-schedule-coverage

    # or directly:
    uv run src/municipal_finances/fir_instructions/validate_schedule_coverage.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import typer
from sqlalchemy import text
from sqlmodel import Session

from municipal_finances.database import get_engine
from municipal_finances.fir_instructions.extract_schedule_meta import _DEFAULT_EXPORT_PATH

app = typer.Typer()

_DEFAULT_YEAR = 2025


@app.command()
def validate_schedule_coverage(
    csv_path: Path = typer.Option(
        _DEFAULT_EXPORT_PATH,
        help="Path to the baseline schedule metadata CSV",
    ),
    year: int = typer.Option(
        _DEFAULT_YEAR,
        help="FIR year to check against (marsyear in firrecord)",
    ),
) -> None:
    """Report schedules in firrecord or the CSV that are missing from the other.

    Reads the baseline CSV produced by ``extract-baseline-schedule-meta``, then
    queries the database for all distinct schedule codes present in the given
    year's firrecord data using the pre-parsed ``base_schedule_code`` column.

    Prints two lists:

    - **In DB, not in CSV** — schedules found in live data but no metadata row.
    - **In CSV, not in DB** — metadata rows with no matching data (possibly
      unused schedules or codes not yet loaded).
    """
    # Load schedule codes from CSV.
    csv_schedules: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            csv_schedules.add(row["schedule"])

    typer.echo(f"Loaded {len(csv_schedules)} schedule(s) from {csv_path}.")

    # Query DB for distinct base schedule codes using the pre-parsed column.
    engine = get_engine()
    with Session(engine) as session:
        result = session.execute(
            text("""
                SELECT
                    base_schedule_code,
                    COUNT(*) AS record_count
                FROM firrecord
                WHERE marsyear = :year
                  AND base_schedule_code IS NOT NULL
                GROUP BY base_schedule_code
                ORDER BY base_schedule_code
            """),
            {"year": year},
        ).fetchall()

    db_schedules: dict[str, int] = {code: count for code, count in result}

    typer.echo(
        f"Found {len(db_schedules)} distinct schedule code(s) in "
        f"{year} firrecord data."
    )

    in_db_not_csv = sorted(set(db_schedules) - csv_schedules)
    in_csv_not_db = sorted(csv_schedules - set(db_schedules))

    if not in_db_not_csv and not in_csv_not_db:
        typer.echo("\nNo gaps found — DB schedules and CSV schedules match exactly.")
        return

    if in_db_not_csv:
        typer.echo(
            f"\n{len(in_db_not_csv)} schedule(s) in DB but NOT in CSV "
            "(possible extractor gaps):"
        )
        for code in in_db_not_csv:
            typer.echo(f"  {code}  —  {db_schedules[code]:,} records")

    if in_csv_not_db:
        typer.echo(
            f"\n{len(in_csv_not_db)} schedule(s) in CSV but NOT in DB "
            "(unused codes or not yet loaded):"
        )
        for code in in_csv_not_db:
            typer.echo(f"  {code}")
