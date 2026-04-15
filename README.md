# FlatSQL Studio

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

![Runs on Windows](https://img.shields.io/badge/runs%20on%20-Windows-blue)

FlatSQL Studio is a desktop SQL client for querying flat files and cloud-backed storage directly with DuckDB. It is designed for fast local analytics workflows without spinning up a database server.

## Key Features

- DuckDB-powered SQL execution.
- Multi-tab SQL editor with syntax highlighting and formatting.
- File Explorer and Database Explorer side panels.
- Results grid, messages panel, and profiling/visualization tools.
- Theme support with multiple bundled themes.
- Export to CSV, Parquet, JSON, and Excel.
- Ability to mount external file systems (for example Azure) and databases (for example DuckDB and Databricks).

## Tech Stack

- GUI: PySide6
- Query Engine: DuckDB
- Data Processing: Polars
- SQL Formatting: SQLFluff
- Visualization: Matplotlib

## Project Layout

```text
.
|- run.py
|- requirements.txt
|- src/
|  |- flatsql/
|  |  |- main.py
|  |  |- config.py
|  |  |- core/
|  |  |- ui/
|  |  |- assets/
|- snippets/
|- tests/
```

## Installation

### Prerequisites

- Python 3.10+
- pip

### Setup

```bash
pip install -r requirements.txt
```

### Run

```bash
python run.py
```

## Usage

1. Open FlatSQL Studio.
2. Drag a file into the query area or use File Explorer.
3. Run SQL against your files.
4. Review results in the grid and messages tabs.
5. Save useful queries as snippets for reuse.

## Verify

Run tests:

```bash
pytest
```

## Architecture

FlatSQL Studio follows a layered architecture:

- core: business logic, query execution, settings, connectors.
- ui: panels, dialogs, models, and custom widgets.
- main window: composition and signal wiring between UI and controllers.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full walkthrough.

## Development

For contributor setup, workflow, and expectations, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and project expectations.

## License

FlatSQL Studio is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Roadmap

- Additional connectors (AWS, GCP, and more).
- Built-in Delta support.
- Additional database explorer functionality.
- Flat file pivot tables.
- Data and schema compare tools.
- Advanced snippet functionalities (for example parameters).

