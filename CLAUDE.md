# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt                              # install dependencies
python run.py                                                 # run the desktop app

pytest                                                        # run all tests
pytest tests/test_core.py::TestSQLGeneratorMerge              # run a single test class
pytest tests/test_core.py::TestSQLGeneratorMerge -k merge     # filter by name within a class
```

There is no Python linter wired into the repo — PEP 8 is enforced by convention. SQL files are formatted with SQLFluff; see [.sqlfluff](.sqlfluff). Release binaries are built by [.github/workflows/release.yml](.github/workflows/release.yml) on tag push (`v*`); local PyInstaller invocation is not part of the dev loop.

## Architecture

FlatSQL Studio is a PySide6 desktop SQL client backed by DuckDB. The codebase is split into two layers with a strict one-way dependency:

- **[src/flatsql/core/](src/flatsql/core/)** — business logic, DB engine, connection management, threading. **Must not import from `flatsql.ui`.**
- **[src/flatsql/ui/](src/flatsql/ui/)** — Qt panels, dialogs, widgets. May import from `flatsql.core`.

[ARCHITECTURE.md](ARCHITECTURE.md) has the full module map. Three concerns span multiple files and aren't obvious from any one of them:

**1. Async query execution.** Every DuckDB query goes through `QueryController` ([src/flatsql/core/query_controller.py](src/flatsql/core/query_controller.py)), which moves a `QueryWorker` ([src/flatsql/core/worker.py](src/flatsql/core/worker.py)) onto a fresh `QThread` and emits results back via Qt signals. The main UI thread never executes SQL directly. New long-running operations must follow the same pattern.

**2. Signal-based wiring.** UI panels emit signals (e.g., `run_query_requested`); `ActionController` ([src/flatsql/core/action_controller.py](src/flatsql/core/action_controller.py)) is the central glue that translates UI signals into core operations. Components never hold direct references across the core/UI boundary.

**3. Connection lifecycle.** `ConnectionManager` ([src/flatsql/core/connection_manager.py](src/flatsql/core/connection_manager.py)) tracks all open DB/FS connections and stores credentials in the OS keyring via the `keyring` package, never on disk. Each editor tab is associated with a connection *key*, not a connection object. `connector.py` provides `AbstractConnector` plus concrete implementations for Local, Azure, and Databricks Unity Catalog.

## Project rules

These are non-negotiable conventions — violating them breaks the app's design or runtime:

- **PySide6 only.** Never use PyQt5, PyQt6, or tkinter.
- **Polars only.** Never use pandas.
- **No `.ui` XML files.** All UI is procedural Python; do not introduce Qt Designer files.
- **Core never imports UI.** `flatsql.core.*` must not import anything from `flatsql.ui.*`.
- **Never block the main thread.** All DB queries and heavy I/O run via `QueryController`/`QueryWorker` or an equivalent `QThread` pattern.
- **No hardcoded paths or colors.** Asset paths come from `flatsql.config` constants; styling goes through the QSS/JSON theme system in [src/flatsql/core/theme.py](src/flatsql/core/theme.py), never inline `setStyleSheet("color: #fff")` calls.
- **Type hints + docstrings on new or modified code.** Add `from __future__ import annotations` at the top of new files.

## Packaging and runtime paths

Two different path roots that often get confused:

- **Read-only assets** (themes, `.sqlfluff`, templates, icons) are bundled by PyInstaller via `--add-data` and resolved through `sys._MEIPASS`. See [src/flatsql/config.py](src/flatsql/config.py): when frozen, `_PKG_DIR = sys._MEIPASS`; otherwise it falls back to the package directory. Use the `ASSETS_DIR`, `THEMES_DIR`, `SQLFLUFF_CONFIG_PATH`, etc. constants — never hardcode paths assuming the source-checkout layout.
- **User-writable data** (settings, query history, snippets, logs) lives under `platformdirs.user_data_dir(APP_NAME)` → `%APPDATA%\FlatSQL\FlatSQL Studio\` on Windows, `~/Library/Application Support/FlatSQL Studio/` on macOS. Never write next to the executable.

The Windows release produces a `--onedir` PyInstaller bundle wrapped in an Inno Setup installer ([packaging/windows/FlatSQL-Studio.iss](packaging/windows/FlatSQL-Studio.iss)); the macOS release produces a zipped `.app`. The `AppId` GUID in the Inno Setup script must remain stable across releases — changing it makes upgrades install side-by-side instead of in place.

## Adding things

- **New cloud connector**: subclass `AbstractConnector` in `core/connector.py`, register in `core/connection_manager.py`, add a dialog under `ui/dialogs/`.
- **New theme**: drop a JSON file into `src/flatsql/assets/themes/`; it is auto-discovered. Structure mirrors [src/flatsql/assets/themes/dracula.json](src/flatsql/assets/themes/dracula.json).
- **New file format**: add a read method to `core/engine.py`, generation logic to `core/sql_generator.py`, and a context-menu entry in `ui/panels/file_explorer_panel.py`.
