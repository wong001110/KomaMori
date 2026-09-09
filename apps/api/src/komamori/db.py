from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _prepare_sqlite_path(database_url: str) -> None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix(prefix)).parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(settings.database_url)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
