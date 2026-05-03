"""Path helpers for SQL-safe, cross-platform path normalization."""

from __future__ import annotations

import os
import re


_AZURE_FLATSQL_URI_PATTERN = re.compile(
    r'^(?P<scheme>abfss?|az)://(?P<account>[^/@]+)\.(?P<host>(?:dfs|blob)\.core\.windows\.net)/(?P<container>[^/]+)/(?P<blob>.*)$'
)


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
    FlatSQL Studio already supports. Some extension aliases need explicit reader
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


def _to_delta_kernel_uri(uri: str) -> str:
    """Rewrite Azure URLs into the ``container@account`` form expected by delta-kernel.

    DuckDB's delta extension uses delta-kernel + the Rust ``object_store`` crate,
    which parses Azure URLs as ``abfss://<container>@<account>.dfs.core.windows.net/<blob>``
    (and analogously for ``az://``). The Azure extension itself happily accepts
    ``abfss://<account>.dfs.core.windows.net/<container>/<blob>``, but the delta
    extension does not — passing the Azure-extension form to ``delta_scan`` raises
    ``URL did not match any known pattern for scheme: abfss://``.

    Non-Azure URIs (local paths, ``s3://``, ``https://``) are returned unchanged.
    """
    match = _AZURE_FLATSQL_URI_PATTERN.match(uri)
    if not match:
        return uri
    scheme = match.group("scheme")
    account = match.group("account")
    host = match.group("host")
    container = match.group("container")
    blob = match.group("blob")
    return f"{scheme}://{container}@{account}.{host}/{blob}"


def to_duckdb_delta_relation(path_value: str | os.PathLike[str], version: int | None = None) -> str:
    """Return a ``delta_scan(...)`` relation expression for a Delta table path.

    Args:
        path_value: Path to a Delta table directory (the directory containing
            ``_delta_log/``), local or remote (e.g. ``abfss://``, ``az://``).
        version: Optional Delta version for time-travel queries. When provided,
            emits ``delta_scan('path', version=N)``.

    Returns:
        SQL relation expression suitable for a FROM clause.
    """
    normalized_path = to_duckdb_path(path_value)
    delta_path = _to_delta_kernel_uri(normalized_path)
    escaped_path = delta_path.replace("'", "''")
    if version is not None:
        return f"delta_scan('{escaped_path}', version={int(version)})"
    return f"delta_scan('{escaped_path}')"
