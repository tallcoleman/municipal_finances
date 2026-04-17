"""Tests for fir_instructions/extract_column_meta.py.

Covers heading parser, per-schedule extraction, all-schedule extraction,
CSV round-trip, DB insertion, baseline CSV content, and CLI commands.

DB tests require the test PostgreSQL container (localhost:5433).
Baseline CSV tests are skipped when the CSV has not yet been generated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from municipal_finances.fir_instructions.extract_column_meta import (
    _CSV_FIELDS,
    _extract_per_schedule_columns,
    _parse_column_heading,
    app,
    extract_all_column_meta,
    insert_column_meta,
    load_from_csv,
    save_to_csv,
)
from municipal_finances.fir_instructions.extract_schedule_meta import (
    SCHEDULE_CATEGORIES,
)
from municipal_finances.models import FIRColumnMeta, FIRScheduleMeta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASELINE_CSV = Path("fir_instructions/exports/baseline_column_meta.csv")

# Schedules confirmed to have column descriptions in FIR2025 markdown.
_SCHEDULES_WITH_COLUMNS: frozenset[str] = frozenset(
    {"12", "20", "22", "24", "26", "28", "40", "51A", "51B", "61A", "61B", "72", "74", "74E", "80", "80D"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_column_record(**overrides: Any) -> dict[str, Any]:
    """Build a minimal valid column metadata record."""
    base: dict[str, Any] = {
        "schedule": "12",
        "column_id": "01",
        "column_name": "Ontario Conditional Grants",
        "description": "Grants from the Province of Ontario.",
        "valid_from_year": None,
        "valid_to_year": None,
        "change_notes": None,
    }
    return {**base, **overrides}


def _load_baseline() -> list[dict[str, Any]]:
    """Load the pre-extracted baseline CSV; skip if it does not exist."""
    if not _BASELINE_CSV.exists():
        pytest.skip(f"Baseline CSV not found: {_BASELINE_CSV}")  # pragma: no cover
    return load_from_csv(_BASELINE_CSV)


def _insert_schedule_meta_for_test(engine: Any, schedules: list[str]) -> None:
    """Insert minimal schedule rows so column meta FK can be resolved."""
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
# 1. Heading parser
# ---------------------------------------------------------------------------


class TestParseColumnHeading:
    def test_standard_dash_separator(self) -> None:
        """'Column 1 - Ontario Conditional Grants' parses to (id, name)."""
        result = _parse_column_heading("Column 1 - Ontario Conditional Grants")
        assert result == ("01", "Ontario Conditional Grants")

    def test_zero_padded_single_digit(self) -> None:
        """Single-digit column numbers are zero-padded to 2 characters."""
        result = _parse_column_heading("Column 3 - Materials")
        assert result is not None
        assert result[0] == "03"

    def test_two_digit_column_number(self) -> None:
        """Two-digit column numbers (e.g. 16) are preserved as-is."""
        result = _parse_column_heading("Column 16 - Amortization")
        assert result == ("16", "Amortization")

    def test_colon_variant_s51a(self) -> None:
        """'Column 1: - Name' (S51A variant) is parsed correctly."""
        result = _parse_column_heading("Column 1: - Opening Net Book Value")
        assert result == ("01", "Opening Net Book Value")

    def test_en_dash_separator(self) -> None:
        """En-dash (–) separator is handled."""
        result = _parse_column_heading("Column 2 \u2013 Canada Conditional Grants")
        assert result is not None
        assert result[0] == "02"

    def test_em_dash_separator(self) -> None:
        """Em-dash (—) separator is handled."""
        result = _parse_column_heading("Column 4 \u2014 Contracted Services")
        assert result is not None
        assert result[0] == "04"

    def test_trailing_colon_stripped(self) -> None:
        """Trailing colon on column_name is stripped."""
        result = _parse_column_heading("Column 1 - Ontario Conditional Grants:")
        assert result is not None
        assert not result[1].endswith(":")

    def test_non_column_heading_returns_none(self) -> None:
        """A non-column heading returns None."""
        assert _parse_column_heading("Description of Columns") is None
        assert _parse_column_heading("Line 0299 - Taxation") is None
        assert _parse_column_heading("General Notes") is None

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        result = _parse_column_heading("column 5 - User Fees")
        assert result is not None
        assert result[0] == "05"


# ---------------------------------------------------------------------------
# 2. Per-schedule extraction
# ---------------------------------------------------------------------------


class TestExtractPerScheduleColumns:
    def test_extracts_columns_from_schedule_file(self, tmp_path: Path) -> None:
        """Column records are extracted from a markdown file with column headings."""
        md = tmp_path / "FIR2025 S12.md"
        md.write_text(
            "## Description of Columns\n\n"
            "## Column 1 - Ontario Conditional Grants\n\n"
            "Grants from the Province of Ontario.\n\n"
            "## Column 2 - Canada Conditional Grants\n\n"
            "Grants from the Government of Canada.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "12")
        assert len(records) == 2
        assert records[0]["column_id"] == "01"
        assert records[0]["column_name"] == "Ontario Conditional Grants"
        assert records[0]["description"] == "Grants from the Province of Ontario."
        assert records[1]["column_id"] == "02"
        assert records[1]["column_name"] == "Canada Conditional Grants"

    def test_empty_body_uses_default_description(self, tmp_path: Path) -> None:
        """A column heading with no body text gets 'No description provided.'."""
        md = tmp_path / "FIR2025 S12.md"
        md.write_text(
            "## Column 1 - Ontario Conditional Grants\n\n"
            "## Column 2 - Canada Conditional Grants\n\n"
            "Has some text.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "12")
        assert records[0]["description"] == "No description provided."
        assert records[1]["description"] == "Has some text."

    def test_no_column_headings_returns_empty(self, tmp_path: Path) -> None:
        """A schedule markdown with no Column headings produces no records."""
        md = tmp_path / "FIR2025 S10.md"
        md.write_text(
            "## Line 0299 - Taxation Own Purposes\n\nTaxation description.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "10")
        assert records == []

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """A missing markdown file produces no records."""
        records = _extract_per_schedule_columns(tmp_path, "99")
        assert records == []

    def test_deduplicate_column_id(self, tmp_path: Path) -> None:
        """Duplicate column_id headings keep only the first occurrence."""
        md = tmp_path / "FIR2025 S12.md"
        md.write_text(
            "## Column 1 - First Name\n\nFirst description.\n\n"
            "## Column 1 - Duplicate\n\nShould be ignored.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "12")
        assert len(records) == 1
        assert records[0]["column_name"] == "First Name"

    def test_valid_from_to_year_null(self, tmp_path: Path) -> None:
        """Baseline records have NULL year fields."""
        md = tmp_path / "FIR2025 S12.md"
        md.write_text(
            "## Column 1 - Ontario Conditional Grants\n\nDescription.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "12")
        assert records[0]["valid_from_year"] is None
        assert records[0]["valid_to_year"] is None

    def test_schedule_code_set_on_record(self, tmp_path: Path) -> None:
        """Each record carries the correct schedule code."""
        md = tmp_path / "FIR2025 S40.md"
        md.write_text(
            "## Column 1 - Salaries, Wages, and Employee Benefits\n\nDescription.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "40")
        assert records[0]["schedule"] == "40"

    def test_colon_variant_extracted(self, tmp_path: Path) -> None:
        """Column headings using 'Column N: - Name' (S51A variant) are extracted."""
        md = tmp_path / "FIR2025 S51.md"
        md.write_text(
            "## Schedule 51A: Tangible Capital Assets by Function\n\n"
            "## Column 1: - Opening Net Book Value\n\nDescription.\n\n"
            "## Column 2: - Opening Cost Balance\n\nDescription.\n",
            encoding="utf-8",
        )
        records = _extract_per_schedule_columns(tmp_path, "51A")
        assert len(records) == 2
        assert records[0]["column_id"] == "01"
        assert records[0]["column_name"] == "Opening Net Book Value"


# ---------------------------------------------------------------------------
# 3. All-schedule extraction
# ---------------------------------------------------------------------------


class TestExtractAllColumnMeta:
    def test_returns_records_for_schedules_with_columns(
        self, tmp_path: Path
    ) -> None:
        """extract_all_column_meta returns records only for schedules with columns."""
        # Provide column-format files for a couple of schedules
        (tmp_path / "FIR2025 S12.md").write_text(
            "## Column 1 - Ontario Conditional Grants\n\nDescription.\n",
            encoding="utf-8",
        )
        (tmp_path / "FIR2025 S40.md").write_text(
            "## Column 1 - Salaries\n\nDescription.\n"
            "## Column 2 - Interest\n\nDescription.\n",
            encoding="utf-8",
        )
        # All other schedule files are absent → skipped
        records = extract_all_column_meta(tmp_path)
        schedules_found = {r["schedule"] for r in records}
        assert "12" in schedules_found
        assert "40" in schedules_found
        assert len(records) == 3

    def test_empty_dir_returns_no_records(self, tmp_path: Path) -> None:
        """When no markdown files exist, no records are produced."""
        records = extract_all_column_meta(tmp_path)
        assert records == []

    def test_all_records_have_required_fields(self, tmp_path: Path) -> None:
        """Every extracted record contains all required CSV fields."""
        (tmp_path / "FIR2025 S12.md").write_text(
            "## Column 1 - Ontario Conditional Grants\n\nDescription.\n",
            encoding="utf-8",
        )
        records = extract_all_column_meta(tmp_path)
        for r in records:
            for field in _CSV_FIELDS:
                assert field in r, f"Missing field '{field}' in record {r}"


# ---------------------------------------------------------------------------
# 4. CSV round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadCSV:
    def test_round_trip_preserves_all_fields(self, tmp_path: Path) -> None:
        """save_to_csv + load_from_csv preserves all field values."""
        records = [
            _minimal_column_record(),
            _minimal_column_record(
                schedule="40",
                column_id="02",
                column_name="Interest on Long-Term Debt",
                description="Interest description.",
                valid_from_year=2023,
                valid_to_year=None,
                change_notes="Added in 2023.",
            ),
        ]
        csv_path = tmp_path / "test.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)

        assert len(loaded) == 2
        assert loaded[0]["schedule"] == "12"
        assert loaded[0]["column_id"] == "01"
        assert loaded[0]["column_name"] == "Ontario Conditional Grants"
        assert loaded[1]["valid_from_year"] == 2023
        assert loaded[1]["valid_to_year"] is None
        assert loaded[1]["change_notes"] == "Added in 2023."

    def test_nullable_fields_round_trip_as_none(self, tmp_path: Path) -> None:
        """Nullable fields stored as empty strings in CSV are loaded back as None."""
        records = [_minimal_column_record(description=None, change_notes=None)]
        csv_path = tmp_path / "test.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["description"] is None
        assert loaded[0]["change_notes"] is None

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """save_to_csv creates missing parent directories."""
        csv_path = tmp_path / "nested" / "dir" / "output.csv"
        save_to_csv([_minimal_column_record()], csv_path)
        assert csv_path.exists()

    def test_multiline_description_preserved(self, tmp_path: Path) -> None:
        """Multi-line description text survives the CSV round-trip."""
        desc = "First paragraph.\n\nSecond paragraph."
        records = [_minimal_column_record(description=desc)]
        csv_path = tmp_path / "test.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["description"] == desc

    def test_null_year_integers_round_trip(self, tmp_path: Path) -> None:
        """NULL year fields survive as Python None after CSV round-trip."""
        records = [_minimal_column_record(valid_from_year=None, valid_to_year=None)]
        csv_path = tmp_path / "test.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["valid_from_year"] is None
        assert loaded[0]["valid_to_year"] is None

    def test_integer_year_fields_loaded_as_int(self, tmp_path: Path) -> None:
        """Non-null year fields are loaded back as Python ints, not strings."""
        records = [_minimal_column_record(valid_from_year=2022, valid_to_year=2024)]
        csv_path = tmp_path / "test.csv"
        save_to_csv(records, csv_path)
        loaded = load_from_csv(csv_path)
        assert loaded[0]["valid_from_year"] == 2022
        assert isinstance(loaded[0]["valid_from_year"], int)


# ---------------------------------------------------------------------------
# 5. Database insertion
# ---------------------------------------------------------------------------


class TestInsertColumnMeta:
    def test_insert_single_record(self, engine: Any, session: Session) -> None:
        """A single valid record can be inserted and retrieved from the DB."""
        _insert_schedule_meta_for_test(engine, ["12"])
        records = [_minimal_column_record()]
        inserted = insert_column_meta(engine, records)
        assert inserted == 1

        rows = session.exec(select(FIRColumnMeta)).all()
        assert len(rows) == 1
        assert rows[0].schedule == "12"
        assert rows[0].column_id == "01"
        assert rows[0].column_name == "Ontario Conditional Grants"

    def test_insert_returns_count(self, engine: Any, session: Session) -> None:
        """insert_column_meta returns the number of rows actually inserted."""
        _insert_schedule_meta_for_test(engine, ["12", "40"])
        records = [
            _minimal_column_record(schedule="12", column_id="01"),
            _minimal_column_record(schedule="40", column_id="01", column_name="Salaries"),
        ]
        inserted = insert_column_meta(engine, records)
        assert inserted == 2

    def test_idempotent_insertion(self, engine: Any, session: Session) -> None:
        """Re-inserting the same records returns 0 (application-layer dedup)."""
        _insert_schedule_meta_for_test(engine, ["12"])
        records = [_minimal_column_record()]
        first = insert_column_meta(engine, records)
        second = insert_column_meta(engine, records)
        assert first == 1
        assert second == 0
        assert len(session.exec(select(FIRColumnMeta)).all()) == 1

    def test_insert_empty_list(self, engine: Any, session: Session) -> None:
        """Inserting an empty list is a no-op and returns 0."""
        assert insert_column_meta(engine, []) == 0

    def test_baseline_rows_have_null_year_fields(
        self, engine: Any, session: Session
    ) -> None:
        """Baseline records have NULL year fields stored as NULL in the DB."""
        _insert_schedule_meta_for_test(engine, ["12"])
        insert_column_meta(engine, [_minimal_column_record()])
        row = session.exec(select(FIRColumnMeta)).first()
        assert row is not None
        assert row.valid_from_year is None
        assert row.valid_to_year is None

    def test_schedule_id_fk_resolved(self, engine: Any, session: Session) -> None:
        """schedule_id FK is populated from fir_schedule_meta."""
        _insert_schedule_meta_for_test(engine, ["12"])
        insert_column_meta(engine, [_minimal_column_record()])
        row = session.exec(select(FIRColumnMeta)).first()
        assert row is not None
        assert row.schedule_id is not None

    def test_multiple_schedules_inserted(self, engine: Any, session: Session) -> None:
        """Records for multiple schedules are all inserted correctly."""
        _insert_schedule_meta_for_test(engine, ["12", "40", "72"])
        records = [
            _minimal_column_record(schedule="12", column_id="01"),
            _minimal_column_record(schedule="40", column_id="01", column_name="Salaries"),
            _minimal_column_record(schedule="72", column_id="01", column_name="English Public"),
        ]
        inserted = insert_column_meta(engine, records)
        assert inserted == 3


# ---------------------------------------------------------------------------
# 6. Baseline CSV content tests (skipped if CSV absent)
# ---------------------------------------------------------------------------


class TestBaselineCSVContent:
    @pytest.fixture(scope="class")
    def records(self) -> list[dict[str, Any]]:
        return _load_baseline()

    def test_schedules_with_columns_are_present(
        self, records: list[dict[str, Any]]
    ) -> None:
        """All schedules known to have column descriptions appear in the baseline CSV."""
        found = {r["schedule"] for r in records}
        missing = _SCHEDULES_WITH_COLUMNS - found
        assert missing == set(), f"Expected schedule codes missing: {sorted(missing)}"

    def test_column_id_format(self, records: list[dict[str, Any]]) -> None:
        """All column_id values are 2-digit numeric strings."""
        import re

        bad = [
            f"{r['schedule']}:{r['column_id']}"
            for r in records
            if not re.match(r"^\d{2}$", r.get("column_id", ""))
        ]
        assert bad == [], f"Invalid column_id values: {bad[:20]}"

    def test_no_duplicate_column_ids_per_schedule(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Each (schedule, column_id) combination is unique in the baseline."""
        from collections import Counter

        counts = Counter((r["schedule"], r["column_id"]) for r in records)
        dupes = [key for key, count in counts.items() if count > 1]
        assert dupes == [], f"Duplicate (schedule, column_id) pairs: {dupes[:10]}"

    def test_year_fields_null_in_baseline(self, records: list[dict[str, Any]]) -> None:
        """All baseline rows have NULL valid_from_year and valid_to_year."""
        non_null = [
            f"{r['schedule']}:{r['column_id']}"
            for r in records
            if r.get("valid_from_year") is not None
            or r.get("valid_to_year") is not None
        ]
        assert non_null == [], f"Non-null year fields on: {non_null}"

    def test_no_empty_column_names(self, records: list[dict[str, Any]]) -> None:
        """No column_name field is empty or whitespace-only."""
        bad = [
            f"{r['schedule']}:{r['column_id']}"
            for r in records
            if not r.get("column_name", "").strip()
        ]
        assert bad == [], f"Empty column_name on: {bad}"

    def test_all_descriptions_non_empty(self, records: list[dict[str, Any]]) -> None:
        """Every row has a non-empty description."""
        missing = [
            f"{r['schedule']}:{r['column_id']}"
            for r in records
            if not r.get("description", "").strip()
        ]
        assert missing == [], f"Empty description on: {missing}"

    def test_spot_check_s12_column_count(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Schedule 12 has at least 7 column records."""
        s12 = [r for r in records if r["schedule"] == "12"]
        assert len(s12) >= 7, f"Expected ≥7 columns for S12, got {len(s12)}"

    def test_spot_check_s40_column_count(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Schedule 40 has at least 10 column records."""
        s40 = [r for r in records if r["schedule"] == "40"]
        assert len(s40) >= 10, f"Expected ≥10 columns for S40, got {len(s40)}"

    def test_spot_check_s51a_column_count(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Schedule 51A has at least 11 column records."""
        s51a = [r for r in records if r["schedule"] == "51A"]
        assert len(s51a) >= 11, f"Expected ≥11 columns for S51A, got {len(s51a)}"

    def test_spot_check_s72_columns(self, records: list[dict[str, Any]]) -> None:
        """Schedule 72 has exactly 9 column records."""
        s72 = [r for r in records if r["schedule"] == "72"]
        assert len(s72) == 9, f"Expected 9 columns for S72, got {len(s72)}"


# ---------------------------------------------------------------------------
# 7. CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_extract_command_creates_csv(self, tmp_path: Path) -> None:
        """extract-baseline-column-meta creates the CSV file."""
        md_dir = tmp_path / "markdown"
        md_dir.mkdir()
        # Provide column files for a couple of schedules
        (md_dir / "FIR2025 S12.md").write_text(
            "## Column 1 - Ontario Conditional Grants\n\nDescription.\n",
            encoding="utf-8",
        )
        for code in SCHEDULE_CATEGORIES:
            path = md_dir / f"FIR2025 S{code}.md"
            if not path.exists():
                path.write_text("## General Notes\n\nNo columns here.\n", encoding="utf-8")

        export_path = tmp_path / "exports" / "column_meta.csv"
        runner = CliRunner()
        with patch(
            "municipal_finances.fir_instructions.extract_column_meta.get_engine"
        ) as mock_engine_fn:
            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            with patch(
                "municipal_finances.fir_instructions.extract_column_meta.insert_column_meta",
                return_value=1,
            ):
                result = runner.invoke(
                    app,
                    [
                        "extract-baseline-column-meta",
                        "--markdown-dir",
                        str(md_dir),
                        "--export-path",
                        str(export_path),
                    ],
                )

        assert result.exit_code == 0, result.output
        assert export_path.exists(), "CSV file was not created"

    def test_extract_command_no_db_skip(self, tmp_path: Path) -> None:
        """extract-baseline-column-meta with --no-load-db skips DB insertion."""
        md_dir = tmp_path / "markdown"
        md_dir.mkdir()
        export_path = tmp_path / "column_meta.csv"
        runner = CliRunner()
        with patch(
            "municipal_finances.fir_instructions.extract_column_meta.get_engine"
        ) as mock_engine_fn:
            result = runner.invoke(
                app,
                [
                    "extract-baseline-column-meta",
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
        """load-baseline-column-meta reads CSV and calls insert_column_meta."""
        records = [_minimal_column_record()]
        csv_path = tmp_path / "column_meta.csv"
        save_to_csv(records, csv_path)

        runner = CliRunner()
        with patch(
            "municipal_finances.fir_instructions.extract_column_meta.get_engine"
        ) as mock_engine_fn:
            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            with patch(
                "municipal_finances.fir_instructions.extract_column_meta.insert_column_meta",
                return_value=1,
            ) as mock_insert:
                result = runner.invoke(
                    app,
                    ["load-baseline-column-meta", "--csv-path", str(csv_path)],
                )
                assert mock_insert.called

        assert result.exit_code == 0, result.output
        assert "Inserted 1" in result.output
