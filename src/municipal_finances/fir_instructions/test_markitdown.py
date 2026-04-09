from pathlib import Path

from markitdown import MarkItDown


def convert_pdf(pdf_path: Path):
    md = MarkItDown()
    result = md.convert(pdf_path)
    output_path = pdf_path.with_suffix(".md")
    with output_path.open("w") as f:
        f.write(result.text_content)


if __name__ == "__main__":
    convert_pdf(Path("fir_instructions/source_files/2025/FIR2025 S40.pdf"))
