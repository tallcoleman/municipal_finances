import re
from pathlib import Path

import typer

app = typer.Typer()


def escape_quotes(text):
    """Changes '"' to '\"' so that mid-string quotes are properly escaped.
    Regex applied twice in case of overlap.
    """
    return re.sub(
        r'([^,\n\\])(")([^,\n])',
        r"\g<1>\"\g<3>",
        re.sub(r'([^,\n\\])(")([^,\n])', r"\g<1>\"\g<3>", text),
    )


def _fix_csv(source_file: Path, cleaned_data_path: Path) -> None:
    """Fix known CSV formatting errors for a single source file. Skips if the cleaned file already exists."""
    if not (cleaned_data_path / source_file.name).exists():
        with source_file.open("r") as f:
            og_csv_lines = f.readlines()
        fixed_csv_lines = [
            escape_quotes(
                line.replace("\\", "\\\\")
                # special cases I'm not good enough at regex to fix:
                .replace('furniture", were', 'furniture\\", were')
                .replace('Other", but', 'Other\\", but')
                .replace('Profile", in', 'Profile\\", in')
            )
            for line in og_csv_lines
        ]
        with (cleaned_data_path / source_file.name).open(
            "w", encoding="utf-8"
        ) as f:
            f.writelines(fixed_csv_lines)
        print(f"fixed {source_file.name}", end="\r", flush=True)


@app.command()
def fix_csvs(source_data_path: Path, cleaned_data_path: Path):
    """Fix known errors in the CSV files from the FIR site. This can take a while (minutes) if all the source files need to be fixed."""

    source_files = list(source_data_path.glob("*.csv"))
    cleaned_data_path.mkdir(exist_ok=True, parents=True)

    for source_file in source_files:
        _fix_csv(source_file, cleaned_data_path)
