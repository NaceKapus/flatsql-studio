"""DuckDB-backed aggregation worker for the Visualize dialog.

Aggregations run on a background thread against a long-lived in-memory DuckDB
connection that has the source Polars DataFrame registered as a view. Requests
are debounced so rapid drag-drop / filter changes coalesce into a single query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import polars as pl
from PySide6.QtCore import (
    QMetaObject,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)


AGG_FUNCS: dict[str, str] = {
    "SUM": "SUM",
    "AVG": "AVG",
    "MIN": "MIN",
    "MAX": "MAX",
    "COUNT": "COUNT",
}


@dataclass
class FilterSpec:
    """A single filter predicate destined for the WHERE clause."""

    col: str
    kind: str  # "all" | "single" | "multi_partial" | "multi_none"
    values: list[Any] = field(default_factory=list)


@dataclass
class AggregationRequest:
    """Self-contained description of one aggregation the dialog wants rendered."""

    chart_type: str  # bar | stacked_bar | line | area | stacked_area | scatter | pie | donut | heatmap
    x_col: str
    y_items: list[tuple[str, str]]
    rows_col: str | None = None  # heatmap second grouping dimension
    filters: list[FilterSpec] = field(default_factory=list)
    pie_sort: bool = True  # pie/donut: order slices by value descending


def _quote(name: str) -> str:
    """Escape a DuckDB identifier with double quotes."""
    return '"' + name.replace('"', '""') + '"'


def _alias_for(col: str, agg: str) -> str:
    """Display alias used for an aggregated measure column."""
    return f"{col} ({agg})"


def build_sql(req: AggregationRequest) -> tuple[str, list[Any]]:
    """Translate an AggregationRequest into a parameterized DuckDB SELECT."""
    group_cols = [req.x_col]
    if req.chart_type in ("heatmap", "table") and req.rows_col:
        group_cols.append(req.rows_col)

    select_parts = [_quote(c) for c in group_cols]
    for col, agg in req.y_items:
        func = AGG_FUNCS.get(agg, "SUM")
        select_parts.append(f"{func}({_quote(col)}) AS {_quote(_alias_for(col, agg))}")

    where_clauses: list[str] = [f"{_quote(c)} IS NOT NULL" for c in group_cols]
    params: list[Any] = []
    for f in req.filters:
        if f.kind == "all":
            continue
        if f.kind == "multi_none":
            where_clauses.append("FALSE")
        elif f.kind == "single":
            where_clauses.append(f"{_quote(f.col)} = ?")
            params.append(f.values[0])
        elif f.kind == "multi_partial":
            placeholders = ", ".join("?" for _ in f.values)
            where_clauses.append(f"{_quote(f.col)} IN ({placeholders})")
            params.extend(f.values)

    sql = "SELECT " + ", ".join(select_parts) + " FROM data"
    sql += " WHERE " + " AND ".join(where_clauses)
    sql += " GROUP BY " + ", ".join(_quote(c) for c in group_cols)

    if req.chart_type in ("pie", "donut") and req.pie_sort and req.y_items:
        first_alias = _alias_for(*req.y_items[0])
        sql += f" ORDER BY {_quote(first_alias)} DESC"
    else:
        sql += " ORDER BY " + ", ".join(_quote(c) for c in group_cols)

    return sql, params


class AggregationWorker(QObject):
    """Lives on a worker thread; owns the DuckDB connection and runs queries."""

    result_ready = Signal(int, object)  # (req_id, pl.DataFrame)
    failed = Signal(int, str)            # (req_id, message)

    def __init__(self, df: pl.DataFrame) -> None:
        """Capture a reference to the source DataFrame; defer DuckDB setup to the worker thread."""
        super().__init__()
        self._df = df
        self._con: duckdb.DuckDBPyConnection | None = None

    def _ensure_connection(self) -> duckdb.DuckDBPyConnection:
        """Create the DuckDB connection and register the DataFrame on first use."""
        if self._con is None:
            self._con = duckdb.connect()
            self._con.register("data", self._df)
        return self._con

    @Slot(int, object)
    def run_request(self, req_id: int, req: AggregationRequest) -> None:
        """Execute one aggregation request on the worker thread."""
        try:
            con = self._ensure_connection()
            sql, params = build_sql(req)
            plot_df = con.execute(sql, params).pl()
            self.result_ready.emit(req_id, plot_df)
        except Exception as exc:
            self.failed.emit(req_id, str(exc))

    @Slot()
    def shutdown(self) -> None:
        """Close the DuckDB connection from the worker thread before exit."""
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None


class AggregationController(QObject):
    """Debounces requests and forwards results from the worker back to the dialog."""

    result_ready = Signal(object)  # pl.DataFrame
    failed = Signal(str)
    _run_requested = Signal(int, object)  # to worker, queued

    DEBOUNCE_MS = 80

    def __init__(self, df: pl.DataFrame, parent: QObject | None = None) -> None:
        """Spin up the worker thread and wire signals."""
        super().__init__(parent)
        self._req_id = 0
        self._latest_id = 0
        self._pending: AggregationRequest | None = None

        self._thread = QThread()
        self._worker = AggregationWorker(df)
        self._worker.moveToThread(self._thread)
        self._run_requested.connect(self._worker.run_request, Qt.QueuedConnection)
        self._worker.result_ready.connect(self._on_result_ready)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self.DEBOUNCE_MS)
        self._debounce.timeout.connect(self._fire)

    def request(self, req: AggregationRequest) -> None:
        """Schedule an aggregation; supersedes any pending request."""
        self._pending = req
        self._debounce.start()

    def _fire(self) -> None:
        if self._pending is None:
            return
        self._req_id += 1
        self._latest_id = self._req_id
        self._run_requested.emit(self._req_id, self._pending)
        self._pending = None

    @Slot(int, object)
    def _on_result_ready(self, req_id: int, plot_df: pl.DataFrame) -> None:
        if req_id == self._latest_id:
            self.result_ready.emit(plot_df)

    @Slot(int, str)
    def _on_failed(self, req_id: int, msg: str) -> None:
        if req_id == self._latest_id:
            self.failed.emit(msg)

    def shutdown(self) -> None:
        """Stop the worker thread cleanly; safe to call multiple times."""
        if not self._thread.isRunning():
            return
        QMetaObject.invokeMethod(self._worker, "shutdown", Qt.QueuedConnection)
        self._thread.quit()
        self._thread.wait(2000)
