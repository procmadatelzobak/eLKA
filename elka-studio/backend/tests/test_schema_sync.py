"""Tests covering the automatic SQLite schema synchronisation helper."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.db.schema_sync import synchronize_sqlite_schema
from app.db.session import Base


def test_synchronize_sqlite_schema_adds_missing_columns(tmp_path: Path) -> None:
    """Columns added to the ORM are created on existing SQLite databases."""

    db_path = tmp_path / "legacy.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    # Simulate a pre-existing tasks table that predates newer columns.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    type VARCHAR(255) NOT NULL,
                    status VARCHAR(50) NOT NULL
                )
                """
            )
        )

    # Ensure metadata is aware of all tables/columns defined in the models.
    Base.metadata.create_all(engine)

    synchronize_sqlite_schema(engine, Base.metadata)

    inspector = inspect(engine)
    task_columns = {column["name"] for column in inspector.get_columns("tasks")}

    assert "parent_task_id" in task_columns
    assert "result" in task_columns
