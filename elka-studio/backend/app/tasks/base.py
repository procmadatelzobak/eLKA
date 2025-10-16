"""Core Celery tasks for eLKA Studio."""

from __future__ import annotations

import time

from app.celery_app import celery_app
from app.models.task import TaskStatus
from app.services.task_manager import TaskManager


@celery_app.task(bind=True, name="app.tasks.dummy_task")
def dummy_task(self, task_db_id: int, **_: object) -> None:
    """A demonstrative long-running task that reports progress back to the API."""

    manager = TaskManager()
    celery_task_id = self.request.id

    try:
        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=0,
            log_message=f"Task {task_db_id} started.",
        )

        total_steps = 10
        for step in range(total_steps):
            time.sleep(1)
            progress = int(((step + 1) / total_steps) * 100)
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=progress,
                log_message=f"Task {task_db_id}: Step {step + 1} of {total_steps} completed.",
            )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=f"Task {task_db_id} finished successfully.",
        )
    except Exception as exc:  # pragma: no cover - defensive safeguard
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
        )
        raise


__all__ = ["dummy_task"]
