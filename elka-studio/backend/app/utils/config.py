"""Utility helpers for loading eLKA Studio configuration files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


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


__all__ = ["find_config_file", "load_config"]
