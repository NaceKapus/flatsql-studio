"""QtCharts builders and a custom HeatmapView for the Visualize dialog.

Each `build_*` function configures a `QChart` for a specific chart type from a
small (already-aggregated) Polars DataFrame. The HeatmapView is a standalone
QGraphicsView since QtCharts has no native heatmap series.
"""

from __future__ import annotations

import math
from typing import Sequence

import polars as pl
from PySide6.QtCharts import (
    QAreaSeries,
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QLineSeries,
    QPieSeries,
    QScatterSeries,
    QStackedBarSeries,
    QValueAxis,
)
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
)


def _alias_for(col: str, agg: str) -> str:
    """Display alias used for an aggregated measure column (matches _visualize_query)."""
    return f"{col} ({agg})"


# ---------------------------------------------------------------------------
# Theme styling
# ---------------------------------------------------------------------------

def style_chart(
    chart: QChart,
    *,
    bg_color: str,
    text_color: str,
) -> None:
    """Apply palette-aligned background, title, and legend styling to the chart."""
    bg = QColor(bg_color)
    text = QColor(text_color)

    chart.setBackgroundBrush(QBrush(bg))
    chart.setBackgroundPen(QPen(bg))
    chart.setPlotAreaBackgroundBrush(QBrush(bg))
    chart.setPlotAreaBackgroundVisible(True)
    chart.setTitleBrush(QBrush(text))
    chart.setMargins(chart.margins())  # respect default margins; QChart picks a sane value

    legend = chart.legend()
    legend.setLabelColor(text)
    legend.setBackgroundVisible(False)
    legend.setAlignment(Qt.AlignBottom)

    chart.setAnimationOptions(QChart.SeriesAnimations)
    chart.setAnimationDuration(350)
    chart.setAnimationEasingCurve(chart.animationEasingCurve())  # default OutQuart-like


def _style_axes(chart: QChart, text_color: str, grid_color: str) -> None:
    """Color the axes labels and grid lines to match the active palette."""
    text = QColor(text_color)
    grid = QColor(grid_color)
    grid.setAlphaF(0.25)

    for axis in chart.axes():
        axis.setLabelsColor(text)
        axis.setTitleBrush(QBrush(text))
        try:
            axis.setGridLinePen(QPen(grid))
        except AttributeError:
            pass
        try:
            line_pen = QPen(text)
            line_pen.setWidthF(0.8)
            axis.setLinePen(line_pen)
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# Tooltip helpers
# ---------------------------------------------------------------------------

def _format_value(v: float) -> str:
    """Format a numeric value for tooltips with sensible precision."""
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 1:
        return f"{v:.2f}"
    return f"{v:.4g}"


def _hook_xy_tooltip(series, label: str, x_categories: Sequence[str]) -> None:
    """Wire a (point, state) hovered signal to a tooltip showing the category name."""
    def _handler(point: QPointF, state: bool) -> None:
        if state:
            idx = int(round(point.x()))
            if 0 <= idx < len(x_categories):
                cat = x_categories[idx]
            else:
                cat = str(point.x())
            QToolTip.showText(QCursor.pos(), f"<b>{label}</b><br>{cat}: {_format_value(point.y())}")
        else:
            QToolTip.hideText()

    series.hovered.connect(_handler)


def _hook_bar_tooltip(series: QBarSeries, x_categories: Sequence[str]) -> None:
    """Tooltip handler for bar/stacked-bar series (signal carries index + barset)."""
    def _handler(status: bool, index: int, barset: QBarSet) -> None:
        if status and 0 <= index < len(x_categories):
            value = barset.at(index)
            QToolTip.showText(
                QCursor.pos(),
                f"<b>{barset.label()}</b><br>{x_categories[index]}: {_format_value(value)}",
            )
        else:
            QToolTip.hideText()

    series.hovered.connect(_handler)


def _hook_pie_tooltip(series: QPieSeries, total: float) -> None:
    """Tooltip handler for pie/donut slices including share-of-total %."""
    def _handler(slice_, state: bool) -> None:
        if state and total > 0:
            pct = 100.0 * slice_.value() / total
            QToolTip.showText(
                QCursor.pos(),
                f"<b>{slice_.label()}</b><br>{_format_value(slice_.value())} ({pct:.1f}%)",
            )
        else:
            QToolTip.hideText()

    series.hovered.connect(_handler)


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _category_labels(plot_df: pl.DataFrame, x_col: str) -> list[str]:
    """Stringify the X column so QBarCategoryAxis can label the ticks."""
    return [str(v) for v in plot_df[x_col].to_list()]


def _measure_values(plot_df: pl.DataFrame, alias: str) -> list[float]:
    """Pull a measure column out as floats with NULLs coerced to 0.0 for plotting."""
    return [float(v) if v is not None else 0.0 for v in plot_df[alias].to_list()]


def _attach_xy_axes(
    chart: QChart,
    categories: Sequence[str],
    *,
    rotate_labels: bool,
) -> tuple[QBarCategoryAxis, QValueAxis]:
    """Attach a categorical X-axis and a numeric Y-axis, return them for further styling."""
    axis_x = QBarCategoryAxis()
    axis_x.append(list(categories))
    if rotate_labels:
        axis_x.setLabelsAngle(-45)

    axis_y = QValueAxis()
    axis_y.applyNiceNumbers()

    chart.addAxis(axis_x, Qt.AlignBottom)
    chart.addAxis(axis_y, Qt.AlignLeft)
    for s in chart.series():
        s.attachAxis(axis_x)
        s.attachAxis(axis_y)
    return axis_x, axis_y


def build_bar(
    chart: QChart,
    plot_df: pl.DataFrame,
    x_col: str,
    y_items: list[tuple[str, str]],
    palette: Sequence[str],
    *,
    stacked: bool,
    grid_color: str,
    text_color: str,
) -> None:
    """Render a grouped or stacked bar chart."""
    series: QBarSeries = QStackedBarSeries() if stacked else QBarSeries()
    series.setLabelsVisible(False)

    categories = _category_labels(plot_df, x_col)

    for i, (col, agg) in enumerate(y_items):
        alias = _alias_for(col, agg)
        bs = QBarSet(alias)
        color = QColor(palette[i % len(palette)])
        bs.setColor(color)
        bs.setBorderColor(color)
        for v in _measure_values(plot_df, alias):
            bs.append(v)
        series.append(bs)

    chart.addSeries(series)
    _attach_xy_axes(chart, categories, rotate_labels=len(categories) > 5)
    _style_axes(chart, text_color, grid_color)
    _hook_bar_tooltip(series, categories)


def build_line(
    chart: QChart,
    plot_df: pl.DataFrame,
    x_col: str,
    y_items: list[tuple[str, str]],
    palette: Sequence[str],
    *,
    grid_color: str,
    text_color: str,
) -> None:
    """Render a line chart with one QLineSeries per measure."""
    categories = _category_labels(plot_df, x_col)

    for i, (col, agg) in enumerate(y_items):
        alias = _alias_for(col, agg)
        line = QLineSeries()
        line.setName(alias)
        line.setPointsVisible(True)
        color = QColor(palette[i % len(palette)])
        pen = QPen(color)
        pen.setWidth(2)
        line.setPen(pen)
        for j, v in enumerate(_measure_values(plot_df, alias)):
            line.append(j, v)
        chart.addSeries(line)
        _hook_xy_tooltip(line, alias, categories)

    _attach_xy_axes(chart, categories, rotate_labels=len(categories) > 5)
    _style_axes(chart, text_color, grid_color)


def build_area(
    chart: QChart,
    plot_df: pl.DataFrame,
    x_col: str,
    y_items: list[tuple[str, str]],
    palette: Sequence[str],
    *,
    stacked: bool,
    grid_color: str,
    text_color: str,
) -> None:
    """Render an area chart, optionally stacked."""
    categories = _category_labels(plot_df, x_col)
    n = len(categories)

    lower_running = [0.0] * n
    for i, (col, agg) in enumerate(y_items):
        alias = _alias_for(col, agg)
        upper_vals = _measure_values(plot_df, alias)

        if stacked:
            new_upper = [lower_running[j] + upper_vals[j] for j in range(n)]
            lower_line = QLineSeries()
            for j, v in enumerate(lower_running):
                lower_line.append(j, v)
            upper_line = QLineSeries()
            for j, v in enumerate(new_upper):
                upper_line.append(j, v)
            area = QAreaSeries(upper_line, lower_line)
            # Re-parent the line series so they are not garbage-collected when this
            # function returns. QAreaSeries does not take ownership in C++ Qt.
            upper_line.setParent(area)
            lower_line.setParent(area)
            lower_running = new_upper
        else:
            upper_line = QLineSeries()
            for j, v in enumerate(upper_vals):
                upper_line.append(j, v)
            area = QAreaSeries(upper_line)
            upper_line.setParent(area)

        area.setName(alias)
        color = QColor(palette[i % len(palette)])
        fill = QColor(color)
        fill.setAlpha(180 if stacked else 130)
        area.setBrush(QBrush(fill))
        area.setPen(QPen(color))
        chart.addSeries(area)
        _hook_xy_tooltip(area, alias, categories)

    _attach_xy_axes(chart, categories, rotate_labels=len(categories) > 5)
    _style_axes(chart, text_color, grid_color)


def build_scatter(
    chart: QChart,
    plot_df: pl.DataFrame,
    x_col: str,
    y_items: list[tuple[str, str]],
    palette: Sequence[str],
    *,
    grid_color: str,
    text_color: str,
) -> None:
    """Render a scatter chart with one QScatterSeries per measure."""
    categories = _category_labels(plot_df, x_col)
    n = len(categories)

    for i, (col, agg) in enumerate(y_items):
        alias = _alias_for(col, agg)
        scatter = QScatterSeries()
        scatter.setName(alias)
        color = QColor(palette[i % len(palette)])
        scatter.setColor(color)
        scatter.setBorderColor(color)
        scatter.setMarkerSize(9.0)
        for j, v in enumerate(_measure_values(plot_df, alias)):
            scatter.append(j, v)
        if n > 5000:
            scatter.setUseOpenGL(True)
        chart.addSeries(scatter)
        _hook_xy_tooltip(scatter, alias, categories)

    _attach_xy_axes(chart, categories, rotate_labels=n > 5)
    _style_axes(chart, text_color, grid_color)


def build_pie(
    chart: QChart,
    plot_df: pl.DataFrame,
    x_col: str,
    y_item: tuple[str, str],
    palette: Sequence[str],
    *,
    donut: bool,
    text_color: str,
) -> None:
    """Render a pie or donut chart for a single measure."""
    col, agg = y_item
    alias = _alias_for(col, agg)

    series = QPieSeries()
    if donut:
        series.setHoleSize(0.45)
    series.setPieSize(0.78)

    labels = plot_df[x_col].to_list()
    values = plot_df[alias].to_list()
    total = float(sum(v for v in values if v is not None and v > 0))

    for i, (label, value) in enumerate(zip(labels, values)):
        if value is None or value <= 0:
            continue
        slice_ = series.append(str(label), float(value))
        color = QColor(palette[i % len(palette)])
        slice_.setColor(color)
        slice_.setBorderColor(color)
        slice_.setLabelVisible(True)
        slice_.setLabelArmLengthFactor(0.12)
        slice_.setLabelColor(QColor(text_color))

    chart.addSeries(series)
    _hook_pie_tooltip(series, total)


# ---------------------------------------------------------------------------
# Heatmap (custom QGraphicsView; QtCharts has no native heatmap)
# ---------------------------------------------------------------------------

class HeatmapView(QGraphicsView):
    """Custom heatmap renderer driven by an aggregated 3-column DataFrame."""

    PADDING = 8
    COLORBAR_WIDTH = 12
    COLORBAR_GAP = 10
    COLORBAR_LABEL_GAP = 4
    LABEL_GAP = 8
    ROTATE_THRESHOLD = 0.95  # rotate column labels when they are wider than this fraction of cell_w

    def __init__(self, parent=None) -> None:
        """Initialize an empty heatmap view with palette defaults."""
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)

        self._plot_df: pl.DataFrame | None = None
        self._x_col = ""
        self._rows_col = ""
        self._value_col = ""
        self._title = ""

        self._bg_color = QColor("#1e1e1e")
        self._text_color = QColor("#ffffff")
        self._accent_color = QColor("#4f9de9")

        self.setBackgroundBrush(QBrush(self._bg_color))

    def set_theme(self, *, bg_color: str, text_color: str, accent_color: str) -> None:
        """Update background, text, and accent colors used for cells and labels."""
        self._bg_color = QColor(bg_color)
        self._text_color = QColor(text_color)
        self._accent_color = QColor(accent_color)
        self.setBackgroundBrush(QBrush(self._bg_color))
        self._redraw()

    def render_data(
        self,
        plot_df: pl.DataFrame,
        x_col: str,
        rows_col: str,
        value_col: str,
        title: str = "",
    ) -> None:
        """Replace the displayed heatmap with the given aggregated data."""
        self._plot_df = plot_df
        self._x_col = x_col
        self._rows_col = rows_col
        self._value_col = value_col
        self._title = title
        self._redraw()

    def clear_chart(self) -> None:
        """Drop the rendered heatmap and clear the scene."""
        self._plot_df = None
        self._scene.clear()

    def show_message(self, message: str) -> None:
        """Display a centered placeholder message instead of a heatmap."""
        self._plot_df = None
        self._scene.clear()
        text = self._scene.addText(message, QFont())
        text.setDefaultTextColor(self._text_color)
        br = text.boundingRect()
        text.setPos(
            max(0.0, (self.viewport().width() - br.width()) / 2),
            max(0.0, (self.viewport().height() - br.height()) / 2),
        )
        self._scene.setSceneRect(0, 0, self.viewport().width(), self.viewport().height())

    def resizeEvent(self, event) -> None:
        """Rerender on resize so cells fill the available area."""
        super().resizeEvent(event)
        if self._plot_df is not None:
            self._redraw()

    def _lerp_color(self, t: float) -> QColor:
        """Interpolate cell color from the background tone to the accent."""
        t = max(0.0, min(1.0, t))
        r = int(self._bg_color.red() + (self._accent_color.red() - self._bg_color.red()) * t)
        g = int(self._bg_color.green() + (self._accent_color.green() - self._bg_color.green()) * t)
        b = int(self._bg_color.blue() + (self._accent_color.blue() - self._bg_color.blue()) * t)
        return QColor(r, g, b)

    def _redraw(self) -> None:
        self._scene.clear()
        if self._plot_df is None or self._plot_df.is_empty():
            return

        df = self._plot_df
        x_vals = [str(v) for v in df[self._x_col].to_list()]
        row_vals = [str(v) for v in df[self._rows_col].to_list()]
        v_vals = df[self._value_col].to_list()

        unique_cols = sorted(set(x_vals))
        unique_rows = sorted(set(row_vals))
        col_idx = {c: i for i, c in enumerate(unique_cols)}
        row_idx = {r: i for i, r in enumerate(unique_rows)}

        cell_map: dict[tuple[int, int], float] = {}
        for x, r, v in zip(x_vals, row_vals, v_vals):
            if v is None:
                continue
            cell_map[(col_idx[x], row_idx[r])] = float(v)

        if not cell_map:
            self.show_message("No data to display")
            return

        vmin = min(cell_map.values())
        vmax = max(cell_map.values())
        vrange = vmax - vmin if vmax > vmin else 1.0

        font = QFont()
        fm = QFontMetrics(font)
        text_h = fm.height()

        # Compute label-driven margins so nothing gets clipped.
        longest_row_label = max((fm.horizontalAdvance(r) for r in unique_rows), default=0)
        longest_col_label = max((fm.horizontalAdvance(c) for c in unique_cols), default=0)
        max_value_label_w = max(
            fm.horizontalAdvance(_format_value(vmin)),
            fm.horizontalAdvance(_format_value(vmax)),
        )

        margin_left = self.PADDING + longest_row_label + self.LABEL_GAP
        margin_top = self.PADDING + text_h // 2  # leave room so first row label isn't clipped at top
        margin_right = self.PADDING + self.COLORBAR_GAP + self.COLORBAR_WIDTH + self.COLORBAR_LABEL_GAP + max_value_label_w + self.PADDING

        view_w = self.viewport().width()
        view_h = self.viewport().height()

        # Tentative bottom margin assuming horizontal column labels.
        margin_bottom_h = self.PADDING + text_h + self.LABEL_GAP
        plot_w = max(50.0, view_w - margin_left - margin_right)
        cell_w = plot_w / max(1, len(unique_cols))

        # Decide rotation: if even one label is wider than ~95% of cell_w, rotate them all.
        rotate = longest_col_label > cell_w * self.ROTATE_THRESHOLD
        if rotate:
            # Rotated label height = projected width of the longest label along Y after a -45° rotation.
            rotated_h = int(longest_col_label * math.sin(math.radians(45))) + text_h
            margin_bottom = self.PADDING + rotated_h + self.LABEL_GAP // 2
        else:
            margin_bottom = margin_bottom_h

        plot_h = max(50.0, view_h - margin_top - margin_bottom)
        cell_h = plot_h / max(1, len(unique_rows))

        # Cells.
        for (ci, ri), value in cell_map.items():
            t = (value - vmin) / vrange
            color = self._lerp_color(t)
            x = margin_left + ci * cell_w
            y = margin_top + (len(unique_rows) - 1 - ri) * cell_h
            rect = QGraphicsRectItem(x + 1, y + 1, cell_w - 2, cell_h - 2)
            rect.setBrush(QBrush(color))
            rect.setPen(Qt.NoPen)
            rect.setToolTip(
                f"{self._x_col}: {unique_cols[ci]}\n"
                f"{self._rows_col}: {unique_rows[ri]}\n"
                f"{self._value_col}: {_format_value(value)}"
            )
            rect.setAcceptHoverEvents(True)
            self._scene.addItem(rect)

        # Row labels (left side).
        for r, ri in row_idx.items():
            text_item = self._scene.addText(str(r), font)
            text_item.setDefaultTextColor(self._text_color)
            br = text_item.boundingRect()
            text_item.setPos(
                margin_left - br.width() - self.LABEL_GAP,
                margin_top + (len(unique_rows) - 1 - ri) * cell_h + (cell_h - br.height()) / 2,
            )

        # Column labels (bottom). Rotate via transformOrigin so the anchor is the top-left of the text
        # and the label hangs below the cell with the right end pinned to the cell's center.
        for c, ci in col_idx.items():
            text_item = self._scene.addText(str(c), font)
            text_item.setDefaultTextColor(self._text_color)
            br = text_item.boundingRect()
            label_top = margin_top + plot_h + self.LABEL_GAP // 2
            cell_center_x = margin_left + ci * cell_w + cell_w / 2
            if rotate:
                # Place the right edge of the label under the cell center, then rotate -45° around that point.
                text_item.setTransformOriginPoint(br.width(), 0)
                text_item.setRotation(-45)
                text_item.setPos(cell_center_x - br.width(), label_top)
            else:
                text_item.setPos(cell_center_x - br.width() / 2, label_top)

        self._draw_colorbar(margin_left + plot_w, margin_top, plot_h, vmin, vmax, font, fm)
        self._scene.setSceneRect(0, 0, view_w, view_h)

    def _draw_colorbar(
        self,
        plot_right: float,
        plot_top: float,
        plot_h: float,
        vmin: float,
        vmax: float,
        font: QFont,
        fm: QFontMetrics,
    ) -> None:
        """Render a slim vertical colorbar with min/max value labels at the bar tips."""
        bar_x = plot_right + self.COLORBAR_GAP
        bar_y = plot_top
        bar_w = float(self.COLORBAR_WIDTH)
        bar_h = plot_h
        steps = 32
        for i in range(steps):
            t = 1.0 - i / max(1, steps - 1)
            color = self._lerp_color(t)
            seg_y = bar_y + (i / steps) * bar_h
            seg = QGraphicsRectItem(bar_x, seg_y, bar_w, bar_h / steps + 0.5)
            seg.setBrush(QBrush(color))
            seg.setPen(Qt.NoPen)
            self._scene.addItem(seg)

        text_h = fm.height()
        label_x = bar_x + bar_w + self.COLORBAR_LABEL_GAP

        max_label = self._scene.addText(_format_value(vmax), font)
        max_label.setDefaultTextColor(self._text_color)
        max_label.setPos(label_x, bar_y - text_h / 4)

        min_label = self._scene.addText(_format_value(vmin), font)
        min_label.setDefaultTextColor(self._text_color)
        min_label.setPos(label_x, bar_y + bar_h - text_h * 3 / 4)


# ---------------------------------------------------------------------------
# Pivot table (BI-style cross-tab using QTableWidget)
# ---------------------------------------------------------------------------

class PivotTableView(QTableWidget):
    """Cross-tab pivot driven by a long-format aggregated DataFrame.

    Two modes:
    * Flat: only `x_col` is set → renders as a 2-column table (X, measure).
    * Pivot: both `x_col` and `rows_col` are set → wide table with column totals
      and row totals, cells lerp-tinted by the active accent color.
    """

    def __init__(self, parent=None) -> None:
        """Initialize an empty, non-editable pivot table."""
        super().__init__(parent)
        self.setObjectName("pivotTableView")
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setShowGrid(True)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        self._accent = QColor("#4f9de9")
        self._bg = QColor("#1e1e1e")
        self._text = QColor("#ffffff")

    def set_theme(self, *, bg_color: str, text_color: str, accent_color: str) -> None:
        """Update colors used to tint pivot cells based on cell magnitude."""
        self._bg = QColor(bg_color)
        self._text = QColor(text_color)
        self._accent = QColor(accent_color)

    def show_message(self, message: str) -> None:
        """Replace the table with a single placeholder cell."""
        self.clear()
        self.setRowCount(1)
        self.setColumnCount(1)
        self.setHorizontalHeaderLabels([""])
        self.setVerticalHeaderLabels([""])
        item = QTableWidgetItem(message)
        item.setTextAlignment(Qt.AlignCenter)
        self.setItem(0, 0, item)

    def render_flat(
        self,
        plot_df: pl.DataFrame,
        x_col: str,
        measure_aliases: Sequence[str],
    ) -> None:
        """Render a flat aggregated table: one row per X category, one col per measure."""
        self.clear()
        self.setRowCount(plot_df.height + (1 if plot_df.height > 0 else 0))
        self.setColumnCount(1 + len(measure_aliases))
        self.setHorizontalHeaderLabels([x_col, *measure_aliases])
        self.setVerticalHeaderLabels([""] * self.rowCount())

        for r in range(plot_df.height):
            x_item = QTableWidgetItem(str(plot_df[x_col][r]))
            self.setItem(r, 0, x_item)
            for c, alias in enumerate(measure_aliases, start=1):
                val = plot_df[alias][r]
                fval = float(val) if val is not None else 0.0
                cell = QTableWidgetItem(_format_value(fval))
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.setItem(r, c, cell)

        # Totals row.
        if plot_df.height > 0:
            total_row = self.rowCount() - 1
            self.setItem(total_row, 0, self._bold_item("Total"))
            for c, alias in enumerate(measure_aliases, start=1):
                total = float(sum(v for v in plot_df[alias].to_list() if v is not None))
                cell = self._bold_item(_format_value(total))
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.setItem(total_row, c, cell)

    def render_pivot(
        self,
        plot_df: pl.DataFrame,
        x_col: str,
        rows_col: str,
        value_col: str,
    ) -> None:
        """Pivot a long-format DF into a cross-tab with row and column totals."""
        self.clear()
        if plot_df.is_empty():
            self.show_message("No data to display")
            return

        try:
            wide = plot_df.pivot(index=rows_col, on=x_col, values=value_col)
        except Exception:
            wide = plot_df.pivot(index=rows_col, columns=x_col, values=value_col)

        wide = wide.sort(rows_col)

        col_names = [c for c in wide.columns if c != rows_col]
        n_rows = wide.height
        n_cols = len(col_names)

        self.setRowCount(n_rows + 1)  # +1 for totals row
        self.setColumnCount(n_cols + 2)  # rows label + values + total
        self.setHorizontalHeaderLabels([rows_col, *col_names, "Total"])
        self.setVerticalHeaderLabels([""] * (n_rows + 1))

        # Compute min/max across cells to drive cell tinting.
        all_values: list[float] = []
        for col in col_names:
            for v in wide[col].to_list():
                if v is not None:
                    all_values.append(float(v))
        vmin = min(all_values) if all_values else 0.0
        vmax = max(all_values) if all_values else 1.0
        vrange = vmax - vmin if vmax > vmin else 1.0

        col_totals = [0.0] * n_cols
        grand_total = 0.0

        for r in range(n_rows):
            row_label_item = QTableWidgetItem(str(wide[rows_col][r]))
            row_label_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.setItem(r, 0, row_label_item)

            row_total = 0.0
            for c, col_name in enumerate(col_names, start=1):
                v = wide[col_name][r]
                if v is None:
                    cell = QTableWidgetItem("")
                else:
                    fv = float(v)
                    cell = QTableWidgetItem(_format_value(fv))
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    t = (fv - vmin) / vrange
                    cell.setBackground(QBrush(self._lerp_cell(t)))
                    row_total += fv
                    col_totals[c - 1] += fv
                self.setItem(r, c, cell)

            grand_total += row_total
            total_cell = self._bold_item(_format_value(row_total))
            total_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(r, n_cols + 1, total_cell)

        # Totals row.
        self.setItem(n_rows, 0, self._bold_item("Total"))
        for c, total in enumerate(col_totals, start=1):
            cell = self._bold_item(_format_value(total))
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(n_rows, c, cell)
        grand_cell = self._bold_item(_format_value(grand_total))
        grand_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(n_rows, n_cols + 1, grand_cell)

    def _bold_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    def _lerp_cell(self, t: float) -> QColor:
        """Light tint from base background to accent (~28% max alpha) for cell shading."""
        t = max(0.0, min(1.0, t))
        # Use accent at ~28% over the alternate-base background; we paint via the item background.
        color = QColor(self._accent)
        color.setAlphaF(0.10 + 0.22 * t)
        return color
