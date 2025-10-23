"""Story archival utilities executed inside Celery workers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import frontmatter
import yaml
from pydantic import ValidationError

try:
    from frontmatter import FrontmatterError
except ImportError:  # pragma: no cover - fallback
    class FrontmatterError(Exception):
        """Fallback error when python-frontmatter is unavailable."""

        pass

from app.adapters.ai.base import BaseAIAdapter
from app.adapters.git.base import GitAdapter
from app.utils.config import Config
from app.utils.filesystem import sanitize_filename

from git.exc import GitCommandError

from .extractor import _slugify, extract_story_entities
from .schemas import (
    EntityType,
    ExtractedData,
    ExtractedEntity,
    ExtractedEvent,
    FactEvent,
    FactGraph,
)
from ..core.schemas import FactEntity

TEMPLATES_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "universe_scaffold"
)

logger = logging.getLogger(__name__)

EntityRecord = Union[ExtractedEntity, ExtractedEvent]


_ENTITY_DIRECTORY_MAP: dict[str, tuple[str, str]] = {
    "character": ("Characters", "Character"),
    "characters": ("Characters", "Character"),
    "person": ("Characters", "Character"),
    "location": ("Locations", "Location"),
    "locations": ("Locations", "Location"),
    "place": ("Locations", "Location"),
    "event": ("Events", "Event"),
    "events": ("Events", "Event"),
    "concept": ("Concepts", "Concept"),
    "concepts": ("Concepts", "Concept"),
    "idea": ("Concepts", "Concept"),
    "item": ("Items", "Item"),
    "items": ("Items", "Item"),
    "artifact": ("Items", "Item"),
    "thing": ("Items", "Item"),
    "material": ("Misc", "Material"),
    "materials": ("Misc", "Material"),
    "organization": ("Misc", "Organization"),
    "organizations": ("Misc", "Organization"),
    "organisation": ("Misc", "Organization"),
    "organisations": ("Misc", "Organization"),
    "misc": ("Misc", "Misc"),
    "other": ("Misc", "Misc"),
}


@dataclass(slots=True)
class ArchiveResult:
    """Result returned by the archivist when persisting a story."""

    success: bool
    files: Dict[str, str]
    metadata: Dict[str, str]
    log_messages: List[str]
    changed_paths: List[str] = field(default_factory=list)


class ArchivistEngine:
    """Persist validated stories into the lore repository."""

    def __init__(
        self,
        git_adapter: GitAdapter,
        ai_adapter: BaseAIAdapter,
        config: Config,
        *,
        model_overrides: dict[str, str] | None = None,
    ) -> None:
        self.git_adapter = git_adapter
        self.ai_adapter = ai_adapter
        self.config = config
        self.project_path = self.git_adapter.project_path
        self._model_overrides = model_overrides or {}

    def archive(
        self,
        story_content: str,
        *,
        story_file_path: Path,
        universe_context: str | None = None,
        task_id: int | None = None,
        saga_theme: str | None = None,
    ) -> ArchiveResult:
        """Write the story to ``story_file_path`` and prepare metadata for committing.

        Saga themes are slugified before creating directories to keep paths portable.
        """

        summary = self.ai_adapter.summarise(story_content)

        provided_path = Path(story_file_path)
        saga_slug: str | None = None
        saga_directory: Path | None = None
        configured_directory = self.config.story_directory
        if configured_directory == Path("stories"):
            story_directory = Path("Stories")
        else:
            story_directory = configured_directory

        if provided_path.is_absolute():
            target_path = provided_path
        else:
            extension = provided_path.suffix or ".md"
            stem = provided_path.stem or provided_path.name or "story"
            sanitized_stem = sanitize_filename(stem, default="story")
            filename = f"{sanitized_stem}{extension}"
            if saga_theme:
                saga_slug = self._slugify(str(saga_theme)) or "saga"
                saga_directory = story_directory / saga_slug
                target_path = saga_directory / filename
            else:
                target_path = story_directory / filename

        absolute_path = (
            target_path
            if target_path.is_absolute()
            else self.project_path / target_path
        )

        try:
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            absolute_path.write_text(story_content, encoding="utf-8")
            logger.info("Story file saved: %s", absolute_path)
        except OSError as exc:
            logger.error("Failed to write story file %s: %s", absolute_path, exc)
            fallback_directory = self.config.ensure_story_directory(self.project_path)
            if (
                fallback_directory.name.lower() == "stories"
                and fallback_directory.name != "Stories"
            ):
                fallback_directory = fallback_directory.parent / "Stories"
                fallback_directory.mkdir(parents=True, exist_ok=True)
            if saga_slug:
                fallback_directory = fallback_directory / saga_slug
                fallback_directory.mkdir(parents=True, exist_ok=True)
            fallback_name = target_path.stem or "story"
            fallback_path = fallback_directory / self.config.story_filename(
                fallback_name
            )
            try:
                fallback_path.write_text(story_content, encoding="utf-8")
                logger.info("Story file saved to fallback path: %s", fallback_path)
                absolute_path = fallback_path
            except OSError as fallback_exc:
                logger.error(
                    "Fallback write failed for story file %s: %s",
                    fallback_path,
                    fallback_exc,
                )
                raise

        try:
            relative_path_obj = absolute_path.relative_to(self.project_path)
        except ValueError:
            relative_path_obj = absolute_path

        relative_path = str(relative_path_obj)
        files = {relative_path: story_content}
        front_matter = _parse_front_matter(story_content)
        metadata = {
            "summary": summary,
            "filename": relative_path_obj.name,
            "relative_path": relative_path,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if saga_slug:
            metadata["saga_folder"] = str(saga_directory)
            metadata["saga_theme"] = saga_theme or ""
        for key in ("title", "author", "seed", "project"):
            if key in front_matter:
                metadata[key] = front_matter[key]
        log_messages = [f"Story archived to {relative_path}"]
        if task_id is not None:
            metadata["task_id"] = str(task_id)

        extracted_files = {}
        extracted_data: Optional[ExtractedData] = None
        try:
            extracted_data = extract_story_entities(
                story_content,
                self.ai_adapter,
                universe_context=universe_context,
                model_key=self._model_overrides.get("extraction"),
            )
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
            timeline_messages = self._update_timeline(extracted_data.events)
            log_messages.extend(timeline_messages)

        changed_paths = [relative_path]
        changed_paths.extend(extracted_files.keys())

        return ArchiveResult(
            success=True,
            files=files,
            metadata=metadata,
            log_messages=log_messages,
            changed_paths=sorted(set(changed_paths)),
        )

    def commit_to_branch(
        self,
        *,
        task_id: int,
        commit_message: str,
        expected_files: Optional[Iterable[str]] = None,
    ) -> tuple[str, List[str]]:
        """Stage changes, commit them on a dedicated branch, and push to origin."""

        branch_name = self._prepare_branch_name(task_id)
        base_branch = self.config.default_branch
        logger.debug("Preparing branch '%s' based on '%s'", branch_name, base_branch)
        self.git_adapter.create_branch(branch_name, base=base_branch)

        changed_paths = set(expected_files or [])
        changed_paths.update(self._collect_changed_paths())

        if not changed_paths:
            logger.info(
                "No repository changes detected for task %s; skipping commit.", task_id
            )
            self._checkout_default_branch()
            return branch_name, []

        try:
            self.git_adapter.repo.index.add(sorted(changed_paths))
        except GitCommandError as exc:
            logger.error("Failed to stage files for task %s: %s", task_id, exc)
            raise

        if not self.git_adapter.repo.is_dirty(
            index=True, working_tree=True, untracked_files=True
        ):
            logger.info(
                "Repository clean after staging for task %s; nothing to commit.",
                task_id,
            )
            self._checkout_default_branch()
            return branch_name, sorted(changed_paths)

        commit = self.git_adapter.repo.index.commit(commit_message)
        try:
            self.git_adapter.push_branch(branch_name)
        except Exception:
            # Attempt to switch back even when push fails
            self._checkout_default_branch()
            raise

        logger.info(
            "Changes for task %s pushed to branch: %s (commit %s)",
            task_id,
            branch_name,
            commit.hexsha,
        )
        self._checkout_default_branch()
        return branch_name, sorted(changed_paths)

    def _prepare_branch_name(self, task_id: int) -> str:
        base_name = f"elka-task-{task_id}"
        existing = {head.name for head in self.git_adapter.repo.branches}
        if base_name not in existing:
            return base_name

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        counter = 1
        candidate = f"{base_name}-{timestamp}"
        while candidate in existing:
            counter += 1
            candidate = f"{base_name}-{timestamp}-{counter}"
        return candidate

    def _collect_changed_paths(self) -> List[str]:
        try:
            status_output = self.git_adapter.repo.git.status("--porcelain")
        except GitCommandError as exc:
            logger.error("Failed to inspect repository status: %s", exc)
            return []

        paths: List[str] = []
        for raw_line in status_output.splitlines():
            if not raw_line:
                continue
            if len(raw_line) <= 3:
                continue

            entry = raw_line[3:]
            # ``git status --porcelain`` always separates the status and the
            # path with at least one space. Still, we defensively strip
            # whitespace so that we do not accidentally truncate the leading
            # character of the path when unusual whitespace appears.
            entry = entry.lstrip()

            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1]
            entry = entry.strip()
            if entry:
                paths.append(entry)
        return paths

    def _checkout_default_branch(self) -> None:
        target_branch = self.config.default_branch
        try:
            self.git_adapter.repo.git.checkout(target_branch)
        except GitCommandError as exc:
            logger.warning(
                "Failed to checkout default branch '%s': %s", target_branch, exc
            )

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
            logger.info(
                "Archiving %s uncategorised entities...", len(extracted_data.others)
            )
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

        prepared = self._prepare_fact_entity(entity, entity_type)
        if prepared is None:
            logger.warning("Unable to archive entity without a valid identifier: %s", entity)
            return None

        fact_entity, subfolder = prepared
        filename = f"{fact_entity.id}.md"
        entity_directory = Path("Entities") / subfolder
        absolute_directory_path = self.project_path / entity_directory
        absolute_directory_path.mkdir(parents=True, exist_ok=True)
        file_path = absolute_directory_path / filename
        content = self._format_document(fact_entity)

        logger.info("Writing entity file: %s", file_path)
        try:
            file_path.write_text(content, encoding="utf-8")
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

        relative_path = entity_directory / filename
        return relative_path.as_posix(), content

    def _prepare_fact_entity(
        self,
        entity: EntityRecord | FactEntity,
        fallback_type: EntityType,
    ) -> Optional[tuple[FactEntity, str]]:
        """Normalise extracted entities into :class:`FactEntity` instances."""

        entity_id = getattr(entity, "id", None)
        if not entity_id:
            return None

        raw_type = getattr(entity, "type", None)
        if isinstance(raw_type, EntityType):
            raw_type_value = raw_type.value
        else:
            raw_type_value = str(raw_type or "").strip().lower()

        if not raw_type_value and isinstance(entity, ExtractedEntity):
            raw_type_value = entity.entity_type.value
        if not raw_type_value:
            raw_type_value = fallback_type.value

        directory, canonical_type = _ENTITY_DIRECTORY_MAP.get(
            raw_type_value.lower(),
            ("Misc", "Misc"),
        )

        name = (
            getattr(entity, "name", None)
            or getattr(entity, "title", None)
            or str(entity_id)
        )
        summary = getattr(entity, "summary", None)
        description = getattr(entity, "description", None)
        if description is None and isinstance(entity, ExtractedEvent):
            description = summary

        aliases = list(getattr(entity, "aliases", []) or [])

        relationships_obj = getattr(entity, "relationships", {}) or {}
        if not isinstance(relationships_obj, dict):
            relationships_obj = {}
        relationships = {
            str(key): str(value)
            for key, value in relationships_obj.items()
            if key
        }

        attributes_obj = getattr(entity, "attributes", {}) or {}
        if not isinstance(attributes_obj, dict):
            attributes_obj = {}
        attributes = {str(key): value for key, value in attributes_obj.items() if key}

        if isinstance(entity, ExtractedEvent):
            if entity.date:
                attributes.setdefault("date", entity.date)
            if entity.location:
                attributes.setdefault("location", entity.location)
            if entity.participants:
                attributes.setdefault("participants", list(entity.participants))

        fact_entity = (
            entity
            if isinstance(entity, FactEntity)
            else FactEntity(
                id=str(entity_id),
                type=canonical_type,
                name=str(name),
                summary=summary,
                description=description,
                aliases=aliases,
                relationships=relationships,
                attributes=attributes,
            )
        )

        if isinstance(entity, FactEntity):
            fact_entity = entity.model_copy(
                update={
                    "type": canonical_type,
                    "name": entity.name or str(name),
                    "summary": summary if summary is not None else entity.summary,
                    "description": description
                    if description is not None
                    else entity.description,
                    "aliases": aliases or entity.aliases,
                    "relationships": relationships or entity.relationships,
                    "attributes": attributes or entity.attributes,
                }
            )

        return fact_entity, directory

    def _format_document(self, entity: FactEntity) -> str:
        """Generate YAML front matter and Markdown body for an entity file."""

        yaml_data: dict[str, object] = {
            "id": entity.id,
            "type": entity.type,
            "name": entity.name or entity.id,
        }

        if entity.aliases:
            yaml_data["aliases"] = [alias for alias in entity.aliases if alias]
        if entity.summary:
            yaml_data["summary"] = entity.summary
        if entity.relationships:
            yaml_data["relationships"] = {
                str(rel_id): str(rel_desc)
                for rel_id, rel_desc in entity.relationships.items()
                if rel_id
            }
        if entity.attributes:
            yaml_data["attributes"] = entity.attributes

        yaml_string = yaml.dump(
            yaml_data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

        markdown_content = (entity.description or "").strip()
        if not markdown_content and entity.summary:
            markdown_content = entity.summary.strip()

        final_content = f"---\n{yaml_string}---\n"
        if markdown_content:
            final_content += f"\n{markdown_content}\n"
        else:
            final_content += "\n"
        return final_content

    def _update_timeline(self, events: List[ExtractedEvent]) -> List[str]:
        """Append extracted events to the project timeline when available."""

        if not events:
            return []

        candidates = _timeline_candidates(self.project_path)
        timeline_path: Path | None = None
        for candidate in candidates:
            if candidate.exists():
                timeline_path = candidate
                break
        if timeline_path is None:
            # Default to a plain-text timeline when none exists yet.
            timeline_path = self.project_path / "timeline.txt"

        try:
            existing_text = (
                timeline_path.read_text(encoding="utf-8")
                if timeline_path.exists()
                else ""
            )
        except OSError as exc:  # pragma: no cover - filesystem interaction
            logger.error("Failed to read timeline %s: %s", timeline_path, exc)
            existing_text = ""

        existing_lower = existing_text.lower()
        new_entries: list[str] = []
        for event in events:
            event_id = (event.id or event.name or "").strip()
            if not event_id:
                continue
            marker = f"[{event_id}]".lower()
            if marker and marker in existing_lower:
                logger.debug("Timeline already contains event %s; skipping.", event_id)
                continue

            title = event.name or event_id.replace("_", " ").title()
            if event.date:
                title = f"{event.date} – {title}"

            descriptors: list[str] = []
            summary = (event.description or event.summary or "").strip()
            if summary:
                descriptors.append(summary)
            if event.location:
                descriptors.append(f"Location: {event.location}")
            participants = ", ".join(
                sorted(
                    {participant for participant in event.participants if participant}
                )
            )
            if participants:
                descriptors.append(f"Participants: {participants}")

            descriptor_text = f" — {'; '.join(descriptors)}" if descriptors else ""
            entry = f"- [{event_id}] {title}{descriptor_text}"
            new_entries.append(entry)

        if not new_entries:
            return []

        append_lines: list[str] = []
        if not existing_text.strip():
            append_lines.append("# Timeline")
            append_lines.append("")
        elif not existing_text.endswith("\n"):
            append_lines.append("")

        append_lines.extend(new_entries)
        text_to_append = "\n".join(append_lines)
        if not text_to_append.endswith("\n"):
            text_to_append += "\n"

        try:
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            with timeline_path.open("a", encoding="utf-8") as handle:
                handle.write(text_to_append)
        except OSError as exc:  # pragma: no cover - filesystem interaction
            logger.error("Failed to update timeline %s: %s", timeline_path, exc)
            return []

        relative_path = timeline_path.relative_to(self.project_path)
        message = (
            f"Timeline updated with {len(new_entries)} event(s) in {relative_path}."
        )
        logger.info(message)
        return [message]

    @staticmethod
    def _slugify(value: str) -> str:
        sanitized = sanitize_filename(value, default="story")
        return sanitized[:40]


def _parse_front_matter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.+?)\n---\n", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group("body")) or {}
    except yaml.YAMLError:  # pragma: no cover - defensive parsing
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items()}


def _extract_markdown_body(text: str) -> str:
    match = re.match(r"^---\n.+?\n---\n(?P<body>[\s\S]*)", text, flags=re.DOTALL)
    if not match:
        return text.strip()
    return match.group("body").strip()


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
    template_candidates = [
        TEMPLATES_ROOT / "Canon" / "CoreTruths.md",
        TEMPLATES_ROOT / "Legends" / "CORE_TRUTHS.md",
    ]
    for candidate in template_candidates:
        if candidate.is_file() and candidate not in sources:
            sources.append(candidate)

    canon_dir = repo_path / "Canon"
    if canon_dir.is_dir():
        sources.extend(sorted(canon_dir.glob("*.md")))

    legacy_dir = repo_path / "Legendy"
    if legacy_dir.is_dir():
        sources.extend(sorted(legacy_dir.glob("*.md")))

    return sources


def _timeline_candidates(repo_path: Path) -> list[Path]:
    return [
        repo_path / "Metadata" / "Timeline.md",
        repo_path / "timeline.md",
        repo_path / "timeline.txt",
    ]


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

    entity_index: dict[str, FactEntity] = {}
    events: list[FactEvent] = []

    entities_dir = repo_path / "Entities"
    if entities_dir.is_dir():
        entity_paths = sorted(entities_dir.rglob('*.md'))
        for path in entity_paths:
            if not path.is_file():
                continue
            try:
                post = frontmatter.load(path)
            except (yaml.YAMLError, FrontmatterError) as exc:
                logger.warning('Failed to parse entity front matter %s: %s', path, exc)
                continue
            except OSError as exc:
                logger.warning('Failed to read entity file %s: %s', path, exc)
                continue

            metadata = post.metadata or {}
            if not isinstance(metadata, dict):
                metadata = {}

            missing_fields = [
                key
                for key in ('id', 'type', 'name')
                if key not in metadata or not str(metadata.get(key) or '').strip()
            ]
            if missing_fields:
                logger.warning(
                    'Skipping entity file %s due to missing fields: %s',
                    path,
                    ', '.join(missing_fields),
                )
                continue

            entity_id = str(metadata.get('id')).strip()
            raw_type = metadata.get('type')
            type_key = str(raw_type or '').strip().lower()

            try:
                relative_path = path.relative_to(entities_dir)
                if len(relative_path.parts) > 1:
                    directory_hint = relative_path.parts[0]
                else:
                    directory_hint = path.parent.name
            except ValueError:
                directory_hint = path.parent.name

            directory_hint = str(directory_hint)
            if not type_key:
                type_key = directory_hint.strip().lower()

            canonical_type = _ENTITY_DIRECTORY_MAP.get(
                type_key,
                (directory_hint, str(raw_type or directory_hint)),
            )[1]

            raw_aliases = metadata.get('aliases', [])
            if isinstance(raw_aliases, list):
                alias_candidates = raw_aliases
            elif raw_aliases:
                alias_candidates = [raw_aliases]
            else:
                alias_candidates = []
            aliases = [
                str(alias).strip()
                for alias in alias_candidates
                if str(alias).strip()
            ]

            relationships_raw = metadata.get('relationships', {})
            if not isinstance(relationships_raw, dict):
                relationships_raw = {}
            relationships = {
                str(key): str(value)
                for key, value in relationships_raw.items()
                if str(key).strip()
            }

            attributes_raw = metadata.get('attributes', {})
            if not isinstance(attributes_raw, dict):
                attributes_raw = {}

            additional_fields: dict[str, object] = {}
            for key, value in metadata.items():
                if key in {
                    'id',
                    'type',
                    'name',
                    'aliases',
                    'summary',
                    'description',
                    'relationships',
                    'attributes',
                }:
                    continue
                additional_fields[str(key)] = value

            if additional_fields:
                attributes_raw = {**attributes_raw, **additional_fields}

            attributes_clean = {str(key): value for key, value in attributes_raw.items()}

            summary = None
            raw_summary = metadata.get('summary')
            if isinstance(raw_summary, str) and raw_summary.strip():
                summary = raw_summary.strip()

            content = post.content if isinstance(post.content, str) else str(post.content or '')
            description = content.strip()
            if not description and summary:
                description = summary

            name = str(metadata.get('name')).strip()

            try:
                entity_index[entity_id] = FactEntity(
                    id=entity_id,
                    type=canonical_type,
                    name=name,
                    summary=summary,
                    description=description or None,
                    aliases=aliases,
                    relationships=relationships,
                    attributes=attributes_clean,
                )
            except ValidationError as exc:
                logger.warning('Skipping entity file %s due to validation error: %s', path, exc)
                continue

    if not entity_index:
        objekty_dir = repo_path / "Objekty"
        if objekty_dir.is_dir():
            for path in sorted(objekty_dir.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
                entity_type = "place" if "place" in path.stem.lower() else "other"
                attributes = {**_parse_front_matter(text), **_parse_attribute_block(text)}
                entity_id = _slugify(path.stem)
                entity_index[entity_id] = FactEntity(
                    id=entity_id,
                    type=entity_type,
                    summary=titles[0] if titles else path.stem,
                    attributes=attributes,
                )

        legendy_dir = repo_path / "Legendy"
        if legendy_dir.is_dir():
            for path in sorted(legendy_dir.glob("*.md")):
                text = path.read_text(encoding="utf-8")
                titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
                attributes = {**_parse_front_matter(text), **_parse_attribute_block(text)}
                entity_id = _slugify(path.stem)
                if entity_id in entity_index:
                    continue
                entity_index[entity_id] = FactEntity(
                    id=entity_id,
                    type="concept",
                    summary=titles[0] if titles else path.stem,
                    attributes=attributes,
                )

    for timeline_path in _timeline_candidates(repo_path):
        if not timeline_path.is_file():
            continue
        text = timeline_path.read_text(encoding="utf-8")
        events.extend(_parse_timeline_events(text))

    core_truth_sources = _collect_truth_sources(repo_path)
    core_truths = _extract_core_truths(core_truth_sources)

    return FactGraph(
        entities=list(entity_index.values()),
        events=events,
        core_truths=core_truths,
    )


__all__ = ["ArchiveResult", "ArchivistEngine", "load_universe"]
