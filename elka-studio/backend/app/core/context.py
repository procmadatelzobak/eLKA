"""Application-wide context shared with Celery workers."""

from __future__ import annotations

import logging
from threading import Lock
from typing import Optional

from app.adapters.ai.base import BaseAIAdapter, get_default_ai_adapter
from app.adapters.git.base import GitAdapter
from app.core.archivist import ArchivistEngine
from app.core.validator import ValidatorEngine
from app.models.project import Project
from app.services.git_manager import GitManager
from app.utils.config import Config
from app.utils.security import decrypt

logger = logging.getLogger(__name__)


class AppContext:
    """Singleton container for backend services shared with workers."""

    _instance: "AppContext | None" = None
    _lock: Lock = Lock()

    def __new__(cls) -> "AppContext":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialise()
        return cls._instance

    def _initialise(self) -> None:
        self.config = Config()
        self.git_manager = GitManager(self.config.projects_dir)
        self._ai_adapter: Optional[BaseAIAdapter] = None
        self._validator: Optional[ValidatorEngine] = None

    @property
    def ai_adapter(self) -> BaseAIAdapter:
        if self._ai_adapter is None:
            self._ai_adapter = get_default_ai_adapter(self.config)
        return self._ai_adapter

    @property
    def validator(self) -> ValidatorEngine:
        if self._validator is None:
            self._validator = ValidatorEngine(ai_adapter=self.ai_adapter, config=self.config)
        return self._validator

    def create_git_adapter(self, project: Project) -> GitAdapter:
        project_path = self.git_manager.resolve_project_path(project)
        token = self._resolve_git_token(project)
        return GitAdapter(project_path=project_path, config=self.config, token=token)

    def create_archivist(self, git_adapter: GitAdapter) -> ArchivistEngine:
        return ArchivistEngine(git_adapter=git_adapter, ai_adapter=self.ai_adapter, config=self.config)

    def _resolve_git_token(self, project: Project) -> str | None:
        encrypted = project.git_token
        if not encrypted:
            return None

        secret_key = self.config.secret_key
        if not secret_key:
            logger.warning(
                "Project %s has a stored Git token but no secret key is configured.",
                project.id,
            )
            return None

        try:
            return decrypt(encrypted, secret_key)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to decrypt Git token for project %s: %s", project.id, exc)
            return None


app_context = AppContext()

__all__ = ["AppContext", "app_context"]
