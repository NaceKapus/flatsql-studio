"""Background query orchestration for FlatSQL Studio."""

from __future__ import annotations

import re
import time
from typing import Any

import polars as pl
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from flatsql.core.engine import FlatEngine
from flatsql.core.worker import AutoCompleteWorker, QueryWorker

class QueryController(QObject):
    """Manages the execution of SQL queries on background threads."""
    
    # Signals to communicate with the MainWindow
    query_started = Signal()
    query_completed = Signal(object, object, object, object, float, bool, object)
    timer_updated = Signal(object, str, object)
    autocomplete_ready = Signal(object, object, int)
    error_occurred = Signal(str, str)

    def __init__(self, connection_manager: Any) -> None:
        """Initialize query execution state and the live status timer."""
        super().__init__()
        self.conn_manager = connection_manager
        
        self.query_thread: QThread | None = None
        self.query_worker: QueryWorker | None = None
        self.autocomplete_thread: QThread | None = None
        self.autocomplete_worker: AutoCompleteWorker | None = None
        self.active_query_engine: FlatEngine | None = None
        self.active_query_editor: Any = None
        self.query_start_time: float = 0.0
        self.last_query_was_ddl = False
        self.peak_memory: int = 0
        self._autocomplete_request_id = 0
        self._pending_autocomplete_request: tuple[int, Any, FlatEngine, str] | None = None

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(100)
        self.status_timer.timeout.connect(self._update_status_timer)

    def execute_query(self, editor: Any, query_text: str, connection_key: str | None) -> None:
        """Prepares and starts the background worker for query execution."""
        if self.query_thread and self.query_thread.isRunning():
            self.error_occurred.emit("Busy", "A query is already running.")
            return

        if not connection_key:
            self.error_occurred.emit("No Connection", "The current tab has no active database connection.")
            return

        engine = self.conn_manager.get_db(connection_key)
        if not engine:
            self.error_occurred.emit("Connection Lost", f"The connection '{connection_key}' is no longer available.")
            return

        if not query_text.strip(): 
            return

        # Simple heuristic to check for schema-modifying queries
        ddl_keywords = ('CREATE', 'DROP', 'ALTER', 'INSERT', 'UPDATE', 'DELETE', 'ATTACH', 'DETACH')
        ddl_pattern = r'\b(' + '|'.join(ddl_keywords) + r')\b'
        query_without_comments = re.sub(r'--.*', '', query_text)
        query_without_comments = re.sub(r'/\*.*?\*/', '', query_without_comments, flags=re.DOTALL)
        self.last_query_was_ddl = bool(re.search(ddl_pattern, query_without_comments, re.IGNORECASE))

        self.active_query_engine = engine
        self.active_query_editor = editor
        self.query_start_time = time.perf_counter()
        self.peak_memory = 0
        
        self.query_started.emit()
        self.status_timer.start()

        engine_settings = self.conn_manager.settings_manager._settings

        self.query_thread = QThread()
        self.query_worker = QueryWorker(engine, query_text, engine_settings)
        self.query_worker.moveToThread(self.query_thread)

        self.query_thread.started.connect(self.query_worker.run)
        self.query_worker.finished.connect(self._handle_query_completion)
        self.query_worker.finished.connect(self.query_thread.quit)
        self.query_worker.finished.connect(self.query_worker.deleteLater)
        self.query_thread.finished.connect(self.query_thread.deleteLater)
        self.query_thread.finished.connect(self._on_thread_finished)

        self.query_thread.start()

    def request_autocomplete(self, editor: Any, query_text: str, cursor_position: int) -> None:
        """Request SQL autocomplete suggestions for the active editor."""
        connection_key = getattr(editor, 'connection_key', None)
        if not connection_key:
            self.autocomplete_ready.emit(editor, [], cursor_position)
            return

        engine = self.conn_manager.get_db(connection_key)
        if not engine:
            self.autocomplete_ready.emit(editor, [], cursor_position)
            return

        self._autocomplete_request_id += 1
        request = (self._autocomplete_request_id, editor, engine, query_text)

        if self.autocomplete_thread and self.autocomplete_thread.isRunning():
            self._pending_autocomplete_request = request
            return

        self._start_autocomplete_request(*request)

    def _start_autocomplete_request(
        self,
        request_id: int,
        editor: Any,
        engine: FlatEngine,
        query_text: str,
    ) -> None:
        """Start a background worker for one autocomplete request."""
        self.autocomplete_thread = QThread()
        self.autocomplete_worker = AutoCompleteWorker(request_id, editor, engine, query_text)
        self.autocomplete_worker.moveToThread(self.autocomplete_thread)

        self.autocomplete_thread.started.connect(self.autocomplete_worker.run)
        self.autocomplete_worker.finished.connect(self._handle_autocomplete_completion)
        self.autocomplete_worker.finished.connect(self.autocomplete_thread.quit)
        self.autocomplete_worker.finished.connect(self.autocomplete_worker.deleteLater)
        self.autocomplete_thread.finished.connect(self.autocomplete_thread.deleteLater)
        self.autocomplete_thread.finished.connect(self._on_autocomplete_thread_finished)

        self.autocomplete_thread.start()

    def stop_query(self) -> None:
        """Interrupts the active query."""
        if self.query_thread and self.query_thread.isRunning() and self.active_query_engine:
            self.active_query_engine.interrupt_query()

    def wait_for_completion(self, timeout_ms: int = 5000) -> None:
        """Safely stops and waits for the thread to exit (useful for app shutdown)."""
        if self.query_thread and self.query_thread.isRunning():
            self.stop_query()
            self.query_thread.quit()
            self.query_thread.wait(timeout_ms)

    def _update_status_timer(self) -> None:
        """Emit live elapsed-time and memory statistics for the running query."""
        if self.query_start_time > 0 and self.active_query_engine:
            elapsed = time.perf_counter() - self.query_start_time
            current_mem = self.active_query_engine.get_memory_usage()
            self.peak_memory = max(self.peak_memory, current_mem)
            
            stats_text = f"{self.active_query_engine.get_display_name()} | {elapsed:.2f}s | 0 rows"
            self.timer_updated.emit(self.active_query_editor, stats_text, current_mem)

    def _on_thread_finished(self) -> None:
        """Clear worker references after the background thread exits."""
        self.query_thread = None
        self.query_worker = None

    def _on_autocomplete_thread_finished(self) -> None:
        """Clear autocomplete worker references and process the newest queued request."""
        self.autocomplete_thread = None
        self.autocomplete_worker = None

        if self._pending_autocomplete_request is not None:
            pending_request = self._pending_autocomplete_request
            self._pending_autocomplete_request = None
            self._start_autocomplete_request(*pending_request)

    def _handle_autocomplete_completion(
        self,
        request_id: int,
        editor: Any,
        suggestions: object,
        replace_start: int,
    ) -> None:
        """Emit autocomplete results for the latest matching request only."""
        if request_id == self._autocomplete_request_id:
            self.autocomplete_ready.emit(editor, suggestions, replace_start)

    def _handle_query_completion(self, result: object, duration: float) -> None:
        """Processes raw results from the worker and emits them to the UI."""
        self.status_timer.stop()
        self.query_start_time = 0
        
        is_ddl = self.last_query_was_ddl
        self.last_query_was_ddl = False

        df = None
        error_msg = None
        info_msg = None

        if isinstance(result, pl.DataFrame):
            if "explain_key" in result.columns and "explain_value" in result.columns:
                try:
                    plan_rows = result.filter(pl.col("explain_key") == "physical_plan")
                    if not plan_rows.is_empty():
                        info_msg = plan_rows["explain_value"][0]
                    else:
                        info_msg = "\n".join(result["explain_value"].to_list())
                except Exception:
                    df = result
            else:
                df = result
        else:
            error_msg = str(result)

        self.query_completed.emit(self.active_query_editor, df, error_msg, info_msg, duration, is_ddl, self.peak_memory)
        
        self.active_query_engine = None
        self.active_query_editor = None