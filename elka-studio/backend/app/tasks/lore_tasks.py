"""Celery tasks powering the lore processing pipeline."""

from __future__ import annotations

import difflib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from textwrap import dedent

from celery.utils.log import get_task_logger

from app.adapters.ai.base import get_ai_adapters
from app.celery_app import celery_app
from app.core.context import app_context
from app.core.archivist import load_universe
from app.core.extractor import extract_fact_graph
from app.core.planner import plan_changes
from app.core.validator import validate_universe
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.tasks.base import BaseTask

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


def _load_full_universe_context(project_path: Path, project_id: int) -> str:
    include_dirs = ["Objekty", "Legendy", "Pokyny", "Příběhy"]
    include_files = ["timeline.txt", "timeline.md", "README.txt", "README.md"]

    env_dirs = os.getenv("ELKA_UNIVERSE_CONTEXT_DIRS")
    if env_dirs:
        include_dirs = [
            entry.strip()
            for entry in env_dirs.split(os.pathsep)
            if entry.strip()
        ] or include_dirs

    env_files = os.getenv("ELKA_UNIVERSE_CONTEXT_FILES")
    if env_files:
        include_files = [
            entry.strip()
            for entry in env_files.split(os.pathsep)
            if entry.strip()
        ] or include_files

    full_context_string = ""
    try:
        for item_name in include_dirs:
            item_path = project_path / item_name
            if not item_path.is_dir():
                continue
            for pattern in ("*.txt", "*.md"):
                for filepath in item_path.rglob(pattern):
                    if not filepath.is_file():
                        continue
                    relative_path = filepath.relative_to(project_path)
                    full_context_string += f"--- START FILE: {relative_path} ---\n"
                    try:
                        full_context_string += (
                            filepath.read_text(encoding="utf-8") + "\n"
                        )
                    except Exception as exc:  # pragma: no cover - filesystem interaction
                        logger.warning("Could not read file %s: %s", filepath, exc)
                    full_context_string += (
                        f"--- END FILE: {relative_path} ---\n\n"
                    )

        for file_name in include_files:
            if not file_name:
                continue
            file_path = project_path / file_name
            if not file_path.is_file():
                continue
            full_context_string += f"--- START FILE: {file_name} ---\n"
            try:
                full_context_string += file_path.read_text(encoding="utf-8") + "\n"
            except Exception as exc:  # pragma: no cover - filesystem interaction
                logger.warning("Could not read file %s: %s", file_path, exc)
            full_context_string += f"--- END FILE: {file_name} ---\n\n"

        if not full_context_string:
            full_context_string = "No universe context files found or loaded."
            logger.warning("Universe context is empty for project %s.", project_id)
        else:
            word_count = len(full_context_string.split())
            logger.info(
                "Loaded full context for project %s (approx. %s words).",
                project_id,
                word_count,
            )
    except Exception as exc:  # pragma: no cover - filesystem interaction
        logger.error(
            "Failed to load full universe context for project %s: %s",
            project_id,
            exc,
        )
        full_context_string = f"Error loading universe context: {exc}"

    return full_context_string


def _persist_context_token_count(project_id: int, token_count: int) -> None:
    if token_count < 0:
        token_count = 0

    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            return
        project.estimated_context_tokens = token_count
        session.add(project)
        session.commit()


def _accumulate_usage(
    usage: dict | None,
    accumulator: dict[str, int],
) -> None:
    if not usage:
        return
    accumulator["input"] += int(usage.get("prompt_token_count", 0) or 0)
    accumulator["output"] += int(usage.get("candidates_token_count", 0) or 0)


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.tasks.lore_tasks.uce_process_story_task",
)
def uce_process_story_task(
    self,
    task_db_id: int,
    project_id: int,
    story_text: str,
    apply: bool = False,
) -> None:
    """Execute the Universe Consistency Engine pipeline."""

    from app.services.task_manager import TaskManager

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


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.tasks.lore_tasks.generate_story_from_seed",
)
def generate_story_from_seed_task(
    self,
    task_db_id: int,
    project_id: int,
    seed: str,
    pr_id: int | None = None,
) -> dict:
    """Generate a story from a seed and return the content for further processing."""

    from app.services.task_manager import TaskManager

    manager = TaskManager()
    celery_task_id = self.request.id
    tokens = {"input": 0, "output": 0}

    try:
        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=5,
            log_message=f"Task {task_db_id}: starting story generation from seed.",
        )

        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = Path(app_context.git_manager.resolve_project_path(project))

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message=(
                f"Loaded project '{project.name}'. Loading full universe context..."
            ),
        )

        full_context_string = _load_full_universe_context(project_path, project_id)

        model_key = manager.config.get_model_key_for_task("generation")
        model_name = manager.config.get_model_name_for_task("generation")
        adapter_name = (
            "heuristic"
            if model_key == "heuristic"
            else manager.config.get_default_adapter()
        )
        ai_adapter = manager.ai_adapter_factory.get_adapter(
            adapter_name, model_key=model_key
        )

        context_tokens = ai_adapter.count_tokens(full_context_string)
        _persist_context_token_count(project_id, context_tokens)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=35,
            log_message=(
                f"Using AI adapter '{adapter_name}' (model key '{model_key}', model '{model_name}')."
            ),
        )

        prompt_template = """
**Full Universe Context:**
---
{full_context_string}
---
**End of Full Universe Context**

**Instruction:** Based **strictly and solely** on the **Full Universe Context** provided above, continue the story for project '{project_name}'. Use the following seed idea. Ensure the generated story is deeply consistent with **all** aspects of the established lore, characters, locations, events, timeline, and writing style found in the context. Output only the new story content in Markdown format. Do not repeat the context.

**Seed idea:** {seed}

**Generated Story:**
""".strip()

        prompt = prompt_template.format(
            project_name=project.name,
            seed=seed.strip(),
            full_context_string=full_context_string,
        )

        generated_body = ""
        text, usage_metadata = ai_adapter.generate_text(
            prompt,
            model_key=model_key if adapter_name != "heuristic" else None,
        )
        generated_body = text.strip()
        _accumulate_usage(usage_metadata, tokens)

        story_content = _write_story(seed, project, generated_body=generated_body)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=55,
            log_message="Story drafted. Ready for processing pipeline...",
            result={"story": story_content},
        )

        return {
            "task_db_id": task_db_id,
            "project_id": project_id,
            "story_content": story_content,
            "universe_context": full_context_string,
            "pr_id": pr_id,
        }
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("generate_story_from_seed_task failed: %s", exc)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
        )
        raise
    finally:
        self.update_db_task_tokens(tokens["input"], tokens["output"])


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.tasks.lore_tasks.process_story",
)
def process_story_task(
    self,
    payload: dict | int,
    project_id: int | None = None,
    story_content: str | None = None,
    pr_id: int | None = None,
) -> None:
    """Validate, archive, and commit a story to the project's repository."""

    from app.services.task_manager import TaskManager

    manager = TaskManager()
    celery_task_id = self.request.id
    tokens = {"input": 0, "output": 0}

    if isinstance(payload, dict):
        task_db_id = int(payload.get("task_db_id") or 0)
        story_content = story_content or payload.get("story_content")
        project_id = project_id or payload.get("project_id")
        pr_id = pr_id or payload.get("pr_id")
        universe_context = payload.get("universe_context")
    else:
        task_db_id = int(payload)
        universe_context = None

    if not story_content:
        raise ValueError("Story content is required for processing.")
    if project_id is None:
        raise ValueError("Project identifier is required for processing.")
    if not task_db_id:
        raise ValueError("Task database identifier is required for processing.")

    try:
        project_id_int = int(project_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Project identifier is required for processing.") from exc

    project_id = project_id_int

    try:
        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = Path(app_context.git_manager.resolve_project_path(project))

        if not universe_context:
            universe_context = _load_full_universe_context(project_path, project_id_int)
            ai_for_context = manager.ai_adapter_factory.get_adapter(
                manager.config.get_default_adapter(),
                model_key=manager.config.get_model_key_for_task("generation"),
            )
            context_tokens = ai_for_context.count_tokens(universe_context)
            _persist_context_token_count(project_id_int, context_tokens)

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.RUNNING,
            progress=55,
            log_message="Story processing pipeline started.",
        )

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.RUNNING,
            progress=60,
            log_message="Validating story content...",
        )

        validator = app_context.validator
        validation_report = validator.validate(
            story_content,
            universe_context=universe_context,
        )

        for step in validation_report.steps:
            manager.update_task_status_by_db_id(
                task_db_id,
                TaskStatus.RUNNING,
                progress=65,
                log_message=step.summary(),
            )

        if not validation_report.passed:
            messages = " | ".join(validation_report.failed_messages())
            manager.update_task_status_by_db_id(
                task_db_id,
                TaskStatus.FAILURE,
                progress=70,
                log_message=f"Validation failed: {messages}",
            )
            return

        git_adapter = app_context.create_git_adapter(project)
        archivist = app_context.create_archivist(git_adapter)

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.RUNNING,
            progress=75,
            log_message="Validation passed. Archiving story...",
        )

        archive_result = archivist.archive(
            story_content,
            universe_context=universe_context,
        )
        files_to_commit: dict[str, str] = dict(archive_result.files)

        for message in archive_result.log_messages:
            manager.update_task_status_by_db_id(
                task_db_id,
                TaskStatus.RUNNING,
                progress=80,
                log_message=message,
            )

        if not files_to_commit:
            manager.update_task_status_by_db_id(
                task_db_id,
                TaskStatus.FAILURE,
                progress=82,
                log_message="Archival produced no files to commit.",
            )
            return

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.RUNNING,
            progress=85,
            log_message="Prepared files for commit.",
            result={
                "files": files_to_commit,
                "metadata": archive_result.metadata,
            },
        )

        commit_summary = archive_result.metadata.get("summary", "New story")
        commit_message = f"Add lore entry: {commit_summary}"

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.RUNNING,
            progress=90,
            log_message="Committing story to project repository...",
        )

        git_adapter.update_pr_branch(
            files=files_to_commit,
            commit_message=commit_message,
        )

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message="Story processed and archived successfully.",
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("process_story_task failed: %s", exc)
        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.FAILURE,
            log_message=f"Processing failed: {exc}",
        )
        raise
    finally:
        self.update_db_task_tokens(tokens["input"], tokens["output"])

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

    from app.services.task_manager import TaskManager

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
    "uce_process_story_task",
    "generate_story_from_seed_task",
    "process_story_task",
    "generate_saga_task",
]
