"""API endpoints for managing backend configuration values."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from ruamel.yaml import YAML
from sqlalchemy.orm import Session

from app.core.context import app_context
from app.db.session import get_session
from app.models.project import Project, Setting
from app.services.project_settings import (
    MODEL_SETTING_KEYS,
    fetch_project_ai_settings,
    resolve_project_ai_models,
)
from app.utils.config import Config, find_config_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])
project_settings_router = APIRouter(prefix="/projects", tags=["project-settings"])

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


class AiSettingsUpdate(BaseModel):
    """Payload for updating AI settings via the API."""

    default_adapter: str


class ProjectAIModelUpdate(BaseModel):
    """Payload for updating per-project AI model overrides."""

    extraction: str | None = None
    validation: str | None = None
    generation: str | None = None
    planning: str | None = None

    class Config:
        extra = "forbid"


def _ensure_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _serialize_project_ai_settings(session: Session, project_id: int) -> dict[str, str]:
    overrides = fetch_project_ai_settings(session, project_id)
    resolved = resolve_project_ai_models(app_context.config, overrides)
    return resolved


def _resolve_config_path() -> Path | None:
    path = find_config_file()
    if path:
        return path
    return None


def _load_config_data(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.load(handle) or {}
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid configuration structure.",
        )
    return data


@router.get("/ai", summary="Retrieve AI adapter settings")
def get_ai_settings() -> Dict[str, str]:
    """Return the currently configured default AI adapter."""

    config_path = _resolve_config_path()
    config = Config()
    adapter = config.get_default_adapter()

    response = {"default_adapter": adapter}
    if config_path is not None:
        response["config_path"] = str(config_path)
    return response


@router.post("/ai", summary="Update AI adapter settings")
def update_ai_settings(payload: AiSettingsUpdate) -> Dict[str, str]:
    """Persist a new default AI adapter to ``config.yml``."""

    normalised = payload.default_adapter.strip().lower()
    if normalised not in {"gemini", "heuristic"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_adapter must be either 'gemini' or 'heuristic'.",
        )

    config_path = _resolve_config_path()
    if config_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="config.yml not found. Create a configuration file before updating settings.",
        )

    data = _load_config_data(config_path)
    ai_config = data.setdefault("ai", {})
    ai_config["default_adapter"] = normalised

    with config_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)

    logger.info(
        "Default AI adapter updated to '%s' via API. Restart the backend to apply changes.",
        normalised,
    )

    return {
        "default_adapter": normalised,
        "message": "Adapter updated. Restart the backend to apply changes.",
    }


@project_settings_router.get(
    "/{project_id}/settings/ai-models",
    summary="Retrieve AI model overrides for a project",
)
def get_project_ai_models(
    project_id: int, session: Session = Depends(get_session)
) -> dict[str, str]:
    """Return the effective AI model mapping for the requested project."""

    _ensure_project(session, project_id)
    return _serialize_project_ai_settings(session, project_id)


@project_settings_router.put(
    "/{project_id}/settings/ai-models",
    summary="Update AI model overrides for a project",
)
def update_project_ai_models(
    project_id: int,
    payload: ProjectAIModelUpdate,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Persist project-level AI model overrides and return the updated mapping."""

    _ensure_project(session, project_id)
    dump_method = getattr(payload, "model_dump", None)
    updates = (
        dump_method(exclude_unset=True)
        if callable(dump_method)
        else payload.dict(exclude_unset=True)
    )

    if updates:
        existing = {
            setting.key: setting
            for setting in session.query(Setting)
            .filter(
                Setting.project_id == project_id,
                Setting.key.in_(MODEL_SETTING_KEYS.values()),
            )
            .all()
        }

        for field, value in updates.items():
            setting_key = MODEL_SETTING_KEYS[field]
            cleaned = (value or "").strip() if value is not None else ""
            current = existing.get(setting_key)
            if cleaned:
                if current is None:
                    current = Setting(
                        project_id=project_id, key=setting_key, value=cleaned
                    )
                    session.add(current)
                else:
                    current.value = cleaned
            else:
                if current is not None:
                    session.delete(current)

        session.commit()

    return _serialize_project_ai_settings(session, project_id)
