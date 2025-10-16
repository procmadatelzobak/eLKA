"""Celery tasks powering the lore processing pipeline."""

from __future__ import annotations

from pathlib import Path

from celery.utils.log import get_task_logger
from sqlalchemy.orm import joinedload

from app.adapters.ai.base import get_default_ai_adapter
from app.adapters.git.base import GitAdapter
from app.celery_app import celery_app
from app.core.archivist import ArchivistEngine
from app.core.validator import ValidatorEngine
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.services.task_manager import TaskManager
from app.utils.config import Config

logger = get_task_logger(__name__)


@celery_app.task(bind=True, name="app.tasks.lore_tasks.process_story_task")
def process_story_task(self, task_db_id: int, story_content: str) -> None:
    """Execute the story validation and archival pipeline."""

    manager = TaskManager()
    celery_task_id = self.request.id
    config = Config()

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: starting story processing pipeline.",
    )

    session = SessionLocal()
    try:
        task: Task | None = (
            session.query(Task)
            .options(joinedload(Task.project))
            .filter(Task.id == task_db_id)
            .one_or_none()
        )
        if task is None:
            raise ValueError(f"Task with id {task_db_id} does not exist")
        project: Project | None = task.project
        if project is None:
            raise ValueError(f"Task {task_db_id} is not linked to a project")

        project_path_str = project.local_path or str(config.projects_dir / project.name)
        project_path = Path(project_path_str)
        if not project_path.exists():
            raise FileNotFoundError(
                f"Project path '{project_path}' does not exist. Synchronise the project before retrying."
            )

        ai_adapter = get_default_ai_adapter(config)
        git_adapter = GitAdapter(project_path=project_path, config=config)
        validator = ValidatorEngine(ai_adapter=ai_adapter, config=config)
        archivist = ArchivistEngine(git_adapter=git_adapter, ai_adapter=ai_adapter, config=config)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=20,
            log_message="Validation pipeline started.",
        )
        validation_report = validator.validate(story_content)
        for step in validation_report.steps:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=30,
                log_message=step.summary(),
            )

        if not validation_report.passed:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.FAILURE,
                progress=35,
                log_message="Validation failed; aborting archival.",
            )
            return

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=55,
            log_message="Validation passed. Starting archival step.",
        )
        archive_result = archivist.archive(story_content)
        for message in archive_result.log_messages:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=65,
                log_message=message,
            )

        files_to_commit: dict[str, str] = dict(archive_result.files)
        if not files_to_commit:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.FAILURE,
                progress=70,
                log_message="Archival did not return any files to commit.",
            )
            return

        commit_summary = archive_result.metadata.get("summary", "New story")
        commit_message = f"Add lore entry: {commit_summary}"

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=80,
            log_message="Committing story to project repository.",
        )
        git_adapter.update_pr_branch(files=files_to_commit, commit_message=commit_message)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message="Story processed, validated, archived, and pushed successfully.",
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("process_story_task failed: %s", exc)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
        )
        raise
    finally:
        session.close()


__all__ = ["process_story_task"]
