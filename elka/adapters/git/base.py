"""Abstraktní definice rozhraní pro Git adaptéry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List


class BaseGitAdapter(ABC):
    """Základní abstraktní třída pro Git adaptéry."""

    def __init__(self, repo_url: str, token: str) -> None:
        self.repo_url = repo_url
        self.token = token

    @abstractmethod
    def get_pr_files(self, pr_id: int) -> List[Dict[str, str]]:
        """Vrátí seznam souborů v Pull Requestu."""

    @abstractmethod
    def get_file_content(self, file_path: str, branch: str) -> str:
        """Vrátí obsah jednoho souboru z dané větve."""

    @abstractmethod
    def post_comment_on_pr(self, pr_id: int, comment: str) -> None:
        """Přidá komentář k Pull Requestu."""

    @abstractmethod
    def update_pr_branch(
        self,
        pr_id: int,
        files_to_commit: Dict[str, str],
        commit_message: str,
    ) -> None:
        """Přidá nový commit do větve Pull Requestu s novými/upravenými soubory."""
