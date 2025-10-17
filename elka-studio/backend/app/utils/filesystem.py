"""Filesystem-related helpers."""

from __future__ import annotations

import re

_INVALID_CHARS_PATTERN = re.compile(r"[^0-9A-Za-z_-]+")


def sanitize_filename(value: str, *, default: str = "item") -> str:
    """Return a filesystem-safe representation of ``value``.

    The helper replaces spaces with underscores, strips characters unsupported by
    common filesystems, and collapses consecutive separators. When the resulting
    string becomes empty, ``default`` is returned instead.
    """

    text = str(value or "").strip()
    if not text:
        return default

    normalized = text.replace(" ", "_")
    sanitized = _INVALID_CHARS_PATTERN.sub("", normalized)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("_-.")
    return sanitized or default


__all__ = ["sanitize_filename"]
