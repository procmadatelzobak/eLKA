"""Git adapter used by lore processing tasks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable

import git
from git.exc import GitCommandError

from app.utils.config import Config


class GitAdapter:
    """High-level helper for staging and pushing lore updates."""

    def __init__(
        self,
        project_path: Path | str,
        config: Config,
        token: str | None = None,
    ) -> None:
        self.project_path = Path(project_path).expanduser()
        if not self.project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {self.project_path}")
        self.config = config
        self._token = token
        self._credential_helper = (
            Path(__file__).resolve().parent.parent.parent
            / "services"
            / "git_credential_helper.sh"
        )
        if self._token and not self._credential_helper.is_file():  # pragma: no cover - defensive
            raise FileNotFoundError(
                f"Credential helper script not found at {self._credential_helper}"
            )
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

    def create_branch(self, branch: str, repo_path: Path | None = None) -> None:
        """Ensure the target branch exists and is checked out."""

        repository = git.Repo(repo_path) if repo_path else self.repo
        branch_names = {head.name for head in repository.branches}
        if branch in branch_names:
            repository.git.checkout(branch)
        else:
            repository.git.checkout("-b", branch)

    def apply_changeset(self, changeset) -> None:
        """Write all files contained in the provided changeset."""

        for file in changeset.files:
            destination = self.project_path / file.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(file.new, encoding="utf-8")

    def commit_all(self, message: str, author=None) -> str:
        """Commit all staged and unstaged changes and return the commit SHA."""

        self.repo.git.add(A=True)
        commit = self.repo.index.commit(message, author=author)
        return commit.hexsha

    def _current_branch(self) -> str:
        try:
            return self.repo.active_branch.name
        except (TypeError, GitCommandError, AttributeError):  # detached HEAD
            return self.config.default_branch

    def _push(self, branch: str) -> None:
        try:
            self.repo.remote(name="origin")
        except ValueError as exc:  # pragma: no cover - remote missing
            raise RuntimeError("No 'origin' remote configured for repository") from exc

        command = [
            "git",
            "-C",
            str(self.project_path),
            "push",
            "origin",
            f"{branch}:{branch}",
        ]
        if self._token:
            helper = self._credential_helper
            command = [
                "git",
                "-c",
                f"credential.helper=!sh {helper.resolve()}",
                "-C",
                str(self.project_path),
                "push",
                "origin",
                f"{branch}:{branch}",
            ]

        env = self._build_git_env()

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
            raise RuntimeError(f"Failed to push changes: {message}") from exc

    def _build_git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = "true"
        if self._token:
            env["GIT_TOKEN"] = self._token
        else:
            env.pop("GIT_TOKEN", None)
        return env

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
