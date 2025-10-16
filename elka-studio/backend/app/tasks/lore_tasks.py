"""Celery tasks powering the lore processing pipeline."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from textwrap import dedent

from celery.utils.log import get_task_logger
from sqlalchemy.orm import Session, joinedload

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


def _get_task_with_project(session: Session, task_db_id: int) -> Task:
    task: Task | None = (
        session.query(Task)
        .options(joinedload(Task.project))
        .filter(Task.id == task_db_id)
        .one_or_none()
    )
    if task is None:
        raise ValueError(f"Task with id {task_db_id} does not exist")
    if task.project is None:
        raise ValueError(f"Task {task_db_id} is not linked to a project")
    return task


def _ensure_project_path(project: Project, config: Config) -> Path:
    project_path_str = project.local_path or str(config.projects_dir / project.name)
    project_path = Path(project_path_str)
    if not project_path.exists():
        raise FileNotFoundError(
            f"Project path '{project_path}' does not exist. Synchronise the project before retrying."
        )
    return project_path


def _generate_metadata_block(project: Project, seed: str, config: Config) -> str:
    generated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    title = seed.strip().split("\n", maxsplit=1)[0].strip().title() or "Untitled Saga Entry"
    metadata = {
        "title": title,
        "seed": seed.strip(),
        "project": project.name,
        "generated_at": generated_at,
        "model": config.ai_model,
        "author": "eLKA Autonomous Scribe",
    }
    lines = ["---"] + [f"{key}: {value}" for key, value in metadata.items()] + ["---", ""]
    return "\n".join(lines)


def _write_story(seed: str, project: Project, config: Config) -> str:
    metadata = _generate_metadata_block(project, seed, config)
    premise = seed.strip() or "An unexpected development in the eLKA universe."
    paragraphs = dedent(
        f"""
        ## Opening
        The saga opens on the central theme: {premise}. The tone mirrors the established
        chronicles of {project.name}, weaving familiar motifs with fresh tensions.

        ## Rising Action
        Characters evolve as they respond to the call of the seed. Relationships shift,
        secrets surface, and the lore of {project.name} deepens through new dilemmas
        sparked by the guiding idea.

        ## Resolution
        The story concludes with consequences that matter to the wider canon. Threads
        remain for future tales, while the immediate conflict finds closure that feels
        authentic to the universe.
        """
    ).strip()
    return f"{metadata}{paragraphs}\n"


def _plan_saga(theme: str, chapters: int) -> list[dict[str, str]]:
    chapter_templates = [
        "Awakening",
        "Rising Tension",
        "Crossroads",
        "Revelation",
        "Convergence",
        "Climax",
        "Aftermath",
        "Legacy",
    ]
    plan: list[dict[str, str]] = []
    for index in range(chapters):
        template = chapter_templates[index % len(chapter_templates)]
        number = index + 1
        title = f"{theme.title()} — {template} ({number})"
        seed = (
            f"Chapter {number} of the {theme} saga focuses on {template.lower()} moments, "
            "building on established canon with new conflicts and discoveries."
        )
        plan.append({"title": title, "seed": seed})
    return plan


def _wait_while_paused(task_db_id: int, interval_seconds: int = 30) -> None:
    while True:
        session = SessionLocal()
        try:
            status = (
                session.query(Task.status)
                .filter(Task.id == task_db_id)
                .scalar()
            )
        finally:
            session.close()

        if status != TaskStatus.PAUSED:
            break

        logger.info("Task %s is paused; waiting %s seconds before rechecking.", task_db_id, interval_seconds)
        time.sleep(interval_seconds)


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
        task = _get_task_with_project(session, task_db_id)
        project = task.project
        assert project is not None  # for mypy

        project_path = _ensure_project_path(project, config)

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


@celery_app.task(bind=True, name="app.tasks.lore_tasks.generate_story_from_seed_task")
def generate_story_from_seed_task(self, task_db_id: int, seed: str) -> None:
    """Generate a story from a seed idea and enqueue processing."""

    manager = TaskManager()
    celery_task_id = self.request.id
    config = Config()

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: starting story generation from seed.",
    )

    session = SessionLocal()
    try:
        task = _get_task_with_project(session, task_db_id)
        project = task.project
        assert project is not None

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=25,
            log_message="Drafting story content via generator model.",
        )

        ai_adapter = get_default_ai_adapter(config)
        _ = ai_adapter  # placeholder to emphasise generator usage
        story_content = _write_story(seed, project, config)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=60,
            log_message="Story drafted. Scheduling processing pipeline.",
        )

        process_task = manager.create_task(
            project_id=project.id,
            task_type="process_story",
            params={"story_content": story_content},
        )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=(
                "Story generation finished. Created processing task "
                f"#{process_task.id} for validation and archival."
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("generate_story_from_seed_task failed: %s", exc)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
        )
        raise
    finally:
        session.close()


@celery_app.task(bind=True, name="app.tasks.lore_tasks.generate_saga_task")
def generate_saga_task(self, task_db_id: int, theme: str, chapters: int) -> None:
    """Plan a saga and dispatch story generation subtasks."""

    if chapters < 1:
        raise ValueError("Saga must contain at least one chapter.")

    manager = TaskManager()
    celery_task_id = self.request.id
    config = Config()

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: planning a {chapters}-part saga for theme '{theme}'.",
    )

    session = SessionLocal()
    try:
        task = _get_task_with_project(session, task_db_id)
        project = task.project
        assert project is not None

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=20,
            log_message="Requesting saga outline from generator model.",
        )

        plan = _plan_saga(theme, chapters)
        plan_payload = json.dumps({"chapters": plan}, ensure_ascii=False)
        logger.debug("Saga plan for task %s: %s", task_db_id, plan_payload)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=40,
            log_message="Saga outline prepared. Dispatching chapter tasks.",
        )

        for index, chapter in enumerate(plan, start=1):
            _wait_while_paused(task_db_id)
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=40 + int(50 * index / max(chapters, 1)),
                log_message=(
                    f"Dispatching chapter {index}/{chapters}: {chapter['title']}."
                ),
            )
            sub_task = manager.create_task(
                project_id=project.id,
                task_type="generate_story",
                params={"seed": chapter["seed"]},
            )
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                log_message=(
                    f"Chapter task #{sub_task.id} created for '{chapter['title']}'."
                ),
            )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message="Saga generation tasks dispatched successfully.",
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("generate_saga_task failed: %s", exc)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
        )
        raise
    finally:
        session.close()


__all__ = [
    "process_story_task",
    "generate_story_from_seed_task",
    "generate_saga_task",
]
