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


def _columns(connection: Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def _add_column(connection: Connection, table: str, name: str, ddl: str) -> None:
    if name not in _columns(connection, table):
        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _chapter_identity_and_provenance(connection: Connection) -> None:
    """Add v2 chapter identity and machine-output provenance without rebuilding tables."""
    _add_column(connection, "chapters", "display_number", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "chapters", "sort_order", "FLOAT NOT NULL DEFAULT 0")
    _add_column(connection, "text_regions", "ocr_provenance", "JSON NOT NULL DEFAULT '{}'")
    _add_column(connection, "localizations", "provenance", "JSON NOT NULL DEFAULT '{}'")

    connection.exec_driver_sql(
        """
        UPDATE chapters
        SET display_number = CASE
          WHEN number = CAST(number AS INTEGER) THEN CAST(CAST(number AS INTEGER) AS TEXT)
          ELSE CAST(number AS TEXT)
        END
        WHERE display_number IS NULL OR TRIM(display_number) = ''
        """
    )
    connection.exec_driver_sql(
        "UPDATE chapters SET sort_order = number WHERE sort_order IS NULL OR sort_order = 0"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_chapters_sort_order ON chapters(sort_order)"
    )


MIGRATIONS = (
    Migration(1, "structured-mvp-baseline", _baseline),
    Migration(2, "chapter-identity-and-provenance", _chapter_identity_and_provenance),
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
