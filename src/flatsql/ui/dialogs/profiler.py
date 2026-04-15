"""DuckDB memory profiler dialog with live monitoring and visualization."""
from __future__ import annotations

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QDialog, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

matplotlib.use("QtAgg")


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
        self.text_color = "#ffffff"

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
        """Create and configure the live memory graph tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.figure = Figure(figsize=(6, 4), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)

        # Match application theme colors
        bg_color = self.palette().color(QPalette.Window).name()
        self.text_color = self.palette().color(QPalette.WindowText).name()
        self.figure.patch.set_facecolor(bg_color)
        self.ax.set_facecolor(bg_color)

        layout.addWidget(self.canvas)
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
        """Redraw the memory usage graph with current history data."""
        self.ax.clear()

        # Apply theme aesthetics
        self.ax.tick_params(colors=self.text_color)
        for spine in self.ax.spines.values():
            spine.set_color(self.text_color)
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)

        self.ax.set_ylabel("Total DuckDB Memory (MB)", color=self.text_color)
        self.ax.set_title("DuckDB Memory Usage", color=self.text_color)

        # Grab the current theme's primary highlight/accent color
        accent_color = self.palette().color(QPalette.Highlight).name()

        # Plot the data (Task Manager style with a filled area under the curve)
        x_data = list(range(len(self.mem_history)))
        self.ax.plot(x_data, self.mem_history, color=accent_color, linewidth=2)
        self.ax.fill_between(x_data, self.mem_history, color=accent_color, alpha=0.3)

        # Keep the X axis fixed to our max history size so it scrolls right-to-left
        self.ax.set_xlim(0, self.max_history_points - 1)

        if self.mem_history:
            peak_value = max(self.mem_history)
            upper_bound = max(1.0, peak_value * 1.1)
            self.ax.set_ylim(0, upper_bound)

        # Hide X-axis ticks as they just represent generic polling intervals
        self.ax.set_xticks([])

        self.figure.tight_layout()
        self.canvas.draw_idle()

    def closeEvent(self, event: object) -> None:
        """Clean up timer on dialog close.
        
        Args:
            event: The close event.
        """
        self.timer.stop()
        super().closeEvent(event)
