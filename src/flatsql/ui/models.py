"""Qt item models used by FlatSQL Studio UI components."""

from __future__ import annotations

import json
import os
from typing import Any

import polars as pl
from PySide6.QtCore import QAbstractTableModel, QMimeData, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QStandardItemModel
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit
)

from flatsql.core.logger import get_logger

logger = get_logger(__name__)


class PolarsModel(QAbstractTableModel):
    """Expose a Polars dataframe through Qt's table model interface."""

    def __init__(self, data: pl.DataFrame | None) -> None:
        """Initialize the model with an optional Polars dataframe."""
        super().__init__()
        self._data = data

    def rowCount(self, parent: Any = None) -> int:
        """Return the number of rows available to the view."""
        if self._data is None:
            return 0
        return self._data.height

    def columnCount(self, parent: Any = None) -> int:
        """Return the number of columns, including the row-number column."""
        if self._data is None:
            return 1
        return self._data.width + 1

    def _column_dtype(self, col: int) -> pl.DataType | None:
        """Return the Polars dtype for a visible result-grid column."""
        if self._data is None or col <= 0 or col > self._data.width:
            return None
        col_name = self._data.columns[col - 1]
        return self._data.schema.get(col_name)

    def data(self, index: Any, role: int = Qt.DisplayRole) -> Any:
        """Return cell data, formatting, and visual styling for the view."""
        if not index.isValid():
            return None

        if index.column() == 0:
            if role == Qt.DisplayRole:
                return str(index.row() + 1)
            return None

        val = self._data.item(index.row(), index.column() - 1)

        if role == Qt.DisplayRole:
            if val is None:
                return "NULL"

            if isinstance(val, dict):
                if not val:
                    return "{}"
                peek = str(val)
                return peek[:35] + " ...}" if len(peek) > 35 else peek

            if isinstance(val, pl.Series):
                if len(val) == 0:
                    return "[]"
                peek = str(val.head(1).to_list())
                return peek[:-1][:35] + " ...]" if len(peek) > 35 else peek

            if isinstance(val, list):
                if not val:
                    return "[]"
                peek = str(val)
                return peek[:35] + " ...]" if len(peek) > 35 else peek
            
            return str(val)

        if role == Qt.ForegroundRole:
            if val is None:
                return QColor("#808080")

        if role == Qt.FontRole:
            if val is None:
                font = QFont()
                font.setItalic(True)
                return font
                
        return None

    def headerData(self, col: int, orientation: Qt.Orientation, role: int) -> Any:
        """Return header text and tooltips for the results grid."""
        if orientation != Qt.Horizontal:
            return None

        if col == 0:
            if role == Qt.DisplayRole:
                return ""
            if role == Qt.ToolTipRole:
                return "Row number"
            return None

        if self._data is None:
            return None

        column_name = self._data.columns[col - 1]
        dtype = self._column_dtype(col)
        dtype_name = str(dtype or "Unknown")

        if role == Qt.DisplayRole:
            return column_name
        if role == Qt.ToolTipRole:
            return f"{column_name} ({dtype_name})"
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def sort(self, column: int, order: Qt.SortOrder) -> None:
        """Sorts the model by a specific column."""
        if column == 0:
            return

        try:
            col_name = self._data.columns[column - 1]
            self.layoutAboutToBeChanged.emit()
            is_descending = (order != Qt.AscendingOrder)
            self._data = self._data.sort(col_name, descending=is_descending)
            self.layoutChanged.emit()
        except Exception:
            logger.exception("Failed to sort column %s in PolarsModel.", column)


class FileExplorerModel(QStandardItemModel):
    """Custom model to handle drag and drop for file system items."""

    def mimeData(self, indexes: list[Any]) -> QMimeData:
        """Build mime data for dragged local files or Azure URIs."""
        mime_data = QMimeData()
        urls = []
        texts = []
        
        for index in indexes:
            if index.isValid():
                item = self.itemFromIndex(index)
                raw_path = item.data(Qt.UserRole + 3)
                
                converted_path = item.data(Qt.UserRole + 4)
                path = converted_path if converted_path else raw_path
                
                if path:
                    if os.path.exists(path):
                        urls.append(QUrl.fromLocalFile(path))
                    elif path.startswith("abfss://") or path.startswith("az://"):
                        urls.append(QUrl(path))
                    else:
                        texts.append(path)

        if urls:
            mime_data.setUrls(urls)
        
        if texts:
            mime_data.setText("\n".join(texts))

        return mime_data

    def _create_adls_widget(self) -> QWidget:
        """Creates the form widget for ADLS connection details."""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)

        self.adls_name_input = QLineEdit()
        self.adls_name_input.setPlaceholderText("e.g., My ADLS Project")
        self.adls_account_input = QLineEdit()
        self.adls_account_input.setPlaceholderText("e.g., mystorageaccount")
        self.adls_container_input = QLineEdit()
        self.adls_container_input.setPlaceholderText("e.g., mycontainer")
        self.adls_conn_str_input = QLineEdit()
        self.adls_conn_str_input.setPlaceholderText("(Optional) Enter full connection string")

        layout.addRow("Display Name:", self.adls_name_input)
        layout.addRow("Storage Account Name:", self.adls_account_input)
        layout.addRow("Container Name:", self.adls_container_input)
        layout.addRow("Connection String:", self.adls_conn_str_input)

        return widget

    def get_connection_details(self) -> dict[str, str] | None:
        """Returns the details for the new connection."""
        conn_type = self.type_combo.currentData()
        if conn_type == "adls":
            return {
                "type": "adls",
                "name": self.adls_name_input.text(),
                "account_name": self.adls_account_input.text(),
                "container": self.adls_container_input.text(),
                "connection_string": self.adls_conn_str_input.text(),
            }
        return None