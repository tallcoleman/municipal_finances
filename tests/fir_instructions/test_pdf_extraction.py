"""Tests for fir_instructions/pdf_extraction.py.

These tests exercise the prerequisite step for schedule metadata extraction:
PDF-to-text conversion and schedule offset map building.  They require the
pre-converted ``.txt`` files in ``fir_instructions/source_files/`` to be
present (produced by ``pdftotext -layout``).  If the files are absent the
tests are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from municipal_finances.fir_instructions.pdf_extraction import (
    build_schedule_offsets,
    load_schedule_offsets,
    save_schedule_offsets,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_DIR = Path("fir_instructions/source_files")

ALL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

# The 26 schedule sections present in FIR2025 Instructions.txt, determined by
# inspecting the actual PDF text.  Excludes Schedule 02 (Declaration) and the
# internal sub-section markers 74A–74D that appear within Schedule 74's section.
EXPECTED_FIR2025_SCHEDULES = frozenset({
    "10", "12",                                    # Revenue
    "20", "22", "24", "26", "28",                  # Taxation
    "40", "42",                                    # Expense
    "51", "53", "54",                              # TCA / Net Assets / Cash Flow
    "60", "61", "62",                              # Reserves
    "70", "71", "72",                              # Financial Position / Remeasurement / Tax Continuity
    "74", "74E",                                   # Long Term Liabilities
    "76", "77",                                    # Other (GBEs, Other Entities)
    "80", "80D", "81", "83",                       # Statistical / ARL / Notes
})

# Codes that may appear in addition to EXPECTED_FIR2025_SCHEDULES — these are
# recognised internal section markers, not unexpected garbage values.
_ALLOWED_FIR2025_EXTRAS = frozenset({"02", "74A", "74B", "74C", "74D"})

# Spot-check: known Page-|1 line numbers (1-based) for FIR2025
_FIR2025_SPOT_CHECKS: dict[str, tuple[int, str]] = {
    # schedule_code: (expected_1based_line, substring that line must contain)
    "10": (3506, "Schedule 10"),
    "40": (10120, "Schedule 40"),
    "74": (15606, "Schedule 74"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _txt_path(year: int) -> Path:
    return SOURCE_DIR / f"FIR{year} Instructions.txt"


def _json_path(year: int) -> Path:
    return SOURCE_DIR / f"FIR{year} Instructions.offsets.json"


def _skip_if_missing(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"Required file not found: {path}")


# ---------------------------------------------------------------------------
# 1.  pdftotext output — non-empty .txt files
# ---------------------------------------------------------------------------

class TestPdftotextOutput:
    @pytest.mark.parametrize("year", ALL_YEARS)
    def test_txt_file_exists_and_nonempty(self, year: int) -> None:
        """pdftotext must produce a non-empty .txt file for each source PDF."""
        p = _txt_path(year)
        _skip_if_missing(p)
        assert p.stat().st_size > 0, f"{p} is empty"

    @pytest.mark.parametrize("year", ALL_YEARS)
    def test_txt_file_has_substantial_content(self, year: int) -> None:
        """Each .txt file must contain at least 5,000 lines (sanity check)."""
        p = _txt_path(year)
        _skip_if_missing(p)
        line_count = sum(1 for _ in p.open(encoding="utf-8"))
        assert line_count >= 5_000, (
            f"{p} has only {line_count} lines — conversion may have failed"
        )


# ---------------------------------------------------------------------------
# 2.  build_schedule_offsets — FIR2025 returns all 26 expected keys
# ---------------------------------------------------------------------------

class TestBuildScheduleOffsetsFIR2025:
    @pytest.fixture(scope="class")
    def offsets(self) -> dict[str, int]:
        p = _txt_path(2025)
        _skip_if_missing(p)
        return build_schedule_offsets(str(p))

    def test_all_26_expected_schedules_present(self, offsets: dict[str, int]) -> None:
        """All 26 expected FIR2025 schedule sections must be in the offset map."""
        missing = EXPECTED_FIR2025_SCHEDULES - offsets.keys()
        assert missing == set(), f"Missing schedule keys: {sorted(missing)}"

    def test_no_unexpected_extra_keys(self, offsets: dict[str, int]) -> None:
        """Offset map must contain only expected schedules or known extras."""
        extras = set(offsets.keys()) - EXPECTED_FIR2025_SCHEDULES - _ALLOWED_FIR2025_EXTRAS
        assert extras == set(), f"Unexpected schedule keys: {sorted(extras)}"

    def test_all_offsets_are_non_negative_integers(self, offsets: dict[str, int]) -> None:
        """Every line-number offset must be a non-negative integer."""
        bad = {k: v for k, v in offsets.items() if not isinstance(v, int) or v < 0}
        assert bad == {}, f"Invalid offset values: {bad}"

    def test_offsets_are_strictly_ordered(self, offsets: dict[str, int]) -> None:
        """Schedule sections must appear in document order (no two share a line)."""
        values = list(offsets.values())
        assert len(values) == len(set(values)), "Duplicate line offsets detected"


# ---------------------------------------------------------------------------
# 3.  Spot-check offsets for Schedules 10, 40, 74
# ---------------------------------------------------------------------------

class TestSpotCheckOffsets:
    @pytest.fixture(scope="class")
    def fir2025_lines(self) -> list[str]:
        p = _txt_path(2025)
        _skip_if_missing(p)
        # Use readlines() — offsets from build_schedule_offsets are indices into
        # this list (form-feed \x0c characters are part of line content, not
        # line separators, so splitlines() would produce different indices).
        with open(p, encoding="utf-8") as fh:
            return fh.readlines()

    @pytest.fixture(scope="class")
    def fir2025_offsets(self) -> dict[str, int]:
        p = _txt_path(2025)
        _skip_if_missing(p)
        return build_schedule_offsets(str(p))

    @pytest.mark.parametrize(
        "schedule, expected_line, expected_text",
        [
            ("10", 3506, "Schedule 10"),
            ("40", 10120, "Schedule 40"),
            ("74", 15606, "Schedule 74"),
        ],
    )
    def test_spot_check_offset_line_content(
        self,
        fir2025_lines: list[str],
        fir2025_offsets: dict[str, int],
        schedule: str,
        expected_line: int,
        expected_text: str,
    ) -> None:
        """Spot-checked offsets must point to lines containing schedule cover text."""
        offset = fir2025_offsets[schedule]
        line_text = fir2025_lines[offset]
        assert expected_text in line_text, (
            f"Schedule {schedule}: expected {expected_text!r} in line {offset + 1}, "
            f"got {line_text!r}"
        )

    @pytest.mark.parametrize(
        "schedule, expected_line, expected_text",
        [
            ("10", 3506, "Schedule 10"),
            ("40", 10120, "Schedule 40"),
            ("74", 15606, "Schedule 74"),
        ],
    )
    def test_spot_check_line_numbers(
        self,
        fir2025_offsets: dict[str, int],
        schedule: str,
        expected_line: int,
        expected_text: str,
    ) -> None:
        """Spot-checked offsets must match the expected 1-based line numbers."""
        offset = fir2025_offsets[schedule]
        assert offset + 1 == expected_line, (
            f"Schedule {schedule}: expected line {expected_line}, "
            f"got line {offset + 1}"
        )


# ---------------------------------------------------------------------------
# 4.  save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path: Path) -> None:
        """save_schedule_offsets / load_schedule_offsets must be inverse ops."""
        original = {"10": 100, "22": 500, "74E": 900}
        json_file = tmp_path / "test.offsets.json"
        save_schedule_offsets(original, str(json_file))
        loaded = load_schedule_offsets(str(json_file))
        assert loaded == original

    def test_saved_json_is_sorted(self, tmp_path: Path) -> None:
        """Saved JSON must have keys in sorted order for stable diffs."""
        offsets = {"74": 900, "10": 100, "22": 500}
        json_file = tmp_path / "sorted.offsets.json"
        save_schedule_offsets(offsets, str(json_file))
        raw = json.loads(json_file.read_text())
        assert list(raw.keys()) == sorted(raw.keys())

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save_schedule_offsets must create missing parent directories."""
        deep_path = tmp_path / "a" / "b" / "c.offsets.json"
        save_schedule_offsets({"10": 42}, str(deep_path))
        assert deep_path.exists()


# ---------------------------------------------------------------------------
# 5.  build_schedule_offsets — older years produce consistent results
# ---------------------------------------------------------------------------

class TestBuildScheduleOffsetsOlderYears:
    @pytest.mark.parametrize("year", [2022, 2023, 2024])
    def test_core_schedules_present(self, year: int) -> None:
        """Core revenue and expense schedules must be present in all 2022–2024 maps."""
        p = _txt_path(year)
        _skip_if_missing(p)
        offsets = build_schedule_offsets(str(p))
        core = {"10", "12", "22", "24", "40", "42", "70", "74"}
        missing = core - offsets.keys()
        assert missing == set(), f"FIR{year} missing core schedules: {sorted(missing)}"

    def test_fir2023_has_schedule_71(self) -> None:
        """Schedule 71 (Remeasurement Gains/Losses) must be present in FIR2023."""
        p = _txt_path(2023)
        _skip_if_missing(p)
        offsets = build_schedule_offsets(str(p))
        assert "71" in offsets, "FIR2023 should contain Schedule 71"

    def test_fir2019_missing_schedules_added_later(self) -> None:
        """FIR2019 should not have Schedule 53 or 71 (added in later years)."""
        p = _txt_path(2019)
        _skip_if_missing(p)
        offsets = build_schedule_offsets(str(p))
        assert "71" not in offsets, "FIR2019 should not contain Schedule 71"
