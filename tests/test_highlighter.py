"""Unit tests for the SQL syntax highlighter.

These tests drive :class:`flatsql.core.highlighter.SqlHighlighter` against a
real ``QTextDocument`` and read back the formats it applies. Highlighter
formats are presentation overlays on the block layout (not document character
formats), so they are inspected via ``block.layout().formats()`` rather than a
``QTextCursor``.

A ``QApplication`` is required for the Qt text layout to exist; the repo has no
``conftest`` / ``pytest-qt``, so we follow the same inline pattern used in
``test_core.py``.
"""
from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

# Make sure the source tree is importable when running pytest from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# Distinct, easily distinguishable colors so each token class is unambiguous.
THEME = {
    "quoted_identifier": "#111111",
    "string": "#222222",
    "keyword": "#333333",
    "function": "#444444",
    "comment": "#555555",
    "number": "#666666",
}
KEYWORDS = ["SELECT", "FROM", "LEFT"]
# LEFT is intentionally both a keyword and a function (function must win).
FUNCTIONS = ["LEFT", "COUNT"]


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    """Ensure a single QApplication exists for the layout engine."""
    app = QApplication.instance() or QApplication([])
    assert app is not None
    return app


def _highlight(sql: str) -> QTextDocument:
    """Return a QTextDocument with the SQL highlighter applied."""
    from flatsql.core.highlighter import SqlHighlighter

    doc = QTextDocument()
    doc.setPlainText(sql)
    highlighter = SqlHighlighter(doc, KEYWORDS, FUNCTIONS, theme_colors=THEME)
    highlighter.rehighlight()
    return doc


def _color_at(doc: QTextDocument, pos: int) -> str | None:
    """Return the foreground color hex applied at character ``pos``, or None."""
    block = doc.findBlock(pos)
    if not block.isValid():
        return None
    rel = pos - block.position()
    color: str | None = None
    # Later ranges win, mirroring how QSyntaxHighlighter overwrites formats.
    for fmt_range in block.layout().formats():
        if fmt_range.start <= rel < fmt_range.start + fmt_range.length:
            brush = fmt_range.format.foreground()
            if brush.style() != Qt.NoBrush:
                color = brush.color().name().lower()
    return color


class TestSqlHighlighter:
    """SqlHighlighter applies theme colors to SQL token classes."""

    def test_escaped_string_is_one_span(self) -> None:
        """'O''Brien' is a single string literal, colored end to end."""
        sql = "SELECT 'O''Brien'"
        doc = _highlight(sql)
        start = sql.index("'O''Brien'")
        end = start + len("'O''Brien'")
        # Every character of the literal, including across the '' escape, is a string.
        for pos in range(start, end):
            assert _color_at(doc, pos) == THEME["string"], f"pos {pos} not string"

    def test_escaped_quoted_identifier_is_one_span(self) -> None:
        """\"col\"\"x\" is a single quoted identifier, colored end to end."""
        sql = 'SELECT "col""x" FROM t'
        doc = _highlight(sql)
        start = sql.index('"col""x"')
        end = start + len('"col""x"')
        for pos in range(start, end):
            assert _color_at(doc, pos) == THEME["quoted_identifier"], f"pos {pos} not identifier"

    def test_numeric_literals_highlighted(self) -> None:
        """Integers, decimals, and scientific notation are colored as numbers."""
        sql = "SELECT 42, 3.14, 1e9"
        doc = _highlight(sql)
        for literal in ("42", "3.14", "1e9"):
            start = sql.index(literal)
            for pos in range(start, start + len(literal)):
                assert _color_at(doc, pos) == THEME["number"], f"{literal!r} pos {pos} not number"

    def test_digits_inside_identifiers_are_not_numbers(self) -> None:
        """Digits embedded in identifiers (col1, t1) keep no number color."""
        sql = "SELECT col1 FROM t1"
        doc = _highlight(sql)
        assert _color_at(doc, sql.index("col1") + 3) != THEME["number"]  # the '1' in col1
        assert _color_at(doc, sql.index("t1") + 1) != THEME["number"]    # the '1' in t1

    def test_dollar_quoted_strings_highlighted(self) -> None:
        """$$...$$ and $tag$...$tag$ are colored as strings."""
        sql = "SELECT $$hi$$, $t$bye$t$"
        doc = _highlight(sql)
        for literal in ("$$hi$$", "$t$bye$t$"):
            start = sql.index(literal)
            for pos in range(start, start + len(literal)):
                assert _color_at(doc, pos) == THEME["string"], f"{literal!r} pos {pos} not string"

    def test_unterminated_dollar_tag_not_highlighted(self) -> None:
        """A lone $foo with no closing tag is not treated as a string."""
        sql = "SELECT $foo FROM t"
        doc = _highlight(sql)
        start = sql.index("$foo")
        for pos in range(start, start + len("$foo")):
            assert _color_at(doc, pos) != THEME["string"], f"pos {pos} wrongly string"

    def test_keyword_and_number_inside_string_not_recolored(self) -> None:
        """Keyword-like words and digits inside a string keep the string color."""
        sql = "SELECT 'FROM SELECT 42'"
        doc = _highlight(sql)
        literal = "'FROM SELECT 42'"
        start = sql.index(literal)
        for pos in range(start, start + len(literal)):
            assert _color_at(doc, pos) == THEME["string"], f"pos {pos} not string"

    def test_tokens_inside_line_comment_stay_comment(self) -> None:
        """Keywords and numbers inside a -- comment keep the comment color."""
        sql = "SELECT 1 -- FROM 5"
        doc = _highlight(sql)
        assert _color_at(doc, sql.index(" 1 ") + 1) == THEME["number"]     # the leading 1
        comment_start = sql.index("--")
        for pos in range(comment_start, len(sql)):
            assert _color_at(doc, pos) == THEME["comment"], f"pos {pos} not comment"

    def test_tokens_inside_block_comment_stay_comment(self) -> None:
        """Numbers inside a /* */ block comment keep the comment color."""
        sql = "/* block 99 */ SELECT"
        doc = _highlight(sql)
        nine = sql.index("99")
        assert _color_at(doc, nine) == THEME["comment"]
        assert _color_at(doc, sql.index("SELECT")) == THEME["keyword"]

    def test_function_wins_over_keyword(self) -> None:
        """A name that is both keyword and function is a function when called."""
        sql = "SELECT LEFT('a', 1)"
        doc = _highlight(sql)
        assert _color_at(doc, sql.index("LEFT")) == THEME["function"]
        assert _color_at(doc, sql.index("SELECT")) == THEME["keyword"]
        assert _color_at(doc, sql.index("'a'")) == THEME["string"]
        assert _color_at(doc, sql.index(", 1") + 2) == THEME["number"]
