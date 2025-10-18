"""SQLAlchemy model for tasks executed within a project."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, relationship
from sqlalchemy.sql import expression


class TaskStatus(str):
    """String-based task statuses shared across the application."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PAUSED = "PAUSED"

from ..db.session import Base

if TYPE_CHECKING:  # pragma: no cover
    from .project import Project


class Task(Base):
    """Represents a background or generation task tied to a project."""

    __tablename__ = "tasks"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = Column(Integer, ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = Column(String(255), nullable=False)
    status: Mapped[str] = Column(String(50), nullable=False, default=TaskStatus.PENDING)
    celery_task_id: Mapped[str | None] = Column(String(255), nullable=True, index=True)
    log: Mapped[str | None] = Column(Text, nullable=True)
    progress: Mapped[int | None] = Column(Integer, nullable=True)
    params: Mapped[dict[str, Any] | None] = Column(JSON, nullable=True, default=dict)
    result: Mapped[dict[str, Any] | None] = Column(JSON, nullable=True, default=dict)
    total_input_tokens: Mapped[int | None] = Column(Integer, nullable=True, default=0)
    total_output_tokens: Mapped[int | None] = Column(Integer, nullable=True, default=0)
    result_approved: Mapped[bool] = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=expression.false(),
    )
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="tasks")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the task for API responses."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "type": self.type,
            "status": self.status,
            "celery_task_id": self.celery_task_id,
            "log": self.log,
            "progress": self.progress,
            "params": deepcopy(self.params) if self.params is not None else None,
            "result": deepcopy(self.result) if self.result is not None else None,
            "result_approved": self.result_approved,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


__all__ = ["Task", "TaskStatus"]
