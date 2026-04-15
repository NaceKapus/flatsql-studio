"""Data export helpers for writing Polars dataframes to disk."""
from __future__ import annotations

import polars as pl


class DataExporter:
    """Service class responsible for exporting dataframes to various file formats."""

    @staticmethod
    def export(
        df: pl.DataFrame,
        file_path: str,
        format_type: str,
        delimiter: str = ",",
        header: bool = True,
    ) -> None:
        """
        Exports the provided Polars DataFrame to the specified file path and format.

        Args:
            df: The Polars DataFrame to export.
            file_path: Destination file path.
            format_type: One of 'csv', 'json', 'parquet', 'xlsx'.
            delimiter: Separator character (only used for CSV).
            header: Boolean to include header (only used for CSV).

        Raises:
            ValueError: If an unsupported format_type is provided.
            Exception: Any underlying IO error from Polars.
        """
        if format_type == "csv":
            # Polars uses 'separator' argument for delimiter
            df.write_csv(file_path, separator=delimiter, include_header=header)

        elif format_type == "json":
            # Defaulting to row-oriented and pretty print as per original requirement
            df.write_json(file_path, row_oriented=True, pretty=True)

        elif format_type == "parquet":
            df.write_parquet(file_path)

        elif format_type == "xlsx":
            # Note: Requires xlsxwriter or openpyxl to be installed in the environment
            df.write_excel(file_path)

        else:
            raise ValueError(f"Unsupported export format: {format_type}")