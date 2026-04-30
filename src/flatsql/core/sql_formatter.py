"""SQL formatting support backed by SQLFluff."""

from __future__ import annotations

import configparser
import os
import re

import sqlfluff

from flatsql.core.logger import get_logger

logger = get_logger(__name__)

# SQLFluff's capitalisation.identifiers (CP02) rule only targets *unquoted*
# identifiers, so when the user asks us to wrap everything in double quotes
# we have to apply the configured case policy to pre-quoted identifiers
# ourselves. ``"((?:[^"]|"")*)"`` matches a DuckDB quoted identifier and
# tolerates the standard ``""`` escape for an embedded double quote.
_QUOTED_IDENT_RE = re.compile(r'"((?:[^"]|"")*)"')


class SQLFormatter:
    """Format SQL strings using a user-controlled SQLFluff config file.

    Uses the high-level ``sqlfluff.fix`` API rather than building a Linter
    manually — building one via ``Linter(config=FluffConfig.from_path(...))``
    silently skips the capitalisation rules, which is why we route through the
    simple API instead.

    SQLFluff's ``references.quoting`` (RF06) rule detects unquoted identifiers
    when ``prefer_quoted_identifiers = True`` but does **not** auto-fix them —
    its ``fixes`` list is empty. To honour that user preference we read the
    config flag and inject quotes ourselves after the standard fix pass, using
    the byte ranges from a follow-up ``sqlfluff.lint`` call.
    """

    def __init__(self, config_path: str):
        """Store the path to the SQLFluff config file."""
        self._config_path: str | None = None
        self._quote_identifiers: bool = False
        self._identifier_case: str = ""
        self._init_config(config_path)

    def _init_config(self, config_path: str) -> None:
        """Validate and store the config path, leaving formatting disabled if missing."""
        if config_path and os.path.exists(config_path):
            self._config_path = config_path
            parser = self._load_parser(config_path)
            self._quote_identifiers = self._read_quote_flag(parser)
            self._identifier_case = self._read_identifier_case(parser)
        else:
            self._config_path = None
            self._quote_identifiers = False
            self._identifier_case = ""
            logger.warning(
                "SQLFluff config not found at %s. Formatting disabled.", config_path
            )

    @staticmethod
    def _load_parser(config_path: str) -> configparser.ConfigParser:
        """Return a ConfigParser populated from the SQLFluff config, or empty on error."""
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
        except (configparser.Error, OSError):
            logger.exception("Failed to parse SQLFluff config at %s.", config_path)
        return parser

    @staticmethod
    def _read_quote_flag(parser: configparser.ConfigParser) -> bool:
        """Return the ``prefer_quoted_identifiers`` value from the user's config."""
        section = "sqlfluff:rules:references.quoting"
        if not parser.has_option(section, "prefer_quoted_identifiers"):
            return False
        return parser.getboolean(section, "prefer_quoted_identifiers", fallback=False)

    @staticmethod
    def _read_identifier_case(parser: configparser.ConfigParser) -> str:
        """Return the configured identifier case policy (``lower``, ``upper``, etc.)."""
        section = "sqlfluff:rules:capitalisation.identifiers"
        if not parser.has_option(section, "extended_capitalisation_policy"):
            return ""
        return parser.get(section, "extended_capitalisation_policy", fallback="").lower()

    def reload(self, config_path: str) -> None:
        """Switch to a new config file, e.g. after the user changes settings.

        SQLFluff caches loaded config files by path (``functools.cache`` on
        ``load_config_file_as_dict`` / ``load_config_at_path``), so if we
        rewrite the same file the next ``sqlfluff.fix`` call will silently see
        the stale config. Clear those caches before swapping the path in.
        """
        try:
            from sqlfluff.core.config.loader import (
                load_config_at_path,
                load_config_file_as_dict,
            )

            load_config_file_as_dict.cache_clear()
            load_config_at_path.cache_clear()
        except Exception:
            logger.exception("Failed to clear SQLFluff config cache.")
        self._init_config(config_path)

    def format(self, sql_string: str) -> str:
        """Return a formatted SQL string, or the original string on failure."""
        if not self._config_path or not sql_string or not sql_string.strip():
            return sql_string

        try:
            fixed = sqlfluff.fix(
                sql_string,
                dialect="duckdb",
                config_path=self._config_path,
            )
        except Exception:
            logger.exception("SQL auto-formatting failed.")
            return sql_string

        if not self._quote_identifiers:
            return fixed
        fixed = self._inject_identifier_quotes(fixed)
        return self._normalize_quoted_identifier_case(fixed)

    def _inject_identifier_quotes(self, sql: str) -> str:
        """Wrap each unquoted identifier reported by RF06 in double quotes."""
        try:
            violations = sqlfluff.lint(
                sql, dialect="duckdb", config_path=self._config_path
            )
        except Exception:
            logger.exception("SQL identifier-quote pass failed.")
            return sql

        targets = []
        for violation in violations:
            if violation.get("code") != "RF06":
                continue
            description = (violation.get("description") or "")
            if not description.startswith("Missing quoted identifier"):
                continue
            start = violation.get("start_file_pos")
            end = violation.get("end_file_pos")
            if start is None or end is None or end <= start:
                continue
            targets.append((int(start), int(end)))

        if not targets:
            return sql

        targets.sort(key=lambda r: r[0], reverse=True)
        for start, end in targets:
            sql = sql[:start] + '"' + sql[start:end] + '"' + sql[end:]
        return sql

    def _normalize_quoted_identifier_case(self, sql: str) -> str:
        """Apply the configured case policy to every double-quoted identifier."""
        case = self._identifier_case
        if case in ("", "consistent", "pascal"):
            # consistent has no normalised form; pascal is ambiguous on
            # already-quoted identifiers (snake_case word boundaries vs
            # arbitrary text), so we conservatively leave them as-is.
            return sql

        def transform(case_policy: str, body: str) -> str:
            if case_policy == "lower":
                return body.lower()
            if case_policy == "upper":
                return body.upper()
            if case_policy == "capitalise":
                return body.capitalize()
            return body

        return _QUOTED_IDENT_RE.sub(
            lambda m: '"' + transform(case, m.group(1)) + '"', sql
        )
