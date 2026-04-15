from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QRect, QSize, QStringListModel, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPaintEvent, QPainter, QResizeEvent, QTextCursor, QWheelEvent
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QWidget
from flatsql.core.highlighter import SqlHighlighter


class QueryTextEdit(QPlainTextEdit):
    """SQL editor with line numbers, auto-indent, and zoom support."""

    run_query = Signal()
    showFind = Signal()
    showFindReplace = Signal()
    zoomRequested = Signal(int)
    autocompleteRequested = Signal(object, str, int)

    def __init__(
        self,
        theme_colors: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the query editor.

        Args:
            theme_colors: Theme color mapping used for editor chrome and syntax.
            parent: Parent widget.
        """
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.highlighter: SqlHighlighter | None = None
        self.main_window_ref: object | None = None

        # Store theme colors for custom painting
        self.theme_colors = theme_colors.get("lineNumberArea", {}) if theme_colors else {}

        self._autocomplete_model = QStringListModel(self)
        self._autocomplete = QCompleter(self._autocomplete_model, self)
        self._autocomplete.setWidget(self)
        self._autocomplete.setCaseSensitivity(Qt.CaseInsensitive)
        self._autocomplete.setCompletionMode(QCompleter.PopupCompletion)
        self._autocomplete.activated[str].connect(self._insert_selected_completion)

        self._autocomplete_timer = QTimer(self)
        self._autocomplete_timer.setSingleShot(True)
        self._autocomplete_timer.setInterval(175)
        self._autocomplete_timer.timeout.connect(self._request_autocomplete)
        self._autocomplete_replace_start = 0
        self._highlight_restore_pending = False
        self._large_paste_threshold_chars = 20000

        # Connect signals for updating the line number area
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)

        self.results_df = None
        self.error_message = None
        self.info_message = None
        self.stats_text = ""
        self.status_message = "Ready"
        self.connection_key = None
        self.snippet_file_path: str | None = None
        self.column_widths = {}
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def set_main_window(self, main_window: object) -> None:
        """Store the main window reference and connect autocomplete signals."""
        self.main_window_ref = main_window

        if hasattr(main_window, "query_controller"):
            self.autocompleteRequested.connect(main_window.query_controller.request_autocomplete)
            main_window.query_controller.autocomplete_ready.connect(self.show_autocomplete)

    def update_theme_colors(
        self,
        theme_colors: dict[str, Any] | None,
        keywords: set[str],
        functions: set[str],
    ) -> None:
        """Update editor colors and rebuild the SQL highlighter."""
        self.theme_colors = theme_colors.get("lineNumberArea", {}) if theme_colors else {}
        self.line_number_area.update()

        syntax_colors = theme_colors.get("syntax") if theme_colors else None
        self.highlighter = SqlHighlighter(self.document(), keywords, functions, theme_colors=syntax_colors)
        self.highlighter.rehighlight()

    def line_number_area_width(self) -> int:
        """Calculate the width required to render line numbers."""
        digits = 1
        count = max(1, self.blockCount())
        while count >= 10:
            count //= 10
            digits += 1
        space = 10 + self.fontMetrics().horizontalAdvance("9") * digits
        return space

    def update_line_number_area_width(self, _: int) -> None:
        """Adjust the editor viewport margin to fit the line number area."""
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        """Scroll or repaint the line number area after editor updates."""
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Resize the line number area with the editor viewport."""
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event: QPaintEvent) -> None:
        """Paint line numbers for visible text blocks."""
        painter = QPainter(self.line_number_area)

        background_color = QColor(self.theme_colors.get("background", "#2B2B2B"))
        text_color = QColor(self.theme_colors.get("text", "#FFFFFF"))
        dim_text_alpha = self.theme_colors.get("dimTextAlpha", 150)

        painter.fillRect(event.rect(), background_color)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        current_block_number = self.textCursor().blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        
        dim_text_color = QColor(text_color)
        dim_text_color.setAlpha(dim_text_alpha)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                font = self.font()
                if block_number == current_block_number:
                    font.setBold(True)
                    painter.setFont(font)
                    painter.setPen(text_color)
                else:
                    font.setBold(False)
                    painter.setFont(font)
                    painter.setPen(dim_text_color)

                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 5,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        """Refresh the line number area when the cursor moves."""
        self.line_number_area.update()

    def _is_autocomplete_enabled(self) -> bool:
        """Return whether SQL autocomplete is enabled in the current settings."""
        if self.main_window_ref is None:
            return True

        settings_manager = getattr(self.main_window_ref, "settings_manager", None)
        if settings_manager is None:
            return True

        return bool(settings_manager.get("sql_autocomplete_enabled", True))

    def _should_schedule_autocomplete(self, event: QKeyEvent) -> bool:
        """Return whether the key press should trigger a fresh autocomplete lookup."""
        if not self._is_autocomplete_enabled():
            return False

        if event.modifiers() not in (Qt.NoModifier, Qt.ShiftModifier):
            return False

        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            return True

        typed_text = event.text()
        return bool(typed_text) and (typed_text.isalnum() or typed_text in {"_", "."})

    def _request_autocomplete(self) -> None:
        """Request autocomplete suggestions for the SQL text up to the cursor."""
        if not self._is_autocomplete_enabled():
            self._autocomplete.popup().hide()
            return

        if self.main_window_ref is None or not getattr(self, "connection_key", None):
            return

        cursor = self.textCursor()
        cursor_pos = cursor.position()
        query_prefix = self.toPlainText()[:cursor_pos]
        self.autocompleteRequested.emit(self, query_prefix, cursor_pos)

    def show_autocomplete(self, editor: object, suggestions: object, replace_start: int) -> None:
        """Display the suggestion popup for the matching editor instance."""
        if not self._is_autocomplete_enabled():
            self._autocomplete.popup().hide()
            return

        if editor is not self or not self.hasFocus():
            return

        items = [str(item) for item in (suggestions or []) if str(item).strip()]
        if not items:
            self._autocomplete.popup().hide()
            return

        self._autocomplete_replace_start = max(0, replace_start)
        self._autocomplete_model.setStringList(items)
        self._autocomplete.setCompletionPrefix("")

        popup = self._autocomplete.popup()
        popup.setCurrentIndex(self._autocomplete_model.index(0, 0))

        cursor_rect = self.cursorRect()
        cursor_rect.setWidth(max(240, popup.sizeHintForColumn(0) + 24))
        self._autocomplete.complete(cursor_rect)

    def apply_completion(self, completion: str, replace_start: int) -> None:
        """Replace the current token span with the selected completion text."""
        cursor = self.textCursor()
        end_pos = cursor.position()
        start_pos = max(0, min(replace_start, end_pos))

        cursor.setPosition(start_pos)
        cursor.setPosition(end_pos, QTextCursor.KeepAnchor)
        cursor.insertText(completion)
        self.setTextCursor(cursor)
        self._autocomplete.popup().hide()

    def _insert_selected_completion(self, completion: str) -> None:
        """Insert the chosen completion into the current cursor location."""
        self.apply_completion(completion, self._autocomplete_replace_start)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle auto-indentation and SQL autocomplete keystrokes."""
        if self._autocomplete.popup().isVisible() and event.key() in (
            Qt.Key_Enter,
            Qt.Key_Return,
            Qt.Key_Escape,
            Qt.Key_Tab,
            Qt.Key_Backtab,
        ):
            event.ignore()
            return

        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_Space:
            if self._is_autocomplete_enabled():
                self._autocomplete_timer.start(0)
            else:
                self._autocomplete.popup().hide()
            return

        # Auto Indentation on Enter ---
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            super().keyPressEvent(event)

            cursor = self.textCursor()
            previous_block = cursor.block().previous()

            if previous_block.isValid():
                previous_text = previous_block.text()
                indentation = previous_text[:len(previous_text) - len(previous_text.lstrip())]
                if indentation:
                    cursor.insertText(indentation)
            self._autocomplete.popup().hide()
            return

        super().keyPressEvent(event)

        if self._should_schedule_autocomplete(event):
            self._autocomplete_timer.start()
        else:
            self._autocomplete.popup().hide()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle zoom in and out with Ctrl + mouse wheel."""
        if event.modifiers() == Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoomRequested.emit(1)
            elif delta < 0:
                self.zoomRequested.emit(-1)

            event.accept()
        else:
            super().wheelEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        """React to font changes so the gutter stays aligned."""
        super().changeEvent(event)

        if event.type() == QEvent.FontChange:
            self.document().setDefaultFont(self.font())

            self.update_line_number_area_width(0)
            self.line_number_area.update()

            self.updateGeometry()
            self.viewport().update()

    def canInsertFromMimeData(self, source: object) -> bool:
        """Reject URL drops so file drag-and-drop is handled elsewhere."""
        return not source.hasUrls() and super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: object) -> None:
        """Insert clipboard text and defer highlight refresh for large pastes.

        For large payloads, SQL syntax highlighting can dominate paste latency.
        This fast path inserts plain text first, then restores highlighting on the
        next event-loop turn so pasted text appears immediately.
        """
        if source is None:
            return

        if source.hasUrls():
            return

        paste_text = source.text() if source.hasText() else ""
        should_defer_highlight = (
            self.highlighter is not None
            and len(paste_text) >= self._large_paste_threshold_chars
            and not self._highlight_restore_pending
        )

        if should_defer_highlight:
            self.highlighter.setDocument(None)

            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertText(paste_text)
            cursor.endEditBlock()
            self.setTextCursor(cursor)

            self._highlight_restore_pending = True
            QTimer.singleShot(0, self._restore_highlighter_after_large_paste)
            return

        super().insertFromMimeData(source)

    def _restore_highlighter_after_large_paste(self) -> None:
        """Reconnect and reapply syntax highlighting after a deferred paste."""
        self._highlight_restore_pending = False
        if self.highlighter is None:
            return

        self.highlighter.setDocument(self.document())
        self.highlighter.rehighlight()


class LineNumberArea(QWidget):
    """Margin widget that renders line numbers for a query editor."""

    def __init__(self, editor: QueryTextEdit) -> None:
        """Initialize the line number area.

        Args:
            editor: Owning query editor instance.
        """
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        """Return the preferred gutter size."""
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Delegate line number painting to the owning editor."""
        self.editor.line_number_area_paint_event(event)