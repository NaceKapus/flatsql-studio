# FlatSQL Studio

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The SQL IDE for Flat files.

![FlatSQL Studio](./flatsql-studio.png)

## Key Features

- Drag-and-drop query interface for querying flat files.
- DuckDB-powered SQL execution.
- Multi-tab SQL editor with syntax highlighting and formatting.
- Integrated File Explorer.
- Theme support with multiple bundled themes.
- Export to CSV, Parquet, JSON, and Excel.
- Ability to mount external file systems (e.g. Azure) and databases (e.g. DuckDB and Databricks Unity Catalog).

## Installing FlatSQL Studio

### Download (recommended)

Download the latest release from the [Releases](../../releases/latest) page:

- **Windows** — run `FlatSQL-Studio-Windows-Setup.exe` and follow the installer. No admin rights required; you can install per-user or system-wide. SmartScreen may warn on first launch (the installer is not yet signed) — click "More info" → "Run anyway".
- **macOS** — unzip `FlatSQL-Studio-macOS.zip` and move `FlatSQL Studio.app` to your Applications folder. On first launch, right-click → Open to bypass the Gatekeeper warning (the app is not yet signed).

### Run from source

```bash
pip install -r requirements.txt
python run.py
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full walkthrough of the codebase.

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow and project expectations.

## License

FlatSQL Studio is licensed under the MIT License. See [LICENSE](LICENSE) for details.
