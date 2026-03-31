import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, TypedDict
from zipfile import ZipFile

import requests
from bs4 import BeautifulSoup

import typer

app = typer.Typer()

FIR_DATA_URL = "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/MYCIndex.html"
FIR_DOWNLOAD_URL_PREFIX = "https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/"
FIR_EXPECTED_TABLE_HEADERS = [
    "FIR Year / RIF année",
    "Last Updated / Dernière mise à jour (YYYYMMDD)",
    "Date Posted / Date de Publication (YYYYMMDD)",
    "File / Fichier",
]
FIR_TABLE_DATE_FORMAT = "%Y%m%d"


class FIRStatus(TypedDict):
    year: int
    last_updated: str
    date_posted: str
    file_url: str


def get_fir_status_table() -> Dict[str, FIRStatus]:
    """gets data status and download urls from https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/MYCIndex.html"""

    # get data table from FIR open data page
    r = requests.get(FIR_DATA_URL)
    if r.status_code != 200:  # pragma: no cover
        raise Exception(
            f"Could not get page content from FIR url. Page returned status {r.status_code}"
        )
    fir_page = r.text

    # extract data table
    soup = BeautifulSoup(fir_page, "html.parser")
    data_table = soup.css.select(".file-filter-section")[0].find("table")

    # check table headers
    table_headers = [h.get_text() for h in data_table.find("thead").find_all("th")]
    if table_headers != FIR_EXPECTED_TABLE_HEADERS:  # pragma: no cover
        raise Exception("FIR open data table column headings different than expected")

    # extract and convert rows
    fir_entries: Dict[str, FIRStatus] = {}
    for row in data_table.find("tbody").find_all("tr"):
        values = row.find_all("td")
        year = values[0].get_text()
        last_updated = (
            datetime.strptime(values[1].get_text(), FIR_TABLE_DATE_FORMAT)
            .date()
            .isoformat()
        )
        date_posted = (
            datetime.strptime(values[2].get_text(), FIR_TABLE_DATE_FORMAT)
            .date()
            .isoformat()
        )
        file_url = FIR_DOWNLOAD_URL_PREFIX + values[3].find("a").get("href")
        fir_entries[year] = {
            "year": int(year),
            "last_updated": last_updated,
            "date_posted": date_posted,
            "file_url": file_url,
        }

    return fir_entries


def download_fir_csv(entry: FIRStatus, source_data_path: Path, delay=1):
    """Download zip from FIR open data page and extract csv"""
    time.sleep(delay)

    r = requests.get(entry["file_url"])
    if r.status_code != 200:  # pragma: no cover
        raise Exception(
            f"Could not get file content from {entry['file_url']}. URL returned status {r.status_code}"
        )

    zip_path = source_data_path / f"fir_data_{entry['year']}.zip"
    source_data_path.mkdir(exist_ok=True)
    with zip_path.open("wb") as f:
        f.write(r.content)
    unzipped_files = None
    with ZipFile(zip_path, "r") as z:
        unzipped_files = z.namelist()
        z.extractall(source_data_path)
    return unzipped_files


@app.command()
def get_fir_data(source_data_path: Path):
    """Downloads and updates CSV files from https://efis.fma.csc.gov.on.ca/fir/MultiYearReport/MYCIndex.html"""

    # load saved metadata
    saved_status: Dict[str, FIRStatus] = {}
    status_path = source_data_path / "fir_status.json"
    if status_path.exists():
        with status_path.open("r") as f:
            saved_status = json.load(f)

    # get current metatadata
    current_status = get_fir_status_table()
    to_update: list[FIRStatus] = []

    # get datasets that need to be updated
    for year, entry in current_status.items():
        saved = saved_status.get(year, None)
        if saved is None:
            to_update.append(entry)
            continue
        saved_last_updated = datetime.fromisoformat(saved["last_updated"]).date()
        current_last_updated = datetime.fromisoformat(entry["last_updated"]).date()
        if saved_last_updated < current_last_updated:
            to_update.append(entry)

    # download datasets that need to be updated
    for entry in to_update:
        download_fir_csv(entry)

    # save metadata
    source_data_path.mkdir(exist_ok=True)
    with status_path.open("w") as f:
        json.dump(current_status, f, indent=2)

    return current_status
