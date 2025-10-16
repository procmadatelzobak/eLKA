"""Task-related API endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.task import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", summary="List tasks")
def list_tasks(session: Session = Depends(get_session)) -> List[dict]:
    """Return all tasks currently tracked in the database."""
    tasks = session.query(Task).all()
    return [task.to_dict() for task in tasks]
