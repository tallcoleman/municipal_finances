"""Tests for fir_instructions/convert_pdf_to_md.py."""

# postpone evaluation of typing annotations
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from municipal_finances.fir_instructions.convert_pdf_to_md import (
    _build_toc_level_map,
    _fix_heading_levels,
    _normalize,
    convert_folder,
    convert_pdf,
    count_pages,
    fix_folder_headings,
    fix_pdf_headings,
)

MOCK_MARKDOWN = "# FIR Instructions\n\nSome content here."


# ---------------------------------------------------------------------------
# count_pages
# ---------------------------------------------------------------------------


def _make_doc_mock(page_count: int) -> MagicMock:
    """Return a mock pymupdf document with the given page count."""
    doc = MagicMock()
    doc.__len__ = MagicMock(return_value=page_count)
    return doc


class TestCountPages:
    def test_prints_page_count_per_pdf(self, tmp_path: Path, capsys) -> None:
        """Each PDF's name and page count are printed."""
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")

        doc_a = _make_doc_mock(3)
        doc_b = _make_doc_mock(7)

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=[doc_a, doc_b],
        ):
            count_pages(tmp_path)

        out = capsys.readouterr().out
        assert "a.pdf: 3" in out
        assert "b.pdf: 7" in out

    def test_prints_total_page_count(self, tmp_path: Path, capsys) -> None:
        """A total page count is printed at the end."""
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=[_make_doc_mock(3), _make_doc_mock(7)],
        ):
            count_pages(tmp_path)

        out = capsys.readouterr().out
        assert "Total: 10 pages across 2 PDFs" in out

    def test_excludes_pdfs_in_subdirectories(self, tmp_path: Path, capsys) -> None:
        """PDFs nested in subdirectories are not counted."""
        (tmp_path / "top.pdf").write_bytes(b"%PDF-1.4")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.pdf").write_bytes(b"%PDF-1.4")

        open_mock = MagicMock(return_value=_make_doc_mock(5))
        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            open_mock,
        ):
            count_pages(tmp_path)

        assert open_mock.call_count == 1
        out = capsys.readouterr().out
        assert "nested.pdf" not in out

    def test_empty_folder(self, tmp_path: Path, capsys) -> None:
        """An empty folder prints a zero total without error."""
        open_mock = MagicMock()
        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            open_mock,
        ):
            count_pages(tmp_path)

        open_mock.assert_not_called()
        out = capsys.readouterr().out
        assert "Total: 0 pages across 0 PDFs" in out


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


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_collapses_multiple_spaces(self) -> None:
        assert _normalize("foo  bar") == "foo bar"

    def test_strips_leading_and_trailing_whitespace(self) -> None:
        assert _normalize("  hello  ") == "hello"

    def test_collapses_tabs_and_newlines(self) -> None:
        assert _normalize("foo\t\nbar") == "foo bar"

    def test_empty_string(self) -> None:
        assert _normalize("") == ""


# ---------------------------------------------------------------------------
# _fix_heading_levels
# ---------------------------------------------------------------------------


class TestFixHeadingLevels:
    def test_matched_heading_gets_correct_level(self) -> None:
        """A heading whose text is in the TOC map is re-levelled correctly."""
        toc_map = {"General Instructions": 3}
        content = "## **General Instructions**"
        result = _fix_heading_levels(content, toc_map)
        assert result == "### **General Instructions**"

    def test_matched_heading_without_bold_markers(self) -> None:
        """Headings not wrapped in ** are still matched and re-levelled."""
        toc_map = {"General Instructions": 3}
        content = "## General Instructions"
        result = _fix_heading_levels(content, toc_map)
        assert result == "### General Instructions"

    def test_unmatched_heading_has_markers_removed(self) -> None:
        """An unmatched heading loses its '#' markers; text is preserved as-is."""
        toc_map = {}
        content = "## **Table of Contents**"
        result = _fix_heading_levels(content, toc_map)
        assert result == "**Table of Contents**"

    def test_unmatched_heading_preserves_bold(self) -> None:
        """Bold markers are kept when a heading is demoted to plain text."""
        toc_map = {}
        content = "## **Some Note**"
        result = _fix_heading_levels(content, toc_map)
        assert "**Some Note**" in result
        assert result.startswith("**")

    def test_non_heading_lines_pass_through_unchanged(self) -> None:
        """Lines that do not start with '#' are returned unchanged."""
        toc_map = {"Title": 2}
        content = "This is a paragraph.\n\nAnother line."
        result = _fix_heading_levels(content, toc_map)
        assert result == content

    def test_multiline_content(self) -> None:
        """Heading and non-heading lines are each handled correctly in one pass."""
        toc_map = {"Section One": 2, "Sub-section": 3}
        content = "## **Section One**\n\nSome text.\n\n## **Sub-section**\n\n## **Unlisted**"
        result = _fix_heading_levels(content, toc_map)
        assert "## **Section One**" in result
        assert "### **Sub-section**" in result
        assert "**Unlisted**" in result
        assert "## **Unlisted**" not in result

    def test_whitespace_normalization_in_matching(self) -> None:
        """Extra whitespace in a heading title is normalized before TOC lookup."""
        toc_map = {"Section One": 3}
        content = "##  **Section  One**"
        result = _fix_heading_levels(content, toc_map)
        assert result == "### **Section  One**"


# ---------------------------------------------------------------------------
# fix_pdf_headings
# ---------------------------------------------------------------------------

MOCK_TOC = [
    [1, "Schedule 02", 1],
    [2, "General Instructions", 2],
]

MOCK_TOC_MAP = {"Schedule 02": 2, "General Instructions": 3}


def _make_pymupdf_mock(toc: list) -> MagicMock:
    """Return a mock that mimics pymupdf.open() returning a document with get_toc()."""
    doc_mock = MagicMock()
    doc_mock.get_toc.return_value = toc
    open_mock = MagicMock(return_value=doc_mock)
    return open_mock


class TestFixPdfHeadings:
    def test_reads_from_markdown_when_clean_does_not_exist(
        self, tmp_path: Path
    ) -> None:
        """Falls back to markdown/ input when no markdown_clean/ file exists."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        raw_md = tmp_path / "markdown" / "report.md"
        raw_md.write_text("## **General Instructions**\n", encoding="utf-8")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock(MOCK_TOC),
        ):
            fix_pdf_headings(pdf)

        out = tmp_path / "markdown_clean" / "report.md"
        assert out.exists()
        assert out.read_text(encoding="utf-8").startswith("###")

    def test_reads_from_markdown_clean_when_it_exists(self, tmp_path: Path) -> None:
        """Prefers markdown_clean/ as input when the file already exists there."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        (tmp_path / "markdown" / "report.md").write_text(
            "## **General Instructions** raw\n", encoding="utf-8"
        )
        (tmp_path / "markdown_clean").mkdir()
        clean_md = tmp_path / "markdown_clean" / "report.md"
        clean_md.write_text(
            "## **General Instructions** edited\n", encoding="utf-8"
        )

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock(MOCK_TOC),
        ):
            fix_pdf_headings(pdf)

        result = (tmp_path / "markdown_clean" / "report.md").read_text(encoding="utf-8")
        assert "edited" in result
        assert "raw" not in result

    def test_creates_output_directory_if_missing(self, tmp_path: Path) -> None:
        """markdown_clean/ is created automatically if it does not exist."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        (tmp_path / "markdown" / "report.md").write_text("## **Schedule 02**\n")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock(MOCK_TOC),
        ):
            fix_pdf_headings(pdf)

        assert (tmp_path / "markdown_clean" / "report.md").exists()

    def test_skips_file_when_toc_is_empty(self, tmp_path: Path, capsys) -> None:
        """Emits a warning and skips writing when the TOC has 0 entries."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        (tmp_path / "markdown" / "report.md").write_text("## **Schedule 02**\n")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock([]),
        ):
            fix_pdf_headings(pdf)

        assert not (tmp_path / "markdown_clean" / "report.md").exists()
        assert "WARNING" in capsys.readouterr().out

    def test_skips_file_when_toc_has_one_entry(self, tmp_path: Path, capsys) -> None:
        """Emits a warning and skips writing when the TOC has exactly 1 entry."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        (tmp_path / "markdown" / "report.md").write_text("## **Schedule 02**\n")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock([[1, "Schedule 02", 1]]),
        ):
            fix_pdf_headings(pdf)

        assert not (tmp_path / "markdown_clean" / "report.md").exists()
        assert "WARNING" in capsys.readouterr().out

    def test_warns_but_processes_when_toc_has_few_entries(
        self, tmp_path: Path, capsys
    ) -> None:
        """Emits a warning but still writes the file when the TOC has 2–5 entries."""
        small_toc = [[1, "Schedule 02", 1], [2, "General Instructions", 2]]
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        (tmp_path / "markdown" / "report.md").write_text("## **Schedule 02**\n")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock(small_toc),
        ):
            fix_pdf_headings(pdf)

        assert (tmp_path / "markdown_clean" / "report.md").exists()
        assert "WARNING" in capsys.readouterr().out

    def test_no_warning_when_toc_has_six_or_more_entries(
        self, tmp_path: Path, capsys
    ) -> None:
        """No warning is emitted when the TOC has 6 or more entries."""
        large_toc = [[1, f"Section {i}", i] for i in range(1, 7)]
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown").mkdir()
        (tmp_path / "markdown" / "report.md").write_text("## **Section 1**\n")

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock(large_toc),
        ):
            fix_pdf_headings(pdf)

        assert (tmp_path / "markdown_clean" / "report.md").exists()
        assert "WARNING" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# fix_folder_headings
# ---------------------------------------------------------------------------


class TestFixFolderHeadings:
    def test_processes_all_pdfs_in_folder(self, tmp_path: Path) -> None:
        """All PDFs in the folder have their heading levels fixed."""
        (tmp_path / "markdown").mkdir()
        for name in ("a.pdf", "b.pdf"):
            (tmp_path / name).write_bytes(b"%PDF-1.4")
            (tmp_path / "markdown" / f"{name[:-4]}.md").write_text(
                "## **Schedule 02**\n", encoding="utf-8"
            )

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            _make_pymupdf_mock(MOCK_TOC),
        ):
            fix_folder_headings(tmp_path)

        assert (tmp_path / "markdown_clean" / "a.md").exists()
        assert (tmp_path / "markdown_clean" / "b.md").exists()

    def test_does_not_process_pdfs_in_subdirectories(self, tmp_path: Path) -> None:
        """PDFs nested in subdirectories are not processed."""
        (tmp_path / "markdown").mkdir()
        (tmp_path / "top.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "markdown" / "top.md").write_text("## **Schedule 02**\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.pdf").write_bytes(b"%PDF-1.4")

        open_mock = _make_pymupdf_mock(MOCK_TOC)
        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            open_mock,
        ):
            fix_folder_headings(tmp_path)

        assert open_mock.call_count == 1
        assert not (tmp_path / "markdown_clean" / "nested.md").exists()
