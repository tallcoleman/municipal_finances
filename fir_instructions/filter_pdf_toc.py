"""
filter_pdf_toc.py — Keep only a single TOC entry and its descendants.

Given a PDF whose table of contents was inherited from a larger document,
this script strips all entries except the one whose title matches the given
string and any entries nested beneath it. The retained subtree is re-rooted
at level 1 so the hierarchy is clean.

Usage:
    uv run fir_instructions/filter_pdf_toc.py <input.pdf> <output.pdf> <"Entry Title">
"""

import sys
from pathlib import Path

import pymupdf


def _find_subtree(toc: list, title: str) -> list:
    """Return the entry matching *title* and all its descendants.

    Raises ValueError if no entry with an exact title match is found.
    """
    start_idx = next(
        (i for i, e in enumerate(toc) if e[1] == title),
        None,
    )
    if start_idx is None:
        raise ValueError(f"No TOC entry found with title: {title!r}")

    root_level = toc[start_idx][0]
    subtree = [toc[start_idx]]
    for entry in toc[start_idx + 1 :]:
        if entry[0] <= root_level:
            break
        subtree.append(entry)
    return subtree


def _reroot_levels(subtree: list) -> list:
    """Shift all levels so the root entry becomes level 1."""
    if not subtree:
        return subtree
    offset = subtree[0][0] - 1
    result = []
    for entry in subtree:
        new_entry = list(entry)
        new_entry[0] = entry[0] - offset
        result.append(new_entry)
    return result


def filter_toc(input_path: str | Path, output_path: str | Path, title: str) -> int:
    """Keep only *title* and its descendants; write the result to *output_path*.

    Returns the number of TOC entries retained.
    """
    doc = pymupdf.open(str(input_path))
    toc = doc.get_toc(simple=False)

    print(f"Pages: {doc.page_count}")
    print(f"TOC entries (original): {len(toc)}")

    subtree = _find_subtree(toc, title)
    subtree = _reroot_levels(subtree)

    print(f"TOC entries (retained): {len(subtree)}")
    for entry in subtree:
        indent = "  " * (entry[0] - 1)
        print(f"  {indent}[L{entry[0]}] {entry[1]}")

    doc.set_toc(subtree)
    doc.save(str(output_path))
    doc.close()
    print(f"\nSaved: {output_path}")
    return len(subtree)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <input.pdf> <output.pdf> <entry-title>")
        sys.exit(1)

    input_pdf = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2])
    entry_title = sys.argv[3]

    if not input_pdf.exists():
        print(f"Error: {input_pdf} not found")
        sys.exit(1)

    filter_toc(input_pdf, output_pdf, entry_title)
