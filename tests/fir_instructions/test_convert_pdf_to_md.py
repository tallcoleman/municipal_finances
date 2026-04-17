"""Tests for fir_instructions/convert_pdf_to_md.py."""

# postpone evaluation of typing annotations
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from municipal_finances.fir_instructions.convert_pdf_to_md import (
    convert_folder,
    convert_pdf,
)

MOCK_MARKDOWN = "# FIR Instructions\n\nSome content here."


# ---------------------------------------------------------------------------
# convert_pdf
# ---------------------------------------------------------------------------


class TestConvertPdf:
    def test_creates_output_in_markdown_subdirectory(self, tmp_path: Path) -> None:
        """Output file is written to <parent>/markdown/ by default."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN):
            convert_pdf(pdf)

        out = tmp_path / "markdown" / "report.md"
        assert out.exists()
        assert out.read_text() == MOCK_MARKDOWN

    def test_creates_output_in_same_directory_when_output_folder_empty(
        self, tmp_path: Path
    ) -> None:
        """Passing output_folder='' saves the .md file beside the PDF."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN):
            convert_pdf(pdf, output_folder="")

        out = tmp_path / "report.md"
        assert out.exists()
        assert out.read_text() == MOCK_MARKDOWN

    def test_creates_output_in_custom_subdirectory(self, tmp_path: Path) -> None:
        """output_folder parameter controls the output subdirectory name."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN):
            convert_pdf(pdf, output_folder="converted")

        out = tmp_path / "converted" / "report.md"
        assert out.exists()

    def test_creates_missing_parent_directories(self, tmp_path: Path) -> None:
        """Output directory is created automatically if it does not exist."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN):
            convert_pdf(pdf, output_folder="a/b/c")

        assert (tmp_path / "a" / "b" / "c" / "report.md").exists()

    def test_raises_value_error_when_to_markdown_returns_list(
        self, tmp_path: Path
    ) -> None:
        """ValueError is raised if pymupdf4llm.to_markdown returns a list."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=["page1", "page2"]):
            with pytest.raises(ValueError, match="wrong output format"):
                convert_pdf(pdf)

    def test_passes_correct_flags_to_to_markdown(self, tmp_path: Path) -> None:
        """header=False and footer=False are passed to pymupdf4llm.to_markdown."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN) as mock_md:
            convert_pdf(pdf)

        mock_md.assert_called_once_with(
            pdf,
            header=False,
            footer=False,
            show_progress=True,
        )


# ---------------------------------------------------------------------------
# convert_folder
# ---------------------------------------------------------------------------


class TestConvertFolder:
    def test_converts_all_pdfs_in_folder(self, tmp_path: Path) -> None:
        """All PDFs in the folder are converted to markdown."""
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            (tmp_path / name).write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN):
            convert_folder(tmp_path)

        for name in ("a.md", "b.md", "c.md"):
            assert (tmp_path / "markdown" / name).exists()

    def test_does_not_convert_pdfs_in_subdirectories(self, tmp_path: Path) -> None:
        """PDFs nested inside subdirectories are not converted."""
        (tmp_path / "top.pdf").write_bytes(b"%PDF-1.4")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.pdf").write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN) as mock_md:
            convert_folder(tmp_path)

        assert mock_md.call_count == 1
        assert (tmp_path / "markdown" / "top.md").exists()
        assert not (tmp_path / "markdown" / "nested.md").exists()

    def test_empty_folder_converts_nothing(self, tmp_path: Path) -> None:
        """An empty folder results in zero conversions without error."""
        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN) as mock_md:
            convert_folder(tmp_path)

        mock_md.assert_not_called()

    def test_custom_output_folder_is_forwarded(self, tmp_path: Path) -> None:
        """output_folder parameter is passed through to each convert_pdf call."""
        (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4")

        with patch("pymupdf4llm.to_markdown", return_value=MOCK_MARKDOWN):
            convert_folder(tmp_path, output_folder="out")

        assert (tmp_path / "out" / "report.md").exists()
