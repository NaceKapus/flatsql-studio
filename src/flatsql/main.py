"""Main window composition and lifecycle wiring for FlatSQL Studio."""

from __future__ import annotations

import os
import sys
from typing import Any

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QSplitter, QVBoxLayout, QWidget

from flatsql.config import APP_VERSION, ASSETS_DIR, THEMES_DIR
from flatsql.core.action_controller import ActionController
from flatsql.core.connection_manager import ConnectionManager
from flatsql.core.extension_manager import ExtensionManager
from flatsql.core.history import HistoryManager
from flatsql.core.query_controller import QueryController
from flatsql.core.settings import SettingsManager
from flatsql.core.sql_formatter import SQLFormatter
from flatsql.core.sqlfluff_config import write_user_sqlfluff_config
from flatsql.core.theme import ThemeManager
from flatsql.ui.panels.db_explorer_panel import DBExplorerPanel
from flatsql.ui.panels.file_explorer_panel import FileExplorerPanel
from flatsql.ui.menu_bar import MainMenuBar
from flatsql.ui.panels.query_panel import QueryPanel
from flatsql.ui.panels.results_panel import ResultsPanel
from flatsql.ui.panels.snippet_panel import SnippetPanel

os.environ['QT_API'] = 'pyside6'

class MainWindow(QMainWindow):
    """Primary application window that composes all panels and controllers."""

    def __init__(self, theme_manager: ThemeManager) -> None:
        """Initialize application services and lightweight window state."""
        super().__init__()
        self.ui_initialized = False
        self.theme_manager = theme_manager
        self.theme_colors = self.theme_manager.get_component_colors()
        self.settings_manager = SettingsManager()
        self.history_manager = HistoryManager()

        self.conn_manager = ConnectionManager(self.settings_manager)
        self.conn_manager.error_occurred.connect(lambda t, m: QMessageBox.critical(self, t, m))

        self.extension_manager = ExtensionManager(self.conn_manager, self.settings_manager)
        self.conn_manager.set_extension_manager(self.extension_manager)

        self.db_keywords, self.db_functions = [], []
        sqlfluff_path = write_user_sqlfluff_config(self.settings_manager._settings)
        self.sql_formatter = SQLFormatter(sqlfluff_path)
        self.query_controller = QueryController(self.conn_manager)
        self.action_controller = ActionController(self)
    
        self.conn_manager.db_connections_changed.connect(self.action_controller.handle_db_connections_changed)

    def setup_ui(self) -> None:
        """Build the full main window UI and connect application signals."""
        self.setWindowTitle(f"FlatSQL Studio {APP_VERSION}")
        
        icon_path = os.path.join(ASSETS_DIR, 'img', 'icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        if sys.platform == 'win32':
            # Segoe UI is usually crisper than bundled web fonts on Windows LCDs.
            app_font = QFont('Segoe UI', 10)
            app_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
            app_font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
            QApplication.instance().setFont(app_font)
        else:
            font_path = os.path.join(ASSETS_DIR, 'fonts', 'Inter-Regular.ttf')
            if os.path.exists(font_path):
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    app_font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10)
                    app_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
                    QApplication.instance().setFont(app_font)

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(main_container)

        self.conn_manager.initialize_all()
        self.db_keywords = self.conn_manager.db_keywords
        self.db_functions = self.conn_manager.db_functions

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(1)
        main_layout.addWidget(self.main_splitter)
        self._setup_panes()

        
        self.query_controller.error_occurred.connect(lambda t, m: QMessageBox.warning(self, t, m))
        self.query_controller.timer_updated.connect(self.results_panel.update_live_stats)

        self.query_controller.query_started.connect(self.query_panel.on_query_started)
        self.query_controller.query_completed.connect(self.query_panel.on_query_completed)
        self.query_controller.query_started.connect(self.results_panel.on_query_started)

        self.query_controller.query_completed.connect(
            lambda ed, df, err, info, dur, is_ddl: self.db_explorer_panel.refresh() if is_ddl else None
        )

        self.db_explorer_panel.refresh()
        self.file_explorer_panel.refresh()

        saved_tabs = self.settings_manager.get('open_tabs')
        if self.settings_manager.get('restore_previous_session', True) and saved_tabs:
            self.query_panel.restore_session(saved_tabs)

        self.setMenuBar(MainMenuBar(self.action_controller, self))
        self._create_shortcuts()
        self.query_panel.update_all_editors_theme(self.theme_colors, self.db_keywords, self.db_functions)
        self.action_controller.handle_query_tab_changed(self.query_tabs.currentIndex())

        self.set_file_explorer_visible(self.settings_manager.get('file_explorer_visible', True))
        self.set_db_explorer_visible(self.settings_manager.get('db_explorer_visible', True))
        self.set_snippets_visible(self.settings_manager.get('snippets_visible', False))

        self.showMaximized()
        QApplication.processEvents()
        self._apply_initial_splitter_sizes()
        self.ui_initialized = True

    def _setup_panes(self) -> None:
        """Instantiate side panel splitters and wire inter-panel signals."""
        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.setHandleWidth(1)
        self.left_splitter.setChildrenCollapsible(False)

        self.right_side_splitter = QSplitter(Qt.Vertical)
        self.right_side_splitter.setHandleWidth(1)
        self.right_side_splitter.setChildrenCollapsible(False)

        self.file_explorer_panel = FileExplorerPanel(self.theme_colors, self.settings_manager, self.conn_manager.fs_connections, self.action_controller.get_active_engine_for_file_explorer, self)
        self.db_explorer_panel = DBExplorerPanel(self.theme_colors, self.settings_manager, self.theme_manager, self.conn_manager.db_connections, self)
        self.snippet_panel = SnippetPanel(self.theme_colors, self)
        self.file_explorer_panel.setMinimumWidth(220)
        self.db_explorer_panel.setMinimumWidth(220)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.setHandleWidth(1)
        self.right_splitter.setChildrenCollapsible(False)

        self.query_panel = QueryPanel(
            self.theme_colors, 
            self.settings_manager, 
            self.conn_manager, 
            self.history_manager, 
            self
        )
        
        self.results_panel = ResultsPanel(self.settings_manager, self)
        self.query_tabs = self.query_panel.query_tabs
        self.query_tabs.tabBar().setElideMode(Qt.ElideRight)
        self.connection_combo = self.query_panel.connection_combo
        self.db_explorer_panel.set_connection_combo(self.connection_combo)

        self.right_splitter.addWidget(self.query_panel)
        self.right_splitter.addWidget(self.results_panel)

        self.main_splitter.addWidget(self.left_splitter)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.addWidget(self.right_side_splitter)

        self._move_panel_to_side(
            self.file_explorer_panel,
            self._normalize_panel_side(self.settings_manager.get('file_explorer_side', 'left')),
        )
        self._move_panel_to_side(
            self.db_explorer_panel,
            self._normalize_panel_side(self.settings_manager.get('db_explorer_side', 'left')),
        )
        self._move_panel_to_side(
            self.snippet_panel,
            self._normalize_panel_side(self.settings_manager.get('snippets_side', 'left')),
        )

        self.left_splitter.setSizes([1, 1, 1])
        self.right_side_splitter.setSizes([1, 1, 1])

        self.snippet_panel.snippet_opened.connect(
            lambda name, content, file_path: self.query_panel.add_new_tab(
                content,
                name,
                snippet_path=file_path,
            )
        )
        self.conn_manager.db_connections_changed.connect(self.db_explorer_panel.refresh)
        self.conn_manager.fs_connections_changed.connect(self.file_explorer_panel.refresh)   
        
        self.db_explorer_panel.add_connection_requested.connect(self.action_controller.show_add_db_connection_dialog)
        self.db_explorer_panel.disconnect_requested.connect(self.conn_manager.remove_db_connection)
        self.db_explorer_panel.active_connection_changed.connect(self.action_controller.change_active_tab_connection)
        self.db_explorer_panel.action_new_query.connect(self.action_controller.open_new_query_for_connection)
        self.db_explorer_panel.action_script_select.connect(self.action_controller.handle_db_script_select)
        self.db_explorer_panel.action_script_ddl.connect(self.action_controller.handle_db_script_ddl)
        
        self.file_explorer_panel.add_connection_requested.connect(self.action_controller.show_add_file_connection_dialog)
        self.file_explorer_panel.disconnect_requested.connect(self.conn_manager.remove_fs_connection)
        self.file_explorer_panel.action_script_select.connect(self.action_controller.script_and_open_select)
        self.file_explorer_panel.action_script_flattened.connect(self.action_controller.script_and_open_flattened_select)
        self.file_explorer_panel.action_show_schema.connect(self.action_controller.show_schema)
        self.file_explorer_panel.action_show_stats.connect(self.action_controller.show_statistics)
        self.file_explorer_panel.action_split_file.connect(self.action_controller.show_split_dialog)
        self.file_explorer_panel.action_convert_file.connect(self.action_controller.handle_file_conversion)
        self.file_explorer_panel.action_create_table.connect(self.action_controller.create_table_from_file)
        self.file_explorer_panel.action_create_view.connect(self.action_controller.create_view_from_file)
        self.file_explorer_panel.action_merge_folder.connect(self.action_controller.show_merge_dialog)
        self.file_explorer_panel.action_select_folder.connect(self.action_controller.select_from_folder)

        self.query_panel.run_query_requested.connect(self.action_controller.execute_query)
        self.query_panel.stop_query_requested.connect(self.action_controller.stop_query)
        self.query_panel.explain_requested.connect(self.action_controller.explain_current_query)
        self.query_panel.save_snippet_requested.connect(self.action_controller.save_as_snippet)
        self.query_panel.file_dropped.connect(self.action_controller.handle_file_drop)
        self.query_panel.tab_changed.connect(self.action_controller.handle_query_tab_changed)
        self.query_panel.show_message_requested.connect(lambda msg: [self.results_panel.messages_view.setText(msg), self.results_panel.results_tabs.setCurrentIndex(1)])
        
        self.results_panel.export_requested.connect(self.action_controller.show_export_dialog)
        self.results_panel.copy_query_as_python_requested.connect(self.action_controller.copy_query_as_python_script)

    def _apply_initial_splitter_sizes(self) -> None:
        """Apply DPI-friendly default splitter sizes after the window is shown."""
        total_width = max(self.main_splitter.size().width(), self.width())
        left_width = max(240, total_width // 5)
        left_width = min(left_width, max(240, total_width // 3))
        right_width = max(240, total_width // 5)
        right_width = min(right_width, max(240, total_width // 3))

        total_height = max(self.right_splitter.size().height(), self.height())
        top_height = max(220, total_height // 2)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)

        has_left = self.left_splitter.isVisible()
        has_right = self.right_side_splitter.isVisible()

        if has_left and has_right:
            center_width = max(320, total_width - left_width - right_width)
            self.main_splitter.setSizes([left_width, center_width, right_width])
        elif has_left:
            self.main_splitter.setSizes([left_width, max(320, total_width - left_width), 0])
        elif has_right:
            self.main_splitter.setSizes([0, max(320, total_width - right_width), right_width])
        else:
            self.main_splitter.setSizes([0, total_width, 0])

        self.right_splitter.setSizes([top_height, max(180, total_height - top_height)])

    def _apply_theme(self, theme_file: str) -> None:
        """Apply a theme file and propagate palette updates across panels."""
        theme_path = os.path.join(THEMES_DIR, theme_file)
        try:
            self.theme_manager = ThemeManager(theme_path)
            self.theme_manager.apply(QApplication.instance())
            self.theme_colors = self.theme_manager.get_component_colors()
            
            if hasattr(self, 'db_explorer_panel'): self.db_explorer_panel.update_theme(self.theme_colors, self.theme_manager)
            if hasattr(self, 'file_explorer_panel'): self.file_explorer_panel.update_theme(self.theme_colors)
            if hasattr(self, 'snippet_panel'): self.snippet_panel.update_theme(self.theme_colors)
            if hasattr(self, 'query_panel'): self.query_panel.refresh_theme(self.theme_colors)
            if hasattr(self, 'results_panel'): self.results_panel.update_theme(self.theme_manager)

            self.query_panel.update_all_editors_theme(self.theme_colors, self.db_keywords, self.db_functions)
            self.action_controller.handle_query_tab_changed(self.query_tabs.currentIndex())
            self.settings_manager.set('theme', theme_file)
        except Exception as e:
            QMessageBox.critical(self, "Theme Error", f"Failed to apply theme '{theme_file}':\n{e}")

    def set_file_explorer_visible(self, visible: bool) -> None:
        """Toggle file explorer panel visibility and persist the setting."""
        self.settings_manager.set('file_explorer_visible', visible)
        self.file_explorer_panel.setVisible(visible)
        self._update_side_splitter_visibility()

    def set_db_explorer_visible(self, visible: bool) -> None:
        """Toggle database explorer panel visibility and persist the setting."""
        self.settings_manager.set('db_explorer_visible', visible)
        self.db_explorer_panel.setVisible(visible)
        self._update_side_splitter_visibility()

    def set_snippets_visible(self, visible: bool) -> None:
        """Toggle snippet panel visibility and persist the setting."""
        self.settings_manager.set('snippets_visible', visible)
        self.snippet_panel.setVisible(visible)
        self._update_side_splitter_visibility()

    @staticmethod
    def _normalize_panel_side(side: object) -> str:
        """Normalize panel side values to left or right."""
        return 'right' if str(side).lower() == 'right' else 'left'

    @staticmethod
    def _splitter_has_visible_child(splitter: QSplitter) -> bool:
        """Return whether any splitter child is currently visible."""
        return any(not splitter.widget(i).isHidden() for i in range(splitter.count()))

    def _move_panel_to_side(self, panel: QWidget, side: str) -> None:
        """Move a panel widget to the requested side splitter."""
        target_splitter = self.right_side_splitter if side == 'right' else self.left_splitter
        if panel.parent() is target_splitter:
            self._reorder_side_panels(target_splitter)
            return

        panel.setParent(None)
        target_splitter.addWidget(panel)
        self._reorder_side_panels(target_splitter)

    def _reorder_side_panels(self, splitter: QSplitter) -> None:
        """Apply the standard side-panel order within a splitter.

        Order is always File Explorer, Database Explorer, then SQL Snippets.
        """
        panel_order = [
            self.file_explorer_panel,
            self.db_explorer_panel,
            self.snippet_panel,
        ]

        insert_index = 0
        for panel in panel_order:
            if panel.parent() is splitter:
                splitter.insertWidget(insert_index, panel)
                insert_index += 1

    def set_file_explorer_side(self, side: str) -> None:
        """Pin the file explorer panel to the left or right side."""
        normalized_side = self._normalize_panel_side(side)
        self.settings_manager.set('file_explorer_side', normalized_side)
        self._move_panel_to_side(self.file_explorer_panel, normalized_side)
        self._update_side_splitter_visibility()

    def set_db_explorer_side(self, side: str) -> None:
        """Pin the database explorer panel to the left or right side."""
        normalized_side = self._normalize_panel_side(side)
        self.settings_manager.set('db_explorer_side', normalized_side)
        self._move_panel_to_side(self.db_explorer_panel, normalized_side)
        self._update_side_splitter_visibility()

    def set_snippets_side(self, side: str) -> None:
        """Pin the snippets panel to the left or right side."""
        normalized_side = self._normalize_panel_side(side)
        self.settings_manager.set('snippets_side', normalized_side)
        self._move_panel_to_side(self.snippet_panel, normalized_side)
        self._update_side_splitter_visibility()

    def _update_side_splitter_visibility(self) -> None:
        """Show side splitters only when they contain a visible panel."""
        self.left_splitter.setVisible(self._splitter_has_visible_child(self.left_splitter))
        self.right_side_splitter.setVisible(self._splitter_has_visible_child(self.right_side_splitter))

        if self.ui_initialized:
            self._apply_initial_splitter_sizes()

    def _create_shortcuts(self) -> None:
        """Create and register keyboard shortcuts for the main window."""
        self.run_query_shortcut = QShortcut(self)
        self.run_query_shortcut.activated.connect(self.action_controller.execute_query)
        self._update_run_query_shortcut()

    def _update_run_query_shortcut(self) -> None:
        """Refresh the run-query shortcut from the current settings value."""
        shortcut = self.settings_manager.get('run_query_shortcut', 'Ctrl+Return')
        self.run_query_shortcut.setKey(QKeySequence(shortcut))

    def closeEvent(self, event: Any) -> None:
        """Persist session state and close background resources on exit."""
        self.extension_manager.shutdown()
        self.action_controller.save_session_and_cleanup()
        event.accept()