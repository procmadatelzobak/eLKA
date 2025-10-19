"""Project-related API endpoints."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import git
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.project import Project
from ..services import GitManager
from ..utils.config import load_config
from ..utils.security import encrypt, get_secret_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    """Schema for creating a new project."""

    name: str
    git_url: str
    git_token: Optional[str] = None

    @validator("name")
    def validate_name(cls, value: str) -> str:
        """Ensure the project name is usable as a directory name."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Project name must not be empty.")
        if cleaned in {".", ".."}:
            raise ValueError("Project name cannot be '.' or '..'.")
        if any(sep and sep in cleaned for sep in (os.sep, os.altsep)):
            raise ValueError("Project name must not contain path separators.")
        return cleaned

    @validator("git_url")
    def validate_git_url(cls, value: str) -> str:
        """Normalise Git URLs and allow the shorthand owner/repo form."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Git repository URL must not be empty.")

        if (
            cleaned.count("/") == 1
            and "//" not in cleaned
            and not cleaned.startswith("git@")
        ):
            owner, repo = (part.strip() for part in cleaned.split("/", 1))
            if not owner or not repo:
                raise ValueError(
                    "GitHub repository shorthand must be in the form 'owner/repository'."
                )
            return f"https://github.com/{owner}/{repo}"

        parsed = urlparse(cleaned)
        if not parsed.scheme and not cleaned.startswith("git@"):
            raise ValueError(
                "Git repository must be a full URL (https://...) or in the form 'owner/repository'."
            )
        return cleaned

    @validator("git_token", pre=True)
    def normalize_git_token(cls, value: Optional[str]) -> Optional[str]:
        """Strip empty tokens so public repositories can be imported without credentials."""
        if value is None:
            return None
        token = value.strip()
        return token or None


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return project.to_dict()


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Create a new project")
def create_project(
    payload: ProjectCreateRequest, session: Session = Depends(get_session)
) -> dict:
    """Create a project, clone its Git repository and initialise scaffolding if needed."""
    try:
        secret_key = get_secret_key()
    except RuntimeError as exc:
        logger.exception(
            "Failed to access the secret key while creating project '%s'", payload.name
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    encrypted_token = (
        encrypt(payload.git_token, secret_key) if payload.git_token else None
    )
    projects_dir = _resolve_projects_dir()
    git_manager = GitManager(str(projects_dir))
    target_path = projects_dir / GitManager._normalize_project_name(payload.name)

    project = Project(
        name=payload.name,
        git_url=payload.git_url,
        git_token=encrypted_token,
    )

    with session.begin():
        session.add(project)
        session.flush()

        try:
            local_path = git_manager.clone_repo(
                payload.git_url, payload.name, payload.git_token
            )
        except FileExistsError as exc:
            logger.error(
                "Cannot create project '%s': target path '%s' already exists",
                payload.name,
                target_path,
            )
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:  # pragma: no cover - network dependent
            logger.exception(
                "Failed to clone repository '%s' for project '%s'",
                payload.git_url,
                payload.name,
            )
            session.rollback()
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        try:
            repo = git.Repo(local_path)
        except Exception as exc:  # pragma: no cover - git inspection dependent
            logger.exception(
                "Failed to inspect cloned repository for project '%s' at '%s'",
                payload.name,
                local_path,
            )
            session.rollback()
            if Path(local_path).exists():
                shutil.rmtree(Path(local_path), ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to inspect repository: {exc}",
            ) from exc

        try:
            repo_empty = not repo.head.is_valid()
        except Exception:  # pragma: no cover - safety net for unusual git states
            repo_empty = True
        finally:
            repo.close()

        project.local_path = str(local_path)
        session.add(project)

        if repo_empty:
            scaffold_path = (
                Path(__file__).resolve().parents[1] / "templates" / "universe_scaffold"
            )
            try:
                git_manager._initialize_empty_repo(
                    Path(project.local_path), scaffold_path, payload.git_token
                )
            except Exception as exc:  # pragma: no cover - network/IO dependent
                logger.exception(
                    "Failed to scaffold initial universe for project '%s' in '%s'",
                    payload.name,
                    project.local_path,
                )
                session.rollback()
                if Path(project.local_path).exists():
                    shutil.rmtree(Path(project.local_path), ignore_errors=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to initialise repository scaffold: {exc}",
                ) from exc

    session.refresh(project)
    return project.to_dict()


@router.post("/{project_id}/sync", summary="Synchronise a project's repository")
def sync_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    """Pull the latest changes for the specified project repository."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if not project.local_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no local repository path",
        )

    local_path = Path(project.local_path)
    git_manager = GitManager(str(local_path.parent))

    try:
        git_manager.pull_updates(local_path.name)
    except Exception as exc:  # pragma: no cover - network dependent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synchronise repository: {exc}",
        ) from exc

    return project.to_dict()


def _resolve_projects_dir() -> Path:
    """Return the projects directory from configuration or fall back to defaults."""
    env_override = os.getenv("ELKA_PROJECTS_DIR")
    if env_override:
        return Path(env_override).expanduser()

    config = load_config()
    projects_dir = config.get("storage", {}).get("projects_dir")
    if projects_dir:
        return Path(projects_dir).expanduser()

    return Path("~/.elka/projects").expanduser()


__all__ = [
    "list_projects",
    "get_project",
    "create_project",
    "sync_project",
]
