"""Application settings persistence for FlatSQL Studio."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from flatsql.config import SETTINGS_PATH
from flatsql.core.logger import get_logger

DEFAULT_SETTINGS = {
    'font_size': 11,
    'file_explorer_visible': True,
    'db_explorer_visible': True,
    'snippets_visible': False,
    'file_explorer_side': 'left',
    'db_explorer_side': 'left',
    'snippets_side': 'right',
    'theme': 'dark.json',
    'run_query_shortcut': 'Ctrl+Return',
    'sql_autocomplete_enabled': True,
    'connections': [],
    'file_connections': [],
    'open_tabs': [],
    'restore_previous_session': False,
    'default_export_format': 'csv',
    'pinned_files': [],
    'app_id': str(uuid.uuid4()),
    'history_retention_limit': 10000,
    'engine_max_memory': '',
    'engine_temp_dir': '',
    'engine_max_spill_size': '',
    'engine_threads': '',
    'engine_timezone': 'UTC',
    'engine_preserve_insertion_order': True,
    'sqlfluff_keywords_case': 'upper',
    'sqlfluff_functions_case': 'upper',
    'sqlfluff_identifiers_case': 'lower',
    'sqlfluff_literals_case': 'upper',
    'sqlfluff_types_case': 'upper',
    'sqlfluff_indent_unit': 'space',
    'sqlfluff_tab_space_size': 4,
    'sqlfluff_max_line_length': 80,
    'sqlfluff_comma_position': 'trailing',
    'sqlfluff_require_semicolon': False,
    'sqlfluff_quote_identifiers': True,
    'preview_row_limit': 1000,
}

logger = get_logger(__name__)

class SettingsManager:
    """Load, expose, and persist user-configurable application settings."""

    def __init__(self) -> None:
        """Initialize the settings manager with default values."""
        self._settings = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self) -> None:
        """Load settings from disk and merge them with defaults."""
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._settings.update(data)
        except Exception as e:
            logger.exception("Failed to load settings from %s.", SETTINGS_PATH)

    def save(self) -> None:
        """Persist the current settings to disk."""
        try:
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=4)
        except Exception as e:
            logger.exception("Failed to save settings to %s.", SETTINGS_PATH)

    def get(self, key: str, default: Any = None) -> Any:
        """Return a setting value, or the provided default when absent."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a single setting value in memory."""
        self._settings[key] = value

    def update(self, new_dict: dict[str, Any]) -> None:
        """Merge a dictionary of updated setting values into memory."""
        self._settings.update(new_dict)