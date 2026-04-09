from pathlib import Path
from typing import List

import pymupdf4llm as md


def convert_folder(path: Path):
    pdf_paths = path.glob("*.pdf")
    for pdf_path in pdf_paths:
        convert_pdf(pdf_path)


def convert_pdf(pdf_path: Path):
    result = md.to_markdown(
        pdf_path,
        header=False,
        footer=False,
        show_progress=True,
    )
    if isinstance(result, List):
        raise ValueError("wrong output format - list detected, should be string")
    output_path = pdf_path.parent / "pymupdf4llm" / pdf_path.with_suffix(".md").name
    with output_path.open("w") as f:
        f.write(result)


if __name__ == "__main__":
    convert_folder(Path("fir_instructions/source_files/2025"))
