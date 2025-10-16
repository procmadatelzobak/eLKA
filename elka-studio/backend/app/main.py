"""Entry point for the eLKA Studio FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI

from .api import projects, root, tasks, websockets
from .db.session import Base, engine

# Import models so that SQLAlchemy registers the tables on metadata creation
from .models import project, task  # noqa: F401  pylint: disable=unused-import


def include_routers(application: FastAPI) -> None:
    """Attach all API routers to the provided application instance."""
    application.include_router(projects.router)
    application.include_router(root.router)
    application.include_router(tasks.router)
    application.include_router(websockets.router)


def create_app() -> FastAPI:
    """Factory to create a configured FastAPI app instance."""
    application = FastAPI(title="eLKA Studio", version="0.1.0")
    include_routers(application)

    @application.on_event("startup")
    async def on_startup() -> None:  # pragma: no cover - side effect only
        """Create database tables on application startup."""
        Base.metadata.create_all(bind=engine)

    return application


app = create_app()
