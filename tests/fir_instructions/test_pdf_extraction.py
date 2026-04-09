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


# ---------------------------------------------------------------------------
# 6.  build_schedule_offsets — synthetic file tests (no real PDFs required)
# ---------------------------------------------------------------------------

class TestBuildScheduleOffsetsSynthetic:
    """Unit tests for build_schedule_offsets using synthetic .txt content.

    These tests exercise the parsing logic without requiring pdftotext output.
    They create minimal temp files named to trigger the correct year-dispatch path.
    """

    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    # -- FIR2025 header format ------------------------------------------------

    def test_fir2025_detects_page1_header(self, tmp_path: Path) -> None:
        """FIR2025 Page |1 headers are detected and mapped to the correct line."""
        content = (
            "preamble line\n"
            "another line\n"
            "FIR2025   Page |1   Schedule 10\n"
            "schedule content\n"
            "FIR2025   Page |1   Schedule 22\n"
        )
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 2
        assert offsets["22"] == 4

    def test_fir2025_ignores_page2_headers(self, tmp_path: Path) -> None:
        """FIR2025: only Page |1 lines are recorded; later pages are ignored."""
        content = (
            "FIR2025   Page |1   Schedule 10\n"
            "FIR2025   Page |2   Schedule 10\n"
            "FIR2025   Page |3   Schedule 10\n"
        )
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 0  # Only the first line recorded

    def test_fir2025_alphanumeric_code(self, tmp_path: Path) -> None:
        """FIR2025: alphanumeric schedule codes (e.g. 74E, 80D) are captured."""
        content = "FIR2025   Page |1   Schedule 74E\n"
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert "74E" in offsets

    # -- Old-year footer format -----------------------------------------------

    def test_old_year_detects_page1_footer(self, tmp_path: Path) -> None:
        """FIR2022 footer pattern is detected and mapped to the correct line."""
        content = (
            "intro\n"
            "FIR2022   Schedule 10   Statement of Operations: Revenue   10 - 1\n"
            "FIR2022   Schedule 22   Taxation   22 - 1\n"
        )
        p = self._write(tmp_path, "FIR2022 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 1
        assert offsets["22"] == 2

    def test_old_year_requires_matching_groups(self, tmp_path: Path) -> None:
        """Footer where schedule code and trailing code differ is not recorded."""
        # "10 - 1" at the end but the schedule header says "22" — groups mismatch
        content = "FIR2022   Schedule 22   Some Title   10 - 1\n"
        p = self._write(tmp_path, "FIR2022 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert "22" not in offsets
        assert "10" not in offsets

    def test_old_year_ignores_later_pages(self, tmp_path: Path) -> None:
        """Old-year: only '- 1' footers are recorded; '- 2', '- 3' etc. are ignored."""
        content = (
            "FIR2022   Schedule 10   Title   10 - 1\n"
            "FIR2022   Schedule 10   Title   10 - 2\n"
        )
        p = self._write(tmp_path, "FIR2022 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 0

    # -- Form-feed detection --------------------------------------------------

    def test_formfeed_adds_missing_code(self, tmp_path: Path) -> None:
        """A form-feed line adds an offset for codes not yet seen via header/footer."""
        content = (
            "FIR2025   Page |1   Schedule 10\n"
            "\x0cSchedule 74E\n"
        )
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert "10" in offsets
        assert offsets["74E"] == 1

    def test_formfeed_does_not_override_existing_offset(self, tmp_path: Path) -> None:
        """A form-feed line is ignored when a header already recorded that code."""
        content = (
            "FIR2025   Page |1   Schedule 10\n"
            "\x0cSchedule 10\n"           # should NOT override line 0
        )
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 0

    def test_formfeed_only_file(self, tmp_path: Path) -> None:
        """A file with only form-feed markers builds a valid offset map."""
        content = "\x0cSchedule 74E\n\x0cSchedule 80D\n"
        # Use a filename with no recognisable year so neither header nor footer
        # path fires, and form-feeds are the only source.
        p = self._write(tmp_path, "mystery.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["74E"] == 0
        assert offsets["80D"] == 1

    # -- Edge cases -----------------------------------------------------------

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """An empty text file produces an empty offset map."""
        p = self._write(tmp_path, "FIR2025 Instructions.txt", "")
        assert build_schedule_offsets(str(p)) == {}

    def test_no_schedule_markers_returns_empty_dict(self, tmp_path: Path) -> None:
        """A file with no schedule markers produces an empty offset map."""
        content = "just some text\nno schedules here\n"
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        assert build_schedule_offsets(str(p)) == {}

    def test_first_occurrence_wins_for_duplicates(self, tmp_path: Path) -> None:
        """When a code appears twice via FIR2025 headers, the first line wins."""
        content = (
            "FIR2025   Page |1   Schedule 10\n"
            "some content\n"
            "FIR2025   Page |1   Schedule 10\n"  # duplicate — should be ignored
        )
        p = self._write(tmp_path, "FIR2025 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 0

    def test_old_year_first_occurrence_wins(self, tmp_path: Path) -> None:
        """When a code appears twice via old-year footers, the first line wins."""
        content = (
            "FIR2022   Schedule 10   Revenue   10 - 1\n"
            "content line\n"
            "FIR2022   Schedule 10   Revenue   10 - 1\n"  # duplicate — should be ignored
        )
        p = self._write(tmp_path, "FIR2022 Instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert offsets["10"] == 0

    def test_unknown_year_filename_uses_old_format(self, tmp_path: Path) -> None:
        """A filename with no FIR-year pattern falls back to the old footer path."""
        content = "FIR2022   Schedule 10   Revenue   10 - 1\n"
        p = self._write(tmp_path, "instructions.txt", content)
        offsets = build_schedule_offsets(str(p))
        assert "10" in offsets


# ---------------------------------------------------------------------------
# 7.  load_schedule_offsets — JSON value casting
# ---------------------------------------------------------------------------

class TestLoadScheduleOffsetsCasting:
    def test_string_values_in_json_are_cast_to_int(self, tmp_path: Path) -> None:
        """load_schedule_offsets casts all JSON values to int even if stored as strings."""
        json_file = tmp_path / "test.offsets.json"
        # Write JSON with string values (as if produced by a non-Python tool)
        json_file.write_text('{"10": "42", "22": "100"}', encoding="utf-8")
        loaded = load_schedule_offsets(str(json_file))
        assert loaded == {"10": 42, "22": 100}
        assert all(isinstance(v, int) for v in loaded.values())

    def test_large_offset_values_round_trip(self, tmp_path: Path) -> None:
        """Offset values beyond 16-bit range survive the save/load round-trip."""
        offsets = {"10": 100_000, "83": 999_999}
        json_file = tmp_path / "large.offsets.json"
        save_schedule_offsets(offsets, str(json_file))
        loaded = load_schedule_offsets(str(json_file))
        assert loaded == offsets
