"""Utilities for configuring logging across the eLKA agent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional


DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logger(config: Dict[str, object]) -> logging.Logger:
    """Configure and return the root logger based on configuration values."""

    level_name = str(config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicated logs when reconfiguring
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    log_format = str(config.get("format", DEFAULT_FORMAT))
    formatter = logging.Formatter(log_format)

    if _should_enable_console(config):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    log_file = _resolve_log_file(config.get("file"))
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.debug("Logger nakonfigurován s úrovní %s", level_name)
    return logger


def _should_enable_console(config: Dict[str, object]) -> bool:
    console = config.get("console")
    if console is None:
        return True
    return bool(console)


def _resolve_log_file(value: Optional[object]) -> Optional[str]:
    if not value:
        return None
    path = Path(str(value)).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)
