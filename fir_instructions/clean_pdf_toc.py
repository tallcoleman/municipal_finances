"""
clean_pdf_toc.py — Remove non-functional TOC entries from a PDF.

When a PDF is extracted from a larger document, the table of contents is often
inherited wholesale. Entries that pointed to pages outside the extracted range
get their destinations clamped to a fallback page, so their bookmarks no longer
navigate to meaningful content.

This script detects non-functional entries by checking whether the TOC entry
title text actually appears near the destination coordinate on the destination
page. Entries whose title cannot be found near the bookmark target are removed.
Parent entries are also removed if none of their descendants are functional.

Usage:
    uv run fir_instructions/clean_pdf_toc.py <input.pdf> <output.pdf>
"""

import re
import sys
from pathlib import Path

import pymupdf


# ---------------------------------------------------------------------------
# Destination resolution
# ---------------------------------------------------------------------------

_DEST_XYZ_RE = re.compile(
    r"/Dest\s*\[\s*(\d+)\s+0\s+R\s*/XYZ\s+([\d.]+)\s+([\d.]+)"
)
_DEST_FITH_RE = re.compile(r"/Dest\s*\[\s*(\d+)\s+0\s+R\s*/FitH\s+([\d.]+)")
_DEST_FITV_RE = re.compile(r"/Dest\s*\[\s*(\d+)\s+0\s+R\s*/FitV\s+([\d.]+)")
_DEST_FIT_RE = re.compile(r"/Dest\s*\[\s*(\d+)\s+0\s+R\s*/Fit\b")


def _resolve_dest(doc: pymupdf.Document, xref: int, page_xref_map: dict) -> tuple:
    """Return (page_idx, pymupdf.Point) for an outline item xref, or (None, None)."""
    obj = doc.xref_object(xref)
    if not obj:
        return None, None

    # /XYZ x y zoom — most common
    m = _DEST_XYZ_RE.search(obj)
    if m:
        dest_xref = int(m.group(1))
        page_idx = page_xref_map.get(dest_xref)
        if page_idx is None:
            return None, None
        pdf_x, pdf_y = float(m.group(2)), float(m.group(3))
        page_h = doc[page_idx].rect.height
        return page_idx, pymupdf.Point(pdf_x, max(0.0, page_h - pdf_y))

    # /FitH top — scroll to top edge at given y
    m = _DEST_FITH_RE.search(obj)
    if m:
        dest_xref = int(m.group(1))
        page_idx = page_xref_map.get(dest_xref)
        if page_idx is None:
            return None, None
        pdf_y = float(m.group(2))
        page_h = doc[page_idx].rect.height
        return page_idx, pymupdf.Point(0.0, max(0.0, page_h - pdf_y))

    # /FitV left — scroll to left edge at given x; use top of page
    m = _DEST_FITV_RE.search(obj)
    if m:
        dest_xref = int(m.group(1))
        page_idx = page_xref_map.get(dest_xref)
        if page_idx is None:
            return None, None
        return page_idx, pymupdf.Point(0.0, 0.0)

    # /Fit — fit whole page; use top of page
    m = _DEST_FIT_RE.search(obj)
    if m:
        dest_xref = int(m.group(1))
        page_idx = page_xref_map.get(dest_xref)
        if page_idx is None:
            return None, None
        return page_idx, pymupdf.Point(0.0, 0.0)

    return None, None


# ---------------------------------------------------------------------------
# Text-based validity check
# ---------------------------------------------------------------------------

def _significant_words(title: str) -> list[str]:
    """Extract lowercase words that are meaningful enough to match against."""
    words = []
    for token in re.findall(r"[A-Za-z0-9]+", title):
        # Keep tokens that are either:
        #   - alphabetic and longer than 3 characters  (skips "of", "the", etc.)
        #   - digit sequences longer than 2 characters (line codes like "0420")
        if token.isdigit():
            if len(token) > 2:
                words.append(token.lower())
        elif token.isalpha():
            if len(token) > 3:
                words.append(token.lower())
        else:
            # Alphanumeric mix (e.g. "FIR2025", "S71") — keep if > 2 chars
            if len(token) > 2:
                words.append(token.lower())
    return words


def _title_found_near(
    page: pymupdf.Page,
    point: pymupdf.Point,
    title: str,
    above: float = 30.0,
    below: float = 140.0,
    match_threshold: float = 0.35,
) -> bool:
    """Return True if enough title words appear in the text band around `point`.

    The search band extends `above` points above and `below` points below the
    destination coordinate (in PyMuPDF top-left origin space).
    """
    words = _significant_words(title)
    if not words:
        return True  # nothing to check — assume valid

    y_top = max(0.0, point.y - above)
    y_bottom = min(page.rect.height, point.y + below)
    clip = pymupdf.Rect(0, y_top, page.rect.width, y_bottom)
    text = page.get_text("text", clip=clip).lower()

    matched = sum(1 for w in words if w in text)
    return (matched / len(words)) >= match_threshold


def _check_direct(
    doc: pymupdf.Document,
    toc: list,
    page_xref_map: dict,
    threshold: float = 0.7,
    above: float = 20.0,
    below: float = 120.0,
) -> list[bool]:
    """Return a bool list marking entries whose title text matches near the destination."""
    flags = []
    for entry in toc:
        xref = entry[3].get("xref", 0) if len(entry) > 3 else 0
        if not xref:
            flags.append(False)
            continue
        page_idx, point = _resolve_dest(doc, xref, page_xref_map)
        if page_idx is None:
            flags.append(False)
            continue
        flags.append(
            _title_found_near(
                doc[page_idx],
                point,
                entry[1],
                above=above,
                below=below,
                match_threshold=threshold,
            )
        )
    return flags


# ---------------------------------------------------------------------------
# Main cleaning logic
# ---------------------------------------------------------------------------

def _build_valid_flags(
    doc: pymupdf.Document,
    toc: list,
    page_xref_map: dict,
) -> list[bool]:
    """Return a bool list: True if the entry is functional, False otherwise.

    An entry is functional if its title text is found near its destination
    coordinate on the destination page.  Parent entries are also kept when at
    least one descendant is functional (even if the parent itself does not
    match), so the hierarchy remains intact.
    """
    n = len(toc)
    direct = _check_direct(doc, toc, page_xref_map)

    # Propagate: a parent is kept if any descendant passes.
    # Walk backwards: when we find a kept entry, mark its nearest ancestor at
    # each level above it.  The "nearest ancestor" of a level-L entry is the
    # closest preceding entry with level < L.
    keep = list(direct)
    for i in range(n - 1, -1, -1):
        if not keep[i]:
            continue
        current_level = toc[i][0]
        for j in range(i - 1, -1, -1):
            entry_level = toc[j][0]
            if entry_level < current_level:
                keep[j] = True
                current_level = entry_level
            if current_level == 1:
                break  # reached the top level; no further ancestors possible

    return keep


def _adjust_levels(toc: list) -> list:
    """Ensure level numbers are contiguous (no child skips more than one level)."""
    result = []
    prev_level = 0
    for entry in toc:
        lvl = entry[0]
        # Clamp: cannot be deeper than prev_level + 1
        adjusted = min(lvl, prev_level + 1)
        adjusted = max(adjusted, 1)
        new_entry = list(entry)
        new_entry[0] = adjusted
        result.append(new_entry)
        prev_level = adjusted
    return result


def clean_toc(input_path: str | Path, output_path: str | Path) -> int:
    """Remove non-functional TOC entries and write the cleaned PDF.

    Returns the number of entries retained.
    """
    doc = pymupdf.open(str(input_path))
    toc = doc.get_toc(simple=False)

    page_xref_map = {doc[i].xref: i for i in range(doc.page_count)}

    print(f"Pages: {doc.page_count}")
    print(f"TOC entries (original): {len(toc)}")

    keep_flags = _build_valid_flags(doc, toc, page_xref_map)
    filtered = [entry for entry, keep in zip(toc, keep_flags) if keep]

    # Adjust levels so no child is more than 1 level deeper than its parent
    filtered = _adjust_levels(filtered)

    print(f"TOC entries (retained): {len(filtered)}")
    for entry in filtered:
        indent = "  " * (entry[0] - 1)
        print(f"  {indent}[L{entry[0]}] {entry[1]}")

    doc.set_toc(filtered)
    doc.save(str(output_path))
    doc.close()
    print(f"\nSaved: {output_path}")
    return len(filtered)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.pdf> <output.pdf>")
        sys.exit(1)

    input_pdf = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2])

    if not input_pdf.exists():
        print(f"Error: {input_pdf} not found")
        sys.exit(1)

    clean_toc(input_pdf, output_pdf)
