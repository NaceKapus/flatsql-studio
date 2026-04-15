"""Application logging utilities for FlatSQL."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Final

from flatsql.config import SETTINGS_PATH

_LOGGER_NAME: Final[str] = "flatsql"
_LOG_FILE_NAME: Final[str] = "flatsql.log"
_MAX_LOG_BYTES: Final[int] = 1_048_576
_BACKUP_COUNT: Final[int] = 5


def _normalize_logger_name(name: str) -> str:
    """Normalize module logger names relative to the FlatSQL root logger."""
    prefix = f"{_LOGGER_NAME}."
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


def _get_log_directory() -> str:
    """Return the directory used for persistent FlatSQL log files."""
    return os.path.dirname(SETTINGS_PATH)


def _get_log_file_path() -> str:
    """Return the full path to the FlatSQL log file."""
    return os.path.join(_get_log_directory(), _LOG_FILE_NAME)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the shared FlatSQL application logger."""
    logger = logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_flatsql_configured", False):
        logger.setLevel(level)
        return logger

    os.makedirs(_get_log_directory(), exist_ok=True)

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        _get_log_file_path(),
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger._flatsql_configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a configured logger scoped to the FlatSQL logger hierarchy."""
    base_logger = configure_logging()
    if not name:
        return base_logger
    normalized_name = _normalize_logger_name(name)
    if not normalized_name or normalized_name == _LOGGER_NAME:
        return base_logger
    return base_logger.getChild(normalized_name)
