"""Background worker for executing DuckDB queries."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QObject, Signal

from flatsql.core.engine import FlatEngine

class QueryWorker(QObject):
    """Run a query on a background thread and emit the result and duration."""

    finished = Signal(object, float)
    
    def __init__(
        self,
        engine: FlatEngine,
        query: str,
        engine_settings: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the worker with the target engine and query payload."""
        super().__init__()
        self.engine = engine
        self.query = query
        self.engine_settings = engine_settings
        
    def run(self) -> None:
        """Execute the query and emit either the dataframe or the error string."""
        start_time = time.perf_counter()
        df, error = self.engine.execute_query(self.query, self.engine_settings)
        duration = time.perf_counter() - start_time
        self.finished.emit(error if error else df, duration)


class AutoCompleteWorker(QObject):
    """Fetch DuckDB autocomplete suggestions on a background thread."""

    finished = Signal(int, object, object, int)

    def __init__(
        self,
        request_id: int,
        editor: Any,
        engine: FlatEngine,
        query_text: str,
        limit: int = 25,
    ) -> None:
        """Initialize the worker with the autocomplete request payload."""
        super().__init__()
        self.request_id = request_id
        self.editor = editor
        self.engine = engine
        self.query_text = query_text
        self.limit = limit

    def run(self) -> None:
        """Resolve autocomplete suggestions and emit them back to the controller."""
        suggestions, replace_start = self.engine.get_autocomplete_suggestions(self.query_text, self.limit)
        self.finished.emit(self.request_id, self.editor, suggestions, replace_start)