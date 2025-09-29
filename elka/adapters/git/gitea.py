"""Příprava Gitea adaptéru."""

from __future__ import annotations

from typing import Dict, List

from .base import BaseGitAdapter


class GiteaAdapter(BaseGitAdapter):
    """Základní kostra Gitea adaptéru."""

    def get_pr_files(self, pr_id: int) -> List[Dict[str, str]]:  # pragma: no cover - zatím neimplementováno
        # TODO: Implementovat pomocí Gitea API
        pass

    def get_file_content(self, file_path: str, branch: str) -> str:  # pragma: no cover - zatím neimplementováno
        # TODO: Implementovat pomocí Gitea API
        pass

    def post_comment_on_pr(self, pr_id: int, comment: str) -> None:  # pragma: no cover - zatím neimplementováno
        # TODO: Implementovat pomocí Gitea API
        pass

    def update_pr_branch(
        self,
        pr_id: int,
        files_to_commit: Dict[str, str],
        commit_message: str,
    ) -> None:  # pragma: no cover - zatím neimplementováno
        # TODO: Implementovat pomocí Gitea API
        pass

    def create_branch_and_commit(
        self,
        base_branch: str,
        new_branch: str,
        files_to_commit: Dict[str, str],
        commit_message: str,
    ) -> str:  # pragma: no cover - zatím neimplementováno
        # TODO: Implementovat pomocí Gitea API
        raise NotImplementedError

    def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
    ) -> str:  # pragma: no cover - zatím neimplementováno
        # TODO: Implementovat pomocí Gitea API
        raise NotImplementedError
