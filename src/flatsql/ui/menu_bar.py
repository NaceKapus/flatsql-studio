"""Main application menu bar and its actions."""
from __future__ import annotations

from typing import Any

import qtawesome as qta
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import QMenuBar, QMessageBox, QWidget

from flatsql.config import APP_VERSION, DOCS_URL


class MainMenuBar(QMenuBar):
    """Top-level menu bar for main window actions."""

    def __init__(
        self,
        action_controller: object,
        main_window: object,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the menu bar and create all menus."""
        super().__init__(parent)
        self.action_controller = action_controller
        self.mw = main_window
        self.settings_manager = self.mw.settings_manager

        self._create_menus()

    def _create_menus(self) -> None:
        """Create the File, Edit, View, Search, Query, Tools, and Help menus."""
        file_menu = self.addMenu("File")
        edit_menu = self.addMenu("Edit")
        view_menu = self.addMenu("View")
        search_menu = self.addMenu("Search")
        query_menu = self.addMenu("Query")
        tools_menu = self.addMenu("Tools")
        help_menu = self.addMenu("Help")

        # --- File Menu Actions ---
        open_action = QAction("Open File...", self, triggered=self.mw.query_panel.open_query_file)
        open_action.setShortcut(QKeySequence.Open)

        save_action = QAction("Save File...", self, triggered=self.mw.query_panel.save_current_query)
        save_action.setShortcut(QKeySequence.Save)

        exit_action = QAction("Exit", self, triggered=self.mw.close)

        file_menu.addActions([open_action, save_action])
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        # --- Edit Menu Actions ---
        undo_action = QAction(
            qta.icon("mdi.undo"),
            "Undo",
            self,
            shortcut=QKeySequence.Undo,
            triggered=lambda: self._trigger_editor_action("undo"),
        )
        redo_action = QAction(
            qta.icon("mdi.redo"),
            "Redo",
            self,
            shortcut=QKeySequence.Redo,
            triggered=lambda: self._trigger_editor_action("redo"),
        )
        edit_menu.addAction(undo_action)
        edit_menu.addAction(redo_action)

        # --- View Menu Actions ---
        self.toggle_file_explorer_action = QAction(
            "File Explorer",
            self,
            checkable=True,
            checked=self.settings_manager.get("file_explorer_visible", True),
        )
        self.toggle_file_explorer_action.toggled.connect(self.mw.set_file_explorer_visible)

        self.toggle_db_explorer_action = QAction(
            "Database Explorer",
            self,
            checkable=True,
            checked=self.settings_manager.get("db_explorer_visible", True),
        )
        self.toggle_db_explorer_action.toggled.connect(self.mw.set_db_explorer_visible)

        self.toggle_snippets_action = QAction(
            "Snippets",
            self,
            checkable=True,
            checked=self.settings_manager.get("snippets_visible", False),
        )
        self.toggle_snippets_action.toggled.connect(self.mw.set_snippets_visible)

        is_wrapped = self.settings_manager.get("word_wrap", False)
        self.toggle_word_wrap_action = QAction("Word Wrap", self, checkable=True, checked=is_wrapped)
        self.toggle_word_wrap_action.toggled.connect(self.mw.query_panel.toggle_word_wrap)

        view_menu.addActions([self.toggle_file_explorer_action, self.toggle_db_explorer_action])
        view_menu.addAction(self.toggle_snippets_action)
        view_menu.addSeparator()
        self._create_pane_position_menu(view_menu)
        view_menu.addSeparator()
        view_menu.addAction(self.toggle_word_wrap_action)

        # Zoom Actions
        view_menu.addSeparator()
        zoom_in_action = QAction("Zoom In", self, triggered=self.mw.query_panel.zoom_in)
        zoom_in_action.setShortcut(QKeySequence.ZoomIn)

        zoom_out_action = QAction("Zoom Out", self, triggered=self.mw.query_panel.zoom_out)
        zoom_out_action.setShortcut(QKeySequence.ZoomOut)

        view_menu.addAction(zoom_in_action)
        view_menu.addAction(zoom_out_action)

        # --- Search Menu Actions ---
        find_action = QAction("Find...", self, triggered=lambda: self.mw.query_panel.show_find_dialog(replace=False))
        find_action.setShortcut(QKeySequence.Find)

        replace_action = QAction("Replace...", self, triggered=lambda: self.mw.query_panel.show_find_dialog(replace=True))
        replace_action.setShortcut(QKeySequence.Replace)

        go_to_line_action = QAction("Go to Line", self, triggered=self.mw.query_panel.show_go_to_line_dialog)
        go_to_line_action.setShortcut(QKeySequence("Ctrl+G"))

        search_menu.addAction(find_action)
        search_menu.addAction(replace_action)
        search_menu.addAction(go_to_line_action)

        # --- Query Menu Actions ---
        query_menu.addSeparator()

        new_query_action = QAction("New Query", self, triggered=self.mw.query_panel.add_new_tab)
        new_query_action.setShortcut(QKeySequence("Ctrl+N"))
        query_menu.addAction(new_query_action)

        execute_action = QAction("Execute", self, triggered=self.action_controller.execute_query)
        query_menu.addAction(execute_action)

        explain_action = QAction("Explain Plan", self, triggered=self.action_controller.explain_current_query)
        explain_action.setToolTip("Show the execution plan for the current query")
        query_menu.addAction(explain_action)

        query_menu.addSeparator()

        history_action = QAction("Query History", self, triggered=self.action_controller.show_history_dialog)
        history_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        query_menu.addAction(history_action)

        # --- Tools Menu Actions ---
        settings_action = QAction("Settings", self, triggered=self.action_controller.show_settings_dialog)
        tools_menu.addAction(settings_action)

        tools_menu.addSeparator()

        profiler_action = QAction("DuckDB Profiler", self, triggered=self.action_controller.show_duckdb_profiler)
        tools_menu.addAction(profiler_action)

        tools_menu.addSeparator()

        view_logs_action = QAction("View Logs", self, triggered=self.action_controller.open_logs)
        tools_menu.addAction(view_logs_action)

        # --- Help Menu Actions ---
        docs_action = QAction("Documentation", self, triggered=self._open_documentation)
        docs_action.setShortcut(QKeySequence.HelpContents)
        #help_menu.addAction(docs_action)
        #help_menu.addSeparator()
        about_action = QAction("About", self, triggered=self._show_about_dialog)
        help_menu.addAction(about_action)

    def _create_pane_position_menu(self, view_menu: object) -> None:
        """Create left/right pinning actions for explorer panes."""
        pane_menu = view_menu.addMenu("Pane Position")

        side_specs = [
            (
                "File Explorer",
                self.settings_manager.get("file_explorer_side", "left"),
                self.mw.set_file_explorer_side,
            ),
            (
                "Database Explorer",
                self.settings_manager.get("db_explorer_side", "left"),
                self.mw.set_db_explorer_side,
            ),
            (
                "Snippets",
                self.settings_manager.get("snippets_side", "left"),
                self.mw.set_snippets_side,
            ),
        ]

        for pane_name, current_side, side_setter in side_specs:
            pane_submenu = pane_menu.addMenu(pane_name)
            group = QActionGroup(self)
            group.setExclusive(True)

            left_action = QAction("Pin Left", self, checkable=True)
            right_action = QAction("Pin Right", self, checkable=True)

            group.addAction(left_action)
            group.addAction(right_action)

            normalized_side = "right" if str(current_side).lower() == "right" else "left"
            left_action.setChecked(normalized_side == "left")
            right_action.setChecked(normalized_side == "right")

            left_action.triggered.connect(lambda checked=False, setter=side_setter: setter("left"))
            right_action.triggered.connect(lambda checked=False, setter=side_setter: setter("right"))

            pane_submenu.addAction(left_action)
            pane_submenu.addAction(right_action)

    def _trigger_editor_action(self, action_name: str) -> None:
        """Forward undo and redo actions to the active query editor."""
        editor = self.mw.query_panel.get_active_editor()
        if editor:
            if action_name == "undo":
                editor.undo()
            elif action_name == "redo":
                editor.redo()

    def _open_documentation(self) -> None:
        """Open the FlatSQL documentation in the default browser."""
        QDesktopServices.openUrl(QUrl(DOCS_URL))

    def _show_about_dialog(self) -> None:
        """Display the About dialog for FlatSQL."""
        QMessageBox.about(self.mw, "About FlatSQL", f"""
    <p><b>FlatSQL - Version {APP_VERSION}</b></p>
    <p>FlatSQL is an open-source desktop SQL client designed to make querying flat files and cloud storage as simple as querying a traditional database.</p>
    <p>Powered by DuckDB and Polars, it allows you to write standard SQL directly against local and remote data formats (CSV, TSV, PSV, Parquet, JSON, JSON Lines, text, Excel) without any ingestion steps.</p>
    <p>Built for data engineers and analysts, FlatSQL streamlines your workflow with native cloud connectivity, automated schema inference, and built-in data profiling tools.</p>
        """)