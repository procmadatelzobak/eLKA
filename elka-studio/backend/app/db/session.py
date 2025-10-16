"""Database session and configuration helpers for eLKA Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from ..utils.config import load_config

_config = load_config()
_storage_config = _config.get("storage", {})
_database_path = Path(_storage_config.get("database_file", "~/.elka/elka.db")).expanduser()
_database_path.parent.mkdir(parents=True, exist_ok=True)

database_url = f"sqlite:///{_database_path}"
engine = create_engine(database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session for dependency injection."""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


__all__ = ["Base", "engine", "SessionLocal", "get_session", "database_url"]
