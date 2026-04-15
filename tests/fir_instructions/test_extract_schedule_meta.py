"""Tests for fir_instructions/extract_schedule_meta.py.

These tests cover schedule metadata extraction, database insertion, and CSV
round-trip.  DB tests require the test PostgreSQL container (localhost:5433).
"""

# postponse evaluation of typing annotations
from __future__ import annotations

import csv
from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from municipal_finances.fir_instructions.extract_schedule_meta import (
    SCHEDULE_CATEGORIES,
    SUB_SCHEDULE_PARENTS,
    _SUB_SCHEDULE_HEADING_PREFIXES,
    _clean_md_content,
    _extract_regular_schedule,
    _extract_schedule_53,
    _extract_schedule_74e,
    _extract_sub_schedule,
    _extract_sub_schedule_name,
    _find_section,
    _parse_md_sections,
    _strip_bold,
    app,
    extract_all_schedule_meta,
    extract_schedule_record,
    insert_schedule_meta,
    load_from_csv,
    save_to_csv,
)
from municipal_finances.models import FIRScheduleMeta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPECTED_CODES: frozenset[str] = frozenset(SCHEDULE_CATEGORIES.keys())

_BASELINE_CSV = Path("fir_instructions/exports/baseline_schedule_meta.csv")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_record(**overrides: Any) -> dict[str, Any]:
    """Build a minimal valid schedule metadata record."""
    base: dict[str, Any] = {
        "schedule": "10",
        "schedule_name": "Consolidated Statement of Operations: Revenue",
        "category": "Revenue",
        "description": "Test description.",
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }
    return {**base, **overrides}


def _load_baseline() -> list[dict[str, Any]]:
    """Load the pre-extracted baseline CSV; skip if it does not exist."""
    if not _BASELINE_CSV.exists():
        pytest.skip(f"Baseline CSV not found: {_BASELINE_CSV}")
    return load_from_csv(_BASELINE_CSV)


def _write_md(tmp_path: Path, filename: str, content: str) -> Path:
    """Write a markdown file into tmp_path and return the path."""
    p = tmp_path / filename
    p.write_text(dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Baseline CSV content — schedule codes, names, categories, descriptions
# ---------------------------------------------------------------------------


class TestBaselineCSVContent:
    @pytest.fixture(scope="class")
    def records(self) -> list[dict[str, Any]]:
        return _load_baseline()

    def test_exactly_31_records(self, records: list[dict[str, Any]]) -> None:
        """Baseline CSV must contain exactly 31 records (one per schedule code)."""
        assert len(records) == 31

    def test_all_31_codes_present(self, records: list[dict[str, Any]]) -> None:
        """Every expected schedule code must appear in the CSV."""
        found = {r["schedule"] for r in records}
        missing = _EXPECTED_CODES - found
        assert missing == set(), f"Missing codes: {sorted(missing)}"

    def test_no_unexpected_codes(self, records: list[dict[str, Any]]) -> None:
        """No schedule code outside the expected set should be in the CSV."""
        found = {r["schedule"] for r in records}
        extras = found - _EXPECTED_CODES
        assert extras == set(), f"Unexpected codes: {sorted(extras)}"

    def test_no_empty_schedule_names(self, records: list[dict[str, Any]]) -> None:
        """Every record must have a non-empty schedule_name."""
        empty = [r["schedule"] for r in records if not r.get("schedule_name")]
        assert empty == [], f"Empty schedule_name for: {empty}"

    def test_no_empty_categories(self, records: list[dict[str, Any]]) -> None:
        """Every record must have a non-empty category."""
        empty = [r["schedule"] for r in records if not r.get("category")]
        assert empty == [], f"Empty category for: {empty}"

    def test_no_empty_descriptions(self, records: list[dict[str, Any]]) -> None:
        """Every record must have a non-empty description."""
        empty = [r["schedule"] for r in records if not r.get("description")]
        assert empty == [], f"Empty description for: {empty}"

    def test_valid_from_year_is_null_on_all_rows(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Baseline rows must have valid_from_year = NULL."""
        non_null = [
            r["schedule"] for r in records if r.get("valid_from_year") is not None
        ]
        assert non_null == [], f"Unexpected valid_from_year on: {non_null}"

    def test_valid_to_year_is_null_on_all_rows(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Baseline rows must have valid_to_year = NULL."""
        non_null = [
            r["schedule"] for r in records if r.get("valid_to_year") is not None
        ]
        assert non_null == [], f"Unexpected valid_to_year on: {non_null}"

    def test_categories_match_expected_mapping(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Each record's category must match the SCHEDULE_CATEGORIES mapping."""
        wrong = [
            r["schedule"]
            for r in records
            if r["category"] != SCHEDULE_CATEGORIES.get(r["schedule"])
        ]
        assert wrong == [], f"Category mismatch for: {wrong}"

    def test_sub_schedule_names_are_non_empty(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Sub-schedules (22A/B/C, 51A/B, 61A/B) must have non-empty names and descriptions."""
        sub_records = [r for r in records if r["schedule"] in SUB_SCHEDULE_PARENTS]
        empty_names = [r["schedule"] for r in sub_records if not r.get("schedule_name")]
        empty_descs = [r["schedule"] for r in sub_records if not r.get("description")]
        assert empty_names == [], f"Sub-schedule missing name: {empty_names}"
        assert empty_descs == [], f"Sub-schedule missing description: {empty_descs}"

    def test_description_minimum_length(self, records: list[dict[str, Any]]) -> None:
        """Every description must be at least 50 characters (sanity check)."""
        too_short = [
            r["schedule"] for r in records if len(r.get("description", "")) < 50
        ]
        assert too_short == [], f"Suspiciously short descriptions for: {too_short}"


# ---------------------------------------------------------------------------
# 2. Database insertion
# ---------------------------------------------------------------------------


class TestInsertScheduleMeta:
    def test_insert_single_record(self, engine, session: Session) -> None:
        """A single valid record can be inserted and retrieved from the DB."""
        records = [_minimal_record()]
        inserted = insert_schedule_meta(engine, records)
        assert inserted == 1

        rows = session.exec(select(FIRScheduleMeta)).all()
        assert len(rows) == 1
        assert rows[0].schedule == "10"
        assert rows[0].schedule_name == "Consolidated Statement of Operations: Revenue"
        assert rows[0].category == "Revenue"

    def test_insert_returns_count(self, engine, session: Session) -> None:
        """insert_schedule_meta returns the number of rows actually inserted."""
        records = [
            _minimal_record(schedule="10"),
            _minimal_record(schedule="40", category="Expense"),
        ]
        inserted = insert_schedule_meta(engine, records)
        assert inserted == 2

    def test_idempotent_insertion(self, engine, session: Session) -> None:
        """Re-inserting the same record leaves exactly one row (ON CONFLICT DO NOTHING)."""
        records = [_minimal_record()]
        first = insert_schedule_meta(engine, records)
        second = insert_schedule_meta(engine, records)
        assert first == 1
        assert second == 0
        assert len(session.exec(select(FIRScheduleMeta)).all()) == 1

    def test_insert_empty_list(self, engine, session: Session) -> None:
        """Inserting an empty list is a no-op and returns 0."""
        assert insert_schedule_meta(engine, []) == 0

    def test_baseline_rows_have_null_year_fields(
        self, engine, session: Session
    ) -> None:
        """Baseline records inserted with NULL year fields are stored as NULL."""
        records = [_minimal_record(valid_from_year=None, valid_to_year=None)]
        insert_schedule_meta(engine, records)
        row = session.exec(select(FIRScheduleMeta)).first()
        assert row is not None
        assert row.valid_from_year is None
        assert row.valid_to_year is None
        assert row.change_notes is None

    def test_insert_all_31_baseline_records(self, engine, session: Session) -> None:
        """All 31 baseline records from the CSV can be inserted into the DB."""
        records = _load_baseline()
        inserted = insert_schedule_meta(engine, records)
        assert inserted == 31

        db_rows = session.exec(select(FIRScheduleMeta)).all()
        assert len(db_rows) == 31

    def test_all_31_codes_in_db(self, engine, session: Session) -> None:
        """After inserting all baseline records, every expected code is present in the DB."""
        records = _load_baseline()
        insert_schedule_meta(engine, records)

        db_codes = {r.schedule for r in session.exec(select(FIRScheduleMeta)).all()}
        missing = _EXPECTED_CODES - db_codes
        assert missing == set(), f"Missing codes in DB: {sorted(missing)}"

    def test_no_required_fields_null_in_db(self, engine, session: Session) -> None:
        """After insertion, no row should have NULL schedule, schedule_name, or category."""
        records = _load_baseline()
        insert_schedule_meta(engine, records)

        rows = session.exec(select(FIRScheduleMeta)).all()
        null_schedule = [r.id for r in rows if not r.schedule]
        null_name = [r.schedule for r in rows if not r.schedule_name]
        null_category = [r.schedule for r in rows if not r.category]
        assert null_schedule == [], "Rows with NULL schedule"
        assert null_name == [], f"Rows with NULL schedule_name: {null_name}"
        assert null_category == [], f"Rows with NULL category: {null_category}"


# ---------------------------------------------------------------------------
# 3. CSV round-trip
# ---------------------------------------------------------------------------


class TestCSVRoundTrip:
    def test_save_and_load_preserves_data(self, tmp_path: Path) -> None:
        """Records saved with save_to_csv and reloaded with load_from_csv are identical."""
        records = [
            _minimal_record(schedule="10"),
            _minimal_record(schedule="40", category="Expense"),
            _minimal_record(
                schedule="22A",
                category="Taxation",
                valid_from_year=None,
                valid_to_year=None,
            ),
        ]
        csv_path = tmp_path / "test_schedule_meta.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)

        assert len(loaded) == 3
        assert loaded[0]["schedule"] == "10"
        assert loaded[1]["schedule"] == "40"
        assert loaded[2]["schedule"] == "22A"

    def test_nullable_int_fields_round_trip_as_none(self, tmp_path: Path) -> None:
        """NULL integer fields (valid_from_year, valid_to_year) survive CSV round-trip as None."""
        records = [_minimal_record(valid_from_year=None, valid_to_year=None)]
        csv_path = tmp_path / "nulls.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["valid_from_year"] is None
        assert loaded[0]["valid_to_year"] is None

    def test_nullable_str_field_round_trips_as_none(self, tmp_path: Path) -> None:
        """NULL string field (change_notes) survives CSV round-trip as None."""
        records = [_minimal_record(change_notes=None)]
        csv_path = tmp_path / "change_notes_null.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["change_notes"] is None

    def test_non_null_year_fields_survive_round_trip(self, tmp_path: Path) -> None:
        """Non-NULL integer year fields round-trip as integers."""
        records = [_minimal_record(valid_from_year=2022, valid_to_year=2024)]
        csv_path = tmp_path / "years.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["valid_from_year"] == 2022
        assert loaded[0]["valid_to_year"] == 2024

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save_to_csv creates missing parent directories."""
        deep_path = tmp_path / "a" / "b" / "meta.csv"
        save_to_csv([_minimal_record()], deep_path)
        assert deep_path.exists()

    def test_load_and_insert(self, engine, session: Session, tmp_path: Path) -> None:
        """Records saved to CSV, reloaded, and passed to insert_schedule_meta are inserted OK."""
        records = [_minimal_record()]
        csv_path = tmp_path / "roundtrip.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        inserted = insert_schedule_meta(engine, loaded)
        assert inserted == 1


# ---------------------------------------------------------------------------
# 4. Markdown parsing helper functions
# ---------------------------------------------------------------------------


class TestStripBold:
    def test_removes_bold_markers(self) -> None:
        """**text** has markers removed, leaving just text."""
        assert _strip_bold("**hello**") == "hello"

    def test_removes_inline_bold(self) -> None:
        """Bold markers in the middle of a string are removed."""
        assert _strip_bold("foo **bar** baz") == "foo bar baz"

    def test_strips_surrounding_whitespace(self) -> None:
        """Leading and trailing whitespace is stripped from the result."""
        assert _strip_bold("  plain  ") == "plain"

    def test_no_markers_unchanged(self) -> None:
        """A string without bold markers is returned unchanged (modulo strip)."""
        assert _strip_bold("plain text") == "plain text"

    def test_empty_string(self) -> None:
        """Empty input returns an empty string."""
        assert _strip_bold("") == ""


class TestParseMdSections:
    def test_single_heading_no_preamble(self, tmp_path: Path) -> None:
        """A file with a single heading and content is parsed into two sections."""
        md = _write_md(
            tmp_path,
            "test.md",
            """\
            # Heading One
            content line
        """,
        )
        sections = _parse_md_sections(md)
        # [("", []), ("Heading One", ["content line"])]
        assert len(sections) == 2
        assert sections[1][0] == "Heading One"
        assert "content line" in sections[1][1]

    def test_preamble_before_first_heading(self, tmp_path: Path) -> None:
        """Content before the first heading is captured under an empty heading string."""
        md = _write_md(
            tmp_path,
            "test.md",
            """\
            preamble line
            # First Heading
            after
        """,
        )
        sections = _parse_md_sections(md)
        assert sections[0][0] == ""
        assert any("preamble line" in line for line in sections[0][1])

    def test_multiple_headings(self, tmp_path: Path) -> None:
        """Multiple headings produce one section per heading."""
        md = _write_md(
            tmp_path,
            "test.md",
            """\
            ## Alpha
            alpha content
            ## Beta
            beta content
        """,
        )
        sections = _parse_md_sections(md)
        headings = [s[0] for s in sections]
        assert "Alpha" in headings
        assert "Beta" in headings

    def test_bold_markers_stripped_from_headings(self, tmp_path: Path) -> None:
        """**bold** in heading text is stripped when the heading is recorded."""
        md = _write_md(
            tmp_path,
            "test.md",
            """\
            ## **Bold Heading**
            content
        """,
        )
        sections = _parse_md_sections(md)
        heading_texts = [s[0] for s in sections]
        assert "Bold Heading" in heading_texts
        assert "**Bold Heading**" not in heading_texts

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """A path that does not exist returns an empty list without raising."""
        result = _parse_md_sections(tmp_path / "nonexistent.md")
        assert result == []

    def test_content_lines_have_no_trailing_newlines(self, tmp_path: Path) -> None:
        """Content lines stored in sections have trailing newlines stripped."""
        md = _write_md(
            tmp_path,
            "test.md",
            """\
            ## Heading
            line with text
        """,
        )
        sections = _parse_md_sections(md)
        for _, content in sections:
            for line in content:
                assert not line.endswith("\n")


class TestCleanMdContent:
    def test_preserves_bold_markers(self) -> None:
        """**bold** markers are preserved so the output remains valid markdown."""
        result = _clean_md_content(["**important** text"])
        assert "**important**" in result

    def test_strips_trailing_whitespace(self) -> None:
        """Trailing whitespace on each line is removed."""
        result = _clean_md_content(["text   "])
        assert result == "text"

    def test_collapses_three_blank_lines(self) -> None:
        """Three or more consecutive blank lines are collapsed to two."""
        result = _clean_md_content(["line one", "", "", "", "line two"])
        assert "\n\n\n" not in result
        assert "line one" in result
        assert "line two" in result

    def test_two_blank_lines_preserved(self) -> None:
        """Exactly two blank lines (one empty line between content) are preserved."""
        result = _clean_md_content(["line one", "", "", "line two"])
        assert "line one\n\nline two" in result

    def test_empty_input(self) -> None:
        """An empty list of lines produces an empty string."""
        assert _clean_md_content([]) == ""

    def test_strips_leading_trailing_blank_lines(self) -> None:
        """The final result is stripped of leading/trailing whitespace."""
        result = _clean_md_content(["", "content", ""])
        assert result == "content"


class TestFindSection:
    def _sections(self) -> list[tuple[str, list[str]]]:
        return [
            ("", []),
            ("General Information", ["desc"]),
            ("Line 1010", ["line content"]),
            ("Schedule 51A: Capital Assets", ["51a content"]),
        ]

    def test_prefix_match(self) -> None:
        """A prefix of the heading text matches the section."""
        sections = self._sections()
        idx = _find_section(sections, "General")
        assert idx == 1

    def test_exact_match(self) -> None:
        """Exact match requires the heading to equal the prefix exactly."""
        sections = self._sections()
        idx = _find_section(sections, "General Information", exact=True)
        assert idx == 1

    def test_exact_no_match_on_prefix_only(self) -> None:
        """Exact mode does not match when the heading only starts with the prefix."""
        sections = self._sections()
        idx = _find_section(sections, "General", exact=True)
        assert idx is None

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        sections = self._sections()
        idx = _find_section(sections, "general information", exact=True)
        assert idx == 1

    def test_start_parameter(self) -> None:
        """Search begins at the given start index."""
        sections = self._sections()
        idx = _find_section(sections, "General Information", start=2)
        assert idx is None  # Section 1 is before start=2

    def test_not_found_returns_none(self) -> None:
        """Returns None when no section matches."""
        sections = self._sections()
        assert _find_section(sections, "Nonexistent") is None


# ---------------------------------------------------------------------------
# 5. Sub-schedule name extraction
# ---------------------------------------------------------------------------


class TestExtractSubScheduleName:
    def test_strips_schedule_prefix(self) -> None:
        """A heading of the form 'Schedule XX: Name' has the prefix stripped, returning Name."""
        result = _extract_sub_schedule_name(
            "Schedule 51A: Tangible Capital Assets", "51A"
        )
        assert result == "Tangible Capital Assets"

    def test_strips_code_suffix_in_parentheses(self) -> None:
        """A heading ending with '(CODE)' has the parenthesised suffix stripped."""
        result = _extract_sub_schedule_name(
            "General Purpose Levy Information (22A)", "22A"
        )
        assert result == "General Purpose Levy Information"

    def test_plain_heading_returned_as_is(self) -> None:
        """A heading with no recognised prefix or suffix is returned unchanged."""
        result = _extract_sub_schedule_name("Some Heading Without Code", "99X")
        assert result == "Some Heading Without Code"

    def test_strips_internal_whitespace_in_name(self) -> None:
        """Extra spaces around the name after stripping the prefix are removed."""
        result = _extract_sub_schedule_name("Schedule 61A:  Reserves", "61A")
        assert result == "Reserves"


# ---------------------------------------------------------------------------
# 6. Per-schedule extractors — using temporary markdown files
# ---------------------------------------------------------------------------


class TestExtractRegularSchedule:
    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Name from SCHEDULE heading and description from General Information section."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue Operations
            ## General Information
            This schedule collects revenue information.
        """,
        )
        result = _extract_regular_schedule(tmp_path, "10")
        assert result["schedule"] == "10"
        assert result["schedule_name"] == "Revenue Operations"
        assert "revenue information" in result["description"].lower()

    def test_general_instructions_also_accepted(self, tmp_path: Path) -> None:
        """'General Instructions' heading is accepted in addition to 'General Information'."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## General Instructions
            Instruction text for this schedule.
        """,
        )
        result = _extract_regular_schedule(tmp_path, "10")
        assert "Instruction text" in result["description"]

    def test_empty_name_when_no_schedule_heading(self, tmp_path: Path) -> None:
        """schedule_name is empty when no matching SCHEDULE heading is found."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## General Information
            Some description.
        """,
        )
        result = _extract_regular_schedule(tmp_path, "10")
        assert result["schedule_name"] == ""

    def test_empty_description_when_no_gi_heading(self, tmp_path: Path) -> None:
        """description is empty when no General Information/Instructions section is found."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## Line 1010
            Some line description.
        """,
        )
        result = _extract_regular_schedule(tmp_path, "10")
        assert result["description"] == ""

    def test_null_year_fields(self, tmp_path: Path) -> None:
        """valid_from_year, valid_to_year, and change_notes are always None."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## General Information
            Description.
        """,
        )
        result = _extract_regular_schedule(tmp_path, "10")
        assert result["valid_from_year"] is None
        assert result["valid_to_year"] is None
        assert result["change_notes"] is None

    def test_missing_file_returns_empty_fields(self, tmp_path: Path) -> None:
        """When the markdown file does not exist, name and description are empty strings."""
        result = _extract_regular_schedule(tmp_path, "99")
        assert result["schedule"] == "99"
        assert result["schedule_name"] == ""
        assert result["description"] == ""

    def test_category_set_from_schedule_categories(self, tmp_path: Path) -> None:
        """Category in the result matches SCHEDULE_CATEGORIES for the code."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## General Information
            Description.
        """,
        )
        result = _extract_regular_schedule(tmp_path, "10")
        assert result["category"] == SCHEDULE_CATEGORIES["10"]


class TestExtractSchedule53:
    def test_extracts_name_and_description(self, tmp_path: Path) -> None:
        """Name from SCHEDULE 53 heading; description from the section immediately after."""
        _write_md(
            tmp_path,
            "FIR2025 S53.md",
            """\
            ## SCHEDULE 53: Net Financial Assets (Net Debt)
            ## Consolidated Statement of Change in Net Financial Assets (Net Debt)
            This statement explains the difference between surplus or deficit and
            the change in net financial assets for the reporting year.
        """,
        )
        result = _extract_schedule_53(tmp_path)
        assert result["schedule"] == "53"
        assert "Net Financial Assets" in result["schedule_name"]
        assert "surplus or deficit" in result["description"]

    def test_empty_description_when_no_body_section(self, tmp_path: Path) -> None:
        """description is empty when SCHEDULE 53 heading is not found."""
        _write_md(
            tmp_path,
            "FIR2025 S53.md",
            """\
            ## Some Other Heading
            Content.
        """,
        )
        result = _extract_schedule_53(tmp_path)
        assert result["schedule"] == "53"
        assert result["description"] == ""

    def test_null_year_fields(self, tmp_path: Path) -> None:
        """Year and change_notes fields are always None."""
        _write_md(
            tmp_path,
            "FIR2025 S53.md",
            """\
            ## SCHEDULE 53: Net Financial Assets
            ## Body Section
            Content.
        """,
        )
        result = _extract_schedule_53(tmp_path)
        assert result["valid_from_year"] is None
        assert result["valid_to_year"] is None
        assert result["change_notes"] is None


class TestExtractSchedule74E:
    def test_extracts_description_after_aro_heading(self, tmp_path: Path) -> None:
        """Finds the 'Schedule 74E' section (exact), then extracts the ARO sub-section."""
        _write_md(
            tmp_path,
            "FIR2025 S74.md",
            """\
            ## Schedule 74E - Asset Retirement Obligation Liability
            Overview mention of 74E here.
            ## Schedule 74E
            ## Asset Retirement Obligation Liability
            This section describes ARO liabilities for municipalities.
        """,
        )
        result = _extract_schedule_74e(tmp_path)
        assert result["schedule"] == "74E"
        assert result["schedule_name"] == "Asset Retirement Obligation Liability"
        assert "ARO liabilities" in result["description"]

    def test_empty_description_when_aro_heading_absent(self, tmp_path: Path) -> None:
        """Returns empty description when 'Asset Retirement Obligation Liability' is not found."""
        _write_md(
            tmp_path,
            "FIR2025 S74.md",
            """\
            ## Schedule 74E
            Some content without the ARO heading.
        """,
        )
        result = _extract_schedule_74e(tmp_path)
        assert result["schedule"] == "74E"
        assert result["description"] == ""
        assert result["schedule_name"] == "Asset Retirement Obligation Liability"
        assert result["valid_from_year"] is None
        assert result["valid_to_year"] is None

    def test_empty_when_s74e_section_absent(self, tmp_path: Path) -> None:
        """Returns empty description when exact 'Schedule 74E' heading is not present."""
        _write_md(
            tmp_path,
            "FIR2025 S74.md",
            """\
            ## Schedule 74E - Asset Retirement Obligation Liability
            No exact bare 74E heading here.
        """,
        )
        result = _extract_schedule_74e(tmp_path)
        assert result["description"] == ""


class TestExtractSubSchedule:
    def test_extracts_22a_from_parent(self, tmp_path: Path) -> None:
        """22A content is extracted from FIR2025 S22.md using the heading prefix."""
        _write_md(
            tmp_path,
            "FIR2025 S22.md",
            """\
            ## SCHEDULE 22: Taxation
            ## General Information
            Parent description.
            ## General Purpose Levy Information (22A)
            This sub-schedule covers the general purpose levy.
            ## Lower-Tier / Single-Tier Special Area Levy Information (22B)
            22B content.
        """,
        )
        result = _extract_sub_schedule(tmp_path, "22A")
        assert result["schedule"] == "22A"
        assert result["schedule_name"] == "General Purpose Levy Information"
        assert "general purpose levy" in result["description"].lower()

    def test_extracts_51a_from_parent(self, tmp_path: Path) -> None:
        """51A content is extracted using 'Schedule 51A:' prefix."""
        _write_md(
            tmp_path,
            "FIR2025 S51.md",
            """\
            ## SCHEDULE 51: Tangible Capital Assets
            ## Schedule 51A: Prior Year Balances
            Prior year balance description.
            ## Schedule 51B: Current Year
            51B content.
        """,
        )
        result = _extract_sub_schedule(tmp_path, "51A")
        assert result["schedule"] == "51A"
        assert result["schedule_name"] == "Prior Year Balances"
        assert "Prior year balance" in result["description"]

    def test_empty_result_when_heading_absent(self, tmp_path: Path) -> None:
        """Returns empty description when the sub-schedule heading is not found."""
        _write_md(
            tmp_path,
            "FIR2025 S22.md",
            """\
            ## SCHEDULE 22: Taxation
            ## General Information
            Some content with no sub-schedule heading.
        """,
        )
        result = _extract_sub_schedule(tmp_path, "22A")
        assert result["schedule"] == "22A"
        assert result["description"] == ""
        assert result["valid_from_year"] is None
        assert result["valid_to_year"] is None

    def test_falls_back_to_parent_gi_when_section_content_empty(
        self, tmp_path: Path
    ) -> None:
        """When the sub-schedule heading exists but has no body, the parent GI is used."""
        _write_md(
            tmp_path,
            "FIR2025 S51.md",
            """\
            ## SCHEDULE 51: Tangible Capital Assets
            ## General Information
            The Schedule 51 series collects net book value by function and class.
            ## Schedule 51A: By Function
            ## Column 1: Opening Balance
            Column content here.
        """,
        )
        result = _extract_sub_schedule(tmp_path, "51A")
        assert result["schedule"] == "51A"
        assert "Schedule 51 series" in result["description"]

    def test_no_fallback_when_gi_also_absent(self, tmp_path: Path) -> None:
        """When the sub-schedule heading has no body and there is no GI, description is empty."""
        _write_md(
            tmp_path,
            "FIR2025 S51.md",
            """\
            ## SCHEDULE 51: Tangible Capital Assets
            ## Schedule 51A: By Function
            ## Column 1: Opening Balance
            Column content here.
        """,
        )
        result = _extract_sub_schedule(tmp_path, "51A")
        assert result["schedule"] == "51A"
        assert result["description"] == ""


# ---------------------------------------------------------------------------
# 7. extract_schedule_record dispatcher
# ---------------------------------------------------------------------------


class TestExtractScheduleRecordDispatcher:
    """Verify that extract_schedule_record dispatches to the correct extractor."""

    _REQUIRED_KEYS = {
        "schedule",
        "schedule_name",
        "category",
        "description",
        "valid_from_year",
        "valid_to_year",
        "change_notes",
    }

    def test_sub_schedule_routes_to_sub_extractor(self, tmp_path: Path) -> None:
        """Sub-schedule codes are dispatched to _extract_sub_schedule."""
        _write_md(
            tmp_path,
            "FIR2025 S22.md",
            """\
            ## SCHEDULE 22: Taxation
            ## General Purpose Levy Information (22A)
            Sub-schedule 22A description text here.
            ## Lower-Tier / Single-Tier Special Area Levy Information (22B)
            22B content.
        """,
        )
        result = extract_schedule_record(tmp_path, "22A")
        assert result["schedule"] == "22A"
        assert self._REQUIRED_KEYS.issubset(result.keys())

    def test_schedule_53_routes_to_special_extractor(self, tmp_path: Path) -> None:
        """Schedule 53 is dispatched to its dedicated extractor."""
        _write_md(
            tmp_path,
            "FIR2025 S53.md",
            """\
            ## SCHEDULE 53: Net Financial Assets
            ## Body Section
            Overview paragraph for Schedule 53.
        """,
        )
        result = extract_schedule_record(tmp_path, "53")
        assert result["schedule"] == "53"
        assert self._REQUIRED_KEYS.issubset(result.keys())

    def test_schedule_74e_routes_to_special_extractor(self, tmp_path: Path) -> None:
        """Schedule 74E is dispatched to its dedicated extractor."""
        _write_md(
            tmp_path,
            "FIR2025 S74.md",
            """\
            ## Schedule 74E
            ## Asset Retirement Obligation Liability
            Description text for 74E.
        """,
        )
        result = extract_schedule_record(tmp_path, "74E")
        assert result["schedule"] == "74E"
        assert self._REQUIRED_KEYS.issubset(result.keys())

    def test_regular_schedule_routes_to_regular_extractor(self, tmp_path: Path) -> None:
        """A standard schedule code is dispatched to _extract_regular_schedule."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## General Information
            Revenue description text.
        """,
        )
        result = extract_schedule_record(tmp_path, "10")
        assert result["schedule"] == "10"
        assert self._REQUIRED_KEYS.issubset(result.keys())

    def test_all_results_have_null_year_fields(self, tmp_path: Path) -> None:
        """Baseline records always have valid_from_year and valid_to_year as None."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## General Information
            Description.
        """,
        )
        result = extract_schedule_record(tmp_path, "10")
        assert result["valid_from_year"] is None
        assert result["valid_to_year"] is None
        assert result["change_notes"] is None

    def test_category_set_from_schedule_categories(self, tmp_path: Path) -> None:
        """Category in result matches SCHEDULE_CATEGORIES for the given code."""
        _write_md(
            tmp_path,
            "FIR2025 S10.md",
            """\
            ## SCHEDULE 10: Revenue
            ## General Information
            Description.
        """,
        )
        result = extract_schedule_record(tmp_path, "10")
        assert result["category"] == SCHEDULE_CATEGORIES["10"]


# ---------------------------------------------------------------------------
# 8. extract_all_schedule_meta — integration with real files
# ---------------------------------------------------------------------------


class TestExtractAllScheduleMeta:
    """Tests for extract_all_schedule_meta."""

    def test_returns_31_records_from_real_files(self) -> None:
        """extract_all_schedule_meta returns exactly 31 records when the real markdown files exist."""
        markdown_dir = Path("fir_instructions/source_files/2025/markdown")
        if not markdown_dir.exists():
            pytest.skip("Real FIR2025 markdown files not found")
        records = extract_all_schedule_meta(markdown_dir)
        assert len(records) == 31
        codes = {r["schedule"] for r in records}
        assert codes == set(SCHEDULE_CATEGORIES.keys())


# ---------------------------------------------------------------------------
# 9. CSV round-trip — non-null string field branch
# ---------------------------------------------------------------------------


class TestCSVRoundTripNonNullChangeNotes:
    """Additional CSV round-trip test for the non-empty string branch of load_from_csv."""

    def test_non_null_change_notes_survive_round_trip(self, tmp_path: Path) -> None:
        """A non-empty change_notes value is preserved as a string after CSV round-trip."""
        records = [_minimal_record(change_notes="Added new line 9999.")]
        csv_path = tmp_path / "change_notes_non_null.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["change_notes"] == "Added new line 9999."


# ---------------------------------------------------------------------------
# 10. CLI commands
# ---------------------------------------------------------------------------


class TestCLICommands:
    """Tests for the Typer CLI commands using CliRunner and mocks."""

    def test_extract_baseline_schedule_meta_cmd(self) -> None:
        """extract-baseline-schedule-meta calls extract_all_schedule_meta, save_to_csv, and inserts to DB."""
        runner = CliRunner()
        fake_records = [_minimal_record()]
        module = "municipal_finances.fir_instructions.extract_schedule_meta"

        with (
            patch(f"{module}.extract_all_schedule_meta", return_value=fake_records),
            patch(f"{module}.save_to_csv"),
            patch(f"{module}.get_engine", return_value=MagicMock()),
            patch(f"{module}.insert_schedule_meta", return_value=1),
        ):
            result = runner.invoke(app, ["extract-baseline-schedule-meta"])

        assert result.exit_code == 0
        assert "1 records extracted" in result.output
        assert "Inserted 1 new rows" in result.output

    def test_extract_baseline_schedule_meta_cmd_no_db(self) -> None:
        """extract-baseline-schedule-meta with --no-load-db skips the DB insertion step."""
        runner = CliRunner()
        fake_records = [_minimal_record()]
        module = "municipal_finances.fir_instructions.extract_schedule_meta"

        with (
            patch(f"{module}.extract_all_schedule_meta", return_value=fake_records),
            patch(f"{module}.save_to_csv"),
            patch(f"{module}.insert_schedule_meta") as mock_insert,
        ):
            result = runner.invoke(
                app, ["extract-baseline-schedule-meta", "--no-load-db"]
            )

        assert result.exit_code == 0
        mock_insert.assert_not_called()

    def test_load_baseline_schedule_meta_cmd(self) -> None:
        """load-baseline-schedule-meta reads the CSV and inserts records into the DB."""
        runner = CliRunner()
        fake_records = [_minimal_record()]
        module = "municipal_finances.fir_instructions.extract_schedule_meta"

        with (
            patch(f"{module}.load_from_csv", return_value=fake_records),
            patch(f"{module}.get_engine", return_value=MagicMock()),
            patch(f"{module}.insert_schedule_meta", return_value=1),
        ):
            result = runner.invoke(app, ["load-baseline-schedule-meta"])

        assert result.exit_code == 0
        assert "1 records loaded from CSV" in result.output
        assert "Inserted 1 new rows" in result.output
