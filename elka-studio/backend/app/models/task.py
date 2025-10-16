"""SQLAlchemy model for tasks executed within a project."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, relationship

from ..db.session import Base

if TYPE_CHECKING:  # pragma: no cover
    from .project import Project


class Task(Base):
    """Represents a background or generation task tied to a project."""

    __tablename__ = "tasks"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = Column(Integer, ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = Column(String(255), nullable=False)
    status: Mapped[str] = Column(String(50), nullable=False, default="pending")
    log: Mapped[str | None] = Column(Text, nullable=True)
    progress: Mapped[int | None] = Column(Integer, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")

    def to_dict(self) -> dict[str, int | str | None]:
        """Serialize the task for API responses."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "type": self.type,
            "status": self.status,
            "log": self.log,
            "progress": self.progress,
        }


__all__ = ["Task"]
