"""Application action orchestration between UI and core services."""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QFileDialog, QInputDialog
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from flatsql.config import SNIPPETS_DIR, LOG_PATH
from flatsql.core.path_utils import to_duckdb_path, to_duckdb_relation
from flatsql.core.sql_generator import SQLGenerator
from flatsql.core.sqlfluff_config import write_user_sqlfluff_config
from flatsql.core.exporter import DataExporter
from flatsql.core.theme import ThemeManager
from flatsql.ui.dialogs.file_ops import SplitFileDialog, MergeFilesDialog, ExportDialog
from flatsql.ui.dialogs.history import HistoryDialog
from flatsql.ui.dialogs.db_connection_dialog import AddDatabaseConnectionDialog
from flatsql.ui.dialogs.file_connection_dialog import AddFileConnectionDialog
from flatsql.ui.dialogs.databricks_dialog import UnityCatalogDialog
from flatsql.ui.dialogs.azure_dialog import AzureConnectionDialog
from flatsql.ui.dialogs.settings import SettingsDialog
from flatsql.ui.editor import QueryTextEdit

class ActionController:
    """
    Orchestrates business logic and ties together the UI panels, connection manager, 
    and SQL generation tools.
    """
    def __init__(self, main_window: Any) -> None:
        """Initialize action orchestration with a main window reference."""
        self.mw = main_window

    def format_sql_string(self, sql_string: str) -> str:
        return self.mw.sql_formatter.format(sql_string)

    def _preview_row_limit(self) -> int:
        """Return the user-configured row cap for preview-style queries.

        ``0`` (or any non-positive value) means no cap — callers must skip
        emitting a ``LIMIT`` clause in that case.
        """
        try:
            return int(self.mw.settings_manager.get('preview_row_limit', 1000))
        except (TypeError, ValueError):
            return 1000

    @staticmethod
    def _sanitize_snippet_name(name: str) -> str:
        """Return a filesystem-safe snippet name."""
        return "".join(
            character for character in name if character.isalnum() or character in (' ', '_', '-')
        ).strip()

    # --- QUERY EXECUTION ---
    def execute_query(self) -> None:
        """Execute the selected or full SQL text from the active editor."""
        editor = self.mw.query_panel.get_active_editor()
        if not editor or not getattr(editor, 'connection_key', None): 
            return
        cursor = editor.textCursor()
        query = cursor.selectedText().replace('\u2029', '\n') if cursor.hasSelection() else editor.toPlainText()
        editor.last_executed_query = query 
        self.mw.query_controller.execute_query(editor, query, editor.connection_key)

    def stop_query(self) -> None:
        """Request cancellation of the currently running query."""
        self.mw.query_controller.stop_query()

    def copy_query_as_python_script(self) -> None:
        """Copy a self-contained DuckDB Python reproducer for the active editor's last query."""
        status = self.mw.results_panel.status_message_label
        editor = self.mw.query_panel.get_active_editor()
        if not editor:
            status.setText("No active query tab.")
            return

        query = (getattr(editor, 'last_executed_query', '') or '').strip()
        if not query:
            status.setText("Run a query first, then copy it as Python.")
            return

        conn_key = getattr(editor, 'connection_key', None)
        if conn_key and conn_key.startswith("databricks_"):
            status.setText("Copy as Python is not yet supported for Databricks connections.")
            return

        engine = self.mw.conn_manager.get_db(conn_key) if conn_key else None
        if engine is None:
            status.setText("This editor has no active connection.")
            return

        script = self._build_python_reproducer(engine, query, conn_key or "")
        QApplication.clipboard().setText(script)
        status.setText("Copied query as Python script.")

    @staticmethod
    def _build_python_reproducer(engine: Any, query: str, conn_key: str) -> str:
        """Return a self-contained Python script that reproduces ``query`` against ``engine``."""
        is_temp = bool(getattr(engine, 'is_temp_db', False))
        if is_temp:
            connect_arg = '":memory:"'
            note = (
                "# NOTE: this script connects to a fresh in-memory DuckDB. Any session-only\n"
                "# state from FlatSQL Studio (CREATE TABLE, ATTACH, registered views) is not\n"
                "# replayed here — adapt the script if your query depends on it.\n"
            )
        else:
            connect_arg = 'r"' + str(getattr(engine, 'db_name', '')) + '"'
            note = ""

        safe_query = query.replace('"""', '\\"\\"\\"')
        timestamp = _dt.datetime.now().isoformat(timespec='seconds')

        return (
            '"""FlatSQL Studio - reproducer script.\n\n'
            f'Generated: {timestamp}\n'
            f'Connection: {conn_key}\n'
            '"""\n'
            f'{note}'
            'import duckdb\n\n'
            f'con = duckdb.connect({connect_arg})\n\n'
            'query = """\\\n'
            f'{safe_query}\n'
            '"""\n\n'
            'result = con.sql(query)\n'
            'print(result.pl())  # use .df() for pandas, .arrow() for Arrow, .fetchall() for tuples\n'
        )

    def open_new_query_for_connection(self, connection_key: str) -> None:
        """Open a blank query tab already bound to the selected connection."""
        if not connection_key:
            return
        self.mw.query_panel.add_new_tab(connection_key=connection_key)

    def explain_current_query(self) -> None:
        """Generate and run an EXPLAIN statement for the active query text."""
        editor = self.mw.query_panel.get_active_editor()
        if not editor: return
        cursor = editor.textCursor()
        query = cursor.selectedText() if cursor.hasSelection() else editor.toPlainText()
        if not query.strip(): 
            self.mw.results_panel.status_message_label.setText("No query text to explain.")
            return
        explain_query = f"EXPLAIN {query}"
        self.mw.query_panel.add_new_tab(content=explain_query, tab_name="Explain Plan")
        self.execute_query()

    def show_history_dialog(self) -> None:
        """Open query history and optionally script the history table query."""
        dialog = HistoryDialog(self.mw.theme_colors, self.mw.settings_manager, self.mw.history_manager, self.mw.db_keywords, self.mw.db_functions, self.mw)
        if dialog.exec() == QDialog.Accepted:
            if getattr(dialog, 'wants_query_table', False):
                db_path = self.mw.history_manager.db_path
                if db_path not in self.mw.conn_manager.db_connections:
                    self.mw.conn_manager.add_db_connection(db_path)
                limit = self._preview_row_limit()
                limit_clause = f"\nLIMIT {limit}" if limit > 0 else ""
                query = (
                    "SELECT\n    \"timestamp\",\n    \"duration\",\n    \"rows\",\n    \"query\"\n"
                    f"FROM \"flatsql\".\"query_history\"\nORDER BY \"timestamp\" DESC{limit_clause};"
                )
                self.mw.query_panel.add_new_tab(content=query, tab_name="History Table", connection_key=db_path)
                self.execute_query()
            else:
                selected_query = dialog.get_selected_query()
                if selected_query:
                    self.mw.query_panel.add_new_tab(content=selected_query, tab_name="History Query")

    def save_as_snippet(self, index: int) -> None:
        """Persist query text from a tab as a snippet file."""
        editor = self.mw.query_tabs.widget(index)
        if not editor: return
        query_text = editor.toPlainText().strip()
        if not query_text:
            QMessageBox.warning(self.mw, "Empty Snippet", "Cannot save an empty query as a snippet.")
            return

        existing_path = getattr(editor, 'snippet_file_path', None)
        if existing_path:
            try:
                with open(existing_path, 'w', encoding='utf-8') as snippet_file:
                    snippet_file.write(query_text)
                if hasattr(self.mw, 'snippet_panel'):
                    self.mw.snippet_panel.refresh()
                snippet_name = os.path.splitext(os.path.basename(existing_path))[0]
                self.mw.results_panel.status_message_label.setText(f"Snippet '{snippet_name}' saved.")
            except OSError as e:
                QMessageBox.critical(self.mw, "Error", f"Failed to save snippet:\n{e}")
            return

        default_name = self._sanitize_snippet_name(getattr(editor, 'full_tab_name', ''))
        snippet_name, ok = QInputDialog.getText(
            self.mw,
            "Save Snippet",
            "Enter Snippet Name:",
            text=default_name,
        )
        if not ok or not snippet_name:
            return

        safe_name = self._sanitize_snippet_name(snippet_name)
        if not safe_name:
            QMessageBox.warning(self.mw, "Invalid Name", "Please enter a valid snippet name.")
            return

        target_dir = SNIPPETS_DIR
        if hasattr(self.mw, 'snippet_panel'):
            target_dir = self.mw.snippet_panel.get_selected_directory()

        file_path = os.path.join(target_dir, f"{safe_name}.sql")
        if os.path.exists(file_path):
            reply = QMessageBox.question(
                self.mw,
                "Overwrite Snippet",
                f"The snippet '{safe_name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            with open(file_path, 'w', encoding='utf-8') as snippet_file:
                snippet_file.write(query_text)
            editor.snippet_file_path = file_path
            editor.full_tab_name = safe_name
            self.mw.query_tabs.setTabText(index, safe_name)
            self.mw.query_tabs.setTabToolTip(index, safe_name)
            if hasattr(self.mw, 'snippet_panel'):
                self.mw.snippet_panel.refresh()
            self.mw.results_panel.status_message_label.setText(f"Snippet '{safe_name}' saved.")
        except OSError as e:
            QMessageBox.critical(self.mw, "Error", f"Failed to save snippet:\n{e}")

    # --- DATABASE EXPLORER ACTIONS ---
    def handle_db_script_select(self, object_name_full: str, connection_key: str) -> None:
        """Generate a SELECT TOP script for a chosen database object."""
        engine = self.mw.conn_manager.get_db(connection_key)
        if not engine or '.' not in object_name_full: return
        
        parts = object_name_full.split('.')
        if len(parts) == 3:
            catalog, schema, name = parts
            from_clause = f'"{catalog}"."{schema}"."{name}"'
        else:
            schema, name = parts
            if connection_key and connection_key.startswith("databricks_"):
                catalog = connection_key.replace("databricks_", "")
                from_clause = f'"{catalog}"."{schema}"."{name}"'
            else:
                from_clause = f'"{schema}"."{name}"'
        
        cols_with_types = engine.get_columns_for_object(schema, name)
        columns = [col[0] for col in cols_with_types]

        query_raw = SQLGenerator.generate_select_top(columns, from_clause, self._preview_row_limit())
        query = self.format_sql_string(query_raw)
        
        self.mw.query_panel.add_new_tab(content=query, tab_name=f"SELECT_{name}", connection_key=connection_key)
        self.execute_query()

    def handle_db_script_ddl(
        self,
        object_name_full: str,
        object_type: str,
        script_type: str,
        connection_key: str,
    ) -> None:
        """Generate DDL script text for a selected database object."""
        engine = self.mw.conn_manager.get_db(connection_key)
        if engine:
            self.script_object(object_name_full, object_type, script_type, engine, connection_key)

    def script_object(
        self,
        full_object_name: str,
        object_type: str,
        script_type: str,
        engine: Any,
        connection_key: str,
    ) -> None:
        """Open a tab and populate it with scripted object DDL."""
        if '.' not in full_object_name or not engine: return
        schema_name, object_name = full_object_name.split('.', 1)
        tab_name = f"{script_type}_{object_name}"

        self.mw.query_panel.add_new_tab(content="-- GENERATING SQL...", tab_name=tab_name, connection_key=connection_key)
        editor = self.mw.query_panel.get_active_editor()
        QApplication.processEvents()

        ddl = engine.get_ddl_for_object(schema_name, object_name, object_type, script_type)
        formatted_ddl = self.format_sql_string(ddl)
        if editor: editor.setPlainText(formatted_ddl)

    # --- FILE EXPLORER ACTIONS ---
    def show_split_dialog(self, file_path: str, file_name: str) -> None:
        """Open split-file options and script the resulting SQL."""
        connection_key = None
        active_editor = self.mw.query_panel.get_active_editor()
        if isinstance(active_editor, QueryTextEdit) and getattr(active_editor, 'connection_key', None):
            connection_key = active_editor.connection_key
        elif ":memory:" in self.mw.conn_manager.db_connections:
            connection_key = ":memory:"
            
        if not connection_key:
            QMessageBox.warning(self.mw, "No Connection", "An active connection is required to read the file schema.")
            return

        engine = self.mw.conn_manager.db_connections[connection_key]
        dialog = SplitFileDialog(file_path, engine, self.mw)
        if dialog.exec() == QDialog.Accepted:
            details = dialog.get_details()
            query = SQLGenerator.generate_split_script(file_path, details)
            formatted = self.format_sql_string(query)
            self.mw.query_panel.add_new_tab(content=formatted, tab_name=f"Split_{os.path.basename(file_path)}")

    def show_merge_dialog(self, folder_path: str, folder_name: str) -> None:
        """Open merge-file options and script the resulting SQL."""
        dialog = MergeFilesDialog(folder_path, self.mw)
        if dialog.exec() == QDialog.Accepted:
            details = dialog.get_details()
            query = SQLGenerator.generate_merge_script(folder_path, details)
            formatted = self.format_sql_string(query)
            self.mw.query_panel.add_new_tab(content=formatted, tab_name=f"Merge_{os.path.basename(folder_path)}")

    def handle_file_conversion(self, source_path: str, target_format_key: str) -> None:
        """Script and execute conversion from a source file to target format."""
        target_info = SQLGenerator.CONVERSION_FORMATS.get(target_format_key)
        if not target_info:
            QMessageBox.critical(self.mw, "Error", f"Unknown format key: {target_format_key}")
            return
        source_dir = os.path.dirname(source_path)
        source_basename = os.path.basename(source_path)
        source_name_no_ext = os.path.splitext(source_basename)[0]
        suggested_filename = os.path.join(source_dir, source_name_no_ext)
        save_path, _ = QFileDialog.getSaveFileName(
            self.mw, f"Convert and Save as {target_info['label']}", suggested_filename, target_info['label']
        )
        if not save_path: return
        query = SQLGenerator.generate_conversion_script(source_path, save_path, target_format_key)
        formatted_query = self.format_sql_string(query)
        self.mw.query_panel.add_new_tab(content=formatted_query, tab_name=f"Convert_{source_basename}")
        self.execute_query()

    def create_table_from_file(self, file_path: str, file_name: str) -> None:
        """Open a CREATE TABLE script for the selected file."""
        query = SQLGenerator.generate_create_table(file_path, file_name)
        self.mw.query_panel.add_new_tab(content=query, tab_name=f"CreateTable_{file_name}")

    def create_view_from_file(self, file_path: str, file_name: str) -> None:
        """Open a CREATE VIEW script for the selected file."""
        query = SQLGenerator.generate_create_view(file_path, file_name)
        self.mw.query_panel.add_new_tab(content=query, tab_name=f"CreateView_{file_name}")

    def script_and_open_flattened_select(self, file_path: str, file_name: str) -> None:
        """Generate and run a flattened SELECT for nested file structures."""
        active_editor = self.mw.query_panel.get_active_editor()
        if not active_editor or not getattr(active_editor, 'connection_key', None):
            QMessageBox.warning(self.mw, "No Connection", "Cannot generate script without an active connection.")
            return
        engine = self.mw.conn_manager.get_db(active_editor.connection_key)
        if not engine:
            QMessageBox.critical(self.mw, "Connection Error", "The active connection is invalid.")
            return
        tab_name = f"Flattened_{file_name}"
        self.mw.query_panel.add_new_tab(content="-- GENERATING SQL...", tab_name=tab_name, connection_key=active_editor.connection_key)
        editor = self.mw.query_panel.get_active_editor()
        QApplication.processEvents()

        schema = engine.get_schema_for_file(file_path)
        if not schema:
            if editor: editor.setPlainText("-- Error: Could not determine schema.")
            QMessageBox.warning(self.mw, "Schema Error", f"Could not determine the schema for {file_name}.")
            return
        query = SQLGenerator.generate_flattened_select(schema, file_path, self._preview_row_limit())
        formatted_query = self.format_sql_string(query)
        if editor: editor.setPlainText(formatted_query)
        self.execute_query()

    def script_and_open_select(self, object_identifier: str, tab_name_prefix: str, is_file: bool = False) -> None:
        """Generate and run a SELECT script for either a file or DB object."""
        columns = []
        from_clause = ""
        connection_key = None

        active_editor = self.mw.query_panel.get_active_editor()
        if isinstance(active_editor, QueryTextEdit) and getattr(active_editor, 'connection_key', None):
            connection_key = active_editor.connection_key
        elif ":memory:" in self.mw.conn_manager.db_connections:
            connection_key = ":memory:"

        if not connection_key:
            QMessageBox.warning(self.mw, "No Connection", "Cannot generate script without an active connection.")
            return

        engine = self.mw.conn_manager.get_db(connection_key)
        if not engine:
            QMessageBox.critical(self.mw, "Connection Error", "The active connection is invalid.")
            return

        tab_name = f"SELECT_{tab_name_prefix}"
        self.mw.query_panel.add_new_tab(content="-- GENERATING SQL...", tab_name=tab_name, connection_key=connection_key)
        editor = self.mw.query_panel.get_active_editor()
        QApplication.processEvents()

        if is_file:
            columns = engine.get_columns_for_file(object_identifier)
            from_clause = to_duckdb_relation(object_identifier)
        else:
            if '.' in object_identifier:
                schema_name, object_name = object_identifier.split('.', 1)
                cols_with_types = engine.get_columns_for_object(schema_name, object_name)
                columns = [col[0] for col in cols_with_types]
                from_clause = f'"{schema_name}"."{object_name}"'

        query = SQLGenerator.generate_select_top(columns, from_clause, self._preview_row_limit())
        formatted_query = self.format_sql_string(query)

        if editor: editor.setPlainText(formatted_query)
        self.execute_query()

    def create_and_run_query_for_file(
        self,
        file_path: str,
        file_name: str,
        query_template: str,
        tab_name_template: str,
    ) -> None:
        """Render a file query from templates, open it in a tab, and execute it."""
        if not file_path: return
        file_path_sql = to_duckdb_path(file_path)
        file_relation = to_duckdb_relation(file_path)
        query = query_template.format(file_path=file_path_sql, file_relation=file_relation)
        tab_name = tab_name_template.format(file_name=file_name)
        self.mw.query_panel.add_new_tab(content=query, tab_name=tab_name)
        self.execute_query()

    def handle_file_drop(self, file_path: str) -> None:
        """Handle SQL-file drops directly or script a SELECT for data files."""
        resolved_path = self.mw.file_explorer_panel._convert_to_abfs_path(file_path)
        file_name = os.path.basename(resolved_path)

        if os.path.isfile(file_path) and file_path.lower().endswith('.sql'):
            try:
                with open(file_path, 'r', encoding='utf-8') as f: 
                    query_text = f.read()
                self.mw.query_panel.add_new_tab(content=query_text, tab_name=file_name)
            except Exception as e:
                QMessageBox.critical(self.mw, "Error Opening SQL File", f"Could not read file:\n{e}")
        else:
            self.script_and_open_select(resolved_path, file_name, is_file=True)

    def select_from_folder(self, folder_path: str, folder_name: str, wildcard: str) -> None:
        """Create and run a wildcard SELECT for all matching files in a folder."""
        folder_sql = to_duckdb_path(folder_path)
        # Azure/ABFS paths do not support recursive globs in DuckDB's Azure extension.
        if folder_sql.startswith(("az://", "abfss://")):
            full_path_glob = f"{folder_sql}/{wildcard}"
        else:
            full_path_glob = f"{folder_sql}/**/{wildcard}"
        limit = self._preview_row_limit()
        limit_clause = f" LIMIT {limit}" if limit > 0 else ""
        self.create_and_run_query_for_file(
            full_path_glob,
            folder_name,
            "SELECT * FROM {file_relation}" + limit_clause + ";",
            "{file_name}",
        )

    def show_schema(self, fp: str, fn: str) -> None:
        """Run a DESCRIBE query for a selected file."""
        self.create_and_run_query_for_file(fp, fn, "DESCRIBE SELECT * FROM {file_relation};", "Schema: {file_name}")
        
    def show_statistics(self, fp: str, fn: str) -> None:
        """Run a SUMMARIZE query for a selected file."""
        self.create_and_run_query_for_file(fp, fn, "SUMMARIZE SELECT * FROM {file_relation};", "Stats: {file_name}")

    def copy_as_path(self, fp: str | None) -> None:
        """Copy a file path to the system clipboard when available."""
        if fp: QApplication.clipboard().setText(fp)

    def show_export_dialog(self) -> None:
        """Open the export dialog for the active tab results."""
        active_editor = self.mw.query_panel.get_active_editor()
        if active_editor and getattr(active_editor, 'results_df', None) is not None and not active_editor.results_df.is_empty():
            default_format = self.mw.settings_manager.get('default_export_format', 'csv')
            dialog = ExportDialog(SQLGenerator.CONVERSION_FORMATS, default_format, self.mw.settings_manager, self.mw)

            if dialog.exec() == QDialog.Accepted:
                options = dialog.get_options()
                self.save_results_as(options)
        else:
            QMessageBox.warning(self.mw, "No Results", "There are no results in the current tab to export.")

    def save_results_as(self, options: dict[str, Any]) -> None:
        """Persist current results dataframe using export options."""
        active_editor = self.mw.query_panel.get_active_editor()
        if active_editor is None or getattr(active_editor, 'results_df', None) is None: return

        format_type = options.get('format')
        delimiter = options.get('delimiter', ',')
        has_header = options.get('header', True)
        comp = options.get('compression')

        base_ext = f".{format_type}"
        comp_ext = ""
        
        if comp and comp not in ["None", "uncompressed", "snappy"]:
            comp_ext = f".{comp}" if comp != "gzip" else ".gz"

        full_ext = f"{base_ext}{comp_ext}"

        file_filter = f"{format_type.upper()} Files (*{full_ext});;All Files (*)"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self.mw, f"Save Results as {format_type.upper()}", "export", file_filter
        )
        
        if file_path:
            while file_path.endswith(full_ext + full_ext):
                file_path = file_path[:-len(full_ext)]

            if not file_path.endswith(full_ext):
                if file_path.endswith(comp_ext):
                    file_path = file_path[:-len(comp_ext)]
                elif file_path.endswith(base_ext):
                    file_path = file_path[:-len(base_ext)]

                file_path += full_ext

            try:
                df = active_editor.results_df

                if format_type == 'csv':
                    csv_kwargs = {
                        "separator": delimiter,
                        "include_header": has_header
                    }
                    if comp and comp not in ["None", "", "uncompressed"]:
                        csv_kwargs["compression"] = comp
                        
                    df.write_csv(file_path, **csv_kwargs)
                
                elif format_type == 'parquet':
                    pq_comp = "snappy" if not comp or comp in ["None", ""] else comp
                    df.write_parquet(file_path, compression=pq_comp)
                
                else:
                    DataExporter.export(df, file_path, format_type, delimiter=delimiter, header=has_header)

                self.mw.results_panel.status_message_label.setText(f"Saved to {os.path.basename(file_path)}")
                QMessageBox.information(self.mw, "Save Successful", f"Results saved to:\n{file_path}")
                
            except Exception as e:
                QMessageBox.critical(self.mw, "Error Saving File", f"Could not save file:\n{e}")


    def show_add_db_connection_dialog(self) -> None:
        """Show a selector dialog for database connection type."""
        dialog = AddDatabaseConnectionDialog(self.mw)

        if dialog.exec() != QDialog.Accepted or not dialog.selected_connection_type:
            return

        connection_type = dialog.selected_connection_type

        if connection_type == "duckdb_existing":
            path, _ = QFileDialog.getOpenFileName(
                self.mw,
                "Select DuckDB File",
                "",
                "DuckDB Files (*.duckdb *.db)",
            )
            if path:
                self.mw.conn_manager.add_db_connection(path)
        elif connection_type == "duckdb_new":
            path, _ = QFileDialog.getSaveFileName(
                self.mw,
                "Create New DuckDB File",
                "",
                "DuckDB Files (*.duckdb *.db)",
            )
            if path:
                self.mw.conn_manager.add_db_connection(path)
        elif connection_type == "databricks":
            self.connect_to_unity_catalog()

    def connect_to_unity_catalog(self) -> None:
        """Open Databricks credentials dialog and create a UC connection."""
        uc_dialog = UnityCatalogDialog(self.mw)
        
        if uc_dialog.exec() == QDialog.Accepted:
            creds = uc_dialog.get_credentials()
            endpoint, token, catalog = creds['endpoint'], creds['token'], creds['catalog']

            if not endpoint or not token or not catalog:
                QMessageBox.warning(self.mw, "Input Error", "All fields are required to connect to Databricks.")
                return

            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.mw.conn_manager.add_databricks_connection(catalog, endpoint, token)
                self.mw.results_panel.status_message_label.setText(f"Connected to Unity Catalog: {catalog}")
                QMessageBox.information(self.mw, "Success", f"Successfully connected to Unity Catalog '{catalog}'.")
            except Exception as e:
                QMessageBox.critical(self.mw, "Databricks Error", str(e))
            finally:
                QApplication.restoreOverrideCursor()

    def show_add_file_connection_dialog(self) -> None:
        """Show file-connector selection dialog and dispatch connection flow."""
        dialog = AddFileConnectionDialog(self.mw)
        
        if dialog.exec() == QDialog.Accepted and dialog.selected_connector_type:
            conn_type = dialog.selected_connector_type
            
            if conn_type == "azure_v2":
                self.add_azure_connection()

    def add_azure_connection(self) -> None:
        """Open Azure authentication flow and register an Azure connector."""
        dialog = AzureConnectionDialog(self.mw.conn_manager, self.mw)
        
        if dialog.exec() == QDialog.Accepted:
            details = dialog.get_connection_details()
            
            if details["name"] in self.mw.conn_manager.fs_connections:
                QMessageBox.warning(self.mw, "Duplicate Name", f"A connection named '{details['name']}' already exists.")
                return
                
            self.mw.conn_manager.add_azure_connection(
                details["name"], 
                details["tenant_id"], 
                details["user_name"], 
                details["auth_record"],
                details["connector"],
            )

    def show_settings_dialog(self) -> None:
        """Open settings dialog, apply updates, and handle theme preview rollback."""
        available_themes = ThemeManager.discover_themes()
        current_settings_dict = self.mw.settings_manager._settings
        original_theme = self.mw.settings_manager.get('theme', 'dark.json')
        
        dialog = SettingsDialog(current_settings_dict, available_themes, SQLGenerator.CONVERSION_FORMATS, self.mw)
        dialog.theme_preview_requested.connect(self.mw._apply_theme)

        if dialog.exec() == QDialog.Accepted:
            new_settings = dialog.get_settings()
            old_font_size = self.mw.settings_manager.get('font_size')
            old_shortcut = self.mw.settings_manager.get('run_query_shortcut')
            old_theme = self.mw.settings_manager.get('theme', 'dark.json')

            self.mw.settings_manager.update(new_settings)
            self.mw.settings_manager.save()

            if new_settings['font_size'] != old_font_size:
                self.mw.query_panel.apply_font_size_to_all_editors(new_settings['font_size'])

            if new_settings['run_query_shortcut'] != old_shortcut:
                self.mw._update_run_query_shortcut()

            if new_settings['theme'] != old_theme:
                self.mw._apply_theme(new_settings['theme'])

            sqlfluff_path = write_user_sqlfluff_config(self.mw.settings_manager._settings)
            self.mw.sql_formatter.reload(sqlfluff_path)
        else:
            self.mw._apply_theme(original_theme)

    def show_duckdb_profiler(self) -> None:
        """Open the modeless DuckDB profiler dialog for the active connection."""
        from flatsql.ui.dialogs.profiler import DuckDBProfilerDialog

        active_editor = self.mw.query_panel.get_active_editor()
        conn_key = getattr(active_editor, 'connection_key', None) if active_editor else None

        if not conn_key and ":memory:" in self.mw.conn_manager.db_connections:
            conn_key = ":memory:"

        if not conn_key:
            QMessageBox.warning(self.mw, "No Connection", "No active connection to profile.")
            return

        engine = self.mw.conn_manager.get_db(conn_key)

        self.profiler_dialog = DuckDBProfilerDialog(engine, self.mw)
        self.profiler_dialog.show()

    def show_extensions_dialog(self) -> None:
        """Open the modeless DuckDB extension manager for the active connection."""
        from flatsql.ui.dialogs.extensions import ExtensionsDialog

        if not self.mw.conn_manager.db_connections:
            QMessageBox.warning(self.mw, "No Connection", "No active connection to manage extensions for.")
            return

        active_editor = self.mw.query_panel.get_active_editor()
        initial_key = getattr(active_editor, 'connection_key', None) if active_editor else None
        if initial_key not in self.mw.conn_manager.db_connections:
            initial_key = ":memory:" if ":memory:" in self.mw.conn_manager.db_connections else None

        existing = getattr(self, 'extensions_dialog', None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            if initial_key:
                existing.set_connection(initial_key)
            return

        self.extensions_dialog = ExtensionsDialog(
            self.mw.conn_manager,
            self.mw.extension_manager,
            initial_connection_key=initial_key,
            parent=self.mw,
        )
        self.extensions_dialog.show()

    def open_logs(self) -> None:
        """Open the FlatSQL Studio log file in the default text editor."""
        if os.path.exists(LOG_PATH):
            QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_PATH))
        else:
            QMessageBox.information(self.mw, "No Log File", f"Log file not found at {LOG_PATH}")

    def change_active_tab_connection(self, index: int) -> None:
        """Updates the active editor's connection when the user changes the dropdown."""
        active_editor = self.mw.query_panel.get_active_editor()
        if not active_editor: 
            return
        
        new_key = self.mw.db_explorer_panel.connection_combo.itemData(index)
        if new_key and getattr(active_editor, 'connection_key', None) != new_key:
            active_editor.connection_key = new_key
            self.mw.results_panel.display_results(active_editor)

    def handle_db_connections_changed(self) -> None:
        """Determines fallback connections when databases are added or removed."""
        if not self.mw.ui_initialized: 
            return
            
        valid_keys = list(self.mw.conn_manager.db_connections.keys())
        default_key = ":memory:" if ":memory:" in valid_keys else (valid_keys[0] if valid_keys else None)
        
        self.mw.query_panel.reassign_disconnected_tabs(valid_keys, default_key)
        self.handle_query_tab_changed(self.mw.query_tabs.currentIndex())

    def handle_query_tab_changed(self, index: int) -> None:
        """Syncs the DB explorer dropdown and Results panel when switching tabs."""
        editor = self.mw.query_tabs.widget(index)
        conn_key = getattr(editor, 'connection_key', None) if editor else None
        
        self.mw.db_explorer_panel.sync_connection_combo(conn_key)
        self.mw.results_panel.display_results(editor)

    def get_active_engine_for_file_explorer(self) -> Any:
        """Resolves the engine that the File Explorer should use for schema lookups."""
        active_editor = self.mw.query_panel.get_active_editor()
        if active_editor and getattr(active_editor, 'connection_key', None):
            return self.mw.conn_manager.get_db(active_editor.connection_key)
        return self.mw.conn_manager.get_db(":memory:")

    def save_session_and_cleanup(self) -> None:
        """Persists the session and gracefully closes background threads/connections."""
        if self.mw.settings_manager.get('restore_previous_session', True):
            self.mw.settings_manager.set('open_tabs', self.mw.query_panel.get_session_state())
        else:
            self.mw.settings_manager.set('open_tabs', [])
            
        self.mw.settings_manager.save()
        
        if hasattr(self.mw, 'query_controller'): 
            self.mw.query_controller.wait_for_completion()
        if hasattr(self.mw, 'conn_manager'): 
            self.mw.conn_manager.close_all()