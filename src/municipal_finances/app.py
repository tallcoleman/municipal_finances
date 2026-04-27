import typer

from municipal_finances.data_cleanup import app as data_cleanup_app
from municipal_finances.data_management import app as data_management_app
from municipal_finances.db_management import app as db_management_app
from municipal_finances.fir_instructions.extract_changelog import (
    app as fir_instructions_app,
)
from municipal_finances.fir_instructions.extract_schedule_meta import (
    app as extract_schedule_meta_app,
)
from municipal_finances.fir_instructions.convert_pdf_to_md import (
    app as pdf_conversion_app,
)
from municipal_finances.fir_instructions.extract_line_meta import (
    app as extract_line_meta_app,
)
from municipal_finances.fir_instructions.extract_column_meta import (
    app as extract_column_meta_app,
)
from municipal_finances.resources import app as resources_app

app = typer.Typer()

app.add_typer(data_cleanup_app)
app.add_typer(data_management_app)
app.add_typer(db_management_app)
app.add_typer(fir_instructions_app)
app.add_typer(extract_schedule_meta_app)
app.add_typer(pdf_conversion_app)
app.add_typer(extract_line_meta_app)
app.add_typer(extract_column_meta_app)
app.add_typer(resources_app)

if __name__ == "__main__":  # pragma: no cover
    app()
