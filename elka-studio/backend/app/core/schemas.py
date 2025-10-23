"""Structured data models used by the Universe Consistency Engine."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class FactEntity(BaseModel):
    """Representation of an entity discovered within a story."""

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str = Field(..., description="Stable identifier for the entity")
    type: str = Field(..., description="Categorised entity type")
    name: str = Field(..., description="Primary human-readable name for the entity")
    description: Optional[str] = Field(
        default=None, description="Detailed Markdown description"
    )
    aliases: Optional[List[str]] = Field(
        default=None,
        description="Alternative names and identifiers",
    )
    summary: Optional[str] = Field(default=None, description="Short description")
    relationships: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Relationships to other entities keyed by name",
    )
    attributes: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata for compatibility"
    )


class FactEvent(BaseModel):
    """Representation of a lore event extracted from a story."""

    id: str
    title: str
    date: Optional[str] = None
    location: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class FactGraph(BaseModel):
    """Container holding entities, events, and shared lore context."""

    entities: List[FactEntity] = Field(default_factory=list)
    events: List[FactEvent] = Field(default_factory=list)
    core_truths: List[str] = Field(
        default_factory=list,
        description="Canonical truths extracted from the universe legends.",
    )


class FactEntityGraph(BaseModel):
    """Slim graph used for entity reconciliation within the planner."""

    entities: List[FactEntity] = Field(default_factory=list)


class FactEntityUpdate(BaseModel):
    """Represents an entity update detected by the planner."""

    id: str = Field(..., description="Identifier of the entity to update")
    existing: FactEntity = Field(..., description="Current canonical entity data")
    incoming: FactEntity = Field(..., description="Incoming entity data from extraction")


class ChangeOperation(BaseModel):
    """Single create/update/delete directive emitted by the planner."""

    operation: Literal["create", "update", "delete"]
    entity: Optional[FactEntity] = Field(
        default=None, description="Entity payload for create/delete operations"
    )
    update: Optional[FactEntityUpdate] = Field(
        default=None, description="Structured update description"
    )


class ChangeSet(BaseModel):
    """Collection of planner operations with optional token accounting."""

    operations: List[ChangeOperation] = Field(default_factory=list)
    tokens: Optional[Dict[str, int]] = Field(
        default=None, description="Token usage reported by the AI adapter"
    )


class ConsistencyIssue(BaseModel):
    """Consistency issue discovered when comparing fact graphs."""

    level: Literal["error", "warning", "info"]
    code: str
    message: str
    refs: List[str] = Field(default_factory=list)


class ChangesetFile(BaseModel):
    """Single file entry within a proposed changeset."""

    path: str
    old: Optional[str] = None
    new: str


class Changeset(BaseModel):
    """Collection of files that should be written to the repository."""

    files: List[ChangesetFile]
    summary: str
    breaking: bool = False


class UCEReport(BaseModel):
    """Universe Consistency Engine output shared across API boundaries."""

    ok: bool
    issues: List[ConsistencyIssue] = Field(default_factory=list)
    proposed: Optional[Changeset] = None
    notes: List[str] = Field(default_factory=list)


class EntityType(str, Enum):
    """Enumeration of supported entity types for archival purposes."""

    CHARACTER = "character"
    LOCATION = "location"
    EVENT = "event"
    CONCEPT = "concept"
    ITEM = "item"
    MATERIAL = "material"
    ORGANIZATION = "organization"
    OTHER = "other"


class ExtractedEntity(FactEntity):  # pragma: no cover - backwards compatibility
    """Legacy wrapper maintained for backwards compatibility."""

    @property
    def entity_type(self) -> EntityType:
        try:
            return EntityType(self.type.lower())
        except ValueError:
            return EntityType.OTHER

    @entity_type.setter
    def entity_type(self, value: EntityType | str) -> None:
        if isinstance(value, EntityType):
            resolved = value.value
        else:
            resolved = str(value).lower()
        canonical = resolved.capitalize() if resolved else "Misc"
        object.__setattr__(self, "type", canonical)


class ExtractedEvent(FactEntity):  # pragma: no cover - backwards compatibility
    """Legacy wrapper for event records with optional structured metadata."""

    date: Optional[str] = None
    location: Optional[str] = None
    participants: List[str] = Field(default_factory=list)


class ExtractedData(BaseModel):
    """Aggregate container for all extracted story entities and events."""

    characters: List[FactEntity] = Field(default_factory=list)
    locations: List[FactEntity] = Field(default_factory=list)
    events: List[FactEntity] = Field(default_factory=list)
    concepts: List[FactEntity] = Field(default_factory=list)
    items: List[FactEntity] = Field(default_factory=list)
    misc: List[FactEntity] = Field(default_factory=list)

    @property
    def things(self) -> List[FactEntity]:  # pragma: no cover - compatibility shim
        return self.items

    @property
    def materials(self) -> List[FactEntity]:  # pragma: no cover - compatibility shim
        return [entity for entity in self.misc if entity.type.lower() == "material"]

    @property
    def others(self) -> List[FactEntity]:  # pragma: no cover - compatibility shim
        return self.misc


class TaskType(str, Enum):
    """Identifier for background tasks scheduled in eLKA Studio."""

    GENERATE_STORY = "generate_story"
    GENERATE_SAGA = "generate_saga"
    GENERATE_CHAPTER = "generate_chapter"
    PROCESS_STORY = "process_story"
    UCE_PROCESS_STORY = "uce_process_story"


__all__ = [
    "FactEntity",
    "FactEvent",
    "FactGraph",
    "FactEntityGraph",
    "FactEntityUpdate",
    "ChangeOperation",
    "ChangeSet",
    "ConsistencyIssue",
    "ChangesetFile",
    "Changeset",
    "UCEReport",
    "EntityType",
    "ExtractedEntity",
    "ExtractedEvent",
    "ExtractedData",
    "TaskType",
]
