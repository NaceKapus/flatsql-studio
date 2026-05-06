"""Data visualization dialog for interactive charting (QtCharts + DuckDB-backed aggregation)."""

from __future__ import annotations

from typing import Any

import polars as pl
import qtawesome as qta
from PySide6.QtCharts import QChart, QChartView
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPalette, QPdfWriter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flatsql.ui.dialogs._visualize_charts import (
    HeatmapView,
    PivotTableView,
    build_area,
    build_bar,
    build_line,
    build_pie,
    build_scatter,
    style_chart,
)
from flatsql.ui.dialogs._visualize_query import (
    AggregationController,
    AggregationRequest,
    FilterSpec,
)
from flatsql.ui.widgets import DownwardComboBox, DropZoneList, MultiselectComboBox


# Maps chart-type code → (button label, qta icon name).
_CHART_TYPES: list[tuple[str, str, str]] = [
    ("bar", "Bar", "fa5s.chart-bar"),
    ("stacked_bar", "Stacked Bar", "mdi.chart-bar-stacked"),
    ("line", "Line", "fa5s.chart-line"),
    ("area", "Area", "mdi.chart-areaspline"),
    ("stacked_area", "Stacked Area", "mdi.chart-multiline"),
    ("scatter", "Scatter", "mdi.scatter-plot"),
    ("pie", "Pie", "fa5s.chart-pie"),
    ("donut", "Donut", "mdi.chart-donut"),
    ("heatmap", "Heatmap", "mdi.grid"),
    ("table", "Pivot Table", "fa5s.table"),
]


class _VisualizeDropZone(DropZoneList):
    """DropZoneList with empty-state placeholder text and drag-hover accent border.

    Always rendered in chip mode so dropped fields appear as compact horizontal chips
    that wrap when the well grows past one row.
    """

    def __init__(self, placeholder: str, max_height: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(max_height=max_height, chip_mode=True, parent=parent)
        self._placeholder = placeholder

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(self.palette().color(QPalette.PlaceholderText))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, self._placeholder)

    def dragEnterEvent(self, event: Any) -> None:
        self.setProperty("dragOver", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event: Any) -> None:
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: Any) -> None:
        self.setProperty("dragOver", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        super().dropEvent(event)


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
        self.resize(1200, 720)

        self._chart_type = "bar"

        self._bg_color = self.palette().color(QPalette.Window).name()
        self._text_color = self.palette().color(QPalette.WindowText).name()
        self._accent_color = self.palette().color(QPalette.Highlight).name()
        self._grid_color = self.palette().color(QPalette.Mid).name()

        self.agg_controller = AggregationController(df, self)
        self.agg_controller.result_ready.connect(self._on_aggregation_result)
        self.agg_controller.failed.connect(self._on_aggregation_failed)

        self._build_ui()
        self._populate_field_lists()
        self._update_dropzone_visibility()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        field_panel = self._build_field_panel()
        field_panel.setFixedWidth(170)
        main_layout.addWidget(field_panel)

        settings_panel = self._build_settings_panel()
        settings_panel.setFixedWidth(240)
        main_layout.addWidget(settings_panel)

        main_layout.addLayout(self._build_right_pane(), stretch=1)

    def _build_field_panel(self) -> QFrame:
        field_panel = QFrame()
        field_panel.setObjectName("fieldPanel")
        col_layout = QVBoxLayout(field_panel)
        col_layout.setSpacing(6)
        col_layout.setContentsMargins(8, 8, 8, 8)

        attr_header = QLabel("ATTRIBUTES")
        attr_header.setObjectName("sectionHeader")
        col_layout.addWidget(attr_header)

        self.attributes_list = self._make_field_list()
        col_layout.addWidget(self.attributes_list, stretch=1)

        col_layout.addSpacing(8)

        meas_header = QLabel("MEASURES")
        meas_header.setObjectName("sectionHeader")
        col_layout.addWidget(meas_header)

        self.measures_avail_list = self._make_field_list()
        col_layout.addWidget(self.measures_avail_list, stretch=1)

        return field_panel

    def _make_field_list(self) -> QListWidget:
        list_widget = QListWidget()
        list_widget.setObjectName("dragSourceList")
        list_widget.setMinimumWidth(150)
        list_widget.setMinimumHeight(120)
        list_widget.setSpacing(2)
        list_widget.setUniformItemSizes(True)
        list_widget.setDragEnabled(True)
        list_widget.setAcceptDrops(False)
        list_widget.setDefaultDropAction(Qt.CopyAction)
        list_widget.viewport().setCursor(Qt.OpenHandCursor)
        list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        list_widget.customContextMenuRequested.connect(
            lambda pos, lw=list_widget: self._show_avail_context_menu(pos, lw)
        )
        return list_widget

    def _populate_field_lists(self) -> None:
        for col, dtype in zip(self.df.columns, self.df.dtypes):
            item = QListWidgetItem(col)
            item.setToolTip(f"{col} ({dtype})")
            row_height = self.attributes_list.fontMetrics().height() + 10
            item.setSizeHint(QSize(0, row_height))
            if dtype in pl.NUMERIC_DTYPES:
                self.measures_avail_list.addItem(item)
            else:
                self.attributes_list.addItem(item)

    def _build_settings_panel(self) -> QFrame:
        settings_panel = QFrame()
        settings_panel.setObjectName("settingsPanel")
        layout = QVBoxLayout(settings_panel)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        self.x_header = QLabel("X-AXIS")
        self.x_header.setObjectName("sectionHeader")
        layout.addWidget(self.x_header)
        self.x_list = _VisualizeDropZone("Drop a field here", max_height=36)
        self.x_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.x_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.x_list, "X")
        )
        self.x_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_x_items_inserted)
        )
        self.x_list.model().rowsRemoved.connect(
            lambda: QTimer.singleShot(0, self._request_aggregation)
        )
        layout.addWidget(self.x_list)

        self.rows_header = QLabel("ROWS")
        self.rows_header.setObjectName("sectionHeader")
        layout.addWidget(self.rows_header)
        self.rows_list = _VisualizeDropZone("Drop a field here", max_height=36)
        self.rows_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.rows_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.rows_list, "Rows")
        )
        self.rows_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_rows_items_inserted)
        )
        self.rows_list.model().rowsRemoved.connect(
            lambda: QTimer.singleShot(0, self._request_aggregation)
        )
        layout.addWidget(self.rows_list)

        self.y_header = QLabel("Y-AXIS")
        self.y_header.setObjectName("sectionHeader")
        layout.addWidget(self.y_header)
        self.y_list = _VisualizeDropZone("Drop measures here", max_height=80)
        self.y_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.y_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.y_list, "Y")
        )
        self.y_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_y_items_inserted)
        )
        self.y_list.model().rowsRemoved.connect(
            lambda: QTimer.singleShot(0, self._request_aggregation)
        )
        layout.addWidget(self.y_list)

        filter_header = QLabel("FILTERS")
        filter_header.setObjectName("sectionHeader")
        layout.addWidget(filter_header)
        self.filters_list = _VisualizeDropZone("Drop fields to filter", max_height=80)
        self.filters_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.filters_list.customContextMenuRequested.connect(
            lambda pos: self._show_dropzone_context_menu(pos, self.filters_list, "Filter")
        )
        self.filters_list.model().rowsInserted.connect(
            lambda: QTimer.singleShot(0, self._on_filter_items_inserted)
        )
        self.filters_list.model().rowsRemoved.connect(
            lambda: QTimer.singleShot(0, self._sync_filters)
        )
        layout.addWidget(self.filters_list)

        layout.addStretch()
        return settings_panel

    def _build_chart_type_bar(self) -> QHBoxLayout:
        chart_type_layout = QHBoxLayout()
        chart_type_layout.setSpacing(0)

        self.chart_type_group = QButtonGroup(self)
        self.chart_type_group.setExclusive(True)
        self._chart_type_buttons: dict[str, QPushButton] = {}

        for i, (code, label, icon_name) in enumerate(_CHART_TYPES):
            btn = QPushButton()
            try:
                btn.setIcon(qta.icon(icon_name, color=self._text_color))
            except Exception:
                # Fallback: best-effort fontawesome icon if mdi name is missing
                btn.setIcon(qta.icon("fa5s.chart-bar", color=self._text_color))
            btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.setProperty("chartTypeCode", code)
            if i == 0:
                btn.setObjectName("chartTypeBtnLeft")
                btn.setChecked(True)
            elif i == len(_CHART_TYPES) - 1:
                btn.setObjectName("chartTypeBtnRight")
            else:
                btn.setObjectName("chartTypeBtnMid")
            self.chart_type_group.addButton(btn)
            chart_type_layout.addWidget(btn)
            self._chart_type_buttons[code] = btn

        self.chart_type_group.buttonClicked.connect(self._on_chart_type_changed)
        return chart_type_layout

    def _build_right_pane(self) -> QVBoxLayout:
        right_pane_layout = QVBoxLayout()
        right_pane_layout.setSpacing(6)

        right_pane_layout.addWidget(self._build_chart_toolbar())

        self.slicer_container = QWidget()
        self.slicer_layout = QHBoxLayout(self.slicer_container)
        self.slicer_layout.setContentsMargins(0, 0, 0, 6)
        self.slicer_layout.setSpacing(8)
        self.slicer_layout.setAlignment(Qt.AlignLeft)
        self.slicer_container.setVisible(False)
        right_pane_layout.addWidget(self.slicer_container)

        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.Antialiasing, True)
        self.chart = QChart()
        self.chart.legend().setVisible(True)
        self.chart_view.setChart(self.chart)
        style_chart(self.chart, bg_color=self._bg_color, text_color=self._text_color)

        self.heatmap_view = HeatmapView()
        self.heatmap_view.set_theme(
            bg_color=self._bg_color,
            text_color=self._text_color,
            accent_color=self._accent_color,
        )

        self.pivot_view = PivotTableView()
        self.pivot_view.set_theme(
            bg_color=self._bg_color,
            text_color=self._text_color,
            accent_color=self._accent_color,
        )

        self.chart_stack = QStackedWidget()
        self.chart_stack.addWidget(self.chart_view)      # index 0
        self.chart_stack.addWidget(self.heatmap_view)    # index 1
        self.chart_stack.addWidget(self.pivot_view)      # index 2
        right_pane_layout.addWidget(self.chart_stack, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("slicerInfoLabel")
        self.status_label.setVisible(False)
        right_pane_layout.addWidget(self.status_label)

        return right_pane_layout

    def _build_chart_toolbar(self) -> QFrame:
        toolbar = QFrame()
        toolbar.setObjectName("chartToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 6)
        toolbar_layout.setSpacing(8)

        toolbar_layout.addLayout(self._build_chart_type_bar())
        toolbar_layout.addStretch()

        self.reset_btn = QPushButton("Reset Visual")
        self.reset_btn.clicked.connect(self._reset_visual)
        toolbar_layout.addWidget(self.reset_btn)

        self.export_btn = QPushButton("Export Visual")
        self.export_btn.clicked.connect(self._export_chart)
        toolbar_layout.addWidget(self.export_btn)

        return toolbar

    # ------------------------------------------------------------------
    # Item-text helpers (preserved from previous implementation)
    # ------------------------------------------------------------------

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

        self._request_aggregation()

    def _on_rows_items_inserted(self) -> None:
        """Keep at most one ROWS item (heatmap second dimension) and normalize text."""
        while self.rows_list.count() > 1:
            self.rows_list.takeItem(0)

        if self.rows_list.count() == 1:
            item = self.rows_list.item(0)
            item.setText(self._clean_item_text(item.text()))

        self._request_aggregation()

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

        self._request_aggregation()

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

    # ------------------------------------------------------------------
    # Slicer (filter) widgets
    # ------------------------------------------------------------------

    def _sync_filters(self) -> None:
        """Synchronize slicer widgets with filter drop-zone items."""
        current_filters: dict[str, str] = {}
        for i in range(self.filters_list.count()):
            text = self.filters_list.item(i).text()
            col = self._clean_item_text(text)
            f_type = (
                text.rsplit(" (", 1)[1].rstrip(")")
                if text.endswith(")") and " (" in text
                else "Drop Down"
            )
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
                widget.currentIndexChanged.connect(self._request_aggregation)
            else:
                widget = MultiselectComboBox(title=col)
                widget.add_items(unique_vals)
                widget.selectionChanged.connect(self._request_aggregation)

            self.slicer_layout.addWidget(widget)
            self.active_filters[col] = (f_type, widget)

        self.slicer_container.setVisible(bool(self.active_filters))

        self._request_aggregation()

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _show_avail_context_menu(self, pos: Any, list_widget: QListWidget) -> None:
        """Show context menu for available attribute/measure items."""
        item = list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        add_x_action = menu.addAction("Add to X-Axis")
        add_rows_action = menu.addAction("Add to Rows (Heatmap)")
        add_y_action = menu.addAction("Add to Y-Axis")
        add_filter_action = menu.addAction("Add to Filters")

        action = menu.exec(list_widget.viewport().mapToGlobal(pos))
        if action == add_x_action:
            self.x_list.addItem(item.text())
        elif action == add_rows_action:
            self.rows_list.addItem(item.text())
        elif action == add_y_action:
            self.y_list.addItem(item.text())
        elif action == add_filter_action:
            self.filters_list.addItem(item.text())

    def _show_dropzone_context_menu(self, pos: Any, list_widget: QListWidget, list_type: str) -> None:
        """Show context menu for X/Rows/Y/filter drop-zone items."""
        item = list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)

        targets: list[tuple[str, QListWidget]] = []
        if list_type != "X":
            targets.append(("X-Axis", self.x_list))
        if list_type != "Rows":
            targets.append(("Rows", self.rows_list))
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
            self._request_aggregation()
        elif action in type_actions:
            new_type = type_actions[action]
            item.setText(f"{self._clean_item_text(item.text())} ({new_type})")
            self._sync_filters()

    # ------------------------------------------------------------------
    # Chart-type and dropzone visibility
    # ------------------------------------------------------------------

    def _on_chart_type_changed(self) -> None:
        btn = self.chart_type_group.checkedButton()
        if btn is None:
            return
        self._chart_type = btn.property("chartTypeCode") or "bar"

        if self._chart_type == "heatmap":
            self.chart_stack.setCurrentWidget(self.heatmap_view)
        elif self._chart_type == "table":
            self.chart_stack.setCurrentWidget(self.pivot_view)
        else:
            self.chart_stack.setCurrentWidget(self.chart_view)

        self._update_dropzone_visibility()
        self._request_aggregation()

    def _update_dropzone_visibility(self) -> None:
        # ROWS dropzone is required for heatmap and optional for table; hidden otherwise.
        show_rows = self._chart_type in ("heatmap", "table")
        self.rows_header.setVisible(show_rows)
        self.rows_list.setVisible(show_rows)

        if self._chart_type in ("heatmap", "table"):
            self.x_header.setText("COLUMNS")
        else:
            self.x_header.setText("X-AXIS")

    # ------------------------------------------------------------------
    # Aggregation pipeline
    # ------------------------------------------------------------------

    def _build_filter_specs(self) -> list[FilterSpec]:
        """Translate live slicer state into FilterSpec objects for the worker."""
        specs: list[FilterSpec] = []
        for col, (f_type, widget) in self.active_filters.items():
            dtype = self.df.schema[col]
            if f_type == "Drop Down":
                value = widget.currentText()
                if value == "(All)":
                    specs.append(FilterSpec(col=col, kind="all"))
                else:
                    casted = pl.Series([value]).cast(dtype, strict=False)[0]
                    specs.append(FilterSpec(col=col, kind="single", values=[casted]))
            else:
                checked = widget.get_checked_items()
                total = widget.model.rowCount() - 1
                if len(checked) == total:
                    specs.append(FilterSpec(col=col, kind="all"))
                elif len(checked) == 0:
                    specs.append(FilterSpec(col=col, kind="multi_none"))
                else:
                    casted_vals = pl.Series(checked).cast(dtype, strict=False).to_list()
                    specs.append(FilterSpec(col=col, kind="multi_partial", values=casted_vals))
        return specs

    def _build_y_items(self) -> list[tuple[str, str]]:
        """Parse Y-list entries into (column, aggregation) pairs, deduplicated."""
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
        return y_items

    def _request_aggregation(self) -> None:
        """Build an AggregationRequest from current selections and ask the worker to run it."""
        if self.x_list.count() == 0 or self.y_list.count() == 0:
            self._render_empty_state("Drop a field on X-Axis and a measure on Y-Axis")
            return

        if self._chart_type == "heatmap" and self.rows_list.count() == 0:
            self._render_empty_state("Heatmap also needs a field in ROWS")
            return

        x_col = self._clean_item_text(self.x_list.item(0).text())
        rows_col = (
            self._clean_item_text(self.rows_list.item(0).text())
            if self._chart_type in ("heatmap", "table") and self.rows_list.count() > 0
            else None
        )

        if rows_col is not None and rows_col == x_col:
            self._render_empty_state(
                "COLUMNS and ROWS must be different fields — pick another for ROWS."
            )
            return
        y_items = self._build_y_items()
        if not y_items:
            self._render_empty_state("Drop a measure on Y-Axis")
            return

        if self._chart_type in ("pie", "donut") and len(y_items) > 1:
            self.status_label.setText(
                "Pie / Donut accept a single measure — showing the first."
            )
            self.status_label.setVisible(True)
            y_items = y_items[:1]
        elif self._chart_type == "heatmap" and len(y_items) > 1:
            self.status_label.setText(
                "Heatmap uses a single measure for color intensity — showing the first."
            )
            self.status_label.setVisible(True)
            y_items = y_items[:1]
        elif self._chart_type == "table" and rows_col is not None and len(y_items) > 1:
            self.status_label.setText(
                "Pivot Table with ROWS uses a single measure — showing the first."
            )
            self.status_label.setVisible(True)
            y_items = y_items[:1]
        else:
            self.status_label.setVisible(False)
            self.status_label.setText("")

        req = AggregationRequest(
            chart_type=self._chart_type,
            x_col=x_col,
            y_items=y_items,
            rows_col=rows_col,
            filters=self._build_filter_specs(),
        )
        self.agg_controller.request(req)

    def _render_empty_state(self, message: str) -> None:
        """Show a placeholder message instead of a chart when configuration is incomplete."""
        if self._chart_type == "heatmap":
            self.heatmap_view.show_message(message)
        elif self._chart_type == "table":
            self.pivot_view.show_message(message)
        else:
            self.chart.removeAllSeries()
            for axis in list(self.chart.axes()):
                self.chart.removeAxis(axis)
            self.chart.setTitle(message)
        self.status_label.setVisible(False)

    def _on_aggregation_result(self, plot_df: pl.DataFrame) -> None:
        """Receive the aggregated DataFrame and dispatch to the right chart builder."""
        if plot_df is None or plot_df.is_empty():
            self._render_empty_state("No data matches the current filters")
            return

        x_col = self._clean_item_text(self.x_list.item(0).text())
        y_items = self._build_y_items()
        chart_type = self._chart_type

        if chart_type == "heatmap":
            if not y_items or self.rows_list.count() == 0:
                return
            rows_col = self._clean_item_text(self.rows_list.item(0).text())
            value_col = f"{y_items[0][0]} ({y_items[0][1]})"
            self.heatmap_view.render_data(
                plot_df,
                x_col=x_col,
                rows_col=rows_col,
                value_col=value_col,
            )
            return

        if chart_type == "table":
            measure_aliases = [f"{c} ({a})" for c, a in y_items]
            if self.rows_list.count() > 0:
                rows_col = self._clean_item_text(self.rows_list.item(0).text())
                value_col = measure_aliases[0]
                self.pivot_view.render_pivot(
                    plot_df,
                    x_col=x_col,
                    rows_col=rows_col,
                    value_col=value_col,
                )
            else:
                self.pivot_view.render_flat(plot_df, x_col=x_col, measure_aliases=measure_aliases)
            return

        # Reset the QChart
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)
        self.chart.setTitle("")

        palette = self._build_palette(len(y_items))

        if chart_type == "bar":
            build_bar(
                self.chart, plot_df, x_col, y_items, palette,
                stacked=False, grid_color=self._grid_color, text_color=self._text_color,
            )
        elif chart_type == "stacked_bar":
            build_bar(
                self.chart, plot_df, x_col, y_items, palette,
                stacked=True, grid_color=self._grid_color, text_color=self._text_color,
            )
        elif chart_type == "line":
            build_line(
                self.chart, plot_df, x_col, y_items, palette,
                grid_color=self._grid_color, text_color=self._text_color,
            )
        elif chart_type == "area":
            build_area(
                self.chart, plot_df, x_col, y_items, palette,
                stacked=False, grid_color=self._grid_color, text_color=self._text_color,
            )
        elif chart_type == "stacked_area":
            build_area(
                self.chart, plot_df, x_col, y_items, palette,
                stacked=True, grid_color=self._grid_color, text_color=self._text_color,
            )
        elif chart_type == "scatter":
            build_scatter(
                self.chart, plot_df, x_col, y_items, palette,
                grid_color=self._grid_color, text_color=self._text_color,
            )
        elif chart_type == "pie":
            build_pie(
                self.chart, plot_df, x_col, y_items[0], palette,
                donut=False, text_color=self._text_color,
            )
        elif chart_type == "donut":
            build_pie(
                self.chart, plot_df, x_col, y_items[0], palette,
                donut=True, text_color=self._text_color,
            )

        # Title
        if len(y_items) == 1:
            col, agg = y_items[0]
            if chart_type in ("pie", "donut"):
                self.chart.setTitle(f"{agg} of {col} by {x_col}")
            else:
                self.chart.setTitle(f"{col} vs {x_col} ({agg})")
        else:
            self.chart.setTitle(f"Multiple Measures vs {x_col}")

        self.chart.legend().setVisible(len(y_items) > 1 or chart_type in ("pie", "donut"))

    def _on_aggregation_failed(self, message: str) -> None:
        """Surface query failures inside the chart area instead of a modal dialog."""
        self._render_empty_state(f"Cannot render chart:\n{message}")

    def _build_palette(self, n_measures: int) -> list[str]:
        """Return a list of color hex strings starting with the theme accent."""
        accent_hex = self._accent_color
        bi_palette = [
            accent_hex,
            "#E65100",
            "#28A745",
            "#6F42C1",
            "#D32F2F",
            "#17A2B8",
            "#FFC107",
            "#7B1FA2",
            "#00897B",
        ]
        # De-dupe accent if it collides with one of the fixed colors.
        seen: set[str] = set()
        deduped: list[str] = []
        for c in bi_palette:
            cu = c.upper()
            if cu in seen:
                continue
            seen.add(cu)
            deduped.append(c)
        if n_measures <= len(deduped):
            return deduped
        return deduped + deduped  # repeat for many-measure cases (rare)

    # ------------------------------------------------------------------
    # Reset / Export
    # ------------------------------------------------------------------

    def _reset_visual(self) -> None:
        """Reset all configured axes and filters and clear the chart canvas."""
        self.x_list.clear()
        self.rows_list.clear()
        self.y_list.clear()
        self.filters_list.clear()
        self._render_empty_state("")

    def _export_chart(self) -> None:
        """Export the current chart to PNG, PDF, or SVG using Qt-native renderers."""
        if self.x_list.count() == 0 or self.y_list.count() == 0:
            QMessageBox.information(self, "Export", "Please plot a chart first before exporting.")
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Visual",
            "",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)",
        )
        if not path:
            return

        if self._chart_type == "heatmap":
            target = self.heatmap_view
        elif self._chart_type == "table":
            target = self.pivot_view
        else:
            target = self.chart_view
        try:
            lower = path.lower()
            if lower.endswith(".png") or "PNG" in selected_filter:
                pixmap = target.grab()
                if not pixmap.save(path, "PNG"):
                    raise RuntimeError("Qt could not save the PNG file.")
            elif lower.endswith(".pdf") or "PDF" in selected_filter:
                writer = QPdfWriter(path)
                writer.setResolution(150)
                painter = QPainter(writer)
                target.render(painter)
                painter.end()
            elif lower.endswith(".svg") or "SVG" in selected_filter:
                generator = QSvgGenerator()
                generator.setFileName(path)
                size = target.size()
                generator.setSize(size)
                generator.setViewBox(target.rect())
                painter = QPainter(generator)
                target.render(painter)
                painter.end()
            else:
                pixmap = target.grab()
                if not pixmap.save(path):
                    raise RuntimeError("Qt could not save the file.")
            QMessageBox.information(self, "Success", f"Chart successfully exported to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to export chart:\n{exc}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        """Tear down the aggregation worker thread before the dialog closes."""
        try:
            self.agg_controller.shutdown()
        except Exception:
            pass
        super().closeEvent(event)
