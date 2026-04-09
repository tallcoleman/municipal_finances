from pathlib import Path
from typing import List

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


if __name__ == "__main__":
    convert_folder(Path("fir_instructions/source_files/2025"))
