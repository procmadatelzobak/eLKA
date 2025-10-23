"""Planner responsible for reconciling entity graphs and proposing changes."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.adapters.ai.base import BaseAIAdapter
from app.utils.filesystem import sanitize_filename

from .extractor import _slugify
from .schemas import (
    ChangeOperation,
    ChangeSet,
    Changeset,
    ChangesetFile,
    FactEntity,
    FactEntityGraph,
    FactEntityUpdate,
    FactEvent,
    FactGraph,
)

logger = logging.getLogger(__name__)

TEMPLATE_TIMELINE = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "universe_scaffold"
    / "timeline.md"
)


PLANNER_SYSTEM_PROMPT = """
You are the Universe Consistency Engine (UCE) Planner focused on entity reconciliation.
You will receive two lists:
1.  `existing_unmatched_entities`: Existing entities from the universe that did NOT have an ID match with incoming data.
2.  `potential_new_entities`: Entities extracted from a new story that did NOT have an ID match with existing data.

Your goal is to determine if any `potential_new_entities` are actually duplicates or updates of `existing_unmatched_entities` based on their names, aliases, types, and descriptions.

Respond ONLY with a JSON object containing two keys:
1.  `truly_new_entities`: A list of entities from `potential_new_entities` that have NO plausible match in `existing_unmatched_entities`. These will be created as new entries.
2.  `matched_updates`: A list of `FactEntityUpdate` objects for entities you identified as matches.
    - Use the format: `{"id": "EXISTING_ID", "existing": {...existing_entity_data...}, "incoming": {...potential_new_entity_data...}}`
    - **CRITICAL:** Always use the `id` from the matched `existing_unmatched_entities` object.

Be conservative: Prefer matching entities if there's reasonable similarity (name, type, context) to avoid creating duplicates.
If an entity from `potential_new_entities` has no match, include it in `truly_new_entities`.
""".strip()


class PlannerEngine:
    """Plan entity creations and updates by reconciling two fact graphs."""

    def __init__(
        self,
        *,
        ai_adapter: BaseAIAdapter | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.ai = ai_adapter
        self.logger = logger or logging.getLogger(__name__)

    def plan_changes(
        self,
        current_graph: FactEntityGraph,
        incoming_graph: FactEntityGraph,
        *,
        model_key: str | None = None,
    ) -> ChangeSet:
        """Return a :class:`ChangeSet` describing entity creations and updates."""

        current_entities_map: Dict[str, FactEntity] = {
            entity.id: entity for entity in current_graph.entities if entity.id
        }
        incoming_entities_map: Dict[str, FactEntity] = {
            entity.id: entity for entity in incoming_graph.entities if entity.id
        }

        updated_entities_by_id: List[FactEntityUpdate] = []
        potential_new_entities: List[FactEntity] = []
        existing_unmatched_entities: List[FactEntity] = list(
            current_entities_map.values()
        )

        for entity_id, incoming_entity in incoming_entities_map.items():
            existing_entity = current_entities_map.get(entity_id)
            if existing_entity is not None:
                updated_entities_by_id.append(
                    FactEntityUpdate(
                        id=entity_id,
                        existing=existing_entity,
                        incoming=incoming_entity,
                    )
                )
                existing_unmatched_entities = [
                    entity
                    for entity in existing_unmatched_entities
                    if entity.id != entity_id
                ]
            else:
                potential_new_entities.append(incoming_entity)

        llm_updated_entities: List[FactEntityUpdate] = []
        final_new_entities: List[FactEntity] = []
        tokens: Dict[str, int] | None = None

        if potential_new_entities and existing_unmatched_entities and self._supports_ai:
            prompt_payload = self._build_prompt_payload(
                existing_unmatched_entities, potential_new_entities
            )
            try:
                llm_result, tokens = self._invoke_ai(
                    prompt_payload, model_key=model_key
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.error("Error during AI entity matching: %s", exc)
                final_new_entities = potential_new_entities
            else:
                if llm_result:
                    llm_new_entities, llm_updated_entities = self._process_ai_response(
                        llm_result,
                        potential_new_entities,
                        existing_unmatched_entities,
                    )
                    if llm_new_entities:
                        matched_update_ids = {
                            update.incoming.id
                            for update in llm_updated_entities
                            if update.incoming.id
                        }
                        final_new_entities = self._merge_new_entities(
                            llm_new_entities,
                            potential_new_entities,
                            matched_update_ids,
                        )
                    else:
                        final_new_entities = self._fallback_new_entities(
                            potential_new_entities, llm_updated_entities
                        )
                else:
                    self.logger.warning(
                        "Planner AI failed to return valid JSON. Treating all potential entities as new."
                    )
                    final_new_entities = potential_new_entities
        else:
            if potential_new_entities and not self._supports_ai:
                self.logger.info(
                    "Planner AI adapter unavailable; treating %d entities as new.",
                    len(potential_new_entities),
                )
            final_new_entities = potential_new_entities

        final_updated_entities = updated_entities_by_id + llm_updated_entities

        operations: List[ChangeOperation] = []
        operations.extend(
            ChangeOperation(operation="create", entity=entity)
            for entity in final_new_entities
        )
        operations.extend(
            ChangeOperation(operation="update", update=update)
            for update in final_updated_entities
        )

        return ChangeSet(operations=list(operations), tokens=tokens)

    @property
    def _supports_ai(self) -> bool:
        return bool(self.ai and hasattr(self.ai, "generate_json"))

    def _build_prompt_payload(
        self,
        existing_unmatched_entities: Iterable[FactEntity],
        potential_new_entities: Iterable[FactEntity],
    ) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "existing_unmatched_entities": [
                entity.model_dump(exclude_none=True)
                for entity in existing_unmatched_entities
            ],
            "potential_new_entities": [
                entity.model_dump(exclude_none=True)
                for entity in potential_new_entities
            ],
        }

    def _invoke_ai(
        self,
        payload: Dict[str, Any],
        *,
        model_key: str | None = None,
    ) -> Tuple[Dict[str, Any] | None, Dict[str, int] | None]:
        if not self.ai:
            raise RuntimeError("AI adapter not configured for planner invocation.")

        try:
            if model_key:
                result, tokens = self.ai.generate_json(
                    PLANNER_SYSTEM_PROMPT,
                    payload,
                    model_key=model_key,
                )
            else:
                result, tokens = self.ai.generate_json(PLANNER_SYSTEM_PROMPT, payload)
        except TypeError:
            result, tokens = self.ai.generate_json(PLANNER_SYSTEM_PROMPT, payload)

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                self.logger.warning(
                    "Planner AI returned non-JSON payload; treating as no matches."
                )
                result = None
        elif result is not None and not isinstance(result, dict):
            self.logger.warning(
                "Planner AI returned unexpected payload type %s; ignoring matches.",
                type(result).__name__,
            )
            result = None

        return result, tokens

    def _process_ai_response(
        self,
        llm_result: Dict[str, Any],
        potential_new_entities: List[FactEntity],
        existing_unmatched_entities: List[FactEntity],
    ) -> Tuple[List[FactEntity], List[FactEntityUpdate]]:
        potential_by_id = {entity.id: entity for entity in potential_new_entities}
        existing_by_id = {entity.id: entity for entity in existing_unmatched_entities}

        raw_new_entities = llm_result.get("truly_new_entities", [])
        new_entities: List[FactEntity] = []
        for item in raw_new_entities:
            resolved = self._resolve_entity_reference(item, potential_by_id)
            if resolved is not None:
                new_entities.append(resolved)

        matched_updates: List[FactEntityUpdate] = []
        for raw_update in llm_result.get("matched_updates", []):
            update = self._coerce_update(raw_update, potential_by_id, existing_by_id)
            if update is not None:
                matched_updates.append(update)

        return new_entities, matched_updates

    def _resolve_entity_reference(
        self,
        payload: Any,
        source_lookup: Dict[str, FactEntity],
    ) -> FactEntity | None:
        if isinstance(payload, FactEntity):
            return payload
        if isinstance(payload, dict):
            entity_id = payload.get("id")
            if entity_id and entity_id in source_lookup:
                return source_lookup[entity_id]
            try:
                return FactEntity.model_validate(payload)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.warning(
                    "Failed to parse AI provided entity payload: %s", exc
                )
                return None
        return None

    def _coerce_update(
        self,
        payload: Any,
        potential_by_id: Dict[str, FactEntity],
        existing_by_id: Dict[str, FactEntity],
    ) -> FactEntityUpdate | None:
        if isinstance(payload, FactEntityUpdate):
            return payload
        if not isinstance(payload, dict):
            return None

        entity_id = payload.get("id")
        if not entity_id:
            return None

        existing_entity = existing_by_id.get(entity_id)
        if existing_entity is None:
            self.logger.warning(
                "Planner AI suggested update for unknown entity id '%s'; skipping.",
                entity_id,
            )
            return None

        incoming_payload = payload.get("incoming")
        if isinstance(incoming_payload, FactEntity):
            incoming_entity = incoming_payload
        elif isinstance(incoming_payload, dict):
            try:
                incoming_entity = FactEntity.model_validate(incoming_payload)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.warning(
                    "Planner AI provided invalid incoming entity for id '%s': %s",
                    entity_id,
                    exc,
                )
                return None
        else:
            incoming_entity = potential_by_id.get(entity_id)
            if incoming_entity is None:
                self.logger.warning(
                    "Planner AI did not provide incoming data for entity id '%s'; skipping.",
                    entity_id,
                )
                return None

        return FactEntityUpdate(
            id=entity_id,
            existing=existing_entity,
            incoming=incoming_entity,
        )

    def _merge_new_entities(
        self,
        ai_entities: List[FactEntity],
        potential_new_entities: List[FactEntity],
        matched_update_ids: Iterable[str],
    ) -> List[FactEntity]:
        matched_set = {entity_id for entity_id in matched_update_ids if entity_id}
        result: List[FactEntity] = []
        seen_ids: set[str] = set()

        for entity in ai_entities:
            if entity.id and entity.id in matched_set:
                continue
            if entity.id and entity.id in seen_ids:
                continue
            result.append(entity)
            if entity.id:
                seen_ids.add(entity.id)

        for entity in potential_new_entities:
            if entity.id and (entity.id in matched_set or entity.id in seen_ids):
                continue
            result.append(entity)
            if entity.id:
                seen_ids.add(entity.id)

        return result

    def _fallback_new_entities(
        self,
        potential_new_entities: List[FactEntity],
        llm_updates: List[FactEntityUpdate],
    ) -> List[FactEntity]:
        matched_ids = {
            update.incoming.id for update in llm_updates if update.incoming.id
        }
        if not matched_ids:
            return potential_new_entities
        return [
            entity for entity in potential_new_entities if entity.id not in matched_ids
        ]


def _strip_heading(markdown: str) -> str:
    """Remove leading Markdown headings to extract body text."""

    lines = [line for line in markdown.splitlines() if line.strip()]
    while lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
    return "\n".join(lines).strip()


def _render_entity_body(
    entity: FactEntity,
    writer: BaseAIAdapter | None,
    *,
    model_key: str | None = None,
) -> str:
    summary = (entity.summary or "").strip()
    if writer and summary:
        try:
            generated = writer.generate_markdown(
                instruction=(
                    "Write a short Markdown paragraph (no heading) describing the entity "
                    f"'{entity.id}'. Focus on lore-relevant context."
                ),
                context=summary,
                model_key=model_key,
            ).strip()
        except TypeError:
            generated = writer.generate_markdown(
                instruction=(
                    "Write a short Markdown paragraph (no heading) describing the entity "
                    f"'{entity.id}'. Focus on lore-relevant context."
                ),
                context=summary,
            ).strip()
        if generated:
            summary = _strip_heading(generated) or summary
    return summary


def _render_update_body(
    entity: FactEntity,
    writer: BaseAIAdapter | None,
    *,
    model_key: str | None = None,
) -> str:
    update_text = (entity.summary or "").strip()
    if writer and update_text:
        try:
            generated = writer.generate_markdown(
                instruction=(
                    "Summarise the following lore update as a short paragraph. Do not include headings; "
                    "return Markdown suitable for an '## Update' section."
                ),
                context=update_text,
                model_key=model_key,
            ).strip()
        except TypeError:
            generated = writer.generate_markdown(
                instruction=(
                    "Summarise the following lore update as a short paragraph. Do not include headings; "
                    "return Markdown suitable for an '## Update' section."
                ),
                context=update_text,
            ).strip()
        if generated:
            update_text = _strip_heading(generated) or update_text
    return update_text


def plan_changes(
    current: FactGraph,
    incoming: FactGraph,
    repo_path: Path,
    writer: BaseAIAdapter | None = None,
    *,
    model_key: str | None = None,
) -> Changeset:
    """Generate a deterministic changeset for the provided fact graph."""

    files: list[ChangesetFile] = []
    entity_updates = 0

    planner = PlannerEngine(ai_adapter=writer)
    planned_entities: list[FactEntity] = []
    try:
        change_set = planner.plan_changes(
            FactEntityGraph(entities=current.entities),
            FactEntityGraph(entities=incoming.entities),
            model_key=model_key,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error(
            "Planner engine failed; falling back to naive entity handling: %s",
            exc,
        )
        planned_entities = list(incoming.entities)
    else:
        processed_ids: set[str] = set()
        for operation in change_set.operations:
            entity: FactEntity | None = None
            if operation.operation == "create" and operation.entity:
                entity = operation.entity
            elif operation.operation == "update" and operation.update:
                entity = operation.update.incoming.model_copy(
                    update={"id": operation.update.id}
                )
            if not entity or entity.id in processed_ids:
                continue
            planned_entities.append(entity)
            processed_ids.add(entity.id)

        if not planned_entities:
            planned_entities = list(incoming.entities)

    for entity in planned_entities:
        entity_slug = sanitize_filename(entity.id, default="entity")
        target = repo_path / "Objekty" / f"{entity_slug}.md"
        old_content = target.read_text(encoding="utf-8") if target.exists() else None

        if old_content is None:
            body = _render_entity_body(entity, writer, model_key=model_key)
            new_content = f"# {entity.id}\n{body}\n" if body else f"# {entity.id}\n\n"
        else:
            cleaned_existing = old_content.rstrip("\n")
            summary_text = _render_update_body(entity, writer, model_key=model_key)
            if not summary_text:
                # Empty updates should not modify the file.
                new_content = (
                    old_content if old_content.endswith("\n") else f"{old_content}\n"
                )
            else:
                if "## Update" not in cleaned_existing:
                    base_body = (
                        cleaned_existing.split("\n", 1)[1]
                        if "\n" in cleaned_existing
                        else ""
                    )
                    if base_body.strip() == summary_text.strip():
                        new_content = cleaned_existing + "\n"
                        if old_content == new_content:
                            continue
                update_block = f"\n\n## Update\n{summary_text}\n"
                if cleaned_existing.endswith(update_block.strip("\n")):
                    # The last update already matches the incoming summary.
                    new_content = cleaned_existing + "\n"
                else:
                    new_content = f"{cleaned_existing}{update_block}"

        if old_content == new_content:
            continue

        if not new_content.endswith("\n"):
            new_content = f"{new_content}\n"
        files.append(
            ChangesetFile(
                path=str(target.relative_to(repo_path)),
                old=old_content,
                new=new_content,
            )
        )
        entity_updates += 1

    timeline_change = _plan_timeline_updates(incoming.events, repo_path, files)

    summary = (
        "No universe files require updates"
        if not files
        else (
            "Planned updates for "
            + ", ".join(
                filter(
                    None,
                    [
                        f"{entity_updates} entity file(s)" if entity_updates else "",
                        f"{timeline_change} timeline entry(ies)"
                        if timeline_change
                        else "",
                    ],
                )
            )
            + "."
        )
    )
    return Changeset(files=files, summary=summary)


def _plan_timeline_updates(
    events: Iterable[FactEvent],
    repo_path: Path,
    files: List[ChangesetFile],
) -> int:
    event_list = [event for event in events if event.title]
    if not event_list:
        return 0

    timeline_path, old_content, base_content = _load_timeline(repo_path)

    existing_lines = base_content.splitlines()
    header, existing_events, footer = _split_timeline(existing_lines)
    existing_line_set = {item["line"].strip() for item in existing_events}
    existing_keys = {
        _normalize_date_key(item["date"], _slugify(item["title"]))
        for item in existing_events
    }

    additions: list[dict[str, str | None]] = []
    for event in event_list:
        line = _format_event_line(event)
        stripped = line.strip()
        date = event.date or _extract_date_from_line(stripped)
        slug = _slugify(event.title)
        key = _normalize_date_key(date, slug)
        if stripped in existing_line_set or key in existing_keys:
            continue
        additions.append({"date": date, "title": event.title, "line": stripped})
        existing_keys.add(key)

    if not additions:
        return 0

    merged_events = existing_events + additions
    merged_events.sort(
        key=lambda item: _normalize_date_key(
            item.get("date"), _slugify(str(item.get("title", "")))
        )
    )

    rebuilt_lines: list[str] = []
    rebuilt_lines.extend(header)
    if header and header[-1].strip():
        rebuilt_lines.append("")
    rebuilt_lines.extend(item["line"] for item in merged_events)
    if footer:
        if rebuilt_lines and rebuilt_lines[-1].strip():
            rebuilt_lines.append("")
        rebuilt_lines.extend(footer)

    new_content = "\n".join(rebuilt_lines)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    files.append(
        ChangesetFile(
            path=str(timeline_path.relative_to(repo_path)),
            old=old_content,
            new=new_content,
        )
    )
    return len(additions)


def _load_timeline(repo_path: Path) -> tuple[Path, str | None, str]:
    for candidate in (repo_path / "timeline.md", repo_path / "timeline.txt"):
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
            return candidate, text, text

    template_text = (
        TEMPLATE_TIMELINE.read_text(encoding="utf-8")
        if TEMPLATE_TIMELINE.is_file()
        else "# Timeline\n"
    )
    timeline_path = repo_path / "timeline.md"
    return timeline_path, None, template_text


def _split_timeline(
    lines: List[str],
) -> tuple[List[str], List[dict[str, str | None]], List[str]]:
    header: list[str] = []
    events: list[dict[str, str | None]] = []
    footer: list[str] = []
    event_started = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            date = _extract_date_from_line(stripped)
            title = _extract_title_from_line(stripped)
            events.append({"date": date, "title": title, "line": stripped})
            event_started = True
        else:
            if not event_started:
                header.append(line)
            else:
                footer.append(line)
    return header, events, footer


def _format_event_line(event: FactEvent) -> str:
    parts = []
    if event.date:
        parts.append(event.date.strip())
    title = event.title.strip()
    parts.append(title)
    if event.location:
        parts.append(f"@ {event.location}")
    if event.description:
        parts.append(f"– {event.description.strip()}")
    return " ".join(parts)


def _extract_date_from_line(line: str) -> str | None:
    match = _TIMELINE_DATE_PATTERN.match(line)
    if match:
        return match.group("date").strip()
    return None


def _extract_title_from_line(line: str) -> str:
    match = _TIMELINE_DATE_PATTERN.match(line)
    if match:
        remainder = match.group("title").strip()
        return remainder or line
    return line


_TIMELINE_DATE_PATTERN = re.compile(
    r"^(?P<date>(?:\d{3,4}(?:[\-/]\d{1,2}){0,2}|(?:jaro|léto|leto|podzim|zima|spring|summer|autumn|fall|winter)\s+\d{3,4}))?\s*(?:[-–—:]\s*)?(?P<title>.+)$",
    flags=re.IGNORECASE,
)


def _normalize_date_key(raw: str | None, slug: str) -> Tuple[int, int, int, str]:
    slug = slug or ""
    if not raw:
        return (9999, 12, 31, slug)

    text = raw.strip().lower()
    season_map = {
        "zima": 1,
        "winter": 1,
        "jaro": 4,
        "spring": 4,
        "léto": 7,
        "leto": 7,
        "summer": 7,
        "podzim": 10,
        "autumn": 10,
        "fall": 10,
    }

    year = 9999
    month = 12
    day = 31

    match = re.search(r"(\d{3,4})", text)
    if match:
        year = int(match.group(1))

    if "-" in text or "/" in text:
        parts = re.split(r"[-/]", text)
        try:
            if len(parts) > 1 and parts[1].isdigit():
                month = int(parts[1])
            if len(parts) > 2 and parts[2].isdigit():
                day = int(parts[2])
        except ValueError:
            month = 12
            day = 31
    else:
        for season, value in season_map.items():
            if season in text:
                month = value
                day = 0
                break
    return (year, month, day, slug)


def _date_from_key(key: Tuple[int, int, int, str]) -> str | None:
    year, month, day, slug = key
    if year == 9999:
        return None
    if day == 31 and month == 12:
        return str(year)
    if day == 0:
        return str(year)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _title_from_line(line: str) -> str:
    return _extract_title_from_line(line)


__all__ = ["PlannerEngine", "PLANNER_SYSTEM_PROMPT", "plan_changes"]
