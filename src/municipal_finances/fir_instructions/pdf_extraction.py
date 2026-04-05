"""PDF text extraction utilities for FIR instruction PDFs.

This module supports the prerequisite step for schedule metadata extraction.
It provides helpers to work with pre-converted ``.txt`` files (produced by
``pdftotext -layout``) and to build page-offset maps so downstream extractors
can jump directly to a schedule's section without re-scanning the full file.

Usage — one-time setup per PDF::

    # Convert PDFs to text (run once in the project root)
    # for f in fir_instructions/source_files/*.pdf; do
    #     pdftotext -layout "$f" "${f%.pdf}.txt"
    # done

    from municipal_finances.fir_instructions.pdf_extraction import (
        build_schedule_offsets,
        save_schedule_offsets,
    )

    offsets = build_schedule_offsets("fir_instructions/source_files/FIR2025 Instructions.txt")
    save_schedule_offsets(offsets, "fir_instructions/source_files/FIR2025 Instructions.offsets.json")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Footer / header patterns
# ---------------------------------------------------------------------------

# FIR2025 uses a "Page |N  Schedule {code}" header on each page, e.g.:
#   "FIR2025             Page |1           Schedule 10"
_PAGE1_HEADER_2025 = re.compile(
    r"FIR\d{4}\s+Page \|1\s+Schedule\s+(\w+)\s*$"
)

# FIR2019–2024 use a footer of the form "{code} - N" at the end of each page, e.g.:
#   "FIR2022   Schedule 10   Statement of Operations: Revenue   10 - 1"
# We match page 1 only (suffix "- 1").  group(1) is the schedule code from the
# header; group(2) is the code in the trailing "{code} - 1" suffix.  Only rows
# where both groups are equal indicate a genuine first-page footer.
_PAGE1_FOOTER_OLD = re.compile(
    r"FIR\d{4}\s+Schedule\s+(\w+).*\s+(\w+)\s*-\s*1\s*$"
)

# Some schedules in FIR2025 begin with a form-feed character instead of a
# dedicated "Page |1" header (e.g. Schedule 74E).
_FF_SCHEDULE = re.compile(r"^\x0cSchedule\s+(\w+)\s*$")

# Extract the FIR year from a filename like "FIR2025 Instructions.txt"
_YEAR_FROM_STEM = re.compile(r"FIR(\d{4})")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_schedule_offsets(txt_path: str) -> dict[str, int]:
    """Return ``{schedule_code: line_number}`` for each schedule section found.

    Scans the plain-text file produced by ``pdftotext -layout`` and detects
    the first page of each schedule section using page-header / footer patterns
    that differ across FIR years:

    - **FIR2025**: ``"FIR2025  Page |1  Schedule {code}"`` header on the first
      page of each section.
    - **FIR2019–2024**: ``"FIR{year}  Schedule {code}  …  {code} - 1"`` footer
      at the bottom of the first page of each section.

    For schedules that begin with a form-feed character (``\\x0c``) instead of a
    recognised header/footer (e.g. Schedule 74E in FIR2025), the form-feed line
    is used as the offset if no earlier entry for that code exists.

    The returned line numbers are 0-based indices into the list of lines in the
    file.  They point to the page boundary line nearest to the start of the
    section content; extraction code should read forward from this position.

    Args:
        txt_path: Path to a ``.txt`` file produced by ``pdftotext -layout``,
                  e.g. ``"fir_instructions/source_files/FIR2025 Instructions.txt"``.

    Returns:
        Dict mapping schedule codes (e.g. ``"10"``, ``"74E"``, ``"80D"``) to
        0-based line numbers.  May include internal sub-section markers such as
        ``"74A"`` through ``"74D"`` that appear as form-feed sections within a
        parent schedule's instructions.
    """
    path = Path(txt_path)
    year_m = _YEAR_FROM_STEM.search(path.stem)
    year = int(year_m.group(1)) if year_m else None

    offsets: dict[str, int] = {}

    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()

    for i, line in enumerate(lines):
        stripped = line.strip()

        if year == 2025:
            m = _PAGE1_HEADER_2025.search(stripped)
            if m:
                code = m.group(1)
                if code not in offsets:
                    offsets[code] = i
        else:
            m = _PAGE1_FOOTER_OLD.search(stripped)
            if m and m.group(1) == m.group(2):
                code = m.group(1)
                if code not in offsets:
                    offsets[code] = i

        # Form-feed section starts — supplement header/footer detection
        ff_m = _FF_SCHEDULE.match(line)
        if ff_m:
            code = ff_m.group(1)
            if code not in offsets:
                offsets[code] = i

    return offsets


def save_schedule_offsets(offsets: dict[str, int], json_path: str) -> None:
    """Write a schedule offset map to a JSON file.

    Creates parent directories as needed.  Any existing file is overwritten.

    Args:
        offsets:  Dict produced by :func:`build_schedule_offsets`.
        json_path: Destination path (e.g.
                   ``"fir_instructions/source_files/FIR2025 Instructions.offsets.json"``).
    """
    out = Path(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(offsets, fh, indent=2, sort_keys=True)


def load_schedule_offsets(json_path: str) -> dict[str, int]:
    """Load a schedule offset map from a previously saved JSON file.

    Args:
        json_path: Path to a JSON file written by :func:`save_schedule_offsets`.

    Returns:
        Dict mapping schedule codes to 0-based line numbers.
    """
    with open(json_path, encoding="utf-8") as fh:
        return {k: int(v) for k, v in json.load(fh).items()}
