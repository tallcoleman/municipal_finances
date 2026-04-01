from typer.testing import CliRunner

from municipal_finances.app import app
from municipal_finances.data_cleanup import _fix_csv, escape_quotes

runner = CliRunner()


# --- escape_quotes ---


def test_escape_quotes_escapes_mid_string_quote():
    """A quote surrounded by non-delimiter characters is escaped."""
    assert (
        escape_quotes('value with "embedded" quote')
        == 'value with \\"embedded\\" quote'
    )


def test_escape_quotes_no_change_at_boundaries():
    """Quotes at comma or newline boundaries (CSV field delimiters) are left alone."""
    assert escape_quotes('"field1","field2"\n') == '"field1","field2"\n'


def test_escape_quotes_double_pass_handles_adjacent_quotes():
    """Adjacent mid-string quotes that require the second regex pass are both escaped."""
    # a"b"c: first pass escapes a"b → a\"b; second pass then catches b"c → b\"c
    assert escape_quotes('a"b"c') == 'a\\"b\\"c'


# --- _fix_csv ---


def test_fix_csv_writes_cleaned_file(tmp_path):
    """When no cleaned file exists, the source is read, transformed, and written."""
    source_dir = tmp_path / "source"
    cleaned_dir = tmp_path / "cleaned"
    source_dir.mkdir()
    cleaned_dir.mkdir()

    source_file = source_dir / "fir_data_2022.csv"
    source_file.write_text("normal,line\n")

    _fix_csv(source_file, cleaned_dir)

    cleaned_file = cleaned_dir / "fir_data_2022.csv"
    assert cleaned_file.exists()
    assert cleaned_file.read_text(encoding="utf-8") == "normal,line\n"


def test_fix_csv_skips_if_cleaned_file_already_exists(tmp_path):
    """When the cleaned file already exists, the source is not reprocessed."""
    source_dir = tmp_path / "source"
    cleaned_dir = tmp_path / "cleaned"
    source_dir.mkdir()
    cleaned_dir.mkdir()

    source_file = source_dir / "fir_data_2022.csv"
    source_file.write_text("updated source content\n")

    cleaned_file = cleaned_dir / "fir_data_2022.csv"
    cleaned_file.write_text("original cleaned content\n")

    _fix_csv(source_file, cleaned_dir)

    # Cleaned file must not have been overwritten
    assert cleaned_file.read_text(encoding="utf-8") == "original cleaned content\n"


def test_fix_csv_applies_special_case_replacements(tmp_path):
    """All three hardcoded string replacements are applied correctly."""
    source_dir = tmp_path / "source"
    cleaned_dir = tmp_path / "cleaned"
    source_dir.mkdir()
    cleaned_dir.mkdir()

    source_file = source_dir / "fir_data_2022.csv"
    source_file.write_text(
        'furniture", were used\nOther", but not all\nProfile", in summary\n'
    )

    _fix_csv(source_file, cleaned_dir)

    result = (cleaned_dir / "fir_data_2022.csv").read_text(encoding="utf-8")
    assert 'furniture\\", were used' in result
    assert 'Other\\", but not all' in result
    assert 'Profile\\", in summary' in result


# --- fix_csvs (CLI command) ---


def test_fix_csvs_processes_all_csvs_in_directory(tmp_path):
    """All CSV files in the source directory are cleaned and written to the cleaned directory."""
    source_dir = tmp_path / "source"
    cleaned_dir = tmp_path / "cleaned"
    source_dir.mkdir()

    (source_dir / "fir_data_2021.csv").write_text("line1\n")
    (source_dir / "fir_data_2022.csv").write_text("line2\n")

    result = runner.invoke(
        app,
        [
            "fix-csvs",
            str(source_dir),
            str(cleaned_dir),
        ],
    )

    assert result.exit_code == 0
    assert (cleaned_dir / "fir_data_2021.csv").exists()
    assert (cleaned_dir / "fir_data_2022.csv").exists()


def test_fix_csvs_no_csvs_in_directory(tmp_path):
    """An empty source directory completes without error and creates the cleaned directory."""
    source_dir = tmp_path / "source"
    cleaned_dir = tmp_path / "cleaned"
    source_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "fix-csvs",
            str(source_dir),
            str(cleaned_dir),
        ],
    )

    assert result.exit_code == 0
    assert cleaned_dir.exists()
