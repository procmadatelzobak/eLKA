"""Utilities for extracting structured facts from story text."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Iterable

from pydantic import ValidationError

from app.adapters.ai.base import BaseAIAdapter

from .schemas import (
    EntityType,
    ExtractedData,
    ExtractedEntity,
    ExtractedEvent,
    FactGraph,
)


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


STRICT_FACT_GRAPH_TEMPLATE = """
You are the Universe Consistency Extractor. Reply with JSON **only**.
Return an object with exactly two keys: "entities" and "events".
- "entities": array of objects with keys {"id", "type", "labels", "summary", "attributes"}.
  Valid "type" values include person, place, artifact, organization, concept, material, event, other.
- "events": array of objects with keys {"id", "title", "date", "location", "participants", "description"}.
Match the field names exactly. Use slug-style identifiers (lowercase, underscore).
Do not include markdown, code fences, explanations, or trailing text.
Story follows between <story> markers. When <context> is present, ensure the
extracted facts align with that lore and prefer identifiers already used in the
context.
""".strip()


def _build_request_payload(story: str, context: str | None = None) -> str:
    payload = STRICT_FACT_GRAPH_TEMPLATE
    if context and context.strip():
        payload += "\n<context>\n" + context.strip() + "\n</context>"
    payload += "\n<story>\n" + story.strip() + "\n</story>"
    return payload


def extract_fact_graph(
    story: str,
    ai: BaseAIAdapter,
    context: str | None = None,
) -> FactGraph:
    """Use the AI adapter to convert a story into a :class:`FactGraph`."""

    base_prompt = _build_request_payload(story, context=context)
    prompts = [base_prompt]

    last_error: Exception | None = None
    retry_prompt_used = False
    while prompts:
        prompt = prompts.pop(0)
        result: Any
        if hasattr(ai, "generate_json"):
            system_prompt = (
                "You are a precise information extraction engine. "
                "Respond with compact JSON matching the requested schema."
            )
            try:
                result, _ = ai.generate_json(system_prompt, prompt)  # type: ignore[arg-type]
            except Exception as exc:  # pragma: no cover - adapter specific
                last_error = exc
                continue
        else:
            result = ai.analyse(prompt, aspect="extraction", context=context)

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
        except ValidationError as exc:
            last_error = exc
            if not retry_prompt_used:
                retry_prompt_used = True
                prompts.append("Return ONLY JSON.\n" + base_prompt)
            continue
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = exc
            if not retry_prompt_used:
                retry_prompt_used = True
                prompts.append("Return ONLY JSON.\n" + base_prompt)
            continue

    raise ValueError(f"Extractor failed to return valid JSON: {last_error}")


def _map_entity_type(raw_type: str) -> EntityType:
    normalised = (raw_type or "").strip().lower()
    if normalised in {"person", "character", "being", "creature", "hero", "villain"}:
        return EntityType.CHARACTER
    if normalised in {"place", "location", "region", "area", "planet", "realm"}:
        return EntityType.LOCATION
    if normalised in {"event", "incident", "battle", "ceremony"}:
        return EntityType.EVENT
    if normalised in {"concept", "idea", "philosophy", "belief"}:
        return EntityType.CONCEPT
    if normalised in {"artifact", "item", "object", "device", "thing"}:
        return EntityType.ITEM
    if normalised in {"material", "substance", "element", "alloy"}:
        return EntityType.MATERIAL
    if normalised in {"organization", "organisation", "faction", "guild", "order", "clan"}:
        return EntityType.ORGANIZATION
    return EntityType.OTHER


def extract_story_entities(
    story: str,
    ai: BaseAIAdapter,
    universe_context: str | None = None,
) -> ExtractedData:
    """Extract structured entity data suitable for archival."""

    fact_graph = extract_fact_graph(story, ai, context=universe_context)
    data = ExtractedData()

    for entity in fact_graph.entities:
        entity_type = _map_entity_type(entity.type)
        display_name = entity.summary or entity.id.replace("_", " ").title()
        extracted = ExtractedEntity(
            id=entity.id,
            name=display_name,
            summary=entity.summary,
            description=entity.attributes.get("description") or entity.summary,
            aliases=list(entity.labels),
            attributes=dict(entity.attributes),
            entity_type=entity_type,
        )
        if entity_type == EntityType.CHARACTER:
            data.characters.append(extracted)
        elif entity_type == EntityType.LOCATION:
            data.locations.append(extracted)
        elif entity_type == EntityType.CONCEPT:
            data.concepts.append(extracted)
        elif entity_type == EntityType.ITEM:
            data.things.append(extracted)
        elif entity_type == EntityType.MATERIAL:
            data.materials.append(extracted)
        else:
            data.others.append(extracted)

    for event in fact_graph.events:
        extracted_event = ExtractedEvent(
            id=event.id,
            name=event.title,
            summary=event.description,
            description=event.description,
            date=event.date,
            location=event.location,
            participants=list(event.participants),
        )
        data.events.append(extracted_event)

    return data


__all__ = ["extract_fact_graph", "extract_story_entities", "_slugify"]
