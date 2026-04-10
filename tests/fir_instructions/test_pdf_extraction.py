"""Tests for fir_instructions/pdf_extraction.py.

These tests cover the schedule offset map building logic and the save/load
round-trip.  They use synthetic in-memory files so no pre-converted ``.txt``
files are required.
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
# 1.  save / load round-trip
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
# 2.  build_schedule_offsets — synthetic file tests (no real PDFs required)
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
# 3.  load_schedule_offsets — JSON value casting
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
