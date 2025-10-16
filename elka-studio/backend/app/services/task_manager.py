"""Service utilities for managing background tasks."""

from __future__ import annotations

from typing import Callable

from celery.result import AsyncResult
from sqlalchemy.orm import Session

from app.api.websockets import connection_manager
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.task import Task, TaskStatus


class TaskManager:
    """High-level orchestration for scheduling and tracking background tasks."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def create_task(self, project_id: int, task_type: str, params: dict | None = None) -> Task:
        """Create a task record and dispatch the corresponding Celery job."""

        params = params or {}
        session = self._session_factory()
        try:
            task = Task(project_id=project_id, type=task_type, status=TaskStatus.PENDING)
            session.add(task)
            session.commit()
            session.refresh(task)

            async_result = self._dispatch_to_celery(task_type, task.id, params)
            task.celery_task_id = async_result.id
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
        finally:
            session.close()

        return task

    def update_task_status(
        self,
        celery_task_id: str,
        status: str,
        progress: int | None = None,
        log_message: str | None = None,
    ) -> None:
        """Persist task status changes and broadcast them to websocket clients."""

        session = self._session_factory()
        project_id: int | None = None
        try:
            task = (
                session.query(Task)
                .filter(Task.celery_task_id == celery_task_id)
                .one_or_none()
            )
            if not task:
                return

            task.status = status
            if progress is not None:
                task.progress = progress
            if log_message:
                task.log = f"{task.log}\n{log_message}" if task.log else log_message

            session.add(task)
            session.commit()
            project_id = task.project_id
        finally:
            session.close()

        if project_id is not None:
            self._broadcast_update(project_id)

    def _dispatch_to_celery(self, task_type: str, task_db_id: int, params: dict) -> AsyncResult:
        """Map task types to Celery jobs and enqueue the appropriate task."""

        task_name = self._resolve_task_name(task_type)
        return celery_app.send_task(task_name, args=[task_db_id], kwargs=params)

    def _resolve_task_name(self, task_type: str) -> str:
        """Translate a logical task type into a Celery task name."""

        task_map = {
            "dummy": "app.tasks.dummy_task",
            "dummy_task": "app.tasks.dummy_task",
            "process_story": "app.tasks.lore_tasks.process_story_task",
            "process_story_task": "app.tasks.lore_tasks.process_story_task",
        }
        if task_type not in task_map:
            raise ValueError(f"Unknown task type '{task_type}'.")
        return task_map[task_type]

    @staticmethod
    def _broadcast_update(project_id: int) -> None:
        """Notify websocket listeners about task updates."""

        connection_manager.notify_project(project_id)


__all__ = ["TaskManager"]
