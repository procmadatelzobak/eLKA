"""Core Celery task utilities and base implementations for eLKA Studio."""

from __future__ import annotations

import time
from typing import Any

from celery import Task
from google.api_core.exceptions import ResourceExhausted
from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.task import Task as TaskModel, TaskStatus


logger = get_task_logger(__name__)


class BaseTask(Task):
    """Base class providing helpers for concrete Celery tasks."""

    abstract = True
    autoretry_for = (ResourceExhausted,)
    retry_kwargs = {"max_retries": 5}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - celery runtime
        self.db_task_id: int | None = None
        if args:
            candidate = args[0]
            if isinstance(candidate, dict) and "task_db_id" in candidate:
                try:
                    self.db_task_id = int(candidate["task_db_id"])
                except (TypeError, ValueError):
                    self.db_task_id = None
            else:
                try:
                    self.db_task_id = int(candidate)
                except (TypeError, ValueError):
                    self.db_task_id = None
        elif "task_db_id" in kwargs:
            try:
                self.db_task_id = int(kwargs["task_db_id"])
            except (TypeError, ValueError):
                self.db_task_id = None
        return super().__call__(*args, **kwargs)

    def update_db_task_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Persist aggregated token counters for the current task."""

        if not getattr(self, "db_task_id", None):
            return

        try:
            with SessionLocal() as session:
                task = session.get(TaskModel, self.db_task_id)
                if task is None:
                    return
                current_input = task.total_input_tokens or 0
                current_output = task.total_output_tokens or 0
                task.total_input_tokens = current_input + max(input_tokens, 0)
                task.total_output_tokens = current_output + max(output_tokens, 0)
                session.add(task)
                session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to persist token counters for task %s: %s", self.db_task_id, exc)


@celery_app.task(bind=True, base=BaseTask, name="app.tasks.dummy_task")
def dummy_task(self, task_db_id: int, **_: object) -> None:
    """A demonstrative long-running task that reports progress back to the API."""

    from app.services.task_manager import TaskManager

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


__all__ = ["BaseTask", "dummy_task"]
