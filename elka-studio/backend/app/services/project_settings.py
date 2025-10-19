"""Helpers for loading and persisting per-project AI configuration."""

from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.project import Setting
from app.utils.config import Config

MODEL_SETTING_KEYS: Dict[str, str] = {
    "extraction": "ai_model_extraction",
    "validation": "ai_model_validation",
    "generation": "ai_model_generation",
    "planning": "ai_model_planning",
}

SETTING_KEY_TO_MODEL: Dict[str, str] = {value: key for key, value in MODEL_SETTING_KEYS.items()}


def fetch_project_ai_settings(session: Session, project_id: int) -> Dict[str, str]:
    """Return raw AI model overrides stored for the given project."""

    records = (
        session.query(Setting)
        .filter(
            Setting.project_id == project_id,
            Setting.key.in_(MODEL_SETTING_KEYS.values()),
        )
        .all()
    )
    overrides: Dict[str, str] = {}
    for record in records:
        model_key = SETTING_KEY_TO_MODEL.get(record.key)
        if not model_key:
            continue
        value = (record.value or "").strip()
        if value:
            overrides[model_key] = value
    return overrides


def build_default_ai_settings(config: Config) -> Dict[str, str]:
    """Return the fallback AI model names derived from global configuration."""

    writer_model = config.writer_model()
    validator_model = config.validator_model()
    return {
        "extraction": writer_model,
        "validation": validator_model,
        "generation": writer_model,
        "planning": writer_model,
    }


def resolve_project_ai_models(config: Config, overrides: Dict[str, str]) -> Dict[str, str]:
    """Merge project overrides with global defaults and return the effective map."""

    resolved = build_default_ai_settings(config)
    for key, value in overrides.items():
        cleaned = (value or "").strip()
        if cleaned:
            resolved[key] = cleaned
    return resolved


def load_project_ai_models(config: Config, project_id: int) -> Dict[str, str]:
    """Convenience helper that loads the effective AI model map for a project."""

    session = SessionLocal()
    try:
        overrides = fetch_project_ai_settings(session, project_id)
    finally:
        session.close()
    return resolve_project_ai_models(config, overrides)


__all__ = [
    "MODEL_SETTING_KEYS",
    "fetch_project_ai_settings",
    "build_default_ai_settings",
    "resolve_project_ai_models",
    "load_project_ai_models",
]
