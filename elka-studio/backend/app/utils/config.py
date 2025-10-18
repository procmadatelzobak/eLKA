"""Configuration helpers for eLKA Studio.

This module exposes two levels of helpers:

* :func:`load_config` which returns the raw mapping loaded from ``config.yml``
  (or ``config.yaml``) when it exists.
* :class:`Config`, a lightweight convenience wrapper providing higher-level
  accessors used across Celery tasks and adapters.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.utils.filesystem import sanitize_filename


logger = logging.getLogger(__name__)

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

    def get_ai_model_aliases(self) -> Dict[str, str]:
        """Return mapping of logical model keys to provider-specific names."""

        ai_config = self.data.get("ai", {})
        models = ai_config.get("models", {})
        if not isinstance(models, dict):
            return {}
        return {str(key): str(value) for key, value in models.items()}

    def gemini_rate_limit_rpm(self) -> int:
        """Return the configured Gemini requests-per-minute limit."""

        env_value = os.getenv("GEMINI_RATE_LIMIT_RPM")
        if env_value is not None:
            try:
                return max(int(env_value), 0)
            except ValueError:
                logger.warning(
                    "Invalid GEMINI_RATE_LIMIT_RPM value '%s'; falling back to default.",
                    env_value,
                )

        ai_config = self.data.get("ai", {})
        adapters = ai_config.get("adapters", {})
        if isinstance(adapters, dict):
            gemini_settings = adapters.get("gemini", {})
            if isinstance(gemini_settings, dict):
                raw_value = gemini_settings.get("rate_limit_rpm")
                if raw_value is not None:
                    try:
                        return max(int(raw_value), 0)
                    except (TypeError, ValueError):
                        logger.warning(
                            "Invalid gemini.rate_limit_rpm value '%s'; using default.",
                            raw_value,
                        )

        return 60

    def resolve_model_name(self, model_key: str) -> str:
        """Translate a model key (e.g. ``gemini-pro``) to a provider model name."""

        if not model_key:
            return model_key
        aliases = self.get_ai_model_aliases()
        return aliases.get(model_key, model_key)

    def get_default_adapter(self) -> str:
        """Return the default AI adapter name derived from configuration."""

        ai_config = self.data.get("ai", {})
        configured = str(ai_config.get("default_adapter", "")).strip().lower()
        if configured in {"gemini", "heuristic"}:
            if configured == "gemini" and not self.get_gemini_api_key():
                logger.warning(
                    "Configured default adapter 'gemini' but no API key is available; falling back to 'heuristic'."
                )
                return "heuristic"
            return configured

        provider = self.ai_provider()
        return provider or "heuristic"

    def get_model_key_for_task(self, task_type: str) -> str:
        """Return the configured model key for the given task type."""

        tasks_config = self.data.get("tasks", {})
        if isinstance(tasks_config, dict):
            task_settings = tasks_config.get(task_type)
            if isinstance(task_settings, dict):
                model_key = str(task_settings.get("model", "")).strip()
                if model_key:
                    return model_key
            if task_type == "seed_generation":
                generation_settings = tasks_config.get("generation")
                if isinstance(generation_settings, dict):
                    model_key = str(generation_settings.get("model", "")).strip()
                    if model_key:
                        return model_key
                raise KeyError("seed_generation")

        provider = self.ai_provider()
        if provider != "gemini":
            return "heuristic"

        defaults = {
            "generation": "gemini-flash",
            "seed_generation": "gemini-pro",
            "extraction": "gemini-flash",
            "validation": "gemini-flash",
            "planning": "gemini-pro",
            "generate_chapter": "gemini-pro",
        }
        if task_type == "seed_generation":
            return defaults.get("seed_generation", defaults["generation"])
        return defaults.get(task_type, "gemini-pro")

    def get_model_name_for_task(self, task_type: str) -> str:
        """Return the provider-specific model name for a given task type."""

        model_key = self.get_model_key_for_task(task_type)
        if model_key == "heuristic":
            return "heuristic"
        return self.resolve_model_name(model_key)

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
