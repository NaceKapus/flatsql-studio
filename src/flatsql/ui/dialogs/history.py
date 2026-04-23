"""Query history dialog with syntax highlighting."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont


from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from flatsql.core.highlighter import SqlHighlighter


class HistoryDialog(QDialog):
    """Dialog for browsing and selecting queries from execution history.
    
    Features a dual-pane layout with history list on the left and syntax-highlighted
    preview on the right. Supports opening selected queries in a new tab or as a
    queryable SQL table via the history manager.
    """

    def __init__(
        self,
        theme_colors: dict | None,
        settings_manager: object,
        history_manager: object,
        db_keywords: set[str],
        db_functions: set[str],
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the history dialog.
        
        Args:
            theme_colors: Dictionary mapping theme color names to values (may include 'syntax' key).
            settings_manager: Settings manager instance for retrieving user preferences.
            history_manager: History manager instance for querying stored query history.
            db_keywords: Set of SQL keywords for syntax highlighting.
            db_functions: Set of SQL function names for syntax highlighting.
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.theme_colors = theme_colors
        self.settings_manager = settings_manager
        self.history_manager = history_manager
        self.db_keywords = db_keywords
        self.db_functions = db_functions

        self.wants_query_table = False

        self.setWindowTitle("Query History")
        self.resize(1000, 600)

        layout = QVBoxLayout(self)

        # Use a splitter for the Harlequin-style dual pane
        splitter = QSplitter(Qt.Horizontal)

        # --- Left Side: History List ---
        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        self.list_widget.setSpacing(4)

        splitter.addWidget(self.list_widget)

        # --- Right Side: Syntax Highlighted Preview ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_editor = QPlainTextEdit()
        self.preview_editor.setReadOnly(True)
        if sys.platform == 'win32':
            font = QFont("Consolas")
        else:
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(self.settings_manager.get("font_size", 11))
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
        self.preview_editor.setFont(font)

        # Apply the SQL syntax highlighter to the preview pane
        syntax_colors = (self.theme_colors.get("syntax") if self.theme_colors else {})
        self.highlighter = SqlHighlighter(
            self.preview_editor.document(),
            self.db_keywords,
            self.db_functions,
            theme_colors=syntax_colors,
        )

        right_layout.addWidget(self.preview_editor)
        splitter.addWidget(right_widget)

        # Set splitter proportions (approx 1/3 list, 2/3 preview)
        splitter.setSizes([350, 650])
        layout.addWidget(splitter)

        # --- Bottom Buttons ---
        btn_layout = QHBoxLayout()

        # Left button: Query via SQL
        self.query_table_btn = QPushButton("Query via SQL")
        self.query_table_btn.clicked.connect(self._on_query_table_clicked)
        btn_layout.addWidget(self.query_table_btn)

        btn_layout.addStretch()

        # Right buttons: Close and Open in New Tab
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)

        self.open_btn = QPushButton("Open in New Tab")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.accept)

        btn_layout.addWidget(close_btn)
        btn_layout.addWidget(self.open_btn)

        layout.addLayout(btn_layout)

        self._load_history()

    def _load_history(self) -> None:
        """Load query history from the history manager and populate the list widget."""
        history = self.history_manager.get_recent_history(limit=200)
        for item_data in history:
            query = item_data.get("query", "")
            ts = item_data.get("timestamp", "")
            dur = item_data.get("duration", 0.0)
            rows = item_data.get("rows", 0)
            stats = f"{rows} records in {dur:.3f}s"

            # Create a blank list item to hold our custom widget
            item = QListWidgetItem()
            item.setData(Qt.UserRole, query)
            self.list_widget.addItem(item)

            # Create the custom widget container
            item_widget = QWidget()
            item_layout = QVBoxLayout(item_widget)
            item_layout.setContentsMargins(4, 4, 4, 4)
            item_layout.setSpacing(4)

            # Top row: Timestamp (Left) and Stats (Right)
            top_layout = QHBoxLayout()
            ts_label = QLabel(f"<b>{ts}</b>")
            stats_label = QLabel(f"<b>{stats}</b>")

            top_layout.addWidget(ts_label)
            top_layout.addStretch()
            top_layout.addWidget(stats_label)

            item_layout.addLayout(top_layout)

            # Bottom row: Query preview with ellipsis if truncated
            preview_query = query.replace("\n", " ")
            if len(preview_query) > 90:
                preview_query = preview_query[:87] + "..."

            query_label = QLabel(preview_query)
            query_label.setWordWrap(True)
            item_layout.addWidget(query_label)

            # Apply the size of our custom widget to the list item
            item.setSizeHint(item_widget.sizeHint())

            # Inject the custom widget into the blank list item
            self.list_widget.setItemWidget(item, item_widget)

    def _on_selection_changed(self, index: int) -> None:
        """Update the preview editor when a history item is selected.
        
        Args:
            index: Index of the selected item in the list widget.
        """
        item = self.list_widget.item(index)
        if item:
            self.preview_editor.setPlainText(item.data(Qt.UserRole))
            self.open_btn.setEnabled(True)
        else:
            self.preview_editor.clear()
            self.open_btn.setEnabled(False)

    def get_selected_query(self) -> str | None:
        """Retrieve the currently selected query string.
        
        Returns:
            The selected query string, or None if no item is selected.
        """
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return None

    def _on_query_table_clicked(self) -> None:
        """Set flag to load history as a queryable SQL table and close the dialog."""
        self.wants_query_table = True
        self.accept()
