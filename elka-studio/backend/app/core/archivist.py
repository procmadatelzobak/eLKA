"""Story archival utilities executed inside Celery workers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

from app.adapters.ai.base import BaseAIAdapter
from app.adapters.git.base import GitAdapter
from app.utils.config import Config
from app.utils.filesystem import sanitize_filename

from .extractor import _slugify, extract_story_entities
from .schemas import (
    EntityType,
    ExtractedData,
    ExtractedEntity,
    ExtractedEvent,
    FactEntity,
    FactEvent,
    FactGraph,
)

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates" / "universe_scaffold"

logger = logging.getLogger(__name__)

EntityRecord = Union[ExtractedEntity, ExtractedEvent]


@dataclass(slots=True)
class ArchiveResult:
    """Result returned by the archivist when persisting a story."""

    success: bool
    files: Dict[str, str]
    metadata: Dict[str, str]
    log_messages: List[str]


class ArchivistEngine:
    """Persist validated stories into the lore repository."""

    def __init__(self, git_adapter: GitAdapter, ai_adapter: BaseAIAdapter, config: Config) -> None:
        self.git_adapter = git_adapter
        self.ai_adapter = ai_adapter
        self.config = config
        self.project_path = self.git_adapter.project_path

    def archive(
        self,
        story_content: str,
        universe_files: dict[str, str] | None = None,
    ) -> ArchiveResult:
        """Return the files to be committed and relevant metadata.

        The ``universe_files`` argument is accepted to support future
        contextual archival strategies.  The current implementation focuses on
        the generated story alone, but Celery tasks can already provide the
        additional information.
        """

        summary = self.ai_adapter.summarise(story_content)
        slug = self._slugify(summary) or "story"
        filename = self.config.story_filename(prefix=slug)
        relative_path = str(self.config.story_directory / filename)
        # Ensure the directory exists prior to returning the files
        self.config.ensure_story_directory(self.git_adapter.project_path)
        document = self._build_document(story_content, summary)

        files = {relative_path: document}
        metadata = {
            "summary": summary,
            "filename": filename,
            "relative_path": relative_path,
            "timestamp": datetime.utcnow().isoformat(),
        }
        log_messages = [f"Story archived to {relative_path}"]

        extracted_files = {}
        extracted_data: Optional[ExtractedData] = None
        try:
            extracted_data = extract_story_entities(story_content, self.ai_adapter)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to extract entities from story: %s", exc)

        if extracted_data is not None:
            logger.info(
                "Archiving extracted data: %s",
                extracted_data.model_dump_json(indent=2),
            )
            if (
                not extracted_data.characters
                and not extracted_data.locations
                and not extracted_data.events
            ):
                logger.warning("No entities were extracted to archive.")
            extracted_files = self._archive_extracted_data(extracted_data)
            files.update(extracted_files)
            if extracted_files:
                log_messages.append(
                    f"Archived {len(extracted_files)} extracted entity files."
                )

        return ArchiveResult(success=True, files=files, metadata=metadata, log_messages=log_messages)

    def _archive_extracted_data(self, extracted_data: ExtractedData) -> Dict[str, str]:
        """Persist extracted entities and return the written files."""

        archived: Dict[str, str] = {}

        if extracted_data.characters:
            logger.info("Archiving %s characters...", len(extracted_data.characters))
            for character in extracted_data.characters:
                logger.debug("Attempting to archive character: %s", character.name)
                result = self._archive_entity(character, EntityType.CHARACTER)
                if result:
                    path, content = result
                    archived[path] = content

        if extracted_data.locations:
            logger.info("Archiving %s locations...", len(extracted_data.locations))
            for location in extracted_data.locations:
                logger.debug("Attempting to archive location: %s", location.name)
                result = self._archive_entity(location, EntityType.LOCATION)
                if result:
                    path, content = result
                    archived[path] = content

        if extracted_data.events:
            logger.info("Archiving %s events...", len(extracted_data.events))
            for event in extracted_data.events:
                logger.debug("Attempting to archive event: %s", event.name)
                result = self._archive_entity(event, EntityType.EVENT)
                if result:
                    path, content = result
                    archived[path] = content

        if extracted_data.concepts:
            logger.info("Archiving %s concepts...", len(extracted_data.concepts))
            for concept in extracted_data.concepts:
                logger.debug("Attempting to archive concept: %s", concept.name)
                result = self._archive_entity(concept, EntityType.CONCEPT)
                if result:
                    path, content = result
                    archived[path] = content

        if extracted_data.things:
            logger.info("Archiving %s items...", len(extracted_data.things))
            for thing in extracted_data.things:
                logger.debug("Attempting to archive item: %s", thing.name)
                result = self._archive_entity(thing, EntityType.ITEM)
                if result:
                    path, content = result
                    archived[path] = content

        if extracted_data.materials:
            logger.info("Archiving %s materials...", len(extracted_data.materials))
            for material in extracted_data.materials:
                logger.debug("Attempting to archive material: %s", material.name)
                result = self._archive_entity(material, EntityType.MATERIAL)
                if result:
                    path, content = result
                    archived[path] = content

        if extracted_data.others:
            logger.info("Archiving %s uncategorised entities...", len(extracted_data.others))
            for entity in extracted_data.others:
                logger.debug("Attempting to archive entity: %s", entity.name)
                result = self._archive_entity(entity, EntityType.OTHER)
                if result:
                    path, content = result
                    archived[path] = content

        return archived

    def _archive_entity(
        self,
        entity: EntityRecord,
        entity_type: EntityType,
    ) -> Optional[Tuple[str, str]]:
        """Write an entity file to disk and return the relative path and content."""

        name = getattr(entity, "name", None) or getattr(entity, "id", "entity")
        sanitized_name = sanitize_filename(name, default="entity")
        subdir = self._entity_subdirectory(entity_type)
        file_path = self.project_path / "Objekty" / subdir / f"{sanitized_name}.txt"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._render_entity_content(entity, entity_type)

        logger.info("Writing entity file: %s", file_path)
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(content)
            logger.info("Successfully wrote entity file: %s", file_path)
        except OSError as exc:  # pragma: no cover - filesystem interaction
            logger.error("Failed to write entity file %s: %s", file_path, exc)
            return None
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "An unexpected error occurred while writing entity file %s: %s",
                file_path,
                exc,
            )
            return None

        relative = file_path.relative_to(self.project_path)
        return str(relative), content

    @staticmethod
    def _entity_subdirectory(entity_type: EntityType) -> str:
        mapping = {
            EntityType.CHARACTER: "beings",
            EntityType.LOCATION: "places",
            EntityType.EVENT: "events",
            EntityType.CONCEPT: "concepts",
            EntityType.ITEM: "things",
            EntityType.MATERIAL: "materials",
            EntityType.ORGANIZATION: "organizations",
            EntityType.OTHER: "misc",
        }
        return mapping.get(entity_type, "misc")

    def _render_entity_content(
        self,
        entity: EntityRecord,
        entity_type: EntityType,
    ) -> str:
        if isinstance(entity, ExtractedEvent) or entity_type == EntityType.EVENT:
            event = entity if isinstance(entity, ExtractedEvent) else None
            if event is None and isinstance(entity, ExtractedEntity):
                event = ExtractedEvent(
                    id=entity.id,
                    name=entity.name,
                    summary=entity.summary,
                    description=entity.description,
                )
            return self._render_event_content(event)

        if not isinstance(entity, ExtractedEntity):
            return "\n"  # Fallback to empty file

        lines: list[str] = [entity.name]

        details_added = False
        if entity.description and entity.description.strip():
            lines.extend(["", entity.description.strip()])
            details_added = True
        elif entity.summary and entity.summary.strip():
            lines.extend(["", entity.summary.strip()])
            details_added = True

        if entity.aliases:
            lines.append("")
            lines.append("Aliases: " + ", ".join(sorted({alias.strip() for alias in entity.aliases if alias.strip()})))
            details_added = True

        if entity.attributes:
            lines.append("")
            for key, value in entity.attributes.items():
                lines.append(f"{key}: {value}")
            details_added = True

        if not details_added:
            lines.append("")
            lines.append("No additional details provided.")

        content = "\n".join(lines).strip() + "\n"
        return content

    @staticmethod
    def _render_event_content(event: Optional[ExtractedEvent]) -> str:
        if event is None:
            return "\n"

        lines: list[str] = [event.name]

        if event.description and event.description.strip():
            lines.extend(["", event.description.strip()])
        elif event.summary and event.summary.strip():
            lines.extend(["", event.summary.strip()])

        metadata_lines: list[str] = []
        if event.date:
            metadata_lines.append(f"Date: {event.date}")
        if event.location:
            metadata_lines.append(f"Location: {event.location}")
        if metadata_lines:
            lines.append("")
            lines.extend(metadata_lines)

        if event.participants:
            lines.append("")
            participants = ", ".join(sorted({participant for participant in event.participants if participant}))
            lines.append(f"Participants: {participants}")

        content = "\n".join(lines).strip() + "\n"
        return content

    @staticmethod
    def _slugify(value: str) -> str:
        sanitized = sanitize_filename(value, default="story")
        return sanitized[:40]

    @staticmethod
    def _build_document(story_content: str, summary: str) -> str:
        header = "---\n"
        header += f"summary: \"{summary.replace('\\', '\\\\').replace('"', '\\"')}\"\n"
        header += f"generated_at: {datetime.utcnow().isoformat()}\n"
        header += "---\n\n"
        return f"{header}{story_content.strip()}\n"


def _parse_front_matter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.+?)\n---\n", text, flags=re.DOTALL)
    if not match:
        return {}
    attributes: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        attributes[key.strip().lower()] = value.strip().strip('"')
    return attributes


def _parse_attribute_block(text: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    attribute_section = re.search(
        r"(?im)^(?:##\s+)?(?:atributy|attributes)\s*:?.*$([\s\S]+)",
        text,
    )
    if not attribute_section:
        return attributes
    for line in attribute_section.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            attributes[key.strip().lower()] = value.strip()
    return attributes


def _extract_core_truths(paths: Iterable[Path]) -> list[str]:
    truths: list[str] = []
    bullet_pattern = re.compile(r"^[\s>*-]*[-*+]\s+(?P<truth>.+)$")
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            match = bullet_pattern.match(line.strip())
            if match:
                truths.append(match.group("truth").strip())
    return truths


def _collect_truth_sources(repo_path: Path) -> list[Path]:
    sources: list[Path] = []
    core_truths_template = TEMPLATES_ROOT / "Legends" / "CORE_TRUTHS.md"
    sources.append(core_truths_template)
    legendy_dir = repo_path / "Legendy"
    if legendy_dir.is_dir():
        sources.extend(sorted(legendy_dir.glob("*.md")))
    return sources


def _timeline_candidates(repo_path: Path) -> list[Path]:
    return [repo_path / "timeline.md", repo_path / "timeline.txt"]


def _parse_timeline_events(text: str) -> list[FactEvent]:
    events: list[FactEvent] = []
    line_pattern = re.compile(
        r"^(?P<date>(?:\d{3,4}(?:[\-/]\d{1,2}){0,2}|(?:jaro|léto|leto|podzim|zima|spring|summer|autumn|fall|winter)\s+\d{3,4}))?\s*(?:[-–—:]\s*)?(?P<title>.+)$",
        flags=re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = line_pattern.match(stripped)
        if not match:
            continue
        date = match.group("date")
        title = match.group("title").strip()
        events.append(
            FactEvent(
                id=_slugify(stripped),
                title=title or stripped,
                date=date.strip() if date else None,
            )
        )
    return events


def load_universe(repo_path: Path) -> FactGraph:
    """Parse the existing universe files into a :class:`FactGraph`."""

    entities: list[FactEntity] = []
    events: list[FactEvent] = []

    objekty_dir = repo_path / "Objekty"
    if objekty_dir.is_dir():
        for path in sorted(objekty_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
            entity_type = "place" if "place" in path.stem.lower() else "other"
            attributes = {**_parse_front_matter(text), **_parse_attribute_block(text)}
            entities.append(
                FactEntity(
                    id=_slugify(path.stem),
                    type=entity_type,
                    summary=titles[0] if titles else path.stem,
                    attributes=attributes,
                )
            )

    legendy_dir = repo_path / "Legendy"
    if legendy_dir.is_dir():
        for path in sorted(legendy_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
            attributes = {**_parse_front_matter(text), **_parse_attribute_block(text)}
            entities.append(
                FactEntity(
                    id=_slugify(path.stem),
                    type="concept",
                    summary=titles[0] if titles else path.stem,
                    attributes=attributes,
                )
            )

    for timeline_path in _timeline_candidates(repo_path):
        if not timeline_path.is_file():
            continue
        text = timeline_path.read_text(encoding="utf-8")
        events.extend(_parse_timeline_events(text))

    core_truth_sources = _collect_truth_sources(repo_path)
    core_truths = _extract_core_truths(core_truth_sources)

    return FactGraph(entities=entities, events=events, core_truths=core_truths)


__all__ = ["ArchiveResult", "ArchivistEngine", "load_universe"]
