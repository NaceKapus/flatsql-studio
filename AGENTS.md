# Project Context: FlatSQL Studio

## Role
You are an expert Python, PySide6, and DuckDB developer. Your task is to maintain and extend FlatSQL Studio, an open-source desktop SQL client.

## Overview
FlatSQL Studio queries flat files (CSV, Parquet, JSON, Excel, etc.) and cloud storage (Azure, Databricks) directly using DuckDB.

## Tech Stack
- **GUI Framework:** PySide6 (Qt for Python)
- **Database Engine:** DuckDB
- **DataFrames:** Polars (`import polars as pl`)
- **SQL Formatting:** SQLFluff
- **Visualizations:** Matplotlib (`QtAgg` backend)

## Architecture Map

### Root Level
- `flatsql/main.py`: Entry point (`QMainWindow`). Sets up UI layout, initializes controllers, wires core signals to UI slots.
- `flatsql/config.py`: Centralized config, path management, PyInstaller `_MEIPASS` handling.

### `flatsql/core/` (Business Logic & State - NO UI IMPORTS)
- `engine.py` (`FlatEngine`): DuckDB connection wrapper, schema extraction, DDL generation.
- `connection_manager.py`: DB/FS connection lifecycle (Local, Azure, Unity Catalog) via OS Keyring.
- `connector.py`: Abstract/concrete FS connectors.
- `query_controller.py` & `worker.py`: PySide6 `QThread`/`QueryWorker` managers for async SQL execution.
- `action_controller.py`: Orchestrator mapping UI events to core operations.
- `sql_generator.py`: Generates utility SQL scripts.
- `history.py`: Stores query history in `userdata.duckdb`.
- `theme.py` & `highlighter.py`: QSS theme injection and syntax highlighting.
- `settings.py`: Manages user preferences in `settings.json`.
- `exporter.py`: Polars-based high-speed dataframe exports.

### `flatsql/ui/` (Presentation Layer - PROCEDURAL PYTHON ONLY)
- `models.py`: Custom Qt item models (e.g., `PolarsModel` for fast data grid rendering).
- `editor.py` (`QueryTextEdit`): Custom `QPlainTextEdit` with line numbers and auto-indent.
- `widgets.py`: Reusable custom widgets (`DownwardComboBox`, `BoxPlotWidget`, etc.).
- `menu_bar.py`: App menu actions and shortcuts.
- **`panels/`**: Main dockable split-panes (`query_panel.py`, `results_panel.py`, `db_explorer_panel.py`, `file_explorer_panel.py`, `snippet_panel.py`).
- **`dialogs/`**: Application popups (`visualize.py`, `file_ops.py`, `profiler.py`, `databricks_dialog.py`).

---

## Strict Coding Rules

### 1. Framework Constraints
- **DO:** Strictly use `PySide6` and `polars`.
- **DON'T:** Never import or use `PyQt5`, `PyQt6`, `tkinter`, or `pandas`.
- **DON'T:** Never use `.ui` XML files. All UI must be procedural Python.

### 2. Threading & Performance
- **DO:** Execute all DuckDB queries via `QueryController` and `QueryWorker` using PySide6 `QThread`s.
- **DO:** Use PySide6 `Signal`s for all cross-thread and cross-component communication.
- **DON'T:** Never block the main UI thread with database transactions or heavy file I/O.

### 3. Code Quality & Formatting
- **DO:** Follow PEP 8 strictly.
- **DO:** Write standard docstrings and comprehensive **type hints** for ALL new and existing classes, functions, and methods.
- **DO:** Write cross-platform code using `os.path` or `pathlib`.
- **DO:** Retroactively add docstrings and type hints if you modify an existing method that lacks them.

### 4. Paths & Theming
- **DO:** Use constants from `flatsql.config` (e.g., `ASSETS_DIR`) with `os.path.join()`.
- **DO:** Manage styling via `flatsql/core/theme.py` or dynamic palette calls (`self.palette().color()`).
- **DON'T:** Never hardcode file paths or relative paths.
- **DON'T:** Never hardcode hex colors directly into widget classes.

### 5. Output Generation (CRITICAL)
- **DO:** Output ONLY the requested code or architectural answers.
- **DO:** Precede your code with a short bulleted warning list IF you discover existing code that violates these legacy rules.
- **DON'T:** No conversational filler, no greetings, and no meta-commentary (e.g., remove phrases like "Here is the updated code", "I fixed the loop").