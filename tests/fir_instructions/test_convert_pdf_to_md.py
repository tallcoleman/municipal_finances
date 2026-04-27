"""Tests for fir_instructions/convert_pdf_to_md.py."""

# postpone evaluation of typing annotations
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from municipal_finances.fir_instructions.convert_pdf_to_md import (
    _build_toc_level_map,
    _extract_section_from_footer,
    _fix_heading_levels,
    _get_footer_spans,
    _normalize,
    _section_to_stem,
    convert_folder,
    convert_pdf,
    count_pages,
    fix_folder_headings,
    fix_pdf_headings,
    split_pdf_by_section,
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


# ---------------------------------------------------------------------------
# _get_footer_spans
# ---------------------------------------------------------------------------


def _make_page_mock_for_spans(
    span_texts: list[str],
    page_height: float = 792.0,
    block_y: float | None = None,
) -> MagicMock:
    """Return a mock page whose get_text returns a single text block at *block_y*.

    Defaults to placing the block at 90% of page height (i.e. in the footer zone).
    """
    if block_y is None:
        block_y = page_height * 0.9

    page = MagicMock()
    page.rect = MagicMock()
    page.rect.height = page_height

    spans_list = [{"text": t} for t in span_texts]
    block = {
        "type": 0,
        "bbox": (0, block_y, 612, block_y + 20),
        "lines": [{"spans": spans_list}],
    }
    page.get_text.return_value = {"blocks": [block]}
    return page


class TestGetFooterSpans:
    def test_returns_spans_from_footer_zone(self) -> None:
        """Spans in a block below the 85% threshold are returned."""
        # block_y omitted — exercises the default (page_height * 0.9) branch
        page = _make_page_mock_for_spans(["FIR2022", "Introduction"], page_height=100.0)
        assert _get_footer_spans(page) == ["FIR2022", "Introduction"]

    def test_ignores_block_above_threshold(self) -> None:
        """Blocks whose top edge is above the footer threshold are excluded."""
        page = _make_page_mock_for_spans(["body text"], page_height=100.0, block_y=50.0)
        assert _get_footer_spans(page) == []

    def test_strips_whitespace_only_spans(self) -> None:
        """Spans containing only whitespace are dropped."""
        page = _make_page_mock_for_spans(["  ", "FIR2020", "\t"], page_height=100.0, block_y=90.0)
        assert _get_footer_spans(page) == ["FIR2020"]

    def test_ignores_non_text_blocks(self) -> None:
        """Blocks with type != 0 (e.g. images) are ignored even if in footer zone."""
        page = MagicMock()
        page.rect = MagicMock()
        page.rect.height = 100.0
        image_block = {"type": 1, "bbox": (0, 90, 612, 110)}
        page.get_text.return_value = {"blocks": [image_block]}
        assert _get_footer_spans(page) == []

    def test_collects_multiple_footer_spans(self) -> None:
        """All non-empty spans from the footer zone are collected."""
        page = _make_page_mock_for_spans(
            ["FIR2019     Introduction", "INTRO - 1", "Ministry of Municipal Affairs"],
            page_height=792.0,
            block_y=700.0,
        )
        result = _get_footer_spans(page)
        assert result == [
            "FIR2019     Introduction",
            "INTRO - 1",
            "Ministry of Municipal Affairs",
        ]


# ---------------------------------------------------------------------------
# _extract_section_from_footer
# ---------------------------------------------------------------------------


class TestExtractSectionFromFooter:
    def test_empty_spans_returns_none(self) -> None:
        assert _extract_section_from_footer([]) is None

    def test_no_fir_year_returns_none(self) -> None:
        assert _extract_section_from_footer(["Some text", "INTRO - 1"]) is None

    def test_corrupted_fir_year_returns_none(self) -> None:
        """Partial year token like 'FIR202' should not match."""
        assert _extract_section_from_footer(["FIR202", "12", "Schedule", "83"]) is None

    # 2019 combined-span format
    def test_2019_introduction(self) -> None:
        spans = ["FIR2019     Introduction", "INTRO - 1", "Ministry of Municipal Affairs and Housing"]
        assert _extract_section_from_footer(spans) == "Introduction"

    def test_2019_schedule(self) -> None:
        spans = ["FIR2019      Schedule 26      Taxation and Payments-In-Lieu Summary", "26 - 14"]
        assert _extract_section_from_footer(spans) == "Schedule 26"

    def test_2019_functional_classification(self) -> None:
        spans = ["FIR2019", "Functional Classification", "FUNCTIONS - 12"]
        assert _extract_section_from_footer(spans) == "Functional Classification"

    # 2020 / 2021 separate-span format
    def test_2020_introduction(self) -> None:
        spans = ["Ministry of Municipal Affairs and Housing", "Municipal Finance Policy Branch",
                 "FIR2020", "Introduction", "INTRO -", "1"]
        assert _extract_section_from_footer(spans) == "Introduction"

    def test_2020_schedule_two_token(self) -> None:
        """Schedule and number in one span ('Schedule 26')."""
        spans = ["FIR2020", "Schedule 26", "Taxation and Payments-In-Lieu Summary", "26 -", "11"]
        assert _extract_section_from_footer(spans) == "Schedule 26"

    def test_2021_schedule_with_note(self) -> None:
        """Extra note text before FIR year marker is ignored."""
        spans = ["Some long note.", "FIR2021", "Schedule 24", "Payments-In-Lieu of Taxation", "24 -", "6"]
        assert _extract_section_from_footer(spans) == "Schedule 24"

    # 2022 word-split format
    def test_2022_introduction_split(self) -> None:
        spans = ["FIR2022", "Introduction", "INTRO", "-", "1"]
        assert _extract_section_from_footer(spans) == "Introduction"

    def test_2022_functional_classification_split(self) -> None:
        spans = ["FIR2022", "Functional", "Classification", "FUNCTIONS", "-", "10"]
        assert _extract_section_from_footer(spans) == "Functional Classification"

    def test_2022_schedule_word_split(self) -> None:
        spans = ["FIR2022", "Schedule", "10", "Statement", "of", "Operations:", "Revenue", "10", "-", "1"]
        assert _extract_section_from_footer(spans) == "Schedule 10"

    def test_2022_schedule_non_split(self) -> None:
        """Some 2022 pages use the non-split format."""
        spans = ["FIR2022", "Schedule 28", "Upper-Tier Entitlements", "28 -", "5"]
        assert _extract_section_from_footer(spans) == "Schedule 28"

    def test_schedule_80d(self) -> None:
        spans = ["FIR2021", "Schedule 80D", "Statistical Information", "80 -", "15"]
        assert _extract_section_from_footer(spans) == "Schedule 80D"

    def test_empty_section_text_after_page_id_strip_returns_none(self) -> None:
        """Returns None when the FIR year is immediately followed by the page-ID suffix."""
        # Joined: "FIR2019 INTRO - 1" → after year: "INTRO - 1" → page-ID at pos 0 → empty section
        spans = ["FIR2019", "INTRO - 1"]
        assert _extract_section_from_footer(spans) is None

    def test_arbitrary_section_name_returned_as_is(self) -> None:
        """Section names that don't match any known pattern are returned verbatim."""
        spans = ["FIR2023", "Bulletin on Tile Drainage Loans", "99 -", "1"]
        assert _extract_section_from_footer(spans) == "Bulletin on Tile Drainage Loans"

    def test_footnote_fir_reference_does_not_shadow_section(self) -> None:
        """When a footnote cites 'FIR20XX' before the real section identifier, the last
        occurrence is used so the correct section name is extracted."""
        spans = [
            "See the FIR2022 Tables document for a complete list of RTC Codes.",
            "FIR2022", "Schedule 26", "Taxation Summary", "26 -", "1",
        ]
        assert _extract_section_from_footer(spans) == "Schedule 26"


# ---------------------------------------------------------------------------
# _section_to_stem
# ---------------------------------------------------------------------------


class TestSectionToStem:
    def test_introduction(self) -> None:
        assert _section_to_stem("Introduction", "2019") == "FIR2019 Introduction"

    def test_functional_classification(self) -> None:
        assert _section_to_stem("Functional Classification", "2022") == "FIR2022 Functional Categories"

    def test_schedule_two_digit(self) -> None:
        assert _section_to_stem("Schedule 26", "2019") == "FIR2019 S26"

    def test_schedule_already_zero_padded(self) -> None:
        assert _section_to_stem("Schedule 02", "2020") == "FIR2020 S02"

    def test_schedule_single_digit_zero_padded(self) -> None:
        assert _section_to_stem("Schedule 2", "2021") == "FIR2021 S02"

    def test_schedule_alphanumeric(self) -> None:
        assert _section_to_stem("Schedule 80D", "2022") == "FIR2022 S80D"

    def test_arbitrary_section_name(self) -> None:
        assert (
            _section_to_stem("Bulletin on Tile Drainage Loans", "2023")
            == "FIR2023 Bulletin on Tile Drainage Loans"
        )


# ---------------------------------------------------------------------------
# split_pdf_by_section
# ---------------------------------------------------------------------------


def _make_page_mock_for_split(footer_spans: list[str], page_height: float = 792.0) -> MagicMock:
    """Return a mock page for use in split_pdf_by_section tests."""
    block_y = page_height * 0.9
    page = MagicMock()
    page.rect = MagicMock()
    page.rect.height = page_height
    spans_list = [{"text": t} for t in footer_spans]
    block = {
        "type": 0,
        "bbox": (0, block_y, 612, block_y + 20),
        "lines": [{"spans": spans_list}],
    }
    page.get_text.return_value = {"blocks": [block]}
    return page


def _make_split_doc_mock(pages_spans: list[list[str]]) -> MagicMock:
    """Return a mock pymupdf document whose pages have the given footer spans."""
    page_mocks = [_make_page_mock_for_split(spans) for spans in pages_spans]
    doc = MagicMock()
    doc.__len__ = MagicMock(return_value=len(page_mocks))
    doc.__getitem__ = MagicMock(side_effect=lambda i: page_mocks[i])
    return doc


def _make_open_side_effect(
    pdf: Path, source_doc: MagicMock, out_docs: list[MagicMock]
):
    """Return a side_effect callable for patching pymupdf.open.

    Calls with the source PDF path return *source_doc*.  Calls with no
    arguments (i.e. creating a new empty document inside split_pdf_by_section)
    return a fresh MagicMock that is appended to *out_docs*.
    """

    def _side_effect(*args, **kwargs):
        if args and str(args[0]) == str(pdf):
            return source_doc
        d = MagicMock()
        out_docs.append(d)
        return d

    return _side_effect


class TestSplitPdfBySection:
    def test_two_sections_produce_two_pdfs(self, tmp_path: Path) -> None:
        """Two distinct sections produce two output PDF files."""
        pdf = tmp_path / "FIR2019 Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages_spans = [
            ["FIR2019     Introduction", "INTRO - 1"],
            ["FIR2019     Introduction", "INTRO - 2"],
            ["FIR2019      Schedule 26      Taxation", "26 - 1"],
        ]
        source_doc = _make_split_doc_mock(pages_spans)
        out_docs: list[MagicMock] = []

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=_make_open_side_effect(pdf, source_doc, out_docs),
        ):
            split_pdf_by_section(pdf)

        assert len(out_docs) == 2

    def test_output_directory_named_after_year(self, tmp_path: Path) -> None:
        """Default output directory is a subdirectory named after the year."""
        pdf = tmp_path / "FIR2022 Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages_spans = [["FIR2022", "Introduction", "INTRO", "-", "1"]]
        source_doc = _make_split_doc_mock(pages_spans)
        out_docs: list[MagicMock] = []

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=_make_open_side_effect(pdf, source_doc, out_docs),
        ):
            split_pdf_by_section(pdf)

        assert (tmp_path / "2022").is_dir()

    def test_custom_output_folder(self, tmp_path: Path) -> None:
        """Custom output_folder overrides the year-based default."""
        pdf = tmp_path / "FIR2020 Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages_spans = [["FIR2020", "Introduction", "INTRO -", "1"]]
        source_doc = _make_split_doc_mock(pages_spans)
        out_docs: list[MagicMock] = []

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=_make_open_side_effect(pdf, source_doc, out_docs),
        ):
            split_pdf_by_section(pdf, output_folder="custom_out")

        assert (tmp_path / "custom_out").is_dir()
        assert not (tmp_path / "2020").exists()

    def test_pages_with_no_footer_are_skipped(self, tmp_path: Path) -> None:
        """Pages returning empty footer spans contribute to no output section."""
        pdf = tmp_path / "FIR2021 Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages_spans = [
            [],  # no footer — skipped
            ["FIR2021", "Introduction", "INTRO -", "1"],
            ["FIR2021", "Introduction", "INTRO -", "2"],
        ]
        source_doc = _make_split_doc_mock(pages_spans)
        out_docs: list[MagicMock] = []

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=_make_open_side_effect(pdf, source_doc, out_docs),
        ):
            split_pdf_by_section(pdf)

        # One section PDF created
        assert len(out_docs) == 1
        # insert_pdf called twice (pages 1 and 2, not the empty page 0)
        out_doc = out_docs[0]
        assert out_doc.insert_pdf.call_count == 2
        calls = out_doc.insert_pdf.call_args_list
        page_nums = [c.kwargs.get("from_page") for c in calls]
        assert 1 in page_nums
        assert 2 in page_nums
        assert 0 not in page_nums

    def test_raises_on_filename_without_year(self, tmp_path: Path) -> None:
        """ValueError is raised when the PDF filename contains no FIR year."""
        pdf = tmp_path / "Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        with pytest.raises(ValueError, match="Cannot determine year"):
            split_pdf_by_section(pdf)

    def test_single_section_writes_one_pdf(self, tmp_path: Path) -> None:
        """A PDF with one section produces exactly one output file."""
        pdf = tmp_path / "FIR2019 Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages_spans = [
            ["FIR2019      Schedule 83      Notes", "83 - 1"],
        ]
        source_doc = _make_split_doc_mock(pages_spans)
        out_docs: list[MagicMock] = []

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=_make_open_side_effect(pdf, source_doc, out_docs),
        ):
            split_pdf_by_section(pdf)

        assert len(out_docs) == 1
        out_docs[0].save.assert_called_once()
        saved_path = out_docs[0].save.call_args[0][0]
        assert saved_path.name == "FIR2019 S83.pdf"

    def test_correct_filename_for_schedule_section(self, tmp_path: Path) -> None:
        """Schedule sections are saved as FIR{year} S{NN}.pdf."""
        pdf = tmp_path / "FIR2020 Instructions.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        pages_spans = [["FIR2020", "Schedule 26", "Taxation Summary", "26 -", "1"]]
        source_doc = _make_split_doc_mock(pages_spans)
        out_docs: list[MagicMock] = []

        with patch(
            "municipal_finances.fir_instructions.convert_pdf_to_md.pymupdf.open",
            side_effect=_make_open_side_effect(pdf, source_doc, out_docs),
        ):
            split_pdf_by_section(pdf)

        saved_path = out_docs[0].save.call_args[0][0]
        assert saved_path.name == "FIR2020 S26.pdf"
