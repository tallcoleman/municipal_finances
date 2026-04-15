"""Tests for fir_instructions/extract_changelog.py."""

# postponse evaluation of typing annotations
from __future__ import annotations

import csv

from sqlmodel import select
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
        """A plain schedule code is returned as a one-element list."""
        assert _expand_schedules("10") == ["10"]

    def test_two_schedules_with_prefix(self):
        """Two fully-qualified codes joined by '&' are split into separate schedules."""
        assert _expand_schedules("61A & 61B") == ["61A", "61B"]

    def test_two_schedules_mixed(self):
        """A numeric and an alphanumeric code joined by '&' are both returned."""
        assert _expand_schedules("62 & 62A") == ["62", "62A"]

    def test_four_schedules_letter_suffix(self):
        """Shorthand like '77A, B, C & D' expands by attaching each letter to the shared prefix."""
        assert _expand_schedules("77A, B, C & D") == ["77A", "77B", "77C", "77D"]

    def test_alphanumeric_schedule(self):
        """A single alphanumeric schedule code is returned as a one-element list."""
        assert _expand_schedules("22A") == ["22A"]


# ---------------------------------------------------------------------------
# _parse_slc_field
# ---------------------------------------------------------------------------


class TestParseSLCField:
    def test_normal_slc(self):
        """A well-formed SLC with numeric line and column returns all three components."""
        slc_pattern, line_id, column_id = _parse_slc_field("10 6021 01", "10")
        assert slc_pattern == "10 6021 01"
        assert line_id == "6021"
        assert column_id == "01"

    def test_line_wildcard(self):
        """An SLC with 'xxxx' in the line position returns line_id=None and a concrete column_id."""
        slc_pattern, line_id, column_id = _parse_slc_field("40 xxxx 05", "40")
        assert slc_pattern == "40 xxxx 05"
        assert line_id is None
        assert column_id == "05"

    def test_column_wildcard(self):
        """An SLC with 'xx' in the column position returns a concrete line_id and column_id=None."""
        slc_pattern, line_id, column_id = _parse_slc_field("61 0206 xx", "61")
        assert slc_pattern == "61 0206 xx"
        assert line_id == "0206"
        assert column_id is None

    def test_new_schedule_marker(self):
        """The sentinel value 'New **' signals a new-schedule entry; all three components are None."""
        assert _parse_slc_field("New **", "71") == (None, None, None)

    def test_deleted_marker(self):
        """The sentinel value 'Deleted' signals a deleted-schedule entry; all three components are None."""
        assert _parse_slc_field("Deleted", "51C") == (None, None, None)

    def test_empty_slc(self):
        """An empty SLC field (schedule-level change with no SLC) returns (None, None, None)."""
        assert _parse_slc_field("", "10") == (None, None, None)

    def test_malformed_slc_returns_raw(self):
        """An unparseable SLC (schedule and line concatenated without space) stores the raw
        string as slc_pattern with line_id and column_id both None."""
        slc_pattern, line_id, column_id = _parse_slc_field("77A1040 xx", "77A")
        assert slc_pattern == "77A1040 xx"
        assert line_id is None
        assert column_id is None


# ---------------------------------------------------------------------------
# _infer_change_type
# ---------------------------------------------------------------------------


class TestInferChangeType:
    def test_new_schedule(self):
        """A 'New **' SLC marker with a description mentioning 'new schedule' is classified
        as new_schedule."""
        ct = _infer_change_type(
            "New **", None, None, "New schedule added.", "", "MAJOR CHANGES"
        )
        assert ct == "new_schedule"

    def test_deleted_schedule(self):
        """A 'Deleted' SLC marker with a description mentioning 'eliminated' is classified
        as deleted_schedule."""
        ct = _infer_change_type(
            "Deleted", None, None, "This schedule has been eliminated.", "", ""
        )
        assert ct == "deleted_schedule"

    def test_empty_slc_gives_updated_line(self):
        """A missing SLC with no keyword signals defaults to updated_line."""
        ct = _infer_change_type(None, None, None, "Some change.", "", "")
        assert ct == "updated_line"

    def test_new_line(self):
        """A deterministic SLC with a description containing 'new line' is classified as new_line."""
        ct = _infer_change_type("10 1888 01", "1888", "01", "New line added.", "", "")
        assert ct == "new_line"

    def test_deleted_line(self):
        """A deterministic SLC with a description containing 'removed' is classified as deleted_line."""
        ct = _infer_change_type(
            "10 0831 01",
            "0831",
            "01",
            "Removed line, please refer to instructions.",
            "",
            "",
        )
        assert ct == "deleted_line"

    def test_updated_line(self):
        """A deterministic SLC with a neutral description (no add/remove keywords) is classified
        as updated_line."""
        ct = _infer_change_type(
            "10 1421 01",
            "1421",
            "01",
            "Report all building permit revenue on this line.",
            "",
            "",
        )
        assert ct == "updated_line"

    def test_line_wildcard_gives_column_entity(self):
        """'xxxx' in the line position means the change affects a whole column, so the entity
        type is column-level (updated_column here based on the description)."""
        ct = _infer_change_type(
            "40 xxxx 05", None, "05", "Column heading modified.", "", ""
        )
        assert ct == "updated_column"

    def test_column_wildcard_gives_line_entity(self):
        """'xx' in the column position means the change affects a whole line, so the entity
        type is line-level (new_line here based on the description)."""
        ct = _infer_change_type("61 0206 xx", "0206", None, "New line added.", "", "")
        assert ct == "new_line"

    def test_all_change_types_valid(self):
        """Every value produced by _infer_change_type across a representative set of inputs
        must belong to VALID_CHANGE_TYPES."""
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
            assert ct in VALID_CHANGE_TYPES, (
                f"Unexpected change_type {ct!r} for args {args}"
            )


# ---------------------------------------------------------------------------
# _infer_severity
# ---------------------------------------------------------------------------


class TestInferSeverity:
    def test_explicit_major_label(self):
        """Tier 1: 'MAJOR' in section_desc → severity is major regardless of change_type."""
        assert _infer_severity("MAJOR CHANGES", "new_line", None, "") == "major"

    def test_explicit_minor_label(self):
        """Tier 1: 'Minor' in section_desc → severity is minor regardless of other signals."""
        assert (
            _infer_severity("Minor Changes:", "updated_line", "10 1421 01", "")
            == "minor"
        )

    def test_new_schedule_is_major(self):
        """Tier 2: new_schedule change_type → severity is major (structural scope)."""
        assert _infer_severity("", "new_schedule", None, "New schedule.") == "major"

    def test_deleted_schedule_is_major(self):
        """Tier 2: deleted_schedule change_type → severity is major (structural scope)."""
        assert _infer_severity("", "deleted_schedule", None, "Eliminated.") == "major"

    def test_keyword_eliminated_is_major(self):
        """Tier 3: 'eliminated' keyword in description → severity is major."""
        assert (
            _infer_severity(
                "", "updated_line", "10 9950 01", "This line has been eliminated."
            )
            == "major"
        )

    def test_keyword_updated_language_is_minor(self):
        """Tier 3: 'updated language' keyword in description → severity is minor."""
        assert (
            _infer_severity("", "updated_line", "10 2099 01", "Updated language.")
            == "minor"
        )

    def test_default_is_minor(self):
        """Tier 5: no label, no structural scope, no keyword signals → default severity is minor."""
        assert (
            _infer_severity("", "updated_line", "10 1421 01", "Report on this line.")
            == "minor"
        )

    def test_tier2_new_line_with_xxxx_wildcard_is_major(self):
        """Tier 2: new_line with 'xxxx' in slc_pattern (affects all lines on a schedule)
        → severity is major due to broad structural scope."""
        assert _infer_severity("", "new_line", "40 xxxx 05", "") == "major"

    def test_tier2_deleted_column_with_xx_wildcard_is_major(self):
        """Tier 2: deleted_column with 'xx' wildcard in slc_pattern (affects all columns
        on a schedule) → severity is major due to broad structural scope."""
        assert _infer_severity("", "deleted_column", "74 xxxx xx", "") == "major"

    def test_tier2_no_match_falls_through_to_tier3(self):
        """Tier 2 wildcard checks are skipped for change types other than new/deleted line/column;
        a truthy slc_pattern with change_type='updated_line' falls through to Tier 3/5."""
        assert _infer_severity("", "updated_line", "10 6021 01", "") == "minor"

    def test_tier3_reached_when_slc_pattern_is_none(self):
        """When slc_pattern is None the Tier 2 wildcard block is skipped entirely and Tier 3
        keyword matching applies; 'eliminated' in description → major."""
        assert _infer_severity("", "updated_line", None, "eliminated") == "major"


# ---------------------------------------------------------------------------
# parse_changelog_row
# ---------------------------------------------------------------------------


class TestParseChangelogRow:
    def test_single_schedule_row(self):
        """A standard single-schedule row produces one entry with all fields correctly populated,
        including severity inferred from an explicit 'Minor Changes:' section label."""
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
        """A row whose Schedule field lists multiple schedules (e.g. '77A, B, C & D') is
        expanded into one entry per schedule; all non-schedule fields are identical across
        the expanded entries."""
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
        """A row with 'New **' as the SLC is treated as a new-schedule entry:
        change_type=new_schedule, slc_pattern=None, and severity=major from the
        explicit 'MAJOR CHANGES' section label."""
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
        """A row with 'Deleted' as the SLC is treated as a deleted-schedule entry:
        change_type=deleted_schedule and slc_pattern=None."""
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
        """A row with 'xxxx' in the line position stores the raw SLC pattern,
        sets line_id=None, retains a concrete column_id, and infers a column-level change_type."""
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
        """A list with one valid entry is inserted and the row is retrievable from the database."""
        entries = [_entry()]
        inserted = insert_changelog_entries(engine, entries)
        assert inserted == 1

        rows = session.exec(select(FIRInstructionChangelog)).all()
        assert len(rows) == 1
        assert rows[0].schedule == "10"
        assert rows[0].slc_pattern == "10 6021 01"

    def test_idempotent_insertion_non_null_slc(self, engine, session):
        """Inserting the same non-null-SLC entry twice inserts it once and skips the duplicate,
        leaving exactly one row in the database."""
        entries = [_entry()]
        first = insert_changelog_entries(engine, entries)
        second = insert_changelog_entries(engine, entries)
        assert first == 1
        assert second == 0

        count = len(session.exec(select(FIRInstructionChangelog)).all())
        assert count == 1

    def test_idempotent_insertion_null_slc(self, engine, session):
        """Schedule-level entries (slc_pattern=NULL) are deduplicated at the application layer;
        inserting the same entry twice leaves exactly one row in the database."""
        entries = [
            _entry(
                slc_pattern=None,
                line_id=None,
                column_id=None,
                change_type="new_schedule",
            )
        ]
        first = insert_changelog_entries(engine, entries)
        second = insert_changelog_entries(engine, entries)
        assert first == 1
        assert second == 0

        count = len(session.exec(select(FIRInstructionChangelog)).all())
        assert count == 1

    def test_insert_multiple_entries(self, engine, session):
        """Two entries with distinct SLC patterns are both inserted and the return value
        reflects the count of newly inserted rows."""
        entries = [
            _entry(slc_pattern="10 6021 01", line_id="6021", column_id="01"),
            _entry(slc_pattern="10 1888 01", line_id="1888", column_id="01"),
        ]
        inserted = insert_changelog_entries(engine, entries)
        assert inserted == 2

    def test_insert_empty_list(self, engine, session):
        """Passing an empty list inserts nothing and returns 0."""
        assert insert_changelog_entries(engine, []) == 0

    def test_insert_mix_of_null_and_non_null_slc(self, engine, session):
        """A batch containing both a non-null-SLC entry and a null-SLC entry inserts both rows
        and returns 2."""
        entries = [
            _entry(slc_pattern="10 6021 01", line_id="6021", column_id="01"),
            _entry(
                slc_pattern=None,
                line_id=None,
                column_id=None,
                change_type="new_schedule",
            ),
        ]
        inserted = insert_changelog_entries(engine, entries)
        assert inserted == 2


# ---------------------------------------------------------------------------
# save_to_csv / load_from_csv
# ---------------------------------------------------------------------------


class TestCSVRoundtrip:
    def test_save_and_load(self, tmp_path):
        """Entries saved with save_to_csv and reloaded with load_from_csv match the originals:
        year is cast to int, and None values for nullable fields (line_id, slc_pattern) are
        preserved rather than converted to empty strings."""
        entries = [
            _entry(slc_pattern="10 6021 01", line_id="6021", column_id="01"),
            _entry(slc_pattern="40 xxxx 05", line_id=None, column_id="05"),
            _entry(
                slc_pattern=None,
                line_id=None,
                column_id=None,
                change_type="new_schedule",
            ),
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
        """An entry saved to CSV, reloaded with load_from_csv, and passed to
        insert_changelog_entries is inserted successfully into the database."""
        entries = [_entry()]
        csv_path = tmp_path / "changelog.csv"
        save_to_csv(entries, csv_path)
        loaded = load_from_csv(csv_path)
        inserted = insert_changelog_entries(engine, loaded)
        assert inserted == 1

    def test_save_creates_parent_dirs(self, tmp_path):
        """save_to_csv creates any missing parent directories before writing the file."""
        nested = tmp_path / "a" / "b" / "test.csv"
        save_to_csv([_entry()], nested)
        assert nested.exists()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLI:
    def test_load_changelogs_missing_dir(self, tmp_path, mocker):
        """Passing a csv-dir that does not exist causes the command to exit with a non-zero
        status code."""
        mocker.patch("municipal_finances.fir_instructions.extract_changelog.get_engine")
        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path / "nonexistent")],
        )
        assert result.exit_code != 0

    def test_load_changelogs_empty_dir(self, tmp_path, mocker):
        """A csv-dir that exists but contains no 'FIR* Changes.csv' files causes the command
        to exit with a non-zero status code."""
        mocker.patch("municipal_finances.fir_instructions.extract_changelog.get_engine")
        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_load_changelogs_skips_unrecognised_filename(
        self, tmp_path, engine, session, mocker
    ):
        """A file that matches the 'FIR* Changes.csv' glob but lacks a 4-digit year (e.g.
        'FIRabc Changes.csv') is logged and skipped; a valid file in the same directory is
        still processed and the command exits successfully."""
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        bad_csv = tmp_path / "FIRabc Changes.csv"
        bad_csv.write_text("Schedule,SLC,Heading,Description,Section Description\n")
        valid_csv = tmp_path / "FIR2025 Changes.csv"
        with open(valid_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "Schedule",
                    "SLC",
                    "Heading",
                    "Description",
                    "Section Description",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Schedule": "10",
                    "SLC": "10 6021 01",
                    "Heading": "H",
                    "Description": "New line.",
                    "Section Description": "Minor Changes:",
                }
            )

        export_dir = tmp_path / "exports"
        result = runner.invoke(
            app,
            [
                "load-changelogs",
                "--csv-dir",
                str(tmp_path),
                "--export-dir",
                str(export_dir),
            ],
        )
        assert result.exit_code == 0, result.output

    def test_load_changelogs_with_csv(self, tmp_path, engine, session, mocker):
        """A valid 'FIR{year} Changes.csv' file is parsed, inserted into the database, and
        a combined export CSV is written to the export directory; the command exits with 0."""
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        csv_path = tmp_path / "FIR2025 Changes.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "Schedule",
                    "SLC",
                    "Heading",
                    "Description",
                    "Section Description",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Schedule": "10",
                    "SLC": "10 6021 01",
                    "Heading": "Test Heading",
                    "Description": "New line.",
                    "Section Description": "Minor Changes:",
                }
            )

        export_dir = tmp_path / "exports"
        result = runner.invoke(
            app,
            [
                "load-changelogs",
                "--csv-dir",
                str(tmp_path),
                "--export-dir",
                str(export_dir),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (export_dir / "fir_instruction_changelog.csv").exists()

        rows = session.exec(select(FIRInstructionChangelog)).all()
        assert len(rows) == 1
        assert rows[0].year == 2025

    def test_load_changelogs_no_parseable_entries(
        self, tmp_path, engine, session, mocker
    ):
        """A header-only CSV produces zero parsed entries; the command exits with a non-zero
        status code and writes an error message."""
        mocker.patch(
            "municipal_finances.fir_instructions.extract_changelog.get_engine",
            return_value=engine,
        )
        csv_path = tmp_path / "FIR2025 Changes.csv"
        csv_path.write_text("Schedule,SLC,Heading,Description,Section Description\n")

        result = runner.invoke(
            app,
            ["load-changelogs", "--csv-dir", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_export_changelog(self, tmp_path, engine, session, mocker):
        """export-changelog queries all pdf_changelog rows from the database and writes them
        to a CSV in the specified export directory; the exported file can be reloaded cleanly."""
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
