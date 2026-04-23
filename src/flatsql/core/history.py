"""Query history persistence backed by DuckDB."""
from __future__ import annotations

import datetime

import duckdb

from flatsql.config import HISTORY_DB_PATH


class HistoryManager:
    """Manage storage and retrieval of executed query history."""

    def __init__(self) -> None:
        """Initialize the history database connection and schema."""
        self.db_path = HISTORY_DB_PATH
        self.con = duckdb.connect(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Creates the schema and history table if they don't exist."""
        # 1. Create the custom schema
        self.con.execute("CREATE SCHEMA IF NOT EXISTS flatsql;")

        # 2. Create the table inside the flatsql schema
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS flatsql.query_history (
                timestamp TIMESTAMP,
                query VARCHAR,
                duration DOUBLE,
                rows BIGINT
            )
        """)

    def add_entry(
        self,
        query: str,
        duration: float,
        rows: int,
        retention_limit: int = 10000,
    ) -> None:
        """Inserts a new query record into the database if it's not a consecutive duplicate."""
        query = query.strip()
        if not query:
            return

        # Avoid consecutive exact duplicates by checking the DB
        recent = self.get_recent_history(limit=1)
        if recent and recent[0].get("query") == query:
            return

        # Include microseconds so rapid consecutive inserts don't share the same
        # timestamp value, which would break ordering and retention logic.
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        self.con.execute("""
            INSERT INTO flatsql.query_history (timestamp, query, duration, rows)
            VALUES (?, ?, ?, ?)
        """, (ts, query, duration, rows))

        # Enforce the retention limit immediately after adding
        self.enforce_retention_limit(retention_limit)

    def get_recent_history(self, limit: int = 10000) -> list[dict]:
        """Fetches queries, returning them as a list of dicts to match the UI format."""
        df = self.con.execute(f"""
            SELECT 
                strftime(timestamp, '%Y-%m-%d %H:%M:%S') as timestamp, 
                query, 
                duration, 
                rows 
            FROM flatsql.query_history 
            ORDER BY timestamp DESC, rowid DESC
            LIMIT {limit}
        """).pl()
        return df.to_dicts()

    def enforce_retention_limit(self, limit: int) -> None:
        """Deletes older queries exceeding the retention limit."""
        # rowid is used instead of timestamp so rows with identical timestamps
        # are still uniquely identified and the correct subset is retained.
        self.con.execute(f"""
            DELETE FROM flatsql.query_history
            WHERE rowid NOT IN (
                SELECT rowid FROM flatsql.query_history
                ORDER BY timestamp DESC, rowid DESC
                LIMIT {limit}
            )
        """)