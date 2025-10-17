"""Service utilities for managing background tasks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from celery.result import AsyncResult
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.redis_client import get_redis_client
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.core.context import app_context


class TaskManager:
    """High-level orchestration for scheduling and tracking background tasks."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._redis_client = get_redis_client()

    def create_task(self, project_id: int, task_type: str, params: dict | None = None) -> Task:
        """Create a task record and dispatch the corresponding Celery job."""

        params = dict(params or {})
        persisted_params = deepcopy(params)
        params.setdefault("project_id", project_id)
        session = self._session_factory()
        try:
            task = Task(
                project_id=project_id,
                type=task_type,
                status=TaskStatus.PENDING,
                params=persisted_params or None,
            )
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
        result: dict[str, Any] | None = None,
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
            if result is not None:
                payload = deepcopy(result)
                if isinstance(task.result, dict) and isinstance(payload, dict):
                    task.result = {**task.result, **payload}
                else:
                    task.result = payload

            session.add(task)
            session.commit()
            project_id = task.project_id
        finally:
            session.close()

        if project_id is not None:
            self._broadcast_update(project_id)

    def approve_task(self, task_id: int, session: Session | None = None) -> Task:
        """Mark the task result as approved and finalise any pending changes."""

        owns_session = session is None
        db_session = session or self._session_factory()

        try:
            task = db_session.query(Task).filter(Task.id == task_id).one_or_none()
            if task is None:
                raise LookupError(f"Task with id {task_id} does not exist")
            if task.status != TaskStatus.SUCCESS:
                raise ValueError("Only successful tasks can be approved")
            if task.result_approved:
                db_session.expunge(task)
                return task

            task.result_approved = True
            db_session.add(task)
            db_session.commit()
            db_session.refresh(task)
            db_session.expunge(task)
        finally:
            if owns_session:
                db_session.close()

        try:
            final_task = self._finalise_task(task)
        except Exception:
            self._set_task_approval(task.id, False)
            raise

        self.broadcast_update(task.project_id)
        return final_task

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
            "uce_process_story": "app.tasks.lore_tasks.uce_process_story_task",
            "uce_process_story_task": "app.tasks.lore_tasks.uce_process_story_task",
            "generate_story": "app.tasks.lore_tasks.generate_story_from_seed_task",
            "generate_story_from_seed": "app.tasks.lore_tasks.generate_story_from_seed_task",
            "generate_story_from_seed_task": "app.tasks.lore_tasks.generate_story_from_seed_task",
            "generate_saga": "app.tasks.lore_tasks.generate_saga_task",
            "generate_saga_task": "app.tasks.lore_tasks.generate_saga_task",
        }
        if task_type not in task_map:
            raise ValueError(f"Unknown task type '{task_type}'.")
        return task_map[task_type]

    def _broadcast_update(self, project_id: int) -> None:
        """Publish task update notifications to Redis for websocket listeners."""

        channel = f"project_{project_id}_tasks"
        try:
            self._redis_client.publish(channel, "update")
        except Exception:  # pragma: no cover - network/redis dependent
            pass

    def broadcast_update(self, project_id: int) -> None:
        """Public helper for notifying listeners about task changes."""

        self._broadcast_update(project_id)

    def _finalise_task(self, task: Task) -> Task:
        """Perform repository operations required after task approval."""

        result_payload: dict[str, Any] = {}
        if isinstance(task.result, dict):
            result_payload = deepcopy(task.result)

        branch_name = result_payload.get("branch")
        if not branch_name:
            return task

        project = self._load_project(task.project_id)
        git_adapter = app_context.create_git_adapter(project)
        target_branch = app_context.config.default_branch
        merge_commit = git_adapter.merge_branch(branch_name, target_branch)

        session = self._session_factory()
        try:
            stored_task = session.query(Task).filter(Task.id == task.id).one_or_none()
            if stored_task is None:
                raise LookupError(f"Task {task.id} not found during finalisation")

            result_data: dict[str, Any] = {}
            if isinstance(stored_task.result, dict):
                result_data = deepcopy(stored_task.result)

            result_data.update({
                "merged_into": target_branch,
                "merge_commit": merge_commit,
                "approval_required": False,
            })
            stored_task.result = result_data
            session.add(stored_task)
            session.commit()
            session.refresh(stored_task)
            session.expunge(stored_task)
            return stored_task
        finally:
            session.close()

    def _load_project(self, project_id: int) -> Project:
        session = self._session_factory()
        try:
            project = session.query(Project).filter(Project.id == project_id).one_or_none()
            if project is None:
                raise LookupError(f"Project with id {project_id} does not exist")
            session.expunge(project)
            return project
        finally:
            session.close()

    def _set_task_approval(self, task_id: int, approved: bool) -> None:
        session = self._session_factory()
        try:
            task = session.query(Task).filter(Task.id == task_id).one_or_none()
            if task is None:
                return
            task.result_approved = approved
            session.add(task)
            session.commit()
        finally:
            session.close()


__all__ = ["TaskManager"]
