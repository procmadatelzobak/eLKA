"""Utilities for extracting structured facts from story text."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Iterable

from pydantic import ValidationError

from app.adapters.ai.base import BaseAIAdapter

from .schemas import FactGraph


def _slugify(text: str) -> str:
    """Deterministically slugify text for identifiers."""

    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    return cleaned or "item"


def _normalise_entities(raw_entities: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    normalised: list[Dict[str, Any]] = []
    for index, entity in enumerate(raw_entities):
        item = dict(entity or {})
        identifier = item.get("id") or item.get("name") or f"entity_{index}"
        item["id"] = _slugify(str(identifier))
        item.setdefault("type", "other")
        item.setdefault("labels", [])
        item.setdefault("attributes", {})
        normalised.append(item)
    return normalised


def _normalise_events(raw_events: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    normalised: list[Dict[str, Any]] = []
    for index, event in enumerate(raw_events):
        item = dict(event or {})
        title = item.get("title") or item.get("name") or f"Event {index + 1}"
        item["title"] = str(title).strip()
        item["id"] = _slugify(item.get("id") or item["title"])
        participants = [
            _slugify(str(participant))
            for participant in item.get("participants", [])
            if str(participant).strip()
        ]
        item["participants"] = participants
        location = item.get("location")
        if isinstance(location, str) and location.strip():
            item["location"] = _slugify(location)
        description = item.get("description")
        if isinstance(description, str):
            item["description"] = description.strip()
        normalised.append(item)
    return normalised


def _build_request_payload(story: str) -> str:
    return (
        "Extract entities and events from the following story. "
        "Return STRICT JSON that matches this schema: "
        "{\"entities\": [FactEntity], \"events\": [FactEvent]}. "
        "Use slug-like identifiers. No prose, no markdown.\n\nSTORY:\n"
        + story
    )


def extract_fact_graph(story: str, ai: BaseAIAdapter) -> FactGraph:
    """Use the AI adapter to convert a story into a :class:`FactGraph`."""

    prompts = [
        _build_request_payload(story),
        "ONLY JSON. No prose.\n" + _build_request_payload(story),
    ]

    last_error: Exception | None = None
    for prompt in prompts:
        result: Any
        if hasattr(ai, "generate_json"):
            system_prompt = (
                "You are a precise information extraction engine. "
                "Respond with compact JSON matching the requested schema."
            )
            try:
                result = ai.generate_json(system_prompt, prompt)  # type: ignore[arg-type]
            except Exception as exc:  # pragma: no cover - adapter specific
                last_error = exc
                continue
        else:
            result = ai.analyse(prompt, aspect="extraction")

        try:
            if isinstance(result, dict):
                data = result
            else:
                if not isinstance(result, str):
                    raise TypeError("Extractor returned non-string payload")
                data = json.loads(result)
            entities = _normalise_entities(data.get("entities", []))
            events = _normalise_events(data.get("events", []))
            graph = FactGraph(entities=entities, events=events)
            return graph
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            last_error = exc
            continue

    raise ValueError(f"Extractor failed to return valid JSON: {last_error}")


__all__ = ["extract_fact_graph", "_slugify"]
