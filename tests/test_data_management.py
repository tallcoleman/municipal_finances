import pandas as pd
from typer.testing import CliRunner

from municipal_finances.app import app

runner = CliRunner()


def test_combine_data_concatenates_csvs_and_writes_parquet(tmp_path):
    """CSV files in the source directory are combined into a single parquet file."""
    cleaned_dir = tmp_path / "cleaned"
    output_dir = tmp_path / "output"
    cleaned_dir.mkdir()

    (cleaned_dir / "fir_data_2021.csv").write_text("col1,col2\na,1\n")
    (cleaned_dir / "fir_data_2022.csv").write_text("col1,col2\nb,2\n")

    result = runner.invoke(app, [
        "combine-data",
        str(cleaned_dir),
        str(output_dir),
    ])

    assert result.exit_code == 0
    parquet_path = output_dir / "fir_data_all_years.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 2
    assert set(df["col1"]) == {"a", "b"}


def test_combine_data_no_csvs_raises(tmp_path):
    """With no CSVs in the source directory, pd.concat raises — covering the loop-not-entered branch."""
    cleaned_dir = tmp_path / "cleaned"
    output_dir = tmp_path / "output"
    cleaned_dir.mkdir()

    result = runner.invoke(app, [
        "combine-data",
        str(cleaned_dir),
        str(output_dir),
    ])

    assert result.exit_code != 0
