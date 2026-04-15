"""Application configuration constants and path helpers."""
from __future__ import annotations

import os
import sys
import ctypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Get the base directory of the project (where run.py is)
# File is at src/flatsql/config.py, so go up 3 levels to reach root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Assets is now in src/flatsql/assets (1 level up from config.py, same directory)
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
THEMES_DIR = os.path.join(ASSETS_DIR, "themes")
TEMPLATES_DIR = os.path.join(ASSETS_DIR, "templates")
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")
SNIPPETS_DIR = os.path.join(BASE_DIR, "snippets")
BUILTIN_SNIPPETS_SOURCE_DIR = os.path.join(TEMPLATES_DIR, "snippets")
BUILTIN_SNIPPETS_FOLDER_NAME = "DuckDB"
SQLFLUFF_CONFIG_PATH = os.path.join(BASE_DIR, ".sqlfluff")
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
