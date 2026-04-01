from datetime import date, datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from municipal_finances.resources import (
    FIRStatus,
    download_fir_csv,
    get_fir_data,
    get_fir_status_table,
)


def test_get_fir_data(mocker, tmp_path):
    mock_current_status = {
        "2023": {  # new — not in saved status
            "year": 2023,
            "last_updated": datetime(2024, 11, 8).date().isoformat(),
            "date_posted": datetime(2024, 11, 8).date().isoformat(),
            "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2023.zip",
        },
        "2022": {  # out of date in saved status
            "year": 2022,
            "last_updated": datetime(2024, 10, 24).date().isoformat(),
            "date_posted": datetime(2024, 10, 24).date().isoformat(),
            "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2022.zip",
        },
        "2021": {  # no change
            "year": 2021,
            "last_updated": datetime(2024, 10, 17).date().isoformat(),
            "date_posted": datetime(2024, 10, 17).date().isoformat(),
            "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2021.zip",
        },
    }

    # Mock saved DB records — 2022 is out of date, 2021 is current, 2023 is missing
    mock_2022 = mocker.MagicMock()
    mock_2022.year = 2022
    mock_2022.last_updated = date(2023, 1, 1)

    mock_2021 = mocker.MagicMock()
    mock_2021.year = 2021
    mock_2021.last_updated = date(2024, 10, 17)

    mock_session = mocker.MagicMock()
    mock_session.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mocker.MagicMock(return_value=False)
    mock_session.exec.return_value.all.return_value = [mock_2022, mock_2021]
    # Upsert loop iterates mock_current_status in insertion order: 2023, 2022, 2021.
    # 2023 has no existing DB row (None), exercising the FIRDataSource create branch.
    mock_session.get.side_effect = [None, mocker.MagicMock(), mocker.MagicMock()]

    mocker.patch("municipal_finances.resources.get_engine")
    mocker.patch("municipal_finances.resources.Session", return_value=mock_session)
    mocker.patch(
        "municipal_finances.resources.get_fir_status_table",
        return_value=mock_current_status,
    )

    mock_download_fir_csv = mocker.Mock()
    mocker.patch("municipal_finances.resources.download_fir_csv", mock_download_fir_csv)

    get_fir_data(tmp_path)

    assert mock_download_fir_csv.call_count == 2
    call_list = mock_download_fir_csv.call_args_list
    years_called = [call.args[0]["year"] for call in call_list]
    assert years_called == [2023, 2022]


def validate_FIRStatus(input: dict) -> bool:
    """Type checking utility function for FIRStatus"""
    FIRStatusValidator = TypeAdapter(FIRStatus)
    try:
        FIRStatusValidator.validate_python(input)
    except ValidationError:
        return False
    return True


def test_get_fir_status_table(mocker):
    mock_page = Path("tests/mocks/mock_fir_data_by_year.html").read_text("utf-8")
    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.text = mock_page
    mocker.patch("requests.get", return_value=mock_response)

    output = get_fir_status_table()
    assert all([type(k) is str for k in output.keys()])
    assert all(validate_FIRStatus(v) for v in output.values())


def test_download_fir_csv(mocker, tmp_path):
    mock_status: FIRStatus = {
        "year": 2023,
        "last_updated": datetime(2024, 11, 8).date().isoformat(),
        "date_posted": datetime(2024, 11, 8).date().isoformat(),
        "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2023.zip",
    }

    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.content = Path("tests/mocks/fir_data_2023.zip").read_bytes()
    mocker.patch("requests.get", return_value=mock_response)

    mock_sleep = mocker.patch("municipal_finances.resources.time.sleep")

    unzipped_files = download_fir_csv(mock_status, tmp_path)

    for file in unzipped_files:
        assert (tmp_path / file).exists()
    assert (tmp_path / "fir_data_2023.csv").exists()
    assert (tmp_path / "fir_data_2023.zip").exists()

    mock_sleep.assert_called_once_with(1)
