"""Application configuration constants and path helpers."""
from __future__ import annotations

import os
import sys
import ctypes

from platformdirs import user_data_dir
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

APP_NAME = "FlatSQL Studio"

# Read-only assets shipped with the install (src/flatsql/assets/...)
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(_PKG_DIR, "assets")
THEMES_DIR = os.path.join(ASSETS_DIR, "themes")
SQLFLUFF_CONFIG_PATH = os.path.join(ASSETS_DIR, ".sqlfluff")
TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
BUILTIN_SNIPPETS_SOURCE_DIR = os.path.join(TEMPLATES_DIR, "snippets")
BUILTIN_SNIPPETS_FOLDER_NAME = "DuckDB"

# User-writable per-user data directory (platform-native, survives reinstalls).
#   Windows: %APPDATA%\FlatSQL\FlatSQL Studio\
#   macOS:   ~/Library/Application Support/FlatSQL Studio/
#   Linux:   $XDG_DATA_HOME or ~/.local/share/FlatSQL Studio/
USER_DATA_DIR = user_data_dir(APP_NAME, appauthor=False, roaming=True)
SETTINGS_PATH = os.path.join(USER_DATA_DIR, "settings.json")
SNIPPETS_DIR = os.path.join(USER_DATA_DIR, "snippets")
LOG_PATH = os.path.join(USER_DATA_DIR, "flatsql.log")
HISTORY_DB_PATH = os.path.join(USER_DATA_DIR, "userdata.duckdb")

os.makedirs(USER_DATA_DIR, exist_ok=True)

DOCS_URL = "https://docs.flatsql.com"
APP_VERSION = "1.0.0"


def configure_startup_display() -> None:
    """Configure process-level display behavior before ``QApplication`` starts.

    Use pass-through scaling so Qt preserves the native fractional DPI reported
    by Windows. This prevents text and layout geometry from drifting out of sync
    on smaller high-DPI laptop displays and during monitor switching.
    """
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    if sys.platform != "win32":
        return

    # Prefer per-monitor v2 awareness for modern Windows.
    try:
        dpi_awareness_context_per_monitor_v2 = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(dpi_awareness_context_per_monitor_v2):
            return
    except Exception:
        pass

    # Fall back for older versions of Windows.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
