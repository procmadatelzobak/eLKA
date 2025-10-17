"""Tests for task API helpers that update task status."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import tasks
from app.db.session import Base
from app.models.task import Task, TaskStatus


@pytest.fixture()
def in_memory_session():
    """Provide an isolated in-memory database session for tests."""

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_update_task_status_broadcasts_pause(monkeypatch: pytest.MonkeyPatch, in_memory_session) -> None:
    """Pausing a task uses the task manager instance to broadcast the update."""

    task = Task(project_id=101, type="dummy", status=TaskStatus.RUNNING)
    in_memory_session.add(task)
    in_memory_session.commit()
    in_memory_session.refresh(task)

    broadcast_calls: list[int] = []

    class DummyManager:
        def broadcast_update(self, project_id: int) -> None:
            broadcast_calls.append(project_id)

    monkeypatch.setattr(tasks, "task_manager", DummyManager())

    updated = tasks._update_task_status(in_memory_session, task.id, TaskStatus.PAUSED)

    assert updated.status == TaskStatus.PAUSED
    assert broadcast_calls == [task.project_id]
