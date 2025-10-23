"""Celery tasks powering the lore processing pipeline."""

from __future__ import annotations

import difflib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List, Optional

from celery.exceptions import Retry
from celery.result import AsyncResult
from celery.utils.log import get_task_logger

from app.adapters.ai.base import get_ai_adapters
from app.celery_app import celery_app
from app.core.context import app_context
from app.core.archivist import ArchivistEngine, load_universe
from app.core.schemas import TaskType
from app.core.extractor import _slugify, extract_fact_graph
from app.core.planner import plan_changes
from app.core.validator import ValidatorEngine, validate_universe
from app.db.session import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.tasks.base import BaseTask
from app.utils.filesystem import sanitize_filename
from app.services.project_settings import load_project_ai_models

logger = get_task_logger(__name__)


def _escape_front_matter(value: str) -> str:
    text = (value or "").strip()
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _build_story_document(
    project: Project,
    seed: str,
    story_title: str,
    story_author: str,
    generated_body: str | None = None,
) -> tuple[str, Path]:
    """Compose the final story document with YAML front matter."""

    resolved_title = story_title.strip() or "Untitled Story"
    resolved_author = story_author.strip() or "eLKA Author"
    body = (generated_body or "").strip()
    if not body:
        body = dedent(
            f"""
            ## Opening
            The saga opens by expanding upon the latest creative direction while respecting the canon of {project.name}.

            ## Rising Action
            Characters evolve as new tensions surface, ensuring the narrative remains faithful to the established universe.

            ## Resolution
            The immediate conflict reaches a satisfying conclusion while leaving deliberate threads for future chronicles.
            """
        ).strip()
    if not body.endswith("\n"):
        body = f"{body}\n"

    timestamp_utc = datetime.now(timezone.utc).replace(microsecond=0)
    generated_at = timestamp_utc.isoformat().replace("+00:00", "Z")
    sanitized_title = sanitize_filename(resolved_title, default="story")
    story_filename = f"{sanitized_title}-{timestamp_utc.strftime('%Y%m%d-%H%M%S')}.md"
    relative_path = Path("stories") / story_filename
    front_matter_lines = [
        "---",
        f'title: "{_escape_front_matter(resolved_title)}"',
        f'author: "{_escape_front_matter(resolved_author)}"',
        f"generated_at: {generated_at}",
        f'seed: "{_escape_front_matter(seed)}"',
        f'project: "{_escape_front_matter(project.name)}"',
        "---",
        "",
    ]
    document = "\n".join(front_matter_lines) + body
    return document, relative_path


def _extract_json_payload(raw_text: str) -> Dict[str, Any]:
    """Best-effort extraction of a JSON payload from AI output."""

    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("Planner response was empty")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError as exc:
                raise ValueError("Failed to parse JSON planner response") from exc
        raise ValueError("Planner response did not contain JSON data")


def _build_chapter_document(
    project: Project,
    *,
    saga_title: str,
    chapter_index: int,
    total_chapters: int,
    chapter_plan: Optional[Dict[str, Any]],
    author: str,
    generated_body: str,
    story_directory: Path,
) -> tuple[str, Path, str]:
    """Create a chapter document with YAML front matter."""

    resolved_saga_title = saga_title.strip() if saga_title else project.name
    plan_title = (chapter_plan or {}).get("title")
    resolved_chapter_title = (plan_title or f"Chapter {chapter_index}").strip()
    combined_title = (
        f"{resolved_saga_title} - {resolved_chapter_title}".strip(" -")
        if resolved_saga_title
        else resolved_chapter_title
    )

    timestamp_utc = datetime.now(timezone.utc).replace(microsecond=0)
    generated_at = timestamp_utc.isoformat().replace("+00:00", "Z")
    sanitized_name = sanitize_filename(
        f"{chapter_index:02d}-{resolved_chapter_title}",
        default=f"chapter-{chapter_index:02d}",
    )
    relative_path = story_directory / f"{sanitized_name}.md"

    front_matter_lines = [
        "---",
        f'title: "{_escape_front_matter(combined_title)}"',
        f'author: "{_escape_front_matter(author)}"',
        f"chapter: {chapter_index}",
        f"total_chapters: {total_chapters}",
        f'saga_title: "{_escape_front_matter(resolved_saga_title)}"',
        f"generated_at: {generated_at}",
    ]

    if chapter_plan:
        outline_text = json.dumps(chapter_plan, ensure_ascii=False, indent=2)
        front_matter_lines.append("outline: |")
        front_matter_lines.extend([f"  {line}" for line in outline_text.splitlines()])

    front_matter_lines.extend(["---", ""])

    body = generated_body.strip()
    if not body.endswith("\n"):
        body = f"{body}\n"

    document = "\n".join(front_matter_lines) + body
    return document, relative_path, combined_title


def _get_current_status(task_db_id: int) -> TaskStatus | None:
    session = SessionLocal()
    try:
        status: TaskStatus | None = (
            session.query(Task.status).filter(Task.id == task_db_id).scalar()
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
    include_dirs = [
        "Stories",
        "Legends",
        "Instructions",
        "Objects",
        "Příběhy",
        "Legendy",
        "Pokyny",
        "Objekty",
    ]
    include_dirs = list(dict.fromkeys(include_dirs))
    include_files = ["timeline.txt", "timeline.md", "README.txt", "README.md"]

    env_dirs = os.getenv("ELKA_UNIVERSE_CONTEXT_DIRS")
    if env_dirs:
        include_dirs = [
            entry.strip() for entry in env_dirs.split(os.pathsep) if entry.strip()
        ] or include_dirs

    env_files = os.getenv("ELKA_UNIVERSE_CONTEXT_FILES")
    if env_files:
        include_files = [
            entry.strip() for entry in env_files.split(os.pathsep) if entry.strip()
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
                    except (
                        Exception
                    ) as exc:  # pragma: no cover - filesystem interaction
                        if isinstance(exc, Retry):
                            raise
                        logger.warning("Could not read file %s: %s", filepath, exc)
                    full_context_string += f"--- END FILE: {relative_path} ---\n\n"

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
                if isinstance(exc, Retry):
                    raise
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
        if isinstance(exc, Retry):
            raise
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
) -> dict[str, int]:
    """Merge usage metadata into ``accumulator`` and return the increment."""

    increment = {"input": 0, "output": 0}
    if not usage:
        return increment

    if "input" in usage or "output" in usage:
        increment["input"] = int(usage.get("input", 0) or 0)
        increment["output"] = int(usage.get("output", 0) or 0)
    else:
        increment["input"] = int(usage.get("prompt_token_count", 0) or 0)
        increment["output"] = int(usage.get("candidates_token_count", 0) or 0)

    accumulator["input"] += increment["input"]
    accumulator["output"] += increment["output"]
    return increment


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.tasks.lore_tasks.uce_process_story_task",
)
def uce_process_story_task(
    self,
    task_db_id: int,
    project_id: int,
    story_text: str | None = None,
    apply: bool = False,
    *,
    story_file_path: str | None = None,
    saga_theme: str | None = None,
    remaining_story_filenames: Optional[List[str]] | None = None,
    parent_task_id: int | None = None,
) -> None:
    """Execute the Universe Consistency Engine pipeline.

    When ``story_file_path`` is provided the task loads the chapter content from
    disk and, on success, chains execution to the remaining chapters to avoid
    running multiple Git operations in parallel.
    """

    from app.services.task_manager import TaskManager

    manager = TaskManager()
    celery_task_id = self.request.id
    _ = parent_task_id

    start_message = (
        f"Task {task_db_id}: starting Universe Consistency Engine run."
        if not story_file_path
        else (
            "Task %s: starting Universe Consistency Engine run for '%s'."
            % (task_db_id, story_file_path)
        )
    )
    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=start_message,
    )

    try:
        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = app_context.git_manager.resolve_project_path(project)

        story_text = (story_text or "").strip()

        if not story_text and story_file_path:
            candidate_path = Path(story_file_path)
            if not candidate_path.is_absolute():
                candidate_path = Path(project_path) / candidate_path

            try:
                story_text = candidate_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.exception(
                    "Failed to load story content from %s: %s",
                    candidate_path,
                    exc,
                )
                raise

        if not story_text:
            raise ValueError(
                "story_text must be provided either directly or via story_file_path"
            )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message=f"Loaded project '{project.name}'. Extracting facts...",
        )

        models = load_project_ai_models(app_context.config, project_id)
        validator_ai, writer_ai = get_ai_adapters(
            app_context.config, project_id=project_id
        )
        incoming_graph = extract_fact_graph(
            story_text,
            writer_ai,
            model_key=models.get("extraction"),
        )
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

        changeset = plan_changes(
            current_graph,
            incoming_graph,
            project_path,
            writer_ai,
            model_key=models.get("planning"),
        )
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
            result_data = {
                "diff_preview": diff_preview_text,
                "summary": changeset.summary,
                "files": [file.path for file in changeset.files],
                "mode": "dry-run",
            }
            manager.update_task_status(
                celery_task_id,
                TaskStatus.SUCCESS,
                progress=80,
                log_message="UCE dry-run completed.",
                result=result_data,
            )
            manager.update_task_field(celery_task_id, "result", result_data)
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

        result_data = {
            "branch": branch_name,
            "base_branch": base_branch,
            "commit_sha": commit_sha,
            "diff_preview": diff_preview_text,
            "summary": changeset.summary,
            "files": [file.path for file in changeset.files],
            "mode": "apply",
            "approval_required": True,
            "story_file_path": story_file_path,
        }
        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=f"UCE applied changes on {branch_name}, commit {commit_sha}",
            result=result_data,
        )
        manager.update_task_field(celery_task_id, "result", result_data)

        if remaining_story_filenames:
            next_story_filename = remaining_story_filenames[0]
            new_remaining_list = remaining_story_filenames[1:]
            logger.info(
                "Queueing sequential UCE processing for %s (remaining %s)",
                next_story_filename,
                len(new_remaining_list),
            )
            uce_process_story_task.apply_async(
                args=[task_db_id],
                kwargs={
                    "project_id": project_id,
                    "story_text": None,
                    "apply": apply,
                    "story_file_path": next_story_filename,
                    "saga_theme": saga_theme,
                    "remaining_story_filenames": new_remaining_list,
                    "parent_task_id": parent_task_id,
                },
            )
    except Exception as exc:  # pragma: no cover - defensive logging
        if isinstance(exc, Retry):
            raise
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
    story_title: str | None = None,
    story_author: str | None = None,
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
        models = load_project_ai_models(app_context.config, project_id)
        validator_ai, writer_ai = get_ai_adapters(
            app_context.config, project_id=project_id
        )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message=(
                f"Loaded project '{project.name}'. Loading full universe context..."
            ),
        )

        full_context_string = _load_full_universe_context(project_path, project_id)
        word_count = len(full_context_string.split())
        logger.info("Loaded full context, estimated word count: %s", word_count)
        if word_count > 500000:
            logger.warning(
                "Full context word count (%s) is very large and might exceed model limits or cause slow processing/high costs.",
                word_count,
            )

        context_tokens = writer_ai.count_tokens(full_context_string)
        _persist_context_token_count(project_id, context_tokens)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=35,
            log_message=(
                "Using writer model '%s' for story generation."
                % models.get("generation")
            ),
        )

        prompt_template = """
**Full Universe Context:**
---
{full_context_string}
---
**End of Full Universe Context**

**Instruction:** Based **strictly and solely** on the **Full Universe Context** provided above, continue the story for project '{project_name}'.
The specific idea to develop is: **'{seed}'**.
Ensure the generated story is deeply consistent with **all** aspects of the established lore, characters, locations, events, timeline, and writing style found in the context. Output only the new story content in Markdown format. Do not repeat the context.

**Seed idea:** {seed}

**Generated Story:**
""".strip()

        prompt = prompt_template.format(
            project_name=project.name,
            seed=seed.strip(),
            full_context_string=full_context_string,
        )

        truncated_prompt = prompt[:500]
        if len(prompt) > 500:
            truncated_prompt += "... (truncated)"
        logger.debug(
            "Prompt being sent to AI for story generation:\n%s",
            truncated_prompt,
        )
        prompt_token_count = len(prompt.split())
        logger.info(
            "Estimated prompt word count for generation: %s",
            prompt_token_count,
        )

        generated_body = ""
        text, usage_metadata = writer_ai.generate_text(
            prompt,
            model_key=models.get("generation"),
        )
        generated_body = text.strip()
        usage_increment = _accumulate_usage(usage_metadata, tokens)

        resolved_title = (
            (story_title or "").strip()
            or seed.split("\n", maxsplit=1)[0].strip()
            or "Untitled Story"
        )
        resolved_author = (story_author or "").strip() or "eLKA Author"
        story_content, story_relative_path = _build_story_document(
            project,
            seed,
            resolved_title,
            resolved_author,
            generated_body=generated_body,
        )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=55,
            log_message="Story drafted. Preparing processing pipeline...",
            result={
                "story": story_content,
                "metadata": {
                    "title": resolved_title,
                    "author": resolved_author,
                    "relative_path": str(story_relative_path),
                },
            },
            input_tokens=usage_increment["input"],
            output_tokens=usage_increment["output"],
        )

        return {
            "task_db_id": task_db_id,
            "project_id": project_id,
            "story_content": story_content,
            "universe_context": full_context_string,
            "pr_id": pr_id,
            "story_title": resolved_title,
            "story_author": resolved_author,
            "story_file_path": str(story_relative_path),
            "seed": seed,
        }
    except Exception as exc:  # pragma: no cover - defensive logging
        if isinstance(exc, Retry):
            raise
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
    story_title: str | None = None,
    story_author: str | None = None,
    story_file_path: str | None = None,
    saga_theme: str | None = None,
) -> None:
    """Validate, archive, and commit a story to the project's repository."""

    from app.services.task_manager import TaskManager

    manager = TaskManager()
    tokens = {"input": 0, "output": 0}

    if isinstance(payload, dict):
        task_db_id = int(payload.get("task_db_id") or 0)
        story_content = story_content or payload.get("story_content")
        project_id = project_id or payload.get("project_id")
        pr_id = pr_id or payload.get("pr_id")
        universe_context = payload.get("universe_context")
        story_title = story_title or payload.get("story_title")
        story_author = story_author or payload.get("story_author")
        story_file_path = story_file_path or payload.get("story_file_path")
        saga_theme = saga_theme or payload.get("saga_theme")
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
        models = load_project_ai_models(app_context.config, project_id)
        validator_ai, writer_ai = get_ai_adapters(
            app_context.config, project_id=project_id
        )

        relative_story_path: Path
        if story_file_path:
            candidate_path = Path(story_file_path)
            if candidate_path.is_absolute():
                try:
                    candidate_path = candidate_path.relative_to(project_path)
                except ValueError:
                    candidate_path = Path("stories") / candidate_path.name
            relative_story_path = candidate_path
        else:
            fallback_title = (
                story_title or "Untitled Story"
            ).strip() or "Untitled Story"
            sanitized = sanitize_filename(fallback_title, default="story")
            timestamped_name = (
                f"{sanitized}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.md"
            )
            if saga_theme:
                saga_slug = _slugify(str(saga_theme)) or "saga"
                relative_story_path = Path("stories") / saga_slug / timestamped_name
            else:
                relative_story_path = Path("stories") / timestamped_name

        if not universe_context:
            universe_context = _load_full_universe_context(project_path, project_id)
            context_tokens = writer_ai.count_tokens(universe_context)
            _persist_context_token_count(project_id, context_tokens)

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

        validator_engine = ValidatorEngine(
            ai_adapter=validator_ai, config=app_context.config
        )
        validation_report = validator_engine.validate(
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
        archivist = ArchivistEngine(
            git_adapter=git_adapter,
            ai_adapter=writer_ai,
            config=app_context.config,
            model_overrides=models,
        )

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.RUNNING,
            progress=75,
            log_message="Validation passed. Archiving story...",
        )

        archive_result = archivist.archive(
            story_content,
            story_file_path=project_path / relative_story_path,
            universe_context=universe_context,
            task_id=task_db_id,
            saga_theme=saga_theme,
        )
        files_to_commit: dict[str, str] = dict(archive_result.files)

        if story_title and "title" not in archive_result.metadata:
            archive_result.metadata["title"] = story_title
        if story_author and "author" not in archive_result.metadata:
            archive_result.metadata["author"] = story_author

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

        commit_summary = archive_result.metadata.get(
            "title"
        ) or archive_result.metadata.get("summary", "New story")
        commit_message = f"Add lore entry: {commit_summary}"

        result_payload = {
            "files": files_to_commit,
            "metadata": archive_result.metadata,
            "commit_message": commit_message,
            "approval_required": True,
            "saga_theme": saga_theme,
            "changed_paths": archive_result.changed_paths,
        }

        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=(
                "Story processed and awaiting approval for commit to"
                f" {manager.config.default_branch}."
            ),
            result=result_payload,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        if isinstance(exc, Retry):
            raise
        logger.exception("process_story_task failed: %s", exc)
        manager.update_task_status_by_db_id(
            task_db_id,
            TaskStatus.FAILURE,
            log_message=f"Processing failed: {exc}",
        )
        raise
    finally:
        self.update_db_task_tokens(tokens["input"], tokens["output"])


@celery_app.task(
    bind=True,
    base=BaseTask,
    name="app.tasks.lore_tasks.generate_chapter_task",
)
def generate_chapter_task(
    self,
    task_db_id: int,
    project_id: int,
    chapter_index: int,
    total_chapters: int,
    saga_outline: Dict[str, Any] | str,
    chapter_plan: Dict[str, Any] | None = None,
    story_title: str | None = None,
    story_author: str | None = None,
    previous_chapter_content: str | None = None,
    pr_id: int | None = None,
    saga_theme: str | None = None,
    parent_task_id: int | None = None,
) -> Dict[str, Any]:
    """Generate a single saga chapter and archive it in the repository."""

    from app.services.task_manager import TaskManager

    manager = TaskManager()
    celery_task_id = self.request.id
    tokens = {"input": 0, "output": 0}
    _ = parent_task_id

    try:
        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=5,
            log_message=(
                f"Task {task_db_id}: generating chapter {chapter_index}/{total_chapters}."
            ),
        )

        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = Path(app_context.git_manager.resolve_project_path(project))
        models = load_project_ai_models(app_context.config, project_id)
        _, writer_ai = get_ai_adapters(app_context.config, project_id=project_id)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message="Loading universe context for chapter generation...",
        )

        full_context_string = _load_full_universe_context(project_path, project_id)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=30,
            log_message=(
                "Using writer model '%s' for chapter generation."
                % models.get("generation")
            ),
        )

        if isinstance(saga_outline, dict):
            outline_data = saga_outline
        else:
            outline_data = _extract_json_payload(str(saga_outline))

        chapter_plan_data = chapter_plan if isinstance(chapter_plan, dict) else None
        saga_title = (
            (story_title or "").strip()
            or str(outline_data.get("saga_title", ""))
            or project.name
        )
        resolved_author = (story_author or "").strip() or "eLKA Author"

        outline_text = json.dumps(outline_data, ensure_ascii=False, indent=2)
        chapter_plan_text = (
            json.dumps(chapter_plan_data, ensure_ascii=False, indent=2)
            if chapter_plan_data
            else "No detailed chapter plan provided."
        )

        prompt_sections: List[str] = [
            "You are an expert saga author continuing a multi-chapter narrative.",
            "",
            "## Universe Context",
            full_context_string,
            "",
            "## Saga Outline",
            outline_text,
        ]

        if chapter_plan_data:
            prompt_sections.extend(
                [
                    "",
                    f"## Chapter {chapter_index} Plan",
                    chapter_plan_text,
                ]
            )

        if previous_chapter_content:
            prompt_sections.extend(
                [
                    "",
                    "## Previous Chapter Content",
                    previous_chapter_content.strip(),
                ]
            )

        prompt_sections.extend(
            [
                "",
                dedent(
                    f"""
                    ## Writing Instructions
                    - Write only the full prose for Chapter {chapter_index} of {total_chapters}.
                    - Maintain continuity with earlier chapters and foreshadow future beats only when supported by the outline.
                    - Use expressive Markdown prose suitable for publication.
                    - Do not include commentary about other chapters or meta analysis.
                    - Return only the chapter content in Markdown format.
                    """
                ).strip(),
            ]
        )

        prompt = "\n".join(prompt_sections)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=45,
            log_message="Requesting chapter content from AI adapter...",
        )

        generated_text, usage_metadata = writer_ai.generate_text(
            prompt,
            model_key=models.get("generation"),
        )
        usage_increment = _accumulate_usage(usage_metadata, tokens)
        generated_body = generated_text.strip()

        manager.update_task_field(
            celery_task_id,
            "story_content",
            generated_body,
        )

        story_directory = app_context.config.story_directory
        if saga_theme:
            saga_slug = _slugify(str(saga_theme)) or "saga"
            story_directory = story_directory / saga_slug
        document, relative_path, display_title = _build_chapter_document(
            project,
            saga_title=saga_title,
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            chapter_plan=chapter_plan_data,
            author=resolved_author,
            generated_body=generated_body,
            story_directory=story_directory,
        )

        git_adapter = app_context.create_git_adapter(project)
        archivist = ArchivistEngine(
            git_adapter=git_adapter,
            ai_adapter=writer_ai,
            config=app_context.config,
            model_overrides=models,
        )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=65,
            log_message="Archiving generated chapter and updating lore metadata...",
        )

        archive_result = archivist.archive(
            document,
            story_file_path=project_path / relative_path,
            universe_context=full_context_string,
            task_id=task_db_id,
            saga_theme=saga_theme,
        )

        files_to_commit = dict(archive_result.files)
        commit_message = f"Add saga chapter {chapter_index}: {display_title}"

        result_payload: Dict[str, Any] = {
            "content": document,
            "title": display_title,
            "chapter_index": chapter_index,
            "total_chapters": total_chapters,
            "files": files_to_commit,
            "metadata": archive_result.metadata,
            "commit_message": commit_message,
            "approval_required": True,
            "saga_theme": saga_theme,
            "changed_paths": archive_result.changed_paths,
        }

        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=(
                "Chapter %s/%s archived and awaiting approval for commit to %s."
                % (chapter_index, total_chapters, manager.config.default_branch)
            ),
            result=result_payload,
            input_tokens=usage_increment["input"],
            output_tokens=usage_increment["output"],
        )

        return result_payload
    except Exception as exc:  # pragma: no cover - defensive logging
        if isinstance(exc, Retry):
            raise
        logger.exception("generate_chapter_task failed: %s", exc)
        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
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
    story_title: str | None = None,
    story_author: str | None = None,
    parent_task_id: int | None = None,
) -> None:
    """Plan a saga and sequentially generate each chapter."""

    if chapters < 1:
        raise ValueError("Saga must contain at least one chapter.")

    from app.services.task_manager import TaskManager

    manager = TaskManager()
    celery_task_id = self.request.id
    models = manager.get_project_ai_models(project_id)
    validator_ai, writer_ai = get_ai_adapters(
        app_context.config,
        project_id=project_id,
    )
    tokens = {"input": 0, "output": 0}
    _ = parent_task_id

    manager.update_task_status(
        celery_task_id,
        TaskStatus.RUNNING,
        progress=5,
        log_message=(
            f"Task {task_db_id}: planning a {chapters}-part saga for theme '{theme}'."
        ),
    )

    try:
        project = app_context.git_manager.get_project_from_db(project_id)
        project_path = Path(app_context.git_manager.resolve_project_path(project))

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=15,
            log_message="Gathering universe context for saga planning...",
        )

        full_context_string = _load_full_universe_context(project_path, project_id)

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=25,
            log_message=(
                "Generating saga outline with planning model '%s'."
                % models.get("planning")
            ),
        )

        planning_prompt = dedent(
            f"""
            You are designing an epic saga set within the established universe context.

            ## Universe Context
            {full_context_string}

            Craft a cohesive saga inspired by the theme "{theme}" that spans exactly {chapters} chapters.
            Respond strictly in JSON with the following structure:
            {{
              "saga_title": "...",
              "logline": "...",
              "chapters": [
                {{
                  "index": 1,
                  "title": "...",
                  "summary": "...",
                  "key_events": ["...", "..."]
                }}
              ]
            }}

            Each chapter summary must reference previous developments to maintain continuity.
            """
        ).strip()

        planner_response, usage_metadata = writer_ai.generate_text(
            planning_prompt,
            model_key=models.get("planning"),
        )
        manager.update_task_field(
            celery_task_id,
            "saga_plan",
            planner_response,
        )
        planning_increment = _accumulate_usage(usage_metadata, tokens)
        tokens = {
            "input": planning_increment.get("input", 0),
            "output": planning_increment.get("output", 0),
        }

        outline_data = _extract_json_payload(planner_response)
        chapters_data = outline_data.get("chapters")
        if not isinstance(chapters_data, list) or not chapters_data:
            raise ValueError("Planner response did not include any chapters")

        total_chapters = len(chapters_data)
        if total_chapters != chapters:
            logger.warning(
                "Planner produced %s chapters but %s were requested; proceeding with planner output.",
                total_chapters,
                chapters,
            )

        manager.update_task_status(
            celery_task_id,
            TaskStatus.RUNNING,
            progress=45,
            log_message=f"Saga outline prepared with {total_chapters} chapter(s).",
            result={
                "saga_outline": outline_data,
                "planner_raw": planner_response,
            },
            input_tokens=planning_increment["input"],
            output_tokens=planning_increment["output"],
        )

        saga_title_resolved = (
            (story_title or "").strip()
            or str(outline_data.get("saga_title", ""))
            or project.name
        )
        saga_author_resolved = (story_author or "").strip() or "eLKA Author"

        previous_content: Optional[str] = None
        chapter_results: List[Dict[str, Any]] = []
        story_filenames: List[str] = []

        for index, chapter_plan in enumerate(chapters_data, start=1):
            _wait_while_paused(task_db_id)
            if _get_current_status(task_db_id) == TaskStatus.PAUSED:
                logger.info("Saga task %s paused before chapter %s.", task_db_id, index)
                break

            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                progress=45 + int(40 * index / max(total_chapters, 1)),
                log_message=f"Starting generation for chapter {index}/{total_chapters}.",
            )

            params = {
                "project_id": project.id,
                "chapter_index": index,
                "total_chapters": total_chapters,
                "saga_outline": outline_data,
                "chapter_plan": chapter_plan,
                "story_title": saga_title_resolved,
                "story_author": saga_author_resolved,
                "previous_chapter_content": previous_content,
                "saga_theme": theme,
            }
            if pr_id is not None:
                params["pr_id"] = pr_id
            params["parent_task_id"] = task_db_id

            chapter_task = manager.create_task(
                project_id=project.id,
                task_type=TaskType.GENERATE_CHAPTER.value,
                params=params,
                parent_task_id=task_db_id,
            )

            try:
                async_result = AsyncResult(chapter_task.celery_task_id)
                chapter_payload = async_result.get(disable_sync_subtasks=False)
            except Exception as exc:
                logger.exception(
                    "Chapter %s generation failed for saga task %s: %s",
                    index,
                    task_db_id,
                    exc,
                )
                manager.update_task_status(
                    celery_task_id,
                    TaskStatus.FAILURE,
                    log_message=(
                        f"Chapter {index} generation failed: {exc}. See child task {chapter_task.id}."
                    ),
                    result={
                        "saga_outline": outline_data,
                        "failed_chapter": index,
                        "chapters": chapter_results,
                    },
                )
                raise

            previous_content = chapter_payload.get("content")
            chapter_metadata = chapter_payload.get("metadata") or {}
            relative_path = chapter_metadata.get("relative_path")
            if isinstance(relative_path, str) and relative_path:
                story_filenames.append(relative_path)
            chapter_results.append(
                {
                    "task_id": chapter_task.id,
                    "chapter_index": index,
                    "title": chapter_payload.get("title")
                    or str(chapter_plan.get("title", f"Chapter {index}")),
                    "approval_required": True,
                    "commit_message": chapter_payload.get("commit_message"),
                }
            )

            manager.update_task_status(
                celery_task_id,
                TaskStatus.RUNNING,
                log_message=(
                    f"Chapter {index}/{total_chapters} completed via task {chapter_task.id}."
                ),
                result={"chapters": chapter_results},
            )

        if _get_current_status(task_db_id) == TaskStatus.PAUSED:
            logger.info("Saga task %s paused after chapter loop.", task_db_id)
            return

        final_result = {
            "saga_outline": outline_data,
            "chapters": chapter_results,
            "saga_theme": theme,
            "story_files": story_filenames,
        }
        manager.update_task_status(
            celery_task_id,
            TaskStatus.SUCCESS,
            progress=100,
            log_message=(
                "Saga generation completed. Review chapter tasks and approve to"
                f" publish changes to {manager.config.default_branch}."
            ),
            result=final_result,
        )

        if story_filenames:
            first_story = story_filenames[0]
            remaining_stories = story_filenames[1:]
            manager.update_task_status(
                celery_task_id,
                TaskStatus.SUCCESS,
                log_message=(
                    "Starting sequential Universe Consistency Engine processing for"
                    f" generated chapters beginning with '{first_story}'."
                ),
                result={"story_files": story_filenames},
            )
            uce_process_story_task.apply_async(
                args=[task_db_id],
                kwargs={
                    "project_id": project.id,
                    "story_text": None,
                    "apply": True,
                    "story_file_path": first_story,
                    "saga_theme": theme,
                    "remaining_story_filenames": remaining_stories,
                    "parent_task_id": task_db_id,
                },
            )
    except Exception as exc:  # pragma: no cover - defensive logging
        if isinstance(exc, Retry):
            raise
        logger.exception("generate_saga_task failed: %s", exc)
        input_tokens = tokens.get("input") if isinstance(tokens, dict) else None
        output_tokens = tokens.get("output") if isinstance(tokens, dict) else None

        manager.update_task_status(
            celery_task_id,
            TaskStatus.FAILURE,
            log_message=f"Task {task_db_id} failed: {exc}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        raise


__all__ = [
    "uce_process_story_task",
    "generate_story_from_seed_task",
    "process_story_task",
    "generate_chapter_task",
    "generate_saga_task",
]
