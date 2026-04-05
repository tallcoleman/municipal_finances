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
