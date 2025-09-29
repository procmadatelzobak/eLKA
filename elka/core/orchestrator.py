from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from elka.adapters.ai.base import BaseAIAdapter
from elka.adapters.git.base import BaseGitAdapter
from elka.core.archivist import ArchivistEngine
from elka.core.validator import ValidatorEngine

if TYPE_CHECKING:
    from elka.utils.config import Config


class Orchestrator:
    """Central orchestrator for coordinating agent components."""

    def __init__(
        self,
        config: "Config",
        ai_adapter: BaseAIAdapter,
        git_adapter: BaseGitAdapter,
    ) -> None:
        self.config = config
        self.ai_adapter = ai_adapter
        self.git = git_adapter
        self.logger = logging.getLogger(__name__)

        self.validator = ValidatorEngine(ai_adapter=ai_adapter, config=config)
        self.archivist = ArchivistEngine(ai_adapter=ai_adapter, config=config)

        core_config = config.core or {}
        self.main_branch = core_config.get("main_branch", "master")
        self.repo_root = Path(__file__).resolve().parents[2]

    def process_pull_request(self, pr_id: int) -> None:
        """Process the pull request with the given identifier."""
        self.logger.info("Spouštím zpracování PR #%s", pr_id)

        pr_files = self.git.get_pr_files(pr_id)
        new_files = [item for item in pr_files if item.get("status") == "added"]

        if len(new_files) != 1:
            comment_lines = [
                "Ahoj! Tento PR musí obsahovat přesně jeden nový soubor s příběhem.",
                f"Aktuálně jsem našel {len(new_files)} nových souborů.",
                "Prosím uprav PR tak, aby obsahoval pouze jeden nový příběh.",
            ]
            self.git.post_comment_on_pr(pr_id, "\n".join(comment_lines))
            self.logger.warning("PR #%s obsahuje %s nových souborů, očekáván 1.", pr_id, len(new_files))
            return

        story_path = new_files[0]["filename"]
        story_full_path = self.repo_root / story_path

        try:
            story_content = story_full_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            message = (
                "Nepodařilo se načíst nový příběh z PR – soubor neexistuje v pracovním adresáři. "
                "Ověř, prosím, že PR větev je synchronizovaná."
            )
            self.git.post_comment_on_pr(pr_id, message)
            self.logger.exception("Soubor s příběhem %s nebyl nalezen.", story_path)
            return

        try:
            universe_files = self._load_universe_files(exclude_path=story_path)
        except RuntimeError as exc:
            message = (
                "Nepodařilo se načíst soubory z hlavní větve. Bez kompletního kánonu nemohu validovat. "
                f"Technický detail: {exc}"
            )
            self.git.post_comment_on_pr(pr_id, message)
            self.logger.exception("Chyba při načítání kánonu z větve %s", self.main_branch)
            return

        validation_result = self.validator.validate(story_content, universe_files)

        if validation_result.get("passed", False):
            self.logger.info("PR #%s prošel všemi validačními kroky.", pr_id)

            try:
                archive_updates = self.archivist.archive(story_content, universe_files)
            except Exception as exc:  # pragma: no cover - ochrana proti selhání AI
                message = (
                    "Validace příběhu proběhla, ale během archivace došlo k chybě. "
                    f"Prosím kontaktuj administrátora. Detail: {exc}"
                )
                self.git.post_comment_on_pr(pr_id, message)
                self.logger.exception("Archivace příběhu %s selhala.", story_path)
                return

            files_to_commit = dict(archive_updates)
            files_to_commit[story_path] = story_content

            story_title = self._extract_story_title(story_content)
            changed_count = len(files_to_commit)
            commit_message = (
                f"eLKA: Integrován příběh '{story_title}' a aktualizováno {changed_count} souborů."
            )

            try:
                self.git.update_pr_branch(pr_id, files_to_commit, commit_message)
            except Exception as exc:  # pragma: no cover - závislé na Git API
                message = (
                    "Archivační krok selhal při zapisování do větve. "
                    f"Technický detail: {exc}"
                )
                self.git.post_comment_on_pr(pr_id, message)
                self.logger.exception("Aktualizace větve PR #%s selhala.", pr_id)
                return

            self.git.post_comment_on_pr(
                pr_id,
                (
                    "Validace úspěšná. Databázové soubory byly vygenerovány a přidány do tohoto PR. "
                    "Nyní je připraven k revizi komunitou."
                ),
            )
            return

        errors = validation_result.get("errors", [])
        comment_parts = [
            "Ahoj! Při validaci nového příběhu jsem narazil na problémy:",
        ]
        for error in errors:
            comment_parts.append(f"- {error}")

        self.git.post_comment_on_pr(pr_id, "\n".join(comment_parts))
        self.logger.info("PR #%s neprošel validací. Počet chyb: %s", pr_id, len(errors))

    # ------------------------------------------------------------------
    # Helpers

    def _load_universe_files(self, exclude_path: str | None = None) -> Dict[str, str]:
        file_paths = self._list_branch_files(self.main_branch)
        universe_files: Dict[str, str] = {}
        for path in file_paths:
            if exclude_path and path == exclude_path:
                continue
            try:
                universe_files[path] = self.git.get_file_content(path, self.main_branch)
            except Exception as exc:  # pragma: no cover - závislé na Git API
                raise RuntimeError(f"Načtení souboru {path} z větve {self.main_branch} selhalo: {exc}") from exc
        return universe_files

    def _list_branch_files(self, branch: str) -> List[str]:
        try:
            result = subprocess.run(
                ["git", "ls-tree", "-r", branch, "--name-only"],
                check=True,
                capture_output=True,
                text=True,
                cwd=self.repo_root,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git ls-tree selhalo: {exc}") from exc

        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return files

    @staticmethod
    def _extract_story_title(story_content: str) -> str:
        for line in story_content.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip().lower() == "nazev":
                return value.strip() or "Neznámý příběh"
        return "Neznámý příběh"


