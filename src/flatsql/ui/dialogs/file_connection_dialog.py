"""Dialog for selecting which type of file-system connection to add."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout

from flatsql.config import ASSETS_DIR


class AddFileConnectionDialog(QDialog):
    """A dialog to select the type of file-system connection to add."""

    def __init__(self, parent: QDialog | None = None) -> None:
        """Initialize the connection type chooser dialog."""
        super().__init__(parent)
        self.setWindowTitle("Add Connection")
        self.resize(760, 460)
        self.setMinimumSize(640, 420)
        self.selected_connector_type: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h3>Select Connection Type</h3>"))

        self.connector_list = QListWidget()
        self.connector_list.setObjectName("connectionTypeList")
        self.connector_list.setIconSize(QSize(56, 56))
        self.connector_list.setViewMode(QListWidget.IconMode)
        self.connector_list.setFlow(QListView.LeftToRight)
        self.connector_list.setWrapping(True)
        self.connector_list.setResizeMode(QListView.Adjust)
        self.connector_list.setWordWrap(True)
        self.connector_list.setUniformItemSizes(False)
        self.connector_list.setGridSize(QSize(240, 148))
        self.connector_list.setTextElideMode(Qt.ElideNone)
        self.connector_list.setMovement(QListWidget.Static)
        self.connector_list.setSpacing(12)

        azure_icon_path = os.path.join(ASSETS_DIR, 'img', 'azure', 'Azure.svg')
        azure_icon = QIcon(azure_icon_path)
        azure_item = QListWidgetItem(azure_icon, "Microsoft Azure")
        azure_item.setData(Qt.UserRole, "azure_v2")
        self.connector_list.addItem(azure_item)

        self.connector_list.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.connector_list)
        self.connector_list.setCurrentRow(0)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept_selection(self) -> None:
        """Accept the dialog using the currently selected connector type."""
        if selected_items := self.connector_list.selectedItems():
            self.selected_connector_type = selected_items[0].data(Qt.UserRole)
            self.accept()