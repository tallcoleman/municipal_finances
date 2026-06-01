import os
from typing import Generator

from dotenv import load_dotenv
from sqlmodel import Session, create_engine

load_dotenv()


def get_engine():
    database_url = os.environ["DATABASE_URL"]
    return create_engine(database_url)


def get_session() -> Generator[Session, None, None]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
