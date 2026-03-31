import json
import time
from datetime import datetime
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
        "2023": {  # excluded from mock saved status
            "year": 2023,
            "last_updated": datetime(2024, 11, 8).date().isoformat(),
            "date_posted": datetime(2024, 11, 8).date().isoformat(),
            "file_url": "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/fir_data_2023.zip",
        },
        "2022": {  # out of date in mock saved status
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
    mock_saved_status = {
        "2022": {  # out of date in mock saved status
            "year": 2022,
            "last_updated": datetime(2023, 1, 1).date().isoformat(),
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

    mocker.patch(
        "muni_hospital.resources.get_fir_status_table", return_value=mock_current_status
    )
    mocker.patch("muni_hospital.resources.SOURCE_DATA_PATH", tmp_path)
    with (tmp_path / "fir_status.json").open("w") as f:
        json.dump(mock_saved_status, f)

    mock_download_fir_csv = mocker.Mock()
    mocker.patch(
        "muni_hospital.resources.download_fir_csv",
        mock_download_fir_csv,
    )

    mocker.patch("muni_hospital.resources.SOURCE_DATA_PATH", tmp_path)

    get_fir_data()

    assert mock_download_fir_csv.call_count == 2

    call_list = mock_download_fir_csv.call_args_list
    years_called = [call.args[0]["year"] for call in call_list]
    assert years_called == [2023, 2022]

    with (tmp_path / "fir_status.json").open("r") as f:
        new_status = json.load(f)
    assert new_status == mock_current_status


def validate_FIRStatus(input: dict) -> bool:
    """Type checking utility function for"""
    FIRStatusValidator = TypeAdapter(FIRStatus)
    try:
        result = FIRStatusValidator.validate_python(input)
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
    breakpoint()


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

    mocker.patch("muni_hospital.resources.SOURCE_DATA_PATH", tmp_path)

    mocker.patch("muni_hospital.resources.time.sleep")

    unzipped_files = download_fir_csv(mock_status)

    for file in unzipped_files:
        assert (tmp_path / file).exists()
    assert (tmp_path / "fir_data_2023.csv").exists()
    assert (tmp_path / "fir_data_2023.zip").exists()

    time.sleep.assert_called_once_with(1)
