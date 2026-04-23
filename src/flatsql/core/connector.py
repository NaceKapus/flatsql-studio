"""Filesystem connectors for local and Azure-backed browsing."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import stat
import sys
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeAlias

import requests
from azure.identity import AuthenticationRecord, InteractiveBrowserCredential
from PySide6.QtGui import QIcon

from flatsql.config import ASSETS_DIR
from flatsql.core.logger import get_logger

if TYPE_CHECKING:
    from flatsql.core.engine import FlatEngine

logger = get_logger(__name__)

FileListing: TypeAlias = tuple[str, str, str]
IconInfo: TypeAlias = QIcon | tuple[str, str] | None


class FileSystemConnector(ABC):
    """Define the interface for filesystem-backed tree navigation."""

    def __init__(self, name: str) -> None:
        """Initialize the connector with a display name."""
        self.name = name

    @abstractmethod
    def get_display_name(self) -> str:
        """Returns a user-friendly name for the connection."""
        raise NotImplementedError

    @abstractmethod
    def list_files(self, engine: FlatEngine, path: str) -> list[FileListing]:
        """Lists files and directories at a given path."""
        raise NotImplementedError

    @abstractmethod
    def get_root_path(self) -> str:
        """Returns the root or base path for this connection as a string."""
        raise NotImplementedError

    def get_icon_info(self, path: str, is_dir: bool) -> IconInfo:
        """Return icon metadata for a path, or `None` to use defaults."""
        return None

class LocalFileSystemConnector(FileSystemConnector):
    """Connector for the local machine's file system."""

    def __init__(self) -> None:
        """Initialize the local filesystem connector."""
        super().__init__("This PC")

    def get_display_name(self) -> str:
        """Return the display name for the local filesystem root."""
        return "This PC"

    def list_files(self, engine: FlatEngine, path: str) -> list[FileListing]:
        """List files and directories for a local filesystem path."""
        results: list[FileListing] = []
        try:
            if not path:
                if sys.platform == 'win32':
                    import string

                    drives: list[FileListing] = []
                    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                    for letter in string.ascii_uppercase:
                        if bitmask & 1:
                            drive_path = f"{letter}:\\"
                            volume_name_buffer = ctypes.create_unicode_buffer(1024)
                            ctypes.windll.kernel32.GetVolumeInformationW(
                                ctypes.c_wchar_p(drive_path), volume_name_buffer,
                                ctypes.sizeof(volume_name_buffer), None, None, None, None, 0)
                            volume_label = volume_name_buffer.value
                            display_name = f"{volume_label} ({letter}:)" if volume_label else f"Local Disk ({letter}:)"
                            drives.append((display_name, 'directory', drive_path))
                        bitmask >>= 1
                    return drives
                elif sys.platform == 'darwin':
                    entries: list[FileListing] = []
                    home = os.path.expanduser('~')
                    entries.append((os.path.basename(home), 'directory', home))
                    volumes_dir = '/Volumes'
                    if os.path.isdir(volumes_dir):
                        for vol in sorted(os.listdir(volumes_dir)):
                            if not vol.startswith('.'):
                                entries.append((vol, 'directory', os.path.join(volumes_dir, vol)))
                    return entries
                else:
                    path = '/'

            with os.scandir(path) as it:
                for entry in it:
                    name = entry.name

                    if name.startswith('.') or name.startswith('$'):
                        continue

                    try:
                        if sys.platform == 'win32':
                            attrs = entry.stat().st_file_attributes
                            if attrs & stat.FILE_ATTRIBUTE_HIDDEN:
                                continue

                        if entry.is_dir():
                            results.append((name, 'directory', entry.path))
                        else:
                            results.append((name, 'file', entry.path))

                    except OSError:
                        continue

        except OSError:
            logger.exception("Failed to list local files at %s.", path)

        return results

    def get_root_path(self) -> str:
        """Return the root path for local browsing."""
        return ""


class AzureConnector(FileSystemConnector):
    """Browse Azure subscriptions, storage accounts, containers, and blobs."""

    def __init__(
        self,
        name: str = "Azure",
        tenant_id: str | None = None,
        authentication_record: AuthenticationRecord | None = None,
    ) -> None:
        """Initialize the Azure connector with optional tenant and auth state."""
        super().__init__(name)
        self.credential: InteractiveBrowserCredential | None = None
        self.tenant_id = tenant_id
        self.authentication_record = authentication_record
        self.account_hns_cache: dict[str, bool] = {}
        if self.authentication_record:
            self.user_display_name = self.authentication_record.username
        else:
            self.user_display_name: str | None = None

    def get_display_name(self) -> str:
        """Return the configured Azure connection display name."""
        return self.name

    def _get_credential(self) -> InteractiveBrowserCredential:
        """Initializes the credential object lazily."""
        if not self.credential:
            self.credential = InteractiveBrowserCredential(
                tenant_id=self.tenant_id,
                authentication_record=self.authentication_record,
            )
        return self.credential

    def login(self) -> AuthenticationRecord:
        """Trigger the browser login flow and return the auth record."""
        cred = self._get_credential()
        record = cred.authenticate()
        self.authentication_record = record
        self.user_display_name = record.username
        return record

    def _get_token(self, scope: str) -> str:
        """Generic helper to get a token for a specific scope."""
        cred = self._get_credential()
        token_obj = cred.get_token(scope)
        return token_obj.token

    def _get_arm_token(self) -> str:
        """Gets a token for Azure Resource Manager (Listing Subs/Accounts)."""
        return self._get_token("https://management.azure.com/.default")

    def _get_storage_token(self) -> str:
        """Gets a token for the Data Plane (Listing Containers/Blobs)."""
        return self._get_token("https://storage.azure.com/.default")

    def list_tenants(self) -> list[dict[str, Any]]:
        """Return available Azure tenants for the authenticated user."""
        token = self._get_arm_token()
        url = "https://management.azure.com/tenants?api-version=2022-12-01"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            return data.get('value', [])
        except Exception:
            logger.exception("Failed to list Azure tenants.")
            raise

    def _list_subscriptions(self) -> list[FileListing]:
        """Level 1: List all Azure Subscriptions."""
        try:
            token = self._get_arm_token()
            url = "https://management.azure.com/subscriptions?api-version=2020-01-01"
            headers = {"Authorization": f"Bearer {token}"}

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            subs = response.json().get('value', [])
            return [(s['displayName'], 'directory', s['subscriptionId']) for s in subs]
        except Exception:
            logger.exception("Failed to list Azure subscriptions.")
            return []

    def _list_storage_accounts(self, subscription_id: str) -> list[FileListing]:
        """Level 2: List Storage Accounts within a Subscription."""
        try:
            token = self._get_arm_token()
            url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.Storage/storageAccounts?api-version=2019-06-01"
            headers = {"Authorization": f"Bearer {token}"}

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            accounts = response.json().get('value', [])
            results: list[FileListing] = []
            for acc in accounts:
                name = acc['name']
                is_hns = acc.get('properties', {}).get('isHnsEnabled', False)
                self.account_hns_cache[name] = is_hns
                full_path = f"{subscription_id}/{name}"
                results.append((name, 'directory', full_path))
            return results
        except Exception:
            logger.exception("Failed to list Azure storage accounts for subscription %s.", subscription_id)
            return []

    def _list_containers(self, subscription_id: str, account_name: str) -> list[FileListing]:
        """Level 3: List Containers within a Storage Account using Blob REST API."""
        try:
            token = self._get_storage_token()
            url = f"https://{account_name}.blob.core.windows.net/?comp=list"
            headers = {
                "Authorization": f"Bearer {token}",
                "x-ms-version": "2020-02-10",
            }

            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.error("Failed to list containers for %s: %s", account_name, response.text)
                return []

            root = ET.fromstring(response.content)
            results: list[FileListing] = []
            for container in root.findall(".//Container"):
                name = container.find("Name").text
                full_path = f"{subscription_id}/{account_name}/{name}"
                results.append((name, 'directory', full_path))
            return results

        except Exception:
            logger.exception("Failed to list containers for storage account %s.", account_name)
            return []

    def _setup_duckdb_secret(self, engine: FlatEngine, account_name: str) -> bool:
        """Configures DuckDB with the current token for a specific account."""
        try:
            token = self._get_storage_token()
            con = engine.main_con
            con.execute("INSTALL azure; LOAD azure;")
            sanitized_acc = account_name.replace('-', '_')
            secret_name = f"azure_secret_{sanitized_acc}"

            query = f"""
            CREATE OR REPLACE SECRET {secret_name} (
                TYPE AZURE,
                PROVIDER ACCESS_TOKEN,
                ACCESS_TOKEN '{token}',
                ACCOUNT_NAME '{account_name}'
            );
            """
            con.execute(query)
            return True
        except Exception:
            logger.exception("Failed to set up DuckDB Azure secret for %s.", account_name)
            return False

    def list_files(self, engine: FlatEngine, path: str) -> list[FileListing]:
        """List Azure resources or blobs for the provided hierarchical path."""
        parts = path.split('/') if path else []
        depth = len(parts)
        results: list[FileListing] = []

        if not path:
            results = self._list_subscriptions()
        elif depth == 1:
            subscription_id = parts[0]
            results = self._list_storage_accounts(subscription_id)
        elif depth == 2:
            subscription_id, account_name = parts
            results = self._list_containers(subscription_id, account_name)
        elif depth >= 3:
            subscription_id = parts[0]
            account_name = parts[1]
            container_name = parts[2]
            blob_path = "/".join(parts[3:])

            self._setup_duckdb_secret(engine, account_name)

            try:
                token = self._get_storage_token()
                prefix_param = f"&prefix={blob_path}/" if blob_path else ""
                if prefix_param == "&prefix=/":
                    prefix_param = ""

                url = f"https://{account_name}.blob.core.windows.net/{container_name}?restype=container&comp=list&delimiter=/{prefix_param}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "x-ms-version": "2020-02-10",
                }

                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    logger.error("Failed to list blobs for %s/%s: %s", account_name, container_name, response.text)
                    return []

                root = ET.fromstring(response.content)

                for prefix in root.findall(".//BlobPrefix"):
                    name_full = prefix.find("Name").text
                    display_name = name_full.rstrip('/').split('/')[-1]
                    clean_full_name = name_full.rstrip('/')
                    item_full_path = f"{subscription_id}/{account_name}/{container_name}/{clean_full_name}"
                    results.append((display_name, 'directory', item_full_path))

                for blob in root.findall(".//Blob"):
                    name_full = blob.find("Name").text
                    display_name = name_full.split('/')[-1]
                    item_full_path = f"{subscription_id}/{account_name}/{container_name}/{name_full}"
                    results.append((display_name, 'file', item_full_path))

            except Exception:
                logger.exception("Failed to list blobs for container %s.", container_name)
                return []

        return results

    def get_root_path(self) -> str:
        """Return the root path for Azure browsing."""
        return ""

    def get_icon_info(self, path: str, is_dir: bool) -> IconInfo:
        """Return icon metadata appropriate for the Azure tree depth."""
        def get_svg_icon(filename: str) -> QIcon | None:
            """Load an Azure-specific SVG icon if it exists on disk."""
            icon_path = os.path.join(ASSETS_DIR, 'img', 'azure', filename)
            if os.path.exists(icon_path):
                return QIcon(icon_path)
            return None

        if not path:
            return get_svg_icon("Azure.svg") or ('mdi.microsoft-azure', '#0078D4')

        parts = path.split('/')
        depth = len(parts)

        if depth == 1:
            return get_svg_icon("Subscriptions.svg") or ('mdi.shield-key', '#F2C811') 
        if depth == 2:
            return get_svg_icon("Storage_Accounts.svg") or ('mdi.server', '#008AD7') 
        if depth == 3:
            return get_svg_icon("Container.svg") or ('mdi.package-variant-closed', '#E85E00')
        if is_dir:
            return ('fa5s.folder', 'goldenrod')

        return None

    def get_storage_protocol(self, account_name: str) -> tuple[str, str]:
        """Returns (protocol, endpoint) based on whether HNS is enabled."""
        is_hns = self.account_hns_cache.get(account_name, False)
        if is_hns:
            return 'abfss', 'dfs.core.windows.net'
        return 'az', 'blob.core.windows.net'

    @staticmethod
    def serialize_auth_record(record: AuthenticationRecord) -> str:
        """Serialize an Azure authentication record for settings storage."""
        return record.serialize()

    @staticmethod
    def deserialize_auth_record(serialized_record: str) -> AuthenticationRecord:
        """Deserialize an Azure authentication record from settings storage."""
        return AuthenticationRecord.deserialize(serialized_record)