"""File explorer panel for browsing local and cloud file systems.

Provides hierarchical navigation of local, Azure, and Databricks file systems
with context menus for file operations, favorites pinning, and schema inspection.
"""
from __future__ import annotations

import os
from typing import Any

import qtawesome as qta
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMenu, QApplication, QMessageBox, QFileIconProvider, QTreeView, QLineEdit,
)
from PySide6.QtGui import QStandardItem, QIcon, QDesktopServices
from PySide6.QtCore import Signal, Qt, QFileInfo, QUrl, QModelIndex

from flatsql.ui.models import FileExplorerModel
from flatsql.ui.widgets import ExplorerTreeView
from flatsql.core.connector import LocalFileSystemConnector, AzureConnector
from flatsql.core.sql_generator import SQLGenerator


class FileExplorerPanel(QFrame):
    """Panel for exploring local and cloud file systems with context actions."""

    add_connection_requested = Signal()
    disconnect_requested = Signal(str)

    action_script_select = Signal(str, str, bool)
    action_script_flattened = Signal(str, str)
    action_show_schema = Signal(str, str)
    action_show_stats = Signal(str, str)
    action_split_file = Signal(str, str)
    action_convert_file = Signal(str, str)
    action_create_table = Signal(str, str)
    action_create_view = Signal(str, str)
    
    action_merge_folder = Signal(str, str)
    action_select_folder = Signal(str, str, str)

    def __init__(self, theme_colors: dict[str, str], settings_manager: Any, 
                 file_system_connections: dict[str, Any], get_active_engine_func: Any, 
                 parent: QFrame | None = None) -> None:
        """Initialize the file explorer with theme and connection settings.
        
        Args:
            theme_colors: Dictionary of theme color values.
            settings_manager: User settings manager.
            file_system_connections: Dict of connector name to connector instances.
            get_active_engine_func: Callable to get the active DuckDB engine.
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.theme_colors = theme_colors
        self.settings_manager = settings_manager
        self.file_system_connections = file_system_connections
        self.get_active_engine_func = get_active_engine_func
        self.icon_provider = QFileIconProvider()

        self.setObjectName("file_explorer_frame")
        self.setFrameShape(QFrame.StyledPanel)
        self.layout = QVBoxLayout(self)

        self._setup_ui()

    def _preview_row_limit(self) -> int:
        """Read the current preview-row-limit setting; ``0`` means no cap."""
        try:
            return int(self.settings_manager.get('preview_row_limit', 1000))
        except (TypeError, ValueError):
            return 1000

    def _setup_ui(self) -> None:
        """Set up the UI with header and tree view."""
        header_layout = QHBoxLayout()
        header_label = QLabel("File Explorer")
        header_label.setObjectName("panelHeader")
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        
        self.add_button = QPushButton(qta.icon('mdi.plus'), "")
        self.add_button.setFlat(True)
        self.add_button.setFixedSize(20, 20)
        self.add_button.clicked.connect(self.add_connection_requested.emit)
        header_layout.addWidget(self.add_button)
        self.layout.addLayout(header_layout)

        self.file_model = FileExplorerModel()
        self.file_tree = ExplorerTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.file_tree.expanded.connect(self._on_item_expanded)
        self.file_tree.setDragEnabled(True)
        self.file_tree.setDragDropMode(QTreeView.DragOnly)
        self.file_tree.doubleClicked.connect(self._on_double_click)
        self.layout.addWidget(self.file_tree)

    @staticmethod
    def _item_state_key(item: QStandardItem) -> tuple[str, str, str, str]:
        """Build a stable key used to restore tree expansion after refresh.

        Args:
            item: Tree model item.

        Returns:
            Tuple key containing connector key, file path, item type, and label.
        """
        connector_key = str(item.data(Qt.UserRole + 1) or "")
        full_path = str(item.data(Qt.UserRole + 3) or "")
        item_type = str(item.data(Qt.UserRole + 2) or "")
        label = item.text() or ""
        return (connector_key, full_path, item_type, label)

    def _iter_items(self) -> list[QStandardItem]:
        """Return all items currently present in the tree model."""
        items: list[QStandardItem] = []
        root = self.file_model.invisibleRootItem()
        stack = [root.child(row) for row in range(root.rowCount())]

        while stack:
            current = stack.pop()
            if current is None:
                continue
            items.append(current)
            for row in range(current.rowCount()):
                stack.append(current.child(row))

        return items

    def _capture_expanded_state(self) -> set[tuple[str, str, str, str]]:
        """Capture expanded tree nodes as stable keys."""
        expanded: set[tuple[str, str, str, str]] = set()
        for item in self._iter_items():
            index: QModelIndex = self.file_model.indexFromItem(item)
            if index.isValid() and self.file_tree.isExpanded(index):
                expanded.add(self._item_state_key(item))
        return expanded

    def _restore_expanded_state(self, expanded_keys: set[tuple[str, str, str, str]]) -> None:
        """Restore expanded tree nodes from stable keys.

        Uses multiple passes so parent expansions can lazily load children,
        allowing deeper expanded paths to be restored as they appear.
        """
        if not expanded_keys:
            return

        for _ in range(10):
            expanded_in_pass = False
            for item in self._iter_items():
                item_key = self._item_state_key(item)
                if item_key not in expanded_keys:
                    continue
                index: QModelIndex = self.file_model.indexFromItem(item)
                if not index.isValid() or self.file_tree.isExpanded(index):
                    continue
                self.file_tree.setExpanded(index, True)
                expanded_in_pass = True
                # Expanding can repopulate nodes and invalidate existing QStandardItem refs.
                # Restart scanning from a fresh snapshot on the next pass.
                break
            if not expanded_in_pass:
                break

    def refresh(self, preserve_expansion: bool = True) -> None:
        """Rebuild the root items (Favorites and Connections).

        Args:
            preserve_expansion: Whether to restore previously expanded nodes.
        """
        expanded_keys = self._capture_expanded_state() if preserve_expansion else set()
        self.file_model.clear()
        icon_color = self.theme_colors.get('icon', '#6C757D')

        fav_icon = qta.icon('fa5s.star', color='goldenrod')
        favorites_root_item = QStandardItem(fav_icon, "Favorites")
        favorites_root_item.setEditable(False)
        favorites_root_item.setData("favorites_root", Qt.UserRole + 2)
        
        pin_folder_icon = qta.icon('mdi.pin', color=icon_color)
        pin_file_icon = qta.icon('mdi.pin-outline', color=icon_color)

        pinned_list = self.settings_manager.get('pinned_files', [])
        for pin_data in pinned_list:
            display_name = pin_data.get("name", "Pinned Item")
            is_dir = pin_data.get("is_dir", True) 
            
            icon = pin_folder_icon if is_dir else pin_file_icon
            item = QStandardItem(icon, display_name)
            item.setEditable(False)
            item.setData(pin_data["connector_key"], Qt.UserRole + 1)
            item.setData(pin_data["path"], Qt.UserRole + 3)

            converted_path = self._convert_to_abfs_path(pin_data["path"])
            item.setData(converted_path, Qt.UserRole + 4)
            
            if is_dir:
                item.setData("directory", Qt.UserRole + 2)
                item.appendRow(QStandardItem())
            else:
                item.setData("file", Qt.UserRole + 2)
            favorites_root_item.appendRow(item)

        self.file_model.appendRow(favorites_root_item)

        for name, connector in self.file_system_connections.items():
            icon_info = connector.get_icon_info("", True) if hasattr(connector, 'get_icon_info') else None
            icon = None
            if icon_info:
                if isinstance(icon_info, QIcon):
                    icon = icon_info
                else:
                    icon = qta.icon(icon_info[0], color=icon_info[1])

            if not icon:
                if isinstance(connector, LocalFileSystemConnector):
                    icon = self.icon_provider.icon(QFileIconProvider.Computer)
                else:
                    icon = qta.icon('mdi.folder-network', color=icon_color)

            root_item = QStandardItem(icon, connector.get_display_name())
            root_item.setEditable(False)
            root_item.setData(name, Qt.UserRole + 1)
            root_item.setData("connection", Qt.UserRole + 2)
            root_item.appendRow(QStandardItem())
            self.file_model.appendRow(root_item)

        if preserve_expansion:
            self._restore_expanded_state(expanded_keys)

    def update_theme(self, theme_colors: dict[str, str]) -> None:
        """Update colors and icons based on new theme.
        
        Args:
            theme_colors: New theme color dictionary.
        """
        self.theme_colors = theme_colors
        icon_color = self.theme_colors.get('icon', '#6C757D')
        self.add_button.setIcon(qta.icon('mdi.plus', color=icon_color))
        self.refresh()

    def refresh_node(self, index: Any) -> None:
        """Reload children of a specific node.
        
        Args:
            index: The model index of the node to refresh.
        """
        item = self.file_model.itemFromIndex(index)
        if not item:
            return
        is_expanded = self.file_tree.isExpanded(index)
        if item.rowCount() > 0:
            item.removeRows(0, item.rowCount())
        item.appendRow(QStandardItem())
        self._on_item_expanded(index)
        if is_expanded:
            self.file_tree.setExpanded(index, True)

    def _on_item_expanded(self, index: Any, show_warning: bool = True) -> None:
        """Populate tree items when node is expanded.
        
        Args:
            index: The model index of expanded node.
            show_warning: Whether to show warning dialogs for missing prerequisites.
        """
        item = self.file_model.itemFromIndex(index)
        if not item or (item.rowCount() > 0 and item.child(0).text()):
            return
        
        self.file_tree.set_loading_state(index, True)
        QApplication.processEvents()

        try:
            conn_name = None
            temp_item = item
            while temp_item:
                conn_name = temp_item.data(Qt.UserRole + 1)
                if conn_name:
                    break
                temp_item = temp_item.parent()

            if not conn_name:
                return
            connector = self.file_system_connections.get(conn_name)
            if not connector:
                return

            path_to_list = item.data(Qt.UserRole + 3) or ""
            if item.rowCount() > 0 and not item.child(0).text():
                item.removeRows(0, item.rowCount())

            engine = self.get_active_engine_func()
            if not engine:
                if show_warning:
                    QMessageBox.warning(self, "No Connection", "A database connection is required to browse files.")
                return

            files = connector.list_files(engine, path_to_list)

            for display_name, file_type, full_path in sorted(files, key=lambda x: (0 if x[1] == 'directory' else 1, x[0].lower())):
                icon = None
                icon_info = connector.get_icon_info(full_path, file_type == 'directory') if hasattr(connector, 'get_icon_info') else None
                
                if icon_info:
                    if isinstance(icon_info, QIcon):
                        icon = icon_info
                    else:
                        try:
                            icon = qta.icon(icon_info[0], color=icon_info[1])
                        except Exception:
                            pass

                if not icon:
                    if isinstance(connector, LocalFileSystemConnector):
                        icon = self.icon_provider.icon(QFileInfo(full_path))
                    else:
                        icon_color = self.theme_colors.get('icon', '#6C757D')
                        icon = qta.icon('fa5s.folder', color='goldenrod') if file_type == 'directory' else qta.icon('fa5s.file', color=icon_color)

                child_item = QStandardItem(icon, display_name)
                if file_type == 'directory':
                    child_item.appendRow(QStandardItem())
                child_item.setEditable(False)
                child_item.setData(conn_name, Qt.UserRole + 1)
                child_item.setData(file_type, Qt.UserRole + 2)
                child_item.setData(full_path, Qt.UserRole + 3)
                converted_path = self._convert_to_abfs_path(full_path)
                child_item.setData(converted_path, Qt.UserRole + 4)
                item.appendRow(child_item)
        finally:
            self.file_tree.set_loading_state(index, False)

    def _on_double_click(self, index: Any) -> None:
        """Generate SELECT query when file is double-clicked.
        
        Args:
            index: The model index of the double-clicked item.
        """
        if not index.isValid(): 
            return

        item = self.file_model.itemFromIndex(index)
        is_connection = item.data(Qt.UserRole + 2) == "connection"
        is_expandable = item.hasChildren() or is_connection
        
        if is_expandable:
            return

        raw_full_path = item.data(Qt.UserRole + 3)
        full_path = self._convert_to_abfs_path(raw_full_path)
        display_name = item.text()

        if not full_path:
            return

        conn_name = item.data(Qt.UserRole + 1)
        temp_item = item
        while not conn_name and temp_item.parent():
            temp_item = temp_item.parent()
            conn_name = temp_item.data(Qt.UserRole + 1)

        connector = self.file_system_connections.get(conn_name)
        if isinstance(connector, AzureConnector) and raw_full_path:
            parts = raw_full_path.strip('/').split('/')
            if len(parts) >= 2 and len(parts[0]) == 36:
                account_name = parts[1]
                engine = self.get_active_engine_func()
                if engine:
                    connector._setup_duckdb_secret(engine, account_name)

        self.action_script_select.emit(full_path, display_name, True)

    def _convert_to_abfs_path(self, path: str) -> str:
        """Convert Azure internal tree paths to DuckDB abfss:// paths.
        
        Args:
            path: The internal path to convert.
            
        Returns:
            Converted abfss:// or az:// path, or original path if not Azure.
        """
        if not path:
            return path
        parts = path.strip('/').split('/')
        if len(parts) >= 3 and len(parts[0]) == 36:
            account = parts[1]
            container = parts[2]
            blob_path = "/".join(parts[3:])
            protocol, endpoint = "az", "blob.core.windows.net"

            for conn in self.file_system_connections.values():
                if isinstance(conn, AzureConnector) and hasattr(conn, 'get_storage_protocol'):
                    if account in conn.account_hns_cache:
                        protocol, endpoint = conn.get_storage_protocol(account)
                        break
            
            if protocol == 'abfss':
                azure_path = f"abfss://{account}.{endpoint}/{container}/{blob_path}"
            else:
                azure_path = f"az://{account}.{endpoint}/{container}/{blob_path}"
            return azure_path.rstrip('/')
        return path

    def _toggle_pin(self, item: QStandardItem) -> None:
        """Toggle favorite status for a file or folder.
        
        Args:
            item: The item to toggle pinning for.
        """
        if not item:
            return
        display_name = item.text()
        full_path = item.data(Qt.UserRole + 3)
        is_dir = item.hasChildren() or item.data(Qt.UserRole + 2) == "connection"
        
        connector_key = item.data(Qt.UserRole + 1)
        if not connector_key:
            parent = item
            while parent.parent():
                parent = parent.parent()
            connector_key = parent.data(Qt.UserRole + 1)

        if not full_path or not connector_key:
            return
            
        pin_data = {"name": display_name, "connector_key": connector_key, "path": full_path, "is_dir": is_dir}
        pinned_list = self.settings_manager.get('pinned_files', [])
        found_pin = next((p for p in pinned_list if p['path'] == full_path and p['connector_key'] == connector_key), None)

        if found_pin:
            pinned_list.remove(found_pin)
        else:
            pinned_list.append(pin_data)

        self.settings_manager.set('pinned_files', pinned_list)
        self.settings_manager.save()
        self.refresh()

    def _show_context_menu(self, point: Any) -> None:
        """Display context menu with file/folder operations.
        
        Args:
            point: The position where context menu was requested.
        """
        index = self.file_tree.indexAt(point)
        if not index.isValid():
            return

        item = self.file_model.itemFromIndex(index)
        is_connection = item.data(Qt.UserRole + 2) == "connection"
        is_favorites_root = item.data(Qt.UserRole + 2) == "favorites_root"
        
        raw_full_path = item.data(Qt.UserRole + 3)
        full_path = self._convert_to_abfs_path(raw_full_path)
        display_name = item.text()
        is_expandable = item.hasChildren() or is_connection

        is_inside_favorites = False
        temp = item
        while temp:
            if temp.data(Qt.UserRole + 2) == "favorites_root":
                is_inside_favorites = True
                break
            temp = temp.parent()

        conn_name = item.data(Qt.UserRole + 1)
        temp_item = item
        while not conn_name and temp_item.parent():
            temp_item = temp_item.parent()
            conn_name = temp_item.data(Qt.UserRole + 1)

        is_queryable_folder = True
        if conn_name:
            connector = self.file_system_connections.get(conn_name)
            if isinstance(connector, AzureConnector) and raw_full_path:
                if len(raw_full_path.split('/')) < 4:
                    is_queryable_folder = False

        is_pinnable = full_path is not None and not is_favorites_root and not is_inside_favorites
        menu = QMenu()

        refresh_action = menu.addAction("Refresh") if (is_expandable and not is_favorites_root) else None
        if refresh_action:
            menu.addSeparator()

        disconnect_action = None
        if is_connection and item.data(Qt.UserRole + 1) != "Local Files":
            disconnect_action = menu.addAction("Disconnect")
            menu.addSeparator()

        actions: dict[Any, Any] = {}

        if not is_connection and not is_favorites_root:
            if not is_expandable:
                preview_label = SQLGenerator.select_top_menu_label(self._preview_row_limit())
                if full_path and full_path.lower().endswith((".json", ".jsonl", ".ndjson")):
                    select_menu = menu.addMenu(preview_label)
                    actions[select_menu.addAction("Standard")] = lambda: self.action_script_select.emit(full_path, display_name, True)
                    actions[select_menu.addAction("Flattened")] = lambda: self.action_script_flattened.emit(full_path, display_name)
                else:
                    actions[menu.addAction(preview_label)] = lambda: self.action_script_select.emit(full_path, display_name, True)
                    
                actions[menu.addAction("Show Schema")] = lambda: self.action_show_schema.emit(full_path, display_name)
                actions[menu.addAction("Show Stats")] = lambda: self.action_show_stats.emit(full_path, display_name)
                menu.addSeparator()

                actions[menu.addAction(qta.icon('fa5s.cut'), "Split / Partition File")] = lambda: self.action_split_file.emit(full_path, display_name)
                menu.addSeparator()

                convert_menu = menu.addMenu("Convert To")
                source_ext = os.path.splitext(full_path)[1].lower().replace('.', '') if full_path else ""
                has_conversion = False
                for format_key, format_info in SQLGenerator.CONVERSION_FORMATS.items():
                    if format_key != source_ext:
                        act = convert_menu.addAction(format_info['label'])
                        actions[act] = lambda fmt=format_key: self.action_convert_file.emit(full_path, fmt)
                        has_conversion = True
                if not has_conversion:
                    convert_menu.setEnabled(False)

                menu.addSeparator()
                script_as_menu = menu.addMenu("Script As")
                actions[script_as_menu.addAction("Create Table")] = lambda: self.action_create_table.emit(full_path, display_name)
                actions[script_as_menu.addAction("Create View")] = lambda: self.action_create_view.emit(full_path, display_name)

            else:
                if is_queryable_folder:
                    actions[menu.addAction("Merge Files in Folder")] = lambda: self.action_merge_folder.emit(full_path, display_name)
                    menu.addSeparator()
                    select_folder_menu = menu.addMenu(
                        SQLGenerator.select_top_menu_label(self._preview_row_limit(), " from Folder")
                    )
                    actions[select_folder_menu.addAction("CSV Files (*.csv)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.csv")
                    actions[select_folder_menu.addAction("TSV Files (*.tsv)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.tsv")
                    actions[select_folder_menu.addAction("TAB Files (*.tab)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.tab")
                    actions[select_folder_menu.addAction("PSV Files (*.psv)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.psv")
                    actions[select_folder_menu.addAction("JSON Files (*.json)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.json")
                    actions[select_folder_menu.addAction("JSON Lines (*.jsonl)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.jsonl")
                    actions[select_folder_menu.addAction("NDJSON Files (*.ndjson)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.ndjson")
                    actions[select_folder_menu.addAction("Parquet Files (*.parquet)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.parquet")
                    actions[select_folder_menu.addAction("Text Files (*.txt)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.txt")
                    actions[select_folder_menu.addAction("Excel Files (*.xlsx)")] = lambda: self.action_select_folder.emit(full_path, display_name, "*.xlsx")
        
        pin_action = None
        if is_pinnable:
            menu.addSeparator()
            c_key = item.data(Qt.UserRole + 1) or (item.parent().data(Qt.UserRole + 1) if item.parent() else None)
            pinned_list = self.settings_manager.get('pinned_files', [])
            found_pin = next((p for p in pinned_list if p['path'] == full_path and p['connector_key'] == c_key), None)
            
            icon = qta.icon('mdi.pin-off') if found_pin else qta.icon('mdi.pin')
            text = "Unpin from Favorites" if found_pin else "Pin to Favorites"
            pin_action = menu.addAction(icon, text)

        if is_inside_favorites and item.parent().data(Qt.UserRole + 2) == "favorites_root":
             menu.addSeparator()
             pin_action = menu.addAction(qta.icon('mdi.pin-off'), "Unpin from Favorites")

        copy_path_action = menu.addAction("Copy as path") if full_path else None

        open_in_explorer_action = None
        if full_path and conn_name and isinstance(self.file_system_connections.get(conn_name), LocalFileSystemConnector):
            open_in_explorer_action = menu.addAction("Open in File Explorer")

        selected_action = menu.exec(self.file_tree.viewport().mapToGlobal(point))

        if not selected_action:
            return
        
        if selected_action == disconnect_action:
            self.disconnect_requested.emit(item.data(Qt.UserRole + 1))
        elif selected_action == refresh_action:
            self.refresh_node(index)
        elif selected_action == pin_action:
            self._toggle_pin(item)
        elif selected_action == copy_path_action:
            QApplication.clipboard().setText(full_path)
        elif selected_action == open_in_explorer_action:
            path_to_open = full_path if os.path.isdir(full_path) else os.path.dirname(full_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path_to_open))
        elif selected_action in actions:
            conn_name = item.data(Qt.UserRole + 1)
            temp_item = item
            while not conn_name and temp_item.parent():
                temp_item = temp_item.parent()
                conn_name = temp_item.data(Qt.UserRole + 1)

            connector = self.file_system_connections.get(conn_name)
            if isinstance(connector, AzureConnector) and raw_full_path:
                parts = raw_full_path.strip('/').split('/')
                if len(parts) >= 2 and len(parts[0]) == 36:
                    account_name = parts[1]
                    engine = self.get_active_engine_func()
                    if engine:
                        connector._setup_duckdb_secret(engine, account_name)
            
            actions[selected_action]()
