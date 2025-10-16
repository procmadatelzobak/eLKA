"""Celery application configuration for eLKA Studio."""

from __future__ import annotations

import os

from celery import Celery


def _load_broker_url() -> str:
    """Return the broker URL for Celery, defaulting to a local Redis instance."""

    return os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")


celery_app = Celery(
    "elka_studio",
    broker=_load_broker_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND", _load_broker_url()),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

celery_app.autodiscover_tasks(["app.tasks"])


__all__ = ["celery_app"]
