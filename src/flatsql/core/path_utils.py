"""Path helpers for SQL-safe, cross-platform path normalization."""

from __future__ import annotations

import os


_CSV_DELIMITER_BY_EXTENSION = {
    ".tsv": "\\t",
    ".tab": "\\t",
    ".psv": "|",
}

_JSON_READER_EXTENSIONS = {".jsonl", ".ndjson"}


def to_duckdb_path(path_value: str | os.PathLike[str]) -> str:
    """Normalize filesystem paths to DuckDB-friendly POSIX separators.

    DuckDB accepts forward-slash separators on all supported platforms.
    This keeps generated SQL paths portable and avoids Windows-only
    backslash literals in query strings.

    Args:
        path_value: A path-like value to normalize.

    Returns:
        Path string using forward slashes.
    """
    return os.fspath(path_value).replace("\\", "/")


def to_duckdb_relation(path_value: str | os.PathLike[str]) -> str:
    """Return a DuckDB relation expression for a file path or glob.

    Plain file paths can be referenced directly by DuckDB for the formats
    FlatSQL already supports. Some extension aliases need explicit reader
    functions so DuckDB interprets them correctly.

    Args:
        path_value: A path-like value or glob pattern to normalize.

    Returns:
        SQL relation expression suitable for a FROM clause.
    """
    normalized_path = to_duckdb_path(path_value)
    escaped_path = normalized_path.replace("'", "''")
    extension = os.path.splitext(normalized_path)[1].lower()

    if extension == ".txt":
        return f"read_text('{escaped_path}')"

    if extension in _JSON_READER_EXTENSIONS:
        return f"read_json_auto('{escaped_path}')"

    if extension in _CSV_DELIMITER_BY_EXTENSION:
        delimiter = _CSV_DELIMITER_BY_EXTENSION[extension]
        return f"read_csv_auto('{escaped_path}', delim='{delimiter}')"

    return f"'{escaped_path}'"
