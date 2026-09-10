from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from komamori import models  # noqa: F401
from komamori.db import Base
from komamori.migrations import run_migrations
from komamori.models import Series


def test_fresh_database_is_initialized_and_versioned(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert run_migrations(engine) == [1, 2]
    tables = set(inspect(engine).get_table_names())
    assert {"series", "chapters", "pages", "text_regions", "localizations", "schema_migrations"} <= tables
    with engine.connect() as connection:
        rows = [tuple(row) for row in connection.exec_driver_sql("SELECT version, name FROM schema_migrations ORDER BY version")]
        assert rows == [
            (1, "structured-mvp-baseline"),
            (2, "chapter-identity-and-provenance"),
        ]
    assert run_migrations(engine) == []


def test_existing_database_is_adopted_without_losing_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        session.add(Series(title="Existing series", source_language="ja"))
        session.commit()

    assert run_migrations(engine) == [1, 2]
    with Session(engine) as session:
        assert session.scalar(select(Series.title)) == "Existing series"
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM schema_migrations").scalar_one() == 2
