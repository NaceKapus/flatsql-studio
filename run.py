import os
import sys

# Add src/ to sys.path so flatsql package can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from PySide6.QtWidgets import QApplication

from flatsql.config import THEMES_DIR, configure_startup_display
from flatsql.core.snippet_bootstrap import ensure_snippets_initialized
from flatsql.core.settings import SettingsManager
from flatsql.core.theme import ThemeManager
from flatsql.main import MainWindow


def main() -> int:
    """Run the FlatSQL Studio desktop application."""
    configure_startup_display()
    app = QApplication(sys.argv)

    ensure_snippets_initialized()

    settings_manager = SettingsManager()
    theme_file = settings_manager.get("theme", "dark.json")
    theme_path = os.path.join(THEMES_DIR, theme_file)
    theme_manager = ThemeManager(theme_path)

    window = MainWindow(theme_manager)

    app.setStyle("Fusion")
    theme_manager.apply(app)

    window.setup_ui()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())