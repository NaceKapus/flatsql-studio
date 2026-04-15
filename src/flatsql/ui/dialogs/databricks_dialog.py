"""Databricks Unity Catalog connection dialog with credential management."""
from __future__ import annotations

import keyring
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


_DATABRICKS_KEYRING_SERVICE = "FlatSQLStudio_Databricks"
_LEGACY_DATABRICKS_KEYRING_SERVICE = "FlatSQL_Databricks"


class UnityCatalogDialog(QDialog):
    """Dialog for connecting to Databricks Unity Catalog.
    
    Supports secure credential storage via OS keyring and auto-fills saved tokens
    when a known workspace URL is entered. Ensures URLs are properly formatted
    for DuckDB connectivity.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the Unity Catalog connection dialog.
        
        Args:
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("Connect to Databricks Unity Catalog")
        self.resize(450, 200)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # Workspace URL with auto-fill support
        self.workspace_url_input = QLineEdit()
        self.workspace_url_input.setPlaceholderText(
            "https://adb-...azuredatabricks.net"
        )
        self.workspace_url_input.textChanged.connect(self._try_load_token)

        # Personal Access Token (password mode)
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.Password)
        self.token_input.setPlaceholderText("dapi...")

        # Catalog Name
        self.catalog_input = QLineEdit()
        self.catalog_input.setPlaceholderText("hive_metastore")

        form_layout.addRow("Workspace URL:", self.workspace_url_input)
        form_layout.addRow("Personal Access Token:", self.token_input)
        form_layout.addRow("Catalog Name:", self.catalog_input)

        layout.addLayout(form_layout)

        # OK/Cancel buttons
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _try_load_token(self) -> None:
        """Auto-fill token if workspace URL matches a securely stored credential."""
        url = self.workspace_url_input.text().strip().rstrip("/")
        if url:
            # Look up the token in Windows Credential Manager / Mac Keychain
            for service_name in (_DATABRICKS_KEYRING_SERVICE, _LEGACY_DATABRICKS_KEYRING_SERVICE):
                saved_token = keyring.get_password(service_name, url)
                if saved_token:
                    self.token_input.setText(saved_token)
                    break

    def _on_accept(self) -> None:
        """Accept the dialog (wrapper for consistency)."""
        self.accept()

    def get_credentials(self) -> dict:
        """Retrieve and normalize connection credentials.
        
        Ensures workspace URL is properly formatted with https:// and no trailing
        slashes for DuckDB compatibility.
        
        Returns:
            Dictionary with endpoint, token, and catalog keys.
        """
        # Get raw string and remove accidental whitespaces
        raw_url = self.workspace_url_input.text().strip()

        # Force https:// if the user pasted the URL without it
        if raw_url and not raw_url.startswith("http"):
            raw_url = "https://" + raw_url

        # Strip trailing slashes so DuckDB doesn't create invalid URLs
        clean_url = raw_url.rstrip("/")

        return {
            "endpoint": clean_url,
            "token": self.token_input.text().strip(),
            "catalog": self.catalog_input.text().strip(),
        }
