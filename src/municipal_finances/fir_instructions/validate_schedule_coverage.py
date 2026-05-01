"""Check schedule metadata coverage against 2025 FIR database records.

Queries ``firrecord`` for all distinct schedule codes present in 2025 data
using the pre-parsed ``base_schedule_code`` and ``schedule_code`` columns, then
compares them against the extracted schedule metadata CSV.  Reports gaps
separately for base schedules and sub-schedules:

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


def _report_gaps(
    label: str,
    db_codes: dict[str, int],
    csv_codes: set[str],
) -> bool:
    """Print gap report for one schedule tier; return True if any gaps found."""
    in_db_not_csv = sorted(set(db_codes) - csv_codes)
    in_csv_not_db = sorted(csv_codes - set(db_codes))

    if not in_db_not_csv and not in_csv_not_db:
        typer.echo(f"  No gaps — {label} match exactly.")
        return False

    if in_db_not_csv:
        typer.echo(
            f"  {len(in_db_not_csv)} {label} in DB but NOT in CSV "
            "(possible extractor gaps):"
        )
        for code in in_db_not_csv:
            typer.echo(f"    {code}  —  {db_codes[code]:,} records")

    if in_csv_not_db:
        typer.echo(
            f"  {len(in_csv_not_db)} {label} in CSV but NOT in DB "
            "(unused codes or not yet loaded):"
        )
        for code in in_csv_not_db:
            typer.echo(f"    {code}")

    return True


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
    queries the database for distinct schedule codes in the given year's
    firrecord data.  Reports gaps separately for base schedules (e.g. ``"10"``)
    and sub-schedules (e.g. ``"22A"``).
    """
    # Partition CSV entries into base schedules (2-char) and sub-schedules (3-char).
    csv_base: set[str] = set()
    csv_sub: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row["schedule"]
            (csv_sub if len(code) == 3 else csv_base).add(code)

    typer.echo(
        f"Loaded {len(csv_base)} base schedule(s) and {len(csv_sub)} "
        f"sub-schedule(s) from {csv_path}."
    )

    engine = get_engine()
    with Session(engine) as session:
        base_rows = session.execute(
            text("""
                SELECT base_schedule_code, COUNT(*) AS record_count
                FROM firrecord
                WHERE marsyear = :year
                  AND base_schedule_code IS NOT NULL
                GROUP BY base_schedule_code
                ORDER BY base_schedule_code
            """),
            {"year": year},
        ).fetchall()

        sub_rows = session.execute(
            text("""
                SELECT schedule_code, COUNT(*) AS record_count
                FROM firrecord
                WHERE marsyear = :year
                  AND sub_schedule_code IS NOT NULL
                GROUP BY schedule_code
                ORDER BY schedule_code
            """),
            {"year": year},
        ).fetchall()

    db_base: dict[str, int] = {code: count for code, count in base_rows}
    db_sub: dict[str, int] = {code: count for code, count in sub_rows}

    typer.echo(
        f"Found {len(db_base)} distinct base schedule(s) and "
        f"{len(db_sub)} distinct sub-schedule(s) in {year} firrecord data."
    )

    typer.echo("\nBase schedules:")
    base_gaps = _report_gaps("base schedule(s)", db_base, csv_base)

    typer.echo("\nSub-schedules:")
    sub_gaps = _report_gaps("sub-schedule(s)", db_sub, csv_sub)

    if not base_gaps and not sub_gaps:
        typer.echo("\nNo gaps found overall.")
