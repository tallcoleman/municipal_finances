"""Tests for fir_instructions/validate_schedule_coverage.py.

Covers CSV loading, gap detection (both directions), X-suffix normalisation,
count aggregation, output formatting, CLI option handling, and a real-DB
integration path via the test PostgreSQL container.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sqlmodel import Session
from typer.testing import CliRunner

from municipal_finances.fir_instructions.validate_schedule_coverage import app
from municipal_finances.models import FIRRecord, Municipality

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_GET_ENGINE = "municipal_finances.fir_instructions.validate_schedule_coverage.get_engine"
_PATCH_SESSION = "municipal_finances.fir_instructions.validate_schedule_coverage.Session"

runner = CliRunner()


def _write_schedule_csv(path: Path, schedules: list[str]) -> None:
    """Write a minimal schedule metadata CSV with the given schedule codes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["schedule", "schedule_name", "category", "description",
                        "valid_from_year", "valid_to_year"],
        )
        writer.writeheader()
        for s in schedules:
            writer.writerow({
                "schedule": s,
                "schedule_name": f"Schedule {s}",
                "category": "Test",
                "description": "Test description.",
                "valid_from_year": "",
                "valid_to_year": "",
            })


def _mock_session(rows: list[tuple[str, int]]) -> MagicMock:
    """Build a mock session whose execute().fetchall() returns the given rows."""
    mock_sess = MagicMock()
    mock_sess.execute.return_value.fetchall.return_value = rows
    return mock_sess


def _invoke(csv_path: Path, db_rows: list[tuple[str, int]], year: int = 2025) -> Any:
    """Invoke validate-schedule-coverage CLI with a mocked DB returning db_rows."""
    mock_sess = _mock_session(db_rows)
    with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
        with patch(_PATCH_SESSION) as MockSession:
            MockSession.return_value.__enter__.return_value = mock_sess
            MockSession.return_value.__exit__.return_value = False
            return runner.invoke(
                app,
                ["--csv-path", str(csv_path), "--year", str(year)],
            )


# ---------------------------------------------------------------------------
# 1. No-gap path
# ---------------------------------------------------------------------------


class TestNoGaps:
    def test_success_message_when_all_covered(self, tmp_path: Path) -> None:
        """'No gaps found' message is printed when CSV and DB schedules match exactly."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22", "40"])
        result = _invoke(csv_path, [("22", 100), ("40", 50)])
        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_empty_db_and_empty_csv_no_gaps(self, tmp_path: Path) -> None:
        """Empty DB and empty CSV → no gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [])
        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_exit_code_zero_when_no_gaps(self, tmp_path: Path) -> None:
        """Exit code is 0 when there are no gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["12"])
        result = _invoke(csv_path, [("12", 10)])
        assert result.exit_code == 0

    def test_loaded_count_echoed(self, tmp_path: Path) -> None:
        """The number of schedule codes loaded from the CSV is echoed."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["12", "22", "40"])
        result = _invoke(csv_path, [])
        assert "3" in result.output

    def test_db_schedule_count_echoed(self, tmp_path: Path) -> None:
        """The number of distinct schedule codes found in the DB is echoed."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22"])
        result = _invoke(csv_path, [("22", 5)])
        assert "1" in result.output


# ---------------------------------------------------------------------------
# 2. In-DB-not-CSV gap detection
# ---------------------------------------------------------------------------


class TestInDBNotCSV:
    def test_db_only_schedule_reported(self, tmp_path: Path) -> None:
        """A schedule in the DB but absent from the CSV is reported."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22"])
        result = _invoke(csv_path, [("22", 100), ("40", 50)])
        assert result.exit_code == 0, result.output
        assert "40" in result.output

    def test_covered_schedule_not_in_db_only_list(self, tmp_path: Path) -> None:
        """A schedule present in both CSV and DB does not appear in the DB-only list."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22"])
        result = _invoke(csv_path, [("22", 100), ("40", 50)])
        in_db_section = result.output
        # 22 is covered so should not appear in the gap list
        lines_with_22 = [
            line for line in in_db_section.splitlines()
            if "22" in line and "extractor" not in line and "Loaded" not in line
        ]
        assert not any("  22 " in line for line in lines_with_22)

    def test_db_only_count_in_header(self, tmp_path: Path) -> None:
        """Count of DB-only schedules appears in the 'in DB but NOT in CSV' header."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("22", 10), ("40", 20)])
        assert "2" in result.output
        assert "NOT in CSV" in result.output

    def test_record_count_shown_per_db_gap(self, tmp_path: Path) -> None:
        """Record count is printed next to each DB-only gap schedule."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("99", 12345)])
        assert "12,345" in result.output

    def test_empty_csv_all_db_schedules_are_gaps(self, tmp_path: Path) -> None:
        """All DB schedules appear as gaps when the CSV is empty."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("22", 10), ("40", 20)])
        assert "22" in result.output
        assert "40" in result.output


# ---------------------------------------------------------------------------
# 3. In-CSV-not-DB gap detection
# ---------------------------------------------------------------------------


class TestInCSVNotDB:
    def test_csv_only_schedule_reported(self, tmp_path: Path) -> None:
        """A schedule in the CSV but absent from the DB is reported."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22", "51"])
        result = _invoke(csv_path, [("22", 100)])
        assert "51" in result.output
        assert "NOT in DB" in result.output

    def test_csv_only_count_in_header(self, tmp_path: Path) -> None:
        """Count of CSV-only schedules appears in the header."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22", "40", "51"])
        result = _invoke(csv_path, [])
        assert "3" in result.output
        assert "NOT in DB" in result.output

    def test_db_matched_schedule_not_in_csv_only_list(self, tmp_path: Path) -> None:
        """A schedule in both CSV and DB does not appear in the CSV-only list."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22", "51"])
        result = _invoke(csv_path, [("22", 100)])
        # '22' is covered; only '51' should appear in the CSV-only section
        csv_only_section_lines = [
            line for line in result.output.splitlines()
            if "  " in line
        ]
        csv_only_codes = [line.strip() for line in csv_only_section_lines]
        assert not any(c == "22" for c in csv_only_codes)

    def test_empty_db_all_csv_schedules_listed(self, tmp_path: Path) -> None:
        """All CSV schedules appear in the CSV-only list when DB returns nothing."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["10", "20", "30"])
        result = _invoke(csv_path, [])
        assert "10" in result.output
        assert "20" in result.output
        assert "30" in result.output


# ---------------------------------------------------------------------------
# 4. X-suffix normalisation
# ---------------------------------------------------------------------------


class TestXSuffixNormalisation:
    def test_x_suffix_resolved_to_base_code(self, tmp_path: Path) -> None:
        """DB returns base_schedule_code '12' (X stripped by SQL); covered by '12' in CSV."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["12"])
        result = _invoke(csv_path, [("12", 105)])
        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_x_suffix_without_base_metadata_still_a_gap(self, tmp_path: Path) -> None:
        """DB returns '99' (base_schedule_code); still a gap when '99' is not in the CSV."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["12"])
        result = _invoke(csv_path, [("99", 53)])
        assert "99" in result.output

    def test_sub_schedule_matched_to_base_in_csv(self, tmp_path: Path) -> None:
        """A sub-schedule ('26A') returns base_schedule_code '26'; covered by '26' in CSV."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["26"])
        result = _invoke(csv_path, [("26", 352)])
        assert "No gaps found" in result.output

    def test_sql_aggregated_counts_shown(self, tmp_path: Path) -> None:
        """SQL pre-aggregates by base_schedule_code; mock returns a single merged row."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        # SQL GROUP BY base_schedule_code merges all sub-schedules before Python sees them
        result = _invoke(csv_path, [("12", 150)])
        assert "150" in result.output
        gap_lines = [line for line in result.output.splitlines() if "  12" in line]
        assert len(gap_lines) == 1, f"Expected 1 gap line for '12', got: {gap_lines}"

    def test_x_suffix_covered_base_in_csv_no_gap(self, tmp_path: Path) -> None:
        """DB returns base_schedule_codes without X suffix; all covered by CSV entries."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["20", "40"])
        result = _invoke(csv_path, [("20", 18), ("40", 9)])
        assert "No gaps found" in result.output


# ---------------------------------------------------------------------------
# 5. Output formatting
# ---------------------------------------------------------------------------


class TestOutputFormatting:
    def test_db_gap_section_header_present(self, tmp_path: Path) -> None:
        """The 'in DB but NOT in CSV' section header is printed when there are DB gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("22", 10)])
        assert "NOT in CSV" in result.output

    def test_csv_gap_section_header_present(self, tmp_path: Path) -> None:
        """The 'in CSV but NOT in DB' section header is printed when there are CSV gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22"])
        result = _invoke(csv_path, [])
        assert "NOT in DB" in result.output

    def test_multiple_db_gaps_all_listed(self, tmp_path: Path) -> None:
        """All DB-only schedules are listed in the output."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("12", 10), ("40", 20), ("72A", 5)])
        assert "12" in result.output
        assert "40" in result.output
        assert "72A" in result.output

    def test_record_count_formatted_with_commas(self, tmp_path: Path) -> None:
        """Large record counts are formatted with comma separators."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("99", 1_000_000)])
        assert "1,000,000" in result.output

    def test_csv_path_echoed_in_output(self, tmp_path: Path) -> None:
        """The CSV path used is echoed in the output."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [])
        assert str(csv_path) in result.output


# ---------------------------------------------------------------------------
# 6. CLI option handling
# ---------------------------------------------------------------------------


class TestCLIOptions:
    def test_default_year_passed_to_query(self, tmp_path: Path) -> None:
        """Default year (2025) is passed to the DB query."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        mock_sess = _mock_session([])
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
            with patch(_PATCH_SESSION) as MockSession:
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False
                runner.invoke(app, ["--csv-path", str(csv_path)])
        call_kwargs = mock_sess.execute.call_args
        assert call_kwargs is not None
        params = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
        assert params == {"year": 2025}

    def test_custom_year_passed_to_query(self, tmp_path: Path) -> None:
        """A custom --year value is forwarded to the DB query."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        mock_sess = _mock_session([])
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
            with patch(_PATCH_SESSION) as MockSession:
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False
                runner.invoke(app, ["--csv-path", str(csv_path), "--year", "2023"])
        call_kwargs = mock_sess.execute.call_args
        assert call_kwargs is not None
        params = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
        assert params == {"year": 2023}

    def test_exit_code_zero_with_gaps(self, tmp_path: Path) -> None:
        """Exit code is 0 even when gaps are found (gaps are informational, not errors)."""
        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])
        result = _invoke(csv_path, [("22", 5)])
        assert result.exit_code == 0

    def test_missing_csv_results_in_nonzero_exit(self, tmp_path: Path) -> None:
        """Invoking with a non-existent CSV path results in a non-zero exit code."""
        missing = tmp_path / "does_not_exist.csv"
        mock_sess = _mock_session([])
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
            with patch(_PATCH_SESSION) as MockSession:
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False
                result = runner.invoke(app, ["--csv-path", str(missing)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 7. Real-DB integration tests
# ---------------------------------------------------------------------------


def _seed_municipality(session: Session, munid: str = "TSTCOV") -> None:
    """Insert a minimal municipality row."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    with session.get_bind().connect() as conn:
        conn.execute(
            pg_insert(Municipality.__table__).values(
                munid=munid,
                municipality_desc="Coverage Test",
                tier_code="LT",
                mtype_code=1,
            ).on_conflict_do_nothing()
        )
        conn.commit()


def _seed_fir_records(
    session: Session,
    rows: list[dict[str, Any]],
    munid: str = "TSTCOV",
) -> None:
    """Insert FIRRecord rows with derived SLC columns into the test DB."""
    import pandas as pd
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from municipal_finances.db_management import _derive_slc_columns

    df = _derive_slc_columns(pd.DataFrame({"slc": [r["slc"] for r in rows]}))

    records = [
        {
            "munid": munid,
            "marsyear": r["marsyear"],
            "slc": r["slc"],
            "schedule_code": df["schedule_code"][i],
            "base_schedule_code": df["base_schedule_code"][i],
            "sub_schedule_code": df["sub_schedule_code"][i],
            "line_id": df["line_id"][i],
            "column_section": df["column_section"][i],
            "column_id": df["column_id"][i],
        }
        for i, r in enumerate(rows)
    ]

    with session.get_bind().connect() as conn:
        conn.execute(
            pg_insert(FIRRecord.__table__).values(records).on_conflict_do_nothing()
        )
        conn.commit()


class TestValidateScheduleCoverageRealDB:
    """Integration tests using the real test PostgreSQL container.

    Each test patches ``get_engine`` to return the test engine so the CLI reads
    from the same isolated database where seeds are inserted.
    """

    def _invoke_with_engine(self, engine: Any, csv_path: Path, year: int = 2025) -> Any:
        with patch(_PATCH_GET_ENGINE, return_value=engine):
            return runner.invoke(
                app,
                ["--csv-path", str(csv_path), "--year", str(year)],
            )

    def test_db_gap_found_via_real_query(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """A firrecord schedule with no metadata entry appears as a DB-only gap."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.22.L0010.C01.01"},
            {"marsyear": 2025, "slc": "slc.99.L0010.C01.01"},  # no metadata for 99
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22"])  # covers 22 but not 99

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "99" in result.output
        assert "NOT in CSV" in result.output

    def test_no_gaps_when_all_covered_real_db(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """No gaps when every firrecord schedule is covered by the metadata CSV."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.22.L0010.C01.01"},
            {"marsyear": 2025, "slc": "slc.22.L0020.C02.01"},
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22"])

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_x_suffix_resolved_real_db(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """'12X' schedule in firrecord is normalised to '12' and matched against CSV."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.12X.L0010.C01.01"},
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["12"])

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_year_filter_respected(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """Records from other years are excluded from the gap check."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2024, "slc": "slc.99.L0010.C01.01"},  # wrong year
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])  # no metadata

        result = self._invoke_with_engine(engine, csv_path, year=2025)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output  # 2024 record excluded

    def test_null_slc_excluded(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """FIRRecord rows with NULL slc are excluded from the DB query."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": None},
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_csv_only_schedule_reported_real_db(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """A schedule in the CSV but absent from DB data appears in the CSV-only list."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.22.L0010.C01.01"},
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, ["22", "51"])  # 51 has no DB data

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "51" in result.output
        assert "NOT in DB" in result.output

    def test_counts_aggregated_across_records_real_db(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """Multiple firrecord rows for the same schedule contribute to a single count."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.99.L0010.C01.01"},
            {"marsyear": 2025, "slc": "slc.99.L0020.C02.01"},
            {"marsyear": 2025, "slc": "slc.99.L0030.C03.01"},
        ])

        csv_path = tmp_path / "meta.csv"
        _write_schedule_csv(csv_path, [])

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "99" in result.output
        assert "3" in result.output
