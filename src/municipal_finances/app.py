import typer

from municipal_finances.data_cleanup import app as data_cleanup_app
from municipal_finances.data_management import app as data_management_app
from municipal_finances.db_management import app as db_management_app
from municipal_finances.resources import app as resources_app

app = typer.Typer()

app.add_typer(data_cleanup_app)
app.add_typer(data_management_app)
app.add_typer(db_management_app)
app.add_typer(resources_app)

if __name__ == "__main__":
    app()
