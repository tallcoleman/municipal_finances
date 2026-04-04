"""Extract Content Changes tables from FIR Instructions PDF changelogs.

Each FIR year ships a "Changes" PDF with a Content Changes table listing every
schedule/line/column that was added, removed, or modified.  This module parses
those tables with pdfplumber and stores the results in
``fir_instruction_changelog``.

PDF table structure
-------------------
The tables have four columns: Schedule, SLC, Heading, Description.  Column
x-positions vary across years but the relative layout is consistent:

- **Schedule zone**: ``[sch_x - 15, sch_x + 35]``
- **SLC zone**: ``[sch_x + 35, slc_x + 30]``  (slc_x = header "SLC" label x-pos)
- **Heading + Description**: everything to the right of slc_x + 30, split at the
  largest inter-word gap.

Key parsing behaviours
----------------------
- Words are grouped into rows via sequential y-position comparison with a 4-pt
  tolerance, which handles rows whose words span a couple of points vertically.
- Section headers ("MAJOR CHANGES", "MINOR CHANGES") reset the current severity.
- Cells for Schedule, SLC, and Heading are only populated on the first row where
  the value changes; blank cells carry forward the previous value.  However, SLC
  and Heading carry-forward resets when Schedule changes.
- Entries that describe multiple changes in one row (e.g. "New lines 0410, 0420,
  0430 added") are split into separate records.
- Schedule-level entries ("New **", "Deleted") produce ``new_schedule`` /
  ``deleted_schedule`` change_type records with slc_pattern=None.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import pdfplumber
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session

from municipal_finances.models import FIRInstructionChangelog
from municipal_finances.slc import pdf_slc_to_components

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_CHANGE_TYPES = frozenset(
    [
        "new_schedule",
        "deleted_schedule",
        "new_line",
        "deleted_line",
        "updated_line",
        "new_column",
        "deleted_column",
        "updated_column",
        "updated_schedule",
    ]
)

# Words that indicate a "New **" schedule-level marker in the SLC zone.
_NEW_SCHEDULE_TOKEN = "**"
_DELETED_TOKEN_RE = re.compile(r"^deleted$", re.IGNORECASE)

# Section header patterns.
_MAJOR_RE = re.compile(r"major\s+change", re.IGNORECASE)
_MINOR_RE = re.compile(r"minor\s+change", re.IGNORECASE)

# Regex to split concatenated SLC tokens like "77A1040" → ("77A", "1040").
_SPLIT_SCHED_LINE_RE = re.compile(r"^(.+?)(\d{4})$")

# Regex for multi-entry rows, e.g. "New lines 0410, 0420, 0430 added".
_MULTI_LINE_RE = re.compile(r"\b(\d{4})\b")

# ---------------------------------------------------------------------------
# Row grouping
# ---------------------------------------------------------------------------


def _group_words_into_rows(
    words: list[dict[str, Any]], y_tolerance: float = 4.0
) -> list[list[dict[str, Any]]]:
    """Group pdfplumber word dicts into rows by y-position proximity.

    Words are sorted top-to-bottom then left-to-right.  A new row starts when
    the word's ``top`` value exceeds the current row's running maximum ``bottom``
    by more than *y_tolerance* points.

    Args:
        words: List of word dicts from ``pdfplumber.Page.extract_words()``.
        y_tolerance: Maximum gap (in points) between a word's ``top`` and the
            current row's maximum ``bottom`` before starting a new row.

    Returns:
        List of rows, each row being a list of word dicts sorted by ``x0``.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: list[list[dict[str, Any]]] = []
    current_row: list[dict[str, Any]] = [sorted_words[0]]
    row_max_bottom: float = sorted_words[0]["bottom"]

    for w in sorted_words[1:]:
        if w["top"] > row_max_bottom + y_tolerance:
            rows.append(sorted(current_row, key=lambda x: x["x0"]))
            current_row = [w]
            row_max_bottom = w["bottom"]
        else:
            current_row.append(w)
            row_max_bottom = max(row_max_bottom, w["bottom"])

    rows.append(sorted(current_row, key=lambda x: x["x0"]))
    return rows


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------


def _find_header_row(
    rows: list[list[dict[str, Any]]],
) -> tuple[float, float, float, float] | None:
    """Locate the Content Changes table header and return column x-positions.

    Scans rows for one containing the tokens "SLC", "Heading" (or "Sch."),
    and "Description".

    Args:
        rows: Rows produced by :func:`_group_words_into_rows`.

    Returns:
        ``(sch_x, slc_x, heading_x, desc_x)`` — the ``x0`` of the first word
        in each column header cell — or ``None`` if no header row is found.
    """
    for row in rows:
        texts = [w["text"].lower() for w in row]
        joined = " ".join(texts)
        if "slc" in texts and ("heading" in texts or "description" in joined):
            sch_x: float | None = None
            slc_x: float | None = None
            heading_x: float | None = None
            desc_x: float | None = None
            for w in row:
                t = w["text"].lower()
                if t in ("sch.", "schedule") and sch_x is None:
                    sch_x = w["x0"]
                elif t == "slc" and slc_x is None:
                    slc_x = w["x0"]
                elif t in ("heading", "head.", "head") and heading_x is None:
                    heading_x = w["x0"]
                elif t in ("description", "desc.", "desc") and desc_x is None:
                    desc_x = w["x0"]
            if slc_x is not None and desc_x is not None:
                if sch_x is None:
                    sch_x = slc_x - 40.0  # fallback estimate
                if heading_x is None:
                    heading_x = slc_x + 30.0
                return (sch_x, slc_x, heading_x, desc_x)
    return None


# ---------------------------------------------------------------------------
# Row classification helpers
# ---------------------------------------------------------------------------


def _is_section_header(row_words: list[dict[str, Any]]) -> str | None:
    """Return 'major', 'minor', or None based on row text content.

    Args:
        row_words: Words in a single row.

    Returns:
        ``'major'``, ``'minor'``, or ``None``.
    """
    text = " ".join(w["text"] for w in row_words)
    if _MAJOR_RE.search(text):
        return "major"
    if _MINOR_RE.search(text):
        return "minor"
    return None


def _is_header_row(row_words: list[dict[str, Any]]) -> bool:
    """Return True if this row is the Content Changes table header.

    Args:
        row_words: Words in the row.

    Returns:
        True when the row looks like a column-header row (contains "SLC" and
        "Heading" or "Description").
    """
    texts_lower = {w["text"].lower() for w in row_words}
    return "slc" in texts_lower and (
        "heading" in texts_lower or "description" in texts_lower
    )


# Valid schedule token: alphanumeric characters only (no colon, slash, etc.)
_VALID_SCHEDULE_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")


def _classify_row(
    row_words: list[dict[str, Any]],
    sch_x: float,
    slc_x: float,
) -> str:
    """Classify a data row as 'data', 'blank_schedule', 'continuation', or 'other'.

    Args:
        row_words: Words in the row, sorted by x0.
        sch_x: x-position of the Schedule header column.
        slc_x: x-position of the SLC header column.

    Returns:
        Row type string.
    """
    if not row_words:
        return "other"

    # Header rows (Sch./SLC/Heading/Description) are never data
    if _is_header_row(row_words):
        return "other"

    first = row_words[0]
    sched_lo = sch_x - 15
    sched_hi = sch_x + 35
    slc_lo = sch_x + 35
    slc_hi = slc_x + 30

    if sched_lo <= first["x0"] < sched_hi:
        # First word is in schedule zone — data row only if it starts with alnum
        if first["text"] and first["text"][0].isalnum():
            return "data"
        return "other"
    elif slc_lo <= first["x0"] < slc_hi:
        # blank_schedule row: first SLC-zone word must look like a valid schedule
        # or SLC token (pure alphanumeric — no colon, slash, etc.)
        if _VALID_SCHEDULE_TOKEN_RE.match(first["text"]):
            return "blank_schedule"
        return "other"
    elif first["x0"] >= slc_hi:
        return "continuation"
    return "other"


# ---------------------------------------------------------------------------
# SLC token parsing
# ---------------------------------------------------------------------------


def _extract_slc_info(
    slc_tokens: list[str],
) -> tuple[str | None, str | None, str | None, bool, bool]:
    """Parse SLC zone tokens into components.

    SLC zone tokens typically follow one of:
    - ``[schedule_dup, line_id, col_id]`` — normal line/column entry
    - ``[schedule, "New", "**"]`` — new schedule marker
    - ``[schedule, "Deleted"]`` — deleted schedule marker

    Tokens may also be concatenated, e.g. ``"77A1040"`` → ``("77A", "1040")``.

    Args:
        slc_tokens: Text of words in the SLC zone, in left-to-right order.

    Returns:
        ``(slc_pattern, line_id, column_id, is_new_schedule, is_deleted_schedule)``
        where ``slc_pattern`` is the raw SLC string (e.g. ``"61 0206 xx"``),
        ``line_id`` and ``column_id`` are ``None`` for wildcards, and the two
        boolean flags indicate schedule-level changes.
    """
    if not slc_tokens:
        return None, None, None, False, False

    # Detect "New **" → new_schedule
    if _NEW_SCHEDULE_TOKEN in slc_tokens:
        return None, None, None, True, False

    # Detect "Deleted" → deleted_schedule
    if any(_DELETED_TOKEN_RE.match(t) for t in slc_tokens):
        return None, None, None, False, True

    # Try to split concatenated tokens so we end up with [schedule, line, col]
    expanded: list[str] = []
    for token in slc_tokens:
        m = _SPLIT_SCHED_LINE_RE.match(token)
        if m and len(expanded) == 0:
            # First token may be schedule+line glued together
            expanded.append(m.group(1))
            expanded.append(m.group(2))
        else:
            expanded.append(token)

    if len(expanded) < 3:
        # Insufficient tokens — can't form a full SLC pattern
        return None, None, None, False, False

    schedule_dup = expanded[0]
    line_tok = expanded[1]
    col_tok = expanded[2]
    slc_pattern = f"{schedule_dup} {line_tok} {col_tok}"

    try:
        components = pdf_slc_to_components(slc_pattern)
        return slc_pattern, components["line_id"], components["column_id"], False, False
    except ValueError:
        # Pattern didn't parse — return raw with no components
        return slc_pattern, None, None, False, False


# ---------------------------------------------------------------------------
# Heading / description split
# ---------------------------------------------------------------------------


def _split_heading_description(
    words: list[dict[str, Any]],
) -> tuple[str, str | None]:
    """Split remaining (heading + description) words at the largest inter-word gap.

    Args:
        words: Words to the right of the SLC zone, sorted by x0.

    Returns:
        ``(heading, description)`` where ``description`` is ``None`` if there
        is only one cluster of words.
    """
    if not words:
        return "", None
    if len(words) == 1:
        return words[0]["text"], None

    # Compute gaps between consecutive words
    gaps: list[tuple[float, int]] = []
    for i in range(1, len(words)):
        gap = words[i]["x0"] - words[i - 1]["x1"]
        gaps.append((gap, i))

    max_gap, split_idx = max(gaps, key=lambda g: g[0])

    # Only split if the gap is substantial (> 10 pts)
    if max_gap < 10:
        return " ".join(w["text"] for w in words), None

    heading = " ".join(w["text"] for w in words[:split_idx])
    description = " ".join(w["text"] for w in words[split_idx:])
    return heading, description


# ---------------------------------------------------------------------------
# Change type inference
# ---------------------------------------------------------------------------


def _infer_change_type(
    description: str | None,
    heading: str | None,
    slc_pattern: str | None,
    line_id: str | None,
    column_id: str | None,
    is_new_schedule: bool,
    is_deleted_schedule: bool,
) -> str:
    """Infer change_type from context clues.

    Args:
        description: Description cell text (may be None).
        heading: Heading cell text (may be None).
        slc_pattern: Raw SLC pattern string (may be None or contain wildcards).
        line_id: Parsed line ID (None for wildcards).
        column_id: Parsed column ID (None for wildcards).
        is_new_schedule: True if a "New **" marker was detected.
        is_deleted_schedule: True if a "Deleted" marker was detected.

    Returns:
        A change_type string from the allowed set.
    """
    if is_new_schedule:
        return "new_schedule"
    if is_deleted_schedule:
        return "deleted_schedule"

    text = " ".join(filter(None, [description, heading])).lower()

    # Check for new/deleted/updated at column level
    has_col = column_id is not None or (
        slc_pattern is not None and not slc_pattern.endswith("xx")
    )
    # Determine if this is a column-level or line-level entry.
    # Column-level: column_id is deterministic (not wildcard)
    col_deterministic = column_id is not None
    line_wildcard = line_id is None and slc_pattern is not None

    if col_deterministic:
        if re.search(r"\b(new|added)\b", text):
            return "new_column"
        if re.search(r"\b(deleted?|removed?)\b", text):
            return "deleted_column"
        return "updated_column"

    if line_wildcard:
        # Line wildcarded — change applies to a whole set of lines/columns
        if re.search(r"\b(new|added)\b", text):
            return "new_line"
        if re.search(r"\b(deleted?|removed?)\b", text):
            return "deleted_line"
        return "updated_line"

    # line_id is deterministic
    if re.search(r"\b(new|added)\b", text):
        return "new_line"
    if re.search(r"\b(deleted?|removed?)\b", text):
        return "deleted_line"
    return "updated_line"


# ---------------------------------------------------------------------------
# Multi-entry splitting
# ---------------------------------------------------------------------------


def _split_multi_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Split a single entry that references multiple line IDs into separate entries.

    For example, a description like "New lines 0410, 0420, 0430 added" with a
    wildcard line_id becomes three entries, one per line ID.

    Args:
        entry: A single changelog entry dict.

    Returns:
        List of one or more entry dicts.
    """
    # Only split when the SLC is fully wildcarded at line level
    if entry.get("line_id") is not None:
        return [entry]
    desc = entry.get("description") or ""
    heading = entry.get("heading") or ""
    combined = f"{heading} {desc}"
    line_ids = _MULTI_LINE_RE.findall(combined)
    if len(line_ids) <= 1:
        return [entry]

    schedule = entry.get("schedule", "")
    col_id = entry.get("column_id")
    results = []
    for lid in line_ids:
        col_part = col_id if col_id else "xx"
        slc_pattern = f"{schedule} {lid} {col_part}"
        try:
            components = pdf_slc_to_components(slc_pattern)
            parsed_col = components["column_id"]
        except ValueError:
            parsed_col = None
        new_entry = dict(entry)
        new_entry["slc_pattern"] = slc_pattern
        new_entry["line_id"] = lid
        new_entry["column_id"] = parsed_col
        results.append(new_entry)
    return results


# ---------------------------------------------------------------------------
# Carry-forward
# ---------------------------------------------------------------------------


def _apply_carry_forward(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill blank heading values by carrying forward from the previous row.

    Carry-forward rules:
    - ``heading`` is carried forward within the same ``schedule`` + ``slc_pattern``
      group (stops when either changes).
    - ``schedule`` is NOT carried forward; it is always extracted from the row or
      from the SLC schedule_dup token.

    Args:
        entries: List of raw entry dicts (in order).

    Returns:
        Same list with heading gaps filled in-place.
    """
    prev_heading: str | None = None
    prev_schedule: str | None = None
    prev_slc: str | None = None

    for entry in entries:
        sched = entry.get("schedule")
        slc = entry.get("slc_pattern")

        # Reset carry-forward if schedule or SLC changes
        if sched != prev_schedule or slc != prev_slc:
            prev_heading = None

        heading = entry.get("heading")
        if not heading and prev_heading:
            entry["heading"] = prev_heading
        elif heading:
            prev_heading = heading

        prev_schedule = sched
        prev_slc = slc

    return entries


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------


def _parse_content_changes_page(
    page: Any,
    sch_x: float,
    slc_x: float,
    current_severity: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Extract changelog entries from a single PDF page.

    Args:
        page: A ``pdfplumber.Page`` object.
        sch_x: x-position of the Schedule column header.
        slc_x: x-position of the SLC column header.
        current_severity: Severity carried in from the previous page ('major',
            'minor', or None).

    Returns:
        ``(entries, new_severity)`` — list of raw entry dicts and the severity
        state at the end of the page.
    """
    slc_zone_end = slc_x + 30
    sched_lo = sch_x - 15
    sched_hi = sch_x + 35

    words = page.extract_words()
    rows = _group_words_into_rows(words)
    entries: list[dict[str, Any]] = []

    for row in rows:
        # Section header check
        severity_hit = _is_section_header(row)
        if severity_hit:
            current_severity = severity_hit
            continue

        row_type = _classify_row(row, sch_x, slc_x)
        if row_type not in ("data", "blank_schedule"):
            continue

        # Partition words into schedule zone, SLC zone, remainder
        sched_zone_words = [w for w in row if sched_lo <= w["x0"] < sched_hi]
        slc_zone_words = [w for w in row if sched_hi <= w["x0"] < slc_zone_end]
        remainder_words = [w for w in row if w["x0"] >= slc_zone_end]

        # --- Schedule ---
        if row_type == "data":
            # All tokens in schedule zone; handle multi-token ("77A, B, C & D")
            schedule = " ".join(w["text"] for w in sched_zone_words).strip()
        else:
            # blank_schedule: extract schedule from SLC schedule_dup (first token
            # that isn't a 4-digit number or wildcard)
            schedule = ""
            for w in slc_zone_words:
                t = w["text"]
                if not re.match(r"^\d{4}$", t) and not re.match(r"^x+$", t, re.I):
                    schedule = t
                    break

        # --- SLC tokens ---
        slc_tokens = [w["text"] for w in slc_zone_words]
        slc_pattern, line_id, column_id, is_new, is_deleted = _extract_slc_info(
            slc_tokens
        )

        # --- Heading / description ---
        heading, description = _split_heading_description(remainder_words)

        change_type = _infer_change_type(
            description, heading, slc_pattern, line_id, column_id, is_new, is_deleted
        )

        entry: dict[str, Any] = {
            "schedule": schedule,
            "slc_pattern": slc_pattern,
            "line_id": line_id,
            "column_id": column_id,
            "heading": heading or None,
            "change_type": change_type,
            "severity": current_severity,
            "description": description or None,
        }
        entries.append(entry)

    return entries, current_severity


def extract_changelog_from_pdf(
    pdf_path: Path, year: int
) -> list[dict[str, Any]]:
    """Extract all Content Changes entries from a single FIR changelog PDF.

    Scans every page for the Content Changes table header, then extracts rows
    until all pages are processed.  Applies carry-forward logic and multi-entry
    splitting before returning.

    Args:
        pdf_path: Path to the FIR Changes PDF file.
        year: FIR reporting year (e.g. 2025).

    Returns:
        List of entry dicts ready for insertion into ``fir_instruction_changelog``.
        Each dict has keys: ``year``, ``schedule``, ``slc_pattern``, ``line_id``,
        ``column_id``, ``heading``, ``change_type``, ``severity``, ``description``,
        ``source``.

    Raises:
        ValueError: If no Content Changes header row is found in the PDF.
    """
    entries: list[dict[str, Any]] = []
    sch_x: float | None = None
    slc_x: float | None = None
    current_severity: str | None = None
    header_found = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            rows = _group_words_into_rows(words)

            # Look for (or re-find) the header on this page
            header = _find_header_row(rows)
            if header is not None:
                sch_x, slc_x, _, _ = header
                header_found = True
                # Skip the header row itself when extracting
                # (handled by _parse_content_changes_page classification)

            if not header_found or sch_x is None or slc_x is None:
                continue

            page_entries, current_severity = _parse_content_changes_page(
                page, sch_x, slc_x, current_severity
            )
            entries.extend(page_entries)

    if not header_found:
        raise ValueError(
            f"No Content Changes table header found in {pdf_path.name}"
        )

    # Apply carry-forward to fill blank heading cells
    entries = _apply_carry_forward(entries)

    # Split multi-entry rows
    split_entries: list[dict[str, Any]] = []
    for entry in entries:
        split_entries.extend(_split_multi_entry(entry))

    # Stamp year and source
    for entry in split_entries:
        entry["year"] = year
        entry["source"] = "pdf_changelog"

    return split_entries


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def insert_changelog_entries(
    engine: Any, entries: list[dict[str, Any]]
) -> int:
    """Insert changelog entries into ``fir_instruction_changelog``, skipping duplicates.

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` for entries whose ``slc_pattern``
    is not NULL (those can be matched by the unique constraint on the table).
    For entries where ``slc_pattern`` IS NULL, deduplication is handled at the
    application level because PostgreSQL treats NULLs as distinct in unique
    constraints.

    Args:
        engine: SQLAlchemy engine (from :func:`~municipal_finances.database.get_engine`).
        entries: List of dicts produced by :func:`extract_changelog_from_pdf`.

    Returns:
        Number of rows actually inserted.
    """
    if not entries:
        return 0

    required_keys = {"year", "schedule", "change_type", "source"}
    for entry in entries:
        missing = required_keys - entry.keys()
        if missing:
            raise ValueError(f"Entry missing required keys: {missing}. Entry: {entry}")

    inserted = 0

    with Session(engine) as session:
        # Separate null-slc_pattern entries (schedule-level) from the rest
        null_slc = [e for e in entries if e.get("slc_pattern") is None]
        non_null_slc = [e for e in entries if e.get("slc_pattern") is not None]

        # Non-null: bulk insert with ON CONFLICT DO NOTHING
        if non_null_slc:
            stmt = pg_insert(FIRInstructionChangelog).values(non_null_slc)
            stmt = stmt.on_conflict_do_nothing()
            result = session.execute(stmt)
            inserted += result.rowcount

        # Null slc_pattern: app-level dedup before inserting
        for entry in null_slc:
            exists = session.exec(  # type: ignore[call-overload]
                __import__("sqlmodel", fromlist=["select"]).select(
                    FIRInstructionChangelog
                ).where(
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


def save_to_csv(entries: list[dict[str, Any]], csv_path: Path) -> None:
    """Save extracted changelog entries to a CSV file.

    The file uses the column order defined by ``_CSV_FIELDS``.  Existing content
    is overwritten.

    Args:
        entries: List of entry dicts.
        csv_path: Destination path (parent directory must exist).
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)


def load_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load changelog entries from a previously saved CSV file.

    Empty strings are converted to ``None`` for nullable fields
    (``slc_pattern``, ``line_id``, ``column_id``, ``heading``,
    ``severity``, ``description``).

    Args:
        csv_path: Path to a CSV file written by :func:`save_to_csv`.

    Returns:
        List of entry dicts with integer ``year`` and typed fields.
    """
    nullable = {"slc_pattern", "line_id", "column_id", "heading", "severity", "description"}
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
