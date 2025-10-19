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
        if (
            self._token and not self._credential_helper.is_file()
        ):  # pragma: no cover - defensive
            raise FileNotFoundError(
                f"Credential helper script not found at {self._credential_helper}"
            )
        try:
            self.repo = git.Repo(self.project_path)
        except (
            git.InvalidGitRepositoryError
        ) as exc:  # pragma: no cover - defensive branch
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

    def create_branch(
        self,
        branch: str,
        repo_path: Path | None = None,
        base: str | None = None,
    ) -> None:
        """Ensure the target branch exists and is checked out."""

        repository = git.Repo(repo_path) if repo_path else self.repo
        if base:
            available_branches = {head.name for head in repository.branches}
            if base not in available_branches:
                try:
                    repository.git.fetch("origin", base)
                    repository.git.checkout("-B", base, f"origin/{base}")
                except GitCommandError:
                    repository.git.checkout("-b", base)
            else:
                repository.git.checkout(base)
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

    def push_branch(self, branch: str | None = None) -> None:
        """Push the specified branch (or current branch) to origin."""

        target = branch or self._current_branch()
        self._push(target)

    def merge_branch(
        self,
        source_branch: str,
        target_branch: str | None = None,
        *,
        delete_source: bool = False,
    ) -> str:
        """Merge ``source_branch`` into ``target_branch`` and push the result.

        Returns the resulting merge commit SHA. When ``delete_source`` is true,
        the local and remote source branches are removed after a successful
        merge.
        """

        if self.repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            raise RuntimeError("Cannot merge branches with uncommitted changes present")

        target = target_branch or self.config.default_branch
        try:
            origin = self.repo.remote(name="origin")
        except ValueError as exc:  # pragma: no cover - remote missing
            raise RuntimeError("No 'origin' remote configured for repository") from exc
        origin.fetch()

        current_branch = self._current_branch()
        branches = {head.name for head in self.repo.branches}

        try:
            if source_branch not in branches:
                self.repo.git.fetch("origin", source_branch)
                self.repo.git.checkout("-B", source_branch, f"origin/{source_branch}")
            else:
                self.repo.git.checkout(source_branch)
                try:
                    origin.pull(source_branch)
                except GitCommandError:
                    pass

            self.repo.git.checkout(target)
            try:
                origin.pull(target)
            except GitCommandError:
                pass

            try:
                self.repo.git.merge(source_branch)
            except GitCommandError as exc:
                raise RuntimeError(
                    f"Failed to merge branch '{source_branch}' into '{target}'"
                ) from exc
            merge_commit = self.repo.head.commit.hexsha
            self._push(target)

            if delete_source:
                try:
                    self.repo.git.branch("-D", source_branch)
                except GitCommandError:
                    pass
                try:
                    origin.push(refspec=f":{source_branch}")
                except GitCommandError:
                    pass

            return merge_commit
        finally:
            try:
                self.repo.git.checkout(target)
            except GitCommandError:
                if current_branch and current_branch in {
                    head.name for head in self.repo.branches
                }:
                    try:
                        self.repo.git.checkout(current_branch)
                    except GitCommandError:
                        pass

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
        except (
            subprocess.CalledProcessError
        ) as exc:  # pragma: no cover - network interaction
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
        """Legacy helper retained for compatibility; no longer commits directly."""

        if not files:
            raise ValueError("No files supplied for update")

        written_paths = self.write_files(files)
        rel_paths: Iterable[str] = [
            str(path.relative_to(self.project_path)) for path in written_paths
        ]
        if rel_paths:
            self.repo.index.add(list(rel_paths))

        # Commit/push handled during task approval. This method intentionally avoids
        # mutating repository history to keep backwards compatibility for callers
        # expecting side effects prior to approval.


__all__ = ["GitAdapter"]
