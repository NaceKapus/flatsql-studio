"""DuckDB memory profiler dialog with live monitoring and visualization."""
from __future__ import annotations

from PySide6.QtCharts import QAreaSeries, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QDialog, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class DuckDBProfilerDialog(QDialog):
    """Dialog for monitoring DuckDB memory usage and performance metrics.

    Displays memory allocation by tag in a tree widget and provides a live
    memory usage graph updated every 0.1 seconds. Supports theme-aware colors.
    """

    def __init__(self, engine: object, parent: QWidget | None = None) -> None:
        """Initialize the profiler dialog.

        Args:
            engine: DuckDB engine instance with a main_con connection.
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("DuckDB Profiler")
        self.resize(650, 450)
        self.engine = engine

        # State for the live graph (store up to 60 seconds of history)
        self.mem_history: list[float] = []
        self.max_history_points = 60
        self.graph_floor_tolerance_mb = 0.01

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._setup_details_tab()
        self._setup_graph_tab()

        # Timer to refresh stats every 0.1 second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_stats)
        self.timer.start(100)

        self.refresh_stats()

    def _setup_details_tab(self) -> None:
        """Create and configure the memory details tab with tree widget."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Memory Tag", "Memory Usage", "Temporary Storage"])

        # Make the columns wider by default so text isn't cut off
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 150)

        layout.addWidget(self.tree)
        self.tabs.addTab(tab, "Details")

    def _setup_graph_tab(self) -> None:
        """Create and configure the live memory graph tab using QtCharts."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        bg_color = QColor(self.palette().color(QPalette.Window))
        text_color = QColor(self.palette().color(QPalette.WindowText))
        accent_color = QColor(self.palette().color(QPalette.Highlight))
        grid_color = QColor(text_color)
        grid_color.setAlphaF(0.25)

        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.NoAnimation)  # critical for 10 Hz updates
        self.chart.legend().setVisible(False)
        self.chart.setBackgroundBrush(QBrush(bg_color))
        self.chart.setBackgroundPen(QPen(bg_color))
        self.chart.setPlotAreaBackgroundBrush(QBrush(bg_color))
        self.chart.setPlotAreaBackgroundVisible(True)
        self.chart.setTitle("DuckDB Memory Usage")
        self.chart.setTitleBrush(QBrush(text_color))
        self.chart.setMargins(self.chart.margins())

        # Upper line follows the history; lower line is held flat at y=0 so the
        # area series fills from the curve down to the X axis.
        self.upper_series = QLineSeries()
        self.upper_series.append(0.0, 0.0)

        self.lower_series = QLineSeries()
        self.lower_series.append(0.0, 0.0)
        self.lower_series.append(float(self.max_history_points - 1), 0.0)

        self.area_series = QAreaSeries(self.upper_series, self.lower_series)
        # QAreaSeries does not take ownership of its line series in C++ Qt; reparent
        # to the area so they outlive this function's local references.
        self.upper_series.setParent(self.area_series)
        self.lower_series.setParent(self.area_series)

        fill_color = QColor(accent_color)
        fill_color.setAlphaF(0.30)
        self.area_series.setBrush(QBrush(fill_color))
        line_pen = QPen(accent_color)
        line_pen.setWidth(2)
        self.area_series.setPen(line_pen)

        self.chart.addSeries(self.area_series)

        # X axis: hidden — the horizontal position is just polling order.
        self.axis_x = QValueAxis()
        self.axis_x.setRange(0, self.max_history_points - 1)
        self.axis_x.setVisible(False)

        # Y axis: dynamic range based on peak * 1.1, palette-styled.
        self.axis_y = QValueAxis()
        self.axis_y.setRange(0, 1.0)
        self.axis_y.setTitleText("Total DuckDB Memory (MB)")
        self.axis_y.setTitleBrush(QBrush(text_color))
        self.axis_y.setLabelsColor(text_color)
        self.axis_y.setGridLinePen(QPen(grid_color))
        axis_line_pen = QPen(text_color)
        axis_line_pen.setWidthF(0.8)
        self.axis_y.setLinePen(axis_line_pen)
        self.axis_y.applyNiceNumbers()

        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)
        self.area_series.attachAxis(self.axis_x)
        self.area_series.attachAxis(self.axis_y)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing, True)

        layout.addWidget(self.chart_view)
        self.tabs.addTab(tab, "Live Graph")

    def refresh_stats(self) -> None:
        """Fetch current DuckDB memory statistics and update both tree and graph."""
        if not self.engine or not self.engine.main_con:
            return

        try:
            cursor = self.engine.main_con.cursor()
            rows = cursor.execute(
                "SELECT tag, memory_usage_bytes, temporary_storage_bytes FROM duckdb_memory()"
            ).fetchall()
            cursor.close()

            self.tree.clear()
            total_mem_mb = 0.0

            # Update Tree
            for tag, memory_usage_bytes, temporary_storage_bytes in rows:
                mem_mb = float(memory_usage_bytes or 0) / (1024 * 1024)
                temp_mb = float(temporary_storage_bytes or 0) / (1024 * 1024)
                total_mem_mb += mem_mb

                item = QTreeWidgetItem(
                    [str(tag), f"{mem_mb:.2f} MB", f"{temp_mb:.2f} MB"]
                )
                self.tree.addTopLevelItem(item)

            # Plot absolute memory so opening the profiler mid-query still shows usage.
            graph_mem_mb = max(total_mem_mb, 0.0)
            if graph_mem_mb < self.graph_floor_tolerance_mb:
                graph_mem_mb = 0.0

            # Update Graph History
            self.mem_history.append(graph_mem_mb)
            if len(self.mem_history) > self.max_history_points:
                self.mem_history.pop(0)

            self._update_graph()

        except Exception as e:
            self.tree.clear()
            self.tree.addTopLevelItem(QTreeWidgetItem(["Error fetching stats", str(e), ""]))

    def _update_graph(self) -> None:
        """Push the current history into the line/area series and rescale Y."""
        n = len(self.mem_history)
        if n == 0:
            return

        upper_points = [QPointF(float(i), float(v)) for i, v in enumerate(self.mem_history)]
        self.upper_series.replace(upper_points)

        # Hold the lower line flat at y=0 across the same X range as the upper line.
        right_x = float(max(n - 1, 1))
        self.lower_series.replace([QPointF(0.0, 0.0), QPointF(right_x, 0.0)])

        peak_value = max(self.mem_history)
        upper_bound = max(1.0, peak_value * 1.1)
        self.axis_y.setRange(0, upper_bound)

    def closeEvent(self, event: object) -> None:
        """Clean up timer on dialog close.

        Args:
            event: The close event.
        """
        self.timer.stop()
        super().closeEvent(event)
