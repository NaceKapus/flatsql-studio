"""DuckDB extension discovery, installation, and per-connection auto-load."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import duckdb
from PySide6.QtCore import QObject, QThread, Signal

from flatsql.core.logger import get_logger

logger = get_logger(__name__)

_EXT_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_LIST_SQL = (
    "SELECT extension_name, description, installed, loaded, "
    "install_path, extension_version, aliases "
    "FROM duckdb_extensions() ORDER BY extension_name"
)


@dataclass(frozen=True)
class ExtensionInfo:
    """Snapshot of a single DuckDB extension's status for a given connection."""

    name: str
    description: str
    version: str
    installed: bool
    loaded: bool
    install_path: str
    aliases: tuple[str, ...]

    @property
    def is_builtin(self) -> bool:
        """True for statically-linked extensions that need no INSTALL step."""
        path = (self.install_path or "").upper()
        return "BUILT-IN" in path or "STATICALLY" in path


class ExtensionInstallWorker(QObject):
    """Run a single ``INSTALL <name>`` on a background DuckDB connection."""

    finished = Signal(str, bool, str)

    def __init__(self, db_name: str, ext_name: str) -> None:
        """Initialize the worker with the target database file and extension name."""
        super().__init__()
        self.db_name = db_name
        self.ext_name = ext_name

    def run(self) -> None:
        """Connect, run INSTALL on a fresh connection, and emit the outcome."""
        try:
            con = duckdb.connect(database=self.db_name, read_only=False)
            try:
                con.execute(f"INSTALL {self.ext_name}")
                self.finished.emit(self.ext_name, True, "")
            finally:
                con.close()
        except Exception as exc:
            self.finished.emit(self.ext_name, False, str(exc))


class ExtensionManager(QObject):
    """Façade for listing, installing, loading, and auto-loading DuckDB extensions."""

    extensions_listed = Signal(str, list)
    operation_started = Signal(str, str, str)
    operation_completed = Signal(str, str, str, bool, str)

    def __init__(self, conn_manager: Any, settings_manager: Any) -> None:
        """Initialize the manager with references to connection and settings services."""
        super().__init__()
        self.conn_manager = conn_manager
        self.settings_manager = settings_manager
        self._active: list[tuple[QThread, ExtensionInstallWorker]] = []
        self._observed: dict[str, dict[str, ExtensionInfo]] = {}

    @staticmethod
    def is_valid_name(name: str) -> bool:
        """Return True when the extension name only contains safe characters."""
        return bool(name) and bool(_EXT_NAME_RE.match(name))

    def is_persistent_capable(self, connection_key: str | None) -> bool:
        """Return True when auto-load persistence is meaningful for the connection.

        ``:memory:`` is included because the auto-load list is keyed by connection
        identifier in settings, not stored in the DuckDB file itself — each launch
        re-runs the LOADs against the fresh temp DB. Databricks connections are
        excluded because their connector hardcodes its own extension setup.
        """
        if not connection_key:
            return False
        if connection_key.startswith("databricks_"):
            return False
        return True

    def list_extensions(self, connection_key: str) -> None:
        """Query duckdb_extensions() and emit the result, synthesizing rows for known-but-uninstalled extensions."""
        engine = self.conn_manager.get_db(connection_key)
        if not engine or not engine.main_con:
            self.extensions_listed.emit(connection_key, [])
            return
        try:
            df = engine.main_con.execute(_LIST_SQL).pl()
        except Exception as exc:
            logger.exception("Failed to list extensions for %s.", connection_key)
            self.operation_completed.emit(connection_key, "list", "", False, str(exc))
            self.extensions_listed.emit(connection_key, [])
            return

        infos = self._extension_info_from_df(df)
        observed = self._observed.setdefault(connection_key, {})
        present = set()
        for info in infos:
            observed[info.name] = info
            present.add(info.name)

        for name, last_known in observed.items():
            if name in present:
                continue
            infos.append(
                ExtensionInfo(
                    name=name,
                    description=last_known.description,
                    version="",
                    installed=False,
                    loaded=False,
                    install_path="",
                    aliases=last_known.aliases,
                )
            )

        infos.sort(key=lambda i: i.name)
        self.extensions_listed.emit(connection_key, infos)

    def install(self, connection_key: str, name: str) -> None:
        """Run INSTALL on a worker thread and emit the result on completion."""
        if not self.is_valid_name(name):
            self.operation_completed.emit(connection_key, "install", name, False, "Invalid extension name.")
            return
        engine = self.conn_manager.get_db(connection_key)
        if not engine:
            self.operation_completed.emit(connection_key, "install", name, False, "No active connection.")
            return

        self.operation_started.emit(connection_key, "install", name)
        worker = ExtensionInstallWorker(engine.db_name, name)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda ext, ok, err: self._on_install_finished(connection_key, ext, ok, err, thread, worker)
        )
        self._active.append((thread, worker))
        thread.start()

    def load(self, connection_key: str, name: str) -> None:
        """Run LOAD synchronously on engine.main_con; LOAD is a fast metadata op."""
        if not self.is_valid_name(name):
            self.operation_completed.emit(connection_key, "load", name, False, "Invalid extension name.")
            return
        engine = self.conn_manager.get_db(connection_key)
        if not engine or not engine.main_con:
            self.operation_completed.emit(connection_key, "load", name, False, "No active connection.")
            return

        self.operation_started.emit(connection_key, "load", name)
        try:
            engine.main_con.execute(f"LOAD {name}")
            self.operation_completed.emit(connection_key, "load", name, True, "")
        except Exception as exc:
            err = str(exc)
            if "already loaded" in err.lower():
                self.operation_completed.emit(connection_key, "load", name, True, "")
            else:
                self.operation_completed.emit(connection_key, "load", name, False, err)

    def uninstall(self, connection_key: str, name: str) -> None:
        """Delete the cached extension binary from disk and clear any auto-load entry."""
        if not self.is_valid_name(name):
            self.operation_completed.emit(connection_key, "uninstall", name, False, "Invalid extension name.")
            return
        engine = self.conn_manager.get_db(connection_key)
        if not engine or not engine.main_con:
            self.operation_completed.emit(connection_key, "uninstall", name, False, "No active connection.")
            return

        try:
            row = engine.main_con.execute(
                "SELECT install_path FROM duckdb_extensions() WHERE extension_name = ?",
                [name],
            ).fetchone()
        except Exception as exc:
            self.operation_completed.emit(connection_key, "uninstall", name, False, str(exc))
            return

        install_path = (row[0] if row else "") or ""
        upper = install_path.upper()
        if not install_path or "BUILT-IN" in upper or "STATICALLY" in upper:
            self.operation_completed.emit(
                connection_key, "uninstall", name, False, "Built-in extensions cannot be uninstalled."
            )
            return

        self.operation_started.emit(connection_key, "uninstall", name)
        try:
            if os.path.exists(install_path):
                os.remove(install_path)
        except Exception as exc:
            self.operation_completed.emit(connection_key, "uninstall", name, False, str(exc))
            return

        for autoload_key in list((self.settings_manager.get("extension_autoload", {}) or {}).keys()):
            self.set_autoload(autoload_key, name, False)

        self.operation_completed.emit(connection_key, "uninstall", name, True, "")

    def get_autoload(self, connection_key: str | None) -> list[str]:
        """Return the persisted auto-load list for a file-backed connection."""
        if not self.is_persistent_capable(connection_key):
            return []
        all_autoload = self.settings_manager.get("extension_autoload", {}) or {}
        return list(all_autoload.get(connection_key, []))

    def set_autoload(self, connection_key: str, name: str, enabled: bool) -> None:
        """Persist or remove an extension from the per-connection auto-load list."""
        if not self.is_persistent_capable(connection_key):
            return
        if not self.is_valid_name(name):
            return

        all_autoload = dict(self.settings_manager.get("extension_autoload", {}) or {})
        current = list(all_autoload.get(connection_key, []))

        if enabled and name not in current:
            current.append(name)
        elif not enabled and name in current:
            current.remove(name)
        else:
            return

        if current:
            all_autoload[connection_key] = current
        else:
            all_autoload.pop(connection_key, None)

        self.settings_manager.set("extension_autoload", all_autoload)
        self.settings_manager.save()

    def apply_autoload(self, engine: Any, connection_key: str | None) -> None:
        """Run LOAD for every persisted auto-load extension on a freshly built engine."""
        if not self.is_persistent_capable(connection_key):
            return
        if not engine or not engine.main_con:
            return
        for name in self.get_autoload(connection_key):
            if not self.is_valid_name(name):
                continue
            try:
                engine.main_con.execute(f"LOAD {name}")
            except Exception:
                logger.exception("Failed to auto-load extension %s on %s.", name, connection_key)

    def shutdown(self) -> None:
        """Stop all in-flight install workers cleanly. Called from MainWindow.closeEvent."""
        for thread, _worker in list(self._active):
            thread.quit()
            thread.wait(2000)
        self._active.clear()

    def _on_install_finished(
        self,
        connection_key: str,
        ext_name: str,
        ok: bool,
        error: str,
        thread: QThread,
        worker: ExtensionInstallWorker,
    ) -> None:
        """Tear down the worker thread and emit the operation_completed signal."""
        try:
            self.operation_completed.emit(connection_key, "install", ext_name, ok, error)
        finally:
            thread.quit()
            thread.wait()
            try:
                self._active.remove((thread, worker))
            except ValueError:
                pass

    @staticmethod
    def _extension_info_from_df(df: Any) -> list[ExtensionInfo]:
        """Convert the duckdb_extensions() Polars DataFrame into ExtensionInfo records."""
        infos: list[ExtensionInfo] = []
        for row in df.iter_rows(named=True):
            aliases_raw = row.get("aliases") or []
            if isinstance(aliases_raw, (list, tuple)):
                aliases = tuple(str(a) for a in aliases_raw if a)
            else:
                aliases = ()
            infos.append(
                ExtensionInfo(
                    name=str(row.get("extension_name") or ""),
                    description=str(row.get("description") or ""),
                    version=str(row.get("extension_version") or ""),
                    installed=bool(row.get("installed")),
                    loaded=bool(row.get("loaded")),
                    install_path=str(row.get("install_path") or ""),
                    aliases=aliases,
                )
            )
        return infos
