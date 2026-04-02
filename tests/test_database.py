from municipal_finances.database import create_db_and_tables, get_engine, get_session


def test_get_engine_uses_database_url(mocker, monkeypatch):
    """get_engine passes DATABASE_URL from the environment to create_engine."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    mock_create_engine = mocker.patch("municipal_finances.database.create_engine")

    get_engine()

    mock_create_engine.assert_called_once_with("postgresql://user:pass@localhost/testdb")


def test_create_db_and_tables_calls_create_all(mocker):
    """create_db_and_tables calls SQLModel.metadata.create_all with the engine."""
    mock_engine = mocker.MagicMock()
    mocker.patch("municipal_finances.database.get_engine", return_value=mock_engine)
    mock_create_all = mocker.patch("municipal_finances.database.SQLModel.metadata.create_all")

    create_db_and_tables()

    mock_create_all.assert_called_once_with(mock_engine)


def test_get_session_yields_session(mocker, monkeypatch):
    """get_session yields the session from the Session context manager."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    mocker.patch("municipal_finances.database.create_engine")

    mock_session = mocker.MagicMock()
    mock_session.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_session.__exit__ = mocker.MagicMock(return_value=False)
    mocker.patch("municipal_finances.database.Session", return_value=mock_session)

    gen = get_session()
    session = next(gen)
    assert session is mock_session
    gen.close()
