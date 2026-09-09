from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _prepare_sqlite_path(database_url: str) -> None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix(prefix)).parent.mkdir(parents=True, exist_ok=True)


def configure_sqlite_connection(dbapi_connection, *, enable_wal: bool = True) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        if enable_wal:
            cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


_prepare_sqlite_path(settings.database_url)

_is_sqlite = settings.database_url.startswith("sqlite")
_is_memory_sqlite = settings.database_url in {"sqlite://", "sqlite:///:memory:"}
connect_args = {"check_same_thread": False, "timeout": 5} if _is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        configure_sqlite_connection(dbapi_connection, enable_wal=not _is_memory_sqlite)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
