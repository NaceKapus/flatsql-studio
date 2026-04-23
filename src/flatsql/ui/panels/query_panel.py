from __future__ import annotations

import os
import sys
from typing import Any

import qtawesome as qta
from PySide6.QtCore import QPoint, Signal, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QTextCursor

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from flatsql.core.highlighter import SqlHighlighter
from flatsql.ui.dialogs.find import FindReplaceDialog, GoToLineDialog
from flatsql.ui.editor import QueryTextEdit
from flatsql.ui.widgets import DownwardComboBox, QueryEmptyState, QueryTabWidget

class QueryPanel(QFrame):
    """Panel hosting query editor tabs, editor tools, and query actions."""

    # Signals for communicating with MainWindow / Controllers
    run_query_requested = Signal()
    stop_query_requested = Signal()
    save_snippet_requested = Signal(int)  # Passes the tab index
    explain_requested = Signal()
    show_message_requested = Signal(str)  # Requests MainWindow to show a message in the Results panel
    cursor_position_changed = Signal(str)
    
    # Internal signals passed through from QueryTabWidget
    file_dropped = Signal(str)
    tab_changed = Signal(int)

    def __init__(
        self,
        theme_colors: dict[str, Any],
        settings_manager: object,
        conn_manager: object,
        history_manager: object,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the query panel and its toolbar and tabs."""
        super().__init__(parent)
        self.theme_colors = theme_colors
        self.settings_manager = settings_manager
        self.conn_manager = conn_manager
        self.history_manager = history_manager
        self.query_tab_counter = 0
        
        self.setObjectName("query_frame")
        self.setFrameShape(QFrame.StyledPanel)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self._setup_toolbar()
        self._setup_tabs()

    def _setup_toolbar(self) -> None:
        """Create the query toolbar and wire its actions."""
        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("queryToolbar")
        toolbar_layout = QHBoxLayout(toolbar_widget)

        # Execution Operations
        self.run_button = QPushButton(qta.icon('ri.play-fill', color='green'), "", toolTip="Run Query")
        self.stop_button = QPushButton(qta.icon('ri.stop-fill', color='red'), "", toolTip="Stop Query")
        self.run_button.clicked.connect(self.run_query_requested.emit)
        self.stop_button.clicked.connect(self.stop_query_requested.emit)
        toolbar_layout.addWidget(self.run_button)
        toolbar_layout.addWidget(self.stop_button)

        self.connection_combo = DownwardComboBox()
        self.connection_combo.setObjectName("queryConnectionCombo")
        self.connection_combo.setToolTip("Active database connection for this query tab")
        self.connection_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.connection_combo.setMinimumWidth(170)
        self.connection_combo.setMaximumWidth(340)

        self._add_separator(toolbar_layout)

        # File Operations
        icon_color = self.theme_colors.get('icon', '#6C757D')
        self.new_query_button = QPushButton(qta.icon('fa5s.plus-square', color=icon_color), "", toolTip="New Query")
        self.open_query_button = QPushButton(qta.icon('fa5s.folder-open', color=icon_color), "", toolTip="Open Query File")
        self.save_query_button = QPushButton(qta.icon('fa5s.save', color=icon_color), "", toolTip="Save Query")
        self.save_snippet_button = QPushButton(qta.icon('fa5s.bookmark', color=icon_color), "", toolTip="Save as Snippet")

        self.new_query_button.clicked.connect(self.add_new_tab)
        self.open_query_button.clicked.connect(self.open_query_file)
        self.save_query_button.clicked.connect(self.save_current_query)
        self.save_snippet_button.clicked.connect(lambda: self.save_snippet_requested.emit(self.query_tabs.currentIndex()))

        toolbar_layout.addWidget(self.new_query_button)
        toolbar_layout.addWidget(self.open_query_button)
        toolbar_layout.addWidget(self.save_query_button)
        toolbar_layout.addWidget(self.save_snippet_button)

        self._add_separator(toolbar_layout)

        # Formatting Operations
        self.format_sql_button = QPushButton(qta.icon('fa5s.code', color=icon_color), "", toolTip="Format SQL")
        self.comment_button = QPushButton(qta.icon('fa5s.indent', color=icon_color), "", toolTip="Comment Selected Lines")
        self.uncomment_button = QPushButton(qta.icon('fa5s.outdent', color=icon_color), "", toolTip="Uncomment Selected Lines")
        
        self.format_sql_button.clicked.connect(self.format_sql)
        self.comment_button.clicked.connect(self.comment_selection)
        self.uncomment_button.clicked.connect(self.uncomment_selection)
        
        toolbar_layout.addWidget(self.format_sql_button)
        toolbar_layout.addWidget(self.comment_button)
        toolbar_layout.addWidget(self.uncomment_button)

        self._add_separator(toolbar_layout)

        # Other
        self.explain_button = QPushButton(qta.icon('fa5s.project-diagram', color=icon_color), "", toolTip="Explain Query Plan")
        self.explain_button.clicked.connect(self.explain_requested.emit)
        toolbar_layout.addWidget(self.explain_button)

        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.connection_combo)

        self.layout.addWidget(toolbar_widget)

    def _add_separator(self, layout: QHBoxLayout) -> None:
        """Insert a vertical separator into the toolbar layout."""
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

    def _setup_tabs(self) -> None:
        """Create the query tab widget and placeholder area."""
        self.query_tabs = QueryTabWidget()
        self.query_tabs.setObjectName("queryEditorTabs")
        self.query_tabs.setDocumentMode(False)
        self.query_tabs.setContextMenuPolicy(Qt.CustomContextMenu)

        tab_font = self.query_tabs.font()
        tab_font.setPointSize(9)
        self.query_tabs.setFont(tab_font)
        
        self.query_tabs.fileDropped.connect(self.file_dropped.emit)
        self.query_tabs.currentChanged.connect(self._on_tab_changed_internal)
        self.query_tabs.tabBarDoubleClicked.connect(self.rename_tab)
        self.query_tabs.customContextMenuRequested.connect(self._show_query_tab_context_menu)
        self.query_tabs.tabMiddleClicked.connect(self.close_tab)
        
        self.query_tabs.setVisible(False)
        self.layout.addWidget(self.query_tabs)

        self.query_placeholder = QueryEmptyState(theme_colors=self.theme_colors, parent=self)
        self.query_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.query_placeholder.newQueryRequested.connect(lambda: self.add_new_tab())
        self.query_placeholder.openFileRequested.connect(self.open_query_file)
        self.query_placeholder.fileDropped.connect(self.file_dropped.emit)
        self.layout.addWidget(self.query_placeholder)


    # --- TAB MANAGEMENT ---

    def add_new_tab(
        self,
        content: str = "",
        tab_name: str | None = None,
        connection_key: str | None = None,
        snippet_path: str | None = None,
    ) -> QueryTextEdit:
        """Create a new query tab, or reuse the active blank tab when appropriate."""
        current_idx = self.query_tabs.currentIndex()
        if current_idx != -1:
            active_editor = self.query_tabs.widget(current_idx)
            is_empty = active_editor.toPlainText().strip() == ""
            is_default_name = active_editor.full_tab_name.startswith("Query ")
            
            if is_empty and is_default_name:
                if not content and not tab_name and not connection_key and not snippet_path:
                    return active_editor

                if tab_name:
                    active_editor.full_tab_name = tab_name
                    self.query_tabs.setTabText(current_idx, tab_name)
                    self.query_tabs.setTabToolTip(current_idx, tab_name)

                if content:
                    active_editor.setPlainText(content)

                if connection_key:
                    active_editor.connection_key = connection_key

                active_editor.snippet_file_path = snippet_path

                if active_editor.highlighter:
                    active_editor.highlighter.rehighlight()

                return active_editor
            
        self.query_tabs.setVisible(True)
        self.query_placeholder.setVisible(False)
        self.query_tab_counter += 1

        if snippet_path and not tab_name:
            tab_name = os.path.splitext(os.path.basename(snippet_path))[0]

        if not tab_name:
            tab_name = f"Query {self.query_tab_counter}"

        editor = QueryTextEdit(theme_colors=self.theme_colors)
        main_win = self.window()
        editor.set_main_window(main_win)
        editor.zoomRequested.connect(self.change_font_size)

        editor.full_tab_name = tab_name
        editor.snippet_file_path = snippet_path
        if content:
            editor.setPlainText(content)

        is_wrapped = self.settings_manager.get('word_wrap', False)
        mode = QPlainTextEdit.WidgetWidth if is_wrapped else QPlainTextEdit.NoWrap
        editor.setLineWrapMode(mode)

        syntax_colors = self.theme_colors.get('syntax', {})
        db_keywords = getattr(main_win, 'db_keywords', [])
        db_functions = getattr(main_win, 'db_functions', [])
        editor.highlighter = SqlHighlighter(editor.document(), db_keywords, db_functions, theme_colors=syntax_colors)

        if sys.platform == 'win32':
            font = QFont('Consolas')
        else:
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(self.settings_manager.get('font_size', 11))
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
        editor.setFont(font)
        editor.setTabStopDistance(QFontMetrics(font).horizontalAdvance(' ') * 4)

        editor.showFind.connect(lambda: self.show_find_dialog(replace=False))
        editor.showFindReplace.connect(lambda: self.show_find_dialog(replace=True))
        editor.setPlaceholderText("")
        editor.run_query.connect(self.run_query_requested.emit)

        if hasattr(main_win, 'conn_manager') and main_win.conn_manager.db_connections:
            if connection_key and connection_key in main_win.conn_manager.db_connections:
                editor.connection_key = connection_key
            else:
                connection_combo = getattr(main_win, 'connection_combo', None)
                active_key = connection_combo.currentData() if connection_combo is not None else None
                editor.connection_key = active_key if active_key else list(main_win.conn_manager.db_connections.keys())[0]

        tab_index = self.query_tabs.addTab(editor, tab_name)
        self.query_tabs.setTabToolTip(tab_index, tab_name)

        close_button = QToolButton()
        close_button.setObjectName("queryTabCloseButton")
        close_button.setText("✕")
        close_button.setAutoRaise(True)
        btn_font = close_button.font()
        btn_font.setPointSize(8)
        btn_font.setBold(True)
        close_button.setFont(btn_font)

        close_button.clicked.connect(lambda checked=False, e=editor: self.close_tab(self.query_tabs.indexOf(e)))
        self.query_tabs.tabBar().setTabButton(tab_index, QTabBar.RightSide, close_button)
        self.query_tabs.setCurrentIndex(tab_index)
        return editor

    def close_tab(self, index: int) -> None:
        """Close a query tab by index."""
        self.query_tabs.removeTab(index)
        if self.query_tabs.count() == 0:
            self.query_tabs.setVisible(False)
            self.query_placeholder.setVisible(True)

    def close_other_tabs(self, index_to_keep: int) -> None:
        """Close all tabs except the provided one."""
        for i in range(self.query_tabs.count() - 1, -1, -1):
            if i != index_to_keep:
                self.query_tabs.removeTab(i)

    def close_all_tabs(self) -> None:
        """Close all query tabs and show the placeholder."""
        self.query_tabs.clear()
        self.query_tabs.setVisible(False)
        self.query_placeholder.setVisible(True)

    def rename_tab(self, index: int) -> None:
        """Prompt the user to rename a tab."""
        widget = self.query_tabs.widget(index)
        if not widget:
            return

        current_name = widget.full_tab_name
        new_name, ok = QInputDialog.getText(self, "Rename Tab", "Enter new tab name:", text=current_name)

        if ok and new_name:
            widget.full_tab_name = new_name
            self.query_tabs.setTabText(index, new_name)
            self.query_tabs.setTabToolTip(index, new_name)

    def _show_query_tab_context_menu(self, point: QPoint) -> None:
        """Show the context menu for a query tab."""
        index = self.query_tabs.tabBar().tabAt(point)
        if index == -1:
            return

        menu = QMenu()
        save_action = menu.addAction("Save as File")
        save_snippet_action = menu.addAction("Save as Snippet")
        menu.addSeparator()
        rename_action = menu.addAction("Rename Tab")
        menu.addSeparator()
        close_action = menu.addAction("Close")
        close_other_action = menu.addAction("Close Other Tabs")
        close_all_action = menu.addAction("Close All Tabs")

        if self.query_tabs.count() <= 1:
            close_other_action.setEnabled(False)

        action = menu.exec(self.query_tabs.mapToGlobal(point))

        if action == save_action:
            self.save_query(index)
        elif action == save_snippet_action:
            self.save_snippet_requested.emit(index)
        elif action == rename_action:
            self.rename_tab(index)
        elif action == close_action:
            self.close_tab(index)
        elif action == close_other_action:
            self.close_other_tabs(index)
        elif action == close_all_action:
            self.close_all_tabs()

    # --- FILE OPERATIONS ---

    def save_current_query(self) -> None:
        """Save the currently active query tab to a file."""
        if self.query_tabs.currentIndex() != -1:
            self.save_query(self.query_tabs.currentIndex())

    def save_query(self, index: int) -> None:
        """Save the query contents from a specific tab index."""
        editor = self.query_tabs.widget(index)
        if not editor:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Query", "", "SQL Files (*.sql);;All Files (*)")
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(editor.toPlainText())
            except Exception as e:
                QMessageBox.critical(self, "Error Saving File", f"Could not save file:\n{e}")

    def open_query_file(self) -> None:
        """Open a SQL file into a new query tab."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Query File", "", "SQL Files (*.sql);;All Files (*)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    query_text = f.read()
                self.add_new_tab(content=query_text, tab_name=os.path.basename(file_path))
            except Exception as e:
                QMessageBox.critical(self, "Error Opening File", f"Could not open file:\n{e}")

    # --- EDITOR OPERATIONS ---

    def format_sql(self) -> None:
        """Format the current selection or full editor SQL text."""
        editor = self.get_active_editor()
        main_win = self.window()
        if not editor or not hasattr(main_win, "sql_formatter"):
            return

        cursor = editor.textCursor()
        sql_to_format = cursor.selectedText() if cursor.hasSelection() else editor.toPlainText()

        formatted_sql = main_win.sql_formatter.format(sql_to_format)

        if formatted_sql != sql_to_format:
            if cursor.hasSelection():
                cursor.insertText(formatted_sql)
            else:
                editor.setPlainText(formatted_sql)

            if editor.highlighter:
                editor.highlighter.rehighlight()

            self.show_message_requested.emit("SQL formatted successfully.")

    def comment_selection(self) -> None:
        """Prefix the selected lines with SQL comment markers."""
        editor = self.get_active_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            return

        cursor.beginEditBlock()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()

        cursor.setPosition(start_pos)
        cursor.movePosition(QTextCursor.StartOfLine)

        while cursor.position() < end_pos or cursor.atBlockEnd():
            cursor.insertText("--")
            if not cursor.movePosition(QTextCursor.NextBlock):
                break
            end_pos += 2
        cursor.endEditBlock()

    def uncomment_selection(self) -> None:
        """Remove SQL comment markers from selected lines when present."""
        editor = self.get_active_editor()
        if not editor:
            return
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            return

        cursor.beginEditBlock()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()

        cursor.setPosition(start_pos)
        cursor.movePosition(QTextCursor.StartOfLine)

        blocks_to_change = []
        while cursor.position() < end_pos or cursor.atBlockEnd():
            line_text = cursor.block().text()
            lstripped_text = line_text.lstrip()
            if lstripped_text.startswith("--"):
                start_index = len(line_text) - len(lstripped_text)
                blocks_to_change.append((cursor.block().position() + start_index, 2))
            if not cursor.movePosition(QTextCursor.NextBlock):
                break

        for pos, length in reversed(blocks_to_change):
            cursor.setPosition(pos)
            cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, length)
            cursor.removeSelectedText()
        cursor.endEditBlock()

    # --- FIND AND REPLACE ---

    def show_find_dialog(self, replace: bool = False) -> None:
        """Open the modeless find or find/replace dialog."""
        editor = self.get_active_editor()
        if not editor:
            return

        if not hasattr(self, "find_dialog") or not self.find_dialog.isVisible():
            self.find_dialog = FindReplaceDialog(self)
            self.find_dialog.findNext.connect(self.on_find_next)
            self.find_dialog.replace.connect(self.on_replace)
            self.find_dialog.replaceAll.connect(self.on_replace_all)

        selected_text = editor.textCursor().selectedText()
        if selected_text:
            self.find_dialog.find_input.setText(selected_text)

        if replace:
            self.find_dialog.show_find_replace()
        else:
            self.find_dialog.show_find()

    def on_find_next(self, text: str, flags: QTextCursor.MoveMode | Any) -> None:
        """Find the next occurrence, wrapping to the top when needed."""
        editor = self.get_active_editor()
        if editor and text:
            if not editor.find(text, flags):
                cursor = editor.textCursor()
                cursor.movePosition(QTextCursor.Start)
                editor.setTextCursor(cursor)
                editor.find(text, flags)

    def on_replace(self, replace_text: str) -> None:
        """Replace the current selection and continue searching."""
        editor = self.get_active_editor()
        if editor and editor.textCursor().hasSelection():
            editor.textCursor().insertText(replace_text)
            self.on_find_next(self.find_dialog.find_input.text(), self.find_dialog.get_find_flags())

    def on_replace_all(self, find_text: str, replace_text: str, flags: Any) -> None:
        """Replace all matches in the active editor and show a summary message."""
        editor = self.get_active_editor()
        if editor and find_text:
            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.Start)
            editor.setTextCursor(cursor)
            count = 0
            while editor.find(find_text, flags):
                editor.textCursor().insertText(replace_text)
                count += 1
            cursor.endEditBlock()
            self.show_message_requested.emit(f"Replaced {count} occurrence(s).")

    def show_go_to_line_dialog(self) -> None:
        """Open the Go to Line dialog for the active editor."""
        editor = self.get_active_editor()
        if not isinstance(editor, QueryTextEdit):
            return

        cursor = editor.textCursor()
        current_line = cursor.blockNumber() + 1
        max_lines = editor.blockCount()

        dialog = GoToLineDialog(current_line, max_lines, self)
        if dialog.exec() == QDialog.Accepted:
            target_line = dialog.get_line_number()
            block = editor.document().findBlockByNumber(target_line - 1)
            new_cursor = QTextCursor(block)
            editor.setTextCursor(new_cursor)
            editor.centerCursor()
            editor.setFocus()

    # --- ZOOMING AND FONT SIZE ---

    def zoom_in(self) -> None:
        """Increase query editor font size."""
        self.change_font_size(1)

    def zoom_out(self) -> None:
        """Decrease query editor font size."""
        self.change_font_size(-1)

    def change_font_size(self, delta: int) -> None:
        """Adjust query editor font size by a delta."""
        current_size = self.settings_manager.get("font_size", 11)
        new_size = max(6, min(72, current_size + delta))

        if new_size != current_size:
            self.settings_manager.set("font_size", new_size)
            self.apply_font_size_to_all_editors(new_size)
            self.settings_manager.save()

    def apply_font_size_to_all_editors(self, size: int) -> None:
        """Apply the chosen font size to every open query editor."""
        for i in range(self.query_tabs.count()):
            editor = self.query_tabs.widget(i)
            if isinstance(editor, QueryTextEdit):
                current_placeholder = editor.placeholderText()
                editor.setPlaceholderText("")
                
                font = editor.font()
                font.setPointSize(size)
                editor.setFont(font)
                
                editor.setPlaceholderText(current_placeholder)

    # --- UTILS ---

    def get_active_editor(self) -> QWidget | None:
        """Return the currently selected query tab widget."""
        return self.query_tabs.currentWidget()

    def refresh_theme(self, theme_colors: dict[str, Any]) -> None:
        """Refresh toolbar icons and the empty-state visuals to match the theme."""
        self.theme_colors = theme_colors
        icon_color = self.theme_colors.get("icon", "#6C757D")

        self.run_button.setIcon(qta.icon("ri.play-fill", color="green"))
        self.stop_button.setIcon(qta.icon("ri.stop-fill", color="red"))
        self.new_query_button.setIcon(qta.icon("fa5s.plus-square", color=icon_color))
        self.open_query_button.setIcon(qta.icon("fa5s.folder-open", color=icon_color))
        self.save_query_button.setIcon(qta.icon("fa5s.save", color=icon_color))
        self.save_snippet_button.setIcon(qta.icon("fa5s.bookmark", color=icon_color))
        self.format_sql_button.setIcon(qta.icon("fa5s.code", color=icon_color))
        self.comment_button.setIcon(qta.icon("fa5s.indent", color=icon_color))
        self.uncomment_button.setIcon(qta.icon("fa5s.outdent", color=icon_color))
        self.explain_button.setIcon(qta.icon("fa5s.project-diagram", color=icon_color))
        if isinstance(self.query_placeholder, QueryEmptyState):
            self.query_placeholder.theme_colors = theme_colors
            self.query_placeholder.update_theme()

    def get_session_state(self) -> list[dict[str, Any]]:
        """Serializes the currently open tabs into a list of dictionaries for saving the session."""
        open_tabs_data = []
        for i in range(self.query_tabs.count()):
            widget = self.query_tabs.widget(i)
            if isinstance(widget, QueryTextEdit):
                tab_data = {
                    "content": widget.toPlainText(),
                    "name": self.query_tabs.tabText(i),
                    "connection_key": getattr(widget, "connection_key", None),
                    "snippet_file_path": getattr(widget, "snippet_file_path", None),
                }
                open_tabs_data.append(tab_data)
        return open_tabs_data

    def _on_tab_changed_internal(self, index: int) -> None:
        """Update toolbar state when the current tab changes."""
        editor = self.query_tabs.widget(index)
        is_running = getattr(editor, "is_running", False) if editor else False

        # Update toolbar buttons based on the specific tab's state
        self.run_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)

        self.tab_changed.emit(index)

    def on_query_started(self) -> None:
        """Disables Run, enables Stop, and resets editor state."""
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        editor = self.get_active_editor()
        if editor:
            editor.results_df = editor.error_message = editor.info_message = None
            editor.column_widths = {}

            editor.is_running = True
            editor.status_message = "Executing query..."

            engine = self.conn_manager.get_db(getattr(editor, "connection_key", None))
            editor.stats_text = f"{engine.get_display_name()} | 0.0000s | 0 rows" if engine else "Ready"

        self.tab_changed.emit(self.query_tabs.currentIndex())

    def on_query_completed(
        self,
        editor: QueryTextEdit | None,
        df: Any,
        error_msg: str | None,
        info_msg: str | None,
        duration: float,
        is_ddl: bool,
        peak_memory: int = 0,
    ) -> None:
        """Re-enables Run, disables Stop, updates editor state, and logs history."""
        if not editor:
            return

        editor.is_running = False

        # Only update the global toolbar buttons if the completed query is the one we are currently looking at
        if editor == self.get_active_editor():
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)

        editor.info_message, editor.error_message = info_msg, error_msg
        row_count = len(df) if df is not None else 0

        # Process Results
        if df is not None:
            editor.results_df, editor.status_message = df, "Query executed successfully."
        elif info_msg:
            editor.results_df, editor.status_message = None, "Explain plan generated."
        else:
            editor.results_df, editor.status_message = None, "Query failed with an error."

        # Process Stats (NO Peak Mem string formatting here!)
        engine = self.conn_manager.get_db(getattr(editor, "connection_key", None))
        display_name = engine.get_display_name() if engine else "Unknown"
        editor.stats_text = f"{display_name} | {duration:.4f}s | {row_count} rows"

        # Save the RAW bytes so ResultsPanel can use them for the progress bar
        editor.peak_memory = peak_memory

        # Save to History
        if getattr(editor, "last_executed_query", None):
            limit = self.settings_manager.get("history_retention_limit", 10000)
            self.history_manager.add_entry(editor.last_executed_query, duration, row_count, limit)

        # Emit signal to tell MainWindow to refresh the Results Panel
        self.tab_changed.emit(self.query_tabs.currentIndex())

    def restore_session(self, saved_tabs: list[dict[str, Any]]) -> None:
        """Restores all query tabs from the last saved session."""
        for tab_data in saved_tabs:
            content = tab_data.get("content", "")
            name = tab_data.get("name", "Query")
            connection_key = tab_data.get("connection_key")
            snippet_file_path = tab_data.get("snippet_file_path")
            self.add_new_tab(content, name, connection_key, snippet_file_path)

        if self.query_tabs.count() == 0:
            self.add_new_tab()

    def toggle_word_wrap(self, checked: bool) -> None:
        """Toggles word wrap for all query editors."""
        self.settings_manager.set("word_wrap", checked)
        mode = QPlainTextEdit.WidgetWidth if checked else QPlainTextEdit.NoWrap

        for i in range(self.query_tabs.count()):
            editor = self.query_tabs.widget(i)
            if isinstance(editor, QueryTextEdit):
                editor.setLineWrapMode(mode)

    def update_all_editors_theme(
        self,
        theme_colors: dict[str, Any],
        db_keywords: list[str] | set[str],
        db_functions: list[str] | set[str],
    ) -> None:
        """Iterates through all open tabs and updates their theme."""
        for i in range(self.query_tabs.count()):
            editor = self.query_tabs.widget(i)
            if isinstance(editor, QueryTextEdit):
                editor.update_theme_colors(theme_colors, db_keywords, db_functions)

    def reassign_disconnected_tabs(
        self,
        valid_keys: list[str] | set[str],
        default_key: str | None,
    ) -> None:
        """Re-assigns query tabs that were using a disconnected DB."""
        for i in range(self.query_tabs.count()):
            editor = self.query_tabs.widget(i)
            if getattr(editor, "connection_key", None) not in valid_keys:
                editor.connection_key = default_key

        if default_key is None and self.query_tabs.count() == 0:
            self.add_new_tab()