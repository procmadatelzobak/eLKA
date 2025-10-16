"""Git adapter used by lore processing tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import git
from git.exc import GitCommandError

from app.utils.config import Config


class GitAdapter:
    """High-level helper for staging and pushing lore updates."""

    def __init__(self, project_path: Path | str, config: Config) -> None:
        self.project_path = Path(project_path).expanduser()
        if not self.project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {self.project_path}")
        self.config = config
        try:
            self.repo = git.Repo(self.project_path)
        except git.InvalidGitRepositoryError as exc:  # pragma: no cover - defensive branch
            raise RuntimeError(f"{self.project_path} is not a git repository") from exc

    def write_files(self, files: dict[str, str]) -> list[Path]:
        """Persist the provided files inside the repository and return absolute paths."""

        written: list[Path] = []
        for relative, content in files.items():
            destination = self.project_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            written.append(destination)
        return written

    def _current_branch(self) -> str:
        try:
            return self.repo.active_branch.name
        except (TypeError, GitCommandError, AttributeError):  # detached HEAD
            return self.config.default_branch

    def _push(self, branch: str) -> None:
        try:
            remote = self.repo.remote(name="origin")
        except ValueError as exc:  # pragma: no cover - remote missing
            raise RuntimeError("No 'origin' remote configured for repository") from exc
        try:
            remote.push(refspec=f"{branch}:{branch}")
        except GitCommandError as exc:  # pragma: no cover - network interaction
            raise RuntimeError(f"Failed to push changes: {exc.stderr or exc}") from exc

    def update_pr_branch(self, files: dict[str, str], commit_message: str) -> None:
        """Write files, create a commit, and push the branch to origin."""

        if not files:
            raise ValueError("No files supplied for commit")

        written_paths = self.write_files(files)
        rel_paths: Iterable[str] = [str(path.relative_to(self.project_path)) for path in written_paths]
        self.repo.index.add(list(rel_paths))

        if not self.repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            return

        self.repo.index.commit(commit_message)
        branch = self._current_branch()
        self._push(branch)


__all__ = ["GitAdapter"]
