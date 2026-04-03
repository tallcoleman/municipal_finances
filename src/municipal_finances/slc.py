"""Utilities for parsing and converting FIR SLC (Schedule-Line-Column) identifiers.

The SLC field on ``firrecord`` encodes a schedule, line, and column as:

    slc.{schedule_code}.L{line_4chars}.C{column_2digits}.{sub}

Example: ``slc.10.L9930.C01.01`` = Schedule 10, Line 9930, Column 01, Sub 01.

The line ID is typically 4 digits (e.g. ``9930``) but some schedules (76X, 80C, 81X)
use a 3-digit-plus-letter form (e.g. ``000A``, ``000B``). The sub field is always a
non-empty 2-character alphanumeric code in practice (e.g. ``01``, ``0A``).

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
    column_id: str
    sub: str


class PDFSLCComponents(TypedDict):
    """Components parsed from a PDF SLC reference. Fields are None where wildcarded."""

    schedule: str | None
    line_id: str | None
    column_id: str | None

# Matches the database SLC format: slc.<schedule>.L<line>.C<column>.<sub>
#
# Verification against firrecord (2020–2024 data, checked 2026-04-03):
#   - All SLC values match this pattern after the line_id was broadened from \d{4}
#     to [0-9A-Z]{4}.
#   - Schedules 76X, 80C, and 81X use alphanumeric line IDs (000A, 000B); all
#     other schedules use purely numeric 4-digit line IDs.
#   - The sub field is never empty in this data range; 30 distinct 2-character
#     alphanumeric values were observed (e.g. 01–28, 0A, 0B). The pattern retains
#     .* to stay permissive in case future data introduces other sub values.
_SLC_PATTERN = re.compile(
    r"^slc\.(?P<schedule>[^.]+)\.L(?P<line_id>[0-9A-Z]{4})\.C(?P<column_id>\d{2})\.(?P<sub>.*)$"
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

    Input format: ``slc.{schedule_code}.L{line_4chars}.C{column_2digits}.{sub}``

    The line ID is usually 4 digits (e.g. ``9930``) but may be a 3-digit-plus-letter
    code such as ``000A`` on schedules 76X, 80C, and 81X.

    Example::

        >>> parse_slc("slc.10.L9930.C01.01")
        {'schedule': '10', 'line_id': '9930', 'column_id': '01', 'sub': '01'}

    Args:
        slc: A database SLC string.

    Returns:
        A dict with keys ``schedule``, ``line_id``, ``column_id``, and ``sub``.
        ``schedule`` matches ``fir_schedule_meta.schedule`` (e.g. ``"10"``, ``"51A"``).

    Raises:
        ValueError: If the input does not match the expected format.
    """
    match = _SLC_PATTERN.match(slc)
    if not match:
        raise ValueError(
            f"Invalid SLC format: {slc!r}. "
            "Expected 'slc.<schedule>.L<line_4digits>.C<column_2digits>.<sub>'"
        )
    return {
        "schedule": match.group("schedule"),
        "line_id": match.group("line_id"),
        "column_id": match.group("column_id"),
        "sub": match.group("sub"),
    }


def slc_to_pdf_format(schedule: str, line_id: str, column_id: str) -> str:
    """Convert SLC components to the PDF reference format.

    Example::

        >>> slc_to_pdf_format("10", "9930", "01")
        'SLC 10 9930 01'

    Args:
        schedule: Schedule code, e.g. ``"10"`` or ``"51A"``.
        line_id: 4-digit line ID string, e.g. ``"9930"``.
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
