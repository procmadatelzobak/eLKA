"""SQLAlchemy models for projects and related settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, relationship

from ..db.session import Base

if TYPE_CHECKING:  # pragma: no cover
    from .task import Task


class Project(Base):
    """Represents a lore project managed by eLKA Studio."""

    __tablename__ = "projects"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    name: Mapped[str] = Column(String(255), unique=True, nullable=False)
    git_url: Mapped[str | None] = Column(String(500), nullable=True)
    local_path: Mapped[str | None] = Column(String(500), nullable=True)
    git_token: Mapped[str | None] = Column(Text, nullable=True)

    settings: Mapped[list["Setting"]] = relationship(
        "Setting", back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="project", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, str | int | None]:
        """Return a serializable representation without sensitive fields."""
        return {
            "id": self.id,
            "name": self.name,
            "git_url": self.git_url,
            "local_path": self.local_path,
        }


class Setting(Base):
    """Key/value pair for project-specific configuration."""

    __tablename__ = "settings"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = Column(Integer, ForeignKey("projects.id"), nullable=False)
    key: Mapped[str] = Column(String(255), nullable=False)
    value: Mapped[str | None] = Column(Text, nullable=True)

    project: Mapped[Project] = relationship("Project", back_populates="settings")

    def to_dict(self) -> dict[str, str | int | None]:
        """Serialize the setting value for API responses."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "key": self.key,
            "value": self.value,
        }


__all__ = ["Project", "Setting"]
