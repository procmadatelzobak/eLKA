"""Identifier generation helpers."""

from __future__ import annotations

import re
from unidecode import unidecode


def generate_entity_id(entity_type: str, name: str) -> str:
    """Generate a deterministic identifier derived from ``name``."""

    normalized = unidecode(name or "").lower()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
    normalized = normalized.strip("_")[:64]
    if not normalized:
        normalized = re.sub(r"[^a-z0-9_]+", "", (entity_type or "entity").lower())
    return normalized or "entity"


__all__ = ["generate_entity_id"]
