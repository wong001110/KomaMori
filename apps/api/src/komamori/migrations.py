from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import Connection, Engine

from .db import Base


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _baseline(connection: Connection) -> None:
    """Adopt/create the current ORM schema without destroying existing rows."""
    Base.metadata.create_all(bind=connection)


MIGRATIONS = (
    Migration(1, "structured-mvp-baseline", _baseline),
)


def run_migrations(engine: Engine) -> list[int]:
    """Apply unapplied migrations in order and return versions applied this run."""
    applied_now: list[int] = []
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row[0])
            for row in connection.exec_driver_sql("SELECT version FROM schema_migrations ORDER BY version")
        }
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            migration.apply(connection)
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, _utcnow()),
            )
            applied_now.append(migration.version)
    return applied_now
