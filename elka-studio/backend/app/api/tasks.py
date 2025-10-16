"""Task-related API endpoints."""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.task import Task
from ..services.task_manager import TaskManager

router = APIRouter(prefix="/tasks", tags=["tasks"])

task_manager = TaskManager()


class TaskCreateRequest(BaseModel):
    """Input payload for enqueuing a background task."""

    project_id: int
    task_type: str = Field(..., alias="type")
    params: dict[str, Any] = Field(default_factory=dict)

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

    try:
        task = task_manager.create_task(payload.project_id, payload.task_type, payload.params)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return task.to_dict()
