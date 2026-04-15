"""Results display panel with data grid, profile dashboard, and message viewer.

Displays query results in a tabbed interface with grid view, profile cards,
and query status messages with live memory tracking.
"""
from __future__ import annotations

import html
from typing import Any

import polars as pl
import qtawesome as qta
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QTableView,
    QTextEdit, QPushButton, QLabel, QMenu, QApplication, QStackedWidget, QMessageBox
)
from PySide6.QtCore import Signal, Qt, QMimeData
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut, QPalette


from flatsql.ui.models import PolarsModel
from flatsql.ui.widgets import ProfileDashboard
from flatsql.ui.dialogs.data_viewer import DataViewerDialog


class ResultsPanel(QFrame):
    """Panel for displaying query results with grid, profiles, and messages."""

    export_requested = Signal()

    def __init__(self, settings_manager: Any, parent: QWidget | None = None) -> None:
        """Initialize the results panel with settings manager.
        
        Args:
            settings_manager: Manager for user settings and runtime preferences.
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.settings_manager = settings_manager
        
        self.setObjectName("results_frame")
        self.setFrameShape(QFrame.StyledPanel)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 10, 0, 0)
        self.layout.setSpacing(0)
        
        self._setup_tabs()
        self._setup_status_bar()
        self.setVisible(False)

    def _setup_tabs(self) -> None:
        """Set up the tabbed interface with results, profiles, and messages."""
        self.results_tabs = QTabWidget()
        
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 8, 0)
        corner_layout.setSpacing(5)

        icon_color = self._toolbar_icon_color()

        self.toggle_view_button = QPushButton(qta.icon('fa5s.list', color=icon_color), " Grid View")
        self.toggle_view_button.setObjectName("resultsToolbarButton")
        self.toggle_view_button.setFlat(True)
        self.toggle_view_button.setCheckable(True)
        self.toggle_view_button.setVisible(False)
        self.toggle_view_button.clicked.connect(self._on_toggle_view_clicked)
        corner_layout.addWidget(self.toggle_view_button)

        self.export_button = QPushButton(qta.icon('fa5s.download', color=icon_color), " Export")
        self.export_button.setObjectName("resultsToolbarButton")
        self.export_button.setFlat(True)
        self.export_button.clicked.connect(self.export_requested.emit)
        corner_layout.addWidget(self.export_button)

        self.visualize_button = QPushButton(qta.icon('fa5s.chart-bar', color=icon_color), " Visualize")
        self.visualize_button.setObjectName("resultsToolbarButton")
        self.visualize_button.setFlat(True)
        self.visualize_button.clicked.connect(self._open_visualize_dialog)
        corner_layout.addWidget(self.visualize_button)

        self.results_tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)
        self.layout.addWidget(self.results_tabs)
        
        results_page = QWidget()
        results_page_layout = QVBoxLayout(results_page)
        
        self.results_stack = QStackedWidget()
        
        self.results_view = QTableView()
        self.results_view.verticalHeader().hide()
        self.results_view.setShowGrid(True)
        self.results_view.setSortingEnabled(False)
        
        self.results_view.verticalHeader().setDefaultSectionSize(30)
        self.results_view.verticalHeader().setMinimumSectionSize(20)
        
        header = self.results_view.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        header.sectionClicked.connect(self._on_column_header_clicked)
        header.sectionDoubleClicked.connect(self._on_column_header_double_clicked)
        self.results_view.clicked.connect(self._on_results_view_clicked)
        self.results_view.doubleClicked.connect(self._on_results_view_double_clicked)
        
        self.results_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_view.customContextMenuRequested.connect(self._show_results_context_menu)
        self.results_view.setModel(PolarsModel(pl.DataFrame()))
        
        copy_shortcut = QShortcut(QKeySequence.Copy, self.results_view)
        copy_shortcut.activated.connect(lambda: self._copy_results(fmt='tsv', with_headers=False))

        theme_manager = getattr(self.window(), 'theme_manager', None)
        self.profile_page = ProfileDashboard(theme_manager)
        
        self.results_stack.addWidget(self.results_view)
        self.results_stack.addWidget(self.profile_page)
        
        results_page_layout.addWidget(self.results_stack)
        
        messages_page = QWidget()
        messages_page_layout = QVBoxLayout(messages_page)
        self.messages_view = QTextEdit()
        self.messages_view.setReadOnly(True)

        self._apply_messages_font()
        self.messages_view.setLineWrapMode(QTextEdit.NoWrap)
        
        messages_page_layout.addWidget(self.messages_view)

        self.results_tabs.addTab(results_page, "Results")
        self.results_tabs.addTab(messages_page, "Messages")

    def _apply_messages_font(self) -> None:
        """Apply a stable monospace font to the messages viewer.

        The query editor font size is user-adjustable and can change via zoom.
        The messages tab should remain readable and not track editor zoom.
        """
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setStyleHint(QFont.Monospace)
        font.setStyleStrategy(QFont.PreferAntialias)

        app_font_size = QApplication.font().pointSize()
        font.setPointSize(app_font_size if app_font_size > 0 else 10)
        self.messages_view.setFont(font)

    def _format_bytes(self, size_bytes: int) -> str:
        """Format byte count as human-readable string.
        
        Args:
            size_bytes: Number of bytes to format.
            
        Returns:
            Formatted string (e.g., '1.5 MB').
        """
        if size_bytes == 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def _parse_memory_to_bytes(self, mem_str: str) -> int:
        """Parse memory string (e.g. '2GB') to byte count.
        
        Args:
            mem_str: Memory size string with unit suffix.
            
        Returns:
            Byte count (0 on parse failure).
        """
        if not mem_str:
            return 0
        mem_str = mem_str.strip().upper()
        try:
            if mem_str.endswith('GB'):
                return int(float(mem_str[:-2]) * 1024**3)
            if mem_str.endswith('MB'):
                return int(float(mem_str[:-2]) * 1024**2)
            if mem_str.endswith('KB'):
                return int(float(mem_str[:-2]) * 1024)
            if mem_str.endswith('B'):
                return int(float(mem_str[:-1]))
            return int(mem_str)
        except ValueError:
            return 0

    def update_live_stats(self, editor: Any, base_stats: str, mem_bytes: int) -> None:
        """Update live statistics display with memory usage.
        
        Args:
            editor: The active query editor.
            base_stats: Base statistics text (e.g., connection info).
            mem_bytes: Current memory usage in bytes.
        """
        if editor:
            editor.stats_text = base_stats
            editor.peak_memory = max(getattr(editor, 'peak_memory', 0), mem_bytes)
            
        main_win = self.window()
        if hasattr(main_win, 'query_panel'):
            active_editor = main_win.query_panel.get_active_editor()
            if editor is not active_editor:
                return

        max_mem_str = self.settings_manager.get('engine_max_memory', '')
        mem_str = self._format_bytes(mem_bytes)
        
        if max_mem_str:
            self.stats_label.setText(f"{base_stats} | Max Memory: {mem_str} / {max_mem_str.upper()}")
        else:
            self.stats_label.setText(f"{base_stats} | Max Memory: {mem_str}")

    def update_theme(self, theme_manager: Any) -> None:
        """Update icons and styling based on current theme.
        
        Args:
            theme_manager: The active theme manager.
        """
        text_color = self._toolbar_icon_color()
        
        if self.toggle_view_button.isChecked():
            self.toggle_view_button.setIcon(qta.icon('fa5s.th-large', color=text_color))
        else:
            self.toggle_view_button.setIcon(qta.icon('fa5s.list', color=text_color))
        
        self.export_button.setIcon(qta.icon('fa5s.download', color=text_color))
        self.visualize_button.setIcon(qta.icon('fa5s.chart-bar', color=text_color))
        self.profile_page.theme_manager = theme_manager

    def _toolbar_icon_color(self) -> str:
        """Return themed toolbar icon color from current application palette."""
        return QApplication.palette().color(QPalette.WindowText).name()

    def _on_toggle_view_clicked(self, checked: bool) -> None:
        """Toggle between grid and profile card views.
        
        Args:
            checked: True if card view should be shown, False for grid.
        """
        if checked:
            self.toggle_view_button.setText(" Card View")
            self.toggle_view_button.setIcon(qta.icon('fa5s.th-large', color=self._toolbar_icon_color()))
            self.results_stack.setCurrentWidget(self.results_view)
        else:
            self.toggle_view_button.setText(" Grid View")
            self.toggle_view_button.setIcon(qta.icon('fa5s.list', color=self._toolbar_icon_color()))
            self.results_stack.setCurrentWidget(self.profile_page)

    def _open_visualize_dialog(self) -> None:
        """Open visualization dialog for current results data."""
        model = self.results_view.model()
        if model is None or getattr(model, '_data', None) is None or model._data.is_empty():
            QMessageBox.warning(self, "No Data", "There is no data to visualize. Please run a query first.")
            return
            
        from flatsql.ui.dialogs.visualize import VisualizeDialog
        theme_colors = getattr(self.window(), 'theme_colors', {})
        dialog = VisualizeDialog(model._data, theme_colors, self)
        dialog.exec()

    def _setup_status_bar(self) -> None:
        """Set up the status bar with message and statistics labels."""
        status_bar_widget = QWidget()
        status_bar_widget.setObjectName("statusBar")
        status_bar_layout = QHBoxLayout(status_bar_widget)
        status_bar_layout.setContentsMargins(5, 3, 5, 3)
        
        self.status_message_label = QLabel("Ready")
        self.stats_label = QLabel("")
        
        status_bar_layout.addWidget(self.status_message_label)
        status_bar_layout.addStretch(1)
        status_bar_layout.addWidget(self.stats_label)
        
        self.layout.addWidget(status_bar_widget)

    def _on_results_view_clicked(self, index: Any) -> None:
        """Handle click on first column to select entire row.
        
        Args:
            index: The clicked model index.
        """
        if index.column() == 0:
            self.results_view.selectRow(index.row())

    def _on_results_view_double_clicked(self, index: Any) -> None:
        """Open data viewer dialog for cell contents.
        
        Args:
            index: The double-clicked model index.
        """
        if not index.isValid() or index.column() == 0:
            return
            
        val = self.results_view.model()._data.item(index.row(), index.column() - 1)
        
        if val is not None:
            dialog = DataViewerDialog(val, self)
            dialog.exec()

    def _on_column_header_clicked(self, index: int) -> None:
        """Handle column header click for selection.
        
        Args:
            index: The clicked column index.
        """
        if index == 0: 
            self.results_view.selectAll()
            return
        self.results_view.clearSelection()
        self.results_view.selectColumn(index)

    def _on_column_header_double_clicked(self, index: int) -> None:
        """Handle column header double-click for sorting.
        
        Args:
            index: The double-clicked column index.
        """
        if index == 0:
            return
        header = self.results_view.horizontalHeader()
        current_section = header.sortIndicatorSection()
        current_order = header.sortIndicatorOrder()

        if index != current_section:
            new_order = Qt.DescendingOrder
        else:
            new_order = Qt.AscendingOrder if current_order == Qt.DescendingOrder else Qt.DescendingOrder

        self.results_view.model().sort(index, new_order)

    def _show_results_context_menu(self, point: Any) -> None:
        """Display context menu for copy operations on selected cells.
        
        Args:
            point: The position where the context menu was requested.
        """
        model = self.results_view.model()
        if model is not None and model.rowCount() > 0:
            menu = QMenu()
            copy_action = menu.addAction("Copy")
            copy_headers_action = menu.addAction("Copy with Headers")
            menu.addSeparator()
            copy_markdown_action = menu.addAction("Copy as Markdown")
            copy_html_action = menu.addAction("Copy as HTML")
            
            action = menu.exec(self.results_view.viewport().mapToGlobal(point))

            if action == copy_action: 
                self._copy_results(fmt='tsv', with_headers=False)
            elif action == copy_headers_action: 
                self._copy_results(fmt='tsv', with_headers=True)
            elif action == copy_markdown_action: 
                self._copy_results(fmt='markdown', with_headers=True)
            elif action == copy_html_action: 
                self._copy_results(fmt='html', with_headers=True)

    def _copy_results(self, fmt: str = 'tsv', with_headers: bool = False) -> None:
        """Format and copy selected grid cells to clipboard.
        
        Args:
            fmt: Output format ('tsv', 'markdown', or 'html').
            with_headers: Include column headers in output.
        """
        selection = self.results_view.selectionModel()
        indexes = selection.selectedIndexes()

        if not indexes:
            return

        rows_data: dict[int, dict[int, str]] = {}
        min_col, max_col = float('inf'), float('-inf')
        for index in indexes:
            row, col = index.row(), index.column()
            if row not in rows_data:
                rows_data[row] = {}
            rows_data[row][col] = str(index.data())
            if col < min_col:
                min_col = col
            if col > max_col:
                max_col = col

        sorted_rows = sorted(rows_data.keys())
        model = self.results_view.model()
        
        headers: list[str] = []
        if with_headers:
            headers = [str(model.headerData(c, Qt.Horizontal, Qt.DisplayRole)) for c in range(int(min_col), int(max_col) + 1)]

        clipboard_text = ""

        if fmt == 'tsv':
            if with_headers:
                clipboard_text += "\t".join(headers) + "\n"
            for row in sorted_rows:
                row_list = [rows_data[row].get(col, "") for col in range(int(min_col), int(max_col) + 1)]
                clipboard_text += "\t".join(row_list) + "\n"

        elif fmt == 'markdown':
            def escape_md(text: str) -> str:
                return text.replace("|", "\\|").replace("\n", " ")
            if headers:
                clipboard_text += "| " + " | ".join([escape_md(h) for h in headers]) + " |\n"
                clipboard_text += "| " + " | ".join(["---"] * len(headers)) + " |\n"
            for row in sorted_rows:
                row_list = [escape_md(rows_data[row].get(col, "")) for col in range(int(min_col), int(max_col) + 1)]
                clipboard_text += "| " + " | ".join(row_list) + " |\n"

        elif fmt == 'html':
            clipboard_text = "<table>"
            if headers:
                clipboard_text += "<thead><tr>" + "".join([f"<th>{html.escape(h)}</th>" for h in headers]) + "</tr></thead>"
            clipboard_text += "<tbody>"
            for row in sorted_rows:
                clipboard_text += "<tr>" + "".join([f"<td>{html.escape(rows_data[row].get(col, ''))}</td>" for col in range(int(min_col), int(max_col) + 1)]) + "</tr>"
            clipboard_text += "</tbody></table>"

        clipboard_text = clipboard_text.rstrip('\n')

        mime_data = QMimeData()
        mime_data.setText(clipboard_text) 
        if fmt == 'html':
            mime_data.setHtml(clipboard_text)
        QApplication.clipboard().setMimeData(mime_data)
        
        self.status_message_label.setText(f"Copied {len(sorted_rows)} rows as {fmt.upper()}.")

    def display_results(self, editor: Any) -> None:
        """Render results, messages, and status based on editor state.
        
        Args:
            editor: The active query editor with results and messages.
        """
        has_results = False
        
        if not editor:
            self.results_view.horizontalHeader().setVisible(False)
            self.results_view.setModel(PolarsModel(pl.DataFrame()))
            self.messages_view.clear()
            self.stats_label.setText("Ready")
            self.status_message_label.setText("Ready")
            self.toggle_view_button.setVisible(False)
            self.setVisible(False)
            return
        
        is_running = getattr(editor, 'is_running', False)

        if getattr(editor, 'results_df', None) is not None:
            has_results = True
            df = editor.results_df
            
            self.results_view.horizontalHeader().setVisible(True)
            self.results_view.setModel(PolarsModel(df))
            
            if editor.column_widths:
                for col_idx, width in editor.column_widths.items():
                    self.results_view.setColumnWidth(col_idx, width)
            else:
                header = self.results_view.horizontalHeader()
                fm = header.fontMetrics()
                model = self.results_view.model()
                
                for i in range(header.count()):
                    if i == 0:
                        width = fm.horizontalAdvance("10000") + 20
                    else:
                        header_text = str(model.headerData(i, Qt.Horizontal, Qt.DisplayRole) or "")
                        header_width = fm.horizontalAdvance(header_text) + 35
                        
                        data_width = 0
                        if df is not None and not df.is_empty():
                            col_name = df.columns[i - 1] 
                            dtype = df.schema[col_name]
                            
                            if dtype in (pl.Struct, pl.List) or str(dtype).startswith("Struct") or str(dtype).startswith("List"):
                                data_width = 150 
                            else:
                                try:
                                    sample_series = df[col_name].head(1000).cast(pl.String).drop_nulls()
                                    unique_strings = sample_series.unique().to_list()
                                except Exception:
                                    raw_values = df[col_name].head(1000).drop_nulls().to_list()
                                    unique_strings = list(set(str(v) for v in raw_values))
                                    
                                if unique_strings:
                                    max_text_width = max(fm.horizontalAdvance(str(s)[:500]) for s in unique_strings)
                                    data_width = max_text_width + 30
                        
                        target_width = max(header_width, data_width)
                        width = min(max(target_width, 60), 250)
                        
                    self.results_view.setColumnWidth(i, width)
                    editor.column_widths[i] = width

            expected_profile_cols = {'column_name', 'column_type', 'min', 'max', 'approx_unique', 'null_percentage'}
            
            if expected_profile_cols.issubset(set(df.columns)):
                self.profile_page.load_data(df)
                self.toggle_view_button.setVisible(True)
                
                if self.toggle_view_button.isChecked():
                    self.results_stack.setCurrentWidget(self.results_view)
                else:
                    self.results_stack.setCurrentWidget(self.profile_page)
            else:
                self.toggle_view_button.setVisible(False)
                self.toggle_view_button.setChecked(False)
                self.toggle_view_button.setText(" Grid View")
                self.toggle_view_button.setIcon(qta.icon('fa5s.list', color=self._toolbar_icon_color()))
                self.results_stack.setCurrentWidget(self.results_view)
                
            self.results_tabs.setCurrentIndex(0)

        else:
            self.toggle_view_button.setVisible(False)
            self.results_stack.setCurrentWidget(self.results_view)
            self.results_view.horizontalHeader().setVisible(False)
            self.results_view.setModel(PolarsModel(pl.DataFrame()))

        if getattr(editor, 'info_message', None):
            has_results = True
            self.results_tabs.setCurrentIndex(1)
            self.messages_view.setPlainText(editor.info_message)
            
        elif getattr(editor, 'error_message', None):
            has_results = True
            self.results_tabs.setCurrentIndex(1)
            self.messages_view.setPlainText(editor.error_message)
        else:
            self.messages_view.clear()

        base_stats = getattr(editor, 'stats_text', None)
        
        if not base_stats:
            main_win = self.window()
            if hasattr(main_win, 'conn_manager'):
                engine = main_win.conn_manager.get_db(getattr(editor, 'connection_key', None))
                display_name = engine.get_display_name() if engine else "Ready"
                base_stats = f"{display_name} | 0.0000s | 0 rows" if engine else "Ready"
            else:
                base_stats = "Ready"

        peak_mem = getattr(editor, 'peak_memory', 0)
        self.update_live_stats(editor, base_stats, peak_mem)
        
        self.status_message_label.setText(getattr(editor, 'status_message', 'Ready'))
        self.setVisible(has_results or is_running)

    def on_query_started(self) -> None:
        """Show panel and update status for query execution."""
        self.setVisible(True)
        self.status_message_label.setText("Executing query...")
