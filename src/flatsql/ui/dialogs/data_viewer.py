"""Data viewer dialog for inspecting cell contents with JSON formatting."""
from __future__ import annotations

import json
import os

import polars as pl
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout, QWidget




class DataViewerDialog(QDialog):
    """Dialog for viewing large strings, JSON, structs, and lists.
    
    Automatically formats and pretty-prints structured data, converts Polars Series
    to native Python objects, and displays with a monospace font for readability.
    """

    def __init__(self, data: object, parent: QWidget | None = None) -> None:
        """Initialize the data viewer dialog.
        
        Args:
            data: The data to display (string, JSON, list, dict, or Polars object).
            parent: Parent widget (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("Data Viewer")
        self.resize(700, 600)

        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)

        # Use a monospace font for structured data
        if os.name == "nt":
            font = QFont("Consolas")
        else:
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(10)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferQuality)
        self.text_edit.setFont(font)
        self.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)

        # Clean and format the data
        formatted_text = self._format_data(data)
        self.text_edit.setPlainText(formatted_text)

        layout.addWidget(self.text_edit)

    @staticmethod
    def _clean_polars_types(obj: object) -> object:
        """Recursively convert Polars Series to Python native types.
        
        Args:
            obj: Object potentially containing Polars types.
        
        Returns:
            Object with all Polars types converted to native Python types.
        """
        if isinstance(obj, pl.Series):
            return obj.to_list()
        if isinstance(obj, list):
            return [DataViewerDialog._clean_polars_types(x) for x in obj]
        if isinstance(obj, dict):
            return {
                k: DataViewerDialog._clean_polars_types(v) for k, v in obj.items()
            }
        return obj

    @staticmethod
    def _format_data(data: object) -> str:
        """Format data for display with JSON pretty-printing.
        
        Attempts to parse strings as JSON for nicely formatted output.
        Falls back to string representation if formatting fails.
        
        Args:
            data: The data to format.
        
        Returns:
            Formatted string suitable for display.
        """
        cleaned_data = DataViewerDialog._clean_polars_types(data)

        try:
            if isinstance(cleaned_data, str):
                # Try parsing as JSON for pretty-printing
                stripped = cleaned_data.strip()
                if (
                    (stripped.startswith("{") and stripped.endswith("}"))
                    or (stripped.startswith("[") and stripped.endswith("]"))
                ):
                    try:
                        parsed = json.loads(cleaned_data)
                        return json.dumps(parsed, indent=4, default=str)
                    except (ValueError, json.JSONDecodeError):
                        return cleaned_data
                else:
                    return cleaned_data
            elif isinstance(cleaned_data, (list, dict)):
                return json.dumps(cleaned_data, indent=4, default=str)
            else:
                return str(cleaned_data)
        except Exception:
            return str(cleaned_data)
