"""Extract FIR2025 column-level metadata from the instructions markdown files.

This module reads the per-schedule ``.md`` files produced by ``convert-folder``
and extracts one metadata record per (schedule, column) combination.

Columns are identified by section headings matching ``Column N - Name`` or
``Column N: - Name`` (the S51A variant).  Schedules where no such headings
appear in the markdown are skipped — no records are produced for them.

Records are inserted into ``fir_column_meta`` and exported to a CSV file at
``fir_instructions/exports/baseline_column_meta.csv`` for human verification.

Usage::

    from municipal_finances.fir_instructions.extract_column_meta import (
        extract_all_column_meta,
        insert_column_meta,
        save_to_csv,
    )

    records = extract_all_column_meta(
        "fir_instructions/source_files/2025/markdown",
    )
    insert_column_meta(engine, records)
    save_to_csv(records, Path("fir_instructions/exports/baseline_column_meta.csv"))
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import typer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from municipal_finances.database import get_engine
from municipal_finances.fir_instructions.extract_line_meta import _get_schedule_sections
from municipal_finances.fir_instructions.extract_schedule_meta import (
    SCHEDULE_CATEGORIES,
    _clean_md_content,
)
from municipal_finances.models import FIRColumnMeta, FIRScheduleMeta

app = typer.Typer()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Matches "Column 1 - Name" (S12/S40 style) and "Column 1: - Name" (S51A style).
# The optional colon (:?) handles the S51A variant where a colon follows the number.
_COLUMN_HEADING_RE = re.compile(
    r"Column\s+(\d+):?\s*[-\u2013\u2014]\s*(.+)",
    re.IGNORECASE,
)

# Matches "Columns N & M: - GroupName" (S74D style) where two column numbers share
# a group description.  Both columns receive the group name as their column_name.
_PAIRED_COLUMN_HEADING_RE = re.compile(
    r"Columns\s+(\d+)\s*&\s*(\d+):?\s*[-\u2013\u2014]\s*(.+)",
    re.IGNORECASE,
)

# Headings that should NOT update current_section_name — boilerplate transitions
# that appear within a section rather than introducing a new one.  Without this
# skip-list, S26's repeated "Description of Columns" sub-heading would overwrite
# the major section name and cause column records from different sections to share
# the same section_name.
_NON_SECTION_RE = re.compile(
    r"^(Description of (Columns|Lines)|Descriptions of (Columns|Lines)|"
    r"This section will be automatically pre-populated|"
    r"Only .* municipalities should have values|"
    r"IMPORTANT:|Note:|Please note|Total is automatically|"
    r".*automatically calculated|.*should equal)",
    re.IGNORECASE,
)

_CSV_FIELDS = [
    "schedule",
    "column_id",
    "column_name",
    "section_name",
    "description",
    "valid_from_year",
    "valid_to_year",
    "change_notes",
]

_DEFAULT_MARKDOWN_DIR = Path("fir_instructions/source_files/2025/markdown")
_DEFAULT_EXPORT_PATH = Path("fir_instructions/exports/baseline_column_meta.csv")


# ---------------------------------------------------------------------------
# Heading parser
# ---------------------------------------------------------------------------


def _parse_paired_column_heading(heading: str) -> tuple[str, str, str] | None:
    """Parse a ``Columns N & M: - GroupName`` heading into ``(col_id_1, col_id_2, group_name)``.

    Handles the S74D variant where two column numbers share a group description.
    Both columns receive the group name as their ``column_name``.  Column IDs
    are zero-padded to two digits.

    Args:
        heading: Section heading text (bold markers already stripped).

    Returns:
        ``(col_id_1, col_id_2, group_name)`` tuple, or ``None`` if not a paired heading.
    """
    m = _PAIRED_COLUMN_HEADING_RE.match(heading.strip())
    if not m:
        return None
    col_id_1 = f"{int(m.group(1)):02d}"
    col_id_2 = f"{int(m.group(2)):02d}"
    name = m.group(3).strip().rstrip(":").strip()
    return (col_id_1, col_id_2, name)


def _parse_column_heading(heading: str) -> tuple[str, str] | None:
    """Parse a section heading into (column_id, column_name) if it is a column heading.

    Handles both ``Column 1 - Name`` (standard) and ``Column 1: - Name``
    (S51A variant where a colon follows the column number).  The ``column_id``
    is zero-padded to two digits (e.g. column 1 → ``"01"``, column 16 → ``"16"``).

    Args:
        heading: Section heading text (bold markers already stripped by
                 :func:`_parse_md_sections`).

    Returns:
        ``(column_id, column_name)`` tuple, or ``None`` if the heading is not
        a column heading.
    """
    m = _COLUMN_HEADING_RE.match(heading.strip())
    if not m:
        return None
    col_num = int(m.group(1))
    col_name = m.group(2).strip().rstrip(":").strip()
    return (f"{col_num:02d}", col_name)


# ---------------------------------------------------------------------------
# Per-schedule extraction
# ---------------------------------------------------------------------------


def _scan_body_for_columns(
    content: list[str],
    code: str,
    current_section_name: str | None,
    seen_keys: set[tuple[str, str | None]],
    records: list[dict[str, Any]],
) -> None:
    """Scan section body text for plain-text column definitions.

    Handles the rare case where a column definition appears as a plain line of
    body text rather than a ``##`` heading (the only known occurrence is S28
    Column 05, which is sandwiched between proper ``##`` headings but is itself
    plain text).  Grep across all 31 schedules confirms this pattern appears
    exactly once, so false-positive risk is negligible.

    Args:
        content:              Body lines of a section (list returned by
                              :func:`_get_schedule_sections`).
        code:                 Schedule code (used when appending a new record).
        current_section_name: Section context active at the time this body is
                              scanned.
        seen_keys:            Mutable dedup set shared with the caller.
        records:              Mutable result list shared with the caller.
    """
    lines = content
    for i, line in enumerate(lines):
        parsed = _parse_column_heading(line.strip())
        if parsed is None:
            continue
        column_id, column_name = parsed
        key = (column_id, current_section_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # Collect description lines until the next column definition or end.
        desc_lines: list[str] = []
        for j in range(i + 1, len(lines)):
            if _parse_column_heading(lines[j].strip()) is not None:
                break
            desc_lines.append(lines[j])
        text = _clean_md_content("\n".join(desc_lines))
        records.append(
            {
                "schedule": code,
                "column_id": column_id,
                "column_name": column_name,
                "section_name": current_section_name,
                "description": text or "No description provided.",
                "valid_from_year": None,
                "valid_to_year": None,
                "change_notes": None,
            }
        )


def _extract_per_schedule_columns(
    markdown_dir: Path, code: str
) -> list[dict[str, Any]]:
    """Extract column metadata records from a schedule's instruction markdown.

    Scans all section headings for ``Column N - Name`` patterns and tracks the
    last major (non-boilerplate) heading as ``section_name`` so that the same
    column ID can appear in multiple sections with distinct meanings (e.g. S20,
    S26, S80, S80D).  A ``(column_id, section_name)`` pair is only emitted once.

    Body text is also scanned for plain-text column definitions to catch S28's
    Column 05, which lacks a ``##`` heading.

    Schedules with no column headings produce an empty list.

    Args:
        markdown_dir: Directory containing per-schedule markdown files.
        code:         Schedule code.

    Returns:
        List of column metadata dicts, one per unique ``(column_id, section_name)``.
    """
    sections = _get_schedule_sections(markdown_dir, code)
    if not sections:
        return []

    records: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str | None]] = set()  # (column_id, section_name)
    current_section_name: str | None = None

    for heading, content in sections:
        # Check for paired heading first (S74D: "Columns N & M: - GroupName").
        paired = _parse_paired_column_heading(heading)
        if paired is not None:
            col_id_1, col_id_2, group_name = paired
            text = _clean_md_content(content)
            for col_id in (col_id_1, col_id_2):
                key = (col_id, current_section_name)
                if key not in seen_keys:
                    seen_keys.add(key)
                    records.append(
                        {
                            "schedule": code,
                            "column_id": col_id,
                            "column_name": group_name,
                            "section_name": current_section_name,
                            "description": text or "No description provided.",
                            "valid_from_year": None,
                            "valid_to_year": None,
                            "change_notes": None,
                        }
                    )
            _scan_body_for_columns(content, code, current_section_name, seen_keys, records)
            continue

        parsed = _parse_column_heading(heading)

        if parsed is None:
            # Non-column heading: update section context unless it is boilerplate
            # (e.g. "Description of Columns" appears in multiple S26 sections and
            # must not overwrite the meaningful parent heading).
            if not _NON_SECTION_RE.match(heading.strip()):
                current_section_name = heading.strip()
            # Also scan body text for plain-text column definitions (S28 col 05).
            _scan_body_for_columns(
                content, code, current_section_name, seen_keys, records
            )
            continue

        column_id, column_name = parsed
        key = (column_id, current_section_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        text = _clean_md_content(content)
        records.append(
            {
                "schedule": code,
                "column_id": column_id,
                "column_name": column_name,
                "section_name": current_section_name,
                "description": text or "No description provided.",
                "valid_from_year": None,
                "valid_to_year": None,
                "change_notes": None,
            }
        )
        # Also scan this section's body for plain-text column definitions.
        # This handles S28 Column 05, which appears as plain text inside
        # Column 04's body rather than as its own ## heading.
        _scan_body_for_columns(content, code, current_section_name, seen_keys, records)

    return records


# ---------------------------------------------------------------------------
# S51B inherited column synthesis
# ---------------------------------------------------------------------------


def _synthesize_s51b_inherited_columns(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Synthesize S51B column records inherited from S51A.

    S51B (Segmented by Asset Class) uses the same column structure as S51A for
    its General Capital Assets and Infrastructure Assets sections but does not
    redefine those columns in its own markdown.  This copies all S51A column
    records to S51B with ``section_name=None`` (applicable across all non-CIP
    asset sections).

    CIP-specific columns (01–04 under
    ``section_name='Line 2405 - Construction-In-Progress'``) are already
    extracted from S51B's markdown; those have a non-``None`` ``section_name``
    and will not conflict with the inherited records (dedup key is
    ``(column_id, section_name)``).

    Args:
        records: Full list of extracted records from all schedules.

    Returns:
        New records to append for S51B inherited columns.
    """
    s51a_cols = [r for r in records if r["schedule"] == "51A"]
    s51b_existing_keys: set[tuple[str, str | None]] = {
        (r["column_id"], r.get("section_name"))
        for r in records
        if r["schedule"] == "51B"
    }
    new_records: list[dict[str, Any]] = []
    for col in s51a_cols:
        key = (col["column_id"], None)
        if key in s51b_existing_keys:
            continue
        new_records.append({**col, "schedule": "51B", "section_name": None})
    return new_records


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------


def extract_all_column_meta(markdown_dir: str | Path) -> list[dict[str, Any]]:
    """Extract column metadata records for all 31 FIR2025 schedule codes.

    Schedules whose markdown files contain no ``Column N - Name`` headings
    produce no records and are silently skipped.

    Args:
        markdown_dir: Path to the folder containing ``FIR2025 S{code}.md`` files.

    Returns:
        Flat list of column metadata dicts, one per (schedule, column) combination.
    """
    markdown_dir = Path(markdown_dir)
    records: list[dict[str, Any]] = []
    for code in SCHEDULE_CATEGORIES:
        records.extend(_extract_per_schedule_columns(markdown_dir, code))
    records.extend(_synthesize_s51b_inherited_columns(records))
    return records


# ---------------------------------------------------------------------------
# Database insertion
# ---------------------------------------------------------------------------


def insert_column_meta(engine: Any, records: list[dict[str, Any]]) -> int:
    """Insert column metadata records into ``fir_column_meta``.

    Uses application-layer deduplication because PostgreSQL's unique constraint
    on ``(schedule, column_id, valid_from_year, valid_to_year)`` does not treat
    ``NULL = NULL``, so ``ON CONFLICT DO NOTHING`` cannot deduplicate baseline
    rows where both year columns are NULL.

    The ``schedule_id`` FK is resolved at insert time by querying
    ``fir_schedule_meta``.

    Args:
        engine:  SQLAlchemy engine.
        records: List of metadata dicts from :func:`extract_all_column_meta` or
                 :func:`load_from_csv`.

    Returns:
        Number of rows actually inserted.
    """
    if not records:
        return 0

    with Session(engine) as session:
        # Fetch existing keys for deduplication.  section_name is included because
        # the same column_id can legitimately appear in multiple named sections.
        existing = session.exec(
            select(
                FIRColumnMeta.schedule,
                FIRColumnMeta.column_id,
                FIRColumnMeta.section_name,
                FIRColumnMeta.valid_from_year,
                FIRColumnMeta.valid_to_year,
            )
        ).all()
        existing_keys: set[tuple[str, str, str | None, int | None, int | None]] = {
            (row.schedule, row.column_id, row.section_name, row.valid_from_year, row.valid_to_year)
            for row in existing
        }

        new_records = [
            r
            for r in records
            if (
                r["schedule"],
                r["column_id"],
                r.get("section_name"),
                r.get("valid_from_year"),
                r.get("valid_to_year"),
            )
            not in existing_keys
        ]

        if not new_records:
            return 0

        # Resolve schedule_id FK from fir_schedule_meta.
        schedule_meta_rows = session.exec(
            select(FIRScheduleMeta.schedule, FIRScheduleMeta.id)
        ).all()
        schedule_id_map: dict[str, int] = {
            row.schedule: row.id for row in schedule_meta_rows
        }

        insert_dicts: list[dict[str, Any]] = []
        for r in new_records:
            d = dict(r)
            d["schedule_id"] = schedule_id_map.get(r["schedule"])
            insert_dicts.append(d)

        stmt = (
            pg_insert(FIRColumnMeta)
            .values(insert_dicts)
            .on_conflict_do_nothing()
            .returning(FIRColumnMeta.id)
        )
        result = session.execute(stmt)
        inserted = len(result.fetchall())
        session.commit()

    return inserted


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------


def save_to_csv(records: list[dict[str, Any]], csv_path: Path) -> None:
    """Save column metadata records to a CSV file.

    Uses the column order defined by :data:`_CSV_FIELDS`.  Parent directories
    are created if needed.  Any existing file is overwritten.

    Args:
        records:  List of column metadata dicts.
        csv_path: Destination path.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def load_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load column metadata records from a previously saved CSV.

    Handles type conversion for nullable string and integer fields.

    Args:
        csv_path: Path to a CSV file written by :func:`save_to_csv`.

    Returns:
        List of metadata dicts suitable for :func:`insert_column_meta`.
    """
    nullable_str_fields = {"description", "change_notes", "section_name"}
    nullable_int_fields = {"valid_from_year", "valid_to_year"}

    records: list[dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record: dict[str, Any] = dict(row)
            for field in nullable_str_fields:
                if record.get(field) == "":
                    record[field] = None
            for field in nullable_int_fields:
                val = record.get(field)
                if val == "" or val is None:
                    record[field] = None
                else:
                    record[field] = int(val)
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command()
def extract_baseline_column_meta(
    markdown_dir: Path = typer.Option(
        _DEFAULT_MARKDOWN_DIR,
        help="Directory containing FIR2025 S{code}.md files",
    ),
    export_path: Path = typer.Option(
        _DEFAULT_EXPORT_PATH,
        help="CSV export path for human verification",
    ),
    load_db: bool = typer.Option(
        True,
        help="Insert records into the database after extraction",
    ),
) -> None:
    """Extract FIR2025 baseline column metadata and optionally load it into the DB.

    Reads per-schedule markdown files, extracts one metadata record per
    (schedule, column) combination, exports to CSV for verification, and
    optionally inserts into ``fir_column_meta``.
    """
    typer.echo(f"Extracting column metadata from {markdown_dir}...")
    records = extract_all_column_meta(markdown_dir)
    typer.echo(f"  {len(records)} records extracted.")

    save_to_csv(records, export_path)
    typer.echo(f"Exported to {export_path}.")

    if load_db:
        engine = get_engine()
        inserted = insert_column_meta(engine, records)
        typer.echo(f"Inserted {inserted} new rows into fir_column_meta.")


@app.command()
def load_baseline_column_meta(
    csv_path: Path = typer.Option(
        _DEFAULT_EXPORT_PATH,
        help="Path to the baseline CSV (default: fir_instructions/exports/baseline_column_meta.csv)",
    ),
) -> None:
    """Load column metadata from the baseline CSV into the database.

    Reads the CSV previously produced by ``extract-baseline-column-meta``
    (which may have been manually edited) and inserts records into
    ``fir_column_meta``, skipping any that already exist.
    """
    typer.echo(f"Loading column metadata from {csv_path}...")
    records = load_from_csv(csv_path)
    typer.echo(f"  {len(records)} records loaded from CSV.")

    engine = get_engine()
    inserted = insert_column_meta(engine, records)
    typer.echo(f"Inserted {inserted} new rows into fir_column_meta.")
