"""SQL formatting support backed by SQLFluff."""

from __future__ import annotations

import os

import sqlfluff

from flatsql.core.logger import get_logger

logger = get_logger(__name__)

class SQLFormatter:
    """Format SQL strings using a user-controlled SQLFluff config file.

    Uses the high-level ``sqlfluff.fix`` API rather than building a Linter
    manually — building one via ``Linter(config=FluffConfig.from_path(...))``
    silently skips the capitalisation rules, which is why we route through the
    simple API instead.
    """

    def __init__(self, config_path: str):
        """Store the path to the SQLFluff config file."""
        self._config_path: str | None = None
        self._init_config(config_path)

    def _init_config(self, config_path: str) -> None:
        """Validate and store the config path, leaving formatting disabled if missing."""
        if config_path and os.path.exists(config_path):
            self._config_path = config_path
        else:
            self._config_path = None
            logger.warning(
                "SQLFluff config not found at %s. Formatting disabled.", config_path
            )

    def reload(self, config_path: str) -> None:
        """Switch to a new config file, e.g. after the user changes settings.

        SQLFluff caches loaded config files by path (``functools.cache`` on
        ``load_config_file_as_dict`` / ``load_config_at_path``), so if we
        rewrite the same file the next ``sqlfluff.fix`` call will silently see
        the stale config. Clear those caches before swapping the path in.
        """
        try:
            from sqlfluff.core.config.loader import (
                load_config_at_path,
                load_config_file_as_dict,
            )

            load_config_file_as_dict.cache_clear()
            load_config_at_path.cache_clear()
        except Exception:
            logger.exception("Failed to clear SQLFluff config cache.")
        self._init_config(config_path)

    def format(self, sql_string: str) -> str:
        """Return a formatted SQL string, or the original string on failure."""
        if not self._config_path or not sql_string or not sql_string.strip():
            return sql_string

        try:
            return sqlfluff.fix(
                sql_string,
                dialect="duckdb",
                config_path=self._config_path,
            )
        except Exception:
            logger.exception("SQL auto-formatting failed.")
            return sql_string