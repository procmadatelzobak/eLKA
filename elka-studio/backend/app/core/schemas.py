"""Structured data models used by the Universe Consistency Engine."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class FactEntity(BaseModel):
    """Representation of an entity discovered within a story."""

    id: str = Field(..., description="Stable identifier for the entity")
    type: Literal[
        "person",
        "place",
        "artifact",
        "organization",
        "concept",
        "event",
        "other",
    ]
    labels: List[str] = Field(default_factory=list, description="Alternative names")
    summary: Optional[str] = Field(default=None, description="Short description")
    attributes: Dict[str, str] = Field(default_factory=dict, description="Key-value facts")


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


__all__ = [
    "FactEntity",
    "FactEvent",
    "FactGraph",
    "ConsistencyIssue",
    "ChangesetFile",
    "Changeset",
    "UCEReport",
]
