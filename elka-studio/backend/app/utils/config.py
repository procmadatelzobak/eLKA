"""Configuration helper for eLKA Studio core services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class Config:
    """Application configuration focused on lore processing utilities."""

    projects_dir: Path = Path("~/.elka/projects").expanduser()
    default_branch: str = "main"
    story_directory: Path = Path("lore/stories")
    story_extension: str = ".md"
    ai_model: str = "stub-model"

    def __post_init__(self) -> None:
        self.projects_dir = Path(os.getenv("ELKA_PROJECTS_DIR", self.projects_dir)).expanduser()
        self.default_branch = os.getenv("ELKA_DEFAULT_BRANCH", self.default_branch)
        story_dir = os.getenv("ELKA_STORY_DIR")
        if story_dir:
            self.story_directory = Path(story_dir)
        story_extension = os.getenv("ELKA_STORY_EXTENSION")
        if story_extension:
            if not story_extension.startswith("."):
                story_extension = f".{story_extension}"
            self.story_extension = story_extension
        self.ai_model = os.getenv("ELKA_AI_MODEL", self.ai_model)

    def story_filename(self, prefix: str | None = None) -> str:
        """Return a timestamped filename for a story using the configured extension."""

        base = prefix or "story"
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        return f"{base}-{timestamp}{self.story_extension}"

    def ensure_story_directory(self, project_path: Path) -> Path:
        """Ensure the story directory exists for the given project."""

        target = Path(project_path) / self.story_directory
        target.mkdir(parents=True, exist_ok=True)
        return target

    def story_path(self, project_path: Path, filename: str) -> Path:
        """Build an absolute path for a story file within the project."""

        return self.ensure_story_directory(project_path) / filename


__all__ = ["Config"]
