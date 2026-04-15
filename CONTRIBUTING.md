# Contributing to FlatSQL

Thank you for contributing to FlatSQL.

## Before You Start

- Open an issue before starting major changes so the direction can be discussed first.
- Keep pull requests focused. Small, scoped changes are easier to review and merge.
- If your change affects behavior, include a clear explanation of the user-facing impact.

## Development Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python run.py
```

Run tests:

```bash
pytest
```

## Project Expectations

- Use PySide6 for UI work.
- Use Polars for dataframe operations.
- Keep UI code procedural Python. Do not introduce `.ui` XML files.
- Do not block the main UI thread with database work or heavy file I/O.
- Use signals and the existing query worker/controller flow for background query execution.
- Follow the existing project structure and naming patterns.
- Add type hints and docstrings for new or modified functions and methods.
- Use cross-platform path handling with `os.path` or `pathlib`.
- Keep styling in the theme/QSS system rather than hardcoding widget colors.

## Pull Requests

- Describe what changed and why.
- Mention any tradeoffs, follow-up work, or known limitations.
- Include screenshots or short recordings for UI changes when practical.
- Update documentation when the behavior or workflow changes.
- Add or update tests where it makes sense.

## Scope Guidance

Good contributions include:

- Bug fixes
- UI polish
- Performance improvements
- Documentation updates
- Tests
- New connectors or query workflow improvements

Please avoid mixing unrelated refactors into feature or bug-fix pull requests.

## Questions

If you are unsure about architecture or implementation direction, open an issue first. That is usually faster than revising a large pull request later.