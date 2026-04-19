import re
from pathlib import Path
from typing import List

import pymupdf
import pymupdf4llm as md
import typer

app = typer.Typer()


@app.command()
def convert_folder(path: Path, output_folder: str = "markdown"):
    """Converts all PDF documents in the specified folder to markdown files using pymupdf4llm. Does not convert any PDFs in sub-folders.

    By default, will save the markdown files in a subdirectory `markdown/`, but this can be changed with the `--output-folder` option. (Add `--output-folder=""` to save in same directory.)
    """
    pdf_paths = [*path.glob("*.pdf")]
    print(
        f"Found {len(pdf_paths)} PDFs to convert. Markdown files will be saved in {path / output_folder}."
    )
    for pdf_path in pdf_paths:
        convert_pdf(pdf_path, output_folder=output_folder)


@app.command()
def convert_pdf(pdf_path: Path, output_folder: str = "markdown"):
    """Converts the specified PDF document to markdown using pymupdf4llm.

    By default, will save the markdown file in a subdirectory `markdown/`, but this can be changed with the `--output-folder` option. (Add `--output-folder=""` to save in same directory.)
    """
    result = md.to_markdown(
        pdf_path,
        header=False,
        footer=False,
        show_progress=True,
    )
    if isinstance(result, List):
        raise ValueError("wrong output format - list detected, should be string")
    output_path = pdf_path.parent / output_folder / pdf_path.with_suffix(".md").name
    output_path.parent.mkdir(exist_ok=True, parents=True)
    with output_path.open("w") as f:
        f.write(result)


def _normalize(s: str) -> str:
    """Normalize whitespace in a string for TOC title matching."""
    return re.sub(r"\s+", " ", s).strip()


def _build_toc_level_map(pdf_path: Path) -> dict[str, int]:
    """Return a mapping of {normalized_title: markdown_heading_level} from the PDF's TOC.

    TOC level N maps to markdown heading level N+1 (e.g. TOC level 1 → ## which is
    markdown heading level 2). Titles are normalized by collapsing whitespace.
    """
    doc = pymupdf.open(pdf_path)
    toc = doc.get_toc()
    doc.close()
    return {_normalize(title): toc_level + 1 for toc_level, title, _ in toc}


def _fix_heading_levels(content: str, toc_map: dict[str, int]) -> str:
    """Rewrite markdown heading levels using a TOC-derived level map.

    For each heading line:
    - If the heading text matches a TOC entry, the heading marker is replaced with
      the correct number of '#' characters.
    - If the heading text does not match any TOC entry, the '#' markers are removed
      and the text (including any bold markers) is preserved as plain text.

    Non-heading lines are passed through unchanged.
    """
    result = []
    for line in content.split("\n"):
        stripped = line.rstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            raw_text = stripped[level:].strip()
            # Strip ** bold wrappers to get the plain title for TOC lookup
            inner_text = raw_text
            if inner_text.startswith("**") and inner_text.endswith("**"):
                inner_text = inner_text[2:-2].strip()
            normalized = _normalize(inner_text)
            if normalized in toc_map:
                result.append("#" * toc_map[normalized] + " " + raw_text)
            else:
                result.append(raw_text)
        else:
            result.append(line)
    return "\n".join(result)


@app.command()
def fix_pdf_headings(
    pdf_path: Path,
    input_folder: str = "markdown",
    output_folder: str = "markdown_clean",
):
    """Fix heading levels in the markdown version of a PDF using the PDF's TOC metadata.

    If a file already exists in the output folder (markdown_clean/ by default), it is
    used as the input to preserve any manual content edits. Otherwise the raw markdown
    from the input folder (markdown/ by default) is used.

    Matched headings are re-levelled to mirror the PDF's TOC hierarchy (TOC level N →
    markdown heading level N+1). Unmatched headings have their '#' markers removed and
    their text is preserved as plain text.
    """
    toc_map = _build_toc_level_map(pdf_path)
    toc_count = len(toc_map)
    if toc_count <= 1:
        typer.echo(
            typer.style(
                f"WARNING: {pdf_path.name} has only {toc_count} TOC entr{'y' if toc_count == 1 else 'ies'} — skipping.",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )
        return
    if toc_count <= 5:
        typer.echo(
            typer.style(
                f"WARNING: {pdf_path.name} has only {toc_count} TOC entries — proceeding, but results may be incomplete.",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )

    md_name = pdf_path.with_suffix(".md").name
    clean_path = pdf_path.parent / output_folder / md_name
    raw_path = pdf_path.parent / input_folder / md_name

    input_path = clean_path if clean_path.exists() else raw_path
    print(f"Reading from {input_path} ({toc_count} TOC entries)")

    content = input_path.read_text(encoding="utf-8")
    fixed = _fix_heading_levels(content, toc_map)

    clean_path.parent.mkdir(exist_ok=True, parents=True)
    clean_path.write_text(fixed, encoding="utf-8")
    print(f"Written to {clean_path}")


def _get_footer_spans(page) -> list[str]:
    """Return non-empty span texts from the bottom 15% of a page.

    Iterates text blocks whose top edge falls below 85% of the page height and
    collects every non-whitespace span text in document order.
    """
    blocks = page.get_text("dict")["blocks"]
    threshold = page.rect.height * 0.85
    spans: list[str] = []
    for block in blocks:
        if block["type"] == 0 and block["bbox"][1] > threshold:
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        spans.append(text)
    return spans


def _extract_section_from_footer(spans: list[str]) -> str | None:
    """Parse the section name from a list of footer span texts.

    Footer formats vary across FIR years (combined spans in 2019, pipe-separated
    in 2020–2021, word-split in 2022).  Joining all spans before parsing handles
    all variants uniformly.

    Returns canonical section names such as ``"Introduction"``,
    ``"Functional Classification"``, ``"Schedule 26"``, or an arbitrary section
    name for other sections.  Returns ``None`` when no ``FIR20XX`` marker is
    found.
    """
    if not spans:
        return None

    text = " ".join(spans)

    # Use the LAST FIR20XX occurrence so that footnotes containing "FIR20XX" as a
    # cross-reference (e.g. "See the FIR2022 Tables document...") do not shadow the
    # real section identifier, which always appears at the end of the footer.
    year_matches = list(re.finditer(r"FIR20\d\d", text))
    if not year_matches:
        return None
    year_match = year_matches[-1]

    after = text[year_match.end() :].strip()

    # Strip the page-ID suffix (e.g. "INTRO - 1", "26 - 14", "FUNCTIONS - 10").
    # The ID always ends with a recognisable token followed by " - <digits>".
    page_id_match = re.search(
        r"\b(?:INTRO|FUNCTIONS|\d{2,3}[A-Z]?)\s+-\s+\d+", after
    )
    section_text = after[: page_id_match.start()] if page_id_match else after
    section_text = re.sub(r"\s+", " ", section_text).strip()

    if not section_text:
        return None

    if re.match(r"Introduction\b", section_text, re.IGNORECASE):
        return "Introduction"

    if re.match(r"Functional\s+(Cla|Cat)", section_text, re.IGNORECASE):
        return "Functional Classification"

    sched_match = re.match(r"Schedule\s+(\d+[A-Z]?)", section_text, re.IGNORECASE)
    if sched_match:
        return f"Schedule {sched_match.group(1)}"

    return section_text


def _section_to_stem(section: str, year: str) -> str:
    """Convert a section name and year to an output filename stem.

    Examples::

        _section_to_stem("Schedule 26", "2019") == "FIR2019 S26"
        _section_to_stem("Schedule 80D", "2022") == "FIR2022 S80D"
        _section_to_stem("Functional Classification", "2021") == "FIR2021 Functional Categories"
        _section_to_stem("Introduction", "2020") == "FIR2020 Introduction"
    """
    sched_match = re.match(r"Schedule\s+(\d+[A-Z]?)", section, re.IGNORECASE)
    if sched_match:
        num = sched_match.group(1).upper()
        # Zero-pad bare single-digit numbers ("2" → "02"); leave "80D" unchanged.
        if re.match(r"^\d$", num):
            num = f"0{num}"
        return f"FIR{year} S{num}"

    if re.match(r"Functional\s+(Cla|Cat)", section, re.IGNORECASE):
        return f"FIR{year} Functional Categories"

    return f"FIR{year} {section}"


@app.command()
def split_pdf_by_section(
    pdf_path: Path,
    output_folder: str = "",
) -> None:
    """Split a FIR instruction PDF into one PDF per section using footer text.

    Section boundaries are detected from the footer printed on each page.
    Pages whose footer does not contain a recognisable section name (e.g. cover
    pages or informational memos) are excluded from the output.

    Schedule sections are saved as ``FIR{year} S{NN}.pdf`` (e.g.
    ``FIR2019 S26.pdf``).  Other sections use the section name verbatim
    (e.g. ``FIR2019 Introduction.pdf``), with ``Functional Classification``
    normalised to ``Functional Categories`` to match the 2023–2025 convention.

    By default the split PDFs are written to a subdirectory named after the
    detected year (e.g. ``2019/``).  Pass ``--output-folder`` to override.
    """
    year_match = re.search(r"FIR(20\d\d)", pdf_path.name)
    if not year_match:
        raise ValueError(
            f"Cannot determine year from filename: {pdf_path.name!r}. "
            "Expected a name containing 'FIR20XX'."
        )
    year = year_match.group(1)

    out_dir = pdf_path.parent / (output_folder if output_folder else year)
    out_dir.mkdir(exist_ok=True, parents=True)

    doc = pymupdf.open(pdf_path)
    sections: dict[str, list[int]] = {}
    section_order: list[str] = []

    for page_num in range(len(doc)):
        spans = _get_footer_spans(doc[page_num])
        section = _extract_section_from_footer(spans)
        if section is None:
            continue
        if section not in sections:
            sections[section] = []
            section_order.append(section)
        sections[section].append(page_num)

    written = 0
    for section in section_order:
        pages = sections[section]
        stem = _section_to_stem(section, year)
        out_path = out_dir / f"{stem}.pdf"

        out_doc = pymupdf.open()
        for page_num in pages:
            out_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        out_doc.save(out_path)
        out_doc.close()
        written += 1
        typer.echo(f"Written {stem}.pdf ({len(pages)} pages)")

    doc.close()
    typer.echo(f"Wrote {written} section PDFs to {out_dir}")


@app.command()
def count_pages(path: Path) -> None:
    """Print the page count for each PDF in a folder, then a total. Excludes subdirectories."""
    pdf_paths = sorted(path.glob("*.pdf"))
    total = 0
    for pdf_path in pdf_paths:
        doc = pymupdf.open(pdf_path)
        pages = len(doc)
        doc.close()
        print(f"{pdf_path.name}: {pages}")
        total += pages
    print(f"Total: {total} pages across {len(pdf_paths)} PDFs")


@app.command()
def fix_folder_headings(
    path: Path,
    input_folder: str = "markdown",
    output_folder: str = "markdown_clean",
):
    """Fix heading levels for all PDFs in a folder using each PDF's TOC metadata.

    Does not process PDFs in sub-folders. See fix-pdf-headings for per-file details.
    """
    pdf_paths = [*path.glob("*.pdf")]
    print(f"Found {len(pdf_paths)} PDFs to process.")
    for pdf_path in pdf_paths:
        fix_pdf_headings(
            pdf_path, input_folder=input_folder, output_folder=output_folder
        )
