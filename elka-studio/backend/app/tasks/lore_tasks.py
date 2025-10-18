"""Celery tasks powering the lore processing pipeline."""

from __future__ import annotations

import difflib
import json
import time
from datetime import datetime
from textwrap import dedent

from celery.utils.log import get_task_logger

from app.adapters.ai.base import get_ai_adapters
from app.celery_app import celery_app
from app.core.context import app_context
from app.core.archivist import load_universe
from app.core.extractor import _slugify, extract_fact_graph
from app.core.planner import plan_changes
from app.core.validator import validate_universe
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.services.task_manager import TaskManager

logger = get_task_logger(__name__)


def _generate_metadata_block(project: Project, seed: str) -> str:
    config = app_context.config
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


def _write_story(seed: str, project: Project, generated_body: str | None = None) -> str:
    metadata = _generate_metadata_block(project, seed)
    body = (generated_body or "").strip()
    if not body:
        premise = seed.strip() or "An unexpected development in the eLKA universe."
        body = dedent(
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
    if not body.endswith("\n"):
        body = f"{body}\n"
    return f"{metadata}{body}"


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


def _get_current_status(task_db_id: int) -> TaskStatus | None:
    session = SessionLocal()
    try:
        status: TaskStatus | None = (
            session.query(Task.status)
            .filter(Task.id == task_db_id)
            .scalar()
        )
    finally:
        session.close()

    return status


def _wait_while_paused(task_db_id: int, interval_seconds: int = 30) -> None:
    while True:
        status = _get_current_status(task_db_id)

        if status != TaskStatus.PAUSED:
            break

        logger.info(
            "Task %s is paused; waiting %s seconds before rechecking.",
            task_db_id,
            interval_seconds,
        )
        time.sleep(interval_seconds)


@celery_app.task(bind=True, name="app.tasks.lore_tasks.uce_process_story_task")
def uce_process_story_task(
    self,
    task_db_id: int,
    project_id: int,
    story_text: str,
    apply: bool = False,
) -> None:
    """Execute the Universe Consistency Engine pipeline."""

    manager = TaskManager()
    celery_task_id = self.request.id

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: starting Universe Consistency Engine run.",
    )

    try:
        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = app_context.git_manager.resolve_project_path(project)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message=f"Loaded project '{project.name}'. Extracting facts...",
        )

        validator_ai, writer_ai = get_ai_adapters(app_context.config)
        incoming_graph = extract_fact_graph(story_text, validator_ai)
        current_graph = load_universe(project_path)
        issues = validate_universe(current_graph, incoming_graph, validator_ai)

        for issue in issues:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=35,
                log_message=f"UCE {issue.level.upper()} {issue.code}: {issue.message}",
            )

        if any(issue.level == "error" for issue in issues):
            manager.update_task_status(
                celery_task_id,
                TaskStatus.FAILURE,
                progress=40,
                log_message="UCE detected blocking inconsistencies; aborting run.",
            )
            return

        changeset = plan_changes(current_graph, incoming_graph, project_path, writer_ai)
        if not changeset.files:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.SUCCESS,
                progress=60,
                log_message="UCE no-op: universe already up-to-date.",
                result={
                    "diff_preview": "",
                    "summary": changeset.summary,
                    "files": [],
                    "notes": ["no-op: universe already up-to-date"],
                },
            )
            return

        diff_preview = []
        for file in changeset.files:
            old_lines = (file.old or "").splitlines(keepends=True)
            new_lines = file.new.splitlines(keepends=True)
            diff = "".join(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{file.path}",
                    tofile=f"b/{file.path}",
                    lineterm="",
                )
            )
            diff_preview.append(diff or f"# No diff for {file.path}")
        diff_preview_text = "\n".join(diff_preview)

        if not apply:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.SUCCESS,
                progress=80,
                log_message="UCE dry-run completed.",
                result={
                    "diff_preview": diff_preview_text,
                    "summary": changeset.summary,
                    "files": [file.path for file in changeset.files],
                    "mode": "dry-run",
                },
            )
            return

        git_adapter = app_context.create_git_adapter(project)
        branch_name = f"task/process-story-{task_db_id}"
        base_branch = app_context.config.default_branch
        git_adapter.create_branch(branch_name, base=base_branch)
        git_adapter.apply_changeset(changeset)
        commit_sha = git_adapter.commit_all(
            f"Add UCE changes for {project.name}",
        )
        git_adapter.push_branch(branch_name)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=f"UCE applied changes on {branch_name}, commit {commit_sha}",
            result={
                "branch": branch_name,
                "base_branch": base_branch,
                "commit_sha": commit_sha,
                "diff_preview": diff_preview_text,
                "summary": changeset.summary,
                "files": [file.path for file in changeset.files],
                "mode": "apply",
                "approval_required": True,
            },
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("uce_process_story_task failed: %s", exc)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
        )
        raise


@celery_app.task(bind=True, name="app.tasks.lore_tasks.process_story_task")
def process_story_task(
    self,
    task_db_id: int,
    project_id: int,
    story_content: str,
    pr_id: int | None = None,
) -> None:
    """Execute the story validation and archival pipeline."""

    manager = TaskManager()
    celery_task_id = self.request.id

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: starting story processing pipeline.",
    )

    try:
        project = app_context.git_manager.get_project_from_db(project_id)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=10,
            log_message=f"Loaded project '{project.name}'. Preparing adapters...",
        )

        git_adapter = app_context.create_git_adapter(project)
        if pr_id is not None:
            logger.debug(
                "process_story_task %s operating on project %s for PR %s",
                task_db_id,
                project.id,
                pr_id,
            )
        archivist = app_context.create_archivist(git_adapter)
        validator = app_context.validator

        project_path = app_context.git_manager.resolve_project_path(project)
        universe_files = app_context.git_manager.load_universe_files(project_path)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=25,
            log_message="Validating story content...",
        )

        validation_report = validator.validate(story_content, universe_files)
        for step in validation_report.steps:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=35,
                log_message=step.summary(),
            )

        if not validation_report.passed:
            messages = " | ".join(validation_report.failed_messages())
            manager.update_task_status(
                celery_task_id,
                TaskStatus.FAILURE,
                progress=40,
                log_message=f"Validation failed: {messages}",
            )
            return

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=55,
            log_message="Validation passed. Archiving story...",
        )

        archive_result = archivist.archive(story_content, universe_files)
        files_to_commit: dict[str, str] = dict(archive_result.files)

        for message in archive_result.log_messages:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=65,
                log_message=message,
            )

        if not files_to_commit:
            manager.update_task_status(
                celery_task_id,
                TaskStatus.FAILURE,
                progress=70,
                log_message="Archival produced no files to commit.",
            )
            return

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=75,
            log_message="Prepared files for commit.",
            result={
                "files": files_to_commit,
                "metadata": archive_result.metadata,
            },
        )

        commit_summary = archive_result.metadata.get("summary", "New story")
        commit_message = f"Add lore entry: {commit_summary}"

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=80,
            log_message="Committing story to project repository...",
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


@celery_app.task(bind=True, name="app.tasks.lore_tasks.generate_story_from_seed_task")
def generate_story_from_seed_task(
    self,
    task_db_id: int,
    project_id: int,
    seed: str,
    pr_id: int | None = None,
) -> None:
    """Generate a story from a seed idea and enqueue processing."""

    manager = TaskManager()
    celery_task_id = self.request.id

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: starting story generation from seed.",
    )

    try:
        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = app_context.git_manager.resolve_project_path(project)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message=f"Loaded project '{project.name}'. Gathering universe context...",
        )

        try:
            current_graph = load_universe(project_path)
            # Prepare a concise context summary for the prompt
            context_summary = "Existing Universe Context:\n"
            if current_graph.core_truths:
                context_summary += "- Core Truths: " + "; ".join(current_graph.core_truths) + "\n"
            # Optional: Add summaries of key entities or recent events if needed, be mindful of token limits
            # Example (limit to 5 entities):
            # if current_graph.entities:
            #     context_summary += "- Key Entities: " + ", ".join([e.id for e in current_graph.entities[:5]]) + "\n"
            # Example (limit to 5 events):
            # if current_graph.events:
            #     context_summary += "- Recent Events: " + ", ".join([e.title for e in current_graph.events[-5:]]) + "\n"

        except Exception as e:
            logger.warning(f"Could not load universe context for project {project_id}: {e}")
            context_summary = "Could not load universe context.\n"

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=25,
            log_message="Universe context loaded. Preparing AI adapter...",
        )

        model_key = manager.config.get_model_key_for_task("generation")
        model_name = manager.config.get_model_name_for_task("generation")
        adapter_name = "heuristic" if model_key == "heuristic" else manager.config.get_default_adapter()
        ai_adapter = manager.ai_adapter_factory.get_adapter(adapter_name, model_key=model_key)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=40,
            log_message=(
                f"Using AI adapter '{adapter_name}' with model key '{model_key}' "
                f"(model: {model_name})."
            ),
        )

        prompt_template = dedent(
            """
            You are the lead chronicler for the {project_name} universe. Using the seed
            idea below, craft a cohesive Markdown story that honours existing canon.

            {context_summary}

            Seed idea:
            {seed}

            Requirements:
            - Write 3-4 paragraphs with natural flow (no headings unless necessary).
            - Keep tone consistent with previous chronicles of {project_name}.
            - Mention at least one established character or location if applicable.
            - Return Markdown without code fences.
            """
        ).strip()
        prompt = prompt_template.format(
            project_name=project.name,
            seed=seed.strip(),
            context_summary=context_summary,
        )

        generated_body = ""
        if hasattr(ai_adapter, "generate_text") and adapter_name != "heuristic":
            generated_body = ai_adapter.generate_text(prompt, model_key=model_key).strip()

        story_content = _write_story(seed, project, generated_body=generated_body)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=60,
            log_message="Story drafted. Scheduling processing pipeline.",
            result={"story": story_content},
        )

        process_params = {"story_content": story_content}
        if pr_id is not None:
            process_params["pr_id"] = pr_id

        process_task = manager.create_task(
            project_id=project.id,
            task_type="process_story",
            params=process_params,
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


@celery_app.task(bind=True, name="app.tasks.lore_tasks.generate_saga_task")
def generate_saga_task(
    self,
    task_db_id: int,
    project_id: int,
    theme: str,
    chapters: int,
    pr_id: int | None = None,
) -> None:
    """Plan a saga and dispatch story generation subtasks."""

    if chapters < 1:
        raise ValueError("Saga must contain at least one chapter.")

    manager = TaskManager()
    celery_task_id = self.request.id

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=f"Task {task_db_id}: planning a {chapters}-part saga for theme '{theme}'.",
    )

    try:
        project = app_context.git_manager.get_project_from_db(project_id)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=20,
            log_message=f"Creating saga outline for '{project.name}'.",
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
            current_status = _get_current_status(task_db_id)
            if current_status == TaskStatus.PAUSED:
                logger.info(
                    "Saga task %s paused. Halting chapter dispatch.",
                    task_db_id,
                )
                break

            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=40 + int(50 * index / max(chapters, 1)),
                log_message=(
                    f"Dispatching chapter {index}/{chapters}: {chapter['title']}."
                ),
            )
            params = {"seed": chapter["seed"]}
            if pr_id is not None:
                params["pr_id"] = pr_id
            sub_task = manager.create_task(
                project_id=project.id,
                task_type="generate_story",
                params=params,
            )
            current_status_after_dispatch = _get_current_status(task_db_id)
            if current_status_after_dispatch == TaskStatus.PAUSED:
                logger.info(
                    "Saga task %s paused after dispatching chapter %s. Skipping status update.",
                    task_db_id,
                    chapter["title"],
                )
                break

            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                log_message=(
                    f"Chapter task #{sub_task.id} created for '{chapter['title']}'."
                ),
            )

        final_status = _get_current_status(task_db_id)
        if final_status == TaskStatus.PAUSED:
            logger.info(
                "Saga task %s remains paused; completion status will be set later.",
                task_db_id,
            )
        else:
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


__all__ = [
    "process_story_task",
    "generate_story_from_seed_task",
    "generate_saga_task",
]
