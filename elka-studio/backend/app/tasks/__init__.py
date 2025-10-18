"""Task definitions for eLKA Studio's Celery workers."""

from .base import dummy_task
from .lore_tasks import (
    generate_and_process_story_from_seed_task,
    generate_saga_task,
    uce_process_story_task,
)

__all__ = [
    "dummy_task",
    "generate_and_process_story_from_seed_task",
    "generate_saga_task",
    "uce_process_story_task",
]
