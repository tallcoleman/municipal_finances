"""Load FIR instruction changelog entries from manually-extracted CSVs.

Source files are per-year CSVs in
``fir_instructions/change_logs/semantic_extraction/``, one file per year
(e.g. ``FIR2025 Changes.csv``). Each CSV has columns:

- ``Schedule``        — schedule code (e.g. ``10``, ``22A``)
- ``SLC``             — SLC in PDF format (e.g. ``10 6021 01``), or ``New **``
                        / ``Deleted`` for schedule-level changes
- ``Heading``         — line or column heading
- ``Description``     — what changed
- ``Section Description`` — section header from the PDF (used for severity)

This module:

- Expands multi-schedule entries (e.g. ``"77A, B, C & D"``) into one record
  per schedule.
- Parses the SLC field, handling wildcards (``xxxx``, ``xx``), schedule-level
  markers (``"New **"``, ``"Deleted"``), and malformed values.
- Infers ``change_type`` from SLC structure and description keywords.
- Infers ``severity`` using a multi-tier approach (explicit label → structural
  scope → keyword signals → default minor).
- Inserts records into ``fir_instruction_changelog`` with duplicate-safe logic.
- Exports a combined CSV for human verification.
"""

# postpone evaluation of typing annotations
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import pandas as pd
import typer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from municipal_finances.database import get_engine
from municipal_finances.models import FIRInstructionChangelog
from municipal_finances.slc import pdf_slc_to_components

app = typer.Typer()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CHANGE_TYPES = frozenset(
    {
        "new_schedule",
        "deleted_schedule",
        "new_line",
        "deleted_line",
        "updated_line",
        "new_column",
        "deleted_column",
        "updated_column",
    }
)

_SOURCE_TAG = "pdf_changelog"

# Default paths (relative to the project working directory)
_DEFAULT_CSV_DIR = Path("fir_instructions/change_logs/semantic_extraction")
_DEFAULT_EXPORT_DIR = Path("fir_instructions/exports")
_EXPORT_FILENAME = "fir_instruction_changelog.csv"

# Year extraction from filename like "FIR2025 Changes.csv"
_YEAR_FROM_FILENAME_RE = re.compile(r"FIR(\d{4})\s+Changes\.csv$")

# Keywords for change action classification (checked in description + heading +
# section_desc, case-insensitive)
_DELETE_KEYWORDS = [
    "removed line",
    "deleted",
    "eliminated",
    "no longer",
    "has been eliminated",
]
_NEW_KEYWORDS = [
    "new line",
    "line added",
    "new lines added",
    "new column",
    "column added",
    "new columns added",
    "added as per",
    "new subtotal",
    "new section",
    " added.",
    "added to capture",
]

# Tier-3 severity signal keywords
_MAJOR_DESC_KEYWORDS = [
    "eliminated",
    "new schedule",
    "replaced with",
    "adoption of new accounting standard",
    "new section",
]
_MINOR_DESC_KEYWORDS = [
    "updated language",
    "referenced to",
    "linked from",
    "pre-populated",
    "calculated as",
    "restated as",
    "report the amount for",
    "is reported on",
]

# CSV field order for export files
_CSV_FIELDS = [
    "year",
    "schedule",
    "slc_pattern",
    "line_id",
    "column_id",
    "heading",
    "change_type",
    "severity",
    "description",
    "source",
]


# ---------------------------------------------------------------------------
# Schedule expansion
# ---------------------------------------------------------------------------


def _expand_schedules(schedule_str: str) -> list[str]:
    """Expand a multi-schedule string into individual schedule codes.

    Handles patterns such as:

    - ``"77A, B, C & D"`` → ``["77A", "77B", "77C", "77D"]``
    - ``"61A & 61B"``      → ``["61A", "61B"]``
    - ``"62 & 62A"``       → ``["62", "62A"]``
    - ``"10"``             → ``["10"]``

    For multi-part strings where later parts consist only of letters (no
    leading digits), the numeric prefix from the first part is prepended.

    Args:
        schedule_str: Raw value from the ``Schedule`` column.

    Returns:
        List of individual schedule code strings (one or more).
    """
    parts = [p.strip() for p in re.split(r"[,&]", schedule_str) if p.strip()]
    if len(parts) <= 1:
        return parts

    # Extract numeric prefix from the first part (e.g. "77" from "77A")
    prefix_match = re.match(r"^(\d+)", parts[0])
    prefix = prefix_match.group(1) if prefix_match else ""

    expanded: list[str] = []
    for part in parts:
        # Pure-letter parts (e.g. "B", "C") take the numeric prefix
        if re.match(r"^[A-Za-z]+$", part) and prefix:
            expanded.append(prefix + part)
        else:
            expanded.append(part)

    return expanded


# ---------------------------------------------------------------------------
# SLC parsing
# ---------------------------------------------------------------------------


def _parse_slc_field(
    slc_str: str,
    schedule: str,
) -> tuple[str | None, str | None, str | None]:
    """Parse the SLC field from a CSV row into (slc_pattern, line_id, column_id).

    Handles:

    - Normal PDF SLC format: ``"10 6021 01"`` → ``("10 6021 01", "6021", "01")``
    - Line wildcard: ``"40 xxxx 05"``        → ``("40 xxxx 05", None, "05")``
    - Column wildcard: ``"61 0206 xx"``      → ``("61 0206 xx", "0206", None)``
    - New-schedule marker: ``"New **"``       → ``(None, None, None)``
    - Deleted-schedule marker: ``"Deleted"`` → ``(None, None, None)``
    - Empty / missing SLC                    → ``(None, None, None)``
    - Malformed SLC (parse failure)          → ``(raw_str, None, None)``

    A warning is printed for malformed SLC values that are not recognized
    schedule-level markers.

    Args:
        slc_str: Raw value from the ``SLC`` column.
        schedule: The schedule code from the same row (used only in warnings).

    Returns:
        ``(slc_pattern, line_id, column_id)`` where ``slc_pattern`` is the
        value stored in the DB and ``None`` is used for wildcards / missing.
    """
    if not slc_str or not slc_str.strip():
        return None, None, None

    stripped = slc_str.strip()
    stripped_lower = stripped.lower()

    # Schedule-level markers
    if "new" in stripped_lower and "**" in stripped:
        return None, None, None
    if stripped_lower == "deleted":
        return None, None, None

    try:
        components = pdf_slc_to_components(stripped)
        return stripped, components["line_id"], components["column_id"]
    except ValueError:
        typer.echo(
            f"  Warning: could not parse SLC {stripped!r} for schedule {schedule!r}",
            err=True,
        )
        return stripped, None, None


# ---------------------------------------------------------------------------
# change_type inference
# ---------------------------------------------------------------------------


def _classify_action(description: str, heading: str, section_desc: str) -> str:
    """Return ``'new'``, ``'deleted'``, or ``'updated'`` from keyword signals.

    Checks the combined text of *description*, *heading*, and *section_desc*
    (case-insensitive). Delete keywords are checked first; new keywords second.
    Falls back to ``'updated'`` if no clear signal is found.

    Args:
        description: Change description text.
        heading:     Line or column heading.
        section_desc: Section description text from the source CSV.

    Returns:
        One of ``'new'``, ``'deleted'``, or ``'updated'``.
    """
    all_text = f"{description} {heading} {section_desc}".lower()

    for kw in _DELETE_KEYWORDS:
        if kw in all_text:
            return "deleted"

    for kw in _NEW_KEYWORDS:
        if kw in all_text:
            return "new"

    return "updated"


def _infer_change_type(
    slc_str: str | None,
    line_id: str | None,
    column_id: str | None,
    description: str,
    heading: str,
    section_desc: str,
) -> str:
    """Infer the ``change_type`` value for a changelog entry.

    Schedule-level special values in ``slc_str`` (``"New **"``, ``"Deleted"``,
    or empty/``None``) map directly to ``new_schedule``, ``deleted_schedule``,
    or ``updated_line``. For regular SLC entries the entity type (line vs
    column) is determined by which SLC position is wildcarded:

    - Line wildcard (``xxxx``, i.e. ``line_id is None``) → column-level change.
    - Column wildcard (``xx``, i.e. ``column_id is None``) or fully specified
      SLC → line-level change.

    The action (new / deleted / updated) is inferred from description keywords
    via :func:`_classify_action`.

    Args:
        slc_str:     Raw SLC field value (may be ``None`` or a special marker).
        line_id:     Parsed line ID (``None`` for wildcards).
        column_id:   Parsed column ID (``None`` for wildcards).
        description: Change description.
        heading:     Line or column heading.
        section_desc: Section description from the source CSV.

    Returns:
        A valid ``change_type`` string.
    """
    if not slc_str:
        return "updated_line"

    slc_lower = slc_str.lower().strip()

    if "new" in slc_lower and "**" in slc_str:
        return "new_schedule"
    if slc_lower == "deleted":
        return "deleted_schedule"

    action = _classify_action(description, heading, section_desc)

    # Line wildcard (xxxx) → column-level change
    if line_id is None:
        entity = "column"
    else:
        entity = "line"

    return f"{action}_{entity}"


# ---------------------------------------------------------------------------
# Severity inference
# ---------------------------------------------------------------------------


def _infer_severity(
    section_desc: str,
    change_type: str,
    slc_pattern: str | None,
    description: str,
) -> str:
    """Infer severity using a multi-tier approach.

    **Tier 1** — explicit label in ``section_desc``:
        If the text (case-insensitive) contains ``"major"`` → ``"major"``;
        ``"minor"`` → ``"minor"``.

    **Tier 2** — structural scope of ``change_type``:
        - ``new_schedule`` or ``deleted_schedule`` → ``"major"``.
        - ``new_line`` or ``deleted_line`` with ``xxxx`` in ``slc_pattern``
          (affects all lines on a schedule) → ``"major"``.
        - ``new_column`` or ``deleted_column`` with ``xx`` in ``slc_pattern``
          (affects all columns on a line) → ``"major"``.

    **Tier 3** — description keyword signals:
        Counts major and minor keyword matches in ``description`` +
        ``section_desc``; uses the stronger signal.

    **Tier 5** — default: ``"minor"``.

    Args:
        section_desc: Section description from the source CSV.
        change_type:  Inferred change type string.
        slc_pattern:  Raw SLC pattern (may contain wildcards).
        description:  Change description text.

    Returns:
        ``"major"`` or ``"minor"``.
    """
    # Tier 1: explicit label
    section_lower = (section_desc or "").lower()
    if "major" in section_lower:
        return "major"
    if "minor" in section_lower:
        return "minor"

    # Tier 2: structural scope
    if change_type in ("new_schedule", "deleted_schedule"):
        return "major"

    if slc_pattern:
        slc_lower = slc_pattern.lower()
        if change_type in ("new_line", "deleted_line") and "xxxx" in slc_lower:
            return "major"
        if change_type in ("new_column", "deleted_column") and re.search(
            r"\bxx\b", slc_lower
        ):
            return "major"

    # Tier 3: keyword signals
    combined = (description + " " + (section_desc or "")).lower()
    major_score = sum(1 for kw in _MAJOR_DESC_KEYWORDS if kw in combined)
    minor_score = sum(1 for kw in _MINOR_DESC_KEYWORDS if kw in combined)

    if major_score > minor_score:
        return "major"
    if minor_score > major_score:
        return "minor"

    # Tier 5: default
    return "minor"


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------


def parse_changelog_row(row: dict[str, Any], year: int) -> list[dict[str, Any]]:
    """Parse a CSV row dict into one or more changelog entry dicts.

    Multi-schedule entries (e.g. ``Schedule = "77A, B, C & D"``) are expanded
    into one entry per schedule; all other fields are identical across the
    expanded entries.

    Args:
        row:  Dict of column names to values (from ``pandas.DataFrame.iterrows``
              or a ``csv.DictReader``).
        year: FIR reporting year (e.g. 2025).

    Returns:
        A list of one or more entry dicts suitable for
        :func:`insert_changelog_entries`.
    """
    schedule_raw = str(row.get("Schedule", "") or "").strip()
    slc_raw = str(row.get("SLC", "") or "").strip()
    heading = str(row.get("Heading", "") or "").strip()
    description = str(row.get("Description", "") or "").strip()
    section_desc = str(row.get("Section Description", "") or "").strip()

    schedules = _expand_schedules(schedule_raw) if schedule_raw else [schedule_raw]

    slc_pattern, line_id, column_id = _parse_slc_field(slc_raw, schedule_raw)

    change_type = _infer_change_type(
        slc_raw if slc_raw else None,
        line_id,
        column_id,
        description,
        heading,
        section_desc,
    )
    severity = _infer_severity(section_desc, change_type, slc_pattern, description)

    entries: list[dict[str, Any]] = []
    for schedule in schedules:
        entries.append(
            {
                "year": year,
                "schedule": schedule,
                "slc_pattern": slc_pattern,
                "line_id": line_id,
                "column_id": column_id,
                "heading": heading or None,
                "change_type": change_type,
                "severity": severity,
                "description": description or None,
                "source": _SOURCE_TAG,
            }
        )

    return entries


def load_changelog_csv(csv_path: Path, year: int) -> list[dict[str, Any]]:
    """Load a single per-year changelog CSV and return parsed entry dicts.

    Reads with UTF-8-sig encoding to strip any BOM characters that appear in
    some source files (e.g. FIR2023 Changes.csv).

    Args:
        csv_path: Path to a ``FIR{year} Changes.csv`` file.
        year:     FIR reporting year.

    Returns:
        List of entry dicts produced by :func:`parse_changelog_row`.
    """
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    entries: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        entries.extend(parse_changelog_row(row.to_dict(), year))
    return entries


# ---------------------------------------------------------------------------
# Database storage
# ---------------------------------------------------------------------------


def insert_changelog_entries(engine: Any, entries: list[dict[str, Any]]) -> int:
    """Insert changelog entries into ``fir_instruction_changelog``, skipping duplicates.

    Entries with a non-NULL ``slc_pattern`` use ``INSERT … ON CONFLICT DO
    NOTHING`` against the table's unique constraint on
    ``(year, schedule, slc_pattern, change_type, source)``.

    Entries with ``slc_pattern = NULL`` (schedule-level changes) are
    deduplicated at the application level, because PostgreSQL treats NULLs as
    distinct in unique constraints.

    Args:
        engine:  SQLAlchemy engine (from
                 :func:`~municipal_finances.database.get_engine`).
        entries: List of entry dicts produced by :func:`parse_changelog_row`
                 or :func:`load_from_csv`.

    Returns:
        Number of rows actually inserted (may be less than ``len(entries)``
        if some already exist).
    """
    if not entries:
        return 0

    non_null = [e for e in entries if e.get("slc_pattern") is not None]
    null_slc = [e for e in entries if e.get("slc_pattern") is None]

    inserted = 0

    with Session(engine) as session:
        # Non-null: bulk insert with ON CONFLICT DO NOTHING.
        # psycopg3 returns rowcount=-1 for this statement type, so use
        # RETURNING to count only the rows that were actually inserted.
        if non_null:
            stmt = (
                pg_insert(FIRInstructionChangelog)
                .values(non_null)
                .on_conflict_do_nothing()
                .returning(FIRInstructionChangelog.id)
            )
            result = session.execute(stmt)
            inserted += len(result.fetchall())

        # NULL slc_pattern: deduplicate in application layer
        for entry in null_slc:
            exists = session.exec(
                select(FIRInstructionChangelog).where(
                    FIRInstructionChangelog.year == entry["year"],
                    FIRInstructionChangelog.schedule == entry["schedule"],
                    FIRInstructionChangelog.slc_pattern.is_(None),  # type: ignore[union-attr]
                    FIRInstructionChangelog.change_type == entry["change_type"],
                    FIRInstructionChangelog.source == entry["source"],
                )
            ).first()
            if exists is None:
                session.add(FIRInstructionChangelog(**entry))
                inserted += 1

        session.commit()

    return inserted


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------


def save_to_csv(entries: list[dict[str, Any]], csv_path: Path) -> None:
    """Save changelog entries to a CSV file.

    The file uses the column order defined by ``_CSV_FIELDS``. Any existing
    content is overwritten. Parent directories are created if needed.

    Args:
        entries:  List of entry dicts.
        csv_path: Destination path.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)


def load_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load changelog entries from a previously saved export CSV.

    Empty strings are converted to ``None`` for nullable fields
    (``slc_pattern``, ``line_id``, ``column_id``, ``heading``,
    ``severity``, ``description``).

    Args:
        csv_path: Path to a CSV file written by :func:`save_to_csv`.

    Returns:
        List of entry dicts with an integer ``year`` field.
    """
    nullable = {
        "slc_pattern",
        "line_id",
        "column_id",
        "heading",
        "severity",
        "description",
    }
    entries: list[dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry: dict[str, Any] = dict(row)
            entry["year"] = int(entry["year"])
            for key in nullable:
                if entry.get(key) == "":
                    entry[key] = None
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command()
def load_changelogs(
    csv_dir: Path = typer.Option(
        _DEFAULT_CSV_DIR,
        help="Directory containing per-year 'FIR{year} Changes.csv' files",
    ),
    export_dir: Path = typer.Option(
        _DEFAULT_EXPORT_DIR,
        help="Directory for the combined export CSV",
    ),
) -> None:
    """Load FIR instruction changelog CSVs into the database.

    Reads all ``FIR{year} Changes.csv`` files from *csv_dir*, parses each row
    into a :class:`~municipal_finances.models.FIRInstructionChangelog` record,
    inserts them into the database (skipping duplicates), and saves a combined
    export CSV to ``{export_dir}/fir_instruction_changelog.csv`` for human
    verification.
    """
    engine = get_engine()

    csv_files = sorted(csv_dir.glob("FIR* Changes.csv"))
    if not csv_files:
        typer.echo(f"No changelog CSVs found in {csv_dir}", err=True)
        raise typer.Exit(code=1)

    all_entries: list[dict[str, Any]] = []
    for csv_path in csv_files:
        match = _YEAR_FROM_FILENAME_RE.search(csv_path.name)
        if not match:
            typer.echo(f"Skipping {csv_path.name}: cannot extract year from filename.")
            continue
        year = int(match.group(1))
        typer.echo(f"Loading {csv_path.name}...")
        entries = load_changelog_csv(csv_path, year)
        typer.echo(f"  {len(entries)} entries parsed.")
        all_entries.extend(entries)

    if not all_entries:
        typer.echo("No entries parsed from any CSV.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Inserting {len(all_entries)} entries into database...")
    inserted = insert_changelog_entries(engine, all_entries)
    typer.echo(f"  {inserted} new rows inserted.")

    export_path = export_dir / _EXPORT_FILENAME
    export_dir.mkdir(parents=True, exist_ok=True)
    save_to_csv(all_entries, export_path)
    typer.echo(f"Exported {len(all_entries)} entries to {export_path}.")


@app.command()
def export_changelog(
    export_dir: Path = typer.Option(
        _DEFAULT_EXPORT_DIR,
        help="Directory for the export CSV",
    ),
) -> None:
    """Re-export the fir_instruction_changelog table to a CSV file.

    Queries all ``pdf_changelog`` entries from the database and writes them to
    ``{export_dir}/fir_instruction_changelog.csv``, ordered by year, schedule,
    and SLC pattern.
    """
    engine = get_engine()
    with Session(engine) as session:
        rows = session.exec(
            select(FIRInstructionChangelog)
            .where(FIRInstructionChangelog.source == _SOURCE_TAG)
            .order_by(
                FIRInstructionChangelog.year,
                FIRInstructionChangelog.schedule,
                FIRInstructionChangelog.slc_pattern,
            )
        ).all()

    records = [
        {
            "year": r.year,
            "schedule": r.schedule,
            "slc_pattern": r.slc_pattern,
            "line_id": r.line_id,
            "column_id": r.column_id,
            "heading": r.heading,
            "change_type": r.change_type,
            "severity": r.severity,
            "description": r.description,
            "source": r.source,
        }
        for r in rows
    ]

    export_path = export_dir / _EXPORT_FILENAME
    save_to_csv(records, export_path)
    typer.echo(f"Exported {len(records)} rows to {export_path}.")
