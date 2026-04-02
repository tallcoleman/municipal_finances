import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine
from starlette.testclient import TestClient

from municipal_finances.api.main import app
from municipal_finances.database import get_session
from municipal_finances.models import FIRDataSource, FIRRecord, Municipality  # noqa: F401

TEST_DATABASE_URL = (
    "postgresql+psycopg://muni:muni@localhost:5433/municipal_finances_test"
)


@pytest.fixture(scope="session")
def engine():
    """Create the test database engine and schema once for the entire test session.

    Connects to the local db-test Docker container, creates all SQLModel tables,
    and drops them on teardown. Session-scoped so the schema is only built once.
    """
    engine = create_engine(TEST_DATABASE_URL)
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session(engine):
    """Provide an isolated database session for a single test.

    Rolls back any uncommitted work and truncates all tables after each test
    so that every test starts with a clean database state.
    """
    with Session(engine) as s:
        yield s
        s.rollback()
        # Truncate all tables to isolate tests
        for table in reversed(SQLModel.metadata.sorted_tables):
            s.exec(text(f"TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE"))  # type: ignore[call-overload]
        s.commit()


@pytest.fixture()
def client(session):
    """Provide a FastAPI TestClient wired to the test database session.

    Overrides the app's get_session dependency to inject the test session,
    ensuring API requests hit the same isolated database as the test's seed data.
    Redirects are not followed so redirect responses can be asserted directly.
    """

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
