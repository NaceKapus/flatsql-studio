"""Theme loading and application utilities for FlatSQL."""

from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtGui import QColor, QPalette

from flatsql.config import ASSETS_DIR, THEMES_DIR
from flatsql.core.logger import get_logger

logger = get_logger(__name__)


class ThemeManager:
    """Load theme metadata and apply it to the Qt application."""

    def __init__(self, theme_path: str) -> None:
        """Initialize the theme manager from a JSON theme definition."""
        self.theme_data = self._load_theme(theme_path)
        if not self.theme_data:
            raise ValueError(f"Could not load or parse theme file: {theme_path}")

    @staticmethod
    def discover_themes(theme_dir: str = THEMES_DIR) -> dict[str, str]:
        """Return available themes keyed by filename in display order."""
        themes_with_order: list[dict[str, Any]] = []
        for filename in os.listdir(theme_dir):
            if filename.endswith('.json'):
                path = os.path.join(theme_dir, filename)
                try:
                    with open(path, 'r', encoding='utf-8-sig') as f:
                        data = json.load(f)
                        if 'name' in data:
                            sort_order = data.get('sort_order', 99)
                            themes_with_order.append({
                                'filename': filename,
                                'name': data['name'],
                                'order': sort_order
                            })
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning("Could not load theme %s.", filename, exc_info=e)

        sorted_themes = sorted(themes_with_order, key=lambda t: t['order'])
        themes = {theme['filename']: theme['name'] for theme in sorted_themes}
        return themes

    def _load_theme(self, theme_path: str) -> dict[str, Any] | None:
        """Load and parse a theme file from disk."""
        try:
            with open(theme_path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("Failed to load theme %s.", theme_path, exc_info=e)
            return None

    def _build_stylesheet(self) -> str:
        """Build the full Qt stylesheet from the base file and theme rules."""
        base_stylesheet = ""
        try:
            with open(os.path.join(THEMES_DIR, 'base_style.qss'), 'r', encoding='utf-8') as f:
                base_stylesheet = f.read()
            
            assets_path_safe = ASSETS_DIR.replace(os.sep, '/')
            base_stylesheet = base_stylesheet.replace('{{ASSETS_DIR}}', assets_path_safe)

            icon_name = "dropdown-arrow-black.svg"
            
            palette = self.theme_data.get('palette', {})
            text_color_hex = palette.get('Text', '#000000')
            
            if self._is_color_bright(text_color_hex):
                icon_name = "dropdown-arrow-white.svg"
            
            base_stylesheet = base_stylesheet.replace('{{DROPDOWN_ICON_NAME}}', icon_name)

        except FileNotFoundError:
            logger.warning("Base stylesheet not found at %s.", os.path.join(THEMES_DIR, 'base_style.qss'))

        theme_style_parts = []
        theme_stylesheet_data = self.theme_data.get('stylesheet', {})
        for selector, properties in theme_stylesheet_data.items():
            props_str = "; ".join([f"{key}: {value}" for key, value in properties.items()])
            theme_style_parts.append(f"{selector} {{ {props_str} }}")

        return base_stylesheet + "\n" + "\n".join(theme_style_parts)

    def _is_color_bright(self, hex_color: str) -> bool:
        """Returns True if the color is considered 'bright', False otherwise."""
        try:
            hex_color = hex_color.lstrip('#')
            if len(hex_color) == 3:
                hex_color = ''.join([c*2 for c in hex_color])
                
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            luminance = (0.299 * r + 0.587 * g + 0.114 * b)
            return luminance > 128
        except Exception:
            return False

    def apply(self, app: Any) -> None:
        """Apply the theme palette and stylesheet to the Qt application."""
        palette_data = self.theme_data.get('palette', {})
        palette = QPalette()
        for role_str, color_hex in palette_data.items():
            if role_str == "Disabled":
                for disabled_role_str, disabled_color_hex in color_hex.items():
                    try:
                        role = getattr(QPalette, disabled_role_str)
                        palette.setColor(QPalette.Disabled, role, QColor(disabled_color_hex))
                    except AttributeError:
                        logger.warning("Unknown disabled palette role '%s'.", disabled_role_str)
            else:
                try:
                    role = getattr(QPalette, role_str)
                    palette.setColor(role, QColor(color_hex))
                except AttributeError:
                    logger.warning("Unknown palette role '%s'.", role_str)
        app.setPalette(palette)

        stylesheet = self._build_stylesheet()
        if stylesheet:
            app.setStyleSheet(stylesheet)

    def get_component_colors(self) -> dict[str, Any]:
        """Return component-specific theme overrides."""
        return self.theme_data.get('components', {})