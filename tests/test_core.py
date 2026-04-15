"""Unit tests for FlatSQL Studio core business logic.

These tests cover the modules that contain pure Python logic and do not
require a running Qt application or a real filesystem connection:

  - path_utils      — path normalization helpers
  - SQLGenerator    — SQL script generation
  - SettingsManager — settings load / get / set / save round-trip
  - HistoryManager  — query history persistence and deduplication

All tests that involve disk I/O use `tmp_path` (pytest) or `tempfile` so
they never pollute the real settings.json or userdata.duckdb.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import polars as pl
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QTextCursor
from PySide6.QtWidgets import QApplication

# Make sure the source tree is importable when running pytest from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# path_utils
# ---------------------------------------------------------------------------

class TestToDuckdbPath:
    """to_duckdb_path normalizes separators for use inside SQL strings."""

    def test_forward_slashes_unchanged(self) -> None:
        from flatsql.core.path_utils import to_duckdb_path

        assert to_duckdb_path("/data/files/query.csv") == "/data/files/query.csv"

    def test_backslashes_converted(self) -> None:
        from flatsql.core.path_utils import to_duckdb_path

        result = to_duckdb_path("C:\\Users\\test\\data.parquet")
        assert "\\" not in result
        assert result == "C:/Users/test/data.parquet"

    def test_mixed_separators(self) -> None:
        from flatsql.core.path_utils import to_duckdb_path

        result = to_duckdb_path("C:\\data/subfolder\\file.csv")
        assert result == "C:/data/subfolder/file.csv"

    def test_pathlib_path_accepted(self) -> None:
        from flatsql.core.path_utils import to_duckdb_path

        result = to_duckdb_path(Path("some") / "nested" / "file.csv")
        # Result must use only forward slashes
        assert "\\" not in result
        assert result.endswith("some/nested/file.csv")


class TestToDuckdbRelation:
    """to_duckdb_relation builds the correct DuckDB FROM expression."""

    def test_non_text_file_returns_quoted_path(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("C:\\data\\file.parquet") == "'C:/data/file.parquet'"

    def test_text_file_uses_read_text(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("C:\\data\\notes.txt") == "read_text('C:/data/notes.txt')"

    def test_globbed_text_path_uses_read_text(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("abfss://acct.blob.core.windows.net/container/**/*.txt") == (
            "read_text('abfss://acct.blob.core.windows.net/container/**/*.txt')"
        )

    def test_jsonl_uses_json_reader(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("C:\\data\\events.jsonl") == "read_json_auto('C:/data/events.jsonl')"

    def test_ndjson_uses_json_reader(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("C:\\data\\events.ndjson") == "read_json_auto('C:/data/events.ndjson')"

    def test_tab_uses_csv_reader_with_tab_delimiter(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("C:\\data\\sample.tab") == (
            "read_csv_auto('C:/data/sample.tab', delim='\\t')"
        )

    def test_psv_uses_csv_reader_with_pipe_delimiter(self) -> None:
        from flatsql.core.path_utils import to_duckdb_relation

        assert to_duckdb_relation("C:\\data\\sample.psv") == (
            "read_csv_auto('C:/data/sample.psv', delim='|')"
        )


# ---------------------------------------------------------------------------
# SQLGenerator
# ---------------------------------------------------------------------------

class TestSQLGeneratorMerge:
    """generate_merge_script builds correct DuckDB COPY statements."""

    def _details(self, **overrides: object) -> dict:
        base = {
            "source_ext": "csv",
            "out_name": "merged",
            "out_ext": ".csv",
            "recursive": False,
            "union_by_name": True,
        }
        base.update(overrides)
        return base

    def test_csv_output_contains_copy_keyword(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_merge_script("/data/folder", self._details())
        assert "COPY" in sql
        assert "FORMAT CSV" in sql

    def test_parquet_source_uses_read_parquet(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(source_ext="parquet", out_ext=".parquet")
        sql = SQLGenerator.generate_merge_script("/data/folder", details)
        assert "read_parquet" in sql

    def test_recursive_uses_double_star_glob(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(recursive=True)
        sql = SQLGenerator.generate_merge_script("/data/folder", details)
        assert "/**/*." in sql

    def test_non_recursive_uses_single_star_glob(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_merge_script("/data/folder", self._details())
        assert "/**/*." not in sql
        assert "/*.csv" in sql

    def test_output_filename_appended_if_missing_extension(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(out_name="result", out_ext=".csv")
        sql = SQLGenerator.generate_merge_script("/data", details)
        assert "result.csv" in sql

    def test_output_filename_not_duplicated_when_extension_present(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(out_name="result.csv", out_ext=".csv")
        sql = SQLGenerator.generate_merge_script("/data", details)
        assert "result.csv.csv" not in sql

    def test_text_source_uses_read_text(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(source_ext="txt")
        sql = SQLGenerator.generate_merge_script("/data/folder", details)
        assert "read_text('/data/folder/*.txt')" in sql

    def test_jsonl_source_uses_json_reader(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(source_ext="jsonl")
        sql = SQLGenerator.generate_merge_script("/data/folder", details)
        assert "read_json_auto('/data/folder/*.jsonl', union_by_name=true)" in sql

    def test_psv_source_uses_pipe_delimiter(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = self._details(source_ext="psv")
        sql = SQLGenerator.generate_merge_script("/data/folder", details)
        assert "read_csv_auto('/data/folder/*.psv', delim='|', union_by_name=true)" in sql


class TestSQLGeneratorSplit:
    """generate_split_script builds correct DuckDB COPY … partition statements."""

    def test_partition_mode_uses_partition_by(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = {
            "mode": "partition",
            "format": "parquet",
            "out_dir": "/out",
            "partition_col": "region",
        }
        sql = SQLGenerator.generate_split_script("/data/file.parquet", details)
        assert "PARTITION_BY" in sql
        assert "region" in sql

    def test_text_source_uses_read_text_relation(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        details = {
            "mode": "chunk",
            "format": "csv",
            "out_dir": "/out",
            "chunk_size": 100,
            "partition_col": "",
        }
        sql = SQLGenerator.generate_split_script("/data/file.txt", details)
        assert "FROM read_text('/data/file.txt')" in sql


class TestSQLGeneratorFileRelations:
    """File-backed SQL generation uses relation wrappers where needed."""

    def test_create_table_for_text_uses_read_text(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_create_table("/data/file.txt", "file.txt")
        assert "FROM read_text('/data/file.txt')" in sql

    def test_create_view_for_text_uses_read_text(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_create_view("/data/file.txt", "file.txt")
        assert "FROM read_text('/data/file.txt')" in sql

    def test_conversion_for_text_uses_read_text(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_conversion_script("/data/file.txt", "/out/file.csv", "csv")
        assert "SELECT * FROM read_text('/data/file.txt')" in sql


# ---------------------------------------------------------------------------
# SettingsManager
# ---------------------------------------------------------------------------

class TestSettingsManager:
    """SettingsManager correctly loads, merges, reads, writes, and saves settings."""

    @pytest.fixture()
    def tmp_settings(self, tmp_path: Path):
        """Provide a SettingsManager pointed at a temporary settings.json."""
        settings_file = tmp_path / "settings.json"
        # Patch SETTINGS_PATH so the manager reads/writes our temp file
        with patch("flatsql.core.settings.SETTINGS_PATH", str(settings_file)):
            with patch("flatsql.config.SETTINGS_PATH", str(settings_file)):
                from flatsql.core.settings import SettingsManager
                yield SettingsManager(), settings_file

    def test_defaults_applied_when_no_file(self, tmp_settings) -> None:
        manager, _ = tmp_settings
        assert manager.get("font_size") == 11
        assert manager.get("theme") == "dark.json"

    def test_get_unknown_key_returns_default(self, tmp_settings) -> None:
        manager, _ = tmp_settings
        assert manager.get("nonexistent_key", "fallback") == "fallback"

    def test_set_and_get_roundtrip(self, tmp_settings) -> None:
        manager, _ = tmp_settings
        manager.set("font_size", 14)
        assert manager.get("font_size") == 14

    def test_save_and_reload(self, tmp_settings) -> None:
        manager, settings_file = tmp_settings
        manager.set("font_size", 16)
        manager.save()

        with patch("flatsql.core.settings.SETTINGS_PATH", str(settings_file)):
            with patch("flatsql.config.SETTINGS_PATH", str(settings_file)):
                from flatsql.core.settings import SettingsManager
                reloaded = SettingsManager()
                assert reloaded.get("font_size") == 16

    def test_update_merges_dict(self, tmp_settings) -> None:
        manager, _ = tmp_settings
        manager.update({"font_size": 20, "theme": "nord.json"})
        assert manager.get("font_size") == 20
        assert manager.get("theme") == "nord.json"

    def test_corrupt_json_does_not_crash(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{bad json", encoding="utf-8")

        with patch("flatsql.core.settings.SETTINGS_PATH", str(settings_file)):
            with patch("flatsql.config.SETTINGS_PATH", str(settings_file)):
                from flatsql.core.settings import SettingsManager
                manager = SettingsManager()
                # Falls back to defaults
                assert manager.get("font_size") == 11


# ---------------------------------------------------------------------------
# HistoryManager
# ---------------------------------------------------------------------------

class TestHistoryManager:
    """HistoryManager persists and retrieves queries using an in-process DuckDB."""

    @pytest.fixture()
    def history(self, tmp_path: Path):
        """Provide a HistoryManager backed by a temporary DuckDB file."""
        db_file = tmp_path / "userdata.duckdb"
        settings_file = tmp_path / "settings.json"
        with patch("flatsql.core.history.SETTINGS_PATH", str(settings_file)):
            from flatsql.core.history import HistoryManager
            yield HistoryManager()

    def test_empty_on_init(self, history) -> None:
        assert history.get_recent_history(limit=10) == []

    def test_add_entry_and_retrieve(self, history) -> None:
        history.add_entry("SELECT 1", duration=0.01, rows=1)
        results = history.get_recent_history(limit=10)
        assert len(results) == 1
        assert results[0]["query"] == "SELECT 1"

    def test_consecutive_duplicate_not_added(self, history) -> None:
        history.add_entry("SELECT 1", duration=0.01, rows=1)
        history.add_entry("SELECT 1", duration=0.02, rows=1)
        results = history.get_recent_history(limit=10)
        assert len(results) == 1

    def test_non_consecutive_duplicate_is_added(self, history) -> None:
        history.add_entry("SELECT 1", duration=0.01, rows=1)
        history.add_entry("SELECT 2", duration=0.01, rows=1)
        history.add_entry("SELECT 1", duration=0.01, rows=1)
        results = history.get_recent_history(limit=10)
        assert len(results) == 3

    def test_empty_query_not_added(self, history) -> None:
        history.add_entry("   ", duration=0.0, rows=0)
        assert history.get_recent_history(limit=10) == []

    def test_retention_limit_enforced(self, history) -> None:
        for i in range(10):
            history.add_entry(f"SELECT {i}", duration=0.0, rows=0)
        history.enforce_retention_limit(5)
        results = history.get_recent_history(limit=100)
        assert len(results) == 5

    def test_result_contains_expected_keys(self, history) -> None:
        history.add_entry("SELECT 42", duration=1.5, rows=10)
        row = history.get_recent_history(limit=1)[0]
        assert set(row.keys()) >= {"query", "duration", "rows", "timestamp"}

    def test_get_recent_history_respects_limit(self, history) -> None:
        for i in range(10):
            history.add_entry(f"SELECT {i}", duration=0.0, rows=0)
        results = history.get_recent_history(limit=3)
        assert len(results) == 3

    def test_get_recent_history_order_is_newest_first(self, history) -> None:
        history.add_entry("SELECT 'first'", duration=0.0, rows=0)
        history.add_entry("SELECT 'second'", duration=0.0, rows=0)
        results = history.get_recent_history(limit=10)
        assert results[0]["query"] == "SELECT 'second'"
        assert results[1]["query"] == "SELECT 'first'"


# ---------------------------------------------------------------------------
# SQLGenerator — remaining methods
# ---------------------------------------------------------------------------

class TestSQLGeneratorSelectTop:
    """generate_select_top builds correct SELECT with quoted column names."""

    def test_empty_column_list_uses_star(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_select_top([], "my_table")
        assert "SELECT *" in sql
        assert "my_table" in sql

    def test_column_list_is_quoted(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_select_top(["id", "name"], "my_table", limit=50)
        assert '"id"' in sql
        assert '"name"' in sql
        assert "LIMIT 50" in sql

    def test_default_limit_is_1000(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_select_top(["id"], "t")
        assert "LIMIT 1000" in sql


class TestThemeDefinitions:
    """Theme definitions should preserve intended visual hierarchy."""

    def test_light_theme_uses_stronger_surface_contrast(self) -> None:
        theme_path = os.path.join(os.path.dirname(__file__), "..", "src", "flatsql", "assets", "themes", "light.json")
        with open(theme_path, "r", encoding="utf-8-sig") as theme_file:
            theme = json.load(theme_file)

        stylesheet = theme["stylesheet"]

        assert stylesheet["QFrame#query_frame"]["background-color"] != theme["palette"]["Window"]
        assert stylesheet["#queryToolbar"]["border-bottom"] == "1px solid #D6DCE5"
        assert stylesheet["#statusBar"]["background-color"] == "#F5F7FA"
        assert stylesheet["#statusBar"]["border-top"] == "2px solid #007ACC"
        assert stylesheet["QFrame#profileCard"]["background-color"] != stylesheet["QScrollArea#profileDashboard, QWidget#profileContainer"]["background-color"]
        assert theme["components"]["lineNumberArea"]["background"] == "#EEF2F6"

    def test_light_theme_keeps_shared_tab_basics_centralized(self) -> None:
        theme_path = os.path.join(os.path.dirname(__file__), "..", "src", "flatsql", "assets", "themes", "light.json")
        with open(theme_path, "r", encoding="utf-8-sig") as theme_file:
            theme = json.load(theme_file)

        stylesheet = theme["stylesheet"]

        assert "QTabBar::tab" not in stylesheet
        assert "QTabBar::tab:hover" not in stylesheet
        assert stylesheet["QTabBar::tab:selected"]["border-top"] == "2px solid #007ACC"

    def test_mint_theme_matches_light_surfaces_with_mint_accent(self) -> None:
        themes_dir = os.path.join(os.path.dirname(__file__), "..", "src", "flatsql", "assets", "themes")
        with open(os.path.join(themes_dir, "light.json"), "r", encoding="utf-8-sig") as theme_file:
            light_theme = json.load(theme_file)
        with open(os.path.join(themes_dir, "mint.json"), "r", encoding="utf-8-sig") as theme_file:
            mint_theme = json.load(theme_file)

        assert mint_theme["palette"]["Window"] == light_theme["palette"]["Window"]
        assert mint_theme["palette"]["Base"] == light_theme["palette"]["Base"]
        assert mint_theme["stylesheet"]["QFrame#query_frame"]["background-color"] == light_theme["stylesheet"]["QFrame#query_frame"]["background-color"]
        assert mint_theme["stylesheet"]["#statusBar"]["background-color"] == light_theme["stylesheet"]["#statusBar"]["background-color"]
        assert mint_theme["components"]["lineNumberArea"]["background"] == light_theme["components"]["lineNumberArea"]["background"]
        assert mint_theme["components"]["icon"] == light_theme["components"]["icon"]
        assert mint_theme["stylesheet"]["QTabBar::tab:selected"]["border-top"] == "2px solid #10B981"


class TestDownwardComboBox:
    """Shared combobox widget should keep a consistent default width."""

    def test_default_width_matches_export_dialog_style(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.ui.widgets import DownwardComboBox

        combo = DownwardComboBox()

        assert combo.minimumWidth() >= 200


class TestDbExplorerPanel:
    """Database explorer controls should remain compact and sensible."""

    def test_connection_combo_prefers_memory_when_no_active_tab(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.ui.panels.db_explorer_panel import DBExplorerPanel

        theme_manager = SimpleNamespace(
            theme_data={
                "stylesheet": {
                    "QCheckBox::indicator:checked": {"background-color": "#62a0ea"}
                }
            }
        )
        settings_manager = SimpleNamespace(get=lambda key, default=None: default)
        connections = {
            ":memory:": SimpleNamespace(
                get_database_objects=lambda: {"tables": [], "views": [], "system_views": [], "functions": []},
                get_display_name=lambda: ":memory:",
            ),
            "demo": SimpleNamespace(
                get_database_objects=lambda: {"tables": [], "views": [], "system_views": [], "functions": []},
                get_display_name=lambda: "demo",
            ),
        }

        with patch("flatsql.ui.panels.db_explorer_panel.qta.icon", return_value=QIcon()):
            panel = DBExplorerPanel({}, settings_manager, theme_manager, connections)
            panel.refresh()
            panel.sync_connection_combo(None)

        assert panel.connection_combo.currentData() == ":memory:"

    def test_connection_combo_does_not_expand_horizontally(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.ui.panels.db_explorer_panel import DBExplorerPanel

        theme_manager = SimpleNamespace(
            theme_data={
                "stylesheet": {
                    "QCheckBox::indicator:checked": {"background-color": "#62a0ea"}
                }
            }
        )
        settings_manager = SimpleNamespace(get=lambda key, default=None: default)
        connections = {
            ":memory:": SimpleNamespace(
                get_database_objects=lambda: {"tables": [], "views": [], "system_views": [], "functions": []},
                get_display_name=lambda: ":memory:",
            )
        }

        with patch("flatsql.ui.panels.db_explorer_panel.qta.icon", return_value=QIcon()):
            panel = DBExplorerPanel({}, settings_manager, theme_manager, connections)

        assert panel.connection_combo.sizePolicy().horizontalPolicy() != panel.connection_combo.sizePolicy().Policy.MinimumExpanding


class TestResultsPanel:
    """ResultsPanel should stay hidden until query output exists."""

    def test_results_panel_is_hidden_on_startup(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from PySide6.QtWidgets import QVBoxLayout, QWidget
        from flatsql.ui.panels.results_panel import ResultsPanel

        settings_manager = SimpleNamespace(get=lambda key, default=None: default)
        host = QWidget()
        layout = QVBoxLayout(host)
        panel = ResultsPanel(settings_manager, host)
        layout.addWidget(panel)
        host.show()
        QApplication.processEvents()

        assert panel.isVisible() is False


class TestUiScalingRegressions:
    """Dialogs should remain usable when Windows applies display scaling."""

    def test_startup_display_uses_pass_through_dpi_rounding(self) -> None:
        script = textwrap.dedent(
            """
            import os
            import sys

            os.environ['QT_QPA_PLATFORM'] = 'offscreen'
            sys.path.insert(0, os.path.join(os.getcwd(), 'src'))

            from PySide6.QtWidgets import QApplication
            from flatsql.config import configure_startup_display

            configure_startup_display()
            app = QApplication([])
            print(QApplication.highDpiScaleFactorRoundingPolicy().name)
            """
        )

        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True,
            text=True,
            check=False,
            cwd=os.path.join(os.path.dirname(__file__), '..'),
        )

        assert result.returncode == 0
        assert result.stdout.strip() == 'PassThrough'

    def test_settings_dialog_is_not_narrower_than_its_layout_hint(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.core.sql_generator import SQLGenerator
        from flatsql.ui.dialogs.settings import SettingsDialog

        dialog = SettingsDialog(
            {},
            {"dark.json": "Dark"},
            SQLGenerator.CONVERSION_FORMATS,
        )
        dialog.show()
        QApplication.processEvents()

        size_hint = dialog.sizeHint()

        assert dialog.width() >= size_hint.width()


class TestActionController:
    """ActionController routes UI actions to the query panel correctly."""

    def test_open_new_query_for_connection_uses_selected_connection(self) -> None:
        from flatsql.core.action_controller import ActionController

        captured_calls: list[dict[str, object]] = []
        query_panel = SimpleNamespace(
            add_new_tab=lambda **kwargs: captured_calls.append(kwargs)
        )
        main_window = SimpleNamespace(query_panel=query_panel)
        controller = ActionController(main_window)

        controller.open_new_query_for_connection("demo_connection")

        assert captured_calls == [{"connection_key": "demo_connection"}]


class TestQueryPanelTabReuse:
    """QueryPanel should preserve requested connection state when reusing tabs."""

    def test_query_panel_starts_with_empty_state_actions(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from PySide6.QtWidgets import QWidget
        from flatsql.ui.panels.query_panel import QueryPanel

        settings_manager = SimpleNamespace(
            get=lambda key, default=None: {
                "word_wrap": False,
                "font_size": 11,
            }.get(key, default)
        )
        conn_manager = SimpleNamespace(db_connections={})
        host = QWidget()
        host.db_keywords = []
        host.db_functions = []
        host.conn_manager = conn_manager

        panel = QueryPanel({}, settings_manager, conn_manager, object(), parent=host)

        assert panel.query_tabs.count() == 0
        assert panel.query_tabs.isHidden()
        assert not panel.query_placeholder.isHidden()
        assert panel.query_placeholder.icon_label.pixmap() is not None

        title_text = panel.query_placeholder.title_label.text().strip().lower()
        assert title_text
        assert "file" in title_text
        assert "query" in title_text or "start" in title_text

        assert not hasattr(panel.query_placeholder, "body_label")
        assert not hasattr(panel.query_placeholder, "helper_label")
        assert panel.query_placeholder.new_query_button.text() == "New Query"
        assert panel.query_placeholder.open_file_button.text() == "Open File"

    def test_blank_tab_reuse_applies_connection_key(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from PySide6.QtWidgets import QWidget
        from flatsql.ui.panels.query_panel import QueryPanel

        settings_manager = SimpleNamespace(
            get=lambda key, default=None: {
                "word_wrap": False,
                "font_size": 11,
            }.get(key, default)
        )
        conn_manager = SimpleNamespace(
            db_connections={"default_connection": object(), "other_connection": object()}
        )
        host = QWidget()
        host.db_keywords = []
        host.db_functions = []
        host.conn_manager = conn_manager
        host.connection_combo = None

        panel = QueryPanel({}, settings_manager, conn_manager, object(), parent=host)
        editor = panel.add_new_tab()
        panel.add_new_tab(connection_key="other_connection")

        assert editor.connection_key == "other_connection"


class TestQueryTextEditAutocomplete:
    """QueryTextEdit applies completion suggestions into the SQL text."""

    def test_autocomplete_can_be_disabled_by_setting(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.ui.editor import QueryTextEdit

        settings_manager = SimpleNamespace(
            get=lambda key, default=None: False if key == "sql_autocomplete_enabled" else default
        )
        editor = QueryTextEdit(theme_colors={})
        editor.set_main_window(SimpleNamespace(settings_manager=settings_manager))

        assert editor._is_autocomplete_enabled() is False

    def test_apply_completion_replaces_current_token(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.ui.editor import QueryTextEdit

        editor = QueryTextEdit(theme_colors={})
        editor.setPlainText("SEL")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.setTextCursor(cursor)

        editor.apply_completion("SELECT ", 0)

        assert editor.toPlainText() == "SELECT "


class TestPolarsModelHeaders:
    """PolarsModel exposes useful metadata for result-grid headers."""

    def test_header_has_type_tooltip(self) -> None:
        app = QApplication.instance() or QApplication([])
        assert app is not None

        from flatsql.ui.models import PolarsModel

        model = PolarsModel(
            pl.DataFrame(
                {
                    "event_date": ["2024-01-01"],
                    "amount": [42.5],
                    "is_active": [True],
                }
            )
        )

        tooltip = model.headerData(1, Qt.Horizontal, Qt.ToolTipRole)

        assert isinstance(tooltip, str)
        assert tooltip == "event_date (String)"
        assert model.headerData(1, Qt.Horizontal, Qt.DecorationRole) is None


class TestSQLGeneratorFlattenedSelect:
    """generate_flattened_select wraps STRUCT columns and leaves others plain."""

    def test_struct_column_uses_unnest(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        schema = [("address", "STRUCT(city VARCHAR, zip VARCHAR)"), ("name", "VARCHAR")]
        sql = SQLGenerator.generate_flattened_select(schema, "/data/file.parquet")
        assert "UNNEST" in sql
        assert '"address"' in sql

    def test_non_struct_column_is_plain(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        schema = [("id", "INTEGER"), ("value", "DOUBLE")]
        sql = SQLGenerator.generate_flattened_select(schema, "/data/file.parquet")
        assert "UNNEST" not in sql
        assert '"id"' in sql
        assert '"value"' in sql

    def test_file_path_uses_forward_slashes(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_flattened_select([], "C:\\data\\file.parquet", limit=500)
        assert "C:/data/file.parquet" in sql
        assert "LIMIT 500" in sql


class TestSQLGeneratorConversion:
    """generate_conversion_script emits correct COPY … FORMAT statements."""

    def test_csv_format(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_conversion_script("/in/f.parquet", "/out/f.csv", "csv")
        assert "FORMAT CSV" in sql

    def test_parquet_format(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_conversion_script("/in/f.csv", "/out/f.parquet", "parquet")
        assert "FORMAT PARQUET" in sql

    def test_xlsx_includes_spatial_install(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_conversion_script("/in/f.csv", "/out/f.xlsx", "xlsx")
        assert "INSTALL spatial" in sql
        assert "DRIVER" in sql

    def test_unknown_format_returns_error_comment(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_conversion_script("/in/f.csv", "/out/f.xyz", "xyz")
        assert sql.startswith("-- Error")


class TestSQLGeneratorCreateTableView:
    """generate_create_table and generate_create_view sanitize filenames correctly."""

    def test_create_table_uses_file_stem(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_create_table("/data/sales_2024.csv", "sales_2024.csv")
        assert "CREATE TABLE sales_2024" in sql

    def test_create_table_replaces_hyphens_and_spaces(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_create_table("/data/my-file name.csv", "my-file name.csv")
        assert "my_file_name" in sql

    def test_create_view_adds_vw_prefix(self) -> None:
        from flatsql.core.sql_generator import SQLGenerator

        sql = SQLGenerator.generate_create_view("/data/orders.parquet", "orders.parquet")
        assert "CREATE VIEW vw_orders" in sql


class TestFlatEngineViewDdlNormalization:
    """Simple scripted view projections are normalized consistently."""

    def test_normalize_view_definition_quotes_simple_projections(self) -> None:
        from flatsql.core.engine import FlatEngine

        sql = (
            'CREATE VIEW main.vw_test AS\n'
            'SELECT\n'
            '    "Index",\n'
            '    Name,\n'
            '    Description\n'
            "FROM 'C:/data/products.csv'\n"
            'LIMIT 1000'
        )

        normalized = FlatEngine._normalize_view_definition(sql)

        assert '"Index"' in normalized
        assert '"Name"' in normalized
        assert '"Description"' in normalized

    def test_normalize_view_definition_leaves_complex_expressions(self) -> None:
        from flatsql.core.engine import FlatEngine

        sql = (
            'CREATE VIEW main.vw_test AS\n'
            'SELECT\n'
            '    Name,\n'
            '    SUM(amount) AS total_amount\n'
            'FROM sales\n'
            'GROUP BY Name'
        )

        normalized = FlatEngine._normalize_view_definition(sql)

        assert 'SUM(amount) AS total_amount' in normalized
        assert '"Name"' in normalized


# ---------------------------------------------------------------------------
# logger — _normalize_logger_name regression
# ---------------------------------------------------------------------------

class TestNormalizeLoggerName:
    """_normalize_logger_name strips the flatsql root prefix to avoid duplication."""

    def test_strips_flatsql_prefix(self) -> None:
        from flatsql.core.logger import _normalize_logger_name

        assert _normalize_logger_name("flatsql.core.engine") == "core.engine"

    def test_leaves_non_flatsql_name_unchanged(self) -> None:
        from flatsql.core.logger import _normalize_logger_name

        assert _normalize_logger_name("myapp.module") == "myapp.module"

    def test_bare_flatsql_name_unchanged(self) -> None:
        from flatsql.core.logger import _normalize_logger_name

        # Exactly the root name — not a child path, leave unchanged.
        assert _normalize_logger_name("flatsql") == "flatsql"

    def test_get_logger_name_has_no_duplicate_prefix(self) -> None:
        from flatsql.core.logger import get_logger

        logger = get_logger("flatsql.core.engine")
        # Must be "flatsql.core.engine", not "flatsql.flatsql.core.engine".
        assert logger.name == "flatsql.core.engine"
