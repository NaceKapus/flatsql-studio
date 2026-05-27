<div align="center">

# FlatSQL Studio

**Drag a file. Write SQL. Get answers in under a second.**

A native desktop SQL IDE for querying CSV, Parquet, JSON, and Excel files, extensible with Azure Data Lake and Databricks Unity Catalog connectors. Powered by [DuckDB](https://duckdb.org/) and [Polars](https://www.pola.rs/).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey.svg)](#install)
[![Built with DuckDB](https://img.shields.io/badge/built%20with-DuckDB-FFF000.svg)](https://duckdb.org/)

[**Download**](../../releases/latest) · [**Architecture**](ARCHITECTURE.md) · [**Contributing**](CONTRIBUTING.md) · [**Report a bug**](../../issues)

</div>

## Why FlatSQL Studio?

Sometimes you just need answers from a file.

Not a database project. Not a notebook environment. Not a data platform migration. Just open the file, write SQL, inspect the results, and move on with your day.

FlatSQL Studio is designed for the moments where the setup would outlast the actual work. Query CSV, Parquet, JSON, and Excel files directly — with a real SQL editor, autocomplete, visualizations, and sub-second performance on millions of rows.

Because ad-hoc data work deserves good tools too.

## Features

- **Instant querying** — Double-click or drag any flat file to generate a `SELECT` automatically. Sub-second results on millions of rows thanks to DuckDB + Polars.
- **Integrated file explorer** — Browse local disks, mounted cloud storage, and favorites in a side panel. Right-click any file for *Show Schema*, *Show Stats*, *Split / Partition*, *Convert To*, or *Script As*.
- **Multi-tab SQL editor** — Syntax highlighting, auto-formatting, find/replace and live autocomplete from your data.
- **Cloud-native** — First-class support for Azure Data Lake Storage and Databricks Unity Catalog.
- **Built-in visualization** — 10 chart types (Bar, Line, Area, Scatter, Pie, Donut, Heatmap, Pivot Table, and stacked variants) without leaving the app.
- **Column profiling** — One-click instant data profiling for every column.
- **Export anywhere** — CSV, Parquet, JSON, Excel. High-speed Polars-backed writers.
- **16 themes** — Dracula, Tokyo Night, Nord, Gruvbox, Monokai, Solarized, and more.
- **Snippets library** — Curated DuckDB snippets out of the box; add your own.
- **Native desktop performance** — Built on PySide6/Qt. No Electron, no web wrapper, no waiting.

## Install

### Download (recommended)

Grab the latest installer from the [**Releases page**](../../releases/latest):

| Platform | File | Notes |
|----------|------|-------|
| **Windows** | `FlatSQL-Studio-Windows-Setup.exe` | Per-user or system-wide; no admin required |
| **macOS** | `FlatSQL-Studio-macOS.zip` | Unzip, drag to Applications |

> [!NOTE]
> The installers are not yet code-signed (signing certs are expensive for solo OSS projects). On first launch:
> - **Windows**: SmartScreen may show a warning → click *More info* → *Run anyway*.
> - **macOS**: Right-click the app → *Open* to bypass Gatekeeper.
>
> If you'd rather not, you can [run from source](#run-from-source) or [verify checksums](../../releases/latest) before installing.

### Run from source

```bash
git clone https://github.com/NaceKapus/flatsql-studio.git
cd flatsql-studio
pip install -r requirements.txt
python run.py
```

Requires Python 3.10+.

## Quickstart

1. **Open FlatSQL Studio.**
2. **Navigate to a file** in the File Explorer (or drag one in from your OS file manager).
3. **Double-click the file.** A `SELECT` query is generated and a result grid appears — usually in well under a second.

That's the whole onboarding. Everything else is normal SQL:

```sql
-- Query a local CSV directly
SELECT category, COUNT(*) AS n, AVG(price) AS avg_price
FROM 'C:/data/products-2000000.csv'
GROUP BY category
ORDER BY n DESC;

-- Join a CSV against a Parquet file
SELECT o.order_id, o.total, c.country
FROM 'orders.parquet' o
JOIN 'customers.csv' c USING (customer_id);

-- Query Azure ADLS (after mounting via the Connect dialog)
SELECT * FROM 'azure://my-container/sales/*.parquet'
WHERE event_date >= '2025-01-01';
```

## Documentation

- [**ARCHITECTURE.md**](ARCHITECTURE.md) — Module map, threading model, theming system, extension points.
- [**CONTRIBUTING.md**](CONTRIBUTING.md) — How to contribute, coding standards, PR workflow.

## Roadmap

Currently working on / considering:

- [ ] Additional connectors (GCP, AWS, MotherDuck,...)
- [ ] Documentation site
- [ ] Native delta lake / iceberg support

Have a request? [Open an issue](../../issues/new) — solo-maintained projects move faster when the audience is loud about what they want.

## Contributing

Pull requests, bug reports, and feature ideas are all welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and coding standards.

If you find FlatSQL Studio useful, the most helpful thing you can do is ⭐ **star the repo** — discoverability is the biggest blocker for small OSS projects, and stars genuinely move the needle.

## Acknowledgments

FlatSQL Studio stands on the shoulders of:

- [**DuckDB**](https://duckdb.org/) — the analytical SQL engine that makes this all fast.
- [**Polars**](https://www.pola.rs/) — high-speed DataFrame library powering the result grid and exports.
- [**PySide6 / Qt**](https://doc.qt.io/qtforpython/) — the GUI framework.
- [**sqlfluff**](https://sqlfluff.com/) — SQL formatting.
- [**qtawesome**](https://github.com/spyder-ide/qtawesome) — icon system.

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
<sub>Built by <a href="https://github.com/NaceKapus">@NaceKapus</a> </sub>
</div>