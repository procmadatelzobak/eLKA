"""Project-related API endpoints."""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse

import git
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from ..db.session import get_session
from ..models.project import Project
from ..models.task import Task, TaskStatus
from ..services.git_manager import GitManager
from ..tasks import uce_process_story_task
from ..utils.config import load_config
from ..utils.filesystem import sanitize_filename
from ..utils.security import decrypt, encrypt, get_secret_key

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


def _resolve_project_and_token(
    project_id: int, session: Session = Depends(get_session)
) -> Tuple[Project, str | None]:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    token: str | None = None
    if project.git_token:
        try:
            secret_key = get_secret_key()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        try:
            token = decrypt(project.git_token, secret_key)
        except Exception as exc:  # pragma: no cover - defensive branch
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt Git token: {exc}",
            ) from exc

    return project, token


def _resolve_project(
    project_id: int, session: Session = Depends(get_session)
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return project


def _build_file_tree(root: Path, current: Path | None = None) -> List[dict[str, Any]]:
    base = current or root
    entries: List[dict[str, Any]] = []
    try:
        candidates = sorted(
            base.iterdir(), key=lambda path: (path.is_file(), path.name.lower())
        )
    except FileNotFoundError:
        return []

    for candidate in candidates:
        if candidate.name == ".git":
            continue

        if candidate.is_dir():
            children = _build_file_tree(root, candidate)
            entries.append(
                {
                    "name": candidate.name,
                    "type": "folder",
                    "children": children,
                }
            )
        elif candidate.is_file():
            entries.append(
                {
                    "name": candidate.name,
                    "type": "file",
                    "path": str(candidate.relative_to(root)),
                }
            )

    return entries


@router.get(
    "/{project_id}/universe-files",
    summary="List files available in a project's universe",
)
def list_universe_files(
    project_and_token: Tuple[Project, str | None] = Depends(_resolve_project_and_token),
) -> List[dict[str, Any]]:
    project, token = project_and_token

    projects_dir = _resolve_projects_dir()
    git_manager = GitManager(str(projects_dir))

    try:
        git_manager.sync_repo_hard(project, token)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - network dependent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synchronise repository: {exc}",
        ) from exc

    try:
        project_path = git_manager.resolve_project_path(project)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return _build_file_tree(project_path)


@router.post(
    "/{project_id}/import-stories",
    summary="Import multiple story files",
)
async def import_stories(
    project_id: int,
    files: List[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Persist uploaded story files and enqueue sequential UCE processing."""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be provided.",
        )

    projects_dir = _resolve_projects_dir()
    git_manager = GitManager(str(projects_dir))

    try:
        project_path = Path(git_manager.resolve_project_path(project))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    stories_path = project_path / "Stories"
    stories_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    import_batch_dir = stories_path / f"Imported_{timestamp}"
    import_batch_dir.mkdir(parents=True, exist_ok=True)

    saved_file_paths: list[str] = []

    for upload in files:
        original_name = upload.filename or f"imported_story_{uuid.uuid4().hex[:8]}"
        stem = sanitize_filename(Path(original_name).stem, default="imported_story")
        if not stem:
            stem = "imported_story"

        safe_filename = f"{stem}.md"
        destination_path = import_batch_dir / safe_filename
        suffix_counter = 1
        while destination_path.exists():
            destination_path = import_batch_dir / f"{stem}_{suffix_counter}.md"
            suffix_counter += 1

        try:
            with destination_path.open("wb") as buffer:
                shutil.copyfileobj(upload.file, buffer)
            saved_file_paths.append(str(destination_path.relative_to(project_path)))
        except Exception as exc:  # pragma: no cover - filesystem dependent
            logger.error(
                "Failed to save imported file %s: %s",
                upload.filename or original_name,
                exc,
            )
            continue
        finally:
            await upload.close()

    if not saved_file_paths:
        logger.warning(
            "No valid files were saved for project %s import.",
            project_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid files were saved.",
        )

    token: str | None = None
    if project.git_token:
        try:
            secret_key = get_secret_key()
            token = decrypt(project.git_token, secret_key)
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.exception(
                "Failed to decrypt git token for project %s during import.",
                project_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to decrypt stored Git token.",
            ) from exc

    first_file_path = saved_file_paths[0]
    remaining_files = saved_file_paths[1:]
    parent_task_id = None

    logger.info(
        "Starting sequential UCE processing for %s imported files for project %s. First file: %s",
        len(saved_file_paths),
        project_id,
        first_file_path,
    )

    task_record: Task | None = None
    async_result = None
    try:
        task_record = Task(
            project_id=project_id,
            type="uce_process_story",
            status=TaskStatus.PENDING,
            params={
                "file_path": first_file_path,
                "remaining_story_filenames": remaining_files,
            },
            parent_task_id=parent_task_id,
        )
        session.add(task_record)
        session.flush()

        async_result = uce_process_story_task.apply_async(
            args=[task_record.id],
            kwargs={
                "project_id": project_id,
                "token": token,
                "file_path": first_file_path,
                "remaining_story_filenames": remaining_files,
                "parent_task_id": parent_task_id,
            },
        )

        task_record.celery_task_id = async_result.id
        session.add(task_record)
        session.commit()
    except Exception as exc:  # pragma: no cover - task scheduling dependent
        logger.exception(
            "Failed to schedule UCE processing for imported stories in project %s: %s",
            project_id,
            exc,
        )
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Files were saved but processing could not be scheduled.",
        ) from exc

    return {
        "message": (
            f"{len(saved_file_paths)} files uploaded and processing started."
        ),
        "import_directory": str(import_batch_dir.relative_to(project_path)),
        "task_id": task_record.id if task_record else None,
        "celery_task_id": async_result.id if async_result else None,
    }


@router.get(
    "/{project_id}/file-content",
    summary="Fetch the content of a file within a project",
)
def get_project_file_content(
    project: Project = Depends(_resolve_project),
    path: str = Query(..., description="Relative path to the requested file"),
) -> dict[str, str]:
    if not path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="path query parameter must be provided",
        )

    relative_path = Path(path)
    if relative_path.is_absolute() or any(part == ".." for part in relative_path.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path",
        )

    projects_dir = _resolve_projects_dir()
    git_manager = GitManager(str(projects_dir))

    try:
        project_path = git_manager.resolve_project_path(project)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    full_path = project_path / relative_path
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested file does not exist",
        )

    try:
        content = full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is not valid UTF-8 text: {exc}",
        ) from exc
    except OSError as exc:  # pragma: no cover - filesystem dependent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file: {exc}",
        ) from exc

    return {"content": content}


@router.post("/{project_id}/sync", summary="Synchronise a project's repository")
def sync_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    """Force the local repository to match the remote default branch."""

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

    token: str | None = None
    if project.git_token:
        try:
            secret_key = get_secret_key()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        try:
            token = decrypt(project.git_token, secret_key)
        except Exception as exc:  # pragma: no cover - defensive branch
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to decrypt Git token: {exc}",
            ) from exc

    projects_dir = _resolve_projects_dir()
    git_manager = GitManager(str(projects_dir))

    try:
        git_manager.sync_repo_hard(project, token)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pragma: no cover - network dependent
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synchronise repository: {exc}",
        ) from exc

    session.refresh(project)
    return {"detail": "Repository synchronised successfully."}


@router.post(
    "/{project_id}/reset", summary="Reset a project's universe to default scaffold"
)
def reset_project_universe(
    project_id: int, session: Session = Depends(get_session)
) -> dict:
    """Reset the project repository and delete all associated tasks."""

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
        secret_key = get_secret_key()
        token = decrypt(project.git_token, secret_key) if project.git_token else None
    except Exception as exc:
        logger.exception("Failed to decrypt token for project reset")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decrypt token: {exc}",
        ) from exc

    try:
        git_manager.reset_universe(project, token)

        tasks_to_delete = session.query(Task).filter(Task.project_id == project_id)
        tasks_to_delete.delete(synchronize_session=False)
        session.commit()

        return {"message": "Project universe reset and all tasks cleared successfully."}

    except Exception as exc:
        session.rollback()
        logger.exception("Failed to reset project universe for project %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset project universe: {exc}",
        ) from exc


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
    "list_universe_files",
    "get_project_file_content",
    "sync_project",
    "reset_project_universe",
    "import_stories",
]
