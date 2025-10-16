"""Task definitions for eLKA Studio's Celery workers."""

from .base import dummy_task
from .lore_tasks import process_story_task

__all__ = ["dummy_task", "process_story_task"]
