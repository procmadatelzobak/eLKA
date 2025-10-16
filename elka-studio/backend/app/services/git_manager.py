"""Service for managing local Git repositories for eLKA Studio projects."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

import git
from git.exc import GitCommandError


from app.db.session import SessionLocal
from app.models.project import Project
from sqlalchemy.orm import Session


class GitManager:
    """High-level helper that wraps GitPython interactions."""

    def __init__(
        self,
        projects_dir: str,
        session_factory: Callable[[], Session] = SessionLocal,
    ):
        self.projects_dir = Path(projects_dir).expanduser()
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._session_factory = session_factory

    def clone_repo(self, git_url: str, project_name: str, token: str | None) -> Path:
        """Clone a repository into the managed projects directory."""
        target_name = self._normalize_project_name(project_name)
        target_path = self.projects_dir / target_name
        if target_path.exists():
            raise FileExistsError(f"Project path already exists: {target_path}")

        command = ["git", "clone", git_url, str(target_path)]
        env = self._build_git_env(token)

        if token:
            helper_path = Path(__file__).parent / "git_credential_helper.sh"
            command = [
                "git",
                "-c",
                f"credential.helper=!sh {helper_path.resolve()}",
                "clone",
                git_url,
                str(target_path),
            ]

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - network interaction
            message = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"Failed to clone repository: {message}") from exc
        return target_path

    def _initialize_empty_repo(
        self, repo_path: Path, scaffold_path: Path, token: str | None
    ) -> None:
        """Populate an empty repository with the default universe scaffold."""
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")
        if not scaffold_path.is_dir():
            raise FileNotFoundError(f"Scaffold path does not exist: {scaffold_path}")

        repo = git.Repo(repo_path)
        for source in scaffold_path.rglob("*"):
            relative = source.relative_to(scaffold_path)
            destination = repo_path / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

        branch_name = self._determine_branch(repo)
        if branch_name in {head.name for head in repo.heads}:
            repo.git.checkout(branch_name)
        else:
            repo.git.checkout("--orphan", branch_name)

        self._ensure_identity(repo)
        repo.git.add(all=True)
        repo.index.commit("Initialize universe scaffold")

        command = [
            "git",
            "-C",
            str(repo_path),
            "push",
            "origin",
            f"{branch_name}:{branch_name}",
        ]
        env = self._build_git_env(token)

        if token:
            helper_path = Path(__file__).parent / "git_credential_helper.sh"
            command = [
                "git",
                "-c",
                f"credential.helper=!sh {helper_path.resolve()}",
                "-C",
                str(repo_path),
                "push",
                "origin",
                f"{branch_name}:{branch_name}",
            ]

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - network interaction
            message = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"Failed to push repository scaffold: {message}") from exc

    def pull_updates(self, project_name: str) -> None:
        """Pull the latest changes from the remote default branch."""
        target_name = self._normalize_project_name(project_name)
        repo_path = self.projects_dir / target_name
        if not repo_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {repo_path}")

        repo = git.Repo(repo_path)
        branch_name = self._determine_branch(repo)
        origin = repo.remote(name="origin")
        origin.fetch()

        try:
            repo.git.checkout(branch_name)
        except GitCommandError:
            repo.git.checkout("-b", branch_name, f"origin/{branch_name}")

        origin.pull(branch_name)

    @staticmethod
    def _normalize_project_name(project_name: str) -> str:
        normalized = project_name.strip()
        if not normalized:
            raise ValueError("Project name must not be empty")
        if normalized in {".", ".."}:
            raise ValueError("Project name cannot be '.' or '..'")
        if any(sep in normalized for sep in (os.sep, os.altsep) if sep):
            raise ValueError("Project name must not contain path separators")
        return normalized

    @staticmethod
    def _build_git_env(token: str | None) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_ASKPASS"] = "true"
        env["GIT_TERMINAL_PROMPT"] = "0"
        if token:
            env["GIT_TOKEN"] = token
        else:
            env.pop("GIT_TOKEN", None)
        return env

    @staticmethod
    def _determine_branch(repo: git.Repo) -> str:
        branch = "main"
        try:
            origin = repo.remote(name="origin")
        except ValueError:
            origin = None
        if origin is not None:
            remote_heads = {ref.remote_head for ref in origin.refs if getattr(ref, "remote_head", None)}
            if "main" in remote_heads:
                branch = "main"
            elif "master" in remote_heads:
                branch = "master"
        try:
            active = repo.active_branch.name
        except (TypeError, GitCommandError, AttributeError):
            active = None
        if active:
            branch = active
        return branch

    @staticmethod
    def _ensure_identity(repo: git.Repo) -> None:
        reader = repo.config_reader()
        needs_update = False
        try:
            reader.get_value("user", "name")
            reader.get_value("user", "email")
        except (configparser.NoSectionError, configparser.NoOptionError, KeyError):
            needs_update = True
        if needs_update:
            with repo.config_writer() as writer:
                writer.set_value("user", "name", "eLKA Studio")
                writer.set_value("user", "email", "studio@elka.local")

    # ------------------------------------------------------------------
    # Helpers exposed to Celery workers
    # ------------------------------------------------------------------
    def get_project_from_db(self, project_id: int) -> Project:
        """Load a project record from the database and detach it from the session."""

        session = self._session_factory()
        try:
            project = (
                session.query(Project)
                .filter(Project.id == project_id)
                .one_or_none()
            )
            if project is None:
                raise ValueError(f"Project with id {project_id} does not exist")
            session.expunge(project)
            return project
        finally:
            session.close()

    def resolve_project_path(self, project: Project) -> Path:
        """Return the local filesystem path for ``project``.

        The path is resolved using the stored ``local_path`` when available. If
        the project has not been synchronised yet, fall back to the configured
        projects directory combined with the normalised project name.
        """

        if project.local_path:
            candidate = Path(project.local_path).expanduser()
        else:
            candidate = self.projects_dir / self._normalize_project_name(project.name)

        if not candidate.exists():
            raise FileNotFoundError(
                f"Project path '{candidate}' does not exist. Synchronise the project before retrying."
            )
        return candidate

    def load_universe_files(
        self,
        project_path: Path | str,
        *,
        suffixes: Iterable[str] = (".md", ".markdown", ".txt", ".json", ".yaml", ".yml"),
    ) -> dict[str, str]:
        """Return a mapping of relative file paths to their textual contents.

        The helper is primarily used by Celery workers to supply contextual
        information to validation and archival services. Binary files are
        skipped silently.
        """

        root = Path(project_path).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"Project path '{root}' does not exist")

        allowed_suffixes = {suffix.lower() for suffix in suffixes}
        contents: dict[str, str] = {}
        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            if allowed_suffixes and candidate.suffix.lower() not in allowed_suffixes:
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            relative = candidate.relative_to(root)
            contents[str(relative)] = text
        return contents


__all__ = ["GitManager"]
