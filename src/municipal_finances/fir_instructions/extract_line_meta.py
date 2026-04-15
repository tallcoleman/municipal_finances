"""Extract FIR2025 line-level metadata from the instructions markdown files.

This module reads the per-schedule ``.md`` files and the shared
``FIR2025 - Functional Categories.md`` file produced by ``convert-folder``
and extracts one metadata record per (schedule, line) combination.

For Schedules 12, 40, and 51A, two data sources are merged into a single
``description`` field:

1. ``FIR2025 - Functional Categories.md`` provides the functional content
   (what belongs under each line, including any exclusion language).
2. Per-schedule ``FIR2025 S{code}.md`` files provide additional reporting
   instructions, ``carry_forward_from``, ``applicability``, ``is_subtotal``,
   and ``is_auto_calculated``.

Records are inserted into ``fir_line_meta`` and exported to a CSV file at
``fir_instructions/exports/baseline_line_meta.csv`` for human verification.

Usage::

    from municipal_finances.fir_instructions.extract_line_meta import (
        extract_all_line_meta,
        insert_line_meta,
        save_to_csv,
    )

    records = extract_all_line_meta(
        "fir_instructions/source_files/2025/markdown",
    )
    insert_line_meta(engine, records)
    save_to_csv(records, Path("fir_instructions/exports/baseline_line_meta.csv"))
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
from municipal_finances.fir_instructions.extract_schedule_meta import (
    SCHEDULE_CATEGORIES,
    SUB_SCHEDULE_PARENTS,
    _MD_PARENT_FILE,
    _SUB_SCHEDULE_HEADING_PREFIXES,
    _clean_md_content,
    _find_section,
    _parse_md_sections,
)
from municipal_finances.models import FIRLineMeta, FIRScheduleMeta

app = typer.Typer()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Schedule codes that use the Functional Categories document for line definitions.
_SCHEDULES_WITH_FC_DATA: frozenset[str] = frozenset({"12", "40", "51A"})

_FC_FILENAME = "FIR2025 - Functional Categories.md"

_CSV_FIELDS = [
    "schedule",
    "line_id",
    "line_name",
    "section",
    "description",
    "is_subtotal",
    "is_auto_calculated",
    "carry_forward_from",
    "applicability",
    "valid_from_year",
    "valid_to_year",
    "change_notes",
]

_DEFAULT_MARKDOWN_DIR = Path("fir_instructions/source_files/2025/markdown")
_DEFAULT_EXPORT_PATH = Path("fir_instructions/exports/baseline_line_meta.csv")

# Matches "Line XXXX - Name", "Lines XXXX to YYYY - Name", or "Line XXXX Name"
# (some headings use a space instead of a dash as the separator).
_LINE_HEADING_RE = re.compile(
    r"Lines?\s+(\w{4})(?:\s+to\s+\w{4})?\s*(?:[-\u2013\u2014]\s*|\s+)(.+)",
    re.IGNORECASE,
)

# Matches all-caps functional area headings: GENERAL GOVERNMENT, PROTECTION SERVICES, etc.
_FUNCTIONAL_AREA_RE = re.compile(r"^[A-Z][A-Z\s&/()]+$")

# Patterns indicating auto-calculated / pre-populated lines
_AUTO_CALC_RE = re.compile(
    r"automatically\s+(?:carried\s+forward|calculated|populated)"
    r"|auto[-\s]?populated"
    r"|pre[-\s]?populated",
    re.IGNORECASE,
)

# SLC reference pattern (e.g. "SLC 12 9910 05")
_CARRY_FWD_SLC_RE = re.compile(r"SLC\s+(\d+\w*\s+\w{4}\s+\d{2})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Heading parsers
# ---------------------------------------------------------------------------


def _parse_line_heading(heading: str) -> tuple[str, str] | None:
    """Parse a section heading into (line_id, line_name) if it is a line heading.

    Handles the following formats found in the FIR markdown files:

    - ``Line 0299 - Taxation Own Purposes``
    - ``Lines 0696 to 0698 - Other:`` (range line — first ID only is returned)
    - ``Line 0812 Wastewater Treatment and Disposal`` (no separator)

    Args:
        heading: Section heading text (bold markers already stripped).

    Returns:
        ``(line_id, line_name)`` tuple, or ``None`` if the heading is not a line.
    """
    m = _LINE_HEADING_RE.match(heading.strip())
    if m:
        line_id = m.group(1)
        line_name = m.group(2).strip().rstrip(":").strip()
        return (line_id, line_name)
    return None


def _is_functional_area(heading: str) -> bool:
    """Return ``True`` if *heading* is an all-caps functional area heading.

    Functional area headings (e.g. ``GENERAL GOVERNMENT``, ``PROTECTION SERVICES``)
    consist entirely of uppercase letters, spaces, and a small set of punctuation
    characters used in the FIR Functional Categories document.

    Args:
        heading: Section heading text.

    Returns:
        ``True`` for headings like ``GENERAL GOVERNMENT``; ``False`` otherwise.
    """
    return bool(_FUNCTIONAL_AREA_RE.match(heading.strip()))


# ---------------------------------------------------------------------------
# Content detectors
# ---------------------------------------------------------------------------


def _extract_fc_description(
    sections: list[tuple[str, list[str]]],
    line_idx: int,
    end: int,
) -> str:
    """Extract functional-classification description text for a line.

    Collects the body text of ``sections[line_idx]`` (content between the line
    heading and the first sub-heading) and any sub-heading sections in
    ``sections[line_idx+1:end]``.

    Sub-heading sections are formatted as ``heading_text\\nbody_text`` blocks
    joined by ``\\n\\n``.  Exclusion language (e.g. ``do not include``,
    ``Excludes:``) is kept in-place within the returned text.

    Args:
        sections:  All parsed sections from the markdown file.
        line_idx:  Index of the line heading section.
        end:       Exclusive upper bound (index of the next line or area heading).

    Returns:
        Combined description string, or an empty string if there is no content.
    """
    if line_idx >= end or line_idx >= len(sections):
        return ""

    blocks: list[str] = []

    # Body text of the line heading section itself (before first sub-heading).
    line_body = _clean_md_content(sections[line_idx][1])
    if line_body:
        blocks.append(line_body)

    # Sub-heading sections within this line's range.
    for heading, content in sections[line_idx + 1 : end]:
        body = _clean_md_content(content)
        if heading and body:
            blocks.append(f"{heading}\n{body}")
        elif heading:
            blocks.append(heading)
        elif body:
            blocks.append(body)

    return "\n\n".join(blocks)


def _detect_auto_calculated(text: str) -> tuple[bool, str | None]:
    """Detect whether a line is auto-calculated and extract the SLC reference.

    Matches phrases like ``automatically carried forward from SLC X Y Z``,
    ``auto-populated``, and ``pre-populated``.

    Args:
        text: Description or other content text for the line.

    Returns:
        ``(is_auto_calculated, carry_forward_from)`` where ``carry_forward_from``
        is ``None`` if the line is not auto-calculated.
    """
    if not _AUTO_CALC_RE.search(text):
        return (False, None)

    m = _CARRY_FWD_SLC_RE.search(text)
    carry_fwd = m.group(1).strip() if m else None
    return (True, carry_fwd)


def _detect_subtotal(
    line_id: str, line_name: str, text: str
) -> tuple[bool, str | None]:
    """Detect whether a line is a subtotal / total row.

    A line is a subtotal if:

    - Its ``line_name`` contains the word ``total`` or ``subtotal`` (case-insensitive).
    - Its ``line_id`` matches the ``9XXX`` pattern (IDs starting with 9 are
      conventionally used for aggregate lines in FIR schedules).
    - Its description contains the phrase ``sum of lines``.

    When the 9XXX pattern is the only evidence, a note is added to
    ``change_notes``.

    Args:
        line_id:   4-character line identifier.
        line_name: Human-readable line name.
        text:      Full description text.

    Returns:
        ``(is_subtotal, change_notes)`` where ``change_notes`` is ``None``
        unless subtotal status was inferred from the ``line_id`` pattern.
    """
    name_lower = line_name.lower()

    if re.search(r"\b(?:sub)?total\b", name_lower):
        return (True, None)

    if "sum of lines" in text.lower():
        return (True, None)

    if re.match(r"^9\d{3}$", line_id):
        return (True, "Subtotal inferred from line_id pattern.")

    return (False, None)


def _detect_applicability(text: str) -> str | None:
    """Detect applicability restrictions mentioned in line instruction text.

    Args:
        text: Description or other content text for the line.

    Returns:
        A standardised applicability string, or ``None`` if no restriction found.
    """
    if re.search(r"upper.tier only", text, re.IGNORECASE):
        return "Upper-tier municipalities only"
    if re.search(r"lower.tier only", text, re.IGNORECASE):
        return "Lower-tier municipalities only"
    if re.search(r"[Cc]ity of [Tt]oronto", text):
        return "City of Toronto only"
    return None


# ---------------------------------------------------------------------------
# Functional Categories extraction
# ---------------------------------------------------------------------------


def _extract_fc_lines(markdown_dir: Path) -> list[dict[str, Any]]:
    """Extract line records from ``FIR2025 - Functional Categories.md``.

    Each functional line produces three records — one for each of schedules
    12, 40, and 51A — with the same ``includes`` / ``excludes`` content and a
    ``change_notes`` entry explaining the shared provenance.

    Sections in the document are classified as:

    - **Functional area headings** (all-caps): update ``section`` for subsequent lines.
    - **Line headings** (``Line XXXX - Name``): start a new line record.
    - **Sub-heading sections**: become sub-blocks within the current line's
      ``includes`` content.

    Args:
        markdown_dir: Directory containing the Functional Categories markdown file.

    Returns:
        Flat list of line metadata dicts.  Length is 3 × number of FC lines.
    """
    fc_path = markdown_dir / _FC_FILENAME
    sections = _parse_md_sections(fc_path)
    if not sections:
        return []

    # Skip the table of contents by starting at the main content heading.
    start_idx = _find_section(
        sections, "FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES"
    )
    if start_idx is None:
        start_idx = 0

    results: list[dict[str, Any]] = []
    current_fc_area: str | None = None

    # State for the currently open line being accumulated.
    open_line: dict[str, Any] | None = None

    def _close_open_line(end_idx: int) -> None:
        """Flush the open line to *results* using sections up to *end_idx*."""
        nonlocal open_line
        if open_line is None:
            return

        line_idx: int = open_line["idx"]
        line_id: str = open_line["line_id"]
        line_name: str = open_line["line_name"]

        fc_description = _extract_fc_description(sections, line_idx, end_idx)

        is_auto, carry_fwd = _detect_auto_calculated(fc_description)
        is_sub, sub_notes = _detect_subtotal(line_id, line_name, fc_description)
        applicability = _detect_applicability(fc_description)

        provenance = (
            "Source: Functional Categories document; "
            "applies to schedules 12, 40, and 51A generically."
        )
        change_notes_parts = [p for p in [sub_notes, provenance] if p]
        change_notes = " ".join(change_notes_parts)

        for sched in sorted(_SCHEDULES_WITH_FC_DATA):
            results.append(
                {
                    "schedule": sched,
                    "line_id": line_id,
                    "line_name": line_name,
                    "section": current_fc_area,
                    "description": fc_description if fc_description else None,
                    "is_subtotal": is_sub,
                    "is_auto_calculated": is_auto,
                    "carry_forward_from": carry_fwd,
                    "applicability": applicability,
                    "valid_from_year": None,
                    "valid_to_year": None,
                    "change_notes": change_notes,
                }
            )
        open_line = None

    for i in range(start_idx, len(sections)):
        heading = sections[i][0]

        line_parsed = _parse_line_heading(heading)
        is_fc_area = _is_functional_area(heading) and not line_parsed

        if is_fc_area or line_parsed:
            _close_open_line(i)

        if is_fc_area:
            current_fc_area = heading
        elif line_parsed:
            open_line = {
                "idx": i,
                "line_id": line_parsed[0],
                "line_name": line_parsed[1],
            }

    _close_open_line(len(sections))
    return results


# ---------------------------------------------------------------------------
# Per-schedule extraction
# ---------------------------------------------------------------------------


def _get_schedule_sections(
    markdown_dir: Path, code: str
) -> list[tuple[str, list[str]]]:
    """Return the parsed sections relevant to a given schedule code.

    For sub-schedules (22A/B/C, 51A/B, 61A/B), extracts only the sections
    within the sub-schedule's portion of the parent file by locating the
    heading prefix in :data:`_SUB_SCHEDULE_HEADING_PREFIXES` and scanning
    forward to the next sibling sub-schedule or EOF.

    For Schedule 74E, extracts sections from the ``Schedule 74E`` (exact) heading
    onward within ``FIR2025 S74.md``.

    For all other schedules, returns all sections from the schedule's own file.

    Args:
        markdown_dir: Directory containing per-schedule markdown files.
        code:         Schedule code.

    Returns:
        List of ``(heading, content)`` tuples, or ``[]`` if the file is absent.
    """
    if code in SUB_SCHEDULE_PARENTS:
        parent = SUB_SCHEDULE_PARENTS[code]
        md_path = markdown_dir / f"FIR2025 S{parent}.md"
        sections = _parse_md_sections(md_path)
        if not sections:
            return []

        prefix = _SUB_SCHEDULE_HEADING_PREFIXES[code]
        start = _find_section(sections, prefix, exact=False)
        if start is None:
            return []

        # Find end: next sibling sub-schedule in the same parent file, or EOF.
        sibling_prefixes = [
            p
            for k, p in _SUB_SCHEDULE_HEADING_PREFIXES.items()
            if k != code and _MD_PARENT_FILE.get(k) == parent
        ]
        end = len(sections)
        for j in range(start + 1, len(sections)):
            h = sections[j][0]
            if any(h.lower().startswith(sp.lower()) for sp in sibling_prefixes):
                end = j
                break

        return sections[start:end]

    if code == "74E":
        md_path = markdown_dir / "FIR2025 S74.md"
        sections = _parse_md_sections(md_path)
        if not sections:
            return []
        idx = _find_section(sections, "Schedule 74E", exact=True)
        return sections[idx:] if idx is not None else []

    md_path = markdown_dir / f"FIR2025 S{code}.md"
    return _parse_md_sections(md_path)


def _extract_per_schedule_lines(markdown_dir: Path, code: str) -> list[dict[str, Any]]:
    """Extract line metadata from a schedule's per-schedule instruction markdown.

    Scans section headings for ``Line XXXX - Name`` patterns.  Non-line headings
    update the current ``section`` label that is applied to all subsequent line
    records.

    Does **not** populate ``includes`` or ``excludes`` — those come from the
    Functional Categories document for schedules 12, 40, and 51A.

    Args:
        markdown_dir: Directory containing per-schedule markdown files.
        code:         Schedule code.

    Returns:
        List of line metadata dicts.
    """
    sections = _get_schedule_sections(markdown_dir, code)
    if not sections:
        return []

    records: list[dict[str, Any]] = []
    seen_line_ids: set[str] = set()
    current_section: str | None = None

    for heading, content in sections:
        line_parsed = _parse_line_heading(heading)

        if line_parsed:
            line_id, line_name = line_parsed

            # Skip duplicate line_ids — some schedules (e.g. 54) describe the same
            # lines twice under different method headings; keep the first occurrence.
            if line_id in seen_line_ids:
                continue
            seen_line_ids.add(line_id)

            text = _clean_md_content(content)
            is_auto, carry_fwd = _detect_auto_calculated(text)
            is_sub, sub_notes = _detect_subtotal(line_id, line_name, text)
            applicability = _detect_applicability(text)

            records.append(
                {
                    "schedule": code,
                    "line_id": line_id,
                    "line_name": line_name,
                    "section": current_section,
                    "description": text if text else None,
                    "is_subtotal": is_sub,
                    "is_auto_calculated": is_auto,
                    "carry_forward_from": carry_fwd,
                    "applicability": applicability,
                    "valid_from_year": None,
                    "valid_to_year": None,
                    "change_notes": sub_notes,
                }
            )
        elif heading:
            # Any non-line heading updates the current section label.
            current_section = heading

    return records


# ---------------------------------------------------------------------------
# Merge and top-level extraction
# ---------------------------------------------------------------------------


def extract_line_records(
    markdown_dir: Path,
    code: str,
    fc_lines: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract line metadata records for a single schedule code.

    For schedules 12, 40, and 51A, merges Functional Categories data with
    per-schedule data: FC lines are the authoritative source for
    ``line_id``, ``line_name``, and ``section``, while per-schedule data
    contributes additional instruction text, ``applicability``, and boolean
    flags when available.  Both sources' text is combined into ``description``.

    For all other schedules (including 51B), returns per-schedule data only.

    Args:
        markdown_dir: Directory containing the markdown source files.
        code:         Schedule code.
        fc_lines:     Pre-computed FC lines (pass from :func:`extract_all_line_meta`
                      to avoid re-parsing the FC file for each of 12 / 40 / 51A).

    Returns:
        List of line metadata dicts for the given schedule.
    """
    if code in _SCHEDULES_WITH_FC_DATA:
        if fc_lines is None:
            fc_lines = _extract_fc_lines(markdown_dir)

        fc_for_code = [r for r in fc_lines if r["schedule"] == code]

        # Index per-schedule lines by line_id for O(1) lookup during merge.
        per_sched: dict[str, dict[str, Any]] = {
            r["line_id"]: r for r in _extract_per_schedule_lines(markdown_dir, code)
        }

        merged: list[dict[str, Any]] = []
        for fc_rec in fc_for_code:
            rec = dict(fc_rec)
            ps_rec = per_sched.get(rec["line_id"])
            if ps_rec:
                # Combine FC description and per-schedule description.
                fc_desc = rec.get("description") or ""
                ps_desc = ps_rec.get("description") or ""
                if fc_desc and ps_desc:
                    rec["description"] = f"{fc_desc}\n\n{ps_desc}"
                elif ps_desc:
                    rec["description"] = ps_desc
                # OR in boolean flags: either source can declare is_subtotal / auto_calc.
                if ps_rec.get("is_subtotal"):
                    rec["is_subtotal"] = True
                if ps_rec.get("is_auto_calculated"):
                    rec["is_auto_calculated"] = True
                    if ps_rec.get("carry_forward_from"):
                        rec["carry_forward_from"] = ps_rec["carry_forward_from"]
                if ps_rec.get("applicability"):
                    rec["applicability"] = ps_rec["applicability"]
            merged.append(rec)

        return merged

    return _extract_per_schedule_lines(markdown_dir, code)


def extract_all_line_meta(markdown_dir: str | Path) -> list[dict[str, Any]]:
    """Extract line metadata records for all 31 FIR2025 schedule codes.

    Parses the Functional Categories document once and reuses the result for
    schedules 12, 40, and 51A.

    Args:
        markdown_dir: Path to the folder containing ``FIR2025 S{code}.md`` files
                      and ``FIR2025 - Functional Categories.md``.

    Returns:
        Flat list of line metadata dicts, one per (schedule, line) combination.
    """
    markdown_dir = Path(markdown_dir)
    fc_lines = _extract_fc_lines(markdown_dir)

    records: list[dict[str, Any]] = []
    for code in SCHEDULE_CATEGORIES:
        code_records = extract_line_records(markdown_dir, code, fc_lines=fc_lines)
        records.extend(code_records)

    return records


# ---------------------------------------------------------------------------
# Database insertion
# ---------------------------------------------------------------------------


def insert_line_meta(engine: Any, records: list[dict[str, Any]]) -> int:
    """Insert line metadata records into ``fir_line_meta``.

    Uses application-layer deduplication because PostgreSQL's unique constraint
    on ``(schedule, line_id, valid_from_year, valid_to_year)`` does not treat
    ``NULL = NULL``, so ``ON CONFLICT DO NOTHING`` cannot deduplicate baseline
    rows where both year columns are NULL.

    The ``schedule_id`` FK is resolved at insert time by querying
    ``fir_schedule_meta``.

    Args:
        engine:  SQLAlchemy engine.
        records: List of metadata dicts from :func:`extract_all_line_meta` or
                 :func:`load_from_csv`.

    Returns:
        Number of rows actually inserted.
    """
    if not records:
        return 0

    with Session(engine) as session:
        # Fetch existing (schedule, line_id, year) keys for deduplication.
        existing = session.exec(
            select(
                FIRLineMeta.schedule,
                FIRLineMeta.line_id,
                FIRLineMeta.valid_from_year,
                FIRLineMeta.valid_to_year,
            )
        ).all()
        existing_keys: set[tuple[str, str, int | None, int | None]] = {
            (row.schedule, row.line_id, row.valid_from_year, row.valid_to_year)
            for row in existing
        }

        new_records = [
            r
            for r in records
            if (
                r["schedule"],
                r["line_id"],
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
            pg_insert(FIRLineMeta)
            .values(insert_dicts)
            .on_conflict_do_nothing()
            .returning(FIRLineMeta.id)
        )
        result = session.execute(stmt)
        inserted = len(result.fetchall())
        session.commit()

    return inserted


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------


def save_to_csv(records: list[dict[str, Any]], csv_path: Path) -> None:
    """Save line metadata records to a CSV file.

    Uses the column order defined by :data:`_CSV_FIELDS`.  Parent directories
    are created if needed.  Any existing file is overwritten.

    Args:
        records:  List of line metadata dicts.
        csv_path: Destination path.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def load_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load line metadata records from a previously saved CSV.

    Handles type conversion for nullable string / integer fields and boolean
    fields that are stored as ``"True"`` / ``"False"`` strings.

    Args:
        csv_path: Path to a CSV file written by :func:`save_to_csv`.

    Returns:
        List of metadata dicts suitable for :func:`insert_line_meta`.
    """
    nullable_str_fields = {
        "section",
        "description",
        "carry_forward_from",
        "applicability",
        "change_notes",
    }
    nullable_int_fields = {"valid_from_year", "valid_to_year"}
    bool_fields = {"is_subtotal", "is_auto_calculated"}

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
            for field in bool_fields:
                record[field] = record.get(field, "False") == "True"
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@app.command()
def extract_baseline_line_meta(
    markdown_dir: Path = typer.Option(
        _DEFAULT_MARKDOWN_DIR,
        help="Directory containing FIR2025 S{code}.md files and Functional Categories",
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
    """Extract FIR2025 baseline line metadata and optionally load it into the DB.

    Reads per-schedule markdown files and the Functional Categories document,
    extracts one metadata record per (schedule, line) combination, exports to CSV
    for verification, and optionally inserts into ``fir_line_meta``.
    """
    typer.echo(f"Extracting line metadata from {markdown_dir}...")
    records = extract_all_line_meta(markdown_dir)
    typer.echo(f"  {len(records)} records extracted.")

    save_to_csv(records, export_path)
    typer.echo(f"Exported to {export_path}.")

    if load_db:
        engine = get_engine()
        inserted = insert_line_meta(engine, records)
        typer.echo(f"Inserted {inserted} new rows into fir_line_meta.")


@app.command()
def load_baseline_line_meta(
    csv_path: Path = typer.Option(
        _DEFAULT_EXPORT_PATH,
        help="Path to the baseline CSV (default: fir_instructions/exports/baseline_line_meta.csv)",
    ),
) -> None:
    """Load line metadata from the baseline CSV into the database.

    Reads the CSV previously produced by ``extract-baseline-line-meta``
    (which may have been manually edited) and inserts records into
    ``fir_line_meta``, skipping any that already exist.
    """
    typer.echo(f"Loading line metadata from {csv_path}...")
    records = load_from_csv(csv_path)
    typer.echo(f"  {len(records)} records loaded from CSV.")

    engine = get_engine()
    inserted = insert_line_meta(engine, records)
    typer.echo(f"Inserted {inserted} new rows into fir_line_meta.")
