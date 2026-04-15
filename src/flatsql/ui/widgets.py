"""Custom PySide6 widgets for visualization, filtering, and data exploration.

Provides specialized Qt widgets including multiselect dropdowns, drag-drop zones,
tab widgets with file support, custom tree views, visualization cards, and flow layouts.
"""
from __future__ import annotations

from typing import Any

import polars as pl
import qtawesome as qta
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QPainter, QColor, QPen, QPalette, QStandardItemModel, QStandardItem
from PySide6.QtCore import Signal, Qt, QRect, QPoint, QSize, QEvent


class DownwardComboBox(QComboBox):
    """A custom QComboBox with a consistent app-wide default width."""

    DEFAULT_WIDTH = 204

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the combobox with the standard FlatSQL sizing behavior."""
        super().__init__(parent)
        self.setMinimumWidth(self.DEFAULT_WIDTH)
        self.setMaximumWidth(self.DEFAULT_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.view().setMinimumWidth(self.DEFAULT_WIDTH)

    def showPopup(self) -> None:
        """Override to position popup below the combobox regardless of screen space."""
        super().showPopup()
        popup = self.view().parentWidget()
        point = self.mapToGlobal(self.rect().bottomLeft())
        popup.move(point)


class MultiselectComboBox(DownwardComboBox):
    """A multiselect combobox widget with checkboxes and a Select All option."""

    selectionChanged = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        """Initialize the multiselect combobox with a title and parent widget.
        
        Args:
            title: Display title shown in the combobox display area.
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.title = title
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setText(f"{title} (All)")
        
        self.model = QStandardItemModel(self)
        self.setModel(self.model)
        self.view().viewport().installEventFilter(self)
        self._updating = False

    def eventFilter(self, widget: QWidget, event: QEvent) -> bool:
        """Intercept mouse clicks to toggle checkboxes without closing the popup.
        
        Args:
            widget: The widget being filtered.
            event: The event to filter.
            
        Returns:
            True if event was handled, False otherwise.
        """
        if event.type() == QEvent.MouseButtonRelease:
            index = self.view().indexAt(event.pos())
            if index.isValid():
                item = self.model.itemFromIndex(index)
                self._toggle_item(item)
                return True
        return super().eventFilter(widget, event)

    def _toggle_item(self, item: QStandardItem) -> None:
        """Toggle the checked state of an item and update Select All state.
        
        Args:
            item: The item to toggle.
        """
        if self._updating:
            return
        self._updating = True
        
        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        item.setCheckState(new_state)
        
        if item.row() == 0:
            for i in range(1, self.model.rowCount()):
                self.model.item(i).setCheckState(new_state)
        else:
            all_checked = True
            any_checked = False
            for i in range(1, self.model.rowCount()):
                if self.model.item(i).checkState() == Qt.Checked:
                    any_checked = True
                else:
                    all_checked = False
                    
            select_all_item = self.model.item(0)
            if all_checked:
                select_all_item.setCheckState(Qt.Checked)
            elif any_checked:
                select_all_item.setCheckState(Qt.PartiallyChecked)
            else:
                select_all_item.setCheckState(Qt.Unchecked)
                
        self._update_text()
        self._updating = False
        self.selectionChanged.emit()

    def add_items(self, items: list[str]) -> None:
        """Add items to the combobox with automatic width adjustment.
        
        Args:
            items: List of item strings to add.
        """
        select_all = QStandardItem("(Select All)")
        select_all.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        select_all.setCheckState(Qt.Checked)
        self.model.appendRow(select_all)
        
        fm = self.fontMetrics()
        max_width = fm.horizontalAdvance(f"{self.title} (All)")
        
        for text in items:
            text_str = str(text)
            item = QStandardItem(text_str)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.model.appendRow(item)
            
            item_width = fm.horizontalAdvance(text_str)
            if item_width > max_width:
                max_width = item_width
                
        self.view().setMinimumWidth(max_width + 50)
            
    def get_checked_items(self) -> list[str]:
        """Return list of currently checked items (excluding Select All).
        
        Returns:
            List of checked item strings.
        """
        return [self.model.item(i).text() for i in range(1, self.model.rowCount()) 
                if self.model.item(i).checkState() == Qt.Checked]

    def _update_text(self) -> None:
        """Update the display text to show selection status."""
        checked_count = len(self.get_checked_items())
        total_count = self.model.rowCount() - 1
        if checked_count == total_count:
            self.lineEdit().setText(f"{self.title} (All)")
        elif checked_count == 0:
            self.lineEdit().setText(f"{self.title} (None)")
        else:
            self.lineEdit().setText(f"{self.title} ({checked_count} selected)")


class DropZoneList(QListWidget):
    """A list widget designed for drag-drop operations with Delete key support."""

    def __init__(self, max_height: int = 70, parent: QWidget | None = None) -> None:
        """Initialize the drop zone list with drag-drop support.
        
        Args:
            max_height: Maximum height of the widget in pixels (default: 70).
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.setMaximumHeight(max_height)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setObjectName("dropZoneList")

    def keyPressEvent(self, event: QEvent) -> None:
        """Handle Delete/Backspace to remove selected items.
        
        Args:
            event: The key press event.
        """
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            for item in self.selectedItems():
                self.takeItem(self.row(item))
        else:
            super().keyPressEvent(event)


class QueryEmptyState(QFrame):
    """Centered empty state shown when the query area has no open tabs."""

    fileDropped = Signal(str)
    newQueryRequested = Signal()
    openFileRequested = Signal()

    def __init__(self, theme_colors: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        """Initialize the welcome panel with drag-drop messaging and actions."""
        super().__init__(parent)
        self.theme_colors = theme_colors or {}
        self._drag_active = False
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.NoFrame)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 8, 24, 40)
        outer_layout.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("queryEmptyStateCard")
        self.card.setProperty("dragActive", False)
        self.card.setFrameShape(QFrame.NoFrame)
        self.card.setMinimumWidth(380)
        self.card.setMaximumWidth(520)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 22, 24, 22)
        card_layout.setSpacing(10)
        card_layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel(alignment=Qt.AlignCenter)
        card_layout.addWidget(self.icon_label)

        self.title_label = QLabel("Drop a file to get started")
        self.title_label.setObjectName("queryEmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        card_layout.addWidget(self.title_label)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)
        actions_layout.setAlignment(Qt.AlignCenter)

        self.new_query_button = QPushButton("New Query")
        self.new_query_button.setObjectName("queryEmptyStatePrimaryButton")
        self.open_file_button = QPushButton("Open File")
        self.open_file_button.setObjectName("queryEmptyStateSecondaryButton")
        self.new_query_button.clicked.connect(self.newQueryRequested.emit)
        self.open_file_button.clicked.connect(self.openFileRequested.emit)
        actions_layout.addWidget(self.new_query_button)
        actions_layout.addWidget(self.open_file_button)
        card_layout.addLayout(actions_layout)

        outer_layout.addWidget(self.card, 0, Qt.AlignHCenter | Qt.AlignTop)
        outer_layout.addStretch(2)

        self.update_theme()

    def update_theme(self) -> None:
        """Refresh iconography and stateful styling for the themed drop zone."""
        palette = self.palette()
        icon_color = self.theme_colors.get("icon", palette.color(QPalette.ButtonText).name())

        self.icon_label.setPixmap(qta.icon("fa5s.file-import", color=icon_color).pixmap(42, 42))
        self.new_query_button.setIcon(qta.icon("fa5s.plus-square", color=icon_color))
        self.open_file_button.setIcon(qta.icon("fa5s.folder-open", color=icon_color))

        self.card.setProperty("dragActive", self._drag_active)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        self.card.update()

    def changeEvent(self, event: QEvent) -> None:
        """Refresh the empty-state styling when the application palette changes."""
        super().changeEvent(event)
        if event.type() in (QEvent.PaletteChange, QEvent.StyleChange):
            self.update_theme()

    def dragEnterEvent(self, event: QEvent) -> None:
        """Accept file or text drags and highlight the drop zone."""
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            self._drag_active = True
            self.update_theme()
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QEvent) -> None:
        """Keep accepting supported drags while hovering over the drop zone."""
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QEvent) -> None:
        """Remove the active drag highlight when the pointer leaves the drop zone."""
        self._drag_active = False
        self.update_theme()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QEvent) -> None:
        """Emit dropped files or text so the existing query flow can handle them."""
        self._drag_active = False
        self.update_theme()

        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            self.fileDropped.emit(url.toLocalFile() if url.isLocalFile() else url.toString())
            event.acceptProposedAction()
            return

        if event.mimeData().hasText():
            text = event.mimeData().text().splitlines()[0]
            self.fileDropped.emit(text)
            event.acceptProposedAction()
            return

        super().dropEvent(event)


class QueryTabWidget(QTabWidget):
    """A tab widget that supports file drag-drop and middle-click detection."""

    fileDropped = Signal(str)
    tabMiddleClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the query tab widget with drag-drop and event filtering.
        
        Args:
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.tabBar().installEventFilter(self)

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """Detect middle-click on tab bar to emit tabMiddleClicked signal.
        
        Args:
            obj: The object being filtered.
            event: The event to filter.
            
        Returns:
            True if middle-click handled, False otherwise.
        """
        if obj == self.tabBar() and event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.MiddleButton:
                index = self.tabBar().tabAt(event.pos())
                if index != -1:
                    self.tabMiddleClicked.emit(index)
                    return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QEvent) -> None:
        """Accept drag enter events with URLs or text data.
        
        Args:
            event: The drag enter event.
        """
        if event.mimeData().hasUrls() or event.mimeData().hasText(): 
            event.acceptProposedAction()
        else: 
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QEvent) -> None:
        """Accept drag move events with URLs or text data.
        
        Args:
            event: The drag move event.
        """
        if event.mimeData().hasUrls() or event.mimeData().hasText(): 
            event.acceptProposedAction()
        else: 
            super().dragMoveEvent(event)

    def dropEvent(self, event: QEvent) -> None:
        """Handle file/URL drop events and emit fileDropped signal.
        
        Args:
            event: The drop event.
        """
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile(): 
                self.fileDropped.emit(url.toLocalFile())
            else:
                self.fileDropped.emit(url.toString())
            event.acceptProposedAction()
        
        elif event.mimeData().hasText():
            text = event.mimeData().text()
            if '\n' in text:
                text = text.split('\n')[0]
            self.fileDropped.emit(text)
            event.acceptProposedAction()
            
        else: 
            super().dropEvent(event)


class ExplorerTreeView(QTreeView):
    """A TreeView that displays loading state by modifying item labels."""

    def set_loading_state(self, index: QRect, is_loading: bool) -> None:
        """Set or clear the loading state for a tree item.
        
        Args:
            index: The model index of the item.
            is_loading: True to show loading state, False to restore.
        """
        model = self.model()
        if hasattr(model, 'itemFromIndex'):
            item = model.itemFromIndex(index)
        else:
            return

        if not item:
            return

        ORIGINAL_TEXT_ROLE = Qt.UserRole + 100

        if is_loading:
            original_text = item.text()
            item.setData(original_text, ORIGINAL_TEXT_ROLE)
            item.setText(f"{original_text} (expanding...)")
            item.setEnabled(False)
        else:
            original_text = item.data(ORIGINAL_TEXT_ROLE)
            if original_text:
                item.setText(original_text)
            item.setEnabled(True)


class BoxPlotWidget(QWidget):
    """A custom widget that renders a box plot visualization for numerical data."""

    def __init__(self, data_dict: dict[str, Any], theme_manager: Any, parent: QWidget | None = None) -> None:
        """Initialize the box plot widget with data and theme configuration.
        
        Args:
            data_dict: Dictionary with keys 'min', 'q25', 'q50', 'q75', 'max'.
            theme_manager: Theme manager for color extraction.
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.setFixedHeight(55) 
        self.theme_manager = theme_manager
        self.valid = False
        
        try:
            self.min_v = float(data_dict.get('min'))
            self.q25 = float(data_dict.get('q25'))
            self.q50 = float(data_dict.get('q50'))
            self.q75 = float(data_dict.get('q75'))
            self.max_v = float(data_dict.get('max'))
            self.valid = True
        except (ValueError, TypeError):
            self.valid = False

    def paintEvent(self, event: QEvent) -> None:
        """Draw the box plot visualization.
        
        Args:
            event: The paint event.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        text_color = self.palette().color(QPalette.WindowText)
        
        accent_hex = '#0078D7'
        if self.theme_manager and 'stylesheet' in self.theme_manager.theme_data:
            sb_style = self.theme_manager.theme_data['stylesheet'].get('#statusBar QLabel', {})
            accent_hex = sb_style.get('color', accent_hex)
            
        accent_color = QColor(accent_hex)

        if not self.valid:
            painter.setPen(text_color)
            painter.drawText(self.rect(), Qt.AlignCenter, "N/A for this data type")
            return

        w = self.width() - 30 
        h = self.height()
        y_center = h // 2
        
        span = self.max_v - self.min_v
        if span == 0:
            span = 1 

        def get_x(val: float) -> int:
            return 15 + int(((val - self.min_v) / span) * w)

        x_min = get_x(self.min_v)
        x_q25 = get_x(self.q25)
        x_q50 = get_x(self.q50)
        x_q75 = get_x(self.q75)
        x_max = get_x(self.max_v)

        pen = QPen(accent_color, 2)
        painter.setPen(pen)
        painter.drawLine(x_min, y_center, x_max, y_center)

        painter.drawLine(x_min, y_center - 5, x_min, y_center + 5)
        painter.drawLine(x_max, y_center - 5, x_max, y_center + 5)

        box_rect = QRect(x_q25, y_center - 8, max(1, x_q75 - x_q25), 16)
        brush_color = QColor(accent_color)
        brush_color.setAlpha(60) 
        painter.setBrush(brush_color)
        painter.drawRect(box_rect)

        median_pen = QPen(text_color, 2)
        painter.setPen(median_pen)
        painter.drawLine(x_q50, y_center - 8, x_q50, y_center + 8)

        small_font = self.font()
        small_font.setPointSize(max(7, small_font.pointSize() - 2))
        painter.setFont(small_font)
        fm = painter.fontMetrics()
        painter.setPen(text_color)

        def format_tiny(v: float) -> str:
            """Format numeric value compactly for label display."""
            if v == 0:
                return "0"
            if abs(v) >= 100000:
                return f"{v:.1e}"
            if v == int(v):
                return str(int(v))
            s = f"{v:.2f}"
            return s.rstrip('0').rstrip('.') if '.' in s else s

        def draw_label(val: float, x: int, y_baseline: int) -> None:
            """Draw a formatted label at the specified position."""
            txt = format_tiny(val)
            tw = fm.horizontalAdvance(txt)
            draw_x = x - tw // 2
            
            if draw_x < 0:
                draw_x = 0
            if draw_x + tw > self.width():
                draw_x = self.width() - tw
            painter.drawText(draw_x, y_baseline, txt)

        draw_label(self.min_v, x_min, y_center + 22)
        draw_label(self.max_v, x_max, y_center + 22)
        draw_label(self.q50, x_q50, y_center + 22)
        draw_label(self.q25, x_q25, y_center - 12)
        draw_label(self.q75, x_q75, y_center - 12)


class ColumnProfileCard(QFrame):
    """A card widget displaying profiling statistics for a single column."""

    def __init__(self, row_dict: dict[str, Any], theme_manager: Any, parent: QWidget | None = None) -> None:
        """Initialize the profile card with column statistics.
        
        Args:
            row_dict: Dictionary containing 'column_name', 'column_type', 'min', 'max', 'avg',
                     'null_percentage', 'count', and 'approx_unique' fields.
            theme_manager: Theme manager for color extraction.
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("profileCard")
        self.setFixedSize(400, 230) 

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        col_name = str(row_dict.get('column_name', 'Unknown'))
        col_type = str(row_dict.get('column_type', 'Unknown'))
        
        header_label = QLabel(f"<b>{col_name}</b> ({col_type})")
        font = header_label.font()
        font.setPointSize(11)
        header_label.setFont(font)
        
        layout.addWidget(header_label)
        layout.addSpacing(5)

        middle_layout = QHBoxLayout()
        
        stats_layout = QVBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(5)
        
        def format_stat(val: Any) -> str:
            """Format a statistic value for display."""
            if val is None:
                return "N/A"
            try:
                return f"{float(val):.2f}"
            except (ValueError, TypeError):
                return str(val)

        def add_stat(name: str, key: str) -> None:
            """Add a statistic label to the stats layout."""
            raw_val = format_stat(row_dict.get(key))
            display_val = raw_val
            if len(display_val) > 22:
                display_val = display_val[:19] + "..."
                
            lbl = QLabel(f"<b>{name}:</b> {display_val}")
            lbl.setToolTip(raw_val) 
            stats_layout.addWidget(lbl)

        add_stat("Min", "min")
        add_stat("Max", "max")
        add_stat("Avg", "avg")
        stats_layout.addStretch()
        
        middle_layout.addLayout(stats_layout, stretch=1)
        
        bars_layout = QVBoxLayout()
        bars_layout.setContentsMargins(0, 0, 0, 0)
        
        null_pct = row_dict.get('null_percentage', 0.0) or 0.0
        null_label = QLabel(f"Nulls: {null_pct:.1f}%")
        null_bar = QProgressBar()
        null_bar.setObjectName("profileNullBar")
        null_bar.setFixedHeight(6)
        null_bar.setTextVisible(False)
        null_bar.setRange(0, 100)
        null_bar.setValue(int(null_pct))
        
        if null_pct > 50:
            null_bar.setProperty("severity", "high")
        else:
            null_bar.setProperty("severity", "normal")
        
        bars_layout.addWidget(null_label)
        bars_layout.addWidget(null_bar)
        
        count = row_dict.get('count', 1)
        approx_unique = row_dict.get('approx_unique', 0)
        unique_pct = min((approx_unique / count) * 100, 100.0) if count and approx_unique is not None else 0.0
            
        unique_label = QLabel(f"Unique: ~{unique_pct:.1f}%")
        unique_bar = QProgressBar()
        unique_bar.setObjectName("profileUniqueBar")
        unique_bar.setFixedHeight(6)
        unique_bar.setTextVisible(False)
        unique_bar.setRange(0, 100)
        unique_bar.setValue(int(unique_pct))
        unique_bar.setProperty("severity", "normal")
        
        bars_layout.addWidget(unique_label)
        bars_layout.addWidget(unique_bar)
        bars_layout.addStretch()
        
        middle_layout.addLayout(bars_layout, stretch=1)
        layout.addLayout(middle_layout)

        layout.addWidget(QLabel("<b>Distribution:</b>"))
        box_plot = BoxPlotWidget(row_dict, theme_manager)
        layout.addWidget(box_plot)


class FlowLayout(QLayout):
    """A layout that arranges items left-to-right and wraps to the next line."""

    def __init__(self, parent: QWidget | None = None, margin: int = 15, spacing: int = 15) -> None:
        """Initialize the flow layout with optional margins and spacing.
        
        Args:
            parent: Parent widget (default: None).
            margin: Wrapper margin in pixels (default: 15).
            spacing: Item spacing in pixels (default: 15).
        """
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.itemList: list[QLayout] = []
        self.m_spacing = spacing

    def __del__(self) -> None:
        """Clean up layout items on deletion."""
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item: QLayout) -> None:
        """Add an item to the layout.
        
        Args:
            item: The layout item to add.
        """
        self.itemList.append(item)

    def count(self) -> int:
        """Return the number of items in the layout.
        
        Returns:
            Item count.
        """
        return len(self.itemList)

    def itemAt(self, index: int) -> QLayout | None:
        """Get the item at the specified index.
        
        Args:
            index: The item index.
            
        Returns:
            The layout item or None if index is out of range.
        """
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index: int) -> QLayout | None:
        """Remove and return the item at the specified index.
        
        Args:
            index: The item index.
            
        Returns:
            The removed layout item or None if index is out of range.
        """
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        """Return expanding directions (none for flow layout).
        
        Returns:
            Qt.Orientations(0).
        """
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        """Indicate that this layout has height for width.
        
        Returns:
            True.
        """
        return True

    def heightForWidth(self, width: int) -> int:
        """Calculate the height needed for the given width.
        
        Args:
            width: The available width.
            
        Returns:
            The required height.
        """
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        """Set the geometry and perform layout.
        
        Args:
            rect: The geometry rectangle.
        """
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self) -> QSize:
        """Return the size hint for the layout.
        
        Returns:
            The minimum size.
        """
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        """Calculate the minimum size needed for all items.
        
        Returns:
            The minimum size.
        """
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _doLayout(self, rect: QRect, testOnly: bool) -> int:
        """Perform the layout calculation and positioning.
        
        Args:
            rect: The layout rectangle.
            testOnly: If True, only calculate size without positioning.
            
        Returns:
            The total height used.
        """
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        spacing = self.m_spacing

        for item in self.itemList:
            wid = item.widget()
            spaceX = spacing
            spaceY = spacing
            nextX = x + item.sizeHint().width() + spaceX
            
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()


class ProfileDashboard(QScrollArea):
    """A scrollable dashboard displaying column profiling statistics as cards."""

    def __init__(self, theme_manager: Any | None = None, parent: QWidget | None = None) -> None:
        """Initialize the profile dashboard with optional theme manager.
        
        Args:
            theme_manager: Theme manager for styling (default: None).
            parent: Parent widget (default: None).
        """
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("profileDashboard")
        
        self.container = QWidget()
        self.container.setObjectName("profileContainer")
        
        self.layout = FlowLayout(self.container)
        self.setWidget(self.container)

    def load_data(self, df: pl.DataFrame) -> None:
        """Load column profiling data and render profile cards.
        
        Args:
            df: DataFrame with columns: column_name, column_type, min, max, avg, null_percentage, count, approx_unique.
        """
        for i in reversed(range(self.layout.count())): 
            item = self.layout.takeAt(i)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        for row in df.iter_rows(named=True):
            card = ColumnProfileCard(row, self.theme_manager)
            self.layout.addWidget(card)
