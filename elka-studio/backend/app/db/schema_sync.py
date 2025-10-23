"""Lightweight helpers to keep the SQLite schema aligned with the ORM models."""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import CreateColumn


LOGGER = logging.getLogger(__name__)


def _iter_tables(metadata: MetaData) -> Iterable:
    """Return an iterator over tables sorted to honour foreign-key dependencies."""

    # ``sorted_tables`` ensures parent tables are processed before their children.
    yield from metadata.sorted_tables


def synchronize_sqlite_schema(engine: Engine, metadata: MetaData) -> None:
    """Add missing columns to existing SQLite tables based on SQLAlchemy models.

    The project historically relied on ``Base.metadata.create_all`` without a
    migration framework. When a new column is introduced, existing SQLite
    databases therefore miss it, leading to ``OperationalError`` exceptions at
    runtime. This helper inspects each table defined in the metadata, compares it
    with the physical schema, and issues ``ALTER TABLE .. ADD COLUMN`` statements
    for any missing nullable column (or columns with a server default).

    Parameters
    ----------
    engine:
        SQLAlchemy engine bound to the SQLite database.
    metadata:
        Declarative metadata containing the application models.
    """

    if engine.dialect.name != "sqlite":  # pragma: no cover - currently SQLite only
        return

    preparer = engine.dialect.identifier_preparer

    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())

        for table in _iter_tables(metadata):
            if table.name not in existing_tables:
                continue

            existing_columns = {
                column_info["name"] for column_info in inspector.get_columns(table.name)
            }

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                if not column.nullable and column.server_default is None:
                    LOGGER.warning(
                        "Skipping automatic creation of column '%s.%s' because it "
                        "has no server default and is non-nullable.",
                        table.name,
                        column.name,
                    )
                    continue

                column_sql = str(CreateColumn(column).compile(dialect=engine.dialect))
                table_sql = preparer.format_table(table)

                LOGGER.info(
                    "Adding missing column '%s.%s' using DDL: %s",
                    table.name,
                    column.name,
                    column_sql,
                )

                try:
                    connection.execute(
                        text(f"ALTER TABLE {table_sql} ADD COLUMN {column_sql}")
                    )
                except OperationalError as exc:  # pragma: no cover - defensive logging
                    LOGGER.exception(
                        "Failed to add column '%s.%s' to the SQLite database.",
                        table.name,
                        column.name,
                    )
                    raise exc

                existing_columns.add(column.name)


__all__ = ["synchronize_sqlite_schema"]
