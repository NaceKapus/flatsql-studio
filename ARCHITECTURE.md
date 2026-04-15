# FlatSQL Architecture Guide

## Overview

FlatSQL is a desktop SQL client for querying flat files (CSV, Parquet, JSON, Excel) and cloud storage (Azure, Databricks) directly using DuckDB. The application is built on:

- **GUI Framework:** PySide6 (Qt for Python)
- **Database Engine:** DuckDB
- **Data Processing:** Polars
- **Styling:** QSS + JSON theming system
- **Threading:** PySide6 QThread for async operations

This guide explains the architecture, design decisions, and how to extend FlatSQL.

---

## System Architecture

### High-Level Flow

```
User Input (UI)
    ↓
Action Controller (translates UI events to operations)
    ↓
Query Controller (manages threading)
    ↓
Query Worker (executes in background thread)
    ↓
FlatEngine (DuckDB wrapper)
    ↓
Connector (file system / cloud storage)
    ↓
Results → UI Updates (via Qt Signals)
```

---

## Module Map

### Root Level

- **`flatsql/main.py`** (`QMainWindow`)
  - Entry point for the GUI
  - Sets up UI layout, initializes controllers
  - Wires signals/slots between panels and controllers
  - Manages application lifecycle

- **`flatsql/config.py`**
  - Centralized application constants (APP_VERSION, paths)
  - Path management with PyInstaller `_MEIPASS` support
  - Settings directory and asset directory helpers

- **`run.py`**
  - Application entry point
  - Initializes settings manager and theme manager
  - Applies theme and shows main window

---

### `flatsql/core/` — Business Logic & State

**Important:** Core modules must **NOT import from `flatsql.ui`** to keep business logic decoupled.

#### Query Execution (Threading)
- **`query_controller.py`** (`QueryController`)
  - Spawns `QThread` workers for SQL execution
  - Emits signals on completion/error
  - Manages query cancellation

- **`worker.py`** (`QueryWorker`)
  - Runs in background `QThread`
  - Executes DuckDB queries and collects results
  - Handles profiling and memory tracking

#### Database & Connections
- **`engine.py`** (`FlatEngine`)
  - DuckDB connection wrapper
  - Schema inspection and DDL generation
  - Temporary database creation for session isolation

- **`connection_manager.py`** (`ConnectionManager`)
  - Lifecycle management for DB/FS connections
  - OS Keyring integration for credential storage
  - Support for Local, Azure, and Unity Catalog connections

- **`connector.py`**
  - Abstract connector base class
  - Concrete implementations: `LocalFileSystemConnector`, `AzureConnector`, etc.
  - Handles authentication and file listing

#### Utilities
- **`action_controller.py`** (`ActionController`)
  - Orchestrator that maps UI events to core operations
  - Bridges between UI signals and query/connection logic

- **`sql_generator.py`** (`SQLGenerator`)
  - Generates SELECT, CREATE TABLE, CREATE VIEW, DDL scripts
  - Handles file format detection and schema generation

- **`history.py`** (`HistoryManager`)
  - Stores query history in `userdata.duckdb`
  - Supports retrieval and filtering

- **`settings.py`** (`SettingsManager`)
  - Loads/saves user preferences from `settings.json`
  - Handles defaults and validation

- **`theme.py`** (`ThemeManager`)
  - Loads theme JSON files (with UTF-8 BOM tolerance)
  - Builds Qt stylesheets from base QSS + theme-specific colors
  - Applies palette and styles to the Qt application

- **`highlighter.py`** (`SqlHighlighter`)
  - Syntax highlighting for SQL editor
  - Uses DuckDB keywords and function lists

- **`logger.py`**
  - Centralized logging configuration
  - File rotation and console output

- **`path_utils.py`**
  - Cross-platform path normalization for DuckDB SQL literals

- **`exporter.py`** (`ExportManager`)
  - High-speed data export using Polars
  - Supports CSV, Parquet, JSON, Excel formats

---

### `flatsql/ui/` — Presentation Layer

**Important:** UI modules are procedural Python only. **NO .ui XML files.**

#### Core Components
- **`models.py`**
  - `PolarsModel`: Qt table model wrapping Polars DataFrames (fast rendering)
  - `FileExplorerModel`: Drag-drop file model with Azure path support

- **`editor.py`**
  - `QueryTextEdit`: Custom `QPlainTextEdit` with line numbers, auto-indent, zoom
  - `LineNumberArea`: Custom widget for rendering line numbers

- **`widgets.py`**
  - `DownwardComboBox`: Dropdown that opens downward
  - `MultiselectComboBox`: Multi-select with checkboxes
  - `DropZoneList`: List widget for drag-drop operations
  - `QueryTabWidget`: Tab widget with file drop support
  - `ExplorerTreeView`: Generic tree with loading state handling
  - `BoxPlotWidget`: Custom box plot visualization
  - `ColumnProfileCard`: Profile statistic card for data profiling
  - `FlowLayout`: Wrapping layout for profile cards
  - `ProfileDashboard`: Scrollable dashboard of profile cards

- **`menu_bar.py`** (`MainMenuBar`)
  - File, Edit, View, Search, Query, Tools, Help menus
  - Action shortcuts and keyboard bindings

#### Panels (Dockable Widgets)
- **`panels/query_panel.py`** (`QueryPanel`)
  - Query editor tabs with file drop support
  - Toolbar (Run, Stop, New, Open, Save, Format, Comment)
  - Find/Replace and Go-to-Line dialogs

- **`panels/results_panel.py`** (`ResultsPanel`)
  - Tabbed widget: Results grid + Messages tab
  - Profile dashboard toggle
  - Export and Visualize buttons
  - Live memory tracking

- **`panels/db_explorer_panel.py`** (`DBExplorerPanel`)
  - Connected databases and schema tree
  - Right-click context menu for DDL scripts
  - Lazy-loaded columns

- **`panels/file_explorer_panel.py`** (`FileExplorerPanel`)
  - Local and cloud file systems
  - Favorites pinning
  - File operations: merge, split, convert, create table/view
  - Azure path conversion for query building

- **`panels/snippet_panel.py`** (`SnippetPanel`)
  - SQL snippet tree from `snippets/` directory
  - Folder organization and search

#### Dialogs (Popups)
- **`dialogs/find.py`**: Find, Find/Replace, Go-to-Line
- **`dialogs/visualize.py`**: Matplotlib chart builder
- **`dialogs/settings.py`**: User preferences dialog
- **`dialogs/db_connection_dialog.py`**: Database connection type chooser
- **`dialogs/file_connection_dialog.py`**: File-system connection type chooser
- **`dialogs/data_viewer.py`**: Cell content viewer
- **`dialogs/profiler.py`**: DuckDB profiler output
- **`dialogs/file_ops.py`**: File merge, split, convert, export
- **`dialogs/azure_dialog.py`**: Azure authentication
- **`dialogs/databricks_dialog.py`**: Databricks workspace browser

---

## Core Concepts

### 1. Threading & Async Execution

**Why:** DuckDB queries can block the UI. All queries run in background threads.

**How it works:**
1. User clicks "Run Query" in the editor
2. `QueryPanel` emits `run_query_requested` signal
3. `ActionController` receives signal and calls `QueryController.execute_query()`
4. `QueryController` creates a `QueryWorker` and moves it to a new `QThread`
5. Worker executes the query, emits `query_completed` signal with results
6. Main thread receives signal and updates UI

**Key files:**
- [flatsql/core/query_controller.py](flatsql/core/query_controller.py)
- [flatsql/core/worker.py](flatsql/core/worker.py)
- [flatsql/ui/panels/query_panel.py](flatsql/ui/panels/query_panel.py) (UI layer)

**Pattern for new async operations:**
```python
# In core module (no UI imports):
class MyWorker(QObject):
    completed = Signal(object)  # Emit results
    error = Signal(str)
    
    @Slot()
    def run_operation(self):
        try:
            result = expensive_operation()
            self.completed.emit(result)
        except Exception as e:
            self.error.emit(str(e))

# In UI module:
def trigger_operation(self):
    worker = MyWorker()
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run_operation)
    worker.completed.connect(self.on_operation_complete)
    thread.start()
```

---

### 2. Theming System

**Architecture:** Separation of concerns between structure and color.

- **Base stylesheet** (`assets/themes/base_style.qss`): Layout, padding, borders, margins
- **Theme JSON** (`assets/themes/*.json`): Colors, palettes, component-specific overrides

**Flow:**
1. User selects theme in settings
2. `ThemeManager` loads the JSON file (BOM-safe decoding)
3. `_build_stylesheet()` merges base QSS + theme-specific selectors
4. `apply()` sets Qt palette and applies the combined stylesheet

**Why two files?**
- Base QSS is reusable across all themes (no duplication)
- Theme JSON can be easily edited for per-theme color variations
- Easier for designers to preview and tweak colors

**Theme JSON structure:**
```json
{
  "name": "Dracula",
  "sort_order": 1,
  "palette": {
    "Window": "#282a36",
    "Base": "#21222c",
    "Text": "#f8f8f2",
    "Disabled": {
      "Text": "#6272a4"
    }
  },
  "stylesheet": {
    "QListWidget::item:hover": {
      "background-color": "#44475a"
    },
    "#profileCard": {
      "border-color": "#6272a4",
      "background-color": "#21222c"
    }
  }
}
```

**How to add a new theme:**
1. Create `assets/themes/mytheme.json`
2. Copy structure from [assets/themes/dracula.json](assets/themes/dracula.json)
3. Edit colors and add `"sort_order"` for menu position
4. Theme appears automatically in settings dialog

---

### 3. Signal/Slot Communication

Qt Signals are used extensively for loose coupling between components:

- **Cross-component communication:** UI → Controllers → Core
- **Thread safety:** Signals automatically marshal data across threads
- **Decoupling:** Components don't need direct references

**Example:**
```python
# In query_panel.py
run_query_requested = Signal()

def on_run_button_clicked(self):
    self.run_query_requested.emit()  # Emit to controller

# In main.py
self.query_panel.run_query_requested.connect(
    self.action_controller.execute_query
)
```

---

### 4. Connection Management

**Supported connection types:**
- Local DuckDB files (`:memory:` or `*.duckdb`)
- Azure Data Lake Storage (ADLS) with device flow auth
- Databricks SQL endpoints
- Future: Snowflake, BigQuery, etc.

**Lifecycle:**
1. `ConnectionManager` stores connections in OS Keyring (secure)
2. When tab is created, connection key is stored on editor
3. Query execution uses the connection's `FlatEngine`
4. On disconnection, tabs are reassigned to default connection

---

### 5. Data Export & Visualization

- **Export:** [flatsql/core/exporter.py](flatsql/core/exporter.py) uses Polars for high-speed multi-format export
- **Visualization:** Matplotlib with `QtAgg` backend for in-app charts
- **Profiling:** Column stats (null %, unique count, distribution) rendered as cards

---

## Development Setup

### Prerequisites
- Python 3.10+
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/FlatSQL.git
   cd FlatSQL
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run FlatSQL:**
   ```bash
   python run.py
   ```

### Running Tests

(To be added when test suite is established)

---

## Extension Points

### Adding a New File Format

1. Create a new method in [flatsql/core/engine.py](flatsql/core/engine.py):
   ```python
   def read_custom_format(self, path: str) -> pl.DataFrame:
       """Read custom format using DuckDB."""
       query = f"SELECT * FROM read_custom('{path}')"
       return self.execute_query(query)
   ```

2. Update [flatsql/core/sql_generator.py](flatsql/core/sql_generator.py) to generate SELECT for the format.

3. Add UI in [flatsql/ui/panels/file_explorer_panel.py](flatsql/ui/panels/file_explorer_panel.py) context menu.

### Adding a New Cloud Provider

1. Create a new connector class in [flatsql/core/connector.py](flatsql/core/connector.py):
   ```python
   class MyCloudConnector(AbstractConnector):
       def list_files(self, path: str) -> list[str]:
           # Implement listing
       def authenticate(self):
           # Implement auth flow
   ```

2. Register in [flatsql/core/connection_manager.py](flatsql/core/connection_manager.py).

3. Add UI dialog in `flatsql/ui/dialogs/mycloud_dialog.py`.

### Adding a Theme

See **Theming System** section above.

### Adding a Keyboard Shortcut

1. Edit [flatsql/ui/menu_bar.py](flatsql/ui/menu_bar.py):
   ```python
   action = QAction("My Action", self)
   action.setShortcut(QKeySequence("Ctrl+Shift+M"))
   action.triggered.connect(self.on_my_action)
   menu.addAction(action)
   ```

---

## Coding Standards

### Type Hints
All functions and methods must have type hints:
```python
def process_data(df: pl.DataFrame, limit: int = 1000) -> dict[str, Any]:
    """Process the dataframe and return results."""
    pass
```

### Docstrings
Use standard docstring format:
```python
def my_function(param1: str, param2: int) -> bool:
    """Short description.
    
    Longer explanation if needed.
    
    Args:
        param1: Description of param1.
        param2: Description of param2.
        
    Returns:
        Description of return value.
    """
```

### Imports
- Standard library imports first
- Third-party imports second
- Local imports last
- Use `from __future__ import annotations` at the top of each file

### Code Style
- Follow PEP 8 strictly
- Max line length: 100 characters
- Use meaningful variable names

### No Hardcoding
- Asset paths: Use constants from `flatsql.config`
- Colors: Use theme system
- Fonts: Use system fonts where possible
- Paths: Use `os.path` or `pathlib`

---

## FAQ

**Q: Why separate core and ui modules?**  
A: Clean separation of concerns. Core is business logic; UI is presentation. Makes testing easier and keeps the app responsive.

**Q: How do I add logging?**  
A: Use the centralized logger:
```python
from flatsql.core.logger import get_logger
logger = get_logger(__name__)
logger.info("Something happened")
logger.warning("Potential issue", exc_info=e)
```

**Q: How do I handle long operations?**  
A: Create a `QThread` worker with signals. Never block the main thread.

**Q: Can I use pandas instead of polars?**  
A: No. FlatSQL is committed to Polars for performance. Pandas is slow on large datasets.

---

## References

- [Qt for Python Documentation](https://doc.qt.io/qtforpython/)
- [DuckDB SQL Reference](https://duckdb.org/docs/sql/introduction)
- [Polars Documentation](https://www.pola.rs/api/python/)
- [PEP 8 Style Guide](https://pep8.org/)
