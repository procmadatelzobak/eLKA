"""Entry point for the eLKA Studio FastAPI application."""

from __future__ import annotations

import os
from typing import Iterable, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import projects, root, tasks, websockets
from .db.session import Base, engine

# Import models so that SQLAlchemy registers the tables on metadata creation
from .models import project, task  # noqa: F401  pylint: disable=unused-import
from .utils.config import load_config

def _configure_cors(application: FastAPI) -> None:
    """Attach CORS middleware with defaults suitable for local development."""

    config = load_config()
    cors_settings = config.get("cors", {})

    default_origins: List[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    env_origins = os.getenv("ELKA_ALLOWED_ORIGINS")
    if env_origins:
        allowed_origins = [origin.strip() for origin in env_origins.split(",") if origin.strip()]
    else:
        configured_origins = cors_settings.get("allow_origins", default_origins)
        if isinstance(configured_origins, str):
            allowed_origins = [configured_origins]
        else:
            allowed_origins = list(configured_origins) if isinstance(configured_origins, Iterable) else default_origins

    if not allowed_origins:
        allowed_origins = default_origins

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def include_routers(application: FastAPI) -> None:
    """Attach all API routers to the provided application instance."""
    application.include_router(projects.router)
    application.include_router(root.router)
    application.include_router(tasks.router)
    application.include_router(websockets.router)


def create_app() -> FastAPI:
    """Factory to create a configured FastAPI app instance."""
    application = FastAPI(title="eLKA Studio", version="0.1.0")
    _configure_cors(application)
    include_routers(application)

    @application.on_event("startup")
    async def on_startup() -> None:  # pragma: no cover - side effect only
        """Create database tables on application startup."""
        Base.metadata.create_all(bind=engine)

    return application


app = create_app()
