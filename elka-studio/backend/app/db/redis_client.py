"""Shared Redis client utilities for the eLKA backend."""

from __future__ import annotations

import os
from functools import lru_cache

import redis


def _load_redis_url() -> str:
    """Return the Redis connection URL based on the Celery configuration."""

    return os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis:
    """Return a cached Redis client configured for pub/sub usage."""

    return redis.Redis.from_url(_load_redis_url(), decode_responses=True)


__all__ = ["get_redis_client"]
