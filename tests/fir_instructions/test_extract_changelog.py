"""Tests for fir_instructions/extract_changelog.py."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from municipal_finances.app import app
from municipal_finances.fir_instructions.extract_changelog import (
    VALID_CHANGE_TYPES,
    _expand_schedules,
    _infer_change_type,
    _infer_severity,
    _parse_slc_field,
    insert_changelog_entries,
    load_from_csv,
    parse_changelog_row,
    save_to_csv,
)
from municipal_finances.models import FIRInstructionChangelog

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_ENTRY = {
    "year": 2025,
    "schedule": "10",
    "slc_pattern": "10 6021 01",
    "line_id": "6021",
    "column_id": "01",
    "heading": "Test Heading",
    "change_type": "new_line",
    "severity": "minor",
    "description": "Test description.",
    "source": "pdf_changelog",
}


def _entry(**overrides) -> dict:
    return {**_MINIMAL_ENTRY, **overrides}


# ---------------------------------------------------------------------------
# _expand_schedules
# ---------------------------------------------------------------------------


class TestExpandSchedules:
    def test_single_schedule(self):
        assert _expand_schedules("10") == ["10"]

    def test_two_schedules_with_prefix(self):
        assert _expand_schedules("61A & 61B") == ["61A", "61B"]

    def test_two_schedules_mixed(self):
        assert _expand_schedules("62 & 62A") == ["62", "62A"]

    def test_four_schedules_letter_suffix(self):
        assert _expand_schedules("77A, B, C & D") == ["77A", "77B", "77C", "77D"]

    def test_alphanumeric_schedule(self):
        assert _expand_schedules("22A") == ["22A"]


# ---------------------------------------------------------------------------
# _parse_slc_field
# ---------------------------------------------------------------------------


class TestParseSLCField:
    def test_normal_slc(self):
        slc_pattern, line_id, column_id = _parse_slc_field("10 6021 01", "10")
        assert slc_pattern == "10 6021 01"
        assert line_id == "6021"
        assert column_id == "01"

    def test_line_wildcard(self):
        slc_pattern, line_id, column_id = _parse_slc_field("40 xxxx 05", "40")
        assert slc_pattern == "40 xxxx 05"
        assert line_id is None
        assert column_id == "05"

    def test_column_wildcard(self):
        slc_pattern, line_id, column_id = _parse_slc_field("61 0206 xx", "61")
        assert slc_pattern == "61 0206 xx"
        assert line_id == "0206"
        assert column_id is None

    def test_new_schedule_marker(self):
        assert _parse_slc_field("New **", "71") == (None, None, None)

    def test_deleted_marker(self):
        assert _parse_slc_field("Deleted", "51C") == (None, None, None)

    def test_empty_slc(self):
        assert _parse_slc_field("", "10") == (None, None, None)

    def test_malformed_slc_returns_raw(self):
        # "77A1040 xx" has schedule+line concatenated without space — unparseable
        slc_pattern, line_id, column_id = _parse_slc_field("77A1040 xx", "77A")
        assert slc_pattern == "77A1040 xx"
        assert line_id is None
        assert column_id is None


# ---------------------------------------------------------------------------
# _infer_change_type
# ---------------------------------------------------------------------------


class TestInferChangeType:
    def test_new_schedule(self):
        ct = _infer_change_type("New **", None, None, "New schedule added.", "", "MAJOR CHANGES")
        assert ct == "new_schedule"

    def test_deleted_schedule(self):
        ct = _infer_change_type("Deleted", None, None, "This schedule has been eliminated.", "", "")
        assert ct == "deleted_schedule"

    def test_empty_slc_gives_updated_line(self):
        ct = _infer_change_type(None, None, None, "Some change.", "", "")
        assert ct == "updated_line"

    def test_new_line(self):
        ct = _infer_change_type("10 1888 01", "1888", "01", "New line added.", "", "")
        assert ct == "new_line"

    def test_deleted_line(self):
        ct = _infer_change_type("10 0831 01", "0831", "01", "Removed line, please refer to instructions.", "", "")
        assert ct == "deleted_line"

    def test_updated_line(self):
        ct = _infer_change_type("10 1421 01", "1421", "01", "Report all building permit revenue on this line.", "", "")
        assert ct == "updated_line"

    def test_line_wildcard_gives_column_entity(self):
        # xxxx in line position → column-level change
        ct = _infer_change_type("40 xxxx 05", None, "05", "Column heading modified.", "", "")
        assert ct == "updated_column"

    def test_column_wildcard_gives_line_entity(self):
        # xx in column position → line-level change
        ct = _infer_change_type("61 0206 xx", "0206", None, "New line added.", "", "")
        assert ct == "new_line"

    def test_all_change_types_valid(self):
        """Every inferred change_type must be in VALID_CHANGE_TYPES."""
        test_cases = [
            ("New **", None, None, "new schedule", "", "MAJOR CHANGES"),
            ("Deleted", None, None, "eliminated", "", ""),
            ("10 1888 01", "1888", "01", "New line added.", "", ""),
            ("10 0831 01", "0831", "01", "Removed line.", "", ""),
            ("10 1421 01", "1421", "01", "Text updated.", "", ""),
            ("40 xxxx 05", None, "05", "New column.", "", ""),
            ("61 xxxx 17", None, "17", "Column deleted.", "", ""),
            ("61 xxxx 17", None, "17", "Column heading modified.", "", ""),
        ]
        for args in test_cases:
            ct = _infer_change_type(*args)
            assert ct in VALID_CHANGE_TYPES, f"Unexpected change_type {ct!r} for args {args}"


# ---------------------------------------------------------------------------
# _infer_severity
# ---------------------------------------------------------------------------


class TestInferSeverity:
    def test_explicit_major_label(self):
        assert _infer_severity("MAJOR CHANGES", "new_line", None, "") == "major"

    def test_explicit_minor_label(self):
        assert _infer_severity("Minor Changes:", "updated_line", "10 1421 01", "") == "minor"

    def test_new_schedule_is_major(self):
        assert _infer_severity("", "new_schedule", None, "New schedule.") == "major"

    def test_deleted_schedule_is_major(self):
        assert _infer_severity("", "deleted_schedule", None, "Eliminated.") == "major"

    def test_keyword_eliminated_is_major(self):
        assert _infer_severity("", "updated_line", "10 9950 01", "This line has been eliminated.") == "major"

    def test_keyword_updated_language_is_minor(self):
        assert _infer_severity("", "updated_line", "10 2099 01", "Updated language.") == "minor"

    def test_default_is_minor(self):
        assert _infer_severity("", "updated_line", "10 1421 01", "Report on this line.") == "minor"

    def test_tier2_new_line_with_xxxx_wildcard_is_major(self):
        # new_line with xxxx in slc_pattern → structural major (Tier 2)
        assert _infer_severity("", "new_line", "40 xxxx 05", "") == "major"

    def test_tier2_deleted_column_with_xx_wildcard_is_major(self):
        # deleted_column with xx in slc_pattern → structural major (Tier 2)
        assert _infer_severity("", "deleted_column", "74 xxxx xx", "") == "major"

    def test_tier2_no_match_falls_through_to_tier3(self):
        # slc_pattern truthy but change_type is "updated_line" (not new/deleted)
        # → Tier 2 inner checks both fail → falls through to Tier 3/5
        assert _infer_severity("", "updated_line", "10 6021 01", "") == "minor"

    def test_tier3_reached_when_slc_pattern_is_none(self):
        # slc_pattern=None → `if slc_pattern:` is False → skips Tier 2 wildcard block,
        # reaches Tier 3 directly
        assert _infer_severity("", "updated_line", None, "eliminated") == "major"


# ---------------------------------------------------------------------------
# parse_changelog_row
# ---------------------------------------------------------------------------


class TestParseChangelogRow:
    def test_single_schedule_row(self):
        row = {
            "Schedule": "10",
            "SLC": "10 6021 01",
            "Heading": "Test Heading",
            "Description": "New line. Linked from schedule 76.",
            "Section Description": "Minor Changes:",
        }
        entries = parse_changelog_row(row, 2025)
        assert len(entries) == 1
        e = entries[0]
        assert e["year"] == 2025
        assert e["schedule"] == "10"
        assert e["slc_pattern"] == "10 6021 01"
        assert e["line_id"] == "6021"
        assert e["column_id"] == "01"
        assert e["severity"] == "minor"
        assert e["source"] == "pdf_changelog"
        assert e["change_type"] == "new_line"

    def test_multi_schedule_expansion(self):
        row = {
            "Schedule": "77A, B, C & D",
            "SLC": "77 9960 xx",
            "Heading": "Some Heading",
            "Description": "New line added.",
            "Section Description": "",
        }
        entries = parse_changelog_row(row, 2022)
        assert len(entries) == 4
        schedules = [e["schedule"] for e in entries]
        assert schedules == ["77A", "77B", "77C", "77D"]
        # All other fields should be identical
        for e in entries:
            assert e["slc_pattern"] == "77 9960 xx"
            assert e["line_id"] == "9960"
            assert e["column_id"] is None

    def test_schedule_level_new(self):
        row = {
            "Schedule": "71",
            "SLC": "New **",
            "Heading": "Statement of Remeasurement Gains & Losses",
            "Description": "This schedule captures the portfolio gains and losses.",
            "Section Description": "MAJOR CHANGES",
        }
        entries = parse_changelog_row(row, 2023)
        assert len(entries) == 1
        e = entries[0]
        assert e["change_type"] == "new_schedule"
        assert e["slc_pattern"] is None
        assert e["severity"] == "major"

    def test_schedule_level_deleted(self):
        row = {
            "Schedule": "79",
            "SLC": "Deleted",
            "Heading": "Community Improvement Plans",
            "Description": "This schedule has been eliminated.",
            "Section Description": "MAJOR CHANGES",
        }
        entries = parse_changelog_row(row, 2023)
        assert len(entries) == 1
        e = entries[0]
        assert e["change_type"] == "deleted_schedule"
        assert e["slc_pattern"] is None

    def test_wildcard_slc(self):
        row = {
            "Schedule": "40",
            "SLC": "40 xxxx 05",
            "Heading": "Rents and Financial Expenses",
            "Description": "Column heading modified.",
            "Section Description": "Minor Changes:",
        }
        entries = parse_changelog_row(row, 2024)
        assert len(entries) == 1
        e = entries[0]
        assert e["slc_pattern"] == "40 xxxx 05"
        assert e["line_id"] is None
        assert e["column_id"] == "05"
        assert e["change_type"] == "updated_column"


# ---------------------------------------------------------------------------
# insert_changelog_entries (requires DB)
# ---------------------------------------------------------------------------


class TestInsertChangelogEntries:
    def test_insert_valid_entries(self, engine, session):
        entries = [_entry()]
        inserted = insert_changelog_entries(engine, entries)
        assert inserted == 1

        rows = session.exec(select(FIRInstructionChangelog)).all()
        assert len(rows) == 1
        assert rows[0].schedule == "10"
        assert rows[0].slc_pattern == "10 6021 01"

    def test_idempotent_insertion_non_null_slc(self, engine, session):
        entries = [_entry()]
        first = insert_changelog_entries(engine, entries)
        second = insert_changelog_entries(engine, entries)
        assert first == 1
        assert second == 0

        count = len(session.exec(select(FIRInstructionChangelog)).all())
        assert count == 1

    def test_idempotent_insertion_null_slc(self, engine, session):
        # Schedule-level entries have slc_pattern=NULL; deduplication is app-level
        entries = [_entry(slc_pattern=None, line_id=None, column_id=None, change_type="new_schedule")]
        first = insert_changelog_entries(engine, entries)
        second = insert_changelog_entries(engine, entries)
        assert first == 1
        assert second == 0

        count = len(session.exec(select(FIRInstructionChangelog)).all())
        assert count == 1

    def test_insert_multiple_entries(self, engine, session):
        entries = [
            _entry(slc_pattern="10 6021 01", line_id="6021", column_id="01"),
            _entry(slc_pattern="10 1888 01", line_id="1888", column_id="01"),
        ]
        inserted = insert_changelog_entries(engine, entries)
        assert inserted == 2

    def test_insert_empty_list(self, engine, session):
        assert insert_changelog_entries(engine, []) == 0

    def test_insert_mix_of_null_and_non_null_slc(self, engine, session):
        entries = [
            _entry(slc_pattern="10 6021 01", line_id="6021", column_id="01"),
            _entry(slc_pattern=None, line_id=None, column_id=None, change_type="new_schedule"),
        ]
        inserted = insert_changelog_entries(engine, entries)
        assert inserted == 2


# ---------------------------------------------------------------------------
# save_to_csv / load_from_csv
# ---------------------------------------------------------------------------


class TestCSVRoundtrip:
    def test_save_and_load(self, tmp_path):
        entries = [
            _entry(slc_pattern="10 6021 01", line_id="6021", column_id="01"),
            _entry(slc_pattern="40 xxxx 05", line_id=None, column_id="05"),
            _entry(slc_pattern=None, line_id=None, column_id=None, change_type="new_schedule"),
        ]
        csv_path = tmp_path / "test_changelog.csv"
        save_to_csv(entries, csv_path)
        loaded = load_from_csv(csv_path)

        assert len(loaded) == 3
        # year is int after load
        assert all(isinstance(e["year"], int) for e in loaded)
        # None values are preserved for nullable fields
        assert loaded[1]["line_id"] is None
        assert loaded[1]["column_id"] == "05"
        assert loaded[2]["slc_pattern"] is None
        assert loaded[2]["line_id"] is None

    def test_load_from_csv_and_insert(self, engine, session, tmp_path):
        entries = [_entry()]
        csv_path = tmp_path / "changelog.csv"
        save_to_csv(entries, csv_path)
        loaded = load_from_csv(csv_path)
        inserted = insert_changelog_entries(engine, loaded)
        assert inserted == 1

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "test.csv"
        save_to_csv([_entry()], nested)
        assert nested.exists()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLI:
    def test_load_changelogs_missing_dir(self, tmp_path, mocker):
        mocker.patch("municipal_finances.fir_instructions.extract_changelog.get_engine")
        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path / "nonexistent")],
        )
        assert result.exit_code != 0

    def test_load_changelogs_empty_dir(self, tmp_path, mocker):
        mocker.patch("municipal_finances.fir_instructions.extract_changelog.get_engine")
        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_load_changelogs_skips_unrecognised_filename(self, tmp_path, engine, session, mocker):
        """Files matching 'FIR* Changes.csv' glob but without a 4-digit year are skipped."""
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        # Matches glob "FIR* Changes.csv" but has no 4-digit year — triggers lines 622-623
        bad_csv = tmp_path / "FIRabc Changes.csv"
        bad_csv.write_text("Schedule,SLC,Heading,Description,Section Description\n")
        valid_csv = tmp_path / "FIR2025 Changes.csv"
        with open(valid_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["Schedule", "SLC", "Heading", "Description", "Section Description"],
            )
            writer.writeheader()
            writer.writerow({
                "Schedule": "10", "SLC": "10 6021 01", "Heading": "H",
                "Description": "New line.", "Section Description": "Minor Changes:",
            })

        export_dir = tmp_path / "exports"
        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path), "--export-dir", str(export_dir)],
        )
        assert result.exit_code == 0, result.output

    def test_load_changelogs_with_csv(self, tmp_path, engine, session, mocker):
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        # Write a minimal CSV file
        csv_path = tmp_path / "FIR2025 Changes.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["Schedule", "SLC", "Heading", "Description", "Section Description"],
            )
            writer.writeheader()
            writer.writerow({
                "Schedule": "10",
                "SLC": "10 6021 01",
                "Heading": "Test Heading",
                "Description": "New line.",
                "Section Description": "Minor Changes:",
            })

        export_dir = tmp_path / "exports"
        result = runner.invoke(
            app,
            [
                "load-changelogs",
                "--csv-dir", str(tmp_path),
                "--export-dir", str(export_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (export_dir / "fir_instruction_changelog.csv").exists()

        rows = session.exec(select(FIRInstructionChangelog)).all()
        assert len(rows) == 1
        assert rows[0].year == 2025

    def test_load_changelogs_no_parseable_entries(self, tmp_path, engine, session, mocker):
        """A header-only CSV yields zero entries and the command exits with error."""
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        # Header-only CSV → load_changelog_csv returns []
        csv_path = tmp_path / "FIR2025 Changes.csv"
        csv_path.write_text("Schedule,SLC,Heading,Description,Section Description\n")

        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_export_changelog(self, tmp_path, engine, session, mocker):
        """export-changelog queries DB and writes a CSV."""
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        insert_changelog_entries(engine, [_entry()])
        export_dir = tmp_path / "exports"
        result = runner.invoke(
            app,
            ["export-changelog", "--export-dir", str(export_dir)],
        )
        assert result.exit_code == 0, result.output
        export_file = export_dir / "fir_instruction_changelog.csv"
        assert export_file.exists()
        loaded = load_from_csv(export_file)
        assert len(loaded) == 1
        assert loaded[0]["year"] == 2025
