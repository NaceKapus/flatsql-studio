"""Snippet tree panel used in the main application window."""

from __future__ import annotations

import os
import shutil
from typing import Any

import qtawesome as qta
from PySide6.QtCore import QMimeData, QModelIndex, QSize, Signal, Qt
from PySide6.QtGui import QDrag, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeView,
    QVBoxLayout,
)

from flatsql.config import SNIPPETS_DIR
from flatsql.core.logger import get_logger

logger = get_logger(__name__)

SNIPPET_PATH_ROLE = Qt.UserRole
SNIPPET_ITEM_TYPE_ROLE = Qt.UserRole + 1
SNIPPET_PATH_MIME_TYPE = "application/x-flatsql-snippet-path"


class SnippetFolderDialog(QDialog):
    """Tree-based folder picker for moving snippets."""

    def __init__(
        self,
        snippets_dir: str,
        theme_colors: dict[str, Any],
        current_dir: str,
        parent: Any = None,
    ) -> None:
        """Initialize the folder selection dialog."""
        super().__init__(parent)
        self.snippets_dir = snippets_dir
        self.theme_colors = theme_colors
        self._selected_directory = snippets_dir

        self.setWindowTitle("Move Snippet")
        self.resize(420, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select destination folder:"))

        self.model = QStandardItemModel(self)
        self.tree = QTreeView(self)
        self.tree.setHeaderHidden(True)
        self.tree.setModel(self.model)
        self.tree.doubleClicked.connect(self.accept)
        layout.addWidget(self.tree)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._build_tree()
        self._select_directory(current_dir)
        self.tree.expandAll()

    def _build_tree(self) -> None:
        """Populate the tree with the snippets folder hierarchy."""
        icon_color = self.theme_colors.get('icon', '#6C757D')
        folder_icon = qta.icon('fa5s.folder', color='goldenrod')
        root_icon = qta.icon('fa5s.folder-open', color=icon_color)

        root_item = QStandardItem(root_icon, '/ (Root)')
        root_item.setEditable(False)
        root_item.setData(self.snippets_dir, SNIPPET_PATH_ROLE)
        root_item.setData('folder', SNIPPET_ITEM_TYPE_ROLE)
        self.model.appendRow(root_item)

        self._append_folder_items(self.snippets_dir, root_item, folder_icon)

    def _append_folder_items(
        self,
        current_dir: str,
        parent_item: QStandardItem,
        folder_icon: Any,
    ) -> None:
        """Recursively append child folder items."""
        for item_name in sorted(os.listdir(current_dir)):
            full_path = os.path.join(current_dir, item_name)
            if not os.path.isdir(full_path):
                continue

            item = QStandardItem(folder_icon, item_name)
            item.setEditable(False)
            item.setData(full_path, SNIPPET_PATH_ROLE)
            item.setData('folder', SNIPPET_ITEM_TYPE_ROLE)
            parent_item.appendRow(item)
            self._append_folder_items(full_path, item, folder_icon)

    def _find_item_by_path(self, item: QStandardItem, target_path: str) -> QStandardItem | None:
        """Return the first item whose stored path matches the target."""
        if item.data(SNIPPET_PATH_ROLE) == target_path:
            return item

        for row in range(item.rowCount()):
            child = item.child(row)
            if child is None:
                continue
            match = self._find_item_by_path(child, target_path)
            if match is not None:
                return match

        return None

    def _select_directory(self, target_dir: str) -> None:
        """Select the initial target directory in the tree."""
        root_item = self.model.item(0, 0)
        if root_item is None:
            return

        item = self._find_item_by_path(root_item, target_dir) or root_item
        self.tree.setCurrentIndex(item.index())
        self._selected_directory = item.data(SNIPPET_PATH_ROLE)

    def selected_directory(self) -> str:
        """Return the currently selected destination directory."""
        index = self.tree.currentIndex()
        if not index.isValid():
            return self._selected_directory

        item = self.model.itemFromIndex(index)
        if item is None:
            return self._selected_directory

        return item.data(SNIPPET_PATH_ROLE)


class SnippetTreeView(QTreeView):
    """Tree view that supports dragging snippets onto folders."""

    snippet_drop_requested = Signal(str, str)

    def __init__(self, parent: Any = None) -> None:
        """Initialize snippet drag-and-drop behavior."""
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def startDrag(self, supported_actions: Qt.DropActions) -> None:
        """Start a drag operation for snippet items only."""
        del supported_actions
        index = self.currentIndex()
        if not index.isValid():
            return

        model = self.model()
        if not hasattr(model, 'itemFromIndex'):
            return

        item = model.itemFromIndex(index)
        if item is None or item.data(SNIPPET_ITEM_TYPE_ROLE) != 'snippet':
            return

        snippet_path = item.data(SNIPPET_PATH_ROLE)
        if not snippet_path:
            return

        mime_data = QMimeData()
        mime_data.setData(SNIPPET_PATH_MIME_TYPE, snippet_path.encode('utf-8'))

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.MoveAction)

    def _resolve_drop_directory(self, index: QModelIndex) -> str:
        """Resolve the filesystem directory represented by a drop target."""
        if not index.isValid():
            return SNIPPETS_DIR

        model = self.model()
        if not hasattr(model, 'itemFromIndex'):
            return SNIPPETS_DIR

        item = model.itemFromIndex(index)
        if item is None:
            return SNIPPETS_DIR

        item_path = item.data(SNIPPET_PATH_ROLE)
        item_type = item.data(SNIPPET_ITEM_TYPE_ROLE)

        if item_type == 'folder':
            return item_path
        if item_type == 'snippet':
            return os.path.dirname(item_path)
        return SNIPPETS_DIR

    def dragEnterEvent(self, event: Any) -> None:
        """Accept drag events for snippet move payloads."""
        if event.mimeData().hasFormat(SNIPPET_PATH_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:
        """Accept drag moves when the payload represents a snippet path."""
        if event.mimeData().hasFormat(SNIPPET_PATH_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: Any) -> None:
        """Emit a filesystem move request when a snippet is dropped."""
        if not event.mimeData().hasFormat(SNIPPET_PATH_MIME_TYPE):
            super().dropEvent(event)
            return

        source_path = bytes(event.mimeData().data(SNIPPET_PATH_MIME_TYPE)).decode('utf-8')
        target_index = self.indexAt(event.position().toPoint())
        target_dir = self._resolve_drop_directory(target_index)
        self.snippet_drop_requested.emit(source_path, target_dir)
        event.acceptProposedAction()


class SnippetPanel(QFrame):
    """Display, open, and manage saved SQL snippets."""

    snippet_opened = Signal(str, str, str)

    def __init__(self, theme_colors: dict[str, Any], parent: Any = None) -> None:
        """Initialize the snippet panel with theme-aware icon colors."""
        super().__init__(parent)
        self.theme_colors = theme_colors
        self.setObjectName("snippet_frame")
        self.setFrameShape(QFrame.StyledPanel)
        self.layout = QVBoxLayout(self)

        self._setup_ui()
        self.refresh()

    @staticmethod
    def _item_state_key(item: QStandardItem) -> tuple[str, str, str]:
        """Build a stable key for restoring expanded snippet tree state."""
        return (
            str(item.data(SNIPPET_PATH_ROLE) or ""),
            str(item.data(SNIPPET_ITEM_TYPE_ROLE) or ""),
            item.text() or "",
        )

    def _iter_items(self) -> list[QStandardItem]:
        """Return all snippet items currently present in the tree model."""
        items: list[QStandardItem] = []
        root = self.model.invisibleRootItem()
        stack = [root.child(row) for row in range(root.rowCount())]

        while stack:
            current = stack.pop()
            if current is None:
                continue
            items.append(current)
            for row in range(current.rowCount()):
                stack.append(current.child(row))

        return items

    def _capture_expanded_state(self) -> set[tuple[str, str, str]]:
        """Capture expanded snippet tree nodes as stable keys."""
        expanded: set[tuple[str, str, str]] = set()
        for item in self._iter_items():
            index: QModelIndex = self.model.indexFromItem(item)
            if index.isValid() and self.tree.isExpanded(index):
                expanded.add(self._item_state_key(item))
        return expanded

    def _restore_expanded_state(self, expanded_keys: set[tuple[str, str, str]]) -> None:
        """Restore expanded nodes after the snippet tree model is rebuilt."""
        if not expanded_keys:
            return

        for item in self._iter_items():
            if self._item_state_key(item) not in expanded_keys:
                continue
            index: QModelIndex = self.model.indexFromItem(item)
            if index.isValid():
                self.tree.setExpanded(index, True)

    def _setup_ui(self) -> None:
        """Build the snippet panel widgets and signal wiring."""
        header_layout = QHBoxLayout()
        header_label = QLabel("SQL Snippets")
        header_label.setObjectName("panelHeader")
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        icon_color = self.theme_colors.get('icon', '#6C757D')

        self.add_folder_btn = QPushButton(qta.icon('fa5s.folder-plus', color=icon_color), "")
        self.add_folder_btn.setFlat(True)
        self.add_folder_btn.setFixedSize(24, 24)
        self.add_folder_btn.setIconSize(QSize(16, 16))
        self.add_folder_btn.setToolTip("New Folder")
        self.add_folder_btn.clicked.connect(self._create_folder)
        
        self.refresh_btn = QPushButton(qta.icon('mdi.refresh', color=icon_color), "")
        self.refresh_btn.setFlat(True)
        self.refresh_btn.setFixedSize(24, 24)
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setToolTip("Refresh Snippets")
        self.refresh_btn.clicked.connect(self.refresh)

        header_layout.addWidget(self.add_folder_btn)
        header_layout.addWidget(self.refresh_btn)
        self.layout.addLayout(header_layout)

        self.model = QStandardItemModel()
        self.tree = SnippetTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QTreeView.NoEditTriggers)

        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.snippet_drop_requested.connect(self._move_snippet_path)
        self.layout.addWidget(self.tree)

    def refresh(self) -> None:
        """Scans the SNIPPETS_DIR and builds the tree."""
        expanded_keys = self._capture_expanded_state()
        self.model.clear()
        self._populate_tree(SNIPPETS_DIR, self.model.invisibleRootItem())
        self._restore_expanded_state(expanded_keys)

    def update_theme(self, theme_colors: dict[str, Any]) -> None:
        """Refresh panel icons after a theme change."""
        self.theme_colors = theme_colors
        icon_color = self.theme_colors.get('icon', '#6C757D')
        self.add_folder_btn.setIcon(qta.icon('fa5s.folder-plus', color=icon_color))
        self.refresh_btn.setIcon(qta.icon('mdi.refresh', color=icon_color))
        self.refresh()

    def _populate_tree(self, current_dir: str, parent_item: QStandardItem) -> None:
        """Recursively populates the tree with folders and .sql files."""
        icon_color = self.theme_colors.get('icon', '#6C757D')
        folder_icon = qta.icon('fa5s.folder', color='goldenrod')
        file_icon = qta.icon('fa5s.file-code', color=icon_color)

        try:
            for item_name in sorted(os.listdir(current_dir)):
                full_path = os.path.join(current_dir, item_name)
                
                if os.path.isdir(full_path):
                    item = QStandardItem(folder_icon, item_name)
                    item.setEditable(False)
                    item.setData(full_path, SNIPPET_PATH_ROLE)
                    item.setData("folder", SNIPPET_ITEM_TYPE_ROLE)
                    parent_item.appendRow(item)
                    self._populate_tree(full_path, item)
                elif item_name.endswith('.sql'):
                    display_name = item_name[:-4]
                    item = QStandardItem(file_icon, display_name)
                    item.setEditable(False)
                    item.setData(full_path, SNIPPET_PATH_ROLE)
                    item.setData("snippet", SNIPPET_ITEM_TYPE_ROLE)
                    parent_item.appendRow(item)
        except Exception:
            logger.exception("Failed to load snippets from %s.", current_dir)

    def _on_double_click(self, index: Any) -> None:
        """Open a snippet when the user activates a snippet tree item."""
        item = self.model.itemFromIndex(index)
        if item.data(SNIPPET_ITEM_TYPE_ROLE) == "snippet":
            file_path = item.data(SNIPPET_PATH_ROLE)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.snippet_opened.emit(item.text(), content, file_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not load snippet:\n{e}")

    def get_selected_directory(self) -> str:
        """Return the currently selected folder, or the parent folder of a snippet."""
        index = self.tree.currentIndex()
        if not index.isValid():
            return SNIPPETS_DIR

        item = self.model.itemFromIndex(index)
        if item is None:
            return SNIPPETS_DIR

        item_type = item.data(SNIPPET_ITEM_TYPE_ROLE)
        item_path = item.data(SNIPPET_PATH_ROLE)

        if item_type == 'folder':
            return item_path
        if item_type == 'snippet':
            return os.path.dirname(item_path)
        return SNIPPETS_DIR

    def _sanitize_entry_name(self, name: str) -> str:
        """Return a filesystem-safe snippet or folder name."""
        return "".join(
            character for character in name if character.isalnum() or character in (" ", "_", "-")
        ).strip()

    def _create_folder(self, parent_dir: str | None = None) -> None:
        """Prompt for and create a new snippet folder."""
        folder_name, ok = QInputDialog.getText(self, "New Folder", "Folder Name:")
        if not ok or not folder_name:
            return

        safe_name = self._sanitize_entry_name(folder_name)
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid folder name.")
            return

        target_dir = parent_dir or SNIPPETS_DIR
        folder_path = os.path.join(target_dir, safe_name)

        if os.path.exists(folder_path):
            QMessageBox.warning(self, "Folder Exists", f"The folder '{safe_name}' already exists.")
            return

        try:
            os.makedirs(folder_path, exist_ok=False)
            self.refresh()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not create folder:\n{e}")

    def _create_snippet(self, target_dir: str | None = None) -> None:
        """Prompt for and create a new snippet file."""
        snippet_name, ok = QInputDialog.getText(self, "New Snippet", "Snippet Name:")
        if not ok or not snippet_name:
            return

        safe_name = self._sanitize_entry_name(snippet_name)
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid snippet name.")
            return

        destination_dir = target_dir or SNIPPETS_DIR
        snippet_path = os.path.join(destination_dir, f"{safe_name}.sql")

        if os.path.exists(snippet_path):
            QMessageBox.warning(self, "Snippet Exists", f"The snippet '{safe_name}' already exists.")
            return

        try:
            with open(snippet_path, 'w', encoding='utf-8') as snippet_file:
                snippet_file.write("-- New SQL snippet\n")
            self.refresh()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not create snippet:\n{e}")

    def _show_root_context_menu(self, point: Any) -> None:
        """Show root-level actions when the user right-clicks empty space."""
        menu = QMenu()
        new_snippet_action = menu.addAction("New Snippet")
        new_folder_action = menu.addAction("New Folder")

        action = menu.exec(self.tree.viewport().mapToGlobal(point))

        if action == new_snippet_action:
            self._create_snippet()
        elif action == new_folder_action:
            self._create_folder()

    def _show_context_menu(self, point: Any) -> None:
        """Show snippet or folder actions for the clicked tree item."""
        index = self.tree.indexAt(point)
        if not index.isValid():
            self._show_root_context_menu(point)
            return
            
        item = self.model.itemFromIndex(index)
        item_type = item.data(SNIPPET_ITEM_TYPE_ROLE)
        
        menu = QMenu()
        
        if item_type == "snippet":
            open_action = menu.addAction("Open Snippet")
            rename_action = menu.addAction("Rename Snippet")
            menu.addSeparator()
            move_action = menu.addAction("Move to Folder")
            delete_action = menu.addAction("Delete Snippet")
            
            action = menu.exec(self.tree.viewport().mapToGlobal(point))
            
            if action == open_action:
                self._on_double_click(index)
            elif action == rename_action:
                self._rename_item(item, is_folder=False)
            elif action == move_action:
                self._move_snippet(item)
            elif action == delete_action:
                self._delete_item(item, is_folder=False)
                
        elif item_type == "folder":
            folder_path = item.data(SNIPPET_PATH_ROLE)
            new_snippet_action = menu.addAction("New Snippet")
            new_folder_action = menu.addAction("New Subfolder")
            rename_action = menu.addAction("Rename Folder")
            menu.addSeparator()
            delete_action = menu.addAction("Delete Folder")
            
            action = menu.exec(self.tree.viewport().mapToGlobal(point))
            
            if action == new_snippet_action:
                self._create_snippet(folder_path)
            elif action == new_folder_action:
                self._create_folder(folder_path)
            elif action == rename_action:
                self._rename_item(item, is_folder=True)
            elif action == delete_action:
                self._delete_item(item, is_folder=True)

    def _delete_item(self, item: QStandardItem, is_folder: bool) -> None:
        """Delete a snippet file or snippet folder after confirmation."""
        path = item.data(SNIPPET_PATH_ROLE)
        name = item.text()
        
        msg = f"Are you sure you want to delete the folder '{name}' and all its contents?" if is_folder else f"Are you sure you want to delete the snippet '{name}'?"
        
        reply = QMessageBox.question(self, "Confirm Delete", msg, QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                if is_folder:
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not delete:\n{e}")

    def _rename_item(self, item: QStandardItem, is_folder: bool) -> None:
        """Rename a snippet or folder on disk and refresh the tree."""
        current_path = item.data(SNIPPET_PATH_ROLE)
        current_name = item.text()
        title = "Rename Folder" if is_folder else "Rename Snippet"
        label = "Folder Name:" if is_folder else "Snippet Name:"
        new_name, ok = QInputDialog.getText(self, title, label, text=current_name)
        if not ok or not new_name:
            return

        safe_name = self._sanitize_entry_name(new_name)
        if not safe_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a valid name.")
            return

        parent_dir = os.path.dirname(current_path)
        target_name = safe_name if is_folder else f"{safe_name}.sql"
        target_path = os.path.join(parent_dir, target_name)
        if current_path == target_path:
            return

        if os.path.exists(target_path):
            QMessageBox.warning(self, "Name Exists", f"'{safe_name}' already exists in this folder.")
            return

        try:
            os.rename(current_path, target_path)
            self._update_open_snippet_tabs(current_path, target_path, is_folder)
            self.refresh()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not rename item:\n{e}")

    def _move_snippet(self, item: QStandardItem) -> None:
        """Move a snippet file to a different folder inside the snippets tree."""
        src_path = item.data(SNIPPET_PATH_ROLE)
        current_dir = os.path.dirname(src_path)
        dialog = SnippetFolderDialog(SNIPPETS_DIR, self.theme_colors, current_dir, self)

        if dialog.exec() != QDialog.Accepted:
            return

        self._move_snippet_path(src_path, dialog.selected_directory())

    def _move_snippet_path(self, src_path: str, dest_dir: str) -> None:
        """Move a snippet file into the requested destination directory."""
        snippet_name = os.path.basename(src_path)
        dest_path = os.path.join(dest_dir, snippet_name)
        if src_path == dest_path:
            return

        if os.path.exists(dest_path):
            QMessageBox.warning(self, "Snippet Exists", f"'{os.path.splitext(snippet_name)[0]}' already exists there.")
            return

        try:
            shutil.move(src_path, dest_path)
            self._update_open_snippet_tabs(src_path, dest_path, is_folder=False)
            self.refresh()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not move snippet:\n{e}")

    def _update_open_snippet_tabs(self, old_path: str, new_path: str, is_folder: bool) -> None:
        """Update snippet-backed query tabs after a move or rename."""
        main_window = self.window()
        query_tabs = getattr(main_window, 'query_tabs', None)
        if query_tabs is None:
            return

        for index in range(query_tabs.count()):
            editor = query_tabs.widget(index)
            editor_path = getattr(editor, 'snippet_file_path', None)
            if not editor_path:
                continue

            updated_path: str | None = None
            if is_folder:
                if editor_path == old_path or editor_path.startswith(old_path + os.sep):
                    relative_path = os.path.relpath(editor_path, old_path)
                    updated_path = os.path.join(new_path, relative_path)
            elif editor_path == old_path:
                updated_path = new_path

            if not updated_path:
                continue

            editor.snippet_file_path = updated_path
            if not is_folder:
                new_name = os.path.splitext(os.path.basename(updated_path))[0]
                editor.full_tab_name = new_name
                query_tabs.setTabText(index, new_name)
                query_tabs.setTabToolTip(index, new_name)