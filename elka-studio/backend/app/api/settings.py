"""API endpoints for managing backend configuration values."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from ruamel.yaml import YAML

from app.utils.config import Config, find_config_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


class AiSettingsUpdate(BaseModel):
    """Payload for updating AI settings via the API."""

    default_adapter: str


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
