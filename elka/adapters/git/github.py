"""Implementace GitHub adaptéru pro práci s GitHub API."""

from __future__ import annotations

from typing import Dict, List

from github import Github, InputGitTreeElement
from github.Repository import Repository

from .base import BaseGitAdapter


class GitHubAdapter(BaseGitAdapter):
    """GitHub adaptér založený na PyGithub."""

    def __init__(self, repo_url: str, token: str) -> None:
        super().__init__(repo_url, token)
        self.client = Github(token)
        normalized = repo_url.strip("/")
        if not normalized:
            raise ValueError("Repozitářní URL musí být ve formátu 'owner/repo'.")
        self.repository: Repository = self.client.get_repo(normalized)

    def get_pr_files(self, pr_id: int) -> List[Dict[str, str]]:
        pr = self.repository.get_pull(pr_id)
        return [{"filename": file.filename, "status": file.status} for file in pr.get_files()]

    def get_file_content(self, file_path: str, branch: str) -> str:
        content_file = self.repository.get_contents(file_path, ref=branch)
        return content_file.decoded_content.decode("utf-8")

    def post_comment_on_pr(self, pr_id: int, comment: str) -> None:
        pr = self.repository.get_pull(pr_id)
        pr.create_issue_comment(comment)

    def update_pr_branch(
        self,
        pr_id: int,
        files_to_commit: Dict[str, str],
        commit_message: str,
    ) -> None:
        if not files_to_commit:
            return

        pr = self.repository.get_pull(pr_id)
        head_repo: Repository = pr.head.repo
        branch_ref = head_repo.get_git_ref(f"heads/{pr.head.ref}")
        last_commit = head_repo.get_git_commit(branch_ref.object.sha)

        tree_elements = []
        for path, content in files_to_commit.items():
            element = InputGitTreeElement(
                path=path,
                mode="100644",
                type="blob",
                content=content,
            )
            tree_elements.append(element)

        new_tree = head_repo.create_git_tree(tree_elements, base_tree=last_commit.tree)
        new_commit = head_repo.create_git_commit(commit_message, new_tree, [last_commit])
        branch_ref.edit(new_commit.sha)
