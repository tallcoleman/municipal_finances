from datetime import date

import pandas as pd
from sqlmodel import SQLModel
from typer.testing import CliRunner

from municipal_finances.app import app
from municipal_finances.db_management import _load_csv_into_db

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

    mock_session = _make_session_mock(
        mocker,
        [
            mock_2021_current,  # 2021 skip check → current
            mock_2022_stale,  # 2022 skip check → stale
            mock_2022_stale,  # 2022 upsert
            None,  # 2023 skip check → missing
            None,  # 2023 upsert
        ],
    )
    _patch_common(mocker, mock_session)

    mock_download = mocker.patch(
        "municipal_finances.db_management.download_fir_csv",
        side_effect=lambda entry, path: [f"fir_data_{entry['year']}.csv"],
    )
    mock_fix = mocker.patch("municipal_finances.db_management._fix_csv")
    mock_load = mocker.patch(
        "municipal_finances.db_management._load_csv_into_db", return_value=100
    )

    result = runner.invoke(
        app,
        [
            "load-years",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

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
    mock_session = _make_session_mock(
        mocker,
        [
            current(date(2024, 10, 17)),
            current(date(2024, 10, 24)),
            current(date(2024, 11, 8)),
        ],
    )
    _patch_common(mocker, mock_session)
    mock_download = mocker.patch("municipal_finances.db_management.download_fir_csv")

    result = runner.invoke(
        app,
        [
            "load-years",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

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

    result = runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

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

    result = runner.invoke(
        app,
        [
            "load-years",
            "--min-year",
            "2022",
            "--max-year",
            "2022",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

    assert result.exit_code == 0
    assert mock_download.call_count == 1
    assert mock_download.call_args.args[0]["year"] == 2022


def test_load_years_year_and_min_year_are_mutually_exclusive(tmp_path):
    """--year combined with --min-year or --max-year exits with code 1."""
    result = runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--min-year",
            "2021",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )
    assert result.exit_code == 1


def test_load_years_year_not_in_status_table(mocker, tmp_path):
    """--year with a year not available on the FIR site exits with code 1."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch(
        "municipal_finances.db_management.get_fir_status_table",
        return_value=MOCK_STATUS,
    )

    result = runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "1990",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )
    assert result.exit_code == 1


def test_load_years_no_matching_years(mocker, tmp_path):
    """A year range that matches nothing exits cleanly with code 0."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch(
        "municipal_finances.db_management.get_fir_status_table",
        return_value=MOCK_STATUS,
    )

    result = runner.invoke(
        app,
        [
            "load-years",
            "--min-year",
            "2030",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )
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

    result = runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

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

    result = runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

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

    result = runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(tmp_path / "cleaned"),
        ],
    )

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

    runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--source-data-path",
            str(source_path),
            "--cleaned-data-path",
            str(cleaned_path),
        ],
    )

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

    runner.invoke(
        app,
        [
            "load-years",
            "--year",
            "2022",
            "--source-data-path",
            str(tmp_path / "source"),
            "--cleaned-data-path",
            str(cleaned_path),
        ],
    )

    mock_load.assert_called_once()
    assert mock_load.call_args.args[0] == cleaned_path / "fir_data_2022.csv"


# ---------------------------------------------------------------------------
# Shared fixtures for _load_csv_into_db and load_data tests
# ---------------------------------------------------------------------------

ALL_COLUMNS = [
    "MUNID",
    "ASSESSMENT_CODE",
    "MUNICIPALITY_DESC",
    "MSO_NUMBER",
    "SGC_CODE",
    "UT_NUMBER",
    "MTYPE_CODE",
    "TIER_CODE",
    "MARSYEAR",
    "SCHEDULE_DESC",
    "SUB_SCHEDULE_DESC",
    "SCHEDULE_LINE_DESC",
    "SCHEDULE_COLUMN_DESC",
    "SLC",
    "DATATYPE_DESC",
    "AMOUNT",
    "VALUE_TEXT",
    "LAST_UPDATE_DATE",
]

SAMPLE_ROW = {
    "MUNID": "MUN001",
    "ASSESSMENT_CODE": "AC1",
    "MUNICIPALITY_DESC": "Test City",
    "MSO_NUMBER": "001",
    "SGC_CODE": "123",
    "UT_NUMBER": "UT1",
    "MTYPE_CODE": 1,
    "TIER_CODE": "LT",
    "MARSYEAR": 2022,
    "SCHEDULE_DESC": "Schedule A",
    "SUB_SCHEDULE_DESC": "Sub A",
    "SCHEDULE_LINE_DESC": "Line 1",
    "SCHEDULE_COLUMN_DESC": "Col 1",
    "SLC": "SLC001",
    "DATATYPE_DESC": "Amount",
    "AMOUNT": 1000.0,
    "VALUE_TEXT": None,
    "LAST_UPDATE_DATE": "2024-01-01",
}


def _make_fir_df(rows):
    return pd.DataFrame(rows, columns=ALL_COLUMNS)


def _make_simple_session(mocker):
    mock_session = mocker.MagicMock()
    mock_session.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mocker.MagicMock(return_value=False)
    return mock_session


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


def test_init_db_calls_create_db_and_tables(mocker):
    mock_create = mocker.patch("municipal_finances.db_management.create_db_and_tables")
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0
    mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# clear_db
# ---------------------------------------------------------------------------


def test_clear_db_with_yes_flag_deletes_all_tables(mocker):
    """--yes skips the confirmation prompt and deletes all registered tables."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = runner.invoke(app, ["clear-db", "--yes"])

    assert result.exit_code == 0
    assert mock_session.execute.call_count == len(list(SQLModel.metadata.sorted_tables))
    mock_session.commit.assert_called_once()


def test_clear_db_prompts_and_proceeds_on_confirmation(mocker):
    """Without --yes the user is prompted; confirming with 'y' proceeds with deletion."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = runner.invoke(app, ["clear-db"], input="y\n")

    assert result.exit_code == 0
    assert mock_session.execute.call_count == len(list(SQLModel.metadata.sorted_tables))


def test_clear_db_aborts_on_decline(mocker):
    """Declining the confirmation prompt aborts without deleting anything."""
    mocker.patch("municipal_finances.db_management.get_engine")
    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = runner.invoke(app, ["clear-db"], input="n\n")

    assert result.exit_code != 0
    mock_session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _load_csv_into_db
# ---------------------------------------------------------------------------


def test_load_csv_into_db_returns_row_count_and_executes_inserts(mocker, tmp_path):
    """1-row CSV: muni upsert + 1 record chunk; returns 1."""
    csv_path = tmp_path / "fir_data_2022.csv"
    _make_fir_df([SAMPLE_ROW]).to_csv(csv_path, index=False)

    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = _load_csv_into_db(csv_path, mocker.MagicMock(), chunk_size=5_000)

    assert result == 1
    assert mock_session.execute.call_count == 2  # 1 muni upsert + 1 record chunk
    assert mock_session.commit.call_count == 2


def test_load_csv_into_db_processes_multiple_chunks(mocker, tmp_path):
    """2-row CSV with chunk_size=1: 1 muni execute + 2 record executes."""
    row2 = {**SAMPLE_ROW, "MUNID": "MUN002", "MARSYEAR": 2023}
    csv_path = tmp_path / "fir_data.csv"
    _make_fir_df([SAMPLE_ROW, row2]).to_csv(csv_path, index=False)

    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = _load_csv_into_db(csv_path, mocker.MagicMock(), chunk_size=1)

    assert result == 2
    assert mock_session.execute.call_count == 3  # 1 muni + 2 record chunks
    assert mock_session.commit.call_count == 3


def test_load_csv_into_db_empty_csv_skips_record_insert(mocker, tmp_path):
    """0-row CSV: record loop not entered; returns 0."""
    csv_path = tmp_path / "fir_data_empty.csv"
    _make_fir_df([]).to_csv(csv_path, index=False)

    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)
    # pg_insert(Municipality).values([]) may raise on an empty list; mock to be safe
    mocker.patch(
        "municipal_finances.db_management.pg_insert", return_value=mocker.MagicMock()
    )

    result = _load_csv_into_db(csv_path, mocker.MagicMock(), chunk_size=5_000)

    assert result == 0
    assert mock_session.execute.call_count == 1  # muni upsert only; no record chunks


# ---------------------------------------------------------------------------
# load_data
# ---------------------------------------------------------------------------


def test_load_data_loads_parquet_and_updates_existing_firdatasource(mocker, tmp_path):
    """1-row parquet: municipalities upserted, record inserted, existing FIRDataSource updated."""
    parquet_path = tmp_path / "fir_data.parquet"
    _make_fir_df([SAMPLE_ROW]).to_parquet(parquet_path)

    existing_source = mocker.MagicMock()
    mock_session = _make_simple_session(mocker)
    mock_session.get.return_value = existing_source
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = runner.invoke(app, ["load-data", str(parquet_path)])

    assert result.exit_code == 0
    assert existing_source.loaded_into_db is True
    mock_session.add.assert_called_with(existing_source)


def test_load_data_creates_firdatasource_when_missing(mocker, tmp_path):
    """When no FIRDataSource row exists for a year, a skeleton row is created."""
    parquet_path = tmp_path / "fir_data.parquet"
    _make_fir_df([SAMPLE_ROW]).to_parquet(parquet_path)

    mock_session = _make_simple_session(mocker)
    mock_session.get.return_value = None
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = runner.invoke(app, ["load-data", str(parquet_path)])

    assert result.exit_code == 0
    mock_session.add.assert_called()
    added = mock_session.add.call_args.args[0]
    assert added.year == 2022
    assert added.loaded_into_db is True


def test_load_data_processes_multiple_chunks(mocker, tmp_path):
    """With --chunk-size 1 and 2 rows, records are inserted in 2 separate chunks."""
    row2 = {**SAMPLE_ROW, "MUNID": "MUN002", "MARSYEAR": 2023}
    parquet_path = tmp_path / "fir_data.parquet"
    _make_fir_df([SAMPLE_ROW, row2]).to_parquet(parquet_path)

    mock_session = _make_simple_session(mocker)
    mock_session.get.return_value = mocker.MagicMock()
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)

    result = runner.invoke(app, ["load-data", str(parquet_path), "--chunk-size", "1"])

    assert result.exit_code == 0
    assert mock_session.execute.call_count == 3  # 1 muni upsert + 2 record chunks


def test_load_data_empty_parquet_skips_record_and_firdatasource_inserts(
    mocker, tmp_path
):
    """0-row parquet: record loop and FIRDataSource loop not entered."""
    parquet_path = tmp_path / "fir_data.parquet"
    _make_fir_df([]).to_parquet(parquet_path)

    mock_session = _make_simple_session(mocker)
    mocker.patch("municipal_finances.db_management.get_engine")
    mocker.patch("municipal_finances.db_management.Session", return_value=mock_session)
    mocker.patch(
        "municipal_finances.db_management.pg_insert", return_value=mocker.MagicMock()
    )

    result = runner.invoke(app, ["load-data", str(parquet_path)])

    assert result.exit_code == 0
    assert mock_session.execute.call_count == 1  # muni upsert only
    mock_session.get.assert_not_called()  # no years → FIRDataSource loop skipped
