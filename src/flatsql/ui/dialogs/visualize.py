"""Data visualization dialog for interactive charting."""

from __future__ import annotations

from typing import Any

import matplotlib
import polars as pl
import qtawesome as qta
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flatsql.ui.widgets import DownwardComboBox, DropZoneList, MultiselectComboBox

matplotlib.use("QtAgg")


class VisualizeDialog(QDialog):
    """Provide drag-and-drop visual configuration for dataframe charting."""

    def __init__(
        self,
        df: pl.DataFrame,
        theme_colors: dict[str, Any] | None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the visualization dialog with source data and theme context."""
        super().__init__(parent)
        self.df = df
        self.theme_colors = theme_colors or {}
        self.active_filters: dict[str, tuple[str, QWidget]] = {}

        self.setWindowTitle("Visualize Data")
        self.resize(1150, 700)

        main_layout = QHBoxLayout(self)

        col_layout = QVBoxLayout()
        col_layout.setSpacing(8)

        col_layout.addWidget(QLabel("<b>Attributes</b>"))
        self.attributes_list = QListWidget()
        self.attributes_list.setObjectName("dragSourceList")
        self.attributes_list.setMinimumWidth(220)
        self.attributes_list.setMinimumHeight(180)
        self.attributes_list.setSpacing(2)
        self.attributes_list.setUniformItemSizes(True)
        self.attributes_list.setDragEnabled(True)
        self.attributes_list.setAcceptDrops(False)
        self.attributes_list.setDefaultDropAction(Qt.CopyAction)
        self.attributes_list.viewport().setCursor(Qt.OpenHandCursor)
        self.attributes_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.attributes_list.customContextMenuRequested.connect(
            lambda pos: self._show_avail_context_menu(pos, self.attributes_list)
        )
        col_layout.addWidget(self.attributes_list, stretch=1)

        col_layout.addSpacing(10)

        col_layout.addWidget(QLabel("<b>Measures</b>"))
        self.measures_avail_list = QListWidget()
        self.measures_avail_list.setObjectName("dragSourceList")
        self.measures_avail_list.setMinimumWidth(220)
        self.measures_avail_list.setMinimumHeight(180)
        self.measures_avail_list.setSpacing(2)
        self.measures_avail_list.setUniformItemSizes(True)
        self.measures_avail_list.setDragEnabled(True)
        self.measures_avail_list.setAcceptDrops(False)
        self.measures_avail_list.setDefaultDropAction(Qt.CopyAction)
        self.measures_avail_list.viewport().setCursor(Qt.OpenHandCursor)
        self.measures_avail_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.measures_avail_list.customContextMenuRequested.connect(
            lambda pos: self._show_avail_context_menu(pos, self.measures_avail_list)
        )
        col_layout.addWidget(self.measures_avail_list, stretch=1)

        for col, dtype in zip(df.columns, df.dtypes):
            item = QListWidgetItem(col)
            item.setToolTip(f"{col} ({dtype})")
            row_height = self.attributes_list.fontMetrics().height() + 10
            item.setSizeHint(QSize(0, row_height))
            if dtype in pl.NUMERIC_DTYPES:
                self.measures_avail_list.addItem(item)
            else:
                self.attributes_list.addItem(item)

        main_layout.addLayout(col_layout, stretch=2)

        settings_layout = QVBoxLayout()
        settings_layout.addWidget(QLabel("<b>Chart Type</b>"))
        chart_type_layout = QHBoxLayout()

        self.chart_type_group = QButtonGroup(self)
        self.chart_type_group.setExclusive(True)

        self.btn_bar = QPushButton(qta.icon("fa5s.chart-bar"), "Bar")
        self.btn_bar.setCheckable(True)
        self.btn_bar.setChecked(True)

        self.btn_line = QPushButton(qta.icon("fa5s.chart-line"), "Line")
        self.btn_line.setCheckable(True)

        self.btn_scatter = QPushButton(qta.icon("mdi.scatter-plot"), "Scatter")
        self.btn_scatter.setCheckable(True)

        for btn in (self.btn_bar, self.btn_line, self.btn_scatter):
            self.chart_type_group.addButton(btn)
            chart_type_layout.addWidget(btn)

        self.chart_type_group.buttonClicked.connect(self._draw_chart)
        settings_layout.addLayout(chart_type_layout)
        settings_layout.addSpacing(15)

        settings_layout.addWidget(QLabel("<b>X-Axis</b>"))
        self.x_list = DropZoneList(max_height=50)
        self.x_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.x_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.x_list, "X")
        )
        self.x_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_x_items_inserted)
        )
        self.x_list.model().rowsRemoved.connect(lambda: QTimer.singleShot(0, self._draw_chart))
        settings_layout.addWidget(self.x_list)

        settings_layout.addSpacing(10)

        settings_layout.addWidget(QLabel("<b>Y-Axis</b>"))
        self.y_list = DropZoneList(max_height=100)
        self.y_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.y_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.y_list, "Y")
        )
        self.y_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_y_items_inserted)
        )
        self.y_list.model().rowsRemoved.connect(lambda: QTimer.singleShot(0, self._draw_chart))
        settings_layout.addWidget(self.y_list)

        settings_layout.addSpacing(10)

        settings_layout.addWidget(QLabel("<b>Filters</b>"))
        self.filters_list = DropZoneList(max_height=100)
        self.filters_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.filters_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.filters_list, "Filter")
        )
        self.filters_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_filter_items_inserted)
        )
        self.filters_list.model().rowsRemoved.connect(lambda: QTimer.singleShot(0, self._sync_filters))
        settings_layout.addWidget(self.filters_list)

        settings_layout.addStretch()
        main_layout.addLayout(settings_layout, stretch=2)

        right_pane_layout = QVBoxLayout()

        self.slicer_container = QWidget()
        self.slicer_layout = QHBoxLayout(self.slicer_container)
        self.slicer_layout.setContentsMargins(0, 0, 0, 10)
        self.slicer_layout.setAlignment(Qt.AlignLeft)

        self.slicer_label = QLabel("")
        self.slicer_label.setObjectName("slicerInfoLabel")
        self.slicer_layout.addWidget(self.slicer_label)
        right_pane_layout.addWidget(self.slicer_container)

        self.figure = Figure(figsize=(6, 4), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)

        self.bg_color = self.palette().color(QPalette.Window).name()
        self.plot_text_color = self.palette().color(QPalette.WindowText).name()

        self.figure.patch.set_facecolor(self.bg_color)
        self._apply_chart_theme()
        self.ax.axis("off")

        right_pane_layout.addWidget(self.canvas, stretch=1)

        chart_btn_layout = QHBoxLayout()
        chart_btn_layout.addStretch()

        self.reset_btn = QPushButton("Reset Visual")
        self.reset_btn.clicked.connect(self._reset_visual)
        chart_btn_layout.addWidget(self.reset_btn)

        self.export_btn = QPushButton("Export Visual")
        self.export_btn.clicked.connect(self._export_chart)
        chart_btn_layout.addWidget(self.export_btn)

        right_pane_layout.addLayout(chart_btn_layout)
        main_layout.addLayout(right_pane_layout, stretch=4)

    def _clean_item_text(self, text: str) -> str:
        """Remove aggregation or filter-type suffixes from an item label."""
        if text.endswith(")") and " (" in text:
            suffix = text.rsplit(" (", 1)[1].rstrip(")")
            if suffix in ["SUM", "AVG", "MIN", "MAX", "COUNT", "Drop Down", "Multi Select"]:
                return text.rsplit(" (", 1)[0]
        return text

    def _on_x_items_inserted(self) -> None:
        """Keep at most one X-axis item and normalize its display text."""
        while self.x_list.count() > 1:
            self.x_list.takeItem(0)

        if self.x_list.count() == 1:
            item = self.x_list.item(0)
            item.setText(self._clean_item_text(item.text()))

        self._draw_chart()

    def _on_y_items_inserted(self) -> None:
        """Ensure Y-axis items default to SUM aggregation when no suffix exists."""
        for i in range(self.y_list.count()):
            item = self.y_list.item(i)
            text = item.text()

            has_agg = False
            if text.endswith(")") and " (" in text:
                suffix = text.rsplit(" (", 1)[1].rstrip(")")
                if suffix in ["SUM", "AVG", "MIN", "MAX", "COUNT"]:
                    has_agg = True

            if not has_agg:
                item.setText(f"{self._clean_item_text(text)} (SUM)")

        self._draw_chart()

    def _on_filter_items_inserted(self) -> None:
        """Ensure filter items default to Drop Down filter type."""
        for i in range(self.filters_list.count()):
            item = self.filters_list.item(i)
            text = item.text()

            has_type = False
            if text.endswith(")") and " (" in text:
                suffix = text.rsplit(" (", 1)[1].rstrip(")")
                if suffix in ["Drop Down", "Multi Select"]:
                    has_type = True

            if not has_type:
                item.setText(f"{self._clean_item_text(text)} (Drop Down)")

        self._sync_filters()

    def _sync_filters(self) -> None:
        """Synchronize slicer widgets with filter drop-zone items."""
        current_filters: dict[str, str] = {}
        for i in range(self.filters_list.count()):
            text = self.filters_list.item(i).text()
            col = self._clean_item_text(text)
            f_type = text.rsplit(" (", 1)[1].rstrip(")") if text.endswith(")") and " (" in text else "Drop Down"
            current_filters[col] = f_type

        for col in list(self.active_filters.keys()):
            if col not in current_filters or self.active_filters[col][0] != current_filters[col]:
                _, widget = self.active_filters.pop(col)
                self.slicer_layout.removeWidget(widget)
                widget.deleteLater()

        for col, f_type in current_filters.items():
            if col in self.active_filters:
                continue

            try:
                unique_vals = self.df[col].drop_nulls().unique().sort().to_list()
            except Exception:
                unique_vals = self.df[col].drop_nulls().unique().to_list()

            if f_type == "Drop Down":
                widget = DownwardComboBox()
                widget.addItem("(All)")
                for val in unique_vals:
                    widget.addItem(str(val))
                widget.currentIndexChanged.connect(self._draw_chart)
            else:
                widget = MultiselectComboBox(title=col)
                widget.add_items(unique_vals)
                widget.selectionChanged.connect(self._draw_chart)

            self.slicer_layout.addWidget(widget)
            self.active_filters[col] = (f_type, widget)

        if self.active_filters:
            self.slicer_label.hide()
        else:
            self.slicer_label.show()

        self._draw_chart()

    def _show_avail_context_menu(self, pos: Any, list_widget: QListWidget) -> None:
        """Show context menu for available attribute/measure items."""
        item = list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        add_x_action = menu.addAction("Add to X-Axis")
        add_y_action = menu.addAction("Add to Y-Axis")
        add_filter_action = menu.addAction("Add to Filters")

        action = menu.exec(list_widget.viewport().mapToGlobal(pos))
        if action == add_x_action:
            self.x_list.addItem(item.text())
        elif action == add_y_action:
            self.y_list.addItem(item.text())
        elif action == add_filter_action:
            self.filters_list.addItem(item.text())

    def _show_dropzone_context_menu(self, pos: Any, list_widget: QListWidget, list_type: str) -> None:
        """Show context menu for X/Y/filter drop-zone items."""
        item = list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)

        targets: list[tuple[str, QListWidget]] = []
        if list_type != "X":
            targets.append(("X-Axis", self.x_list))
        if list_type != "Y":
            targets.append(("Y-Axis", self.y_list))
        if list_type != "Filter":
            targets.append(("Filters", self.filters_list))

        move_actions: dict[Any, QListWidget] = {}
        copy_actions: dict[Any, QListWidget] = {}

        move_menu = menu.addMenu("Move to")
        copy_menu = menu.addMenu("Copy to")

        for name, target_list in targets:
            move_action = move_menu.addAction(name)
            move_actions[move_action] = target_list

            copy_action = copy_menu.addAction(name)
            copy_actions[copy_action] = target_list

        menu.addSeparator()
        remove_action = menu.addAction("Remove")

        agg_actions: dict[Any, str] = {}
        if list_type == "Y":
            menu.addSeparator()
            agg_menu = menu.addMenu("Aggregation")
            for agg in ["SUM", "AVG", "MIN", "MAX", "COUNT"]:
                action = agg_menu.addAction(agg)
                agg_actions[action] = agg

        type_actions: dict[Any, str] = {}
        if list_type == "Filter":
            menu.addSeparator()
            type_menu = menu.addMenu("Type")
            for filter_type in ["Drop Down", "Multi Select"]:
                action = type_menu.addAction(filter_type)
                type_actions[action] = filter_type

        action = menu.exec(list_widget.viewport().mapToGlobal(pos))
        if not action:
            return

        if action in move_actions:
            target_list = move_actions[action]
            target_list.addItem(item.text())
            list_widget.takeItem(list_widget.row(item))
        elif action in copy_actions:
            target_list = copy_actions[action]
            target_list.addItem(item.text())
        elif action == remove_action:
            list_widget.takeItem(list_widget.row(item))
        elif action in agg_actions:
            new_agg = agg_actions[action]
            item.setText(f"{self._clean_item_text(item.text())} ({new_agg})")
            self._draw_chart()
        elif action in type_actions:
            new_type = type_actions[action]
            item.setText(f"{self._clean_item_text(item.text())} ({new_type})")
            self._sync_filters()

    def _apply_chart_theme(self) -> None:
        """Apply palette-aligned styling to the matplotlib axes."""
        self.ax.set_facecolor(self.bg_color)
        self.ax.tick_params(colors=self.plot_text_color)
        self.ax.xaxis.label.set_color(self.plot_text_color)
        self.ax.yaxis.label.set_color(self.plot_text_color)
        self.ax.spines["bottom"].set_color(self.plot_text_color)
        self.ax.spines["left"].set_color(self.plot_text_color)
        self.ax.spines["top"].set_visible(False)
        self.ax.spines["right"].set_visible(False)

    def _reset_visual(self) -> None:
        """Reset all configured axes and filters and clear the chart canvas."""
        self.x_list.clear()
        self.y_list.clear()
        self.filters_list.clear()
        self.ax.clear()
        self.ax.axis("off")
        self.canvas.draw()

    def _export_chart(self) -> None:
        """Export the current chart to an image or vector file."""
        if self.x_list.count() == 0 or self.y_list.count() == 0:
            QMessageBox.information(self, "Export", "Please plot a chart first before exporting.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Visual",
            "",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)",
        )
        if path:
            try:
                self.figure.savefig(path, bbox_inches="tight", facecolor=self.bg_color)
                QMessageBox.information(self, "Success", f"Chart successfully exported to:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Failed to export chart:\n{exc}")

    def _draw_chart(self) -> None:
        """Render the chart from selected axes, measures, and active filters."""
        if self.x_list.count() == 0 or self.y_list.count() == 0:
            self.ax.clear()
            self.ax.axis("off")
            self.canvas.draw()
            return

        self.ax.axis("on")
        checked_button = self.chart_type_group.checkedButton()
        chart_type = checked_button.text() if checked_button else "Bar"

        x_col = self._clean_item_text(self.x_list.item(0).text())

        y_items: list[tuple[str, str]] = []
        seen: set[str] = set()
        for i in range(self.y_list.count()):
            text = self.y_list.item(i).text()
            if text.endswith(")") and " (" in text:
                col, agg = text.rsplit(" (", 1)
                agg = agg.rstrip(")")
            else:
                col, agg = text, "SUM"

            alias = f"{col} ({agg})"
            if alias not in seen:
                y_items.append((col, agg))
                seen.add(alias)

        if not y_items:
            return

        y_cols_raw = [item[0] for item in y_items]

        self.ax.clear()
        self._apply_chart_theme()

        try:
            valid_df = self.df

            for filter_col, (filter_type, widget) in self.active_filters.items():
                dtype = self.df.schema[filter_col]
                if filter_type == "Drop Down":
                    value = widget.currentText()
                    if value != "(All)":
                        cast_value = pl.Series([value]).cast(dtype, strict=False)[0]
                        valid_df = valid_df.filter(pl.col(filter_col) == cast_value)
                else:
                    vals = widget.get_checked_items()
                    total_items = widget.model.rowCount() - 1
                    if len(vals) < total_items:
                        if len(vals) == 0:
                            valid_df = valid_df.filter(pl.lit(False))
                        else:
                            cast_vals = pl.Series(vals).cast(dtype, strict=False)
                            valid_df = valid_df.filter(pl.col(filter_col).is_in(cast_vals))

            valid_df = valid_df.drop_nulls(subset=[x_col] + y_cols_raw)
            if valid_df.is_empty():
                self.ax.text(
                    0.5,
                    0.5,
                    "No valid data to plot",
                    color=self.plot_text_color,
                    ha="center",
                    va="center",
                )
                self.ax.axis("off")
                self.canvas.draw()
                return

            agg_funcs = {
                "SUM": "sum",
                "AVG": "mean",
                "MIN": "min",
                "MAX": "max",
                "COUNT": "count",
            }

            agg_exprs = []
            for col, agg in y_items:
                func_name = agg_funcs.get(agg, "sum")
                agg_exprs.append(getattr(pl.col(col), func_name)().alias(f"{col} ({agg})"))

            plot_df = valid_df.group_by(x_col).agg(agg_exprs).sort(x_col)
            x_data = plot_df[x_col].to_list()

            accent_hex = self.palette().color(QPalette.Highlight).name()
            default_colors = [
                accent_hex,
                "#E65100",
                "#28A745",
                "#6F42C1",
                "#D32F2F",
                "#17A2B8",
                "#FFC107",
            ]
            colors = [accent_hex] + [c for c in default_colors if c.upper() != accent_hex.upper()]

            x_indices = list(range(len(x_data)))
            num_bars = len(y_items)
            bar_width = 0.8 / num_bars

            for i, (col, agg) in enumerate(y_items):
                display_name = f"{col} ({agg})"
                y_data = plot_df[display_name].to_list()
                color = colors[i % len(colors)]

                if chart_type == "Bar":
                    offsets = [x - 0.4 + (i + 0.5) * bar_width for x in x_indices]
                    self.ax.bar(offsets, y_data, width=bar_width, label=display_name, color=color)
                elif chart_type == "Line":
                    self.ax.plot(x_data, y_data, marker="o", linewidth=2, label=display_name, color=color)
                elif chart_type == "Scatter":
                    self.ax.scatter(x_data, y_data, label=display_name, color=color)

            self.ax.set_xlabel(x_col, color=self.plot_text_color)

            if len(y_items) == 1:
                col, agg = y_items[0]
                self.ax.set_ylabel(f"{agg} of {col}", color=self.plot_text_color)
                self.ax.set_title(f"{col} vs {x_col} ({agg})", color=self.plot_text_color)
            else:
                self.ax.set_ylabel("Values", color=self.plot_text_color)
                self.ax.set_title(f"Multiple Measures vs {x_col}", color=self.plot_text_color)

            if chart_type == "Bar":
                self.ax.set_xticks(x_indices)
                self.ax.set_xticklabels(x_data)

            if len(x_data) > 5:
                self.ax.tick_params(axis="x", rotation=45)

            if len(y_items) > 1:
                self.ax.legend(
                    facecolor=self.bg_color,
                    edgecolor=self.plot_text_color,
                    labelcolor=self.plot_text_color,
                )

            self.figure.tight_layout()
            self.canvas.draw()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Rendering Error",
                f"Cannot draw chart with current configuration:\n\n{exc}",
            )
            self.ax.clear()
            self.ax.axis("off")
            self.canvas.draw()
