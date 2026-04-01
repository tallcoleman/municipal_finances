from datetime import date

import pytest
from typer.testing import CliRunner

from municipal_finances.app import app

runner = CliRunner()

MOCK_STATUS = {
    "2023": {
        "year": 2023,
        "last_updated": "2024-11-08",
        "date_posted": "2024-11-08",
        "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2023.zip",
    },
    "2022": {
        "year": 2022,
        "last_updated": "2024-10-24",
        "date_posted": "2024-10-24",
        "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2022.zip",
    },
    "2021": {
        "year": 2021,
        "last_updated": "2024-10-17",
        "date_posted": "2024-10-17",
        "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2021.zip",
    },
}


def _make_session_mock(mocker, get_side_effects):
    """Build a reusable mock Session context manager with ordered session.get() return values."""
    mock_session = mocker.MagicMock()
    mock_session.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mocker.MagicMock(return_value=False)
    mock_session.get.side_effect = get_side_effects
    return mock_session


def _patch_common(mocker, mock_session):
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)
    mocker.patch(
        "municipal_finances.db_management.get_fir_status_table",
        return_value=MOCK_STATUS,
    )


def test_load_years_processes_stale_and_missing_years(mocker, tmp_path):
    """Years that are stale or absent from the DB are downloaded, cleaned, and loaded.
    Years that are already current are skipped.

    MOCK_STATUS has 2021 (current), 2022 (stale), 2023 (missing).
    Session.get calls in processing order (2021 → 2022 → 2023):
      1. 2021 skip check → current, skip
      2. 2022 skip check → stale, process
      3. 2022 upsert
      4. 2023 skip check → None, process
      5. 2023 upsert
    """
    mock_2021_current = mocker.MagicMock()
    mock_2021_current.loaded_into_db = True
    mock_2021_current.last_updated = date(2024, 10, 17)  # matches MOCK_STATUS["2021"]

    mock_2022_stale = mocker.MagicMock()
    mock_2022_stale.loaded_into_db = True
    mock_2022_stale.last_updated = date(2023, 1, 1)  # does not match

    mock_session = _make_session_mock(mocker, [
        mock_2021_current,  # 2021 skip check → current
        mock_2022_stale,    # 2022 skip check → stale
        mock_2022_stale,    # 2022 upsert
        None,               # 2023 skip check → missing
        None,               # 2023 upsert
    ])
    _patch_common(mocker, mock_session)

    mock_download = mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        side_effect=lambda entry, path: [f"fir_data_{entry['year']}.csv"],
    )
    mock_fix = mocker.patch("municipal_finances.db_management._fix_csv")
    mock_load = mocker.patch(
        "municipal_finances.db_management._load_csv_into_db", return_value=100
    )

    result = runner.invoke(app, [
        "load-years",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    assert mock_download.call_count == 2
    downloaded_years = [call.args[0]["year"] for call in mock_download.call_args_list]
    assert downloaded_years == [2022, 2023]
    assert mock_fix.call_count == 2
    assert mock_load.call_count == 2


def test_load_years_skips_all_when_all_current(mocker, tmp_path):
    """No downloads or loads when every year in the DB is already up to date."""
    def current(last_updated):
        m = mocker.MagicMock()
        m.loaded_into_db = True
        m.last_updated = last_updated
        return m

    # Session.get called once per year (skip check only, all three skipped)
    mock_session = _make_session_mock(mocker, [
        current(date(2024, 10, 17)),
        current(date(2024, 10, 24)),
        current(date(2024, 11, 8)),
    ])
    _patch_common(mocker, mock_session)
    mock_download = mocker.patch("municipal_finances.db_management.download_fir_csv")

    result = runner.invoke(app, [
        "load-years",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    mock_download.assert_not_called()


def test_load_years_single_year(mocker, tmp_path):
    """--year restricts processing to exactly the specified year."""
    # 2022 is missing; 2 Session.get calls: skip check + upsert
    mock_session = _make_session_mock(mocker, [None, None])
    _patch_common(mocker, mock_session)

    mock_download = mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.csv"],
    )
    mocker.patch("municipal_finances.db_management._fix_csv")
    mocker.patch("municipal_finances.db_management._load_csv_into_db", return_value=100)

    result = runner.invoke(app, [
        "load-years", "--year", "2022",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    assert mock_download.call_count == 1
    assert mock_download.call_args.args[0]["year"] == 2022


def test_load_years_min_max_year_range(mocker, tmp_path):
    """--min-year and --max-year together restrict processing to years within the range."""
    mock_session = _make_session_mock(mocker, [None, None])
    _patch_common(mocker, mock_session)

    mock_download = mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.csv"],
    )
    mocker.patch("municipal_finances.db_management._fix_csv")
    mocker.patch("municipal_finances.db_management._load_csv_into_db", return_value=100)

    result = runner.invoke(app, [
        "load-years", "--min-year", "2022", "--max-year", "2022",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    assert mock_download.call_count == 1
    assert mock_download.call_args.args[0]["year"] == 2022


def test_load_years_year_and_min_year_are_mutually_exclusive(mocker, tmp_path):
    """--year combined with --min-year or --max-year exits with code 1."""
    result = runner.invoke(app, [
        "load-years", "--year", "2022", "--min-year", "2021",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])
    assert result.exit_code == 1


def test_load_years_year_not_in_status_table(mocker, tmp_path):
    """--year with a year not available on the FIR site exits with code 1."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch(
        "municipal_finances.db_management.get_fir_status_table",
        return_value=MOCK_STATUS,
    )

    result = runner.invoke(app, [
        "load-years", "--year", "1990",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])
    assert result.exit_code == 1


def test_load_years_no_matching_years(mocker, tmp_path):
    """A year range that matches nothing exits cleanly with code 0."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch(
        "municipal_finances.db_management.get_fir_status_table",
        return_value=MOCK_STATUS,
    )

    result = runner.invoke(app, [
        "load-years", "--min-year", "2030",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])
    assert result.exit_code == 0


def test_load_years_skips_year_when_zip_has_no_csv(mocker, tmp_path):
    """A year whose zip contains no CSV file is skipped without loading."""
    # Only the skip-check Session.get is called; no upsert since year is skipped
    mock_session = _make_session_mock(mocker, [None])
    _patch_common(mocker, mock_session)

    mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.txt"],  # no CSV
    )
    mock_load = mocker.patch("municipal_finances.db_management._load_csv_into_db")

    result = runner.invoke(app, [
        "load-years", "--year", "2022",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    mock_load.assert_not_called()


def test_load_years_creates_firdatasource_for_new_year(mocker, tmp_path):
    """A new year (no existing DB row) gets a FIRDataSource row with full metadata."""
    mock_session = _make_session_mock(mocker, [None, None])
    _patch_common(mocker, mock_session)

    mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.csv"],
    )
    mocker.patch("municipal_finances.db_management._fix_csv")
    mocker.patch("municipal_finances.db_management._load_csv_into_db", return_value=100)

    result = runner.invoke(app, [
        "load-years", "--year", "2022",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called()

    added = mock_session.add.call_args.args[0]
    assert added.year == 2022
    assert added.last_updated == date(2024, 10, 24)
    assert added.date_posted == date(2024, 10, 24)
    assert added.file_url == MOCK_STATUS["2022"]["file_url"]
    assert added.loaded_into_db is True


def test_load_years_updates_firdatasource_for_stale_year(mocker, tmp_path):
    """A stale year's existing FIRDataSource row is updated with new metadata."""
    mock_2022_stale = mocker.MagicMock()
    mock_2022_stale.loaded_into_db = True
    mock_2022_stale.last_updated = date(2023, 1, 1)

    mock_session = _make_session_mock(mocker, [mock_2022_stale, mock_2022_stale])
    _patch_common(mocker, mock_session)

    mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.csv"],
    )
    mocker.patch("municipal_finances.db_management._fix_csv")
    mocker.patch("municipal_finances.db_management._load_csv_into_db", return_value=100)

    result = runner.invoke(app, [
        "load-years", "--year", "2022",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(tmp_path / "cleaned"),
    ])

    assert result.exit_code == 0
    assert mock_2022_stale.last_updated == date(2024, 10, 24)
    assert mock_2022_stale.loaded_into_db is True
    mock_session.add.assert_called_once_with(mock_2022_stale)


def test_load_years_fix_csv_called_with_correct_paths(mocker, tmp_path):
    """_fix_csv is called with the source CSV path and the cleaned data directory."""
    mock_session = _make_session_mock(mocker, [None, None])
    _patch_common(mocker, mock_session)

    mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.csv"],
    )
    mock_fix = mocker.patch("municipal_finances.db_management._fix_csv")
    mocker.patch("municipal_finances.db_management._load_csv_into_db", return_value=100)

    source_path = tmp_path / "source"
    cleaned_path = tmp_path / "cleaned"

    runner.invoke(app, [
        "load-years", "--year", "2022",
        "--source-data-path", str(source_path),
        "--cleaned-data-path", str(cleaned_path),
    ])

    mock_fix.assert_called_once_with(source_path / "fir_data_2022.csv", cleaned_path)


def test_load_years_load_csv_called_with_cleaned_path(mocker, tmp_path):
    """_load_csv_into_db is called with the cleaned (not source) CSV path."""
    mock_session = _make_session_mock(mocker, [None, None])
    _patch_common(mocker, mock_session)

    mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        return_value=["fir_data_2022.csv"],
    )
    mocker.patch("municipal_finances.db_management._fix_csv")
    mock_load = mocker.patch(
        "municipal_finances.db_management._load_csv_into_db", return_value=100
    )

    cleaned_path = tmp_path / "cleaned"

    runner.invoke(app, [
        "load-years", "--year", "2022",
        "--source-data-path", str(tmp_path / "source"),
        "--cleaned-data-path", str(cleaned_path),
    ])

    mock_load.assert_called_once()
    assert mock_load.call_args.args[0] == cleaned_path / "fir_data_2022.csv"
