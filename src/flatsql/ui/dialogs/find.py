"""Find, Find/Replace, and Go to Line dialogs for the query editor."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class FindReplaceDialog(QDialog):
    """Modeless dialog for Find and Find/Replace functionality in the editor.
    
    Supports case-sensitive and whole-word search options. Can toggle between
    simple Find mode and full Find/Replace mode via show_find() and show_find_replace().
    """

    # Signals to interact with the main editor
    findNext = Signal(str, QTextDocument.FindFlags)
    replace = Signal(str)
    replaceAll = Signal(str, str, QTextDocument.FindFlags)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the Find/Replace dialog.
        
        Args:
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("Find and Replace")
        self.setModal(False)
        self.create_ui()

    def create_ui(self) -> None:
        """Create and configure the dialog UI."""
        main_layout = QVBoxLayout(self)
        grid_layout = QGridLayout()

        # --- Widgets ---
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find")
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace with")

        self.replace_label = QLabel("Replace with:")

        self.case_sensitive_check = QCheckBox("Case Sensitive")
        self.whole_words_check = QCheckBox("Whole Words")

        self.find_button = QPushButton("Find Next")
        self.find_button.setAutoDefault(False)
        self.replace_button = QPushButton("Replace")
        self.replace_all_button = QPushButton("Replace All")

        # --- Layout ---
        # Row 0: Find Input
        grid_layout.addWidget(QLabel("Find:"), 0, 0)
        grid_layout.addWidget(self.find_input, 0, 1)
        grid_layout.addWidget(self.find_button, 0, 2)

        # Row 1: Replace Input
        grid_layout.addWidget(self.replace_label, 1, 0)
        grid_layout.addWidget(self.replace_input, 1, 1)
        grid_layout.addWidget(self.replace_button, 1, 2)

        # Row 2: Options (Checkboxes)
        options_layout = QHBoxLayout()
        options_layout.addWidget(self.case_sensitive_check)
        options_layout.addWidget(self.whole_words_check)
        options_layout.addStretch()
        grid_layout.addLayout(options_layout, 2, 1)
        grid_layout.addWidget(self.replace_all_button, 2, 2)

        # Make the input field column stretchable
        grid_layout.setColumnStretch(1, 1)

        main_layout.addLayout(grid_layout)

        # --- Connections ---
        self.find_button.clicked.connect(self.on_find_next)
        self.find_input.returnPressed.connect(self.find_button.animateClick)
        self.replace_button.clicked.connect(
            lambda: self.replace.emit(self.replace_input.text())
        )
        self.replace_all_button.clicked.connect(self.on_replace_all)

    def on_find_next(self) -> None:
        """Emit findNext signal with search text and flags."""
        flags = self.get_find_flags()
        self.findNext.emit(self.find_input.text(), flags)

    def on_replace_all(self) -> None:
        """Emit replaceAll signal with find text, replace text, and flags."""
        flags = self.get_find_flags()
        self.replaceAll.emit(
            self.find_input.text(), self.replace_input.text(), flags
        )

    def get_find_flags(self) -> QTextDocument.FindFlags:
        """Build find flags based on checked options.
        
        Returns:
            QTextDocument.FindFlags with currently enabled search options.
        """
        flags = QTextDocument.FindFlags()
        if self.case_sensitive_check.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self.whole_words_check.isChecked():
            flags |= QTextDocument.FindWholeWords
        return flags

    def show_find(self) -> None:
        """Configure and display dialog in Find-only mode."""
        self.replace_label.hide()
        self.replace_input.hide()
        self.replace_button.hide()
        self.replace_all_button.hide()
        self.find_button.setText("Find")
        self.setWindowTitle("Find")
        self.show()
        self.activateWindow()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def show_find_replace(self) -> None:
        """Configure and display dialog in Find/Replace mode."""
        self.replace_label.show()
        self.replace_input.show()
        self.replace_button.show()
        self.replace_all_button.show()
        self.find_button.setText("Find Next")
        self.setWindowTitle("Find and Replace")
        self.show()
        self.activateWindow()
        self.find_input.setFocus()
        self.find_input.selectAll()


class GoToLineDialog(QDialog):
    """Modal dialog to jump to a specific line number in the editor."""

    def __init__(
        self, current_line: int, max_lines: int, parent: QWidget | None = None
    ) -> None:
        """Initialize the Go to Line dialog.
        
        Args:
            current_line: The currently active line number.
            max_lines: The maximum line number in the document.
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("Go to Line")
        self.setFixedSize(300, 120)

        layout = QVBoxLayout(self)

        # Label with range info
        layout.addWidget(QLabel(f"Line number (1 - {max_lines}):"))

        # Input field
        self.line_input = QSpinBox()
        self.line_input.setRange(1, max_lines)
        self.line_input.setValue(current_line)
        self.line_input.selectAll()
        layout.addWidget(self.line_input)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_line_number(self) -> int:
        """Retrieve the selected line number.
        
        Returns:
            The line number selected in the spin box.
        """
        return self.line_input.value()
