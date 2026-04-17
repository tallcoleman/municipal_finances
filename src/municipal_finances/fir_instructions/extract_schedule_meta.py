"""Extract FIR2025 schedule-level metadata from the instructions markdown files.

This module reads the per-schedule ``.md`` files produced by ``convert-folder``
(one file per FIR schedule PDF) and extracts one metadata record per schedule code.
The 31 schedule codes include 7 sub-schedules (22A/B/C, 51A/B, 61A/B) whose
descriptions are found within their parent schedule's section.

Records are inserted into ``fir_schedule_meta`` and exported to a CSV file at
``fir_instructions/exports/baseline_schedule_meta.csv`` for human verification.

Usage::

    from municipal_finances.fir_instructions.extract_schedule_meta import (
        extract_all_schedule_meta,
        insert_schedule_meta,
        save_to_csv,
    )

    records = extract_all_schedule_meta(
        "fir_instructions/source_files/2025/markdown",
    )
    insert_schedule_meta(engine, records)
    save_to_csv(records, Path("fir_instructions/exports/baseline_schedule_meta.csv"))
"""

# postpone evaluation of typing annotations
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import typer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from municipal_finances.database import get_engine
from municipal_finances.models import FIRScheduleMeta

app = typer.Typer()

# ---------------------------------------------------------------------------
# Schedule catalogue
# ---------------------------------------------------------------------------

SCHEDULE_CATEGORIES: dict[str, str] = {
    "10": "Revenue",
    "12": "Revenue",
    "20": "Taxation",
    "22": "Taxation",
    "22A": "Taxation",
    "22B": "Taxation",
    "22C": "Taxation",
    "24": "Taxation",
    "26": "Taxation",
    "28": "Taxation",
    "72": "Taxation",
    "40": "Expense",
    "42": "Expense",
    "51A": "Tangible Capital Assets",
    "51B": "Tangible Capital Assets",
    "53": "Net Financial Assets / Net Debt",
    "54": "Cash Flow",
    "60": "Reserves & Reserve Funds",
    "61A": "Reserves & Reserve Funds",
    "61B": "Reserves & Reserve Funds",
    "62": "Reserves & Reserve Funds",
    "70": "Financial Position",
    "71": "Remeasurement Gains & Losses",
    "74": "Long Term Liabilities",
    "74E": "Long Term Liabilities",
    "76": "Other Information",
    "77": "Other Information",
    "80": "Other Information",
    "80D": "Other Information",
    "81": "Other Information",
    "83": "Other Information",
}

# Maps schedule codes to the parent code used to construct the markdown filename.
# Codes in this map do not have their own ``FIR2025 S{code}.md`` file; their
# content is embedded within the parent schedule's file.
_MD_PARENT_FILE: dict[str, str] = {
    "22A": "22",
    "22B": "22",
    "22C": "22",
    "51A": "51",
    "51B": "51",
    "61A": "61",
    "61B": "61",
    "74E": "74",
}

# Public alias used by callers that check sub-schedule parentage (excludes 74E,
# which behaves differently from the 22/51/61 sub-schedules).
SUB_SCHEDULE_PARENTS: dict[str, str] = {
    k: v for k, v in _MD_PARENT_FILE.items() if k != "74E"
}

# Heading text prefixes used to locate each sub-schedule's section within its
# parent file.  Matched case-insensitively using startswith.
_SUB_SCHEDULE_HEADING_PREFIXES: dict[str, str] = {
    "22A": "General Purpose Levy Information (22A)",
    "22B": "Lower-Tier / Single-Tier Special Area Levy Information (22B)",
    "22C": "Upper-Tier Special Area Levy Information (22C)",
    "51A": "Schedule 51A:",
    "51B": "Schedule 51B:",
    "61A": "Schedule 61A:",
    "61B": "Schedule 61B:",
}

# CSV field order for the baseline export
_CSV_FIELDS = [
    "schedule",
    "schedule_name",
    "category",
    "description",
    "valid_from_year",
    "valid_to_year",
    "change_notes",
]

_DEFAULT_MARKDOWN_DIR = Path("fir_instructions/source_files/2025/markdown")
_DEFAULT_EXPORT_PATH = Path("fir_instructions/exports/baseline_schedule_meta.csv")


# ---------------------------------------------------------------------------
# Markdown parsing helpers
# ---------------------------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _strip_bold(text: str) -> str:
    """Remove ``**`` markdown bold markers from a string.

    Args:
        text: Raw text that may contain ``**`` markers.

    Returns:
        Text with all ``**`` sequences removed and surrounding whitespace stripped.
    """
    return re.sub(r"\*\*", "", text).strip()


def _parse_md_sections(md_path: Path) -> list[tuple[str, list[str]]]:
    """Parse a markdown file into (heading_text, content_lines) sections.

    Splits on any heading line (``#`` through ``######``).  The heading text
    has ``#`` markers and ``**`` bold markers stripped.  Content lines are the
    raw lines (without the trailing newline) between consecutive headings.

    A tuple with an empty heading string represents content that appears before
    the first heading in the file.  Returns an empty list if the file does not
    exist.

    Args:
        md_path: Path to the markdown file.

    Returns:
        List of ``(heading_text, content_lines)`` tuples in document order.
    """
    if not md_path.exists():
        return []

    with open(md_path, encoding="utf-8") as f:
        lines = f.readlines()

    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_content: list[str] = []

    for line in lines:
        stripped = line.rstrip("\n")
        m = _MD_HEADING_RE.match(stripped)
        if m:
            sections.append((current_heading, current_content))
            current_heading = _strip_bold(m.group(2))
            current_content = []
        else:
            current_content.append(stripped)

    sections.append((current_heading, current_content))
    return sections


def _clean_md_content(lines: list[str]) -> str:
    """Normalise markdown content lines into a description string.

    Strips trailing whitespace from each line and collapses runs of three or
    more consecutive blank lines to two.  Inline markdown formatting (e.g.
    ``**bold**``) is preserved so callers receive valid markdown.

    Args:
        lines: Raw content lines from a markdown section (no trailing newlines).

    Returns:
        Markdown string suitable for storage as ``description``.
    """
    cleaned = [line.rstrip() for line in lines]
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_section(
    sections: list[tuple[str, list[str]]],
    prefix: str,
    exact: bool = False,
    start: int = 0,
) -> int | None:
    """Return the index of the first matching section at or after *start*.

    Comparisons are case-insensitive.

    Args:
        sections: Parsed sections from :func:`_parse_md_sections`.
        prefix:   Heading text to match.
        exact:    If ``True``, require an exact heading match; otherwise use
                  ``startswith``.
        start:    Index to begin scanning from (default 0).

    Returns:
        Index of the matching section, or ``None`` if not found.
    """
    prefix_lower = prefix.lower()
    for i in range(start, len(sections)):
        h = sections[i][0].lower()
        if exact:
            if h == prefix_lower:
                return i
        else:
            if h.startswith(prefix_lower):
                return i
    return None


def _extract_sub_schedule_name(heading: str, code: str) -> str:
    """Derive a clean schedule_name from a sub-schedule section heading.

    Strips a leading ``"Schedule XX:"`` prefix or a trailing ``"(XX)"`` code
    suffix so the name is human-readable without the schedule code.

    Args:
        heading: The section heading text (``**`` already stripped).
        code:    The sub-schedule code (e.g. ``"22A"``).

    Returns:
        Clean schedule name string.
    """
    # Remove "Schedule XX: " prefix (e.g. "Schedule 51A: Tangible Capital Assets")
    m = re.match(r"^Schedule\s+\w+:\s*(.+)", heading, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Remove trailing "(XX)" code suffix (e.g. "General Purpose Levy Information (22A)")
    name = re.sub(
        r"\s*\(\s*" + re.escape(code) + r"\s*\)\s*$",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    return name.strip()


# ---------------------------------------------------------------------------
# Per-schedule extractors
# ---------------------------------------------------------------------------


def _extract_regular_schedule(markdown_dir: Path, code: str) -> dict[str, Any]:
    """Extract metadata for a schedule that has a General Information section.

    Reads ``FIR2025 S{code}.md`` from *markdown_dir*, finds the schedule name
    from the ``SCHEDULE {code}: Name`` body heading, and extracts the description
    from the ``General Information`` or ``General Instructions`` section.

    Args:
        markdown_dir: Directory containing the per-schedule markdown files.
        code:         Schedule code (e.g. ``"10"``).

    Returns:
        Dict with keys ``schedule``, ``schedule_name``, ``category``,
        ``description``, ``valid_from_year``, ``valid_to_year``, ``change_notes``.
    """
    md_path = markdown_dir / f"FIR2025 S{code}.md"
    sections = _parse_md_sections(md_path)

    # Schedule name: first heading matching "SCHEDULE {code}[...]: Name" or "SCHEDULE {code}[...] - Name"
    # The [^:-]* allows for variants like "SCHEDULE 62 and 62A: Name".
    schedule_name = ""
    name_re = re.compile(
        r"^(?:SCHEDULE|Schedule)\s+" + re.escape(code) + r"[^:\-]*[:\-]\s*(.*)",
        re.IGNORECASE,
    )
    for heading, _ in sections:
        m = name_re.match(heading)
        if m:
            schedule_name = m.group(1).strip()
            break

    # Description: content of the General Information / General Instructions section
    description = ""
    gi_headings = {"general information", "general instructions"}
    for heading, content in sections:
        if heading.lower().strip() in gi_headings:
            description = _clean_md_content(content)
            break

    return {
        "schedule": code,
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES.get(code, ""),
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_schedule_53(markdown_dir: Path) -> dict[str, Any]:
    """Extract metadata for Schedule 53 (no General Information heading).

    Schedule 53 has no ``General Information`` section; instead the first
    substantive content section immediately follows the ``SCHEDULE 53:`` body
    heading.  The description is the content of that first section.

    Args:
        markdown_dir: Directory containing the per-schedule markdown files.

    Returns:
        Metadata dict for Schedule 53.
    """
    md_path = markdown_dir / "FIR2025 S53.md"
    sections = _parse_md_sections(md_path)

    schedule_name = ""
    name_re = re.compile(r"^(?:SCHEDULE|Schedule)\s+53\s*[:\-]\s*(.*)", re.IGNORECASE)
    for heading, _ in sections:
        m = name_re.match(heading)
        if m:
            schedule_name = m.group(1).strip()
            break

    # Find the SCHEDULE 53 body heading, then use the next section's content
    body_idx = _find_section(sections, "SCHEDULE 53", exact=False)
    description = ""
    if body_idx is not None and body_idx + 1 < len(sections):
        _, content = sections[body_idx + 1]
        description = _clean_md_content(content)

    return {
        "schedule": "53",
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES["53"],
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_schedule_74e(markdown_dir: Path) -> dict[str, Any]:
    """Extract metadata for Schedule 74E from the S74 markdown file.

    ``FIR2025 S74.md`` contains two ``Schedule 74E`` headings: one in the
    general S74 overview (with the full subtitle) and one that marks the actual
    74E content section.  This function locates the shorter ``Schedule 74E``
    heading (exact match) and then extracts the ``Asset Retirement Obligation
    Liability`` sub-section that follows it.

    Args:
        markdown_dir: Directory containing the per-schedule markdown files.

    Returns:
        Metadata dict for Schedule 74E.
    """
    schedule_name = "Asset Retirement Obligation Liability"
    md_path = markdown_dir / "FIR2025 S74.md"
    sections = _parse_md_sections(md_path)

    # Find "Schedule 74E" (exact — not "Schedule 74E - Asset Retirement...")
    s74e_idx = _find_section(sections, "Schedule 74E", exact=True)
    description = ""
    if s74e_idx is not None:
        aro_idx = _find_section(
            sections,
            "Asset Retirement Obligation Liability",
            exact=True,
            start=s74e_idx + 1,
        )
        if aro_idx is not None:
            description = _clean_md_content(sections[aro_idx][1])

    return {
        "schedule": "74E",
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES["74E"],
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_sub_schedule(markdown_dir: Path, code: str) -> dict[str, Any]:
    """Extract metadata for a sub-schedule (22A/B/C, 51A/B, 61A/B).

    Sub-schedules are embedded within their parent schedule's markdown file.
    This function finds the section whose heading starts with the prefix
    defined in :data:`_SUB_SCHEDULE_HEADING_PREFIXES` and extracts its content
    as the description.

    Args:
        markdown_dir: Directory containing the per-schedule markdown files.
        code:         Sub-schedule code (must be a key in :data:`SUB_SCHEDULE_PARENTS`).

    Returns:
        Metadata dict for the sub-schedule.
    """
    parent = SUB_SCHEDULE_PARENTS[code]
    md_path = markdown_dir / f"FIR2025 S{parent}.md"
    sections = _parse_md_sections(md_path)

    heading_prefix = _SUB_SCHEDULE_HEADING_PREFIXES[code]
    idx = _find_section(sections, heading_prefix, exact=False)

    if idx is None:
        return {
            "schedule": code,
            "schedule_name": heading_prefix,
            "category": SCHEDULE_CATEGORIES.get(code, ""),
            "description": "",
            "valid_from_year": None,
            "valid_to_year": None,
            "change_notes": None,
        }

    heading, content = sections[idx]
    schedule_name = _extract_sub_schedule_name(heading, code)
    description = _clean_md_content(content)

    # If the sub-schedule heading has no body text, fall back to the parent
    # schedule's General Information section (e.g. S51A has no intro paragraph;
    # the parent S51 GI describes the whole 51 series).
    if not description:
        gi_headings = {"general information", "general instructions"}
        for h, c in sections:
            if h.lower().strip() in gi_headings:
                description = _clean_md_content(c)
                break

    return {
        "schedule": code,
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES.get(code, ""),
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------


def extract_schedule_record(markdown_dir: Path, code: str) -> dict[str, Any]:
    """Extract one metadata record for a given schedule code.

    Dispatches to the appropriate extractor based on the code:

    - Sub-schedules (22A/B/C, 51A/B, 61A/B): :func:`_extract_sub_schedule`
    - Schedule 53 (no GI heading): :func:`_extract_schedule_53`
    - Schedule 74E (embedded in S74): :func:`_extract_schedule_74e`
    - All others: :func:`_extract_regular_schedule`

    Args:
        markdown_dir: Directory containing the per-schedule markdown files.
        code:         Schedule code to extract.

    Returns:
        Dict with keys ``schedule``, ``schedule_name``, ``category``,
        ``description``, ``valid_from_year``, ``valid_to_year``,
        ``change_notes``.
    """
    if code in SUB_SCHEDULE_PARENTS:
        return _extract_sub_schedule(markdown_dir, code)
    if code == "53":
        return _extract_schedule_53(markdown_dir)
    if code == "74E":
        return _extract_schedule_74e(markdown_dir)
    return _extract_regular_schedule(markdown_dir, code)


def extract_all_schedule_meta(markdown_dir: str | Path) -> list[dict[str, Any]]:
    """Extract metadata records for all 31 schedule codes from FIR2025.

    Reads per-schedule markdown files from *markdown_dir* and extracts one
    record per schedule code in :data:`SCHEDULE_CATEGORIES`.

    Args:
        markdown_dir: Path to the folder containing ``FIR2025 S{code}.md`` files.

    Returns:
        List of 31 dicts, one per schedule code, ordered by the key set of
        :data:`SCHEDULE_CATEGORIES`.
    """
    markdown_dir = Path(markdown_dir)
    records: list[dict[str, Any]] = []
    for code in SCHEDULE_CATEGORIES:
        record = extract_schedule_record(markdown_dir, code)
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Database insertion
# ---------------------------------------------------------------------------


def insert_schedule_meta(engine: Any, records: list[dict[str, Any]]) -> int:
    """Insert schedule metadata records into ``fir_schedule_meta``.

    Uses application-layer deduplication before inserting because PostgreSQL's
    unique constraint on ``(schedule, valid_from_year, valid_to_year)`` does not
    treat ``NULL = NULL``, so ``ON CONFLICT DO NOTHING`` cannot deduplicate
    baseline rows where both year columns are NULL.

    Existing rows are fetched first; any incoming record whose
    ``(schedule, valid_from_year, valid_to_year)`` tuple already exists is
    excluded from the insert batch.

    Args:
        engine:  SQLAlchemy engine.
        records: List of metadata dicts from :func:`extract_all_schedule_meta`
                 or :func:`load_from_csv`.

    Returns:
        Number of rows actually inserted.
    """
    if not records:
        return 0

    with Session(engine) as session:
        existing = session.exec(
            select(
                FIRScheduleMeta.schedule,
                FIRScheduleMeta.valid_from_year,
                FIRScheduleMeta.valid_to_year,
            )
        ).all()
        existing_keys: set[tuple[str, int | None, int | None]] = {
            (row.schedule, row.valid_from_year, row.valid_to_year) for row in existing
        }

        new_records = [
            r
            for r in records
            if (r["schedule"], r.get("valid_from_year"), r.get("valid_to_year"))
            not in existing_keys
        ]

        if not new_records:
            return 0

        stmt = (
            pg_insert(FIRScheduleMeta)
            .values(new_records)
            .on_conflict_do_nothing()
            .returning(FIRScheduleMeta.id)
        )
        result = session.execute(stmt)
        inserted = len(result.fetchall())
        session.commit()

    return inserted


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------


def save_to_csv(records: list[dict[str, Any]], csv_path: Path) -> None:
    """Save schedule metadata records to a CSV file.

    Uses the column order defined by :data:`_CSV_FIELDS`.  Parent directories
    are created if needed.  Any existing file is overwritten.

    Args:
        records:  List of metadata dicts.
        csv_path: Destination path.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def load_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load schedule metadata records from a previously saved CSV.

    Empty strings in nullable fields (``valid_from_year``, ``valid_to_year``,
    ``change_notes``) are converted to ``None``.  Integer fields are cast
    from string.

    Args:
        csv_path: Path to a CSV file written by :func:`save_to_csv`.

    Returns:
        List of metadata dicts suitable for :func:`insert_schedule_meta`.
    """
    nullable_int_fields = {"valid_from_year", "valid_to_year"}
    nullable_str_fields = {"change_notes"}

    records: list[dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record: dict[str, Any] = dict(row)
            for field in nullable_int_fields:
                val = record.get(field)
                if val == "" or val is None:
                    record[field] = None
                else:
                    record[field] = int(val)
            for field in nullable_str_fields:
                if record.get(field) == "":
                    record[field] = None
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command()
def extract_baseline_schedule_meta(
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
    """Extract FIR2025 baseline schedule metadata and optionally load it into the DB.

    Reads per-schedule markdown files from the given directory, extracts one
    metadata record per schedule code, exports to CSV for verification, and
    optionally inserts into ``fir_schedule_meta``.
    """
    typer.echo(f"Extracting schedule metadata from {markdown_dir}...")
    records = extract_all_schedule_meta(markdown_dir)
    typer.echo(f"  {len(records)} records extracted.")

    save_to_csv(records, export_path)
    typer.echo(f"Exported to {export_path}.")

    if load_db:
        engine = get_engine()
        inserted = insert_schedule_meta(engine, records)
        typer.echo(f"Inserted {inserted} new rows into fir_schedule_meta.")


@app.command()
def load_baseline_schedule_meta(
    csv_path: Path = typer.Option(
        _DEFAULT_EXPORT_PATH,
        help="Path to the baseline CSV (default: fir_instructions/exports/baseline_schedule_meta.csv)",
    ),
) -> None:
    """Load schedule metadata from the baseline CSV into the database.

    Reads the CSV previously produced by ``extract-baseline-schedule-meta``
    (which may have been manually edited) and inserts records into
    ``fir_schedule_meta``, skipping any that already exist.
    """
    typer.echo(f"Loading schedule metadata from {csv_path}...")
    records = load_from_csv(csv_path)
    typer.echo(f"  {len(records)} records loaded from CSV.")

    engine = get_engine()
    inserted = insert_schedule_meta(engine, records)
    typer.echo(f"Inserted {inserted} new rows into fir_schedule_meta.")
