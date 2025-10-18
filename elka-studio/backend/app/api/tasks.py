"""Task-related API endpoints."""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.task import Task, TaskStatus
from ..services.task_manager import TaskManager

router = APIRouter(prefix="/tasks", tags=["tasks"])

task_manager = TaskManager()


class TaskCreateRequest(BaseModel):
    """Input payload for enqueuing a background task."""

    project_id: int
    task_type: str = Field(..., alias="type")
    params: dict[str, Any] = Field(default_factory=dict, description="Additional task parameters")
    seed: str | None = Field(default=None, description="Story seed for generation tasks")
    theme: str | None = Field(default=None, description="Saga theme for orchestration tasks")
    chapters: int | None = Field(
        default=None,
        ge=1,
        description="Number of chapters when generating a saga",
    )
    pr_id: int | None = Field(
        default=None,
        description="Optional pull request identifier for Git operations",
    )

    class Config:
        allow_population_by_field_name = True


@router.get("/", summary="List tasks")
def list_tasks(session: Session = Depends(get_session)) -> List[dict]:
    """Return all tasks currently tracked in the database."""
    tasks = session.query(Task).all()
    return [task.to_dict() for task in tasks]


@router.post("/", summary="Create task", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreateRequest) -> dict:
    """Create a new task and dispatch it to the background queue."""

    params = dict(payload.params)
    if payload.pr_id is not None:
        params.setdefault("pr_id", payload.pr_id)
    if payload.seed is not None:
        params.setdefault("seed", payload.seed)
    if payload.theme is not None:
        params.setdefault("theme", payload.theme)
    if payload.chapters is not None:
        params.setdefault("chapters", payload.chapters)

    if payload.task_type in {
        "generate_story",
        "generate_story_from_seed",
        "generate_story_from_seed_task",
        "generate_and_process_story_from_seed",
        "generate_and_process_story_from_seed_task",
    }:
        seed = params.get("seed")
        if not isinstance(seed, str) or not seed.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="seed must be a non-empty string",
            )
        params["seed"] = seed
    elif payload.task_type in {"generate_saga", "generate_saga_task"}:
        theme = params.get("theme")
        chapters = params.get("chapters")
        if not isinstance(theme, str) or not theme.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="theme must be a non-empty string",
            )
        if not isinstance(chapters, int) or chapters < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chapters must be a positive integer",
            )
        params["theme"] = theme
        params["chapters"] = chapters
    elif payload.task_type in {"process_story", "process_story_task"}:
        story_content = params.get("story_content")
        if not isinstance(story_content, str) or not story_content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="story_content must be a non-empty string",
            )
        params["story_content"] = story_content.strip()

    try:
        task = task_manager.create_task(payload.project_id, payload.task_type, params)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return task.to_dict()


def _update_task_status(session: Session, task_id: int, status_value: str) -> Task:
    task = session.query(Task).filter(Task.id == task_id).one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    task.status = status_value
    session.add(task)
    session.commit()
    session.refresh(task)
    task_manager.broadcast_update(task.project_id)
    return task


@router.post("/{task_id}/pause", summary="Pause a running task")
def pause_task(task_id: int, session: Session = Depends(get_session)) -> dict:
    task = _update_task_status(session, task_id, TaskStatus.PAUSED)
    return task.to_dict()


@router.post("/{task_id}/resume", summary="Resume a paused task")
def resume_task(task_id: int, session: Session = Depends(get_session)) -> dict:
    task = _update_task_status(session, task_id, TaskStatus.RUNNING)
    return task.to_dict()


@router.post("/{task_id}/approve", summary="Approve task result")
def approve_task(task_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        task = task_manager.approve_task(task_id, session=session)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive branch
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return task.to_dict()


class ProcessStoryRequest(BaseModel):
    """Payload for invoking the Universe Consistency Engine.

    ``apply`` toggles between dry-run (default) and applying the resulting
    changeset to a dedicated ``task/process-story-<task_id>`` branch. Dry-runs
    persist the diff preview in the task record without modifying the
    repository.
    """

    project_id: int = Field(..., description="Identifier of the project to process")
    story_text: str = Field(
        ..., min_length=1, description="Story text analysed for consistency"
    )
    apply: bool = Field(
        default=False,
        description="When true the changeset is committed and pushed; otherwise only a diff preview is stored.",
    )


class ProcessStoryResponse(BaseModel):
    """Response metadata for a scheduled Universe Consistency Engine run."""

    task_id: int = Field(..., description="Identifier of the persisted task record")
    celery_task_id: str = Field(..., description="Celery identifier for progress tracking")


@router.post(
    "/story/process",
    summary="Run Universe Consistency Engine",
    response_model=ProcessStoryResponse,
    description=(
        "Start a Universe Consistency Engine run for the provided story. "
        "Dry-runs capture the unified diff in `result.diff_preview` while apply runs create "
        "a `task/process-story-<task_id>` branch, push it via the configured Git adapter, and persist the `commit_sha`. "
        "The branch is merged into the default branch only after the task is approved via `/api/tasks/{task_id}/approve`. "
        "Any validation errors are surfaced through the task log and stored notes."
    ),
)
def process_story(payload: ProcessStoryRequest) -> ProcessStoryResponse:
    story_text = payload.story_text.strip()
    if not story_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="story_text must be a non-empty string",
        )

    params = {"story_text": story_text, "apply": payload.apply}
    task = task_manager.create_task(payload.project_id, "uce_process_story", params)
    return ProcessStoryResponse(task_id=task.id, celery_task_id=task.celery_task_id)


__all__ = [
    "create_task",
    "list_tasks",
    "approve_task",
    "pause_task",
    "resume_task",
    "process_story",
]
