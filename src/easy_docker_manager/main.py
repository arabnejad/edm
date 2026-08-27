#!/usr/bin/env python3
"""Console entry point for Easy Docker Manager."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Optional

from easy_docker_manager.app.app import EDMApp
from easy_docker_manager.config import AppConfigStore
from easy_docker_manager.logging.app_logging import configure_logging

DISTRIBUTION_NAME = "easy-docker-manager"


def _installed_version() -> str:
    """Read EDM's version from the installed package metadata.

    setuptools-scm creates this version from the Git release tag when the
    package is built. Returning "unknown" keeps --help and --version usable when
    the source is run without installed package metadata.
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
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable terminal colors for this run",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Process command options and start EDM when no exit option is used.

    The installed edm command and python -m easy_docker_manager both call this
    function. Help and version options exit during argument parsing. Other
    options are applied after EDM loads its config and before the terminal
    interface opens.
    """
    command_options = _build_argument_parser().parse_args(argv)
    configure_logging()
    app_config = AppConfigStore().load_and_sync()
    if command_options.no_color:
        app_config = replace(app_config, colors_enabled=False)
    app = EDMApp(app_config=app_config)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
