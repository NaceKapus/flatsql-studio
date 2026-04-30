"""Helpers for generating SQL scripts used across the UI."""
from __future__ import annotations

import os

from flatsql.core.path_utils import to_duckdb_path, to_duckdb_relation


class SQLGenerator:
    """Service class responsible for generating SQL query strings."""

    CONVERSION_FORMATS = {
        "csv": {"label": "CSV (*.csv)", "format_sql": "CSV"},
        "parquet": {"label": "Parquet (*.parquet)", "format_sql": "PARQUET"},
        "json": {"label": "JSON (*.json)", "format_sql": "JSON"},
        "xlsx": {
            "label": "Excel (*.xlsx)",
            "format_sql": "GDAL",
            "driver_sql": ", DRIVER 'XLSX'",
        },
    }

    @staticmethod
    def generate_merge_script(folder_path: str, details: dict) -> str:
        """Generate a DuckDB COPY script that merges many files into one output."""
        folder_sql = to_duckdb_path(folder_path)
        source_ext = details["source_ext"]

        # Construct output path
        out_filename = details["out_name"]
        if not out_filename.endswith(details["out_ext"]):
            out_filename += details["out_ext"]

        out_full_path = f"{folder_sql}/{out_filename}"

        # Handle Recursion
        if details["recursive"]:
            glob_pattern = f"{folder_sql}/**/*.{source_ext}"
        else:
            glob_pattern = f"{folder_sql}/*.{source_ext}"

        union_opt = str(details["union_by_name"]).lower()

        # Generate read function
        if source_ext == "csv":
            read_func = f"read_csv_auto('{glob_pattern}', union_by_name={union_opt})"
        elif source_ext in {"tsv", "tab"}:
            read_func = f"read_csv_auto('{glob_pattern}', delim='\\t', union_by_name={union_opt})"
        elif source_ext == "psv":
            read_func = f"read_csv_auto('{glob_pattern}', delim='|', union_by_name={union_opt})"
        elif source_ext == "parquet":
            read_func = f"read_parquet('{glob_pattern}', union_by_name={union_opt})"
        elif source_ext == "txt":
            read_func = f"read_text('{glob_pattern}')"
        elif source_ext in {"json", "jsonl", "ndjson"}:
            read_func = f"read_json_auto('{glob_pattern}', union_by_name={union_opt})"
        else:
            read_func = f"'{glob_pattern}'"

        # Output format
        out_fmt_map = {".parquet": "PARQUET", ".csv": "CSV", ".json": "JSON"}
        out_fmt = out_fmt_map.get(details["out_ext"], "CSV")

        return (
            f"-- Merging files ({source_ext}) from: {os.path.basename(folder_path)}\n"
            f"-- Recursive: {details['recursive']}\n"
            f"COPY (\n"
            f"    SELECT * FROM {read_func}\n"
            f")\n"
            f"TO '{out_full_path}'\n"
            f"(FORMAT {out_fmt}, OVERWRITE_OR_IGNORE);"
        )

    @staticmethod
    def generate_split_script(source_path: str, details: dict) -> str:
        """Generate a DuckDB COPY script that partitions or chunks an input file."""
        source_relation = to_duckdb_relation(source_path)
        out_dir_sql = to_duckdb_path(details["out_dir"])
        fmt = details["format"].upper()

        if details["mode"] == "partition":
            # Simple Partition by Column
            col = details["partition_col"]
            return (
                f"COPY (SELECT * FROM {source_relation})\n"
                f"TO '{out_dir_sql}'\n"
                f"(FORMAT {fmt}, PARTITION_BY ({col}), OVERWRITE_OR_IGNORE);"
            )
        else:
            # Split by Row Count (Chunking)
            chunk_size = details["chunk_size"]
            return (
                f"-- Splitting file into chunks of {chunk_size:,} rows\n"
                f"COPY (\n"
                f"    SELECT \n"
                f"        *,\n"
                f"        floor((row_number() OVER () - 1) / {chunk_size}) AS file_chunk_id\n"
                f"    FROM {source_relation}\n"
                f")\n"
                f"TO '{out_dir_sql}'\n"
                f"(FORMAT {fmt}, PARTITION_BY (file_chunk_id), OVERWRITE_OR_IGNORE);"
            )

    @staticmethod
    def select_top_menu_label(limit: int, suffix: str = "") -> str:
        """Return the user-facing menu label for a Select-Top action.

        ``limit <= 0`` becomes "Select All Rows" since no cap is applied.
        ``suffix`` (e.g. " from Folder") is appended to the base label.
        """
        if limit and limit > 0:
            return f"Select Top {limit} Rows{suffix}"
        return f"Select All Rows{suffix}"

    @staticmethod
    def generate_select_top(column_list: list[str], from_clause: str, limit: int = 1000) -> str:
        """Generate a SELECT TOP-style query with optional quoted column list.

        ``limit <= 0`` omits the LIMIT clause entirely (no cap).
        """
        limit_clause = f"\nLIMIT {limit}" if limit and limit > 0 else ""
        if not column_list:
            return f"SELECT *\nFROM {from_clause}{limit_clause};"

        quoted_columns = [f'"{col}"' for col in column_list]
        columns_str = ",\n\t".join(quoted_columns)

        return (
            f"SELECT\n\t{columns_str}\n"
            f"FROM {from_clause}{limit_clause};"
        )

    @staticmethod
    def generate_flattened_select(
        schema: list[tuple[str, str]],
        file_path: str,
        limit: int = 1000,
    ) -> str:
        """Generate a query that recursively unnests STRUCT columns.

        Schema is expected to be a list of tuples (name, type).
        ``limit <= 0`` omits the LIMIT clause entirely (no cap).
        """
        column_expressions = []
        for name, col_type in schema:
            if "STRUCT" in col_type.upper():
                column_expressions.append(f'UNNEST("{name}", recursive := true) AS "{name}"')
            else:
                column_expressions.append(f'"{name}"')

        columns_str = ",\n\t".join(column_expressions)
        file_relation = to_duckdb_relation(file_path)
        limit_clause = f"\nLIMIT {limit}" if limit and limit > 0 else ""

        return (
            f"SELECT\n\t{columns_str}\n"
            f"FROM {file_relation}{limit_clause};"
        )

    @staticmethod
    def generate_conversion_script(source_path: str, save_path: str, target_format_key: str) -> str:
        """Generate a DuckDB COPY script that converts one file format to another."""
        target_info = SQLGenerator.CONVERSION_FORMATS.get(target_format_key)
        if not target_info:
            return f"-- Error: Unknown format {target_format_key}"

        source_relation = to_duckdb_relation(source_path)
        save_path_sql = to_duckdb_path(save_path)

        query_prefix = ""
        driver_option = target_info.get("driver_sql", "")

        if target_format_key == "xlsx":
            query_prefix = "INSTALL spatial; LOAD spatial;\n\n"

        format_option = target_info["format_sql"]

        return (
            f"{query_prefix}"
            f"COPY (\n"
            f"  SELECT * FROM {source_relation}\n"
            f") TO '{save_path_sql}'\n"
            f"WITH (FORMAT {format_option}{driver_option});"
        )

    @staticmethod
    def generate_create_table(file_path: str, file_name: str) -> str:
        """Generate a CREATE TABLE AS SELECT statement for a flat file."""
        table_name = os.path.splitext(file_name)[0].replace("-", "_").replace(" ", "_")
        file_relation = to_duckdb_relation(file_path)
        return f"CREATE TABLE {table_name} AS SELECT * FROM {file_relation};"

    @staticmethod
    def generate_create_view(file_path: str, file_name: str) -> str:
        """Generate a CREATE VIEW statement for a flat file."""
        base_name = os.path.splitext(file_name)[0].replace("-", "_").replace(" ", "_")
        view_name = f"vw_{base_name}"
        file_relation = to_duckdb_relation(file_path)
        return f"CREATE VIEW {view_name} AS SELECT * FROM {file_relation};"