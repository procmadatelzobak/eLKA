"""Database session and configuration helpers for eLKA Studio."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


def _find_config_file() -> Optional[Path]:
    """Locate the configuration file starting from this module's directory."""
    env_path = os.getenv("ELKA_CONFIG_PATH")
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.is_file():
            return candidate

    for parent in Path(__file__).resolve().parents:
        config_path = parent / "config.yml"
        if config_path.is_file():
            return config_path
        alt_path = parent / "config.yaml"
        if alt_path.is_file():
            return alt_path
    return None


def _load_config() -> Dict[str, Any]:
    config_file = _find_config_file()
    if not config_file:
        return {}

    with config_file.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


_config = _load_config()
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
