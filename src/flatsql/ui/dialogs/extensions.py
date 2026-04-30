"""Modeless dialog for browsing and installing DuckDB extensions per connection."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from flatsql.core.extension_manager import ExtensionInfo, ExtensionManager


class _ExtensionTableModel(QAbstractTableModel):
    """Backing model exposing the current extension list to the table view."""

    HEADERS = ("Name", "Description", "Version", "Status")

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize an empty model."""
        super().__init__(parent)
        self._rows: list[ExtensionInfo] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of extension rows currently held by the model."""
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the fixed column count: name, description, version, status."""
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        """Provide horizontal header labels."""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        """Return the cell value for the given role and index."""
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        info = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return info.name
            if col == 1:
                return info.description
            if col == 2:
                return info.version
            if col == 3:
                return self._status_label(info)
        if role == Qt.ToolTipRole:
            if col == 0 and info.aliases:
                return f"Aliases: {', '.join(info.aliases)}"
            if col == 1 and info.description:
                return info.description
        return None

    @staticmethod
    def _status_label(info: ExtensionInfo) -> str:
        """Return a short, human-readable status string for the row."""
        if info.loaded:
            return "Loaded"
        if info.is_builtin:
            return "Built-in"
        if info.installed:
            return "Installed"
        return "Not installed"

    def set_rows(self, rows: list[ExtensionInfo]) -> None:
        """Replace the model's rows with a new snapshot."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def info_at(self, source_row: int) -> ExtensionInfo | None:
        """Return the info at the given source row index, or None when out of range."""
        if 0 <= source_row < len(self._rows):
            return self._rows[source_row]
        return None


class ExtensionsDialog(QDialog):
    """Browse, install, load, and auto-load DuckDB extensions for a chosen connection."""

    def __init__(
        self,
        conn_manager: Any,
        extension_manager: ExtensionManager,
        initial_connection_key: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and prime the connection picker with the active key."""
        super().__init__(parent)
        self.setWindowTitle("DuckDB Extensions")
        self.resize(860, 540)
        self.setSizeGripEnabled(True)

        self.conn_manager = conn_manager
        self.extension_manager = extension_manager
        self._pending_load_after_install: tuple[str, str] | None = None

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Connection:"))
        self.conn_combo = QComboBox()
        self.conn_combo.setMinimumWidth(220)
        header.addWidget(self.conn_combo, 1)
        header.addSpacing(12)
        header.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search by name or description...")
        header.addWidget(self.filter_edit, 2)
        self.refresh_button = QPushButton("Refresh")
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.model = _ExtensionTableModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel(" ")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.install_button = QPushButton("Install")
        self.install_button.setEnabled(False)
        self.load_button = QPushButton("Load")
        self.load_button.setEnabled(False)
        self.uninstall_button = QPushButton("Uninstall")
        self.uninstall_button.setEnabled(False)
        self.autoload_check = QCheckBox("Auto-load on connect")
        self.autoload_check.setEnabled(False)
        actions.addWidget(self.install_button)
        actions.addWidget(self.load_button)
        actions.addWidget(self.uninstall_button)
        actions.addWidget(self.autoload_check)
        actions.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setDefault(True)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

        self.conn_combo.currentIndexChanged.connect(lambda _idx: self._refresh())
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)
        self.refresh_button.clicked.connect(self._refresh)
        self.close_button.clicked.connect(self.close)
        self.install_button.clicked.connect(self._on_install_clicked)
        self.load_button.clicked.connect(self._on_load_clicked)
        self.uninstall_button.clicked.connect(self._on_uninstall_clicked)
        self.autoload_check.toggled.connect(self._on_autoload_toggled)
        self.table.selectionModel().currentRowChanged.connect(lambda *_: self._update_action_buttons())

        self.extension_manager.extensions_listed.connect(self._on_extensions_listed)
        self.extension_manager.operation_started.connect(self._on_operation_started)
        self.extension_manager.operation_completed.connect(self._on_operation_completed)
        self.conn_manager.db_connections_changed.connect(self._refresh_connection_list)

        self._refresh_connection_list(preserve=initial_connection_key)

    def set_connection(self, connection_key: str) -> None:
        """Select the given connection key in the picker, refreshing the list."""
        idx = self.conn_combo.findData(connection_key)
        if idx >= 0:
            self.conn_combo.setCurrentIndex(idx)

    def _refresh_connection_list(self, preserve: str | None = None) -> None:
        """Repopulate the connection picker, restoring the prior selection when possible."""
        previous = preserve if preserve is not None else self._selected_conn_key()
        self.conn_combo.blockSignals(True)
        self.conn_combo.clear()
        for key in self.conn_manager.db_connections.keys():
            engine = self.conn_manager.get_db(key)
            display = engine.get_display_name() if engine else key
            label = display if display == key else f"{display}  —  {key}"
            self.conn_combo.addItem(label, key)
        self.conn_combo.blockSignals(False)

        if previous is not None:
            self.set_connection(previous)
        if self.conn_combo.currentIndex() < 0 and self.conn_combo.count() > 0:
            self.conn_combo.setCurrentIndex(0)
        self._refresh()

    def _selected_conn_key(self) -> str | None:
        """Return the data role of the currently selected connection picker entry."""
        if self.conn_combo.count() == 0:
            return None
        return self.conn_combo.currentData()

    def _refresh(self) -> None:
        """Ask the manager to re-list extensions for the current connection."""
        key = self._selected_conn_key()
        if not key:
            self.model.set_rows([])
            self.status_label.setText("No connection selected.")
            self._update_action_buttons()
            return
        self.status_label.setText(f"Loading extensions for {key}...")
        self.extension_manager.list_extensions(key)

    def _on_extensions_listed(self, connection_key: str, infos: list[ExtensionInfo]) -> None:
        """Populate the table when the manager emits a fresh extension snapshot."""
        if connection_key != self._selected_conn_key():
            return

        previous = self._selected_info()
        previous_name = previous.name if previous else None

        self.model.set_rows(infos)
        self.status_label.setText(f"{len(infos)} extensions for {connection_key}.")

        if previous_name is not None:
            for source_row, item in enumerate(infos):
                if item.name == previous_name:
                    proxy_index = self.proxy.mapFromSource(self.model.index(source_row, 0))
                    if proxy_index.isValid():
                        self.table.selectRow(proxy_index.row())
                    break

        self._update_action_buttons()

    def _selected_info(self) -> ExtensionInfo | None:
        """Return the ExtensionInfo for the currently highlighted row, or None."""
        sel_model = self.table.selectionModel()
        if not sel_model:
            return None
        idx = sel_model.currentIndex()
        if not idx.isValid():
            return None
        source = self.proxy.mapToSource(idx)
        return self.model.info_at(source.row())

    def _update_action_buttons(self) -> None:
        """Recompute Install/Load/Auto-load enable state from the current selection."""
        info = self._selected_info()
        key = self._selected_conn_key()

        self.autoload_check.blockSignals(True)
        try:
            if not info:
                self.install_button.setEnabled(False)
                self.install_button.setToolTip("")
                self.load_button.setEnabled(False)
                self.load_button.setToolTip("")
                self.uninstall_button.setEnabled(False)
                self.uninstall_button.setToolTip("")
                self.autoload_check.setEnabled(False)
                self.autoload_check.setChecked(False)
                self.autoload_check.setToolTip("")
                return

            if info.is_builtin:
                self.install_button.setEnabled(False)
                self.install_button.setToolTip("Built-in extension; no installation needed.")
            elif info.installed:
                self.install_button.setEnabled(False)
                self.install_button.setToolTip("Already installed.")
            else:
                self.install_button.setEnabled(True)
                self.install_button.setToolTip(f"Install {info.name} from the DuckDB extension repository.")

            if info.loaded:
                self.load_button.setEnabled(False)
                self.load_button.setToolTip("Already loaded for this connection.")
            elif info.installed or info.is_builtin:
                self.load_button.setEnabled(True)
                self.load_button.setToolTip(f"Load {info.name} into this connection.")
            else:
                self.load_button.setEnabled(True)
                self.load_button.setToolTip(f"Install and load {info.name} in one step.")

            if info.is_builtin:
                self.uninstall_button.setEnabled(False)
                self.uninstall_button.setToolTip("Built-in extensions cannot be uninstalled.")
            elif info.installed:
                self.uninstall_button.setEnabled(True)
                self.uninstall_button.setToolTip(
                    f"Delete the cached binary for {info.name}. If currently loaded, it stays loaded until reconnect."
                )
            else:
                self.uninstall_button.setEnabled(False)
                self.uninstall_button.setToolTip("Not installed.")

            persistent = self.extension_manager.is_persistent_capable(key)
            if persistent:
                persisted = info.name in self.extension_manager.get_autoload(key)
                self.autoload_check.setEnabled(True)
                self.autoload_check.setChecked(persisted)
                self.autoload_check.setToolTip(
                    f"Re-LOAD {info.name} automatically each time this database is opened."
                )
            else:
                self.autoload_check.setEnabled(False)
                self.autoload_check.setChecked(False)
                if key == ":memory:":
                    self.autoload_check.setToolTip(
                        "Auto-load is unavailable for the in-memory session DB; the connection is recreated each launch."
                    )
                elif key and key.startswith("databricks_"):
                    self.autoload_check.setToolTip(
                        "Databricks connections install their required extensions automatically."
                    )
                else:
                    self.autoload_check.setToolTip("")
        finally:
            self.autoload_check.blockSignals(False)

    def _on_install_clicked(self) -> None:
        """Kick off an INSTALL on the selected extension."""
        info = self._selected_info()
        key = self._selected_conn_key()
        if not info or not key:
            return
        self.install_button.setEnabled(False)
        self.extension_manager.install(key, info.name)

    def _on_load_clicked(self) -> None:
        """Load the selected extension; install it first when not yet on disk."""
        info = self._selected_info()
        key = self._selected_conn_key()
        if not info or not key:
            return
        self.load_button.setEnabled(False)
        if info.installed or info.is_builtin:
            self.extension_manager.load(key, info.name)
        else:
            self.install_button.setEnabled(False)
            self._pending_load_after_install = (key, info.name)
            self.extension_manager.install(key, info.name)

    def _on_uninstall_clicked(self) -> None:
        """Confirm and delete the cached extension binary."""
        info = self._selected_info()
        key = self._selected_conn_key()
        if not info or not key:
            return
        confirm = QMessageBox.question(
            self,
            "Uninstall extension",
            f"Delete the cached binary for '{info.name}'?\n\n"
            "If the extension is currently loaded, it remains loaded in this session "
            "until the connection is closed. You can re-install it at any time.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.uninstall_button.setEnabled(False)
        self.extension_manager.uninstall(key, info.name)

    def _on_autoload_toggled(self, checked: bool) -> None:
        """Persist or remove the selected extension from the per-connection auto-load list."""
        info = self._selected_info()
        key = self._selected_conn_key()
        if not info or not key:
            return
        self.extension_manager.set_autoload(key, info.name, checked)

    _PROGRESSIVE = {"install": "Installing", "load": "Loading", "uninstall": "Uninstalling"}
    _COMPLETED = {"install": "installed", "load": "loaded", "uninstall": "uninstalled"}

    def _on_operation_started(self, connection_key: str, op: str, ext_name: str) -> None:
        """Surface in-flight operation status in the footer label."""
        if connection_key != self._selected_conn_key():
            return
        verb = self._PROGRESSIVE.get(op, op.capitalize())
        self.status_label.setText(f"{verb} {ext_name}...")

    def _on_operation_completed(
        self,
        connection_key: str,
        op: str,
        ext_name: str,
        ok: bool,
        error: str,
    ) -> None:
        """Re-list and update the footer label after an extension operation finishes."""
        if op == "install" and self._pending_load_after_install == (connection_key, ext_name):
            self._pending_load_after_install = None
            if ok:
                self.extension_manager.load(connection_key, ext_name)
                return

        if connection_key != self._selected_conn_key():
            self._update_action_buttons()
            return
        if ok:
            verb = self._COMPLETED.get(op, op + "d")
            self.status_label.setText(f"{ext_name} {verb}.")
            self._refresh()
        else:
            self.status_label.setText(f"Failed to {op} {ext_name}: {error}")
            self._update_action_buttons()
