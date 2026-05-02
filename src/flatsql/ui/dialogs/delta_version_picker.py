"""Dialog for picking a Delta-table version for time-travel queries."""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)


class DeltaVersionPickerDialog(QDialog):
    """Display Delta-table commit history and let the user pick one version.

    History entries come from ``FlatEngine.get_delta_history()`` — each row has
    ``version``, ``commit_time``, ``operation``, and ``operation_parameters``.
    The latest version is preselected; double-click or OK accepts.
    """

    _COLUMNS = ("Version", "Timestamp", "Operation", "Parameters")

    def __init__(
        self,
        history: list[dict[str, Any]],
        table_name: str,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the dialog with a list of Delta history rows."""
        super().__init__(parent)
        self.history = history or []
        self.setWindowTitle(f"Time-travel: {table_name}")
        self.resize(720, 420)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"Pick a version of <b>{table_name}</b> to query:"))

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda _idx: self.accept())

        self.model = QStandardItemModel(self.table)
        self.model.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.setModel(self.model)
        layout.addWidget(self.table)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._populate()

    def _populate(self) -> None:
        """Fill the table from ``self.history`` and preselect the latest row."""
        if not self.history:
            placeholder = QStandardItem("No versions found in _delta_log/.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.model.appendRow([placeholder, QStandardItem(), QStandardItem(), QStandardItem()])
            self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            return

        for row in self.history:
            version = row.get("version")
            commit_time = row.get("commit_time")
            operation = row.get("operation") or ""
            params = row.get("operation_parameters")
            params_text = ""
            if params is not None:
                try:
                    params_text = json.dumps(params, default=str)
                except (TypeError, ValueError):
                    params_text = str(params)

            version_item = QStandardItem(str(version) if version is not None else "")
            version_item.setData(version, Qt.UserRole)
            version_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            timestamp_item = QStandardItem(str(commit_time) if commit_time is not None else "")
            operation_item = QStandardItem(str(operation))
            params_item = QStandardItem(params_text)

            self.model.appendRow([version_item, timestamp_item, operation_item, params_item])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.selectRow(0)
        self.table.setFocus()

    def selected_version(self) -> int | None:
        """Return the integer version of the selected row, or None if nothing valid is picked."""
        indexes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not indexes:
            return None
        version_item = self.model.itemFromIndex(indexes[0])
        if version_item is None:
            return None
        version_value = version_item.data(Qt.UserRole)
        if version_value is None:
            return None
        try:
            return int(version_value)
        except (TypeError, ValueError):
            return None
