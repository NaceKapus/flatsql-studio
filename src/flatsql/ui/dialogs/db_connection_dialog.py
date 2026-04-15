"""Dialog for selecting which type of database connection to add."""
from __future__ import annotations

import os

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from flatsql.config import ASSETS_DIR


class AddDatabaseConnectionDialog(QDialog):
    """A dialog to select the type of database connection to add."""

    @staticmethod
    def _load_connection_icon(asset_name: str, fallback_icon: QIcon) -> QIcon:
        """Load a custom SVG icon from assets when available.

        Args:
            asset_name: SVG file name expected under the assets image directory.
            fallback_icon: Icon used when no custom asset exists.

        Returns:
            A custom icon when present, otherwise the provided fallback.
        """
        icon_path = os.path.join(ASSETS_DIR, "img", asset_name)
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return fallback_icon

    def __init__(self, parent: QDialog | None = None) -> None:
        """Initialize the database connection type chooser dialog."""
        super().__init__(parent)
        self.setWindowTitle("Add Connection")
        self.resize(760, 460)
        self.setMinimumSize(640, 420)
        self.selected_connection_type: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h3>Select Connection Type</h3>"))

        self.connection_list = QListWidget()
        self.connection_list.setObjectName("connectionTypeList")
        self.connection_list.setIconSize(QSize(56, 56))
        self.connection_list.setViewMode(QListWidget.IconMode)
        self.connection_list.setFlow(QListView.LeftToRight)
        self.connection_list.setWrapping(True)
        self.connection_list.setResizeMode(QListView.Adjust)
        self.connection_list.setWordWrap(True)
        self.connection_list.setUniformItemSizes(False)
        self.connection_list.setGridSize(QSize(240, 148))
        self.connection_list.setTextElideMode(Qt.ElideNone)
        self.connection_list.setMovement(QListWidget.Static)
        self.connection_list.setSpacing(12)

        existing_item = QListWidgetItem(
            self._load_connection_icon("duckdb.svg", qta.icon("fa5s.database")),
            "Existing DuckDB database",
        )
        existing_item.setData(Qt.UserRole, "duckdb_existing")
        self.connection_list.addItem(existing_item)

        new_item = QListWidgetItem(
            self._load_connection_icon("duckdb.svg", qta.icon("mdi.database-plus")),
            "New DuckDB database",
        )
        new_item.setData(Qt.UserRole, "duckdb_new")
        self.connection_list.addItem(new_item)

        databricks_item = QListWidgetItem(
            self._load_connection_icon("databricks.svg", qta.icon("mdi.cloud-braces")),
            "Databricks Unity Catalog",
        )
        databricks_item.setData(Qt.UserRole, "databricks")
        self.connection_list.addItem(databricks_item)

        self.connection_list.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.connection_list)
        self.connection_list.setCurrentRow(0)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept_selection(self) -> None:
        """Accept the dialog using the currently selected connection type."""
        if selected_items := self.connection_list.selectedItems():
            self.selected_connection_type = selected_items[0].data(Qt.UserRole)
            self.accept()