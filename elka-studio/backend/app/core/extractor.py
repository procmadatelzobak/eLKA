"""Utilities for extracting structured facts from story text."""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from pydantic import ValidationError

from app.adapters.ai.base import BaseAIAdapter

from ..utils.identifiers import generate_entity_id
from .schemas import ExtractedData, FactEntity, FactEvent, FactGraph


logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Deterministically slugify text for identifiers."""

    normalised = unicodedata.normalize("NFKD", text)
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    return cleaned or "item"


EXTRACTOR_SYSTEM_PROMPT = """
You are an information extraction agent. Your task is to read the provided story text
and extract all relevant entities: Characters, Locations, Events, Concepts, Items, and Misc.

Respond ONLY with a JSON object containing lists for each entity type found.
Each entity object MUST include:
- "name": The primary name of the entity.
- "type": The type of the entity. MUST be one of: "Character", "Location", "Event", "Concept", "Item", "Misc".
- "description": A brief description based on the text.
- "aliases": (Optional) A list of alternative names found in the text.
- "summary": (Optional) A one-sentence summary.
- "relationships": (Optional) A dictionary mapping related entity identifiers to a human-readable string describing the relationship. The description MUST be a string.

DO NOT include an "id" field; it will be generated later.
Focus on accuracy and completeness based ONLY on the provided text.

Example JSON format:
{
  "characters": [
    { "name": "Hubert Nahoda", "type": "Character", "description": "Uředník...", "aliases": ["Hubert"] },
    { "name": "Edita Kvorova", "type": "Character", "description": "Vedoucí..." }
  ],
  "locations": [
    { "name": "Ministerstvo Nepravděpodobnosti", "type": "Location", "description": "Instituce..." }
  ],
  "events": [],
  "concepts": [],
  "items": [],
  "misc": []
}
""".strip()


_ENTITY_KEY_TO_TYPE: Dict[str, str] = {
    "characters": "Character",
    "locations": "Location",
    "events": "Event",
    "concepts": "Concept",
    "items": "Item",
    "misc": "Misc",
}

_TYPE_SYNONYMS: Dict[str, str] = {
    "character": "Character",
    "person": "Character",
    "people": "Character",
    "hero": "Character",
    "location": "Location",
    "place": "Location",
    "city": "Location",
    "event": "Event",
    "battle": "Event",
    "concept": "Concept",
    "idea": "Concept",
    "item": "Item",
    "object": "Item",
    "artifact": "Item",
    "misc": "Misc",
    "other": "Misc",
}

_ALLOWED_TYPE_LOOKUP: Dict[str, str] = {
    **{canonical.lower(): canonical for canonical in _ENTITY_KEY_TO_TYPE.values()},
    **_TYPE_SYNONYMS,
}

_TYPE_TO_KEY: Dict[str, str] = {
    canonical: key for key, canonical in _ENTITY_KEY_TO_TYPE.items()
}


def _build_user_prompt(story: str, context: Optional[str] = None) -> str:
    sections: List[str] = []
    if context and context.strip():
        sections.append("Context:\n" + context.strip())
    sections.append("Story:\n" + story.strip())
    return "\n\n".join(sections)


def _normalise_aliases(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(alias).strip() for alias in value if str(alias).strip()]
    if value:
        alias = str(value).strip()
        return [alias] if alias else []
    return []


def _normalise_relationships(value: Any) -> Dict[str, str]:
    relationships: Dict[str, str] = {}
    if isinstance(value, dict):
        for key, relation in value.items():
            if not isinstance(key, str):
                continue
            if relation is None:
                continue
            relationships[key] = str(relation)
    return relationships


class ExtractorEngine:
    """High-level engine for extracting structured entities from stories."""

    def __init__(
        self,
        ai_adapter: BaseAIAdapter,
        *,
        model_overrides: Dict[str, str] | None = None,
    ) -> None:
        self.ai_adapter = ai_adapter
        self._model_overrides = model_overrides or {}

    def extract(
        self,
        story_text: str,
        *,
        universe_context: str | None = None,
        model_key: str | None = None,
    ) -> tuple[ExtractedData, Dict[str, int] | None]:
        """Extract entities from ``story_text`` and return structured data."""

        if not story_text.strip():
            raise ValueError("Story text must not be empty for extraction.")

        base_prompt = _build_user_prompt(story_text, universe_context)
        user_prompt = base_prompt
        attempts = 0
        last_error: Exception | None = None

        while attempts < 3:
            attempts += 1
            raw_result: Any | None = None
            try:
                logger.info(
                    "Extractor attempt %s for story (first 100 chars): %s…",
                    attempts,
                    story_text[:100].replace("\n", " "),
                )
                logger.debug(
                    "Extractor attempt %s sending full story: %s",
                    attempts,
                    story_text,
                )
                raw_result, tokens = self._invoke_model(user_prompt, model_key)
                logger.debug(
                    "Extractor attempt %s received raw response: %s",
                    attempts,
                    raw_result,
                )
                llm_result = self._coerce_result(raw_result)
                processed_payload = self._post_process(llm_result)

                for entity_list in processed_payload.values():
                    for entity_payload in entity_list:
                        relationships = entity_payload.get("relationships")
                        if not relationships:
                            continue
                        if not isinstance(relationships, dict):
                            logger.warning(
                                "Discarding malformed relationships for entity '%s': expected dict, got %s",
                                entity_payload.get("name") or entity_payload.get("id"),
                                type(relationships).__name__,
                            )
                            entity_payload["relationships"] = {}
                            continue
                        for rel_id, rel_desc in list(relationships.items()):
                            if isinstance(rel_desc, str):
                                continue
                            try:
                                relationships[rel_id] = str(rel_desc)
                            except Exception:  # pragma: no cover - defensive logging
                                logger.warning(
                                    "Failed to coerce relationship description for '%s' -> '%s' (%r)",
                                    entity_payload.get("name")
                                    or entity_payload.get("id"),
                                    rel_id,
                                    rel_desc,
                                )
                                relationships.pop(rel_id, None)

                try:
                    parsed_data = ExtractedData(**processed_payload)
                except ValidationError as exc:  # pragma: no cover - adapter specific
                    raise ValueError(
                        "Pydantic validation failed after adding IDs"
                    ) from exc
                return parsed_data, tokens
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning(
                    "Extractor attempt %s failed to decode JSON: %s",
                    attempts,
                    exc,
                )
                if raw_result is not None:
                    logger.error(
                        "Extractor failed JSON decoding. Raw response from AI was: %s",
                        raw_result,
                    )
                if attempts >= 3:
                    break
                time.sleep(2 ** (attempts - 1))
                user_prompt = (
                    "Return ONLY JSON. If you cannot comply, respond with an empty JSON object.\n"
                    f"{base_prompt}"
                )
            except (TypeError, ValueError) as exc:
                last_error = exc
                logger.warning("Extractor attempt %s failed: %s", attempts, exc)
                if raw_result is not None:
                    logger.warning(
                        "Extractor raw response snippet on attempt %s: %s",
                        attempts,
                        str(raw_result)[:200],
                    )
                if attempts >= 3:
                    break
                time.sleep(2 ** (attempts - 1))
                user_prompt = (
                    "Return ONLY JSON. If you cannot comply, respond with an empty JSON object.\n"
                    f"{base_prompt}"
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                last_error = exc
                logger.error(
                    "Extractor attempt %s failed with unexpected error: %s",
                    attempts,
                    exc,
                    exc_info=True,
                )
                logger.error(
                    "Story snippet during extractor failure: %s",
                    story_text[:500],
                )
                if attempts >= 3:
                    break
                time.sleep(2 ** (attempts - 1))
                user_prompt = base_prompt

        raise ValueError(
            "Failed to extract structured entities from story"
        ) from last_error

    def _invoke_model(
        self,
        user_prompt: str,
        model_key: str | None,
    ) -> tuple[Any, Dict[str, int] | None]:
        resolved_model = model_key or self._model_overrides.get("extraction")
        tokens: Dict[str, int] | None = None

        if hasattr(self.ai_adapter, "generate_json"):
            try:
                if resolved_model:
                    result, tokens = self.ai_adapter.generate_json(
                        EXTRACTOR_SYSTEM_PROMPT,
                        user_prompt,
                        model_key=resolved_model,
                    )
                else:
                    result, tokens = self.ai_adapter.generate_json(
                        EXTRACTOR_SYSTEM_PROMPT,
                        user_prompt,
                    )
            except TypeError:
                result, tokens = self.ai_adapter.generate_json(
                    EXTRACTOR_SYSTEM_PROMPT,
                    user_prompt,
                )
            return result, tokens

        if hasattr(self.ai_adapter, "generate_text"):
            prompt = f"{EXTRACTOR_SYSTEM_PROMPT}\n\n{user_prompt}"
            try:
                if resolved_model:
                    result, tokens = self.ai_adapter.generate_text(
                        prompt,
                        model_key=resolved_model,
                    )
                else:
                    result, tokens = self.ai_adapter.generate_text(prompt)
            except TypeError:
                result, tokens = self.ai_adapter.generate_text(prompt)
            return result, tokens

        raise RuntimeError("AI adapter does not support JSON extraction.")

    @staticmethod
    def _clean_json_response(raw_response: str) -> str:
        """
        Cleans the raw response from the AI model to extract the JSON part.
        Removes markdown code blocks (```json ... ```) and leading/trailing whitespace.
        """

        if not raw_response:
            return ""

        # Hledá ```json (nebo jen ```), pak libovolné mezery/řádky, pak { nebo [, pak cokoli, pak } nebo ], pak libovolné mezery/řádky, pak ```
        match = re.search(
            r"```(?:json)?\s*({[\s\S]*?}|\[[\s\S]*?\])\s*```",
            raw_response,
            re.DOTALL,
        )

        if match:
            cleaned_json = match.group(1).strip()
        else:
            cleaned_json = raw_response.strip()
            cleaned_json = re.sub(r"^[^{[]*", "", cleaned_json)
            cleaned_json = re.sub(r"[^}\]]*$", "", cleaned_json)

        return cleaned_json.strip()

    def _prepare_string_result(self, payload: str) -> str:
        cleaned = self._clean_json_response(payload)
        if not cleaned:
            raise ValueError("Received incomplete or empty JSON response from extractor")

        return cleaned

    def _coerce_result(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            prepared = self._prepare_string_result(payload)
            return json.loads(prepared)
        raise TypeError("Extractor returned non-string payload")

    def _post_process(
        self, llm_result: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        processed: Dict[str, List[Dict[str, Any]]] = {
            key: [] for key in _ENTITY_KEY_TO_TYPE
        }

        normalised_keys: Dict[str, Any] = {}
        for key, value in llm_result.items():
            if isinstance(key, str):
                lowered = key.lower()
                if lowered in _ENTITY_KEY_TO_TYPE:
                    normalised_keys[lowered] = value

        general_entities = llm_result.get("entities")
        if isinstance(general_entities, Iterable) and not isinstance(
            general_entities, (str, bytes)
        ):
            for raw_entity in general_entities:
                if not isinstance(raw_entity, dict):
                    continue
                raw_type = raw_entity.get("type")
                canonical_type = None
                if isinstance(raw_type, str) and raw_type.strip():
                    canonical_type = _ALLOWED_TYPE_LOOKUP.get(raw_type.strip().lower())
                if not canonical_type:
                    raise ValueError(
                        f"Unsupported entity type returned by extractor: {raw_type!r}"
                    )
                target_key = _TYPE_TO_KEY.get(canonical_type, "misc")
                entity_payload = self._normalise_entity(raw_entity, canonical_type)
                if not entity_payload:
                    raise ValueError(
                        f"Entity payload missing required fields for type '{canonical_type}'"
                    )
                processed[target_key].append(entity_payload)

        for key, canonical_type in _ENTITY_KEY_TO_TYPE.items():
            raw_entities = normalised_keys.get(key, [])
            if not isinstance(raw_entities, Iterable) or isinstance(
                raw_entities, (str, bytes)
            ):
                continue
            for raw_entity in raw_entities:
                entity_payload = self._normalise_entity(raw_entity, canonical_type)
                if entity_payload:
                    processed[key].append(entity_payload)
        return processed

    def _normalise_entity(
        self, raw_entity: Any, canonical_type: str
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_entity, dict):
            logger.debug("Skipping incomplete entity data: %s", raw_entity)
            return None

        name_source = (
            raw_entity.get("name") or raw_entity.get("title") or raw_entity.get("id")
        )
        name = str(name_source or "").strip()
        if not name:
            logger.debug("Skipping incomplete entity data without name: %s", raw_entity)
            return None

        raw_type = raw_entity.get("type")
        resolved_type = canonical_type
        resolved_label = canonical_type.lower()
        if isinstance(raw_type, str) and raw_type.strip():
            candidate = _ALLOWED_TYPE_LOOKUP.get(raw_type.strip().lower())
            if candidate:
                resolved_type = candidate
                resolved_label = raw_type.strip().lower()
            else:
                raise ValueError(f"Unsupported entity type '{raw_type}'")
        aliases = _normalise_aliases(raw_entity.get("aliases"))
        description = raw_entity.get("description")
        if isinstance(description, str):
            description = description.strip() or None
        else:
            description = None
        summary = raw_entity.get("summary")
        if isinstance(summary, str):
            summary = summary.strip() or None
        else:
            summary = None
        relationships = _normalise_relationships(raw_entity.get("relationships"))
        attributes: Dict[str, Any] = {}
        raw_attributes = raw_entity.get("attributes")
        if isinstance(raw_attributes, dict):
            for key, value in raw_attributes.items():
                if isinstance(key, str):
                    attributes[key] = value
        if resolved_type.lower() == "event":
            participants_raw = raw_entity.get("participants")
            if isinstance(participants_raw, Iterable) and not isinstance(
                participants_raw, (str, bytes)
            ):
                if relationships is None:
                    relationships = {}
                for participant in participants_raw:
                    if not isinstance(participant, str):
                        continue
                    slug = _slugify(participant)
                    if slug:
                        relationships[slug] = "participant"
            location = raw_entity.get("location")
            if isinstance(location, str) and location.strip():
                attributes["location"] = _slugify(location)

        entity_payload: Dict[str, Any] = {
            "id": generate_entity_id(resolved_type, name),
            "type": resolved_label,
            "name": name,
            "description": description,
            "summary": summary,
            "aliases": aliases,
            "relationships": relationships,
            "attributes": attributes,
        }
        return entity_payload


def extract_fact_graph(
    story: str,
    ai: BaseAIAdapter,
    context: str | None = None,
    *,
    model_key: str | None = None,
    model_overrides: Dict[str, str] | None = None,
) -> FactGraph:
    """Use the AI adapter to convert a story into a :class:`FactGraph`."""

    engine = ExtractorEngine(ai_adapter=ai, model_overrides=model_overrides)
    extracted_data, _ = engine.extract(
        story,
        universe_context=context,
        model_key=model_key,
    )

    entities: List[FactEntity] = []
    for key in ("characters", "locations", "concepts", "items", "misc"):
        entities.extend(getattr(extracted_data, key))

    events: List[FactEvent] = []
    for event_entity in extracted_data.events:
        participants = (
            list(event_entity.relationships.keys())
            if event_entity.relationships
            else []
        )
        location = None
        if event_entity.attributes:
            raw_location = event_entity.attributes.get("location")
            if isinstance(raw_location, str) and raw_location.strip():
                location = raw_location
        events.append(
            FactEvent(
                id=event_entity.id,
                title=event_entity.name,
                description=event_entity.description or event_entity.summary,
                participants=participants,
                location=location,
            )
        )

    return FactGraph(entities=entities, events=events)


def extract_story_entities(
    story: str,
    ai: BaseAIAdapter,
    universe_context: str | None = None,
    *,
    model_key: str | None = None,
    model_overrides: Dict[str, str] | None = None,
) -> ExtractedData:
    """Extract structured entity data suitable for archival."""

    engine = ExtractorEngine(ai_adapter=ai, model_overrides=model_overrides)
    extracted_data, _ = engine.extract(
        story,
        universe_context=universe_context,
        model_key=model_key,
    )
    return extracted_data


__all__ = [
    "ExtractorEngine",
    "EXTRACTOR_SYSTEM_PROMPT",
    "extract_fact_graph",
    "extract_story_entities",
    "_slugify",
]
