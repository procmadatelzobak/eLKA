"""Utilities for extracting structured facts from story text."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.adapters.ai.base import BaseAIAdapter

from .schemas import FactGraph


def _slugify(text: str) -> str:
    """Deterministically slugify text for identifiers."""

    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    return cleaned or "item"


def extract_fact_graph(story: str, ai: BaseAIAdapter) -> FactGraph:
    """Use the AI adapter to convert a story into a :class:`FactGraph`."""

    prompt = (
        "Extract entities and events from this story as strict JSON matching the schema FactGraph. "
        "No explanations, only JSON.\n\nSTORY:\n"
        + story
    )
    result: Any = ai.analyse(prompt, aspect="extraction")
    if isinstance(result, dict) and {"entities", "events"}.issubset(result):
        return FactGraph(**result)
    if isinstance(result, str):
        try:
            data = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid extractor output: {exc}") from exc
        return FactGraph(**data)
    raise ValueError("Extractor returned unsupported response")


__all__ = ["extract_fact_graph", "_slugify"]
