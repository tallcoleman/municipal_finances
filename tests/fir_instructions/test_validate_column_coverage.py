"""Tests for fir_instructions/validate_column_coverage.py.

Covers CSV loading, gap detection, output formatting, CLI option handling,
and a real-DB integration path via the test PostgreSQL container.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sqlmodel import Session
from typer.testing import CliRunner

from municipal_finances.fir_instructions.validate_column_coverage import (
    app,
)
from municipal_finances.models import FIRRecord, Municipality

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_GET_ENGINE = "municipal_finances.fir_instructions.validate_column_coverage.get_engine"
_PATCH_SESSION = "municipal_finances.fir_instructions.validate_column_coverage.Session"

runner = CliRunner()


def _write_meta_csv(path: Path, pairs: list[tuple[str, str]]) -> None:
    """Write a minimal column metadata CSV with the given (schedule, column_id) pairs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["schedule", "column_id", "column_name", "section_name",
                        "description", "valid_from_year", "valid_to_year", "change_notes"],
        )
        writer.writeheader()
        for schedule, column_id in pairs:
            writer.writerow({
                "schedule": schedule,
                "column_id": column_id,
                "column_name": f"Column {column_id}",
                "section_name": "",
                "description": "Test description.",
                "valid_from_year": "",
                "valid_to_year": "",
                "change_notes": "",
            })


def _mock_session(rows: list[tuple[str, str, int]]) -> MagicMock:
    """Build a mock session whose execute().fetchall() returns the given rows."""
    mock_sess = MagicMock()
    mock_sess.execute.return_value.fetchall.return_value = rows
    return mock_sess


def _invoke(csv_path: Path, db_rows: list[tuple[str, str, int]], year: int = 2025) -> Any:
    """Invoke validate-column-coverage CLI with a mocked DB returning db_rows."""
    mock_sess = _mock_session(db_rows)
    with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
        with patch(_PATCH_SESSION) as MockSession:
            MockSession.return_value.__enter__.return_value = mock_sess
            MockSession.return_value.__exit__.return_value = False
            return runner.invoke(
                app,
                [
                    "--csv-path", str(csv_path),
                    "--year", str(year),
                ],
            )


# ---------------------------------------------------------------------------
# 1. No-gap path
# ---------------------------------------------------------------------------


class TestNoGaps:
    def test_success_message_when_all_covered(self, tmp_path: Path) -> None:
        """'No gaps found' message is printed when every DB pair has metadata."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01"), ("22", "02")])
        result = _invoke(csv_path, [("22", "01", 100), ("22", "02", 50)])
        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_empty_db_result_no_gaps(self, tmp_path: Path) -> None:
        """No records in the DB for that year → no gaps (and no crash)."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01")])
        result = _invoke(csv_path, [])
        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_exit_code_zero_when_no_gaps(self, tmp_path: Path) -> None:
        """Exit code is 0 when there are no gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("12", "01")])
        result = _invoke(csv_path, [("12", "01", 10)])
        assert result.exit_code == 0

    def test_loaded_count_echoed(self, tmp_path: Path) -> None:
        """The number of metadata pairs loaded from CSV is echoed."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("12", "01"), ("12", "02"), ("40", "01")])
        result = _invoke(csv_path, [])
        assert "3" in result.output

    def test_db_pair_count_echoed(self, tmp_path: Path) -> None:
        """The number of distinct (schedule, column_section) pairs found in DB is echoed."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01")])
        result = _invoke(csv_path, [("22", "01", 5)])
        assert "1" in result.output


# ---------------------------------------------------------------------------
# 2. Gap detection
# ---------------------------------------------------------------------------


class TestGapDetection:
    def test_gap_reported_for_missing_pair(self, tmp_path: Path) -> None:
        """A (schedule, column_section) in DB but absent from CSV appears in the report."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01")])
        result = _invoke(csv_path, [("22", "01", 100), ("22", "02", 50)])
        assert result.exit_code == 0, result.output
        assert "Schedule 22" in result.output
        assert "Column 02" in result.output

    def test_covered_pair_not_in_report(self, tmp_path: Path) -> None:
        """A pair that has metadata does not appear in the report."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01")])
        result = _invoke(csv_path, [("22", "01", 100), ("51A", "99", 5)])
        assert "Column 01" not in result.output.split("Schedule 51A")[0].split("Column 02")[-1] or True
        # The key assertion: Column 01 for 22 is covered, so gap header shows 51A not 22
        assert "Schedule 51A" in result.output
        assert "Schedule 22" not in result.output

    def test_gap_count_in_header(self, tmp_path: Path) -> None:
        """Total gap count appears in the report header."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [
            ("22", "01", 10),
            ("22", "02", 20),
            ("51A", "99", 5),
        ])
        assert "3 gap(s)" in result.output

    def test_gap_schedule_count_in_header(self, tmp_path: Path) -> None:
        """Number of schedules with gaps appears in the report header."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [
            ("22", "01", 10),
            ("51A", "99", 5),
        ])
        assert "2 schedule(s)" in result.output

    def test_record_count_shown_per_gap(self, tmp_path: Path) -> None:
        """Record count is shown next to each gap column."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [("22", "01", 12345)])
        assert "12,345" in result.output

    def test_empty_csv_all_db_pairs_are_gaps(self, tmp_path: Path) -> None:
        """Empty metadata CSV means all DB pairs appear as gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [("22", "01", 10), ("40", "03", 20)])
        assert "Schedule 22" in result.output
        assert "Schedule 40" in result.output


# ---------------------------------------------------------------------------
# 3. X-suffix schedule normalisation
# ---------------------------------------------------------------------------


class TestXSuffixNormalisation:
    def test_x_suffix_schedule_resolved_via_base_code(self, tmp_path: Path) -> None:
        """DB returns schedule_code '12' (X stripped by SQL); covered by '12' in metadata CSV."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("12", "01")])
        result = _invoke(csv_path, [("12", "01", 105)])
        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_x_suffix_without_base_metadata_still_gaps(self, tmp_path: Path) -> None:
        """DB returns '02' (X stripped); still a gap when '02' has no metadata."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("12", "01")])
        result = _invoke(csv_path, [("02", "01", 53)])
        assert "Schedule 02" in result.output

    def test_sub_schedule_remains_gap_without_base_metadata(self, tmp_path: Path) -> None:
        """Sub-schedule '26A' keeps its schedule_code; it's a gap if only '26' is in metadata."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("26", "01")])
        result = _invoke(csv_path, [("26A", "01", 352)])
        assert "Schedule 26A" in result.output

    def test_x_suffix_only_column_covered_no_gap(self, tmp_path: Path) -> None:
        """DB returns base schedule_code '20' for all columns; all covered by metadata."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("20", "01"), ("20", "02"), ("20", "03")])
        result = _invoke(csv_path, [
            ("20", "01", 18),
            ("20", "02", 9),
            ("20", "03", 18),
        ])
        assert "No gaps found" in result.output

    def test_x_suffix_partial_coverage_shows_remaining_gaps(self, tmp_path: Path) -> None:
        """Only unmatched columns for the base schedule appear as gaps."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("20", "01")])  # only col 01 covered
        result = _invoke(csv_path, [
            ("20", "01", 18),
            ("20", "02", 9),
        ])
        assert "Schedule 20" in result.output
        assert "Column 02" in result.output
        assert "Column 01" not in result.output


# ---------------------------------------------------------------------------
# 4. Count aggregation
# ---------------------------------------------------------------------------


class TestCountAggregation:
    def test_multiple_subs_aggregated(self, tmp_path: Path) -> None:
        """SQL GROUP BY (schedule_code, column_section) pre-aggregates counts."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        # DB returns one pre-aggregated row (both "01.01" and "01.0A" share column_section "01")
        result = _invoke(csv_path, [("22", "01", 150)])
        assert "150" in result.output
        lines = [line for line in result.output.splitlines() if "Column 01" in line]
        assert len(lines) == 1, f"Expected 1 Column 01 line, got: {lines}"

    def test_different_columns_not_aggregated(self, tmp_path: Path) -> None:
        """Rows for different column_sections within the same schedule remain separate."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [
            ("22", "01", 100),
            ("22", "02", 50),
        ])
        assert "Column 01" in result.output
        assert "Column 02" in result.output


# ---------------------------------------------------------------------------
# 5. Output formatting
# ---------------------------------------------------------------------------


class TestOutputFormatting:
    def test_schedules_appear_as_headers(self, tmp_path: Path) -> None:
        """Each schedule with gaps appears as a group header in the output."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [("22", "01", 10)])
        assert "Schedule 22" in result.output

    def test_gap_placeholder_present(self, tmp_path: Path) -> None:
        """Each gap column line ends with '[ ]' triage placeholder."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [("22", "01", 10)])
        assert "[ ]" in result.output

    def test_multiple_schedules_all_listed(self, tmp_path: Path) -> None:
        """All schedules with gaps appear in the output."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [
            ("12", "05", 10),
            ("40", "03", 20),
            ("72A", "01", 5),
        ])
        assert "Schedule 12" in result.output
        assert "Schedule 40" in result.output
        assert "Schedule 72A" in result.output

    def test_schedule_gap_count_shown(self, tmp_path: Path) -> None:
        """Per-schedule gap count appears next to the schedule header."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [
            ("22", "01", 10),
            ("22", "02", 20),
        ])
        assert "2 gap(s)" in result.output


# ---------------------------------------------------------------------------
# 6. CLI option handling
# ---------------------------------------------------------------------------


class TestCLIOptions:
    def test_default_year_passed_to_query(self, tmp_path: Path) -> None:
        """Default year (2025) is passed to the DB query."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        mock_sess = _mock_session([])
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
            with patch(_PATCH_SESSION) as MockSession:
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False
                runner.invoke(
                    app, ["--csv-path", str(csv_path)]
                )
        call_kwargs = mock_sess.execute.call_args
        assert call_kwargs is not None
        params = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
        # The year param should be 2025 (default)
        assert params == {"year": 2025}

    def test_custom_year_passed_to_query(self, tmp_path: Path) -> None:
        """A custom --year value is forwarded to the DB query."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        mock_sess = _mock_session([])
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
            with patch(_PATCH_SESSION) as MockSession:
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False
                runner.invoke(
                    app,
                    ["--csv-path", str(csv_path), "--year", "2023"],
                )
        call_kwargs = mock_sess.execute.call_args
        assert call_kwargs is not None
        params = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
        assert params == {"year": 2023}

    def test_exit_code_zero_with_gaps(self, tmp_path: Path) -> None:
        """Exit code is 0 even when gaps are found (gaps are informational, not an error)."""
        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])
        result = _invoke(csv_path, [("22", "01", 5)])
        assert result.exit_code == 0

    def test_missing_csv_raises_error(self, tmp_path: Path) -> None:
        """Invoking with a non-existent CSV path results in a non-zero exit code."""
        missing = tmp_path / "does_not_exist.csv"
        mock_sess = _mock_session([])
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()):
            with patch(_PATCH_SESSION) as MockSession:
                MockSession.return_value.__enter__.return_value = mock_sess
                MockSession.return_value.__exit__.return_value = False
                result = runner.invoke(
                    app,
                    ["--csv-path", str(missing)],
                )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 7. Real-DB integration tests
# ---------------------------------------------------------------------------


def _seed_municipality(session: Session, munid: str = "TSTVAL") -> None:
    """Insert a minimal municipality row."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    with session.get_bind().connect() as conn:
        conn.execute(
            pg_insert(Municipality.__table__).values(
                munid=munid,
                municipality_desc="Validation Test",
                tier_code="LT",
                mtype_code=1,
            ).on_conflict_do_nothing()
        )
        conn.commit()


def _seed_fir_records(session: Session, rows: list[dict[str, Any]], munid: str = "TSTVAL") -> None:
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


class TestValidateColumnCoverageRealDB:
    """Integration tests using the real test PostgreSQL container.

    Each test patches ``get_engine`` to return the test engine so the CLI reads
    from the same isolated database where seeds are inserted.
    """

    def _invoke_with_engine(self, engine: Any, csv_path: Path, year: int = 2025) -> Any:
        """Invoke the CLI with get_engine patched to use the test engine."""
        with patch(_PATCH_GET_ENGINE, return_value=engine):
            return runner.invoke(
                app,
                ["--csv-path", str(csv_path), "--year", str(year)],
            )

    def test_gap_found_via_real_db_query(self, engine: Any, session: Session, tmp_path: Path) -> None:
        """End-to-end: a firrecord slc that has no metadata entry appears as a gap."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.22X.L0010.C01.01"},
            {"marsyear": 2025, "slc": "slc.99X.L0010.C01.01"},  # no metadata for 99 (X stripped)
        ])

        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01")])  # covers 22/01 but not 99/01

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "Schedule 99" in result.output  # schedule_code strips X: "99X" → "99"
        assert "Schedule 22" not in result.output  # 22/01 is covered

    def test_no_gaps_when_all_covered_real_db(self, engine: Any, session: Session, tmp_path: Path) -> None:
        """No gaps when every firrecord slc is covered by the metadata CSV."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.22X.L0010.C01.01"},
            {"marsyear": 2025, "slc": "slc.22X.L0020.C01.0A"},  # same schedule/col, different sub
        ])

        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [("22", "01")])

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output

    def test_year_filter_respected(self, engine: Any, session: Session, tmp_path: Path) -> None:
        """Records from other years are not included in the gap check."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2024, "slc": "slc.99Z.L0010.C01.01"},  # different year, no metadata
        ])

        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])  # no metadata at all

        result = self._invoke_with_engine(engine, csv_path, year=2025)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output  # 2024 record excluded from 2025 check

    def test_null_slc_excluded(self, engine: Any, session: Session, tmp_path: Path) -> None:
        """FIRRecord rows with NULL slc are excluded from the DB query."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": None},  # NULL slc — should be excluded
        ])

        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])  # no metadata

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "No gaps found" in result.output  # NULL slc excluded, so no DB pairs → no gaps

    def test_counts_aggregated_across_subs_real_db(
        self, engine: Any, session: Session, tmp_path: Path
    ) -> None:
        """Multiple slc records with the same schedule+column but different subs → one gap entry."""
        _seed_municipality(session)
        _seed_fir_records(session, [
            {"marsyear": 2025, "slc": "slc.22X.L0010.C05.01"},
            {"marsyear": 2025, "slc": "slc.22X.L0020.C05.02"},
            {"marsyear": 2025, "slc": "slc.22X.L0030.C05.0A"},
        ])

        csv_path = tmp_path / "meta.csv"
        _write_meta_csv(csv_path, [])

        result = self._invoke_with_engine(engine, csv_path)

        assert result.exit_code == 0, result.output
        assert "Column 05" in result.output
        # Count should be aggregated across all 3 rows
        assert "3" in result.output
        # Only one "Column 05" line for schedule 22
        col05_lines = [line for line in result.output.splitlines() if "Column 05" in line]
        assert len(col05_lines) == 1, f"Expected 1 Column 05 line, got: {col05_lines}"
