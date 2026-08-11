#!/usr/bin/env python3
"""Console entry point for Easy Docker Manager."""

from __future__ import annotations

from easy_docker_manager.app import EDMApp
from easy_docker_manager.config import AppConfigStore
from easy_docker_manager.logging.app_logging import configure_logging


def main() -> int:
    """Set up logging and config, run EDM, and return a successful exit code."""
    configure_logging()
    app_config = AppConfigStore().load_and_sync()
    app = EDMApp(app_config=app_config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
