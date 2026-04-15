"""SQL formatting support backed by SQLFluff."""

from __future__ import annotations

import os

from sqlfluff.core import FluffConfig, Linter

from flatsql.core.logger import get_logger

logger = get_logger(__name__)

class SQLFormatter:
    """Format SQL strings using the configured SQLFluff ruleset."""

    def __init__(self, config_path: str):
        """Initialize the formatter and configure the SQLFluff linter."""
        self.linter = None
        self._init_linter(config_path)

    def _init_linter(self, config_path: str) -> None:
        """Initialize the SQLFluff linter when a config file is available."""
        try:
            if os.path.exists(config_path):
                config = FluffConfig.from_path(config_path)
                self.linter = Linter(config=config)
            else:
                logger.warning("SQLFluff config not found at %s. Formatting disabled.", config_path)
        except Exception as e:
            logger.exception("Failed to initialize SQLFluff from %s.", config_path)
            self.linter = None

    def format(self, sql_string: str) -> str:
        """Return a formatted SQL string, or the original string on failure."""
        if not self.linter or not sql_string or not sql_string.strip():
            return sql_string
    
        try:
            linted_result = self.linter.lint_string(sql_string, fix=True)
            return linted_result.fix_string()[0]
        except Exception as e:
            logger.exception("SQL auto-formatting failed.")
            return sql_string