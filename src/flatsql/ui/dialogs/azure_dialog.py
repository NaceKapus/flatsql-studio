"""Azure connection dialog for authenticating and selecting directories."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AzureConnectionDialog(QDialog):
    """Two-step authentication dialog for Azure SQL connections.
    
    Step 1: User enters a connection name and authenticates via browser.
    Step 2: After authentication, user selects an Azure directory/catalog.
    """

    def __init__(self, conn_manager: object, parent: QWidget | None = None) -> None:
        """Initialize the Azure connection dialog.
        
        Args:
            conn_manager: Connection manager instance with fetch_azure_tenants method.
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.conn_manager = conn_manager
        self.auth_record: object | None = None
        self.auth_connector: object | None = None
        self.user_name = "Unknown"
        self.is_authenticated = False

        self.setWindowTitle("New Azure Connection")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create and configure the dialog UI."""
        layout = QVBoxLayout(self)

        # Connection Name
        layout.addWidget(QLabel("Connection Display Name:"))
        self.name_input = QLineEdit("Azure")
        layout.addWidget(self.name_input)

        # Tenant Dropdown (Hidden initially)
        self.tenant_label = QLabel("Select Azure Directory:")
        self.tenant_combo = QComboBox()
        self.tenant_label.setVisible(False)
        self.tenant_combo.setVisible(False)

        layout.addWidget(self.tenant_label)
        layout.addWidget(self.tenant_combo)

        layout.addSpacing(10)

        # Buttons
        btn_layout = QHBoxLayout()

        # The primary action button
        self.action_btn = QPushButton("Connect")
        self.action_btn.clicked.connect(self._handle_action)

        btn_layout.addStretch()
        btn_layout.addWidget(self.action_btn)
        layout.addLayout(btn_layout)

    def _handle_action(self) -> None:
        """Route the primary button action based on authentication state."""
        if not self.is_authenticated:
            self._authenticate()
        else:
            self.accept()

    def _authenticate(self) -> None:
        """Perform Azure authentication and populate the tenant dropdown."""
        conn_name = self.name_input.text().strip()
        if not conn_name:
            QMessageBox.warning(
                self, "Input Error", "Please enter a connection name."
            )
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.auth_connector, tenants = self.conn_manager.fetch_azure_tenants(
                conn_name
            )

            self.auth_record = getattr(self.auth_connector, "authentication_record", None)

            if not tenants:
                QMessageBox.warning(
                    self,
                    "No Subscriptions",
                    "Authenticated successfully, but no Azure Directories found.",
                )
                return

            # Populate dropdown
            self.tenant_combo.clear()
            for t in sorted(tenants, key=lambda x: x["displayName"]):
                display_text = f"{t['displayName']} ({t['tenantId']})"
                self.tenant_combo.addItem(display_text, t["tenantId"])

            if self.auth_record:
                self.user_name = self.auth_record.username

            # Progress to Step 2: Reveal dropdown and update the button
            self.is_authenticated = True
            self.tenant_label.setVisible(True)
            self.tenant_combo.setVisible(True)

            self.action_btn.setText("Connect")
            self.name_input.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(
                self,
                "Authentication Failed",
                f"Could not login to Azure:\n{e}",
            )
        finally:
            QApplication.restoreOverrideCursor()

    def get_connection_details(self) -> dict:
        """Retrieve the selected connection details.
        
        Returns:
            Dictionary with connection name, tenant ID, user name, and auth record.
        """
        return {
            "name": self.name_input.text().strip(),
            "tenant_id": self.tenant_combo.currentData(),
            "user_name": self.user_name,
            "auth_record": self.auth_record,
            "connector": self.auth_connector,
        }
