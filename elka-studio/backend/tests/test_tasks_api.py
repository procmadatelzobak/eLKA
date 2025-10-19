"""Tests for task API helpers that update task status."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import tasks
from app.db.session import Base
from app.models.task import Task, TaskStatus


@pytest.fixture()
def in_memory_session():
    """Provide an isolated in-memory database session for tests."""

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_update_task_status_broadcasts_pause(
    monkeypatch: pytest.MonkeyPatch, in_memory_session
) -> None:
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


def test_task_serialization_includes_payload() -> None:
    """`Task.to_dict` exposes params and result payloads for the UI."""

    task = Task(
        project_id=5,
        type="generate_story",
        status=TaskStatus.SUCCESS,
        params={"seed": "tajemná knihovna"},
        result={
            "story": "Byl jednou jeden příběh",
            "files": {"Lore/story.md": "obsah"},
        },
        total_input_tokens=120,
        total_output_tokens=55,
    )

    payload = task.to_dict()

    assert payload["params"] == {"seed": "tajemná knihovna"}
    assert payload["result"]["story"].startswith("Byl jednou")
    assert "Lore/story.md" in payload["result"]["files"]
    assert payload["total_input_tokens"] == 120
    assert payload["total_output_tokens"] == 55


def test_process_story_response_masks_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """process_story never exposes configured Gemini credentials."""

    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-token")

    monkeypatch.setattr(tasks, "_synchronise_project", lambda *args, **kwargs: None)

    class DummyTaskRecord:
        id = 42
        celery_task_id = "abc123"

    def fake_create_task(
        project_id: int, task_type: str, params: dict
    ) -> DummyTaskRecord:
        assert "super-secret-token" not in str(params)
        return DummyTaskRecord()

    monkeypatch.setattr(
        tasks,
        "task_manager",
        type("DummyManager", (), {"create_task": staticmethod(fake_create_task)})(),
    )

    payload = tasks.ProcessStoryRequest(project_id=1, story_text="Legend", apply=False)
    response = tasks.process_story(payload, session=None)
    assert response.dict() == {"task_id": 42, "celery_task_id": "abc123"}
