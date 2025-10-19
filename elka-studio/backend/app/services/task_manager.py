"""Service utilities for managing background tasks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Tuple

from celery import chain
from celery.result import AsyncResult
from sqlalchemy.orm import Session

from app.db.redis_client import get_redis_client
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.core.context import app_context
from app.services.ai_adapter_factory import AIAdapterFactory
from app.tasks.base import dummy_task
from app.tasks import lore_tasks


TASK_MAPPING = {
    "dummy": dummy_task,
    "dummy_task": dummy_task,
    "uce_process_story": lore_tasks.uce_process_story_task,
    "uce_process_story_task": lore_tasks.uce_process_story_task,
    "generate_story": lore_tasks.generate_story_from_seed_task,
    "generate_story_from_seed": lore_tasks.generate_story_from_seed_task,
    "generate_story_from_seed_task": lore_tasks.generate_story_from_seed_task,
    "generate_and_process_story_from_seed": lore_tasks.generate_story_from_seed_task,
    "generate_and_process_story_from_seed_task": lore_tasks.generate_story_from_seed_task,
    "process_story": lore_tasks.process_story_task,
    "process_story_task": lore_tasks.process_story_task,
    "generate_chapter": lore_tasks.generate_chapter_task,
    "generate_chapter_task": lore_tasks.generate_chapter_task,
    "generate_saga": lore_tasks.generate_saga_task,
    "generate_saga_task": lore_tasks.generate_saga_task,
}


class TaskManager:
    """High-level orchestration for scheduling and tracking background tasks."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._redis_client = get_redis_client()
        self.config = app_context.config
        self.ai_adapter_factory = AIAdapterFactory(self.config)

    def create_task(
        self,
        project_id: int,
        task_type: str,
        params: dict | None = None,
        *,
        parent_task_id: int | None = None,
    ) -> Task:
        """Create a task record and dispatch the corresponding Celery job."""

        params = dict(params or {})
        try:
            project_id_int = int(project_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("project_id must be an integer") from exc
        persisted_params = deepcopy(params)
        params.setdefault("project_id", project_id_int)
        session = self._session_factory()
        try:
            task = Task(
                project_id=project_id_int,
                type=task_type,
                status=TaskStatus.PENDING,
                params=persisted_params or None,
                parent_task_id=parent_task_id,
            )
            session.add(task)
            session.commit()
            session.refresh(task)

            async_result, tracking_result = self._dispatch_to_celery(
                task_type, task.id, params
            )
            task.celery_task_id = tracking_result.id
            if async_result.id != tracking_result.id:
                existing_result = task.result or {}
                if not isinstance(existing_result, dict):
                    existing_result = {}
                existing_result.update({"processing_celery_task_id": async_result.id})
                task.result = existing_result
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

    def update_task_status_by_db_id(
        self,
        task_db_id: int,
        status: str,
        progress: int | None = None,
        log_message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Helper to update task status when only the database ID is known."""

        session = self._session_factory()
        celery_task_id: str | None = None
        try:
            task = session.query(Task).filter(Task.id == task_db_id).one_or_none()
            if task and task.celery_task_id:
                celery_task_id = task.celery_task_id
        finally:
            session.close()

        if not celery_task_id:
            return

        self.update_task_status(
            celery_task_id,
            status,
            progress=progress,
            log_message=log_message,
            result=result,
        )

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

    def _dispatch_to_celery(
        self, task_type: str, task_db_id: int, params: dict
    ) -> Tuple[AsyncResult, AsyncResult]:
        """Map task types to Celery jobs and enqueue the appropriate task."""

        if task_type not in TASK_MAPPING:
            raise ValueError(f"Unknown task type '{task_type}'.")

        if task_type in {
            "generate_story",
            "generate_story_from_seed",
            "generate_story_from_seed_task",
            "generate_and_process_story_from_seed",
            "generate_and_process_story_from_seed_task",
        }:
            return self._dispatch_generate_story_chain(task_db_id, params)

        if task_type == "process_story":
            story_content = params.get("story_content")
            if not isinstance(story_content, str) or not story_content.strip():
                raise ValueError("story_content must be a non-empty string")

        task = TASK_MAPPING[task_type]
        async_result = task.apply_async(args=[task_db_id], kwargs=params)
        return async_result, async_result

    def _dispatch_generate_story_chain(
        self, task_db_id: int, params: dict
    ) -> Tuple[AsyncResult, AsyncResult]:
        project_id = params.get("project_id")
        seed = params.get("seed")
        pr_id = params.get("pr_id")
        story_title = params.get("story_title")
        story_author = params.get("story_author")

        try:
            project_id = int(project_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("project_id is required for story generation") from exc
        if not isinstance(seed, str) or not seed.strip():
            raise ValueError("seed must be a non-empty string")
        if not isinstance(story_title, str) or not story_title.strip():
            raise ValueError("story_title must be a non-empty string")
        if not isinstance(story_author, str) or not story_author.strip():
            raise ValueError("story_author must be a non-empty string")

        generate_sig = lore_tasks.generate_story_from_seed_task.s(
            task_db_id,
            project_id=project_id,
            seed=seed,
            pr_id=pr_id,
            story_title=story_title.strip(),
            story_author=story_author.strip(),
        )
        process_sig = lore_tasks.process_story_task.s(
            project_id=project_id,
            pr_id=pr_id,
            story_title=story_title.strip(),
            story_author=story_author.strip(),
        )

        workflow = chain(generate_sig, process_sig)
        async_result = workflow.apply_async()
        tracking_result = async_result.parent or async_result
        return async_result, tracking_result

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

            result_data.update(
                {
                    "merged_into": target_branch,
                    "merge_commit": merge_commit,
                    "approval_required": False,
                }
            )
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
            project = (
                session.query(Project).filter(Project.id == project_id).one_or_none()
            )
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
