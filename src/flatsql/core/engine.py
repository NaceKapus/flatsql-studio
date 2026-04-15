"""DuckDB engine wrapper used by FlatSQL Studio."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from typing import Any

import duckdb
import polars as pl

from flatsql.core.logger import get_logger
from flatsql.core.path_utils import to_duckdb_relation

logger = get_logger(__name__)


class FlatEngine:
    """Manage DuckDB connections and metadata queries for FlatSQL Studio."""

    _QUOTED_IDENTIFIER_PART = r'"(?:[^"]|"")+"'
    _UNQUOTED_IDENTIFIER_PART = r'[A-Za-z_][A-Za-z0-9_]*'
    _IDENTIFIER_PART = rf'(?:{_QUOTED_IDENTIFIER_PART}|{_UNQUOTED_IDENTIFIER_PART})'
    _QUALIFIED_IDENTIFIER = rf'{_IDENTIFIER_PART}(?:\s*\.\s*{_IDENTIFIER_PART})*'
    _SIMPLE_IDENTIFIER_PATTERN = re.compile(rf'^\s*(?P<name>{_QUALIFIED_IDENTIFIER})\s*$')
    _SIMPLE_ALIASED_IDENTIFIER_PATTERN = re.compile(
        rf'^\s*(?P<name>{_QUALIFIED_IDENTIFIER})\s+(?:AS\s+)?(?P<alias>{_IDENTIFIER_PART})\s*$',
        re.IGNORECASE,
    )

    def __init__(self, db_path: str | None = None, is_temp: bool = False) -> None:
        """Initialize a persistent or temporary DuckDB engine instance."""
        self.is_temp_db: bool = is_temp
        if self.is_temp_db:
            self.db_name = os.path.join(tempfile.gettempdir(), f"flatsql_session_{os.getpid()}.duckdb")
        else:
            if db_path is None:
                raise ValueError("A database file path must be provided for a non-temporary connection.")
            self.db_name = db_path

        self.main_con: duckdb.DuckDBPyConnection | None = duckdb.connect(database=self.db_name, read_only=False)
        self.worker_con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()
        self._autocomplete_install_attempted = False
        logger.info("Initialized DuckDB engine for %s.", self.db_name)

    def _ensure_autocomplete_loaded(self, connection: duckdb.DuckDBPyConnection) -> bool:
        """Load the DuckDB autocomplete extension on the provided connection."""
        try:
            connection.execute("LOAD autocomplete;")
            return True
        except Exception:
            logger.debug("DuckDB autocomplete extension not yet loaded.", exc_info=True)

        try:
            if not self._autocomplete_install_attempted:
                connection.execute("INSTALL autocomplete;")
                self._autocomplete_install_attempted = True
            connection.execute("LOAD autocomplete;")
            return True
        except Exception:
            logger.debug("DuckDB autocomplete extension is unavailable.", exc_info=True)
            return False

    def get_autocomplete_suggestions(self, sql_text: str, limit: int = 25) -> tuple[list[str], int]:
        """Return DuckDB autocomplete suggestions and the replacement start index."""
        query_text = sql_text or ""

        try:
            with self._lock:
                connection = duckdb.connect(database=self.db_name, read_only=False)

            try:
                if not self._ensure_autocomplete_loaded(connection):
                    return [], len(query_text)

                rows = connection.execute(
                    "SELECT suggestion, suggestion_start FROM sql_auto_complete(?) LIMIT ?",
                    [query_text, limit],
                ).fetchall()
            finally:
                connection.close()

            suggestions: list[str] = []
            seen: set[str] = set()
            replace_start = len(query_text)

            for suggestion, suggestion_start in rows:
                suggestion_text = str(suggestion or "")
                if not suggestion_text or suggestion_text in seen:
                    continue

                seen.add(suggestion_text)
                suggestions.append(suggestion_text)

                if isinstance(suggestion_start, int):
                    replace_start = max(0, suggestion_start)

            return suggestions, replace_start
        except Exception:
            logger.debug("Failed to fetch autocomplete suggestions.", exc_info=True)
            return [], len(query_text)

    def get_syntax_components(self) -> tuple[list[str], list[str]]:
        """Return syntax-highlighting keyword and function lists from DuckDB."""
        keywords: list[str] = []
        functions: list[str] = []
        try:
            keywords_df = self.main_con.execute("SELECT keyword_name FROM duckdb_keywords()").pl()
            keywords = keywords_df['keyword_name'].str.to_uppercase().unique().to_list()

            functions_df = self.main_con.execute("SELECT function_name FROM duckdb_functions()").pl()
            functions = functions_df['function_name'].str.to_uppercase().unique().to_list()

            if "IFNULL" not in functions:
                functions.append("IFNULL")
            if "ISNULL" in functions:
                functions.remove("ISNULL")
            if "COALESCE" not in functions:
                functions.append("COALESCE")
            if "COALESCE" in keywords:
                keywords.remove("COALESCE")

            # Window functions are parser-level syntax in DuckDB and never appear
            # in duckdb_functions(), so they must be registered manually.
            _window_functions = [
                "ROW_NUMBER", "RANK", "DENSE_RANK", "PERCENT_RANK", "CUME_DIST",
                "NTILE", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE", "NTH_VALUE",
            ]
            for _wf in _window_functions:
                if _wf not in functions:
                    functions.append(_wf)
                if _wf in keywords:
                    keywords.remove(_wf)
        except Exception:
            logger.exception("Failed to fetch DuckDB syntax components.")
            keywords = [
                "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "LIMIT",
                "CREATE", "TABLE", "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
            ]
            functions = ["COUNT", "SUM", "AVG", "MIN", "MAX"]

        return keywords, functions

    def get_schema_for_file(self, file_path: str) -> list[tuple[str, str]]:
        """Infer and return the full column schema for a file-backed dataset."""
        try:
            query = f"DESCRIBE SELECT * FROM {to_duckdb_relation(file_path)} LIMIT 0;"
            schema_df = self.main_con.execute(query).pl()
            return list(zip(schema_df['column_name'], schema_df['column_type']))
        except Exception:
            logger.exception("Failed to fetch schema for file %s.", file_path)
            return []

    def get_database_objects(self) -> dict[str, list[Any]]:
        """Return tables, views, system views, and user-defined functions from DuckDB metadata."""
        objects: dict[str, list[Any]] = {
            'tables': [],
            'views': [],
            'system_views': [],
            'functions': [],
        }
        try:
            tables_df = self.main_con.execute(
                "SELECT table_schema, table_name FROM INFORMATION_SCHEMA.TABLES WHERE table_type = 'BASE TABLE'"
            ).pl()
            objects['tables'] = list(zip(tables_df['table_schema'], tables_df['table_name']))

            views_df = self.main_con.execute(
                "SELECT table_schema, table_name, table_catalog FROM INFORMATION_SCHEMA.VIEWS"
            ).pl()
            for row in views_df.iter_rows(named=True):
                item = (row['table_schema'], row['table_name'])
                if row['table_catalog'] == 'system':
                    objects['system_views'].append(item)
                else:
                    objects['views'].append(item)
        except Exception:
            logger.exception("Failed to fetch database objects for %s.", self.db_name)

        try:
            funcs_df = self.main_con.execute(
                "SELECT DISTINCT function_name, function_type "
                "FROM duckdb_functions() "
                "WHERE internal = false "
                "ORDER BY function_name"
            ).pl()
            objects['functions'] = list(zip(funcs_df['function_name'], funcs_df['function_type']))
        except Exception:
            logger.exception("Failed to fetch user-defined functions for %s.", self.db_name)

        return objects

    def get_constraints_for_table(self, schema_name: str, table_name: str) -> list[tuple[str, str]]:
        """Return constraint type and affected columns for a table.

        Args:
            schema_name: Schema the table belongs to.
            table_name: Name of the table.

        Returns:
            List of (constraint_type, columns_display) tuples.
        """
        try:
            result = self.main_con.execute(
                "SELECT constraint_type, constraint_column_names "
                "FROM duckdb_constraints() "
                f"WHERE schema_name = '{schema_name}' AND table_name = '{table_name}'"
            ).pl()
            constraints: list[tuple[str, str]] = []
            for row in result.iter_rows(named=True):
                cols = ", ".join(row['constraint_column_names'] or [])
                display = f"({cols})" if cols else ""
                constraints.append((row['constraint_type'], display))
            return constraints
        except Exception:
            logger.exception("Failed to fetch constraints for %s.%s.", schema_name, table_name)
            return []

    def get_columns_for_object(self, schema_name: str, object_name: str) -> list[tuple[str, str]]:
        """Return column names and types for a table or view."""
        try:
            query = f'DESCRIBE "{schema_name}"."{object_name}";'
            columns_df = self.main_con.execute(query).pl()
            return list(zip(columns_df['column_name'], columns_df['column_type']))
        except Exception:
            logger.exception("Failed to fetch columns for %s.%s.", schema_name, object_name)
            return []

    @classmethod
    def _quote_identifier_part(cls, identifier_part: str) -> str:
        """Return a single identifier part wrapped in double quotes.

        Args:
            identifier_part: One schema/table/column identifier component.

        Returns:
            The identifier part in DuckDB double-quoted form.
        """
        cleaned_part = identifier_part.strip()
        if cleaned_part.startswith('"') and cleaned_part.endswith('"'):
            return cleaned_part
        escaped_part = cleaned_part.replace('"', '""')
        return f'"{escaped_part}"'

    @classmethod
    def _quote_qualified_identifier(cls, identifier: str) -> str:
        """Return a dotted identifier with each part quoted.

        Args:
            identifier: One or more identifier parts separated by dots.

        Returns:
            Identifier with all parts quoted.
        """
        parts = [part.strip() for part in identifier.split('.')]
        return '.'.join(cls._quote_identifier_part(part) for part in parts if part.strip())

    @staticmethod
    def _split_top_level_csv(select_list: str) -> list[str]:
        """Split a SELECT list on commas while respecting nesting and quotes."""
        items: list[str] = []
        current: list[str] = []
        paren_depth = 0
        single_quote = False
        double_quote = False

        for character in select_list:
            if character == "'" and not double_quote:
                single_quote = not single_quote
            elif character == '"' and not single_quote:
                double_quote = not double_quote
            elif not single_quote and not double_quote:
                if character == '(':
                    paren_depth += 1
                elif character == ')' and paren_depth > 0:
                    paren_depth -= 1
                elif character == ',' and paren_depth == 0:
                    items.append(''.join(current).strip())
                    current = []
                    continue

            current.append(character)

        if current:
            items.append(''.join(current).strip())

        return [item for item in items if item]

    @staticmethod
    def _find_top_level_keyword(sql: str, keyword: str, start: int = 0) -> int:
        """Find a top-level SQL keyword, ignoring strings, quotes, and nesting."""
        keyword_upper = keyword.upper()
        paren_depth = 0
        single_quote = False
        double_quote = False
        index = start
        sql_upper = sql.upper()
        keyword_length = len(keyword)

        while index <= len(sql) - keyword_length:
            character = sql[index]
            if character == "'" and not double_quote:
                single_quote = not single_quote
                index += 1
                continue
            if character == '"' and not single_quote:
                double_quote = not double_quote
                index += 1
                continue

            if not single_quote and not double_quote:
                if character == '(':
                    paren_depth += 1
                elif character == ')' and paren_depth > 0:
                    paren_depth -= 1
                elif paren_depth == 0 and sql_upper[index:index + keyword_length] == keyword_upper:
                    before_ok = index == 0 or not (sql_upper[index - 1].isalnum() or sql_upper[index - 1] == '_')
                    after_index = index + keyword_length
                    after_ok = after_index >= len(sql_upper) or not (sql_upper[after_index].isalnum() or sql_upper[after_index] == '_')
                    if before_ok and after_ok:
                        return index

            index += 1

        return -1

    @classmethod
    def _normalize_simple_projection(cls, projection: str) -> str:
        """Quote simple identifier projections while preserving complex expressions."""
        simple_match = cls._SIMPLE_IDENTIFIER_PATTERN.match(projection)
        if simple_match:
            return cls._quote_qualified_identifier(simple_match.group('name'))

        aliased_match = cls._SIMPLE_ALIASED_IDENTIFIER_PATTERN.match(projection)
        if aliased_match:
            name = cls._quote_qualified_identifier(aliased_match.group('name'))
            alias = cls._quote_identifier_part(aliased_match.group('alias'))
            return f'{name} AS {alias}'

        return projection.strip()

    @classmethod
    def _normalize_view_definition(cls, sql_definition: str) -> str:
        """Normalize simple view SELECT lists so identifiers are quoted consistently.

        The normalization is intentionally conservative: only top-level simple
        column projections are rewritten. Complex expressions are left intact.
        """
        select_index = cls._find_top_level_keyword(sql_definition, 'SELECT')
        if select_index == -1:
            return sql_definition

        from_index = cls._find_top_level_keyword(sql_definition, 'FROM', start=select_index + len('SELECT'))
        if from_index == -1:
            return sql_definition

        select_list = sql_definition[select_index + len('SELECT'):from_index]
        projections = cls._split_top_level_csv(select_list)
        if not projections:
            return sql_definition

        normalized_select_list = ',\n    '.join(cls._normalize_simple_projection(projection) for projection in projections)
        return (
            f"{sql_definition[:select_index + len('SELECT')]}\n"
            f"    {normalized_select_list}\n"
            f"{sql_definition[from_index:]}"
        )

    def get_ddl_for_object(
        self,
        schema_name: str,
        object_name: str,
        object_type: str,
        script_type: str = 'CREATE',
    ) -> str:
        """Generate DDL text for a DuckDB table or view."""
        full_name = f'"{schema_name}"."{object_name}"'
        drop_statement = f"DROP {object_type.upper()} IF EXISTS {full_name};"

        try:
            if script_type == 'DROP':
                return drop_statement

            create_statement = ""
            if object_type == 'VIEW':
                query = (
                    "SELECT sql FROM duckdb_views() "
                    f"WHERE schema_name = '{schema_name}' AND view_name = '{object_name}'"
                )
                sql_definition = self.main_con.execute(query).fetchone()[0]
                create_statement = self._normalize_view_definition(sql_definition.rstrip().rstrip(';')) + ";"

                if script_type == 'ALTER':
                    if 'CREATE OR REPLACE VIEW' in create_statement.upper():
                        return create_statement
                    return create_statement.replace('CREATE VIEW', 'CREATE OR REPLACE VIEW', 1)

            elif object_type == 'TABLE':
                columns = self.get_columns_for_object(schema_name, object_name)
                if not columns:
                    return f"-- Could not retrieve columns for table {full_name}"

                cols_str = ',\n  '.join([f'"{col_name}" {col_type}' for col_name, col_type in columns])
                create_statement = f'CREATE TABLE {full_name} (\n  {cols_str}\n);'

            if script_type == 'CREATE':
                return create_statement
            if script_type == 'DROP and CREATE':
                return f"{drop_statement}\n\n{create_statement}"
        except Exception as exc:
            logger.exception("Failed to generate %s DDL for %s.", object_type, full_name)
            return f"-- Error generating DDL for {object_type} {full_name}: {exc}"

        return f"-- DDL generation not supported for script type '{script_type}' on object type '{object_type}'."

    def get_columns_for_file(self, file_path: str) -> list[str]:
        """Infer and return column names for a file-backed dataset."""
        try:
            query = f"DESCRIBE SELECT * FROM {to_duckdb_relation(file_path)} LIMIT 0;"
            columns_df = self.main_con.execute(query).pl()
            return columns_df['column_name'].to_list()
        except Exception:
            logger.exception("Failed to fetch columns for file %s.", file_path)
            return []

    def _apply_runtime_settings(self, settings: dict[str, Any]) -> None:
        """Apply optional DuckDB runtime settings to the worker connection."""
        if not self.worker_con:
            return

        max_mem = settings.get('engine_max_memory')
        temp_dir = settings.get('engine_temp_dir')
        max_spill = settings.get('engine_max_spill_size')
        threads = settings.get('engine_threads')
        timezone = settings.get('engine_timezone')
        preserve_order = settings.get('engine_preserve_insertion_order')

        self._try_execute_setting(f"SET max_memory='{max_mem}';", bool(max_mem), 'max_memory')
        self._try_execute_setting(f"SET temp_directory='{temp_dir}';", bool(temp_dir), 'temp_directory')
        self._try_execute_setting(f"SET max_temp_directory_size='{max_spill}';", bool(max_spill), 'max_temp_directory_size')
        self._try_execute_setting(f"SET threads={threads};", bool(threads) and str(threads).isdigit(), 'threads')
        self._try_execute_setting(f"SET TimeZone='{timezone}';", bool(timezone), 'TimeZone')
        self._try_execute_setting(
            f"SET preserve_insertion_order={str(preserve_order).lower()};",
            preserve_order is not None,
            'preserve_insertion_order',
        )

    def _try_execute_setting(self, statement: str, should_run: bool, setting_name: str) -> None:
        """Attempt to apply a single DuckDB setting without interrupting execution."""
        if not should_run or not self.worker_con:
            return

        try:
            self.worker_con.execute(statement)
        except Exception:
            logger.debug("Ignored invalid DuckDB setting for %s.", setting_name, exc_info=True)

    def execute_query(
        self,
        query: str,
        settings: dict[str, Any] | None = None,
    ) -> tuple[pl.DataFrame | None, str | None]:
        """Execute a query on a worker connection and return data or an error string."""
        try:
            if not query.strip():
                return pl.DataFrame(), None

            with self._lock:
                self.worker_con = duckdb.connect(database=self.db_name, read_only=False)

            if settings:
                self._apply_runtime_settings(settings)

            result_df = self.worker_con.execute(query).pl()
            return result_df, None
        except Exception as exc:
            return None, str(exc)
        finally:
            with self._lock:
                if self.worker_con:
                    self.worker_con.close()
                    self.worker_con = None

    def interrupt_query(self) -> None:
        """Interrupt the currently running worker query, if present."""
        with self._lock:
            if self.worker_con:
                logger.info("Interrupting active query for %s.", self.db_name)
                self.worker_con.interrupt()

    def get_display_name(self) -> str:
        """Return a user-friendly name for the current database connection."""
        if self.is_temp_db:
            return ":memory:"
        return os.path.basename(self.db_name)

    def close(self) -> None:
        """Close open connections and remove temporary database files when used."""
        logger.info("Closing DuckDB connections for %s.", self.db_name)
        if self.main_con:
            self.main_con.close()
            self.main_con = None

        self.interrupt_query()

        if self.is_temp_db and os.path.exists(self.db_name):
            logger.info("Removing temporary database %s.", self.db_name)
            try:
                wal_file = f"{self.db_name}.wal"
                if os.path.exists(self.db_name):
                    os.remove(self.db_name)
                if os.path.exists(wal_file):
                    os.remove(wal_file)
            except OSError:
                logger.exception("Failed to remove temporary database files for %s.", self.db_name)

    def get_memory_usage(self) -> int:
        """Return the current DuckDB memory allocation in bytes."""
        try:
            cursor = self.main_con.cursor()
            result = cursor.execute("SELECT SUM(memory_usage_bytes) FROM duckdb_memory()").fetchone()
            cursor.close()
            if result:
                return result[0]
        except Exception:
            logger.debug("Failed to read DuckDB memory usage for %s.", self.db_name, exc_info=True)
        return 0