"""Connection lifecycle management for FlatSQL Studio."""

from __future__ import annotations

from typing import Any

import keyring
from PySide6.QtCore import QObject, Signal

from flatsql.core.connector import AzureConnector, FileSystemConnector, LocalFileSystemConnector
from flatsql.core.engine import FlatEngine
from flatsql.core.logger import get_logger

logger = get_logger(__name__)

_DATABRICKS_KEYRING_SERVICE = "FlatSQLStudio_Databricks"
_LEGACY_DATABRICKS_KEYRING_SERVICE = "FlatSQL_Databricks"


def _get_saved_databricks_token(endpoint: str) -> str | None:
    """Return a saved Databricks token from current or legacy keyring keys."""
    for service_name in (_DATABRICKS_KEYRING_SERVICE, _LEGACY_DATABRICKS_KEYRING_SERVICE):
        token = keyring.get_password(service_name, endpoint)
        if token:
            return token
    return None

class ConnectionManager(QObject):
    """Manage database and file-system connections used throughout the app."""

    db_connections_changed = Signal()
    fs_connections_changed = Signal()
    error_occurred = Signal(str, str)

    def __init__(self, settings_manager: Any) -> None:
        """Initialize the connection manager with persisted settings access."""
        super().__init__()
        self.settings_manager = settings_manager
        self.db_connections: dict[str, FlatEngine] = {}
        self.fs_connections: dict[str, FileSystemConnector] = {}
        self.db_keywords: list[str] = []
        self.db_functions: list[str] = []
        self.extension_manager: Any = None

    def set_extension_manager(self, extension_manager: Any) -> None:
        """Wire the ExtensionManager so new connections auto-load persisted extensions."""
        self.extension_manager = extension_manager

    def _apply_extension_autoload(self, engine: FlatEngine, key: str) -> None:
        """Replay the user's auto-load list against a freshly created engine."""
        if self.extension_manager is None:
            return
        try:
            self.extension_manager.apply_autoload(engine, key)
        except Exception:
            logger.exception("Failed to apply extension auto-load for %s.", key)

    def initialize_all(self) -> None:
        """Synchronously establishes all initial database and file system connections."""
        try:
            engine = FlatEngine(db_path=None, is_temp=True)
            self.db_connections[":memory:"] = engine
            self._apply_extension_autoload(engine, ":memory:")
        except Exception:
            logger.exception("Failed to connect to the in-memory database.")

        for db_file in self.settings_manager.get('connections', []):
            try:
                engine = FlatEngine(db_path=db_file)
                self.db_connections[db_file] = engine
                self._apply_extension_autoload(engine, db_file)
            except Exception:
                logger.exception("Failed to connect to saved database %s.", db_file)

        if default_engine := self.db_connections.get(":memory:"):
            self.db_keywords, self.db_functions = default_engine.get_syntax_components()

        self.restore_databricks_connections()
        self.fs_connections["Local Files"] = LocalFileSystemConnector()

        for conn_details in self.settings_manager.get('file_connections', []):
            if conn_details.get("type") == "azure_v2":
                try:
                    auth_record = None
                    serialized_record = conn_details.get("auth_record")
                    if isinstance(serialized_record, str) and serialized_record:
                        try:
                            auth_record = AzureConnector.deserialize_auth_record(serialized_record)
                        except Exception:
                            logger.exception(
                                "Failed to deserialize Azure auth record for %s.",
                                conn_details.get("name"),
                            )

                    connector = AzureConnector(
                        name=conn_details.get("name", "Azure"),
                        tenant_id=conn_details.get("tenant_id"),
                        authentication_record=auth_record,
                    )
                    self.fs_connections[conn_details["name"]] = connector
                except Exception:
                    logger.exception("Failed to load Azure connector %s.", conn_details.get("name"))

        self.db_connections_changed.emit()
        self.fs_connections_changed.emit()

    def restore_databricks_connections(self) -> None:
        """Silently restores Unity Catalog connections using OS Keyring."""
        db_conns: dict[str, dict[str, str]] = self.settings_manager.get('databricks_connections', {})
        for conn_key, config in db_conns.items():
            endpoint = config['endpoint']
            catalog = config['catalog']
            token = _get_saved_databricks_token(endpoint)

            if not token:
                logger.warning("Could not restore Databricks catalog %s because the token is missing.", catalog)
                continue

            try:
                engine = FlatEngine(is_temp=True)
                engine.get_display_name = lambda c=catalog: f"Databricks ({c})"
                con = engine.main_con

                con.execute("INSTALL httpfs; LOAD httpfs;")
                con.execute("INSTALL delta; LOAD delta;")
                con.execute("INSTALL unity_catalog; LOAD unity_catalog;")

                secret_name = f"uc_secret_{catalog}"
                con.execute(f"""
                CREATE OR REPLACE SECRET {secret_name} (
                    TYPE unity_catalog,
                    TOKEN '{token}',
                    ENDPOINT '{endpoint}',
                    AWS_REGION 'us-east-1'
                );
                """)
                con.execute(f"ATTACH '{catalog}' AS {catalog} (TYPE unity_catalog, SECRET {secret_name});")
                self.db_connections[conn_key] = engine
            except Exception:
                logger.exception("Failed to restore Databricks connection for catalog %s.", catalog)

    def add_databricks_connection(self, catalog: str, endpoint: str, token: str) -> None:
        """Authenticates and establishes a new Unity Catalog connection."""
        engine = FlatEngine(is_temp=True)
        engine.get_display_name = lambda: f"Databricks ({catalog})"
        con = engine.main_con

        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("INSTALL delta; LOAD delta;")
        con.execute("INSTALL unity_catalog; LOAD unity_catalog;")

        secret_name = f"uc_secret_{catalog}"
        con.execute(f"""
        CREATE OR REPLACE SECRET {secret_name} (
            TYPE unity_catalog,
            TOKEN '{token}',
            ENDPOINT '{endpoint}',
            AWS_REGION 'us-east-1'
        );
        """)
        con.execute(f"ATTACH '{catalog}' AS {catalog} (TYPE unity_catalog, SECRET {secret_name});")

        conn_key = f"databricks_{catalog}"
        self.db_connections[conn_key] = engine

        try:
            keyring.set_password(_DATABRICKS_KEYRING_SERVICE, endpoint, token)
        except Exception:
            logger.exception("Failed to save Databricks token for %s to the OS keyring.", endpoint)

        db_conns = self.settings_manager.get('databricks_connections', {})
        db_conns[conn_key] = {"catalog": catalog, "endpoint": endpoint}
        self.settings_manager.set('databricks_connections', db_conns)
        self.settings_manager.save()
        
        self.db_connections_changed.emit()

    def add_db_connection(self, db_path: str | None, is_temp: bool = False) -> None:
        """Creates and registers a new database connection."""
        key = ":memory:" if is_temp else db_path
        if key in self.db_connections:
            return

        try:
            engine = FlatEngine(db_path, is_temp)
            self.db_connections[key] = engine
            self._apply_extension_autoload(engine, key)

            if not is_temp:
                current_conns = self.settings_manager.get('connections', [])
                if db_path not in current_conns:
                    current_conns.append(db_path)
                    self.settings_manager.set('connections', current_conns)
                    self.settings_manager.save()

            self.db_connections_changed.emit()
        except Exception as e:
            self.error_occurred.emit("Connection Error", f"Failed to connect to {db_path}:\n{e}")

    def remove_db_connection(self, key: str) -> None:
        """Disconnects and removes a database connection."""
        if key not in self.db_connections:
            return

        engine = self.db_connections.pop(key)
        engine.close()

        current_conns = self.settings_manager.get('connections', [])
        if key != ":memory:" and key in current_conns:
            current_conns.remove(key)
            self.settings_manager.set('connections', current_conns)
            self.settings_manager.save()

        databricks_conns = self.settings_manager.get('databricks_connections', {})
        if key in databricks_conns:
            del databricks_conns[key]
            self.settings_manager.set('databricks_connections', databricks_conns)
            self.settings_manager.save()

        autoload = dict(self.settings_manager.get('extension_autoload', {}) or {})
        if key in autoload:
            del autoload[key]
            self.settings_manager.set('extension_autoload', autoload)
            self.settings_manager.save()

        self.db_connections_changed.emit()

    def fetch_azure_tenants(self, conn_name: str) -> tuple[AzureConnector, list[dict[str, Any]]]:
        """Authenticate once and return the live connector plus available tenants."""
        temp_connector = AzureConnector(name=conn_name, tenant_id=None)
        temp_connector.login()
        tenants = temp_connector.list_tenants()
        return temp_connector, tenants

    def add_azure_connection(
        self,
        name: str,
        tenant_id: str,
        user_name: str,
        auth_record: Any = None,
        connector: AzureConnector | None = None,
    ) -> None:
        """Registers a new Azure connection and saves it to settings."""
        try:
            azure_connector = connector or AzureConnector(
                name=name,
                tenant_id=tenant_id,
                authentication_record=auth_record,
            )

            azure_connector.name = name
            azure_connector.tenant_id = tenant_id
            self.fs_connections[name] = azure_connector

            effective_user_name = user_name or azure_connector.user_display_name or "Unknown"
            effective_auth_record = azure_connector.authentication_record or auth_record

            serialized_record = None
            if effective_auth_record:
                try:
                    serialized_record = AzureConnector.serialize_auth_record(effective_auth_record)
                except Exception:
                    logger.exception("Failed to serialize Azure auth record for %s.", name)

            current_file_conns = self.settings_manager.get('file_connections', [])
            current_file_conns.append({
                "name": name,
                "type": "azure_v2",
                "tenant_id": tenant_id,
                "user": effective_user_name,
                "auth_record": serialized_record,
            })
            self.settings_manager.set('file_connections', current_file_conns)
            self.settings_manager.save()

            self.fs_connections_changed.emit()
        except Exception as e:
            self.error_occurred.emit("Azure Error", f"Failed to add Azure connection:\n{e}")

    def remove_fs_connection(self, connection_name: str) -> None:
        """Removes a file system connection."""
        if connection_name in self.fs_connections:
            del self.fs_connections[connection_name]
            
            current_file_conns = self.settings_manager.get('file_connections', [])
            updated_conns = [c for c in current_file_conns if c.get('name') != connection_name]
            self.settings_manager.set('file_connections', updated_conns)
            self.settings_manager.save()
            
            self.fs_connections_changed.emit()

    def get_db(self, key: str | None) -> FlatEngine | None:
        """Return a database connection by key when it exists."""
        return self.db_connections.get(key)

    def close_all(self) -> None:
        """Close all active database connections."""
        for engine in self.db_connections.values():
            engine.close()