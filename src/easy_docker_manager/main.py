#!/usr/bin/env python3
"""Console entry point for Easy Docker Manager."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Optional

from easy_docker_manager.app import EDMApp
from easy_docker_manager.config import AppConfigStore
from easy_docker_manager.logging.app_logging import configure_logging

DISTRIBUTION_NAME = "easy-docker-manager"


def _installed_version() -> str:
    """Read EDM's version from the installed package metadata.

    setuptools-scm creates this version from the Git release tag when the
    package is built. The fallback keeps help available when the source is run
    without installed package metadata.
    """
    try:
        return distribution_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "unknown"


def _build_argument_parser() -> argparse.ArgumentParser:
    """Create the parser used by the edm command and package module."""
    parser = argparse.ArgumentParser(
        prog="edm",
        description=(
            "Inspect local Docker containers in a keyboard-driven terminal "
            "interface. Run without options to start EDM."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_installed_version()}",
        help="show the installed EDM version and exit",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Handle command options or start the terminal application.

    The installed edm command and python -m easy_docker_manager both call this
    function. Help and version options exit during argument parsing. With no
    options, EDM configures logging, loads its config, and opens the terminal
    interface.
    """
    _build_argument_parser().parse_args(argv)
    configure_logging()
    app_config = AppConfigStore().load_and_sync()
    app = EDMApp(app_config=app_config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
