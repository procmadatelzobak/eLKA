"""Task definitions for eLKA Studio's Celery workers."""

from .base import dummy_task
from .lore_tasks import (
    generate_chapter_task,
    generate_saga_task,
    generate_story_from_seed_task,
    process_story_task,
    uce_process_story_task,
)

__all__ = [
    "dummy_task",
    "generate_chapter_task",
    "generate_story_from_seed_task",
    "process_story_task",
    "generate_saga_task",
    "uce_process_story_task",
]
