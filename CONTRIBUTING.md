# Contributing To EDM

Thank you for helping improve Easy Docker Manager.

## Before You Start

- Search existing issues before opening a new one.
- Use the bug or feature issue form when it matches your request.
- Discuss large changes in an issue before spending time implementing them.
- Report security problems privately by following [SECURITY.md](SECURITY.md).

## Development Setup

Fork and clone the repository, then create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Linux or macOS:

```bash
source .venv/bin/activate
```

Activate it in Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install EDM and its development tools:

```bash
python -m pip install --upgrade pip
python -m pip install --group dev --group security -e .
pre-commit install
```

The development tools require a recent pip version because pip uses the
dependency groups defined in `pyproject.toml`.

## Making A Change

1. Create a branch from the latest `main` branch.
2. Keep the change focused on one problem.
3. Follow the existing module boundaries described in
   [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md).
4. Add or update tests when behavior changes.
5. Update the README or development guide when needed.

Run the full local check before opening a pull request:

```bash
make check
```

You can also run all pre-commit hooks directly:

```bash
make pre-commit
```

The project requires at least 95% test coverage. See
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#development-commands) for the
individual formatting, linting, type, security, test, and package commands.

## Pull Requests

- Explain what changed and why.
- Link any related issue.
- Describe how you tested the change.
- Keep unrelated refactoring out of the same pull request.
- Make sure all GitHub Actions checks pass.

A maintainer may ask for changes before merging. Review comments are part of
the collaboration process, so ask when a request is unclear.
