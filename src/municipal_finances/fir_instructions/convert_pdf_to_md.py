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
    md_name = pdf_path.with_suffix(".md").name
    clean_path = pdf_path.parent / output_folder / md_name
    raw_path = pdf_path.parent / input_folder / md_name

    input_path = clean_path if clean_path.exists() else raw_path
    print(f"Reading from {input_path}")

    content = input_path.read_text(encoding="utf-8")
    fixed = _fix_heading_levels(content, toc_map)

    clean_path.parent.mkdir(exist_ok=True, parents=True)
    clean_path.write_text(fixed, encoding="utf-8")
    print(f"Written to {clean_path}")


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
        fix_pdf_headings(pdf_path, input_folder=input_folder, output_folder=output_folder)
