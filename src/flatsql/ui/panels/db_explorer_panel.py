"""Database explorer panel for browsing connected DuckDB objects."""
from __future__ import annotations

from typing import Any

import qtawesome as qta
from PySide6.QtCore import QPoint, Qt, Signal, QModelIndex, QTimer
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
)

from flatsql.ui.widgets import DownwardComboBox, ExplorerTreeView


class DBExplorerPanel(QFrame):
    """Panel that displays connected databases, tables, views, and columns."""

    # Signals for connection management
    add_connection_requested = Signal()
    disconnect_requested = Signal(str)
    active_connection_changed = Signal(int)

    # Signals for right-click actions on DB objects
    action_new_query = Signal(str)
    action_script_select = Signal(str, str)
    action_script_ddl = Signal(str, str, str, str)

    def __init__(
        self,
        theme_colors: dict[str, Any],
        settings_manager: object,
        theme_manager: object,
        connections: dict[str, Any],
        parent: QFrame | None = None,
    ) -> None:
        """Initialize the database explorer panel."""
        super().__init__(parent)
        self.theme_colors = theme_colors
        self.settings_manager = settings_manager
        self.theme_manager = theme_manager
        self.connections = connections
        self._active_filter_query = ""
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._apply_filter_from_input)

        self.setObjectName("db_explorer_frame")
        self.setFrameShape(QFrame.StyledPanel)
        self.layout = QVBoxLayout(self)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the explorer header and tree view."""
        # Header
        header_layout = QHBoxLayout()
        header_label = QLabel("Database Explorer")
        header_label.setObjectName("panelHeader")
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        self.add_button = QPushButton(qta.icon('mdi.plus'), "", toolTip="Add New Connection")
        self.add_button.setFlat(True)
        self.add_button.setFixedSize(20, 20)
        self.add_button.clicked.connect(self.add_connection_requested.emit)
        header_layout.addWidget(self.add_button)
        self.layout.addLayout(header_layout)

        # Connection selector is now hosted in the Query toolbar.
        self.connection_combo = DownwardComboBox()
        self.connection_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.connection_combo.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.connection_combo.currentIndexChanged.connect(self.active_connection_changed.emit)

        self.filter_input = QLineEdit(self)
        self.filter_input.setObjectName("dbExplorerFilterInput")
        self.filter_input.setPlaceholderText("Search")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._schedule_filter)
        self.layout.addWidget(self.filter_input)

        # Tree View
        self.db_model = QStandardItemModel()
        self.db_tree = ExplorerTreeView()
        self.db_tree.setModel(self.db_model)
        self.db_tree.setHeaderHidden(True)
        self.db_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.db_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.db_tree.expanded.connect(self._on_item_expanded)
        self.layout.addWidget(self.db_tree)

    def set_connection_combo(self, combo: QComboBox) -> None:
        """Bind the explorer to an externally hosted connection selector."""
        try:
            self.connection_combo.currentIndexChanged.disconnect(self.active_connection_changed.emit)
        except Exception:
            pass

        self.connection_combo = combo
        self.connection_combo.currentIndexChanged.connect(self.active_connection_changed.emit)

    def _schedule_filter(self, _: str) -> None:
        """Debounce filter updates to keep typing responsive on large trees."""
        self._filter_timer.start()

    def _apply_filter_from_input(self) -> None:
        """Apply the current search text to loaded database tree nodes."""
        query = self.filter_input.text().strip().lower()
        if query == self._active_filter_query:
            return
        self._active_filter_query = query
        self._apply_filter()

    def _item_matches_filter(self, item: QStandardItem, query: str) -> bool:
        """Return whether this item matches the active filter query."""
        if not query:
            return True

        label = (item.text() or "").lower()
        item_kind = str(item.data(Qt.UserRole + 1) or "").lower()
        connection_key = str(item.data(Qt.UserRole + 2) or "").lower()
        return query in label or query in item_kind or query in connection_key

    def _set_item_hidden(self, item: QStandardItem, hidden: bool) -> None:
        """Hide or show a model row in the database tree."""
        parent_item = item.parent()
        parent_index = self.db_model.indexFromItem(parent_item) if parent_item else QModelIndex()
        self.db_tree.setRowHidden(item.row(), parent_index, hidden)

    def _apply_filter_to_item(self, item: QStandardItem, query: str) -> bool:
        """Recursively evaluate visibility for an item and descendants."""
        descendant_match = False
        for row in range(item.rowCount()):
            child_item = item.child(row)
            if child_item and self._apply_filter_to_item(child_item, query):
                descendant_match = True

        self_match = self._item_matches_filter(item, query)
        is_visible = (not query) or self_match or descendant_match
        self._set_item_hidden(item, not is_visible)

        if query and descendant_match:
            index = self.db_model.indexFromItem(item)
            if index.isValid():
                self.db_tree.setExpanded(index, True)

        return is_visible

    def _apply_filter(self) -> None:
        """Filter currently loaded tree nodes without querying metadata again."""
        root = self.db_model.invisibleRootItem()
        self.db_tree.setUpdatesEnabled(False)
        try:
            for row in range(root.rowCount()):
                item = root.child(row)
                if item:
                    self._apply_filter_to_item(item, self._active_filter_query)
        finally:
            self.db_tree.setUpdatesEnabled(True)
            self.db_tree.viewport().update()

    def _item_state_key(self, item: QStandardItem) -> tuple[str, ...]:
        """Build a stable hierarchical key for expansion state restoration.

        Args:
            item: Tree model item.

        Returns:
            Tuple representing this item's path from root to current node.
        """
        parts: list[str] = []
        current: QStandardItem | None = item
        while current is not None:
            part = "|".join(
                [
                    current.text() or "",
                    str(current.data(Qt.UserRole + 1) or ""),
                    str(current.data(Qt.UserRole + 2) or ""),
                ]
            )
            parts.append(part)
            current = current.parent()
        parts.reverse()
        return tuple(parts)

    def _iter_items(self) -> list[QStandardItem]:
        """Return all items currently present in the tree model."""
        items: list[QStandardItem] = []
        root = self.db_model.invisibleRootItem()
        stack = [root.child(row) for row in range(root.rowCount())]

        while stack:
            current = stack.pop()
            if current is None:
                continue
            items.append(current)
            for row in range(current.rowCount()):
                stack.append(current.child(row))

        return items

    def _capture_expanded_state(self) -> set[tuple[str, ...]]:
        """Capture expanded nodes as stable hierarchical keys."""
        expanded: set[tuple[str, ...]] = set()
        for item in self._iter_items():
            index: QModelIndex = self.db_model.indexFromItem(item)
            if index.isValid() and self.db_tree.isExpanded(index):
                expanded.add(self._item_state_key(item))
        return expanded

    def _restore_expanded_state(self, expanded_keys: set[tuple[str, ...]]) -> None:
        """Restore expanded nodes from captured keys.

        Expanding an item may mutate model children (lazy column load), so the
        scan restarts after each expansion to avoid stale item references.
        """
        if not expanded_keys:
            return

        for _ in range(10):
            expanded_in_pass = False
            for item in self._iter_items():
                if self._item_state_key(item) not in expanded_keys:
                    continue
                index: QModelIndex = self.db_model.indexFromItem(item)
                if not index.isValid() or self.db_tree.isExpanded(index):
                    continue
                self.db_tree.setExpanded(index, True)
                expanded_in_pass = True
                break
            if not expanded_in_pass:
                break

    def refresh(self, preserve_expansion: bool = True) -> None:
        """Populate database explorer tree with active connections.

        Args:
            preserve_expansion: Whether to restore previously expanded nodes.
        """
        expanded_keys = self._capture_expanded_state() if preserve_expansion else set()
        selected_key = self.connection_combo.currentData()
        self.db_model.clear()
        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()

        icon_color = self.theme_colors.get("icon", "#6C757D")
        stylesheet_data = self.theme_manager.theme_data.get("stylesheet", {})
        checkbox_style = stylesheet_data.get("QCheckBox::indicator:checked", {})
        checkbox_color = checkbox_style.get("background-color", "#62a0ea")

        db_icon = qta.icon("mdi.server", color=checkbox_color)
        folder_icon = qta.icon("fa5s.folder", color="goldenrod")
        table_icon = qta.icon("fa5s.table", color=icon_color)
        view_icon = qta.icon("mdi.table-eye", color=icon_color)
        func_icon = qta.icon("mdi.function", color=icon_color)
        constraint_icon = qta.icon("fa5s.key", color=icon_color)

        for key, engine in self.connections.items():
            db_objects = engine.get_database_objects()
            display_name = engine.get_display_name()
            
            # Root DB Node
            db_root_item = QStandardItem(db_icon, display_name)
            db_root_item.setEditable(False)
            db_root_item.setData(key, Qt.UserRole + 2)
            self.db_model.appendRow(db_root_item)
            self.connection_combo.addItem(display_name, key)

            # Tables Node
            tables_node = QStandardItem(folder_icon, "Tables")
            tables_node.setEditable(False)
            db_root_item.appendRow(tables_node)
            for schema, table_name in sorted(db_objects.get("tables", [])):
                item = QStandardItem(table_icon, f"{schema}.{table_name}")
                item.setEditable(False)
                item.setData("db_object", Qt.UserRole + 1)
                item.setData(key, Qt.UserRole + 2)

                columns_node = QStandardItem(folder_icon, "Columns")
                columns_node.setEditable(False)
                columns_node.appendRow(QStandardItem())
                item.appendRow(columns_node)

                constraints_node = QStandardItem(folder_icon, "Constraints")
                constraints_node.setEditable(False)
                constraints_node.appendRow(QStandardItem())
                item.appendRow(constraints_node)

                tables_node.appendRow(item)

            # Views Node
            views_node = QStandardItem(folder_icon, "Views")
            views_node.setEditable(False)
            db_root_item.appendRow(views_node)
            for schema, view_name in sorted(db_objects.get("views", [])):
                item = QStandardItem(view_icon, f"{schema}.{view_name}")
                item.setEditable(False)
                item.setData("db_object", Qt.UserRole + 1)
                item.setData(key, Qt.UserRole + 2)

                columns_node = QStandardItem(folder_icon, "Columns")
                columns_node.setEditable(False)
                columns_node.appendRow(QStandardItem())
                item.appendRow(columns_node)
                views_node.appendRow(item)

            # System Views Node
            system_views_list = db_objects.get("system_views", [])
            if system_views_list:
                system_views_node = QStandardItem(folder_icon, "System Views")
                system_views_node.setEditable(False)
                views_node.appendRow(system_views_node)
                for schema, view_name in sorted(system_views_list):
                    item = QStandardItem(view_icon, f"{schema}.{view_name}")
                    item.setData("db_object", Qt.UserRole + 1)
                    item.setData(key, Qt.UserRole + 2)
                    
                    columns_node = QStandardItem(folder_icon, "Columns")
                    columns_node.setEditable(False)
                    columns_node.appendRow(QStandardItem())
                    item.appendRow(columns_node)
                    system_views_node.appendRow(item)

            # Functions / Macros Node (user-defined only, hidden when empty)
            functions_list = db_objects.get("functions", [])
            if functions_list:
                functions_node = QStandardItem(folder_icon, "Functions")
                functions_node.setEditable(False)
                db_root_item.appendRow(functions_node)
                for func_name, func_type in functions_list:
                    f_item = QStandardItem(func_icon, func_name)
                    f_item.setEditable(False)
                    functions_node.appendRow(f_item)

        preferred_key = selected_key if selected_key in self.connections else None
        if preferred_key is None:
            if ":memory:" in self.connections:
                preferred_key = ":memory:"
            elif self.connection_combo.count() > 0:
                preferred_key = self.connection_combo.itemData(0)

        if preferred_key is not None:
            combo_index = self.connection_combo.findData(preferred_key)
            if combo_index != -1:
                self.connection_combo.setCurrentIndex(combo_index)
        else:
            self.connection_combo.setCurrentIndex(-1)

        self.connection_combo.blockSignals(False)

        if preserve_expansion:
            self._restore_expanded_state(expanded_keys)

        self._apply_filter()

    def update_theme(
        self,
        theme_colors: dict[str, Any],
        theme_manager: object,
    ) -> None:
        """Refresh icon colors and rerender the explorer for a new theme."""
        self.theme_colors = theme_colors
        self.theme_manager = theme_manager
        icon_color = self.theme_colors.get("icon", "#6C757D")

        if hasattr(self, "add_button"):
            self.add_button.setIcon(qta.icon("mdi.plus", color=icon_color))

        self.refresh()

    def _on_item_expanded(self, index: Any) -> None:
        """Lazy-load Columns or Constraints when the respective folder node is expanded."""
        item = self.db_model.itemFromIndex(index)
        if not item:
            return
        cleaned_text = item.text().replace(" (expanding...)", "")
        if cleaned_text not in ("Columns", "Constraints"):
            return
        if not item.hasChildren() or item.child(0).text() != "":
            return

        self.db_tree.set_loading_state(index, True)
        QApplication.processEvents()

        try:
            parent_item = item.parent()
            if not parent_item:
                return

            connection_key = parent_item.data(Qt.UserRole + 2)
            engine = self.connections.get(connection_key)
            if not engine:
                return

            item.removeRows(0, item.rowCount())

            full_name = parent_item.text()
            if "." not in full_name:
                return
            schema_name, object_name = full_name.split(".", 1)

            icon_color = self.theme_colors.get("icon", "#6C757D")

            if cleaned_text == "Columns":
                columns = engine.get_columns_for_object(schema_name, object_name)
                column_icon = qta.icon("mdi.table-column", color=icon_color)
                for col_name, col_type in columns:
                    col_item = QStandardItem(column_icon, f"{col_name} ({col_type})")
                    col_item.setEditable(False)
                    item.appendRow(col_item)

            elif cleaned_text == "Constraints":
                constraints = engine.get_constraints_for_table(schema_name, object_name)
                if constraints:
                    constraint_icon = qta.icon("fa5s.key", color=icon_color)
                    for c_type, c_cols in constraints:
                        label = f"{c_type} {c_cols}".strip()
                        c_item = QStandardItem(constraint_icon, label)
                        c_item.setEditable(False)
                        item.appendRow(c_item)
                else:
                    none_item = QStandardItem("(none)")
                    none_item.setEditable(False)
                    item.appendRow(none_item)

        finally:
            self.db_tree.set_loading_state(index, False)
            if self._active_filter_query:
                self._apply_filter()

    def _show_context_menu(self, point: QPoint) -> None:
        """Open the context menu for connections and database objects."""
        index = self.db_tree.indexAt(point)
        if not index.isValid():
            return

        item = self.db_model.itemFromIndex(index)
        connection_key = item.data(Qt.UserRole + 2)
        is_db_object = item.data(Qt.UserRole + 1) == "db_object"

        menu = QMenu()

        if connection_key and not is_db_object:
            new_query_action = menu.addAction("New Query")
            refresh_action = menu.addAction("Refresh")
            menu.addSeparator()
            disconnect_action = menu.addAction("Disconnect")

            if len(self.connections) <= 1:
                disconnect_action.setEnabled(False)

            action = menu.exec(self.db_tree.viewport().mapToGlobal(point))

            if action == new_query_action:
                self.action_new_query.emit(connection_key)
            elif action == refresh_action:
                self.refresh()
            elif action == disconnect_action:
                self.disconnect_requested.emit(connection_key)
            return

        if is_db_object:
            object_name_full = item.text()
            parent_item = item.parent()
            object_type = None

            if parent_item:
                parent_text = parent_item.text()
                if parent_text == "Tables":
                    object_type = "TABLE"
                elif parent_text in ["Views", "System Views"]:
                    object_type = "VIEW"

            if not object_type:
                return

            select_action = menu.addAction("Select Top 1000 Rows")
            menu.addSeparator()
            script_as_menu = menu.addMenu("Script As")
            create_action = script_as_menu.addAction("CREATE")
            alter_action = script_as_menu.addAction("ALTER")
            drop_action = script_as_menu.addAction("DROP")
            drop_create_action = script_as_menu.addAction("DROP and CREATE")

            if object_type == "TABLE":
                alter_action.setEnabled(False)

            action = menu.exec(self.db_tree.viewport().mapToGlobal(point))

            if action == select_action:
                self.action_script_select.emit(object_name_full, connection_key)
            elif action in [create_action, alter_action, drop_action, drop_create_action]:
                script_type_map = {
                    create_action: "CREATE",
                    alter_action: "ALTER",
                    drop_action: "DROP",
                    drop_create_action: "DROP and CREATE",
                }
                script_type = script_type_map[action]
                self.action_script_ddl.emit(object_name_full, object_type, script_type, connection_key)

    def sync_connection_combo(self, connection_key: str | None) -> None:
        """Sync the dropdown with the active tab or default in-memory database."""
        self.connection_combo.blockSignals(True)

        preferred_key = connection_key
        if not preferred_key:
            if ":memory:" in self.connections:
                preferred_key = ":memory:"
            elif self.connection_combo.count() > 0:
                preferred_key = self.connection_combo.itemData(0)

        if preferred_key:
            combo_index = self.connection_combo.findData(preferred_key)
            if combo_index != -1:
                self.connection_combo.setCurrentIndex(combo_index)
            else:
                self.connection_combo.setCurrentIndex(-1)
        else:
            self.connection_combo.setCurrentIndex(-1)

        self.connection_combo.blockSignals(False)