"""Extract FIR2025 schedule-level metadata from the instructions PDF text.

This module reads the pre-converted ``.txt`` file produced by ``pdftotext -layout``
(see :mod:`pdf_extraction`) and extracts one metadata record per schedule code.
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
        "fir_instructions/source_files/FIR2025 Instructions.txt",
        "fir_instructions/source_files/FIR2025 Instructions.offsets.json",
    )
    insert_schedule_meta(engine, records)
    save_to_csv(records, Path("fir_instructions/exports/baseline_schedule_meta.csv"))
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
from municipal_finances.fir_instructions.pdf_extraction import load_schedule_offsets
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

# Sub-schedules that share a PDF section with their parent schedule.
# These codes do NOT have entries in the offset map.
SUB_SCHEDULE_PARENTS: dict[str, str] = {
    "22A": "22",
    "22B": "22",
    "22C": "22",
    "51A": "51",
    "51B": "51",
    "61A": "61",
    "61B": "61",
}

# Heading text that identifies where each sub-schedule begins in its parent body.
# Used as a startswith prefix (case-insensitive).
_SUB_SCHEDULE_HEADINGS: dict[str, str] = {
    "22A": "General Purpose Levy Information (22A)",
    "22B": "Lower-Tier / Single-Tier Special Area Levy Information (22B)",
    "22C": "Upper-Tier Special Area Levy Information (22C)",
    "51A": "Schedule 51A:",
    "51B": "Schedule 51B:",
    "61A": "Schedule 61A:",
    "61B": "Schedule 61B:",
}

# Heading text where each sub-schedule's description ends (exclusive).
# None means: read to the end of the parent section.
_SUB_SCHEDULE_NEXT_HEADINGS: dict[str, str | None] = {
    "22A": "Lower-Tier / Single-Tier Special Area Levy Information (22B)",
    "22B": "Upper-Tier Special Area Levy Information (22C)",
    "22C": "Adjustments to Taxation (22D)",
    "51A": "Schedule 51B:",
    "51B": None,
    "61A": "Schedule 61B:",
    "61B": None,
}

# Offset keys that are internal sub-section markers, not top-level schedules.
# These are skipped when computing a schedule's section_end.
_INTERNAL_OFFSET_KEYS: frozenset[str] = frozenset({"02", "74A", "74B", "74C", "74D"})

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

_DEFAULT_TXT_PATH = Path("fir_instructions/source_files/FIR2025 Instructions.txt")
_DEFAULT_OFFSETS_PATH = Path(
    "fir_instructions/source_files/FIR2025 Instructions.offsets.json"
)
_DEFAULT_EXPORT_PATH = Path("fir_instructions/exports/baseline_schedule_meta.csv")


# ---------------------------------------------------------------------------
# Low-level text helpers
# ---------------------------------------------------------------------------

_PAGE_HEADER_RE = re.compile(r"FIR\d{4}.*P\s*a\s*g\s*e\s*\|?\s*\d+", re.IGNORECASE)
_DOT_LEADERS_RE = re.compile(r"\.{3,}\s*\d+\s*$")
_SCHEDULE_BODY_TITLE_RE = re.compile(r"^SCHEDULE\s+([\w][\w\s]*?):", re.IGNORECASE)


def _is_page_header(line: str) -> bool:
    """Return True if *line* is a FIR page header.

    Matches both normal headers (``FIR2025  Page |N  Schedule XX``) and the
    spaced variant (``P a g e | N``) used in some sub-sections like Schedule 74.

    Args:
        line: A single line from the text file (may contain a trailing newline).

    Returns:
        True if the line matches a page header pattern.
    """
    return bool(_PAGE_HEADER_RE.search(line))


def _has_dot_leaders(line: str) -> bool:
    """Return True if *line* contains a TOC dot-leader pattern (``....N``).

    Args:
        line: A single text line.

    Returns:
        True if the line ends with three or more dots followed by a page number.
    """
    return bool(_DOT_LEADERS_RE.search(line.strip()))


def _strip_dot_leaders(text: str) -> str:
    """Remove trailing dot leaders and page number from a TOC entry text.

    Args:
        text: Stripped TOC entry text, e.g. ``"General Instructions ........ 5"``.

    Returns:
        The heading text without dots or trailing page number.
    """
    return _DOT_LEADERS_RE.sub("", text).strip()


def _count_leading_spaces(line: str) -> int:
    """Return the number of leading space characters in *line*.

    Used to determine the indentation level of TOC entries.

    Args:
        line: A text line (trailing newline is ignored).

    Returns:
        Number of leading spaces.
    """
    return len(line) - len(line.lstrip(" "))


def _clean_text(lines: list[str]) -> str:
    """Produce a clean, plain-text description from a slice of raw lines.

    Removes page headers, strips form-feed characters, strips trailing
    whitespace from each line, and collapses runs of more than two consecutive
    blank lines to a single blank line.

    Args:
        lines: Raw lines from the text file (may include page headers,
               form-feeds, and variable leading/trailing whitespace).

    Returns:
        A clean multi-line string suitable for storage as ``description``.
    """
    # Decorative cover pages for the following schedule appear at the end of the
    # last page of a section.  Their marker line is "YYYY Financial Information
    # Return"; everything from this line onward is discarded.
    _cover_page_re = re.compile(r"^\s*20\d{2}\s+Financial Information Return\s*$")

    cleaned: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r").replace("\x0c", "")
        if _is_page_header(line):
            continue
        if _cover_page_re.match(line):
            break  # Remaining lines are a cover page; discard them
        cleaned.append(line.rstrip())

    # Collapse 3+ consecutive blank lines to 2
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _heading_matches(body_line: str, heading: str) -> bool:
    """Return True if *body_line* begins with *heading* (case-insensitive).

    Compares using the first 40 characters of *heading* to tolerate minor
    formatting differences between TOC text and body headings.

    Args:
        body_line: A stripped line from the schedule body.
        heading:   The heading text to search for (stripped).

    Returns:
        True if the body line starts with the first 40 chars of *heading*.
    """
    b = body_line.strip().lower()
    h = heading.strip().lower()
    prefix = h[:40]
    return b.startswith(prefix)


# ---------------------------------------------------------------------------
# Section-boundary helpers
# ---------------------------------------------------------------------------


def _get_section_end(code: str, offsets: dict[str, int], n_lines: int) -> int:
    """Return the 0-based line index where a schedule's section ends.

    For sub-schedules (22A/B/C, 51A/B, 61A/B) this delegates to the parent.
    For top-level schedules, the section ends at the start of the next schedule
    in the offset map that is not an internal sub-section marker (e.g. 74A–74D).

    Args:
        code:     Schedule code (e.g. ``"10"``, ``"22A"``).
        offsets:  Dict from :func:`~pdf_extraction.load_schedule_offsets`.
        n_lines:  Total number of lines in the text file (fallback for the
                  last schedule in the file).

    Returns:
        0-based exclusive end line index.
    """
    if code in SUB_SCHEDULE_PARENTS:
        parent = SUB_SCHEDULE_PARENTS[code]
        return _get_section_end(parent, offsets, n_lines)

    sorted_codes = sorted(offsets.keys(), key=lambda k: offsets[k])
    try:
        idx = sorted_codes.index(code)
    except ValueError:
        return n_lines

    for next_code in sorted_codes[idx + 1 :]:
        if next_code not in _INTERNAL_OFFSET_KEYS:
            return offsets[next_code]

    return n_lines


def _find_body_start(lines: list[str], section_start: int, section_end: int) -> int:
    """Return the 0-based line where the schedule body begins.

    The body starts at the first line that matches ``SCHEDULE XX:`` without
    dot leaders (i.e. the schedule title in the body, not the TOC).

    Args:
        lines:          All lines from the text file.
        section_start:  0-based start of this schedule's section.
        section_end:    0-based exclusive end of this schedule's section.

    Returns:
        0-based line index of the body title, or *section_start* if not found.
    """
    for i in range(section_start, section_end):
        line = lines[i]
        if _SCHEDULE_BODY_TITLE_RE.match(line.strip()) and not _has_dot_leaders(line):
            # Verify this is the body, not the first line of a multi-line TOC entry
            # (where dot leaders appear on the following non-blank line).
            is_toc_entry = False
            for j in range(i + 1, min(i + 5, section_end)):
                next_stripped = lines[j].strip()
                if next_stripped:
                    if _has_dot_leaders(next_stripped):
                        is_toc_entry = True
                    break
            if not is_toc_entry:
                return i
    return section_start


# ---------------------------------------------------------------------------
# TOC parsing
# ---------------------------------------------------------------------------


def _parse_toc(
    lines: list[str], section_start: int, body_start: int
) -> tuple[str | None, str | None]:
    """Parse the Table of Contents between *section_start* and *body_start*.

    Extracts the schedule name from the first TOC entry (the top-level entry
    with the schedule code) and finds the heading of the section immediately
    following "General Information" / "General Instructions" at the same or
    lower TOC indent level.

    Multi-line TOC entries (where dot leaders appear on a continuation line)
    are handled by joining the entry text found before the dot-leader line.

    Args:
        lines:         All lines from the text file.
        section_start: 0-based start of this schedule's section.
        body_start:    0-based start of the body (first ``SCHEDULE XX:`` line).

    Returns:
        A tuple ``(schedule_name, next_section_heading)`` where either may be
        ``None`` if not found.  ``schedule_name`` is the text after the schedule
        code in the first TOC entry; ``next_section_heading`` is the stripped
        text of the TOC entry that follows "General Information" at the same or
        lower indent.
    """
    # Collect TOC entries: (stripped_text, indent, line_index)
    toc_entries: list[tuple[str, int, int]] = []
    pending_text = ""
    pending_indent = 0

    for i in range(section_start, body_start):
        line = lines[i]
        if _is_page_header(line):
            pending_text = ""
            continue
        stripped = line.rstrip()
        if not stripped:
            pending_text = ""
            continue

        if _has_dot_leaders(stripped):
            # This line ends the current entry
            entry_text = (
                (pending_text + " " + _strip_dot_leaders(stripped)).strip()
                if pending_text
                else _strip_dot_leaders(stripped)
            )
            indent = _count_leading_spaces(
                stripped if not pending_text else pending_text
            )
            toc_entries.append((entry_text, indent, i))
            pending_text = ""
        else:
            # Possible continuation line for a multi-line TOC entry
            content = stripped.strip()
            if content:  # pragma: no cover
                if not pending_text:
                    pending_indent = _count_leading_spaces(stripped)
                    pending_text = content
                else:
                    pending_text += " " + content

    if not toc_entries:
        return None, None

    # Schedule name: first TOC entry is the schedule title
    schedule_name: str | None = None
    first_entry_text = toc_entries[0][0]
    m = _SCHEDULE_BODY_TITLE_RE.match(first_entry_text)
    if m:
        # Strip "SCHEDULE XX: " prefix
        schedule_name = re.sub(
            r"^SCHEDULE\s+[\w][\w\s]*?:\s*", "", first_entry_text, flags=re.IGNORECASE
        ).strip()

    # Find "General Information" or "General Instructions" entry
    gi_idx: int | None = None
    gi_indent: int | None = None
    for idx, (entry_text, indent, _line) in enumerate(toc_entries):
        lower = entry_text.lower()
        if lower.startswith("general information") or lower.startswith(
            "general instructions"
        ):
            gi_idx = idx
            gi_indent = indent
            break

    if gi_idx is None:
        return schedule_name, None

    # Find the next entry at the same or lower (less indented) level
    next_section: str | None = None
    assert gi_indent is not None
    for entry_text, indent, _line in toc_entries[gi_idx + 1 :]:
        if indent <= gi_indent:
            next_section = entry_text
            break

    return schedule_name, next_section


# ---------------------------------------------------------------------------
# Description extraction
# ---------------------------------------------------------------------------


def _find_gi_heading(lines: list[str], start: int, end: int) -> int | None:
    """Find the "General Information" or "General Instructions" heading in body.

    Scans lines in [*start*, *end*) for a line that is exactly (stripped)
    ``"General Information"`` or ``"General Instructions"``.

    Args:
        lines: All lines from the text file.
        start: 0-based start of search range.
        end:   0-based exclusive end of search range.

    Returns:
        0-based line index of the heading, or ``None`` if not found.
    """
    for i in range(start, end):
        s = lines[i].strip()
        lower = s.lower()
        if lower in ("general information", "general instructions"):
            return i
    return None


def _extract_description_two_pass(
    lines: list[str],
    gi_line: int,
    next_section: str | None,
    section_end: int,
) -> str:
    """Extract the General Information description using a two-pass algorithm.

    **Pass 1** — page-boundary scan: Scans forward from *gi_line* tracking
    page-header lines.  When the first non-blank content line after a page
    header matches *next_section*, the description is truncated at the page
    header (inclusive).  This prevents false positives where *next_section*
    appears as an embedded reference *within* the GI text (e.g. "Schedule 74A"
    mentioned inside Schedule 74's GI) before the actual new section starts.

    **Pass 2** — unrestricted scan (fallback): Scans forward from *gi_line*
    stopping at the first non-blank line that starts with *next_section*,
    regardless of whether it follows a page header.  Used for schedules where
    the next section begins mid-page (e.g. "Carry Forwards" in Schedule 10).

    If *next_section* is ``None``, all content to *section_end* is returned.

    Args:
        lines:        All lines from the text file.
        gi_line:      0-based line of the GI heading (content starts at gi_line+1).
        next_section: Text of the next section heading (from the TOC), stripped.
        section_end:  0-based exclusive upper bound for scanning.

    Returns:
        Cleaned description string.
    """
    if next_section is None:
        return _clean_text(lines[gi_line + 1 : section_end])

    # ---- Pass 1: stop only if next_section is first content after a page header ----
    pending_header: int | None = None
    stop_idx: int | None = None

    for i in range(gi_line + 1, section_end):
        line = lines[i]
        if _is_page_header(line):
            pending_header = i
            continue
        if pending_header is not None and line.strip():
            # First non-blank line after a page header
            if _heading_matches(line, next_section):
                stop_idx = pending_header
                break
            pending_header = None  # Not the target; reset and continue

    if stop_idx is not None:
        return _clean_text(lines[gi_line + 1 : stop_idx])

    # ---- Pass 2: stop at first occurrence of next_section anywhere ----
    for i in range(gi_line + 1, section_end):
        if _is_page_header(lines[i]):
            continue
        if lines[i].strip() and _heading_matches(lines[i], next_section):
            return _clean_text(lines[gi_line + 1 : i])

    # Fallback: return everything to section end
    return _clean_text(lines[gi_line + 1 : section_end])


def _extract_schedule_name_from_body(
    lines: list[str], body_start: int, section_end: int
) -> str:
    """Extract the schedule name from the body title line(s).

    Finds the ``SCHEDULE XX: …`` line in the body and collects the name text
    (including any continuation lines) until a blank line is encountered.

    Args:
        lines:       All lines from the text file.
        body_start:  0-based index of the first ``SCHEDULE XX:`` line in the body.
        section_end: 0-based exclusive end of the section.

    Returns:
        The schedule name string (multi-line names are joined with a space).
    """
    line = lines[body_start].rstrip()
    # Strip "SCHEDULE XX: " prefix
    name_part = re.sub(
        r"^SCHEDULE\s+[\w][\w\s]*?:\s*", "", line.strip(), flags=re.IGNORECASE
    ).strip()

    name_parts = [name_part] if name_part else []

    # Collect continuation lines until blank, page header, or GI heading
    for i in range(body_start + 1, section_end):
        next_line = lines[i].rstrip()
        stripped = next_line.strip()
        if not stripped:
            break
        if _is_page_header(next_line):
            break
        if _SCHEDULE_BODY_TITLE_RE.match(stripped):
            break
        lower = stripped.lower()
        if lower in ("general information", "general instructions"):
            break
        name_parts.append(stripped)

    return " ".join(name_parts)


# ---------------------------------------------------------------------------
# Per-schedule extractors
# ---------------------------------------------------------------------------


def _extract_regular_schedule(
    lines: list[str], offsets: dict[str, int], code: str
) -> dict[str, Any]:
    """Extract metadata for a schedule that has a TOC and General Information section.

    Handles the common case: find the TOC, parse it for schedule name and next
    section heading, locate the GI heading in the body, and extract the
    description using the two-pass algorithm.

    Args:
        lines:   All lines from the text file.
        offsets: Schedule offset map from :func:`~pdf_extraction.load_schedule_offsets`.
        code:    Schedule code to extract (must be a key in *offsets*).

    Returns:
        Dict with keys: ``schedule``, ``schedule_name``, ``category``,
        ``description``, ``valid_from_year``, ``valid_to_year``, ``change_notes``.
    """
    section_start = offsets[code]
    section_end = _get_section_end(code, offsets, len(lines))
    body_start = _find_body_start(lines, section_start, section_end)

    schedule_name_toc, next_section = _parse_toc(lines, section_start, body_start)
    schedule_name = _extract_schedule_name_from_body(lines, body_start, section_end)
    if not schedule_name:
        schedule_name = schedule_name_toc or ""

    gi_line = _find_gi_heading(lines, body_start, section_end)
    if gi_line is None:
        description = ""
    else:
        description = _extract_description_two_pass(
            lines, gi_line, next_section, section_end
        )

    return {
        "schedule": code,
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES.get(code, ""),
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_schedule_53(lines: list[str], offsets: dict[str, int]) -> dict[str, Any]:
    """Extract metadata for Schedule 53 (no General Information heading).

    Schedule 53 has no "General Information" or "General Instructions" section
    in the body.  The description is the first substantive paragraph, located
    after the schedule body title and before the first line-specific description
    (``Line XXXX …``).

    Args:
        lines:   All lines from the text file.
        offsets: Schedule offset map.

    Returns:
        Metadata dict for Schedule 53.
    """
    section_start = offsets["53"]
    section_end = _get_section_end("53", offsets, len(lines))
    body_start = _find_body_start(lines, section_start, section_end)

    schedule_name = _extract_schedule_name_from_body(lines, body_start, section_end)

    # Skip past the body title line and its multi-line continuation (i.e. everything
    # up to and including the first blank line after the title), then collect
    # paragraph text until the first line-specific description ("Line XXXX …").
    _line_heading_re = re.compile(r"^Line\s+\d{4}", re.IGNORECASE)
    desc_lines: list[str] = []
    past_title_blank = False  # True once we've passed the blank after the body title

    for i in range(body_start, section_end):
        line = lines[i]
        if _is_page_header(line):
            continue
        s = line.strip()

        if not past_title_blank:
            # Skip the body title and its continuation lines until blank
            if _SCHEDULE_BODY_TITLE_RE.match(s):
                continue  # Skip "SCHEDULE 53: ..." title line
            if not s:
                past_title_blank = True  # Hit the blank that ends the title block
            continue  # Skip all lines (including title continuations) until blank

        # We are past the title blank; collect until "Line XXXX"
        if _line_heading_re.match(s):
            break
        if not s:
            if desc_lines:
                desc_lines.append("")
            continue
        desc_lines.append(s)

    description = _clean_text(desc_lines)

    return {
        "schedule": "53",
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES["53"],
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_schedule_74e(lines: list[str], offsets: dict[str, int]) -> dict[str, Any]:
    """Extract metadata for Schedule 74E (no TOC, no General Information heading).

    Schedule 74E begins with a form-feed-style page within Schedule 74's section.
    The description consists of the paragraphs that appear after the
    "Asset Retirement Obligation Liability" heading and before the first
    "Column N -" description.

    Args:
        lines:   All lines from the text file.
        offsets: Schedule offset map.

    Returns:
        Metadata dict for Schedule 74E.
    """
    section_start = offsets["74E"]
    section_end = _get_section_end("74E", offsets, len(lines))

    schedule_name = "Asset Retirement Obligation Liability"
    _aro_heading = "Asset Retirement Obligation Liability"
    _column_re = re.compile(r"^Column\s+\d+", re.IGNORECASE)

    # Find the "Asset Retirement Obligation Liability" heading
    aro_line: int | None = None
    for i in range(section_start, section_end):
        if lines[i].strip() == _aro_heading:
            aro_line = i
            break

    if aro_line is None:
        return {
            "schedule": "74E",
            "schedule_name": schedule_name,
            "category": SCHEDULE_CATEGORIES["74E"],
            "description": "",
            "valid_from_year": None,
            "valid_to_year": None,
            "change_notes": None,
        }

    # Collect content from after the heading until first "Column N -" heading
    desc_lines: list[str] = []
    for i in range(aro_line + 1, section_end):
        line = lines[i]
        if _is_page_header(line):
            continue
        s = line.strip()
        if _column_re.match(s):
            break
        desc_lines.append(line.rstrip())

    description = _clean_text(desc_lines)

    return {
        "schedule": "74E",
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES["74E"],
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_sub_schedule(
    lines: list[str], offsets: dict[str, int], code: str
) -> dict[str, Any]:
    """Extract metadata for a sub-schedule (22A/B/C, 51A/B, 61A/B).

    Sub-schedules do not have their own entries in the offset map; their
    content is embedded within the parent schedule's section.  This function
    locates the sub-schedule's section heading in the parent body and
    extracts content until the next sub-schedule or a known stopping heading.

    Args:
        lines:   All lines from the text file.
        offsets: Schedule offset map.
        code:    Sub-schedule code (must be a key in :data:`SUB_SCHEDULE_PARENTS`).

    Returns:
        Metadata dict for the sub-schedule.
    """
    parent = SUB_SCHEDULE_PARENTS[code]
    parent_start = offsets[parent]
    section_end = _get_section_end(parent, offsets, len(lines))
    parent_body_start = _find_body_start(lines, parent_start, section_end)

    sub_heading_prefix = _SUB_SCHEDULE_HEADINGS[code]
    next_heading = _SUB_SCHEDULE_NEXT_HEADINGS[code]

    # Locate the sub-schedule heading within the parent body
    heading_line: int | None = None
    for i in range(parent_body_start, section_end):
        if _is_page_header(lines[i]):
            continue
        if _heading_matches(lines[i], sub_heading_prefix):
            heading_line = i
            break

    if heading_line is None:
        return {
            "schedule": code,
            "schedule_name": sub_heading_prefix,
            "category": SCHEDULE_CATEGORIES.get(code, ""),
            "description": "",
            "valid_from_year": None,
            "valid_to_year": None,
            "change_notes": None,
        }

    # Schedule name from the heading line (strip "Schedule XX:" prefix or code suffix)
    raw_heading = lines[heading_line].strip()
    schedule_name = _extract_sub_schedule_name(raw_heading, code)

    # Find stop line
    stop_line = section_end
    if next_heading is not None:
        for i in range(heading_line + 1, section_end):
            if _is_page_header(lines[i]):
                continue
            if lines[i].strip() and _heading_matches(lines[i], next_heading):
                stop_line = i
                break

    description = _clean_text(lines[heading_line + 1 : stop_line])

    return {
        "schedule": code,
        "schedule_name": schedule_name,
        "category": SCHEDULE_CATEGORIES.get(code, ""),
        "description": description,
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }


def _extract_sub_schedule_name(heading: str, code: str) -> str:
    """Derive a clean schedule_name from a sub-schedule section heading.

    Strips a leading ``"Schedule XX:"`` prefix or a trailing ``"(XX)"`` code
    suffix so the name is human-readable without the schedule code.

    Args:
        heading: The raw heading text from the body.
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
# Top-level extraction
# ---------------------------------------------------------------------------


def extract_schedule_record(
    lines: list[str], offsets: dict[str, int], code: str
) -> dict[str, Any]:
    """Extract one metadata record for a given schedule code.

    Dispatches to the appropriate extractor based on the code:

    - Sub-schedules (22A/B/C, 51A/B, 61A/B): :func:`_extract_sub_schedule`
    - Schedule 53 (no GI heading): :func:`_extract_schedule_53`
    - Schedule 74E (no TOC): :func:`_extract_schedule_74e`
    - All others: :func:`_extract_regular_schedule`

    Args:
        lines:   All lines from the text file (``readlines()`` output).
        offsets: Schedule offset map from
                 :func:`~pdf_extraction.load_schedule_offsets`.
        code:    Schedule code to extract.

    Returns:
        Dict with keys ``schedule``, ``schedule_name``, ``category``,
        ``description``, ``valid_from_year``, ``valid_to_year``,
        ``change_notes``.
    """
    if code in SUB_SCHEDULE_PARENTS:
        return _extract_sub_schedule(lines, offsets, code)
    if code == "53":
        return _extract_schedule_53(lines, offsets)
    if code == "74E":
        return _extract_schedule_74e(lines, offsets)
    return _extract_regular_schedule(lines, offsets, code)


def extract_all_schedule_meta(
    txt_path: str | Path,
    offsets_path: str | Path,
) -> list[dict[str, Any]]:
    """Extract metadata records for all 31 schedule codes from FIR2025.

    Opens the pre-converted text file, loads the offset map, and extracts one
    record per schedule code in :data:`SCHEDULE_CATEGORIES`.

    Args:
        txt_path:     Path to ``FIR2025 Instructions.txt``.
        offsets_path: Path to ``FIR2025 Instructions.offsets.json``.

    Returns:
        List of 31 dicts, one per schedule code, ordered by the key set of
        :data:`SCHEDULE_CATEGORIES`.
    """
    with open(txt_path, encoding="utf-8") as fh:
        lines = fh.readlines()

    offsets = load_schedule_offsets(str(offsets_path))

    records: list[dict[str, Any]] = []
    for code in SCHEDULE_CATEGORIES:
        record = extract_schedule_record(lines, offsets, code)
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
    txt_path: Path = typer.Option(
        _DEFAULT_TXT_PATH,
        help="Path to FIR2025 Instructions.txt",
    ),
    offsets_path: Path = typer.Option(
        _DEFAULT_OFFSETS_PATH,
        help="Path to FIR2025 Instructions.offsets.json",
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

    Reads the pre-converted text file and offset map, extracts one metadata
    record per schedule code, exports to CSV for verification, and optionally
    inserts into ``fir_schedule_meta``.
    """
    typer.echo(f"Extracting schedule metadata from {txt_path}...")
    records = extract_all_schedule_meta(txt_path, offsets_path)
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
