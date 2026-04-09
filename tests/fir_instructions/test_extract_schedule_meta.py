"""Tests for fir_instructions/extract_schedule_meta.py.

These tests cover schedule metadata extraction, database insertion, and CSV
round-trip.  DB tests require the test PostgreSQL container (localhost:5433).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from municipal_finances.fir_instructions.extract_schedule_meta import (
    SCHEDULE_CATEGORIES,
    SUB_SCHEDULE_PARENTS,
    _SUB_SCHEDULE_HEADINGS,
    _SUB_SCHEDULE_NEXT_HEADINGS,
    _INTERNAL_OFFSET_KEYS,
    _clean_text,
    _count_leading_spaces,
    _extract_description_two_pass,
    _extract_schedule_name_from_body,
    _extract_sub_schedule_name,
    _find_body_start,
    _find_gi_heading,
    _get_section_end,
    _has_dot_leaders,
    _heading_matches,
    _is_page_header,
    _parse_toc,
    _strip_dot_leaders,
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
        non_null = [r["schedule"] for r in records if r.get("valid_from_year") is not None]
        assert non_null == [], f"Unexpected valid_from_year on: {non_null}"

    def test_valid_to_year_is_null_on_all_rows(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Baseline rows must have valid_to_year = NULL."""
        non_null = [r["schedule"] for r in records if r.get("valid_to_year") is not None]
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
        too_short = [r["schedule"] for r in records if len(r.get("description", "")) < 50]
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

    def test_insert_all_31_baseline_records(
        self, engine, session: Session
    ) -> None:
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

    def test_no_required_fields_null_in_db(
        self, engine, session: Session
    ) -> None:
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
# 4. Text-processing helper functions
# ---------------------------------------------------------------------------

_FIR2025_PAGE_HEADER = "FIR2025             Page |1           Schedule 10"
_FIR2025_PAGE_HEADER_MID = "FIR2025             Page |3           Schedule 10"
_FIR2025_SPACED_HEADER = "FIR2025             P a g e | 5           Schedule 74"


class TestIsPageHeader:
    def test_normal_2025_header(self) -> None:
        """A standard FIR2025 'Page |1' header line is recognised as a page header."""
        assert _is_page_header(_FIR2025_PAGE_HEADER) is True

    def test_mid_page_2025_header(self) -> None:
        """A FIR2025 header on a page other than page 1 is also recognised."""
        assert _is_page_header(_FIR2025_PAGE_HEADER_MID) is True

    def test_spaced_page_header(self) -> None:
        """The spaced 'P a g e' variant used in some sub-sections is matched."""
        assert _is_page_header(_FIR2025_SPACED_HEADER) is True

    def test_regular_content_line(self) -> None:
        """A normal content line that contains no page-header pattern returns False."""
        assert _is_page_header("This line contains municipal finance data.") is False

    def test_empty_string(self) -> None:
        """An empty string does not match any page-header pattern."""
        assert _is_page_header("") is False

    def test_partial_match_without_page_number(self) -> None:
        """A line with 'FIR2025' and a schedule but no 'Page' keyword returns False."""
        assert _is_page_header("FIR2025   Schedule 10") is False


class TestHasDotLeaders:
    def test_dot_leaders_with_page_number(self) -> None:
        """A TOC line with 4+ dots followed by a page number is detected as a dot-leader line."""
        assert _has_dot_leaders("General Instructions ........ 5") is True

    def test_three_dots_minimum(self) -> None:
        """Three consecutive dots followed by a page number also qualifies as a dot-leader line."""
        assert _has_dot_leaders("Section heading ... 12") is True

    def test_two_dots_not_enough(self) -> None:
        """Two consecutive dots do not meet the minimum threshold; returns False."""
        assert _has_dot_leaders("Section heading .. 12") is False

    def test_no_dots(self) -> None:
        """A heading with no dots at all is not a dot-leader line."""
        assert _has_dot_leaders("General Instructions") is False

    def test_dots_without_trailing_number(self) -> None:
        """Dots that are not followed by a page number are not dot-leader lines."""
        assert _has_dot_leaders("Some text ......") is False

    def test_dots_with_spaces_before_number(self) -> None:
        """Dots followed by whitespace and then a page number are still detected correctly."""
        assert _has_dot_leaders("Section ....   8") is True


class TestStripDotLeaders:
    def test_strips_dots_and_number(self) -> None:
        """Dot leaders and trailing page number are removed, leaving the heading text."""
        assert _strip_dot_leaders("General Instructions ........ 5") == "General Instructions"

    def test_strips_dots_with_multidigit_number(self) -> None:
        """Multi-digit page numbers are removed along with their dot leaders."""
        assert _strip_dot_leaders("Some heading .... 12") == "Some heading"

    def test_preserves_text_without_dots(self) -> None:
        """When called on a line without dot leaders, the original text is returned unchanged."""
        result = _strip_dot_leaders("Plain text")
        assert result == "Plain text"


class TestCountLeadingSpaces:
    def test_no_leading_spaces(self) -> None:
        """A string with no leading spaces returns 0."""
        assert _count_leading_spaces("text") == 0

    def test_two_leading_spaces(self) -> None:
        """Two leading spaces returns 2, used to detect TOC indentation level."""
        assert _count_leading_spaces("  text") == 2

    def test_four_leading_spaces(self) -> None:
        """Four leading spaces returns 4."""
        assert _count_leading_spaces("    indented") == 4

    def test_all_spaces(self) -> None:
        """A string that is entirely spaces returns the full count."""
        assert _count_leading_spaces("    ") == 4

    def test_empty_string(self) -> None:
        """An empty string has zero leading spaces."""
        assert _count_leading_spaces("") == 0


class TestCleanText:
    def test_removes_page_headers(self) -> None:
        """Page header lines (FIR2025 Page |N Schedule XX) are stripped from the output."""
        lines = [
            "First paragraph line.\n",
            f"{_FIR2025_PAGE_HEADER}\n",
            "Second paragraph line.\n",
        ]
        result = _clean_text(lines)
        assert "Page |1" not in result
        assert "First paragraph line." in result
        assert "Second paragraph line." in result

    def test_removes_form_feed_characters(self) -> None:
        """Form-feed characters (\\x0c) produced by pdftotext are stripped."""
        lines = ["\x0cSome content\n"]
        result = _clean_text(lines)
        assert "\x0c" not in result
        assert "Some content" in result

    def test_collapses_three_or_more_blank_lines(self) -> None:
        """Three or more consecutive blank lines are collapsed to at most two newlines."""
        lines = ["line one\n", "\n", "\n", "\n", "\n", "line two\n"]
        result = _clean_text(lines)
        # At most two consecutive newlines (one blank line) between content
        assert "\n\n\n" not in result
        assert "line one" in result
        assert "line two" in result

    def test_two_consecutive_blank_lines_preserved(self) -> None:
        """Exactly two consecutive blank lines are preserved (not collapsed)."""
        lines = ["line one\n", "\n", "\n", "line two\n"]
        result = _clean_text(lines)
        assert "line one\n\nline two" in result

    def test_stops_at_cover_page_sentinel(self) -> None:
        """Lines starting with 'YYYY Financial Information Return' are discarded."""
        lines = [
            "Good content.\n",
            "2025 Financial Information Return\n",
            "This should not appear.\n",
        ]
        result = _clean_text(lines)
        assert "Good content." in result
        assert "This should not appear." not in result

    def test_strips_trailing_whitespace_per_line(self) -> None:
        """Trailing spaces on each line (common in pdftotext output) are stripped."""
        lines = ["text with trailing spaces   \n"]
        result = _clean_text(lines)
        assert result == "text with trailing spaces"

    def test_empty_input(self) -> None:
        """An empty list of lines produces an empty string."""
        assert _clean_text([]) == ""


class TestHeadingMatches:
    def test_exact_match(self) -> None:
        """A body line that exactly equals the heading text returns True."""
        assert _heading_matches("Carry Forwards", "Carry Forwards") is True

    def test_case_insensitive(self) -> None:
        """Comparison is case-insensitive; mixed-case variants of the same heading match."""
        assert _heading_matches("carry forwards", "Carry Forwards") is True
        assert _heading_matches("CARRY FORWARDS", "Carry Forwards") is True

    def test_prefix_match(self) -> None:
        """Body line that starts with the heading text (even with extra content) matches."""
        assert _heading_matches("Carry Forwards (additional text)", "Carry Forwards") is True

    def test_no_match(self) -> None:
        """A body line that does not start with the heading text returns False."""
        assert _heading_matches("Completely Different", "Carry Forwards") is False

    def test_empty_body_line(self) -> None:
        """An empty body line never matches any heading."""
        assert _heading_matches("", "Carry Forwards") is False

    def test_uses_first_40_chars_of_heading(self) -> None:
        """Only the first 40 characters of the heading are compared."""
        long_heading = "A" * 50
        body_line = "A" * 40 + "different suffix here"
        # body_line[:40] == heading[:40], so this should match
        assert _heading_matches(body_line, long_heading) is True


# ---------------------------------------------------------------------------
# 5. Section-boundary helpers
# ---------------------------------------------------------------------------


class TestGetSectionEnd:
    def _make_offsets(self) -> dict[str, int]:
        return {"10": 0, "22": 100, "51": 200, "74": 300, "74A": 320, "74B": 340, "74E": 400}

    def test_returns_start_of_next_non_internal_schedule(self) -> None:
        """Section end is the line number where the next real schedule begins."""
        offsets = self._make_offsets()
        # After "10" the next non-internal is "22" at 100
        assert _get_section_end("10", offsets, 1000) == 100

    def test_skips_internal_offset_keys(self) -> None:
        """Internal keys like '74A'–'74D' are skipped when searching for the section end."""
        offsets = self._make_offsets()
        # After "74" the immediate entries are "74A" and "74B" (internal), then "74E"
        assert _get_section_end("74", offsets, 1000) == 400

    def test_last_schedule_returns_n_lines(self) -> None:
        """For the last schedule in the file, n_lines is returned as the section end."""
        offsets = self._make_offsets()
        assert _get_section_end("74E", offsets, 500) == 500

    def test_sub_schedule_delegates_to_parent(self) -> None:
        """Sub-schedules do not have their own offset; end is computed from the parent's offset."""
        offsets = {"22": 100, "51": 200, "61": 300, "70": 400}
        # 22A's parent is "22"; section end for "22" is 200 (start of "51")
        assert _get_section_end("22A", offsets, 1000) == 200
        assert _get_section_end("51A", offsets, 1000) == 300
        assert _get_section_end("61B", offsets, 1000) == 400

    def test_code_not_in_offsets_returns_n_lines(self) -> None:
        """An unrecognised schedule code that is not in the offset map returns n_lines."""
        offsets = {"10": 0}
        assert _get_section_end("99", offsets, 999) == 999


class TestFindBodyStart:
    def _lines(self, raw: str) -> list[str]:
        return [line + "\n" for line in raw.splitlines()]

    def test_finds_schedule_title_in_body(self) -> None:
        """The first uppercase 'SCHEDULE XX:' line that is not a TOC entry is returned."""
        lines = self._lines(
            "cover page stuff\n"
            "Table of Contents\n"
            "Schedule 10: Revenue ........ 2\n"
            "General Information ........ 3\n"
            "SCHEDULE 10: Consolidated Statement of Operations: Revenue\n"
            "body content"
        )
        result = _find_body_start(lines, 0, len(lines))
        assert lines[result].strip().startswith("SCHEDULE 10:")

    def test_skips_toc_entries_with_dot_leaders(self) -> None:
        """A 'SCHEDULE XX:' line followed by a dot-leader continuation is a TOC entry."""
        lines = self._lines(
            "SCHEDULE 10: Consolidated Statement of Operations:\n"
            "  Revenue ........ 2\n"           # dot-leader continuation → TOC entry
            "SCHEDULE 10: Consolidated Statement of Operations: Revenue\n"  # real body
            "body content"
        )
        result = _find_body_start(lines, 0, len(lines))
        # Should return the second SCHEDULE line (index 2), not the first (index 0)
        assert result == 2

    def test_returns_section_start_when_not_found(self) -> None:
        """When no 'SCHEDULE XX:' body line is found, section_start is returned as a fallback."""
        lines = self._lines("no schedule title here\njust text\n")
        assert _find_body_start(lines, 0, len(lines)) == 0

    def test_respects_section_end_boundary(self) -> None:
        """The search stops at section_end; a 'SCHEDULE XX:' line beyond it is not returned."""
        lines = self._lines(
            "preamble\n"
            "preamble\n"
            "SCHEDULE 10: Revenue\n"  # index 2 — outside the [0,2) range
        )
        result = _find_body_start(lines, 0, 2)
        assert result == 0  # Not found within [0, 2)


# ---------------------------------------------------------------------------
# 6. TOC parsing
# ---------------------------------------------------------------------------


class TestParseToc:
    def _lines(self, raw: str) -> list[str]:
        return [line + "\n" for line in raw.splitlines()]

    def test_empty_section_returns_none_none(self) -> None:
        """A section with no TOC entries produces (None, None) for both outputs."""
        lines = self._lines("   \n   \n")
        name, next_sec = _parse_toc(lines, 0, len(lines))
        assert name is None
        assert next_sec is None

    def test_extracts_schedule_name_from_first_toc_entry(self) -> None:
        """The schedule name is taken from the first TOC entry after stripping the code prefix."""
        lines = self._lines(
            "SCHEDULE 10: Consolidated Statement of Operations: Revenue ........ 1\n"
            "  General Information ........ 2\n"
            "  Carry Forwards ........ 5\n"
        )
        name, _ = _parse_toc(lines, 0, len(lines))
        assert name == "Consolidated Statement of Operations: Revenue"

    def test_finds_next_section_after_general_information(self) -> None:
        """The first TOC entry after 'General Information' is returned as next_section."""
        lines = self._lines(
            "SCHEDULE 10: Revenue ........ 1\n"
            "  General Information ........ 2\n"
            "  Carry Forwards ........ 5\n"
        )
        _, next_sec = _parse_toc(lines, 0, len(lines))
        assert next_sec == "Carry Forwards"

    def test_finds_next_section_after_general_instructions(self) -> None:
        """'General Instructions' is treated identically to 'General Information' for next_section detection."""
        lines = self._lines(
            "SCHEDULE 22: Taxation ........ 1\n"
            "  General Instructions ........ 2\n"
            "  Line Descriptions ........ 6\n"
        )
        _, next_sec = _parse_toc(lines, 0, len(lines))
        assert next_sec == "Line Descriptions"

    def test_gi_as_last_entry_returns_none_for_next_section(self) -> None:
        """When 'General Information' is the last TOC entry, next_section is None."""
        lines = self._lines(
            "SCHEDULE 53: Net Financial Assets ........ 1\n"
            "  General Information ........ 2\n"
        )
        _, next_sec = _parse_toc(lines, 0, len(lines))
        assert next_sec is None

    def test_no_gi_entry_returns_none_for_next_section(self) -> None:
        """When the TOC contains no 'General Information' entry, next_section is None."""
        lines = self._lines(
            "SCHEDULE 54: Cash Flow ........ 1\n"
            "  Line Descriptions ........ 3\n"
        )
        _, next_sec = _parse_toc(lines, 0, len(lines))
        assert next_sec is None

    def test_skips_page_headers_in_toc(self) -> None:
        """Page headers embedded in the TOC region are ignored."""
        lines = self._lines(
            "SCHEDULE 10: Revenue ........ 1\n"
            f"{_FIR2025_PAGE_HEADER}\n"
            "  General Information ........ 2\n"
            "  Carry Forwards ........ 5\n"
        )
        name, next_sec = _parse_toc(lines, 0, len(lines))
        assert name == "Revenue"
        assert next_sec == "Carry Forwards"

    def test_multiline_toc_entry_joined(self) -> None:
        """A TOC entry split over two lines is joined before dot-leader stripping."""
        lines = self._lines(
            "SCHEDULE 10: Consolidated Statement of Operations:\n"
            "  Revenue ........ 1\n"
            "  General Information ........ 2\n"
        )
        name, _ = _parse_toc(lines, 0, len(lines))
        assert name is not None
        assert "Revenue" in name


# ---------------------------------------------------------------------------
# 7. GI heading finder and description extractor
# ---------------------------------------------------------------------------


class TestFindGiHeading:
    def _lines(self, raw: str) -> list[str]:
        return [line + "\n" for line in raw.splitlines()]

    def test_finds_general_information(self) -> None:
        """A line reading 'General Information' is found and its line index returned."""
        lines = self._lines("intro\nGeneral Information\ncontent")
        assert _find_gi_heading(lines, 0, len(lines)) == 1

    def test_finds_general_instructions(self) -> None:
        """A line reading 'General Instructions' is also accepted as a GI heading."""
        lines = self._lines("intro\nGeneral Instructions\ncontent")
        assert _find_gi_heading(lines, 0, len(lines)) == 1

    def test_case_insensitive(self) -> None:
        """GI heading detection is case-insensitive (all-caps variant matches)."""
        lines = self._lines("intro\nGENERAL INFORMATION\ncontent")
        assert _find_gi_heading(lines, 0, len(lines)) == 1

    def test_not_found_returns_none(self) -> None:
        """When neither 'General Information' nor 'General Instructions' is found, None is returned."""
        lines = self._lines("intro\nsome other heading\ncontent")
        assert _find_gi_heading(lines, 0, len(lines)) is None

    def test_respects_start_end_range(self) -> None:
        """The search only examines lines within [start, end); lines outside are ignored."""
        lines = self._lines("General Information\nintro\nGeneral Information\ncontent")
        # Search in [2, 4) — should find the second occurrence at index 2
        assert _find_gi_heading(lines, 2, 4) == 2
        # Search in [1, 2) — should not find anything
        assert _find_gi_heading(lines, 1, 2) is None


class TestExtractDescriptionTwoPass:
    """Tests for the two-pass boundary detection algorithm."""

    def _lines(self, raw: str) -> list[str]:
        return [line + "\n" for line in raw.splitlines()]

    def test_no_next_section_returns_all_content(self) -> None:
        """When next_section is None, all content from gi_line to section_end is included."""
        lines = self._lines("General Information\npara one\npara two")
        gi_line = 0
        result = _extract_description_two_pass(lines, gi_line, None, len(lines))
        assert "para one" in result
        assert "para two" in result

    def test_pass1_stops_at_page_header_before_next_section(self) -> None:
        """Pass 1: next_section appearing right after a page header truncates before the header."""
        lines = self._lines(
            "General Information\n"
            "good paragraph text\n"
            f"{_FIR2025_PAGE_HEADER}\n"
            "Carry Forwards\n"
            "should not be included"
        )
        gi_line = 0
        result = _extract_description_two_pass(lines, gi_line, "Carry Forwards", len(lines))
        assert "good paragraph text" in result
        assert "Carry Forwards" not in result
        assert "should not be included" not in result

    def test_pass2_fallback_stops_mid_page(self) -> None:
        """Pass 2: next_section appearing without a preceding page header still stops extraction."""
        lines = self._lines(
            "General Information\n"
            "good paragraph text\n"
            "Carry Forwards\n"
            "should not be included"
        )
        gi_line = 0
        result = _extract_description_two_pass(lines, gi_line, "Carry Forwards", len(lines))
        assert "good paragraph text" in result
        assert "Carry Forwards" not in result

    def test_pass1_does_not_stop_at_inline_reference(self) -> None:
        """Pass 1 does not truncate when next_section appears inline (not after a page header)."""
        # next_section text appears in the middle of a paragraph (not at the start of
        # the first non-blank line after a page header) — pass 1 should keep going.
        lines = self._lines(
            "General Information\n"
            "See the Carry Forwards section for details on this topic.\n"
            "More good content here.\n"
        )
        gi_line = 0
        result = _extract_description_two_pass(lines, gi_line, "Carry Forwards", len(lines))
        # Because "Carry Forwards" is not the start of the line, pass 2 won't
        # stop there either (heading_matches checks startswith), so all content included.
        assert "See the Carry Forwards section" in result
        assert "More good content here." in result

    def test_next_section_never_found_returns_all_content(self) -> None:
        """When next_section is specified but never appears, all content up to section_end is kept."""
        lines = self._lines("General Information\nparagraph text\nmore text")
        gi_line = 0
        result = _extract_description_two_pass(lines, gi_line, "Nonexistent Section", len(lines))
        assert "paragraph text" in result
        assert "more text" in result


# ---------------------------------------------------------------------------
# 8. Schedule name extraction helpers
# ---------------------------------------------------------------------------


class TestExtractScheduleNameFromBody:
    def _lines(self, raw: str) -> list[str]:
        return [line + "\n" for line in raw.splitlines()]

    def test_single_line_title(self) -> None:
        """A single-line 'SCHEDULE XX: Name' body entry returns the name after the colon."""
        lines = self._lines(
            "SCHEDULE 10: Consolidated Statement of Operations: Revenue\n"
            "\n"
            "body text"
        )
        result = _extract_schedule_name_from_body(lines, 0, len(lines))
        assert result == "Consolidated Statement of Operations: Revenue"

    def test_multiline_title_joined_with_space(self) -> None:
        """A title that wraps onto the next line is joined with a space before returning."""
        lines = self._lines(
            "SCHEDULE 10: Consolidated Statement of\n"
            "Operations: Revenue\n"
            "\n"
            "body text"
        )
        result = _extract_schedule_name_from_body(lines, 0, len(lines))
        assert result == "Consolidated Statement of Operations: Revenue"

    def test_stops_at_blank_line(self) -> None:
        """Title collection stops at the first blank line; text after it is not included."""
        lines = self._lines("SCHEDULE 10: Revenue\n\nbody text")
        result = _extract_schedule_name_from_body(lines, 0, len(lines))
        assert result == "Revenue"

    def test_stops_at_general_information_heading(self) -> None:
        """Title collection stops when a 'General Information' heading is encountered."""
        lines = self._lines(
            "SCHEDULE 10: Revenue\n"
            "General Information\n"
            "paragraph"
        )
        result = _extract_schedule_name_from_body(lines, 0, len(lines))
        assert result == "Revenue"

    def test_case_insensitive_schedule_prefix(self) -> None:
        """Lowercase 'schedule XX:' is also recognised as the body title line."""
        lines = self._lines("schedule 10: Revenue\n\nbody text")
        result = _extract_schedule_name_from_body(lines, 0, len(lines))
        assert result == "Revenue"


class TestExtractSubScheduleName:
    def test_strips_schedule_prefix(self) -> None:
        """A heading of the form 'Schedule XX: Name' has the prefix stripped, returning Name."""
        result = _extract_sub_schedule_name("Schedule 51A: Tangible Capital Assets", "51A")
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
# 9. extract_schedule_record dispatcher
# ---------------------------------------------------------------------------


class TestExtractScheduleRecordDispatcher:
    """Verify that extract_schedule_record dispatches to the correct extractor.

    Uses a synthetic minimal text file and offset map so tests run without any
    real PDF files.  We only verify that the returned dict has the correct
    structure and the 'schedule' key is set; deeper content is validated by
    the baseline CSV tests above.
    """

    _REQUIRED_KEYS = {
        "schedule", "schedule_name", "category",
        "description", "valid_from_year", "valid_to_year", "change_notes",
    }

    def _minimal_lines(self, code: str) -> list[str]:
        """Return a list of lines that satisfies the extractor for a given code."""
        return [
            f"FIR2025   Page |1   Schedule {code}\n",
            f"SCHEDULE {code}: Some Schedule Name\n",
            "\n",
            "General Information\n",
            "This is the description text for this schedule.\n",
            "\n",
        ]

    def test_sub_schedule_routes_to_sub_extractor(self) -> None:
        """Sub-schedule codes are dispatched to _extract_sub_schedule."""
        # Build minimal lines that include the parent and sub-schedule headings
        lines = [
            "FIR2025   Page |1   Schedule 22\n",
            "SCHEDULE 22: Taxation\n",
            "\n",
            "General Information\n",
            "Parent description.\n",
            "\n",
            "General Purpose Levy Information (22A)\n",
            "Sub-schedule 22A description text here.\n",
            "Lower-Tier / Single-Tier Special Area Levy Information (22B)\n",
        ]
        offsets = {"22": 0}
        result = extract_schedule_record(lines, offsets, "22A")
        assert result["schedule"] == "22A"
        assert self._required_keys_present(result)

    def test_schedule_53_routes_to_special_extractor(self) -> None:
        """Schedule 53 is dispatched to its dedicated extractor."""
        lines = [
            "FIR2025   Page |1   Schedule 53\n",
            "SCHEDULE 53: Consolidated Statement of Change in Net Financial Assets\n",
            "\n",
            "This is an overview paragraph for Schedule 53.\n",
            "\n",
            "Line 0220 some line description\n",
        ]
        offsets = {"53": 0}
        result = extract_schedule_record(lines, offsets, "53")
        assert result["schedule"] == "53"
        assert self._required_keys_present(result)

    def test_schedule_74e_routes_to_special_extractor(self) -> None:
        """Schedule 74E is dispatched to its dedicated extractor."""
        lines = [
            "FIR2025   Page |1   Schedule 74E\n",
            "Asset Retirement Obligation Liability\n",
            "Description text for 74E.\n",
            "\n",
            "Column 1 - some column description\n",
        ]
        offsets = {"74E": 0}
        result = extract_schedule_record(lines, offsets, "74E")
        assert result["schedule"] == "74E"
        assert self._required_keys_present(result)

    def test_regular_schedule_routes_to_regular_extractor(self) -> None:
        """A standard schedule code is dispatched to _extract_regular_schedule."""
        lines = [
            "FIR2025   Page |1   Schedule 10\n",
            "SCHEDULE 10: Revenue ........ 1\n"
            "  General Information ........ 2\n",
            "SCHEDULE 10: Revenue\n",
            "\n",
            "General Information\n",
            "Revenue description text.\n",
            "\n",
        ]
        offsets = {"10": 0}
        result = extract_schedule_record(lines, offsets, "10")
        assert result["schedule"] == "10"
        assert self._required_keys_present(result)

    def test_all_results_have_null_year_fields(self) -> None:
        """Baseline records always have valid_from_year and valid_to_year as None."""
        lines = self._minimal_lines("10")
        offsets = {"10": 0}
        result = extract_schedule_record(lines, offsets, "10")
        assert result["valid_from_year"] is None
        assert result["valid_to_year"] is None
        assert result["change_notes"] is None

    def test_category_set_from_schedule_categories(self) -> None:
        """Category in result matches SCHEDULE_CATEGORIES for the given code."""
        lines = self._minimal_lines("10")
        offsets = {"10": 0}
        result = extract_schedule_record(lines, offsets, "10")
        assert result["category"] == SCHEDULE_CATEGORIES["10"]

    @staticmethod
    def _required_keys_present(result: dict) -> bool:
        required = {
            "schedule", "schedule_name", "category",
            "description", "valid_from_year", "valid_to_year", "change_notes",
        }
        return required.issubset(result.keys())
