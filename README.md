# FlatSQL

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Runs on Windows](https://img.shields.io/badge/runs%20on-Linux%20%7C%20MacOS%20%7C%20Windows-blue)

FlatSQL is a desktop SQL client for querying flat files and cloud-backed storage directly with DuckDB. It is designed for fast local analytics workflows without spinning up a database server.

## Why FlatSQL

- Query CSV, TSV, PSV, Parquet, JSON, JSON Lines, text, and Excel with SQL in seconds.
- Explore schemas, generate helper SQL, and inspect results in a responsive desktop UI.
- Export query outputs to common formats for downstream workflows.
- Keep everything local-first while still supporting cloud connection scenarios.

## Key Features

- DuckDB-powered SQL execution.
- Multi-tab SQL editor with syntax highlighting and formatting.
- File Explorer and Database Explorer side panels.
- Results grid, messages panel, and profiling/visualization tools.
- Theme support with multiple bundled themes.
- Export to CSV, Parquet, JSON, and Excel.
- Azure and Databricks related connectivity flows.

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

1. Open FlatSQL.
2. Drag a file into the query area or use File Explorer.
3. Run SQL against your files.
4. Review results in the grid and messages tabs.
5. Save useful queries as snippets for reuse.

## Architecture

FlatSQL follows a layered architecture:

- core: business logic, query execution, settings, connectors.
- ui: panels, dialogs, models, and custom widgets.
- main window: composition and signal wiring between UI and controllers.

See ARCHITECTURE.md for a full walkthrough.

## Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python run.py
```

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and project expectations.

## License

FlatSQL is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Roadmap Ideas

- Additional connectors (AWS, GCP, and more).
- Built-in Delta support.
- Additional database explorer functionality.

