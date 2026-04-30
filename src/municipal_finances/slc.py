"""Utilities for parsing and converting FIR SLC (Schedule-Line-Column) identifiers.

The SLC field on ``firrecord`` encodes a schedule, line, and column as:

    slc.{schedule_code}.L{line_4chars}.C{column_section}.{column_id}

Example: ``slc.10X.L9930.C01.01`` = Schedule 10, Line 9930, Column Section 01, Column 01.

**X-suffix convention:** base schedules (those without an alphabetic sub-schedule
letter) use a trailing ``X`` in the schedule code.  So Schedule 10 appears as
``10X``, Schedule 12 as ``12X``, etc.  Schedules with real letter suffixes keep them
unchanged (``51A``, ``74D``, ``26B``, etc.).  Callers that need to join against
instruction metadata (which stores codes without the X) must strip the trailing X
before the lookup.

The line ID is a 4-character alphanumeric code, typically all digits (e.g. ``9930``),
but schedules 76X, 80C, and 81X use codes like ``000A`` and ``000B``. The column_id
field is always a non-empty 2-character alphanumeric code in practice (e.g. ``01``,
``0A``).

The FIR Instructions PDFs use a different, space-separated format:

    SLC {schedule} {line} {column}

Example: ``SLC 10 9930 01``

This module provides functions to parse both formats and convert between them.
"""

import re
from typing import TypedDict


class SLCComponents(TypedDict):
    """Components parsed from a database SLC string."""

    schedule: str
    line_id: str
    column_section: str
    column_id: str


class PDFSLCComponents(TypedDict):
    """Components parsed from a PDF SLC reference. Fields are None where wildcarded."""

    schedule: str | None
    line_id: str | None
    column_id: str | None


# Matches the database SLC format: slc.<schedule>.L<line>.C<column_section>.<column_id>
#
# Verification against firrecord (2020–2025 data, last checked 2026-04-29):
#   - All SLC values match this pattern after the line_id was broadened from \d{4}
#     to [0-9A-Z]{4}.
#   - Schedules 76X, 80C, and 81X use alphanumeric line IDs (000A, 000B); all
#     other schedules use purely numeric 4-digit line IDs.
#   - The column_id field is never empty in this data range; 30 distinct 2-character
#     alphanumeric values were observed across 2020–2024 (e.g. 01–28, 0A, 0B);
#     2025 data alone shows 19 distinct values. The pattern requires exactly 2
#     alphanumeric characters, matching what real data always produces.
_SLC_PATTERN = re.compile(
    r"^slc\.(?P<schedule>[^.]+)\.L(?P<line_id>[0-9A-Z]{4})\.C(?P<column_section>\d{2})\.(?P<column_id>[0-9A-Za-z]{2})$"
)

# Matches the PDF SLC format: [SLC ]<schedule> <line> <column>
# line_id must be exactly 4 digits or a wildcard (x+); column_id must be exactly 2 digits or a wildcard.
_PDF_SLC_PATTERN = re.compile(
    r"^(?:SLC\s+)?(?P<schedule>\S+)\s+(?P<line_id>\d{4}|x+)\s+(?P<column_id>\d{2}|x+)$",
    re.IGNORECASE,
)

# Wildcard token used in PDF SLC patterns (e.g. "40 xxxx 05")
_WILDCARD_RE = re.compile(r"^x+$", re.IGNORECASE)


def parse_slc(slc: str) -> SLCComponents:
    """Parse a database SLC string into its component parts.

    Input format: ``slc.{schedule_code}.L{line_4chars}.C{column_section}.{column_id}``

    The line ID is a 4-character alphanumeric code, usually all digits (e.g. ``9930``),
    but schedules 76X, 80C, and 81X use codes like ``000A`` and ``000B``.

    Example::

        >>> parse_slc("slc.10X.L9930.C01.01")
        {'schedule': '10X', 'line_id': '9930', 'column_section': '01', 'column_id': '01'}

    Args:
        slc: A database SLC string.

    Returns:
        A dict with keys ``schedule``, ``line_id``, ``column_section``, and ``column_id``.
        ``schedule`` is the raw code from the SLC field (e.g. ``"10X"``, ``"51A"``).
        ``column_section`` is the 2-digit grouping number (from ``C01``, ``C02``, etc.)
        that identifies a set of columns sharing the same headings.
        ``column_id`` is the specific column or fill-in label within that section
        (e.g. ``"01"``, ``"02"``, ``"0A"``).
        To look up instruction metadata (which omits the trailing X), strip a
        trailing ``X`` from base schedules before the join.

    Raises:
        ValueError: If the input does not match the expected format.
    """
    match = _SLC_PATTERN.match(slc)
    if not match:
        raise ValueError(
            f"Invalid SLC format: {slc!r}. "
            "Expected 'slc.<schedule>.L<line_4chars>.C<column_section>.<column_id>'"
        )
    return {
        "schedule": match.group("schedule"),
        "line_id": match.group("line_id"),
        "column_section": match.group("column_section"),
        "column_id": match.group("column_id"),
    }


def slc_to_pdf_format(schedule: str, line_id: str, column_id: str) -> str:
    """Convert SLC components to the PDF reference format.

    Example::

        >>> slc_to_pdf_format("10", "9930", "01")
        'SLC 10 9930 01'

    Args:
        schedule: Schedule code, e.g. ``"10"`` or ``"51A"``.
        line_id: 4-character line ID string, e.g. ``"9930"``.
        column_id: 2-digit column ID string, e.g. ``"01"``.

    Returns:
        A space-separated PDF reference string of the form ``SLC <schedule> <line> <column>``.
    """
    return f"SLC {schedule} {line_id} {column_id}"


def pdf_slc_to_components(pdf_slc: str) -> PDFSLCComponents:
    """Parse a PDF-format SLC reference into its component parts.

    Accepts both the bare form (``"10 9930 01"``) and the prefixed form
    (``"SLC 10 9930 01"``). Also handles wildcard tokens such as ``"xxxx"``
    or ``"xx"`` (any sequence of ``x`` characters, case-insensitive) — these
    are represented as ``None`` in the returned dict.

    Example::

        >>> pdf_slc_to_components("SLC 10 9930 01")
        {'schedule': '10', 'line_id': '9930', 'column_id': '01'}

        >>> pdf_slc_to_components("40 xxxx 05")
        {'schedule': '40', 'line_id': None, 'column_id': '05'}

    Args:
        pdf_slc: A PDF SLC reference string.

    Returns:
        A dict with keys ``schedule``, ``line_id``, and ``column_id``.
        Values are ``None`` where the token is a wildcard.

    Raises:
        ValueError: If the input does not match the expected format.
    """
    match = _PDF_SLC_PATTERN.match(pdf_slc.strip())
    if not match:
        raise ValueError(
            f"Invalid PDF SLC format: {pdf_slc!r}. "
            "Expected '[SLC ]<schedule> <line> <column>'"
        )

    def _parse_token(token: str) -> str | None:
        return None if _WILDCARD_RE.match(token) else token

    return {
        "schedule": _parse_token(match.group("schedule")),
        "line_id": _parse_token(match.group("line_id")),
        "column_id": _parse_token(match.group("column_id")),
    }
