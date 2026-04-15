import os
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel, QFrame, QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QRadioButton, QButtonGroup, QSpinBox, QFileDialog

from flatsql.core.logger import get_logger
from flatsql.ui.widgets import DownwardComboBox

logger = get_logger(__name__)


class SplitFileDialog(QDialog):
    """
    Dialog to configure file splitting or partitioning options.
    """
    def __init__(self, file_path: str, engine: Any, parent: Any = None) -> None:
        """Initialize the split/partition dialog for a source file."""
        super().__init__(parent)
        self.setWindowTitle("Split or Partition File")
        self.setMinimumWidth(450)
        self.file_path = file_path
        self.engine = engine
        
        layout = QVBoxLayout(self)
        
        # --- File Info ---
        layout.addWidget(QLabel(f"<b>Source:</b> {os.path.basename(file_path)}"))
        
        # --- Output Directory ---
        dir_layout = QHBoxLayout()
        self.out_dir_input = QLineEdit()
        self.out_dir_input.setPlaceholderText("Select output folder...")
        # Default to a subfolder named after the file
        default_out = os.path.join(os.path.dirname(file_path), os.path.splitext(os.path.basename(file_path))[0] + "_split")
        self.out_dir_input.setText(default_out)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.out_dir_input)
        dir_layout.addWidget(browse_btn)
        layout.addWidget(QLabel("Output Directory:"))
        layout.addLayout(dir_layout)
        
        # --- Mode Selection ---
        group_box = QFrame()
        group_box.setFrameShape(QFrame.StyledPanel)
        group_layout = QVBoxLayout(group_box)
        
        self.mode_group = QButtonGroup(self)
        
        # Option 1: Split by Row Count (Chunking)
        self.radio_chunk = QRadioButton("Split by Row Count (Chunking)")
        self.radio_chunk.setChecked(True)
        self.mode_group.addButton(self.radio_chunk)
        group_layout.addWidget(self.radio_chunk)
        
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(1, 999999999)
        self.chunk_size_spin.setValue(100000) # Default 100k rows
        self.chunk_size_spin.setSuffix(" rows per file")
        self.chunk_size_spin.setSingleStep(50000)
        group_layout.addWidget(self.chunk_size_spin)
        
        # Option 2: Partition by Column
        self.radio_col = QRadioButton("Partition by Column Value")
        self.mode_group.addButton(self.radio_col)
        group_layout.addWidget(self.radio_col)
        
        self.col_combo = DownwardComboBox()
        self.col_combo.setEnabled(False)
        self._populate_columns()
        group_layout.addWidget(self.col_combo)
        
        layout.addWidget(group_box)
        
        # --- Format Selection ---
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Output Format:"))
        self.format_combo = DownwardComboBox()
        self.format_combo.addItems(["Parquet", "CSV", "JSON"])
        format_layout.addWidget(self.format_combo)
        layout.addLayout(format_layout)

        # --- Connect Signals ---
        self.radio_chunk.toggled.connect(lambda: self.chunk_size_spin.setEnabled(self.radio_chunk.isChecked()))
        self.radio_col.toggled.connect(lambda: self.col_combo.setEnabled(self.radio_col.isChecked()))

        # --- Buttons ---
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _browse_dir(self) -> None:
        """Prompt for an output directory."""
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.out_dir_input.setText(d)

    def _populate_columns(self) -> None:
        """Populate the partition-column dropdown from the file schema."""
        try:
            cols = self.engine.get_columns_for_file(self.file_path)
            for c in cols:
                self.col_combo.addItem(c)
        except Exception:
            self.col_combo.addItem("Error fetching columns")
            logger.exception("Failed to populate split columns for %s.", self.file_path)

    def get_details(self) -> dict[str, Any]:
        """Return the selected split configuration."""
        return {
            "out_dir": self.out_dir_input.text(),
            "mode": "chunk" if self.radio_chunk.isChecked() else "partition",
            "chunk_size": self.chunk_size_spin.value(),
            "partition_col": self.col_combo.currentText(),
            "format": self.format_combo.currentText()
        }
    
class MergeFilesDialog(QDialog):
    """
    Dialog to configure merging multiple files from a folder into one.
    """
    def __init__(self, folder_path: str, parent: Any = None) -> None:
        """Initialize the merge dialog for a source folder."""
        super().__init__(parent)
        self.setWindowTitle("Merge Files in Folder")
        self.setMinimumWidth(450)
        self.folder_path = folder_path
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel(f"<b>Source Folder:</b> {os.path.basename(folder_path)}"))
        
        # --- Input Criteria ---
        input_group = QFrame()
        input_group.setFrameShape(QFrame.StyledPanel)
        input_layout = QFormLayout(input_group)
        
        self.ext_combo = DownwardComboBox()
        self.ext_combo.addItems([
            "CSV (*.csv)",
            "TSV (*.tsv)",
            "TAB (*.tab)",
            "PSV (*.psv)",
            "Parquet (*.parquet)",
            "JSON (*.json)",
            "JSON Lines (*.jsonl)",
            "NDJSON (*.ndjson)",
            "Text (*.txt)",
        ])
        input_layout.addRow("Merge files of type:", self.ext_combo)
        
        # 1. Recursive Checkbox
        self.recursive_check = QCheckBox("Include subfolders (Recursive)")
        self.recursive_check.setChecked(False)
        self.recursive_check.setToolTip("If checked, looks for files in all sub-directories using '**'")
        input_layout.addRow("", self.recursive_check)

        # 2. Union By Name Checkbox
        self.union_check = QCheckBox("Union by Name")
        self.union_check.setChecked(True)
        self.union_check.setToolTip("Match columns by name instead of position. Vital if column order varies.")
        input_layout.addRow("", self.union_check)
        
        layout.addWidget(QLabel("Input Settings:"))
        layout.addWidget(input_group)
        
        # --- Output Settings ---
        layout.addWidget(QLabel("Output Settings:"))
        
        out_layout = QHBoxLayout()
        self.out_name_input = QLineEdit()
        self.out_name_input.setPlaceholderText("merged_output")
        self.out_name_input.setText("merged_output")
        out_layout.addWidget(self.out_name_input)
        
        self.out_format_combo = DownwardComboBox()
        self.out_format_combo.addItems([".parquet", ".csv", ".json"])
        out_layout.addWidget(self.out_format_combo)
        
        layout.addLayout(out_layout)

        # --- Buttons ---
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_details(self) -> dict[str, Any]:
        """Return the selected merge configuration."""
        ext_map = {
            0: "csv",
            1: "tsv",
            2: "tab",
            3: "psv",
            4: "parquet",
            5: "json",
            6: "jsonl",
            7: "ndjson",
            8: "txt",
        }
        return {
            "source_ext": ext_map[self.ext_combo.currentIndex()],
            "union_by_name": self.union_check.isChecked(),
            "recursive": self.recursive_check.isChecked(),
            "out_name": self.out_name_input.text(),
            "out_ext": self.out_format_combo.currentText()
        }

class ExportDialog(QDialog):
    """A dialog to select format and options for exporting results."""

    def __init__(
        self,
        formats: dict[str, dict[str, str]],
        default_format: str,
        settings: Any,
        parent: Any = None,
    ) -> None:
        """Initialize the export dialog with available output formats."""
        super().__init__(parent)
        self.setWindowTitle("Export Results")
        self.setMinimumWidth(350)
        self.settings = settings

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.format_combo = DownwardComboBox()
        for key, details in formats.items():
            self.format_combo.addItem(details["label"], key)

        current_index = self.format_combo.findData(default_format)
        if current_index != -1:
            self.format_combo.setCurrentIndex(current_index)
        
        self.format_combo.currentIndexChanged.connect(self._update_options_visibility)

        form_layout.addRow("Export Format:", self.format_combo)
        
        self.compression_combo = DownwardComboBox()
        self.compression_label = QLabel("Compression:")
        form_layout.addRow(self.compression_label, self.compression_combo)

        self.delimiter_combo = DownwardComboBox()
        self.delimiter_combo.addItem("Comma (,)", ",")
        self.delimiter_combo.addItem("Tab (\\t)", "\t")
        self.delimiter_combo.addItem("Pipe (|)", "|")
        self.delimiter_combo.addItem("Semicolon (;)", ";")
        
        default_delim = self.settings.get("csv_delimiter", ",")
        idx = self.delimiter_combo.findData(default_delim)
        if idx != -1:
            self.delimiter_combo.setCurrentIndex(idx)
        
        self.delimiter_label = QLabel("Delimiter:")
        form_layout.addRow(self.delimiter_label, self.delimiter_combo)

        self.header_check = QCheckBox("Include Headers")
        self.header_check.setChecked(self.settings.get("csv_include_header", True))
        form_layout.addRow("", self.header_check)

        layout.addLayout(form_layout)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._update_options_visibility()

    def _update_options_visibility(self) -> None:
        """Shows/Hides options based on the selected format."""
        fmt = self.format_combo.currentData()
        is_csv = fmt == "csv"

        self.delimiter_label.setVisible(is_csv)
        self.delimiter_combo.setVisible(is_csv)
        self.header_check.setVisible(fmt in ["csv", "xlsx"])

        self.compression_combo.clear()

        if fmt == "csv":
            self.compression_combo.addItem("None", "")
            self.compression_combo.addItem("gzip", "gzip")
            self.compression_combo.addItem("zstd", "zstd")
            self.compression_combo.addItem("lz4", "lz4")
            self.compression_label.setVisible(True)
            self.compression_combo.setVisible(True)

        elif fmt == "parquet":
            self.compression_combo.addItem("snappy (default)", "snappy")
            self.compression_combo.addItem("gzip", "gzip")
            self.compression_combo.addItem("zstd", "zstd")
            self.compression_combo.addItem("lz4", "lz4")
            self.compression_combo.addItem("uncompressed", "uncompressed")
            self.compression_label.setVisible(True)
            self.compression_combo.setVisible(True)

        else:
            self.compression_combo.addItem("None", "")
            self.compression_label.setVisible(False)
            self.compression_combo.setVisible(False)

    def get_options(self) -> dict[str, Any]:
        """Return the selected export options."""
        compression_val = self.compression_combo.currentData()
        return {
            "format": self.format_combo.currentData(),
            "delimiter": self.delimiter_combo.currentData(),
            "header": self.header_check.isChecked(),
            "compression": compression_val if compression_val is not None else "",
        }