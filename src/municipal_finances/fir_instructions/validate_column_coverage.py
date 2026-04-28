"""Check column metadata coverage against 2025 FIR database records.

Queries ``firrecord`` for all distinct (schedule, column_id) pairs present in
2025 data, then compares them against the extracted column metadata CSV.  Prints
a grouped report of any (schedule, column_id) combinations that appear in the
live data but have no metadata entry.

Each gap should be triaged as either:

- **Genuinely undocumented** — the FIR instructions don't describe the column;
  no extractor fix needed.
- **Script gap** — the column is documented but the extractor missed it; needs
  a fix to ``extract_column_meta.py``.

Usage::

    uv run src/municipal_finances/fir_instructions/validate_column_coverage.py

    # or via the fir-instructions CLI:
    uv run src/municipal_finances/app.py validate-column-coverage
"""

from __future__ import annotations

import csv
from pathlib import Path

import typer
from sqlalchemy import text
from sqlmodel import Session

from municipal_finances.database import get_engine
from municipal_finances.fir_instructions.extract_column_meta import _DEFAULT_EXPORT_PATH

app = typer.Typer()

_DEFAULT_YEAR = 2025


@app.command()
def validate_column_coverage(
    csv_path: Path = typer.Option(
        _DEFAULT_EXPORT_PATH,
        help="Path to the baseline column metadata CSV",
    ),
    year: int = typer.Option(
        _DEFAULT_YEAR,
        help="FIR year to check against (marsyear in firrecord)",
    ),
) -> None:
    """Report (schedule, column_id) pairs in firrecord that have no column metadata entry.

    Reads the baseline CSV produced by ``extract-baseline-column-meta``, then
    queries the database for all distinct (schedule, column_id) combinations
    present in the given year's firrecord data.  Prints a grouped report of
    any gaps so they can be triaged as genuinely undocumented vs. extractor
    bugs.
    """
    # Load metadata keys from CSV.
    meta_keys: set[tuple[str, str]] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            meta_keys.add((row["schedule"], row["column_id"]))

    typer.echo(f"Loaded {len(meta_keys)} (schedule, column_id) pairs from {csv_path}.")

    # Query DB for distinct (schedule, column_id) in year's firrecord data.
    # The slc field has format: slc.<schedule>.L<line>.C<column_id>.<sub>
    # Use a regex split in SQL to avoid pulling all slc strings into Python.
    engine = get_engine()
    with Session(engine) as session:
        result = session.execute(
            text("""
                SELECT
                    split_part(slc, '.', 2)  AS schedule,
                    split_part(slc, '.C', 2) AS col_raw,
                    COUNT(*)                  AS record_count
                FROM firrecord
                WHERE marsyear = :year
                  AND slc IS NOT NULL
                GROUP BY schedule, col_raw
                ORDER BY schedule, col_raw
            """),
            {"year": year},
        ).fetchall()

    # col_raw has the form "<column_id>.<sub>" — take only the first two chars.
    db_pairs: dict[tuple[str, str], int] = {}
    for schedule, col_raw, count in result:
        column_id = col_raw[:2]
        key = (schedule, column_id)
        db_pairs[key] = db_pairs.get(key, 0) + count

    typer.echo(
        f"Found {len(db_pairs)} distinct (schedule, column_id) pairs in "
        f"{year} firrecord data."
    )

    # Find gaps.
    gaps: dict[str, list[tuple[str, int]]] = {}
    for (schedule, column_id), count in sorted(db_pairs.items()):
        if (schedule, column_id) not in meta_keys:
            gaps.setdefault(schedule, []).append((column_id, count))

    if not gaps:
        typer.echo("\nNo gaps found — all (schedule, column_id) pairs have metadata.")
        return

    total_gaps = sum(len(v) for v in gaps.values())
    typer.echo(
        f"\n{total_gaps} gap(s) found across {len(gaps)} schedule(s).\n"
        "For each gap, mark as:\n"
        "  [U] Genuinely undocumented — FIR instructions don't describe this column\n"
        "  [S] Script gap — extractor missed a documented column\n"
    )

    for schedule in sorted(gaps, key=lambda s: (len(s), s)):
        cols = gaps[schedule]
        typer.echo(f"Schedule {schedule}  ({len(cols)} gap(s)):")
        for column_id, count in sorted(cols):
            typer.echo(f"  Column {column_id}  —  {count:,} records  [ ]")
        typer.echo("")
