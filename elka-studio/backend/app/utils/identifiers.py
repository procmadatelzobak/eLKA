"""Identifier generation helpers."""

from __future__ import annotations

import re
import uuid

from unidecode import unidecode


def generate_entity_id(entity_type: str, name: str) -> str:
    """Generate a stable and unique identifier for an entity."""

    sanitized_name = unidecode(name).lower()
    sanitized_name = re.sub(r"\s+", "_", sanitized_name)
    sanitized_name = re.sub(r"[^a-z0-9_]+", "", sanitized_name)
    sanitized_name = sanitized_name[:30]

    short_uuid = str(uuid.uuid4())[:8]

    return f"{entity_type.lower()}_{sanitized_name}_{short_uuid}"


__all__ = ["generate_entity_id"]
