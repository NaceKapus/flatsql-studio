"""Syntax highlighting for DuckDB SQL with precedence-aware rules."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat


class SqlHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for DuckDB SQL with theme-aware formatting."""

    def __init__(
        self,
        parent: object | None = None,
        keywords: list[str] | set[str] | None = None,
        functions: list[str] | set[str] | None = None,
        theme_colors: dict[str, str] | None = None,
    ) -> None:
        """Initialize highlighting rules for SQL tokens and comments."""
        super().__init__(parent)

        if keywords is None:
            keywords = []
        if functions is None:
            functions = []

        # --- Define Default Theme Colors ---
        if theme_colors is None:
            theme_colors = {
                "quoted_identifier": "#9CDCFE",
                "string": "#CE9178",
                "keyword": "#569CD6",
                "function": "#C586C0",
                "comment": "#6A9955"
            }

        # --- Helper to Create Formats ---
        def create_format(color_hex: str) -> QTextCharFormat:
            """Creates a QTextCharFormat from a hex color string."""
            char_format = QTextCharFormat()
            char_format.setForeground(QColor(color_hex))
            return char_format

        # --- Define Formats from Theme ---
        # Stored as instance variables to be accessible in highlightBlock for precedence checks
        self.quoted_identifier_format = create_format(theme_colors.get('quoted_identifier', "#9CDCFE"))
        self.string_format = create_format(theme_colors.get('string', "#CE9178"))
        self.single_line_comment_format = create_format(theme_colors.get('comment', "#6A9955"))
        self.multi_line_comment_format = create_format(theme_colors.get('comment', "#6A9955"))
        self.function_format = create_format(theme_colors.get('function', "#C586C0"))
        keyword_format = create_format(theme_colors.get('keyword', "#569CD6"))

        # --- Create Highlighting Rules in Order of Precedence ---
        self.highlighting_rules = []

        # 1. High-precedence rules for elements that should never be overridden.
        self.highlighting_rules.append((QRegularExpression(r'"[^"]*"'), self.quoted_identifier_format))
        self.highlighting_rules.append((QRegularExpression(r"'[^']*'"), self.string_format))
        self.highlighting_rules.append((QRegularExpression(r'--[^\n]*'), self.single_line_comment_format))

        # 2. Functions Rule (Applied BEFORE keywords).
        # This ensures that if a name is both a keyword and a function (e.g., "LEFT"),
        # it's correctly identified as a function when followed by '('.
        if functions:
            escaped_functions = [QRegularExpression.escape(func) for func in functions]
            function_pattern = r'\b(' + '|'.join(escaped_functions) + r')\b(?=\s*\()'
            self.highlighting_rules.append((QRegularExpression(function_pattern, QRegularExpression.PatternOption.CaseInsensitiveOption), self.function_format))

        if keywords:
            escaped_keywords = [QRegularExpression.escape(kw) for kw in keywords]
            keyword_pattern = r'\b(' + '|'.join(escaped_keywords) + r')\b'
            self.highlighting_rules.append((QRegularExpression(keyword_pattern, QRegularExpression.PatternOption.CaseInsensitiveOption), keyword_format))

        # --- Multi-line Comment Logic ---
        self.comment_start_expression = QRegularExpression(r"/\*")
        self.comment_end_expression = QRegularExpression(r"\*/")

    def highlightBlock(self, text: str) -> None:
        """Apply syntax highlighting to a block of SQL text."""
        for pattern, format_to_apply in self.highlighting_rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                start = match.capturedStart()
                length = match.capturedLength()

                existing_format = self.format(start)
                if existing_format in (
                    self.string_format,
                    self.quoted_identifier_format,
                    self.single_line_comment_format,
                    self.function_format
                ):
                    continue

                self.setFormat(start, length, format_to_apply)

        self.setCurrentBlockState(0)

        start_index = 0
        if self.previousBlockState() != 1:
            match = self.comment_start_expression.match(text)
            start_index = match.capturedStart() if match.hasMatch() else -1
        
        while start_index >= 0:
            if self.format(start_index) in (self.string_format, self.quoted_identifier_format):
                next_match = self.comment_start_expression.match(text, start_index + 1)
                start_index = next_match.capturedStart() if next_match.hasMatch() else -1
                continue

            end_match = self.comment_end_expression.match(text, start_index)
            end_index = end_match.capturedStart() if end_match.hasMatch() else -1
            
            comment_length = 0
            if end_index == -1:
                self.setCurrentBlockState(1)
                comment_length = len(text) - start_index
            else:
                comment_length = end_index - start_index + end_match.capturedLength()
            
            self.setFormat(start_index, comment_length, self.multi_line_comment_format)

            next_match = self.comment_start_expression.match(text, start_index + comment_length)
            start_index = next_match.capturedStart() if next_match.hasMatch() else -1