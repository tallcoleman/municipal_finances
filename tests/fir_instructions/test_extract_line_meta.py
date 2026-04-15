"""Tests for fir_instructions/extract_line_meta.py.

Covers heading parsers, content detectors, FC extraction, per-schedule
extraction, merge logic, CSV round-trip, DB insertion, and CLI commands.

DB tests require the test PostgreSQL container (localhost:5433).
Baseline CSV tests are skipped when the CSV has not yet been generated.
"""

# postpone evaluation of typing annotations
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from municipal_finances.fir_instructions.extract_line_meta import (
    _CSV_FIELDS,
    _detect_applicability,
    _detect_auto_calculated,
    _detect_subtotal,
    _extract_fc_description,
    _extract_fc_lines,
    _extract_per_schedule_lines,
    _get_schedule_sections,
    _is_functional_area,
    _parse_line_heading,
    app,
    extract_line_records,
    insert_line_meta,
    load_from_csv,
    save_to_csv,
)
from municipal_finances.fir_instructions.extract_schedule_meta import (
    SCHEDULE_CATEGORIES,
)
from municipal_finances.models import FIRLineMeta, FIRScheduleMeta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPECTED_CODES: frozenset[str] = frozenset(SCHEDULE_CATEGORIES.keys())
_BASELINE_CSV = Path("fir_instructions/exports/baseline_line_meta.csv")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_line_record(**overrides: Any) -> dict[str, Any]:
    """Build a minimal valid line metadata record."""
    base: dict[str, Any] = {
        "schedule": "10",
        "line_id": "0299",
        "line_name": "Taxation Own Purposes",
        "section": "Revenue",
        "description": "Test description.",
        "is_subtotal": False,
        "is_auto_calculated": False,
        "carry_forward_from": None,
        "applicability": None,
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


def _insert_schedule_meta_for_test(engine: Any, schedules: list[str]) -> None:
    """Insert minimal schedule rows so line meta FK can be resolved."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows = [
        {
            "schedule": s,
            "schedule_name": f"Schedule {s}",
            "category": "Revenue",
            "description": "Test.",
            "valid_from_year": None,
            "valid_to_year": None,
            "change_notes": None,
        }
        for s in schedules
    ]
    with Session(engine) as sess:
        stmt = pg_insert(FIRScheduleMeta).values(rows).on_conflict_do_nothing()
        sess.execute(stmt)
        sess.commit()


# ---------------------------------------------------------------------------
# 1. Heading parsers
# ---------------------------------------------------------------------------


class TestParseLineHeading:
    def test_standard_dash_separator(self) -> None:
        """'Line 0299 - Taxation Own Purposes' parses to (id, name)."""
        result = _parse_line_heading("Line 0299 - Taxation Own Purposes")
        assert result == ("0299", "Taxation Own Purposes")

    def test_em_dash_separator(self) -> None:
        """Em-dash separator is handled."""
        result = _parse_line_heading("Line 0410 \u2014 Fire")
        assert result == ("0410", "Fire")

    def test_en_dash_separator(self) -> None:
        """En-dash separator is handled."""
        result = _parse_line_heading("Line 0812 \u2013 Wastewater")
        assert result == ("0812", "Wastewater")

    def test_space_only_separator(self) -> None:
        """'Line 0812 Wastewater Treatment' (no dash) parses correctly."""
        result = _parse_line_heading("Line 0812 Wastewater Treatment and Disposal")
        assert result is not None
        assert result[0] == "0812"
        assert result[1] == "Wastewater Treatment and Disposal"

    def test_range_line_returns_first_id(self) -> None:
        """'Lines 0696 to 0698 - Other' returns only the first line_id."""
        result = _parse_line_heading("Lines 0696 to 0698 - Other")
        assert result is not None
        assert result[0] == "0696"
        assert result[1] == "Other"

    def test_trailing_colon_stripped(self) -> None:
        """Trailing colon is stripped from line_name."""
        result = _parse_line_heading("Line 9910 - Total:")
        assert result is not None
        assert result[1] == "Total"

    def test_non_line_heading_returns_none(self) -> None:
        """A non-line heading returns None."""
        assert _parse_line_heading("General Information") is None
        assert _parse_line_heading("Revenue: Property Tax") is None
        assert _parse_line_heading("GENERAL GOVERNMENT") is None

    def test_alphanumeric_line_id(self) -> None:
        """A line with an alphanumeric ID (e.g. '000A') is parsed correctly."""
        result = _parse_line_heading("Line 000A - Other Assets")
        assert result is not None
        assert result[0] == "000A"


class TestIsFunctionalArea:
    def test_all_caps_two_words(self) -> None:
        """'GENERAL GOVERNMENT' is detected as a functional area."""
        assert _is_functional_area("GENERAL GOVERNMENT") is True

    def test_all_caps_with_ampersand(self) -> None:
        """'PARKS & RECREATION' is detected (ampersand allowed)."""
        assert _is_functional_area("PARKS & RECREATION") is True

    def test_mixed_case_not_detected(self) -> None:
        """'Revenue: Property Tax' is not a functional area."""
        assert _is_functional_area("Revenue: Property Tax") is False

    def test_line_heading_not_detected(self) -> None:
        """A line heading is never detected as a functional area."""
        assert _is_functional_area("Line 0299 - Taxation Own Purposes") is False

    def test_single_word(self) -> None:
        """A single all-caps word (like a schedule code) should not match."""
        # Single words starting with one capital letter don't fit our typical pattern,
        # but "TRANSPORTATION" (all caps) would match. Test mixed-case word instead.
        assert _is_functional_area("General") is False


# ---------------------------------------------------------------------------
# 2. Content detectors
# ---------------------------------------------------------------------------


class TestExtractFCDescription:
    def test_flat_body_text_in_description(self, tmp_path: Path) -> None:
        """Flat body text with no sub-headings is returned as a single block."""
        sections = [
            ("Line 0410 - Fire", ["Includes fire stations, fire suppression."]),
            ("PROTECTION SERVICES", []),
        ]
        result = _extract_fc_description(sections, 0, 1)
        assert "fire stations" in result

    def test_sub_headings_become_blocks(self, tmp_path: Path) -> None:
        """Sub-heading sections are formatted as 'heading\\nbody' blocks."""
        sections = [
            ("Line 0421 - Court Security", []),
            ("Booking and Detention", ["Includes booking facilities."]),
            ("Line 0430 - Other", []),
        ]
        result = _extract_fc_description(sections, 0, 2)
        assert "Booking and Detention" in result
        assert "booking facilities" in result

    def test_exclude_language_preserved_in_description(self) -> None:
        """Lines matching 'do not include' remain in the returned text."""
        sections = [
            (
                "Line 0410 - Fire",
                [
                    "Includes fire suppression.",
                    "Do not include police services here.",
                ],
            ),
            ("NEXT", []),
        ]
        result = _extract_fc_description(sections, 0, 1)
        assert "Do not include" in result
        assert "fire suppression" in result

    def test_excludes_heading_preserved_in_description(self) -> None:
        """Lines starting with 'Excludes:' remain in the returned text."""
        sections = [
            (
                "Line 0260 - Support",
                [
                    "General support services.",
                    "Excludes: legal services which belong in Schedule 20.",
                ],
            ),
            ("NEXT", []),
        ]
        result = _extract_fc_description(sections, 0, 1)
        assert "Excludes:" in result

    def test_empty_range_returns_empty_string(self) -> None:
        """When start >= end, an empty string is returned."""
        sections = [("Line 0299 - Tax", ["content"])]
        result = _extract_fc_description(sections, 0, 0)
        assert result == ""

    def test_should_not_be_reported_preserved_in_description(self) -> None:
        """Sentences with 'should not be reported' remain in the returned text."""
        sections = [
            (
                "Line 0250 - Other",
                [
                    "Grants for recreation.",
                    "Capital grants should not be reported here.",
                ],
            ),
            ("END", []),
        ]
        result = _extract_fc_description(sections, 0, 1)
        assert "should not be reported" in result


class TestDetectAutoCalculated:
    def test_automatically_carried_forward(self) -> None:
        """'automatically carried forward from SLC X Y Z' sets both flag and ref."""
        is_auto, carry = _detect_auto_calculated(
            "This line is automatically carried forward from SLC 12 9910 05."
        )
        assert is_auto is True
        assert carry == "12 9910 05"

    def test_auto_populated(self) -> None:
        """'auto-populated' triggers auto flag."""
        is_auto, carry = _detect_auto_calculated("This field is auto-populated.")
        assert is_auto is True

    def test_pre_populated(self) -> None:
        """'pre-populated' triggers auto flag."""
        is_auto, carry = _detect_auto_calculated(
            "Amount is pre-populated from prior year."
        )
        assert is_auto is True

    def test_not_auto_calculated(self) -> None:
        """Normal description text returns (False, None)."""
        is_auto, carry = _detect_auto_calculated("Report all tax revenue here.")
        assert is_auto is False
        assert carry is None

    def test_auto_without_slc_returns_none_ref(self) -> None:
        """Auto flag set but no SLC pattern returns None for carry_forward_from."""
        is_auto, carry = _detect_auto_calculated("This is automatically calculated.")
        assert is_auto is True
        assert carry is None


class TestDetectSubtotal:
    def test_subtotal_in_name(self) -> None:
        """Line named 'Subtotal' is flagged."""
        is_sub, notes = _detect_subtotal("9910", "Subtotal", "")
        assert is_sub is True

    def test_total_in_name(self) -> None:
        """Line named 'Total Revenue' is flagged."""
        is_sub, notes = _detect_subtotal("9940", "Total Revenue", "")
        assert is_sub is True

    def test_9xxx_line_id_pattern(self) -> None:
        """A line_id starting with 9 is flagged as subtotal."""
        is_sub, notes = _detect_subtotal("9810", "Other Totals", "")
        assert is_sub is True

    def test_9xxx_adds_change_notes(self) -> None:
        """Inferred subtotal from line_id pattern adds a change_notes value."""
        is_sub, notes = _detect_subtotal("9810", "Aggregate", "")
        assert notes is not None
        assert "inferred" in notes.lower()

    def test_sum_of_lines_in_text(self) -> None:
        """'sum of lines' in description flags the line as subtotal."""
        is_sub, notes = _detect_subtotal(
            "0299", "Revenue Total", "Sum of lines 0210 to 0298."
        )
        assert is_sub is True

    def test_regular_line_not_subtotal(self) -> None:
        """A regular line is not flagged."""
        is_sub, notes = _detect_subtotal("0410", "Fire", "Fire protection services.")
        assert is_sub is False
        assert notes is None

    def test_non_9xxx_not_flagged_from_id_alone(self) -> None:
        """A line_id of '0410' (not starting with 9) is not inferred as subtotal."""
        is_sub, notes = _detect_subtotal("0410", "Fire", "")
        assert is_sub is False


class TestDetectApplicability:
    def test_upper_tier_only(self) -> None:
        """'upper-tier only' returns the standardised upper-tier string."""
        result = _detect_applicability("Upper-tier only municipalities report here.")
        assert result == "Upper-tier municipalities only"

    def test_lower_tier_only(self) -> None:
        """'lower-tier only' returns the standardised lower-tier string."""
        result = _detect_applicability("Lower-tier only municipalities report here.")
        assert result == "Lower-tier municipalities only"

    def test_city_of_toronto(self) -> None:
        """'City of Toronto' returns the City of Toronto restriction."""
        result = _detect_applicability(
            "City of Toronto reports using a different form."
        )
        assert result == "City of Toronto only"

    def test_no_restriction_returns_none(self) -> None:
        """Text without restrictions returns None."""
        result = _detect_applicability("Report all tax revenue here.")
        assert result is None


# ---------------------------------------------------------------------------
# 3. Functional Categories extraction (unit — tmp_path mock files)
# ---------------------------------------------------------------------------


class TestExtractFCLines:
    def _write_fc_file(self, tmp_path: Path) -> None:
        """Write a minimal Functional Categories markdown fixture."""
        content = dedent("""\
            ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

            General intro text.

            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance

            Includes elected officials' expenses.

            ## Special Programs

            Special sub-section content.

            ## Line 0250 - Program Support

            Corporate support services.
            Do not include IT services here.

            ## PROTECTION SERVICES

            ## Line 0410 - Fire

            Fire suppression and prevention.
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            content, encoding="utf-8"
        )

    def test_returns_three_records_per_fc_line(self, tmp_path: Path) -> None:
        """Each FC line produces one record for each of schedules 12, 40, and 51A."""
        self._write_fc_file(tmp_path)
        results = _extract_fc_lines(tmp_path)
        # 3 FC lines → 9 records (3 × 3)
        assert len(results) == 9

    def test_each_schedule_present(self, tmp_path: Path) -> None:
        """FC records include entries for schedules 12, 40, and 51A."""
        self._write_fc_file(tmp_path)
        results = _extract_fc_lines(tmp_path)
        schedules = {r["schedule"] for r in results}
        assert schedules == {"12", "40", "51A"}

    def test_section_assigned_from_functional_area(self, tmp_path: Path) -> None:
        """FC line sections are taken from the enclosing functional area heading."""
        self._write_fc_file(tmp_path)
        results = _extract_fc_lines(tmp_path)
        governance_records = [r for r in results if r["line_id"] == "0240"]
        assert all(r["section"] == "GENERAL GOVERNMENT" for r in governance_records)

    def test_description_populated(self, tmp_path: Path) -> None:
        """FC line records have non-empty description content."""
        self._write_fc_file(tmp_path)
        results = _extract_fc_lines(tmp_path)
        fire_records = [r for r in results if r["line_id"] == "0410"]
        assert all(r["description"] is not None for r in fire_records)
        assert all("fire" in (r["description"] or "").lower() for r in fire_records)

    def test_exclude_language_in_description(self, tmp_path: Path) -> None:
        """Exclusion-language sentences remain in the description field."""
        self._write_fc_file(tmp_path)
        results = _extract_fc_lines(tmp_path)
        support_records = [r for r in results if r["line_id"] == "0250"]
        assert all(r["description"] is not None for r in support_records)
        assert all(
            "do not include" in (r["description"] or "").lower()
            for r in support_records
        )

    def test_change_notes_contains_provenance(self, tmp_path: Path) -> None:
        """All FC records have change_notes explaining provenance."""
        self._write_fc_file(tmp_path)
        results = _extract_fc_lines(tmp_path)
        assert all(
            "Functional Categories" in (r.get("change_notes") or "") for r in results
        )

    def test_missing_fc_file_returns_empty(self, tmp_path: Path) -> None:
        """If the Functional Categories file is absent, an empty list is returned."""
        results = _extract_fc_lines(tmp_path)
        assert results == []


# ---------------------------------------------------------------------------
# 4. Per-schedule extraction (unit — tmp_path mock files)
# ---------------------------------------------------------------------------


class TestExtractPerScheduleLines:
    def _write_schedule_file(self, tmp_path: Path, code: str, content: str) -> None:
        (tmp_path / f"FIR2025 S{code}.md").write_text(dedent(content), encoding="utf-8")

    def test_basic_line_extraction(self, tmp_path: Path) -> None:
        """Lines are extracted from a simple per-schedule file."""
        self._write_schedule_file(
            tmp_path,
            "10",
            """\
            ## General Information

            General info text.

            ## Revenue: Property Tax

            ## Line 0299 - Taxation Own Purposes

            Report all property tax revenue here.

            ## Line 9940 - Subtotal

            Sum of lines 0299 and above.
            """,
        )
        records = _extract_per_schedule_lines(tmp_path, "10")
        ids = [r["line_id"] for r in records]
        assert "0299" in ids
        assert "9940" in ids

    def test_section_heading_tracking(self, tmp_path: Path) -> None:
        """Non-line headings set the section for subsequent line records."""
        self._write_schedule_file(
            tmp_path,
            "10",
            """\
            ## Revenue: Property Tax

            ## Line 0299 - Taxation Own Purposes

            Report here.

            ## Government Transfers

            ## Line 0410 - Grants

            Federal grants.
            """,
        )
        records = _extract_per_schedule_lines(tmp_path, "10")
        tax_rec = next(r for r in records if r["line_id"] == "0299")
        grant_rec = next(r for r in records if r["line_id"] == "0410")
        assert tax_rec["section"] == "Revenue: Property Tax"
        assert grant_rec["section"] == "Government Transfers"

    def test_subtotal_flagged(self, tmp_path: Path) -> None:
        """Lines with 'Total' in their name are flagged is_subtotal=True."""
        self._write_schedule_file(
            tmp_path,
            "10",
            """\
            ## Line 9940 - Total Revenue

            Sum of all revenue lines.
            """,
        )
        records = _extract_per_schedule_lines(tmp_path, "10")
        assert records[0]["is_subtotal"] is True

    def test_auto_calculated_flagged(self, tmp_path: Path) -> None:
        """'automatically carried forward' sets is_auto_calculated=True."""
        self._write_schedule_file(
            tmp_path,
            "10",
            """\
            ## Line 0299 - Taxation

            This is automatically carried forward from SLC 12 9910 05.
            """,
        )
        records = _extract_per_schedule_lines(tmp_path, "10")
        assert records[0]["is_auto_calculated"] is True
        assert records[0]["carry_forward_from"] == "12 9910 05"

    def test_description_populated_from_content(self, tmp_path: Path) -> None:
        """Line description is populated from section body text."""
        self._write_schedule_file(
            tmp_path,
            "10",
            """\
            ## Line 0299 - Taxation Own Purposes

            Report all municipal property tax revenue here.
            """,
        )
        records = _extract_per_schedule_lines(tmp_path, "10")
        assert records[0]["description"] is not None
        assert "property tax" in records[0]["description"].lower()

    def test_missing_schedule_file_returns_empty(self, tmp_path: Path) -> None:
        """If the schedule file is absent, an empty list is returned."""
        records = _extract_per_schedule_lines(tmp_path, "10")
        assert records == []


# ---------------------------------------------------------------------------
# 5. Merge logic
# ---------------------------------------------------------------------------


class TestMerge:
    def _write_fc_and_schedule(self, tmp_path: Path) -> None:
        """Write FC and per-schedule files with overlapping line 0240."""
        fc = dedent("""\
            ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

            Intro text.

            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance

            Includes elected officials' expenses.
        """)
        sched12 = dedent("""\
            ## Line 0240 - Governance

            Reports governance and legislative costs.
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            fc, encoding="utf-8"
        )
        (tmp_path / "FIR2025 S12.md").write_text(sched12, encoding="utf-8")

    def test_fc_description_preserved_after_merge(self, tmp_path: Path) -> None:
        """FC description content is retained in the merged record."""
        self._write_fc_and_schedule(tmp_path)
        records = extract_line_records(tmp_path, "12")
        governance = next((r for r in records if r["line_id"] == "0240"), None)
        assert governance is not None
        assert governance["description"] is not None
        assert "elected officials" in governance["description"]

    def test_per_schedule_description_added_after_merge(self, tmp_path: Path) -> None:
        """Per-schedule description supplements FC data after merge."""
        self._write_fc_and_schedule(tmp_path)
        records = extract_line_records(tmp_path, "12")
        governance = next((r for r in records if r["line_id"] == "0240"), None)
        assert governance is not None
        assert governance["description"] is not None
        assert "governance" in governance["description"].lower()

    def test_non_fc_schedule_returns_per_schedule_only(self, tmp_path: Path) -> None:
        """Non-FC schedules (e.g. 10) use only per-schedule data."""
        sched10 = dedent("""\
            ## Line 0299 - Taxation Own Purposes

            Report property tax revenue here.
        """)
        (tmp_path / "FIR2025 S10.md").write_text(sched10, encoding="utf-8")
        records = extract_line_records(tmp_path, "10")
        assert len(records) == 1

    def test_fc_line_with_no_fc_description_uses_per_schedule_description(
        self, tmp_path: Path
    ) -> None:
        """When FC doc has no content under a line, per-schedule description is used."""
        fc = dedent("""\
            ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance
        """)
        sched12 = dedent("""\
            ## Line 0240 - Governance

            Reports governance and legislative costs.
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            fc, encoding="utf-8"
        )
        (tmp_path / "FIR2025 S12.md").write_text(sched12, encoding="utf-8")
        records = extract_line_records(tmp_path, "12")
        governance = next((r for r in records if r["line_id"] == "0240"), None)
        assert governance is not None
        assert governance["description"] == "Reports governance and legislative costs."

    def test_fc_line_with_no_description_in_either_source_stays_none(
        self, tmp_path: Path
    ) -> None:
        """When neither FC nor per-schedule source has description text, description is None."""
        fc = dedent("""\
            ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance
        """)
        sched12 = dedent("""\
            ## Line 0240 - Governance
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            fc, encoding="utf-8"
        )
        (tmp_path / "FIR2025 S12.md").write_text(sched12, encoding="utf-8")
        records = extract_line_records(tmp_path, "12")
        governance = next((r for r in records if r["line_id"] == "0240"), None)
        assert governance is not None
        assert governance["description"] is None


# ---------------------------------------------------------------------------
# 6. CSV round-trip
# ---------------------------------------------------------------------------


class TestCSVRoundTrip:
    def test_save_and_load_preserves_data(self, tmp_path: Path) -> None:
        """Records saved to CSV and reloaded are identical."""
        records = [
            _minimal_line_record(schedule="10", line_id="0299"),
            _minimal_line_record(schedule="40", line_id="0410"),
        ]
        csv_path = tmp_path / "test_line_meta.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)

        assert len(loaded) == 2
        assert loaded[0]["schedule"] == "10"
        assert loaded[1]["schedule"] == "40"

    def test_bool_fields_round_trip(self, tmp_path: Path) -> None:
        """Boolean fields True/False survive CSV round-trip as Python bools."""
        records = [_minimal_line_record(is_subtotal=True, is_auto_calculated=True)]
        csv_path = tmp_path / "bools.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["is_subtotal"] is True
        assert loaded[0]["is_auto_calculated"] is True

    def test_false_bool_round_trip(self, tmp_path: Path) -> None:
        """False boolean values also survive CSV round-trip."""
        records = [_minimal_line_record(is_subtotal=False, is_auto_calculated=False)]
        csv_path = tmp_path / "false_bools.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["is_subtotal"] is False
        assert loaded[0]["is_auto_calculated"] is False

    def test_multiline_text_round_trip(self, tmp_path: Path) -> None:
        """Multiline description text survives CSV round-trip."""
        records = [
            _minimal_line_record(
                description="Line one.\n\nLine two.\n\nDo not include X.",
            )
        ]
        csv_path = tmp_path / "multiline.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert "Line one." in loaded[0]["description"]
        assert "Line two." in loaded[0]["description"]
        assert "Do not include X." in loaded[0]["description"]

    def test_nullable_fields_round_trip_as_none(self, tmp_path: Path) -> None:
        """None values in nullable fields survive CSV round-trip as None."""
        records = [
            _minimal_line_record(
                section=None,
                description=None,
                carry_forward_from=None,
                applicability=None,
                change_notes=None,
                valid_from_year=None,
                valid_to_year=None,
            )
        ]
        csv_path = tmp_path / "nulls.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        for field in (
            "section",
            "description",
            "carry_forward_from",
            "applicability",
            "change_notes",
            "valid_from_year",
            "valid_to_year",
        ):
            assert loaded[0][field] is None, f"Expected None for {field}"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save_to_csv creates missing parent directories."""
        deep_path = tmp_path / "a" / "b" / "line_meta.csv"
        save_to_csv([_minimal_line_record()], deep_path)
        assert deep_path.exists()

    def test_csv_fields_are_complete(self, tmp_path: Path) -> None:
        """The exported CSV contains all expected column headers."""
        csv_path = tmp_path / "fields.csv"
        save_to_csv([_minimal_line_record()], csv_path)
        import csv as csv_mod

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            assert set(reader.fieldnames or []) == set(_CSV_FIELDS)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. Database insertion
# ---------------------------------------------------------------------------


class TestInsertLineMeta:
    def test_insert_single_record(self, engine: Any, session: Session) -> None:
        """A single valid record can be inserted and retrieved from the DB."""
        _insert_schedule_meta_for_test(engine, ["10"])
        records = [_minimal_line_record()]
        inserted = insert_line_meta(engine, records)
        assert inserted == 1

        rows = session.exec(select(FIRLineMeta)).all()
        assert len(rows) == 1
        assert rows[0].schedule == "10"
        assert rows[0].line_id == "0299"

    def test_insert_returns_count(self, engine: Any, session: Session) -> None:
        """insert_line_meta returns the number of rows actually inserted."""
        _insert_schedule_meta_for_test(engine, ["10", "40"])
        records = [
            _minimal_line_record(schedule="10", line_id="0299"),
            _minimal_line_record(schedule="40", line_id="0410"),
        ]
        inserted = insert_line_meta(engine, records)
        assert inserted == 2

    def test_idempotent_insertion(self, engine: Any, session: Session) -> None:
        """Re-inserting the same records returns 0 (application-layer dedup)."""
        _insert_schedule_meta_for_test(engine, ["10"])
        records = [_minimal_line_record()]
        first = insert_line_meta(engine, records)
        second = insert_line_meta(engine, records)
        assert first == 1
        assert second == 0
        assert len(session.exec(select(FIRLineMeta)).all()) == 1

    def test_insert_empty_list(self, engine: Any, session: Session) -> None:
        """Inserting an empty list is a no-op and returns 0."""
        assert insert_line_meta(engine, []) == 0

    def test_is_subtotal_default_false(self, engine: Any, session: Session) -> None:
        """A newly inserted row without is_subtotal has it default to False."""
        _insert_schedule_meta_for_test(engine, ["10"])
        insert_line_meta(engine, [_minimal_line_record(is_subtotal=False)])
        row = session.exec(select(FIRLineMeta)).first()
        assert row is not None
        assert row.is_subtotal is False

    def test_is_auto_calculated_default_false(
        self, engine: Any, session: Session
    ) -> None:
        """A newly inserted row without is_auto_calculated has it default to False."""
        _insert_schedule_meta_for_test(engine, ["10"])
        insert_line_meta(engine, [_minimal_line_record(is_auto_calculated=False)])
        row = session.exec(select(FIRLineMeta)).first()
        assert row is not None
        assert row.is_auto_calculated is False

    def test_carry_forward_from_only_when_auto_calculated(
        self, engine: Any, session: Session
    ) -> None:
        """carry_forward_from is only set on rows where is_auto_calculated=True."""
        _insert_schedule_meta_for_test(engine, ["10"])
        records = [
            _minimal_line_record(
                line_id="0299",
                is_auto_calculated=True,
                carry_forward_from="12 9910 05",
            ),
            _minimal_line_record(
                line_id="9940",
                is_auto_calculated=False,
                carry_forward_from=None,
            ),
        ]
        insert_line_meta(engine, records)
        rows = {r.line_id: r for r in session.exec(select(FIRLineMeta)).all()}
        assert rows["0299"].carry_forward_from == "12 9910 05"
        assert rows["9940"].carry_forward_from is None

    def test_baseline_rows_have_null_year_fields(
        self, engine: Any, session: Session
    ) -> None:
        """Baseline records have NULL year fields stored as NULL in the DB."""
        _insert_schedule_meta_for_test(engine, ["10"])
        insert_line_meta(engine, [_minimal_line_record()])
        row = session.exec(select(FIRLineMeta)).first()
        assert row is not None
        assert row.valid_from_year is None
        assert row.valid_to_year is None


# ---------------------------------------------------------------------------
# 8. Baseline CSV content tests (skipped if CSV absent)
# ---------------------------------------------------------------------------


class TestBaselineCSVContent:
    @pytest.fixture(scope="class")
    def records(self) -> list[dict[str, Any]]:
        return _load_baseline()

    def test_all_31_schedules_present(self, records: list[dict[str, Any]]) -> None:
        """Schedule codes with line-based instructions are present in the baseline CSV.

        Column-format schedules (20, 22A, 22B, 28, 61A, 61B, 62, 74E, 81) legitimately
        produce zero records and are excluded from this check.
        """
        column_format_schedules: frozenset[str] = frozenset(
            {"20", "22A", "22B", "28", "61A", "61B", "62", "74E", "81"}
        )
        found = {r["schedule"] for r in records}
        line_based_codes = _EXPECTED_CODES - column_format_schedules
        missing = line_based_codes - found
        assert missing == set(), f"Missing schedule codes: {sorted(missing)}"

    def test_every_schedule_has_lines(self, records: list[dict[str, Any]]) -> None:
        """Every schedule with line-based instructions has at least one line record.

        Some schedules use a "Column X" format rather than "Line XXXX" rows and
        legitimately have zero line metadata entries (their instructions describe
        columns, not named lines).  These are excluded from this check.
        """
        # Schedules whose instructions use Column-X format or are fully auto-populated,
        # and therefore produce no "Line XXXX" metadata rows.
        column_format_schedules: frozenset[str] = frozenset(
            {
                "20",  # Taxation Information — OPTA-prepopulated, Column X structure
                "22A",  # General Purpose Levy — prepopulated, no line headings
                "22B",  # Special Area Levy — form structure, no line headings
                "28",  # Upper-Tier Entitlements — Column X structure
                "61A",  # Development Charges Receivable — Column X structure
                "61B",  # Development Charges Cash Collected — Column X structure
                "62",  # Development Charges Rates — rate table, no named lines
                "74E",  # Asset Retirement Obligation — Column X structure
                "81",  # Annual Debt Repayment Limit — no instruction lines
            }
        )
        from collections import Counter

        counts = Counter(r["schedule"] for r in records)
        empty = [
            code
            for code in _EXPECTED_CODES
            if counts.get(code, 0) == 0 and code not in column_format_schedules
        ]
        assert empty == [], f"Schedules unexpectedly missing lines: {sorted(empty)}"

    def test_line_id_format(self, records: list[dict[str, Any]]) -> None:
        """All line_id values are 4-character alphanumeric strings."""
        import re

        bad = [
            f"{r['schedule']}:{r['line_id']}"
            for r in records
            if not re.match(r"^\w{4}$", r.get("line_id", ""))
        ]
        assert bad == [], f"Invalid line_id values: {bad[:20]}"

    def test_fc_schedules_have_description(self, records: list[dict[str, Any]]) -> None:
        """Schedules 12, 40, and 51A have at least some non-NULL description values."""
        for sched in ("12", "40", "51A"):
            sched_records = [r for r in records if r["schedule"] == sched]
            has_description = [r for r in sched_records if r.get("description")]
            assert has_description, f"Schedule {sched} has no description data"

    def test_year_fields_null_in_baseline(self, records: list[dict[str, Any]]) -> None:
        """All baseline rows have NULL valid_from_year and valid_to_year."""
        non_null = [
            r["schedule"]
            for r in records
            if r.get("valid_from_year") is not None
            or r.get("valid_to_year") is not None
        ]
        assert non_null == [], f"Non-null year fields on: {non_null}"

    def test_no_carry_forward_without_auto_calc(
        self, records: list[dict[str, Any]]
    ) -> None:
        """No row has carry_forward_from set without is_auto_calculated=True."""
        bad = [
            f"{r['schedule']}:{r['line_id']}"
            for r in records
            if r.get("carry_forward_from") and not r.get("is_auto_calculated")
        ]
        assert bad == [], f"carry_forward_from without auto_calculated: {bad}"

    def test_no_duplicate_line_ids_per_schedule(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Each (schedule, line_id) combination should be unique in the baseline."""
        from collections import Counter

        counts = Counter((r["schedule"], r["line_id"]) for r in records)
        dupes = [key for key, count in counts.items() if count > 1]
        assert dupes == [], f"Duplicate (schedule, line_id) pairs: {dupes[:10]}"


# ---------------------------------------------------------------------------
# 9. CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_extract_command_creates_csv(self, tmp_path: Path) -> None:
        """extract-baseline-line-meta creates the CSV file."""
        md_dir = tmp_path / "markdown"
        md_dir.mkdir()
        (md_dir / "FIR2025 - Functional Categories.md").write_text(
            dedent("""\
                ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

                Intro.

                ## GENERAL GOVERNMENT

                ## Line 0240 - Governance

                Includes governance expenses.
            """),
            encoding="utf-8",
        )
        # Provide a minimal schedule file for at least one code
        for code in SCHEDULE_CATEGORIES:
            (md_dir / f"FIR2025 S{code}.md").write_text(
                f"## Line 0299 - Test Line {code}\n\nTest description.\n",
                encoding="utf-8",
            )

        export_path = tmp_path / "exports" / "line_meta.csv"
        runner = CliRunner()
        with patch(
            "municipal_finances.fir_instructions.extract_line_meta.get_engine"
        ) as mock_engine_fn:
            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            with patch(
                "municipal_finances.fir_instructions.extract_line_meta.insert_line_meta",
                return_value=5,
            ):
                result = runner.invoke(
                    app,
                    [
                        "extract-baseline-line-meta",
                        "--markdown-dir",
                        str(md_dir),
                        "--export-path",
                        str(export_path),
                    ],
                )

        assert result.exit_code == 0, result.output
        assert export_path.exists(), "CSV file was not created"

    def test_extract_command_no_db_skip(self, tmp_path: Path) -> None:
        """extract-baseline-line-meta with --no-load-db skips DB insertion."""
        md_dir = tmp_path / "markdown"
        md_dir.mkdir()
        (md_dir / "FIR2025 - Functional Categories.md").write_text(
            "## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES\n\nIntro.\n",
            encoding="utf-8",
        )
        export_path = tmp_path / "line_meta.csv"
        runner = CliRunner()
        with patch(
            "municipal_finances.fir_instructions.extract_line_meta.get_engine"
        ) as mock_engine_fn:
            result = runner.invoke(
                app,
                [
                    "extract-baseline-line-meta",
                    "--markdown-dir",
                    str(md_dir),
                    "--export-path",
                    str(export_path),
                    "--no-load-db",
                ],
            )
            mock_engine_fn.assert_not_called()

        assert result.exit_code == 0, result.output

    def test_load_command_inserts_rows(self, tmp_path: Path) -> None:
        """load-baseline-line-meta reads CSV and calls insert_line_meta."""
        records = [_minimal_line_record()]
        csv_path = tmp_path / "line_meta.csv"
        save_to_csv(records, csv_path)

        runner = CliRunner()
        with patch(
            "municipal_finances.fir_instructions.extract_line_meta.get_engine"
        ) as mock_engine_fn:
            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            with patch(
                "municipal_finances.fir_instructions.extract_line_meta.insert_line_meta",
                return_value=1,
            ) as mock_insert:
                result = runner.invoke(
                    app,
                    ["load-baseline-line-meta", "--csv-path", str(csv_path)],
                )
                assert mock_insert.called

        assert result.exit_code == 0, result.output
        assert "Inserted 1" in result.output


# ---------------------------------------------------------------------------
# 10. Additional branch coverage
# ---------------------------------------------------------------------------


class TestExtractFCDescriptionAdditional:
    """Additional tests for uncovered branches in _extract_fc_description."""

    def test_sub_heading_only_no_body_in_description(self) -> None:
        """A sub-section with a heading but no body adds the heading text to description."""
        sections = [
            ("Line 0410 - Fire", []),  # main section, no body
            ("Sub-type A", []),  # sub-section: heading only, empty body
            ("NEXT", []),
        ]
        result = _extract_fc_description(sections, 0, 2)
        assert "Sub-type A" in result

    def test_sub_section_body_no_heading_in_description(self) -> None:
        """A sub-section with body but no heading adds the body text to description."""
        sections = [
            ("Line 0410 - Fire", []),  # main section, no body
            ("", ["Some additional details."]),  # sub-section: no heading, body only
            ("NEXT", []),
        ]
        result = _extract_fc_description(sections, 0, 2)
        assert "additional details" in result

    def test_exclude_language_included_in_description(self) -> None:
        """Exclusion-language lines are kept in the returned description."""
        sections = [
            ("Line 0410 - Fire", ["Do not include police services here."]),
            ("NEXT", []),
        ]
        result = _extract_fc_description(sections, 0, 1)
        assert "do not include" in result.lower()

    def test_no_usable_content_returns_empty_string(self) -> None:
        """When the line section has no body and sub-sections have no content, returns ''."""
        sections = [
            ("Line 0410 - Fire", []),  # line heading, empty content
            ("", []),  # sub-section with neither heading nor body
            ("NEXT", []),
        ]
        result = _extract_fc_description(sections, 0, 2)
        assert result == ""


class TestDetectSubtotalSumOfLines:
    """Cover the 'sum of lines' branch that is bypassed when name contains 'total'."""

    def test_sum_of_lines_text_without_total_in_name(self) -> None:
        """'sum of lines' in description flags as subtotal even without 'total' in name."""
        is_sub, notes = _detect_subtotal(
            "0299", "Other Revenue", "Sum of lines 0200 to 0298."
        )
        assert is_sub is True
        assert notes is None


class TestExtractFCLinesFallback:
    """Cover the fallback path when the FC file lacks the expected main heading."""

    def test_fc_file_without_main_heading_falls_back_to_start(
        self, tmp_path: Path
    ) -> None:
        """If the FC main heading is absent, extraction falls back to index 0 and still finds lines."""
        content = dedent("""\
            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance

            Includes governance expenses.
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            content, encoding="utf-8"
        )
        results = _extract_fc_lines(tmp_path)
        line_ids = {r["line_id"] for r in results}
        assert "0240" in line_ids


class TestGetScheduleSections:
    """Tests for _get_schedule_sections, focusing on sub-schedule boundary detection."""

    def test_sub_schedule_ends_at_sibling_prefix(self, tmp_path: Path) -> None:
        """51A extraction ends at the 51B heading, not EOF."""
        content = dedent("""\
            ## Schedule 51A: Tangible Capital Assets

            ## Line 0001 - Land

            Land owned by the municipality.

            ## Schedule 51B: Tangible Capital Assets (Continuity)

            ## Line 0002 - Opening Balance

            Opening balance from prior year.
        """)
        (tmp_path / "FIR2025 S51.md").write_text(content, encoding="utf-8")
        sections = _get_schedule_sections(tmp_path, "51A")
        headings = [s[0] for s in sections]
        # 51A section should be present
        assert any("51A" in h for h in headings)
        # 51B content should NOT be included in the 51A slice
        assert not any("51B" in h for h in headings)
        assert not any("0002" in h for h in headings)

    def test_sub_schedule_start_prefix_missing_returns_empty(
        self, tmp_path: Path
    ) -> None:
        """If the sub-schedule heading prefix is not found in the parent file, returns []."""
        (tmp_path / "FIR2025 S51.md").write_text(
            "## Unrelated Heading\n\nSome content.\n", encoding="utf-8"
        )
        sections = _get_schedule_sections(tmp_path, "51A")
        assert sections == []

    def test_74e_extraction_starts_at_schedule_74e_heading(
        self, tmp_path: Path
    ) -> None:
        """74E extraction starts from the 'Schedule 74E' heading within S74.md."""
        content = dedent("""\
            ## Schedule 74

            ## Line 0001 - Preamble

            Intro content.

            ## Schedule 74E

            ## Line 0010 - Asset Retirement

            ARO description.
        """)
        (tmp_path / "FIR2025 S74.md").write_text(content, encoding="utf-8")
        sections = _get_schedule_sections(tmp_path, "74E")
        headings = [s[0] for s in sections]
        # Should start at the Schedule 74E heading
        assert headings[0] == "Schedule 74E"
        # Should NOT include the pre-74E content
        assert not any("Preamble" in h for h in headings)

    def test_74e_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing S74.md returns empty list for 74E."""
        sections = _get_schedule_sections(tmp_path, "74E")
        assert sections == []

    def test_74e_heading_not_found_returns_empty(self, tmp_path: Path) -> None:
        """S74.md without a 'Schedule 74E' heading returns empty list."""
        (tmp_path / "FIR2025 S74.md").write_text(
            "## Some Other Heading\n\nContent.\n", encoding="utf-8"
        )
        sections = _get_schedule_sections(tmp_path, "74E")
        assert sections == []

    def test_sub_schedule_is_last_section_in_parent(self, tmp_path: Path) -> None:
        """When the sub-schedule section is the last in the parent file, the sibling
        search range is empty and the section is returned as-is (no break needed)."""
        content = dedent("""\
            ## Schedule 51A: Tangible Capital Assets
        """)
        (tmp_path / "FIR2025 S51.md").write_text(content, encoding="utf-8")
        sections = _get_schedule_sections(tmp_path, "51A")
        headings = [s[0] for s in sections]
        assert any("51A" in h for h in headings)


class TestDuplicateLineIdSkipped:
    """Cover the duplicate line_id skip in _extract_per_schedule_lines."""

    def test_second_occurrence_of_same_line_id_skipped(self, tmp_path: Path) -> None:
        """When the same line_id appears twice, only the first record is kept."""
        content = dedent("""\
            ## Line 0299 - Taxation Own Purposes

            First occurrence: report property tax here.

            ## Alternative Method

            ## Line 0299 - Taxation Own Purposes

            Second occurrence: should be ignored.
        """)
        (tmp_path / "FIR2025 S10.md").write_text(content, encoding="utf-8")
        records = _extract_per_schedule_lines(tmp_path, "10")
        matching = [r for r in records if r["line_id"] == "0299"]
        assert len(matching) == 1
        assert "First occurrence" in (matching[0]["description"] or "")


class TestMergeFlagPropagation:
    """Cover branches in extract_line_records where per-schedule flags override FC defaults."""

    def _write_fc_and_schedule(
        self,
        tmp_path: Path,
        per_schedule_line_content: str,
        line_name: str = "Governance",
    ) -> None:
        """Write FC file with line 0240 and a per-schedule S12 file."""
        fc = dedent("""\
            ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance

            Includes governance expenses.
        """)
        sched12 = dedent(f"""\
            ## Line 0240 - {line_name}

            {per_schedule_line_content}
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            fc, encoding="utf-8"
        )
        (tmp_path / "FIR2025 S12.md").write_text(sched12, encoding="utf-8")

    def test_merge_propagates_is_subtotal_from_per_schedule(
        self, tmp_path: Path
    ) -> None:
        """When the per-schedule record marks a line as subtotal, the merged record reflects it."""
        # FC: "Governance" (not a subtotal); per-schedule: "Governance Subtotal" (is_subtotal=True)
        fc = dedent("""\
            ## FUNCTIONAL CLASSIFICATION OF REVENUE AND EXPENSES

            ## GENERAL GOVERNMENT

            ## Line 0240 - Governance

            Includes governance expenses.
        """)
        sched12 = dedent("""\
            ## Line 0240 - Governance Subtotal

            Sum of governance lines.
        """)
        (tmp_path / "FIR2025 - Functional Categories.md").write_text(
            fc, encoding="utf-8"
        )
        (tmp_path / "FIR2025 S12.md").write_text(sched12, encoding="utf-8")

        records = extract_line_records(tmp_path, "12")
        gov = next((r for r in records if r["line_id"] == "0240"), None)
        assert gov is not None
        assert gov["is_subtotal"] is True

    def test_merge_propagates_auto_calculated_and_carry_forward(
        self, tmp_path: Path
    ) -> None:
        """Auto-calc flag and carry_forward_from are copied from per-schedule to merged record."""
        self._write_fc_and_schedule(
            tmp_path,
            per_schedule_line_content=(
                "This line is automatically carried forward from SLC 40 9910 05."
            ),
        )
        records = extract_line_records(tmp_path, "12")
        gov = next((r for r in records if r["line_id"] == "0240"), None)
        assert gov is not None
        assert gov["is_auto_calculated"] is True
        assert gov["carry_forward_from"] == "40 9910 05"

    def test_merge_propagates_applicability_from_per_schedule(
        self, tmp_path: Path
    ) -> None:
        """Applicability restriction from per-schedule data appears in the merged record."""
        self._write_fc_and_schedule(
            tmp_path,
            per_schedule_line_content="Upper-tier only municipalities should report here.",
        )
        records = extract_line_records(tmp_path, "12")
        gov = next((r for r in records if r["line_id"] == "0240"), None)
        assert gov is not None
        assert gov["applicability"] == "Upper-tier municipalities only"

    def test_merge_auto_calculated_without_carry_forward(self, tmp_path: Path) -> None:
        """When per-schedule sets auto_calculated but no carry_forward_from SLC is found,
        is_auto_calculated is True and carry_forward_from remains None."""
        self._write_fc_and_schedule(
            tmp_path,
            per_schedule_line_content="This value is automatically calculated.",
        )
        records = extract_line_records(tmp_path, "12")
        gov = next((r for r in records if r["line_id"] == "0240"), None)
        assert gov is not None
        assert gov["is_auto_calculated"] is True
        assert gov["carry_forward_from"] is None


class TestCSVYearFieldIntConversion:
    """Cover the int() conversion branch in load_from_csv for non-null year fields."""

    def test_non_null_year_fields_parsed_as_int(self, tmp_path: Path) -> None:
        """Year field values survive CSV round-trip as Python ints, not strings."""
        records = [_minimal_line_record(valid_from_year=2020, valid_to_year=2024)]
        csv_path = tmp_path / "years.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["valid_from_year"] == 2020
        assert loaded[0]["valid_to_year"] == 2024
        assert isinstance(loaded[0]["valid_from_year"], int)
        assert isinstance(loaded[0]["valid_to_year"], int)
