#!/usr/bin/env python3
"""Console entry point for Easy Docker Manager."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from shutil import get_terminal_size
from typing import Optional

from easy_docker_manager.app.app import EDMApp
from easy_docker_manager.config import AppConfigStore
from easy_docker_manager.constants import (
    MINIMUM_TERMINAL_COLUMNS,
    MINIMUM_TERMINAL_ROWS,
)
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.diagnostics import (
    DockerConnectionStatus,
    create_initial_diagnostics_report,
    format_diagnostics_report,
    get_installed_edm_version,
)
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.local_container_client import LocalDockerContainerClient
from easy_docker_manager.logging.app_logging import configure_logging


def _installed_version() -> str:
    """Read EDM's version from the installed package metadata.

    setuptools-scm creates this version from the Git release tag when the
    package is built. Returning "unknown" keeps --help and --version usable when
    the source is run without installed package metadata.
    """
    return get_installed_edm_version()


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
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="print application and Docker diagnostics, then exit",
    )
    return parser


def _check_minimum_terminal_size() -> bool:
    """Check that the terminal is large enough to display EDM.

    EDM calls this before loading its config or starting background work. If
    the terminal is too small, the function prints the current and required
    sizes so the user knows how far to resize it.
    """
    terminal_size = get_terminal_size(fallback=(0, 0))
    if (
        terminal_size.columns >= MINIMUM_TERMINAL_COLUMNS
        and terminal_size.lines >= MINIMUM_TERMINAL_ROWS
    ):
        return True

    print(
        "Error: EDM requires a terminal size of at least "
        f"{MINIMUM_TERMINAL_COLUMNS} columns by {MINIMUM_TERMINAL_ROWS} rows.\n"
        f"Current terminal size: {terminal_size.columns} columns by "
        f"{terminal_size.lines} rows.\n"
        "Resize the terminal and run EDM again.",
        file=sys.stderr,
    )
    return False


def _print_diagnostics() -> int:
    """Print a diagnostics report and return whether Docker was reachable."""
    report = create_initial_diagnostics_report()
    docker_container_client = LocalDockerContainerClient(
        create_docker_client=partial(
            create_docker_client,
            AppConfig().docker_request_timeout,
        )
    )
    try:
        try:
            docker_daemon_details = docker_container_client.get_docker_daemon_details()
        except Exception as exc:
            report.record_failed_docker_connection(exc)
        else:
            report.record_successful_docker_connection(docker_daemon_details)
    finally:
        docker_container_client.close()

    print(format_diagnostics_report(report))
    return (
        0 if report.docker_connection_status == DockerConnectionStatus.CONNECTED else 1
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Process command options and start EDM when no exit option is used.

    The installed edm command and python -m easy_docker_manager both call this
    function. Help, version, and diagnostics output do not start the terminal
    interface. Other options are applied after EDM loads its config.
    """
    command_options = _build_argument_parser().parse_args(argv)
    if command_options.diagnostics:
        return _print_diagnostics()
    if not _check_minimum_terminal_size():
        return 1

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
