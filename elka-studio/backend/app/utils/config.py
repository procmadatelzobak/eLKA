"""Configuration helpers for eLKA Studio.

This module exposes two levels of helpers:

* :func:`load_config` which returns the raw mapping loaded from ``config.yml``
  (or ``config.yaml``) when it exists.
* :class:`Config`, a lightweight convenience wrapper providing higher-level
  accessors used across Celery tasks and adapters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.utils.filesystem import sanitize_filename

def find_config_file() -> Optional[Path]:
    """Return the first configuration file discovered for the application."""
    env_path = os.getenv("ELKA_CONFIG_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate

    for parent in Path(__file__).resolve().parents:
        config_path = parent / "config.yml"
        if config_path.is_file():
            return config_path
        alt_path = parent / "config.yaml"
        if alt_path.is_file():
            return alt_path

    return None


def load_config() -> Dict[str, Any]:
    """Load the application configuration from disk if available."""
    config_file = find_config_file()
    if not config_file:
        return {}

    with config_file.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return data


@dataclass(slots=True)
class Config:
    """High-level accessor for common configuration values.

    The wrapper keeps the raw configuration mapping accessible while exposing
    convenience properties with sensible defaults. This allows Celery workers
    and other background services to share the same configuration handling as
    the FastAPI application without duplicating parsing logic.
    """

    data: Dict[str, Any] = field(default_factory=load_config)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Return the value stored under ``key`` in the raw mapping."""

        return self.data.get(key, default)

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------
    @property
    def projects_dir(self) -> Path:
        """Absolute path where local Git projects are stored."""

        storage_config = self.data.get("storage", {})
        path_value = storage_config.get("projects_dir", "~/.elka/projects")
        return Path(path_value).expanduser()

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------
    @property
    def default_branch(self) -> str:
        """Fallback branch name used when the repository is detached."""

        git_config = self.data.get("git", {})
        return str(git_config.get("default_branch", "main"))

    # ------------------------------------------------------------------
    # AI helpers
    # ------------------------------------------------------------------
    @property
    def ai_model(self) -> str:
        """Identifier of the AI model used for story generation metadata."""

        ai_config = self.data.get("ai", {})

        if self.ai_provider() == "gemini":
            return self.writer_model()

        configured_model = ai_config.get("model")
        if configured_model:
            return str(configured_model)

        return "heuristic-v1"

    # ------------------------------------------------------------------
    # AI provider helpers
    # ------------------------------------------------------------------
    def get_gemini_api_key(self) -> Optional[str]:
        """Return the Gemini API key from the environment or config."""

        env_key = os.getenv("GEMINI_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()

        ai_config = self.data.get("ai", {})
        key = ai_config.get("gemini_api_key")
        if key:
            cleaned = str(key).strip()
            return cleaned or None
        return None

    def validator_model(self) -> str:
        """Return the model identifier used for validation tasks."""

        env_value = os.getenv("AI_VALIDATOR_MODEL")
        if env_value and env_value.strip():
            return env_value.strip()

        ai_config = self.data.get("ai", {})
        value = ai_config.get("validator_model")
        if value and str(value).strip():
            return str(value).strip()
        return "gemini-2.5-pro"

    def writer_model(self) -> str:
        """Return the model identifier used for content generation."""

        env_value = os.getenv("AI_WRITER_MODEL")
        if env_value and env_value.strip():
            return env_value.strip()

        ai_config = self.data.get("ai", {})
        value = ai_config.get("writer_model")
        if value and str(value).strip():
            return str(value).strip()
        return "gemini-2.5-flash"

    def ai_provider(self) -> str:
        """Return the active AI provider, defaulting to heuristic fallback."""

        env_value = os.getenv("AI_PROVIDER")
        ai_config = self.data.get("ai", {})
        provider = env_value or ai_config.get("provider")
        provider_normalised = str(provider).strip().lower() if provider else ""
        if provider_normalised not in {"gemini", "heuristic"}:
            provider_normalised = ""

        if provider_normalised == "gemini" and not self.get_gemini_api_key():
            return "heuristic"

        if provider_normalised:
            return provider_normalised

        if self.get_gemini_api_key():
            return "gemini"
        return "heuristic"

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------
    @property
    def secret_key(self) -> Optional[str]:
        """Secret key used for symmetric encryption of stored credentials."""

        security_config = self.data.get("security", {})
        secret = security_config.get("secret_key")
        if secret is None:
            return None
        return str(secret)

    # ------------------------------------------------------------------
    # Story archival helpers
    # ------------------------------------------------------------------
    @property
    def _story_settings(self) -> Dict[str, Any]:
        return self.data.get("stories", {})

    @property
    def story_directory(self) -> Path:
        """Relative path inside a project repository for archived stories."""

        directory_value = self._story_settings.get("directory", "stories")
        return Path(directory_value)

    @property
    def _story_extension(self) -> str:
        extension = str(self._story_settings.get("extension", ".md")).strip() or ".md"
        return extension if extension.startswith(".") else f".{extension}"

    @property
    def _timestamp_format(self) -> str:
        default_format = "%Y%m%d-%H%M%S"
        fmt = str(self._story_settings.get("timestamp_format", default_format))
        try:
            # Validate the format string by performing a dry run.
            datetime.utcnow().strftime(fmt)
        except ValueError:  # pragma: no cover - defensive branch
            return default_format
        return fmt

    def story_filename(self, prefix: str) -> str:
        """Return a sanitized filename for an archived story."""

        cleaned_prefix = sanitize_filename(prefix, default="story")
        timestamp = datetime.utcnow().strftime(self._timestamp_format)
        return f"{cleaned_prefix}-{timestamp}{self._story_extension}"

    def ensure_story_directory(self, project_path: Path | str) -> Path:
        """Create the story directory inside ``project_path`` if needed."""

        project_root = Path(project_path)
        target_directory = project_root / self.story_directory
        target_directory.mkdir(parents=True, exist_ok=True)
        return target_directory


__all__ = ["Config", "find_config_file", "load_config"]
