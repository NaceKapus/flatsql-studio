"""Application settings dialog with multiple configuration pages."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flatsql.ui.widgets import DownwardComboBox


class SettingsDialog(QDialog):
    """Settings dialog with sidebar navigation and tabbed configuration pages.
    
    Provides grouped settings for appearance, query editor, export, DuckDB engine,
    and general preferences. Uses a left sidebar for navigation and a stacked widget
    to switch between pages.
    """

    theme_preview_requested = Signal(str)

    def __init__(
        self,
        settings_data: dict,
        available_themes: dict[str, str],
        conversion_formats: dict,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the settings dialog.
        
        Args:
            settings_data: Dictionary of current setting values.
            available_themes: Dictionary mapping theme file names to display names.
            conversion_formats: Dictionary of available export format configurations.
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setSizeGripEnabled(True)

        self.settings_data = settings_data
        self.conversion_formats = conversion_formats
        self.available_themes = available_themes

        # Main layout (Vertical) to hold the content area and the bottom buttons
        main_layout = QVBoxLayout(self)

        # Content Layout (Horizontal) for Sidebar + Pages
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)
        main_layout.addLayout(content_layout)

        # --- Sidebar (Left) ---
        self.pages_list = QListWidget()
        self.pages_list.setObjectName("settingsNav")
        sidebar_width = max(170, self.fontMetrics().horizontalAdvance("SQL Formatting") + 64)
        self.pages_list.setMinimumWidth(sidebar_width)
        self.pages_list.setMaximumWidth(sidebar_width + 40)
        self.pages_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.pages_list.currentRowChanged.connect(self.change_page)
        content_layout.addWidget(self.pages_list)

        # --- Pages Area (Right) ---
        self.pages_stack = QStackedWidget()
        self.pages_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self.pages_stack, 1)

        # --- Initialize Pages ---
        self._init_pages()

        # --- Bottom Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        # Select first item
        self.pages_list.setCurrentRow(0)
        self._apply_responsive_size()

    def _init_pages(self) -> None:
        """Create and add all settings pages to the stacked widget."""
        self.add_page("Appearance", self._create_appearance_tab())
        self.add_page("Query Editor", self._create_editor_tab())
        self.add_page("SQL Formatting", self._create_formatting_tab())
        self.add_page("Export", self._create_export_tab())
        self.add_page("DuckDB", self._create_engine_tab())
        self.add_page("General", self._create_general_tab())

    def add_page(self, name: str, widget: QWidget) -> None:
        """Add a settings page to the stacked widget and sidebar list.
        
        Args:
            name: Display name for the page in the sidebar.
            widget: The widget containing the page content.
        """
        item = QListWidgetItem(name)
        self.pages_list.addItem(item)
        self.pages_stack.addWidget(widget)

    @staticmethod
    def _configure_form_layout(layout: QFormLayout) -> None:
        """Apply responsive defaults so forms remain readable on scaled displays."""
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.setFormAlignment(Qt.AlignTop)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(10)

    def _apply_responsive_size(self) -> None:
        """Choose a practical initial size based on the active screen geometry."""
        size_hint = self.sizeHint().expandedTo(QSize(780, 500))
        screen = self.parentWidget().screen() if self.parentWidget() is not None else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()

        if screen is None:
            self.resize(size_hint)
            self.setMinimumSize(size_hint)
            return

        available = screen.availableGeometry().size()
        max_width = max(560, int(available.width() * 0.9))
        max_height = max(420, int(available.height() * 0.85))

        target_width = min(size_hint.width(), max_width)
        target_height = min(max(size_hint.height(), 420), max_height)

        self.resize(target_width, target_height)
        self.setMinimumSize(target_width, min(target_height, max_height))

    def change_page(self, index: int) -> None:
        """Switch to a different settings page.
        
        Args:
            index: Index of the page to display.
        """
        self.pages_stack.setCurrentIndex(index)

    def _create_appearance_tab(self) -> QWidget:
        """Create the Appearance settings page.
        
        Returns:
            Widget containing appearance settings controls.
        """
        widget = QWidget()
        layout = QFormLayout(widget)
        self._configure_form_layout(layout)

        self.theme_combo = DownwardComboBox()
        for theme_file, theme_name in self.available_themes.items():
            self.theme_combo.addItem(theme_name, theme_file)

        current_theme = self.settings_data.get("theme", "dark.json")
        current_index = self.theme_combo.findData(current_theme)
        if current_index != -1:
            self.theme_combo.setCurrentIndex(current_index)

        self.theme_combo.currentIndexChanged.connect(
            lambda: self.theme_preview_requested.emit(self.theme_combo.currentData())
        )

        layout.addRow("Application Theme:", self.theme_combo)
        return widget

    def _create_editor_tab(self) -> QWidget:
        """Create the Query Editor settings page.
        
        Returns:
            Widget containing editor settings controls.
        """
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)

        layout = QFormLayout()
        self._configure_form_layout(layout)
        layout.setContentsMargins(15, 0, 0, 0)

        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(6, 30)
        self.font_size_spinbox.setValue(
            self.settings_data.get("font_size", 11)
        )
        layout.addRow("Font Size:", self.font_size_spinbox)

        self.shortcut_edit = QKeySequenceEdit()
        self.shortcut_edit.setKeySequence(
            QKeySequence(
                self.settings_data.get("run_query_shortcut", "Ctrl+Return")
            )
        )
        layout.addRow("Run Query Shortcut:", self.shortcut_edit)

        self.sql_autocomplete_check = QCheckBox()
        self.sql_autocomplete_check.setChecked(
            self.settings_data.get("sql_autocomplete_enabled", True)
        )
        self.sql_autocomplete_check.setToolTip(
            "Shows DuckDB-powered SQL suggestions while typing and when pressing Ctrl+Space."
        )
        layout.addRow("Enable SQL Autocomplete:", self.sql_autocomplete_check)

        self.history_limit_input = QLineEdit()
        self.history_limit_input.setValidator(QIntValidator(1, 99999, self))
        current_limit = self.settings_data.get("history_retention_limit", 100)
        self.history_limit_input.setText(str(current_limit))

        layout.addRow("History Retention Limit:", self.history_limit_input)

        self.preview_row_limit_spin = QSpinBox()
        self.preview_row_limit_spin.setRange(0, 10_000_000)
        self.preview_row_limit_spin.setSingleStep(1000)
        self.preview_row_limit_spin.setSuffix(" rows")
        self.preview_row_limit_spin.setSpecialValueText("Unlimited")
        self.preview_row_limit_spin.setValue(
            int(self.settings_data.get("preview_row_limit", 1000) or 0)
        )
        self.preview_row_limit_spin.setToolTip(
            "Maximum rows shown by Select Top, file previews, and history "
            "previews. Set to 0 for no cap."
        )
        layout.addRow("Preview Row Limit:", self.preview_row_limit_spin)

        main_layout.addLayout(layout)
        main_layout.addStretch()

        return widget

    # Defaults for the SQL Formatting page. Kept in sync with DEFAULT_SETTINGS
    # in core/settings.py. The "Reset to defaults" button reads from this map.
    _SQLFLUFF_DEFAULTS: dict = {
        "sqlfluff_keywords_case": "upper",
        "sqlfluff_functions_case": "upper",
        "sqlfluff_identifiers_case": "lower",
        "sqlfluff_literals_case": "upper",
        "sqlfluff_types_case": "upper",
        "sqlfluff_indent_unit": "space",
        "sqlfluff_tab_space_size": 4,
        "sqlfluff_max_line_length": 80,
        "sqlfluff_comma_position": "trailing",
        "sqlfluff_require_semicolon": False,
        "sqlfluff_quote_identifiers": True,
    }

    # SQLFluff uses British spelling for these policy values.
    _BASIC_CASE_CHOICES = [
        ("UPPER", "upper"),
        ("lower", "lower"),
        ("Capitalise", "capitalise"),
        ("Consistent", "consistent"),
    ]
    _EXTENDED_CASE_CHOICES = _BASIC_CASE_CHOICES + [("PascalCase", "pascal")]

    def _create_formatting_tab(self) -> QWidget:
        """Create the SQL Formatting page exposing user-friendly SQLFluff options."""
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setSpacing(12)

        # --- Capitalization section ---
        cap_label = QLabel("Capitalization")
        cap_label.setObjectName("settingsSectionLabel")
        outer.addWidget(cap_label)

        cap_form = QFormLayout()
        self._configure_form_layout(cap_form)
        cap_form.setContentsMargins(15, 0, 0, 0)

        self.sqlfluff_keywords_combo = self._build_case_combo(
            self._BASIC_CASE_CHOICES,
            self.settings_data.get("sqlfluff_keywords_case", "upper"),
        )
        cap_form.addRow("Keywords (SELECT, FROM):", self.sqlfluff_keywords_combo)

        self.sqlfluff_functions_combo = self._build_case_combo(
            self._EXTENDED_CASE_CHOICES,
            self.settings_data.get("sqlfluff_functions_case", "upper"),
        )
        cap_form.addRow("Functions (COUNT, SUM):", self.sqlfluff_functions_combo)

        self.sqlfluff_identifiers_combo = self._build_case_combo(
            self._EXTENDED_CASE_CHOICES,
            self.settings_data.get("sqlfluff_identifiers_case", "lower"),
        )
        cap_form.addRow("Identifiers (table/column):", self.sqlfluff_identifiers_combo)

        self.sqlfluff_quote_identifiers_check = QCheckBox()
        self.sqlfluff_quote_identifiers_check.setChecked(
            bool(self.settings_data.get("sqlfluff_quote_identifiers", True))
        )
        self.sqlfluff_quote_identifiers_check.setToolTip(
            "Always wrap table and column identifiers in double quotes, "
            "even when not strictly required. Helps avoid collisions with "
            "reserved keywords like 'name' or 'index'."
        )
        cap_form.addRow(
            "Always quote identifiers:",
            self.sqlfluff_quote_identifiers_check,
        )

        self.sqlfluff_literals_combo = self._build_case_combo(
            self._BASIC_CASE_CHOICES,
            self.settings_data.get("sqlfluff_literals_case", "upper"),
        )
        cap_form.addRow("Literals (TRUE, NULL):", self.sqlfluff_literals_combo)

        self.sqlfluff_types_combo = self._build_case_combo(
            self._EXTENDED_CASE_CHOICES,
            self.settings_data.get("sqlfluff_types_case", "upper"),
        )
        cap_form.addRow("Data types (INT, VARCHAR):", self.sqlfluff_types_combo)

        outer.addLayout(cap_form)

        outer.addWidget(self._make_section_separator())

        # --- Indentation section ---
        indent_label = QLabel("Indentation")
        indent_label.setObjectName("settingsSectionLabel")
        outer.addWidget(indent_label)

        indent_form = QFormLayout()
        self._configure_form_layout(indent_form)
        indent_form.setContentsMargins(15, 0, 0, 0)

        self.sqlfluff_indent_unit_combo = DownwardComboBox()
        self.sqlfluff_indent_unit_combo.addItem("Spaces", "space")
        self.sqlfluff_indent_unit_combo.addItem("Tabs", "tab")
        idx = self.sqlfluff_indent_unit_combo.findData(
            self.settings_data.get("sqlfluff_indent_unit", "space")
        )
        if idx != -1:
            self.sqlfluff_indent_unit_combo.setCurrentIndex(idx)
        indent_form.addRow("Indent character:", self.sqlfluff_indent_unit_combo)

        self.sqlfluff_tab_size_spin = QSpinBox()
        self.sqlfluff_tab_size_spin.setRange(2, 8)
        self.sqlfluff_tab_size_spin.setValue(
            int(self.settings_data.get("sqlfluff_tab_space_size", 4))
        )
        indent_form.addRow("Spaces per indent:", self.sqlfluff_tab_size_spin)

        outer.addLayout(indent_form)

        outer.addWidget(self._make_section_separator())

        # --- Layout & conventions section ---
        layout_label = QLabel("Layout && conventions")
        layout_label.setObjectName("settingsSectionLabel")
        outer.addWidget(layout_label)

        layout_form = QFormLayout()
        self._configure_form_layout(layout_form)
        layout_form.setContentsMargins(15, 0, 0, 0)

        self.sqlfluff_max_line_spin = QSpinBox()
        self.sqlfluff_max_line_spin.setRange(0, 200)
        self.sqlfluff_max_line_spin.setSpecialValueText("No limit")
        self.sqlfluff_max_line_spin.setValue(
            int(self.settings_data.get("sqlfluff_max_line_length", 80))
        )
        self.sqlfluff_max_line_spin.setToolTip(
            "Maximum line length in characters. Set to 0 to disable line-length checks."
        )
        layout_form.addRow("Max line length:", self.sqlfluff_max_line_spin)

        self.sqlfluff_comma_combo = DownwardComboBox()
        self.sqlfluff_comma_combo.addItem("Trailing (a, b,)", "trailing")
        self.sqlfluff_comma_combo.addItem("Leading (a , b)", "leading")
        idx = self.sqlfluff_comma_combo.findData(
            self.settings_data.get("sqlfluff_comma_position", "trailing")
        )
        if idx != -1:
            self.sqlfluff_comma_combo.setCurrentIndex(idx)
        layout_form.addRow("Comma position:", self.sqlfluff_comma_combo)

        self.sqlfluff_semicolon_check = QCheckBox()
        self.sqlfluff_semicolon_check.setChecked(
            bool(self.settings_data.get("sqlfluff_require_semicolon", False))
        )
        layout_form.addRow(
            "Require trailing semicolon:", self.sqlfluff_semicolon_check
        )

        outer.addLayout(layout_form)

        outer.addStretch()

        # --- Reset to defaults ---
        button_row = QHBoxLayout()
        button_row.addStretch()
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._reset_formatting_defaults)
        button_row.addWidget(reset_btn)
        outer.addLayout(button_row)

        return widget

    @staticmethod
    def _build_case_combo(choices: list[tuple[str, str]], current: str) -> "DownwardComboBox":
        """Build a capitalization-policy combo box pre-selected to ``current``."""
        combo = DownwardComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        idx = combo.findData(current)
        if idx != -1:
            combo.setCurrentIndex(idx)
        return combo

    @staticmethod
    def _make_section_separator() -> QFrame:
        """Return a thin horizontal divider used between formatting sections."""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _reset_formatting_defaults(self) -> None:
        """Reset all SQL formatting controls to their built-in defaults."""
        d = self._SQLFLUFF_DEFAULTS
        for combo, key in (
            (self.sqlfluff_keywords_combo, "sqlfluff_keywords_case"),
            (self.sqlfluff_functions_combo, "sqlfluff_functions_case"),
            (self.sqlfluff_identifiers_combo, "sqlfluff_identifiers_case"),
            (self.sqlfluff_literals_combo, "sqlfluff_literals_case"),
            (self.sqlfluff_types_combo, "sqlfluff_types_case"),
            (self.sqlfluff_indent_unit_combo, "sqlfluff_indent_unit"),
            (self.sqlfluff_comma_combo, "sqlfluff_comma_position"),
        ):
            idx = combo.findData(d[key])
            if idx != -1:
                combo.setCurrentIndex(idx)
        self.sqlfluff_tab_size_spin.setValue(int(d["sqlfluff_tab_space_size"]))
        self.sqlfluff_max_line_spin.setValue(int(d["sqlfluff_max_line_length"]))
        self.sqlfluff_semicolon_check.setChecked(bool(d["sqlfluff_require_semicolon"]))
        self.sqlfluff_quote_identifiers_check.setChecked(bool(d["sqlfluff_quote_identifiers"]))

    def _create_export_tab(self) -> QWidget:
        """Create the Export settings page.

        Returns:
            Widget containing export format settings controls.
        """
        widget = QWidget()
        layout = QFormLayout(widget)
        self._configure_form_layout(layout)

        # --- Default Export Format ---
        self.default_export_combo = DownwardComboBox()
        for key, details in self.conversion_formats.items():
            self.default_export_combo.addItem(details["label"], key)

        current_format = self.settings_data.get("default_export_format", "csv")
        current_index = self.default_export_combo.findData(current_format)
        if current_index != -1:
            self.default_export_combo.setCurrentIndex(current_index)

        layout.addRow("Default Export Format:", self.default_export_combo)

        # --- Default CSV Delimiter ---
        self.default_delimiter_combo = DownwardComboBox()
        self.default_delimiter_combo.addItem("Comma (,)", ",")
        self.default_delimiter_combo.addItem("Tab (\\t)", "\t")
        self.default_delimiter_combo.addItem("Pipe (|)", "|")
        self.default_delimiter_combo.addItem("Semicolon (;)", ";")

        current_delim = self.settings_data.get("csv_delimiter", ",")
        delim_idx = self.default_delimiter_combo.findData(current_delim)
        if delim_idx != -1:
            self.default_delimiter_combo.setCurrentIndex(delim_idx)
        else:
            self.default_delimiter_combo.setCurrentIndex(0)

        layout.addRow("Default CSV Delimiter:", self.default_delimiter_combo)

        # --- Default Include Headers ---
        self.default_header_check = QCheckBox()
        self.default_header_check.setChecked(
            self.settings_data.get("csv_include_header", True)
        )

        layout.addRow("Include Headers (CSV/Excel):", self.default_header_check)

        return widget

    def _create_general_tab(self) -> QWidget:
        """Create the General settings page.
        
        Returns:
            Widget containing general settings controls.
        """
        widget = QWidget()
        layout = QFormLayout(widget)
        self._configure_form_layout(layout)

        self.restore_session_check = QCheckBox()
        self.restore_session_check.setChecked(
            self.settings_data.get("restore_previous_session", True)
        )
        layout.addRow(
            "Restore previous session on startup:", self.restore_session_check
        )

        return widget

    def _create_engine_tab(self) -> QWidget:
        """Create the DuckDB Engine settings page.
        
        Returns:
            Widget containing DuckDB configuration controls.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form_layout = QFormLayout()
        self._configure_form_layout(form_layout)

        # Max Memory
        self.max_memory_input = QLineEdit()
        self.max_memory_input.setPlaceholderText("e.g., 8GB")
        self.max_memory_input.setText(
            self.settings_data.get("engine_max_memory", "")
        )
        form_layout.addRow("Max Memory:", self.max_memory_input)

        # Spill Directory
        dir_layout = QHBoxLayout()
        self.temp_dir_input = QLineEdit()
        self.temp_dir_input.setText(self.settings_data.get("engine_temp_dir", ""))
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_temp_dir)
        dir_layout.addWidget(self.temp_dir_input)
        dir_layout.addWidget(browse_btn)
        form_layout.addRow("Spill Directory:", dir_layout)

        # Max Spill Size
        self.max_spill_input = QLineEdit()
        self.max_spill_input.setPlaceholderText("e.g., 100GB")
        self.max_spill_input.setText(
            self.settings_data.get("engine_max_spill_size", "")
        )
        form_layout.addRow("Max Spill Size:", self.max_spill_input)

        # Threads
        self.threads_input = QLineEdit()
        self.threads_input.setPlaceholderText(
            "e.g., 4 (Leave blank for auto)"
        )
        self.threads_input.setText(str(self.settings_data.get("engine_threads", "")))
        form_layout.addRow("Max CPU Threads:", self.threads_input)

        # Timezone
        self.timezone_input = QLineEdit()
        self.timezone_input.setPlaceholderText("e.g., UTC or America/New_York")
        self.timezone_input.setText(
            self.settings_data.get("engine_timezone", "UTC")
        )
        form_layout.addRow("Timezone:", self.timezone_input)

        # Preserve Insertion Order
        self.preserve_order_check = QCheckBox()
        self.preserve_order_check.setChecked(
            self.settings_data.get("engine_preserve_insertion_order", True)
        )
        self.preserve_order_check.setToolTip(
            "Maintains insertion order when querying without an ORDER BY clause. "
            "May impact performance."
        )
        form_layout.addRow("Preserve Insertion Order:", self.preserve_order_check)

        layout.addLayout(form_layout)
        layout.addStretch()
        return widget

    def _browse_temp_dir(self) -> None:
        """Open a directory browser for selecting the spill directory."""
        directory = QFileDialog.getExistingDirectory(self, "Select Spill Directory")
        if directory:
            self.temp_dir_input.setText(directory)

    def get_settings(self) -> dict:
        """Retrieve all current settings from the dialog controls.
        
        Returns:
            Dictionary of setting names to values.
        """
        limit_text = self.history_limit_input.text()
        retention_limit = int(limit_text) if limit_text.isdigit() else 100

        return {
            "font_size": self.font_size_spinbox.value(),
            "theme": self.theme_combo.currentData(),
            "run_query_shortcut": self.shortcut_edit.keySequence().toString(),
            "sql_autocomplete_enabled": self.sql_autocomplete_check.isChecked(),
            "restore_previous_session": self.restore_session_check.isChecked(),
            "default_export_format": self.default_export_combo.currentData(),
            "csv_delimiter": self.default_delimiter_combo.currentData(),
            "csv_include_header": self.default_header_check.isChecked(),
            "history_retention_limit": retention_limit,
            "preview_row_limit": self.preview_row_limit_spin.value(),
            "engine_max_memory": self.max_memory_input.text().strip(),
            "engine_temp_dir": self.temp_dir_input.text().strip(),
            "engine_max_spill_size": self.max_spill_input.text().strip(),
            "engine_threads": self.threads_input.text().strip(),
            "engine_timezone": self.timezone_input.text().strip(),
            "engine_preserve_insertion_order": self.preserve_order_check.isChecked(),
            "sqlfluff_keywords_case": self.sqlfluff_keywords_combo.currentData(),
            "sqlfluff_functions_case": self.sqlfluff_functions_combo.currentData(),
            "sqlfluff_identifiers_case": self.sqlfluff_identifiers_combo.currentData(),
            "sqlfluff_literals_case": self.sqlfluff_literals_combo.currentData(),
            "sqlfluff_types_case": self.sqlfluff_types_combo.currentData(),
            "sqlfluff_indent_unit": self.sqlfluff_indent_unit_combo.currentData(),
            "sqlfluff_tab_space_size": self.sqlfluff_tab_size_spin.value(),
            "sqlfluff_max_line_length": self.sqlfluff_max_line_spin.value(),
            "sqlfluff_comma_position": self.sqlfluff_comma_combo.currentData(),
            "sqlfluff_require_semicolon": self.sqlfluff_semicolon_check.isChecked(),
            "sqlfluff_quote_identifiers": self.sqlfluff_quote_identifiers_check.isChecked(),
        }
