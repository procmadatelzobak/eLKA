"""Project-related API endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.project import Project

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/", summary="List projects")
def list_projects(session: Session = Depends(get_session)) -> List[dict]:
    """Return all projects registered in the database."""
    projects = session.query(Project).all()
    return [project.to_dict() for project in projects]


@router.get("/{project_id}", summary="Get a project by ID")
def get_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    """Retrieve a single project or return 404 if it doesn't exist."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project.to_dict()
