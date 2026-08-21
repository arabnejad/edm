from __future__ import annotations

import importlib
import importlib.metadata
import os
import pkgutil
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Union

import pytest
from platformdirs import user_config_dir

import easy_docker_manager
from easy_docker_manager.app import app as app_module
from easy_docker_manager.app.background_notifier import (
    PipeBackgroundNotifier,
    PollingBackgroundNotifier,
    create_background_notifier,
)
from easy_docker_manager.config.app_config_store import default_config_path
from easy_docker_manager.constants import APP_NAME
from easy_docker_manager.core import AppConfig, ContainerProcessTable, ContainerSummary
from easy_docker_manager.docker.base import ContainerDataSource
from easy_docker_manager.logging.app_logging import default_log_file_path

pytestmark = pytest.mark.smoke


def _run_installed_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command assembled by this test and return its captured output."""
    # Every argument is fixed by the smoke test; no user input reaches the process.
    return subprocess.run(  # noqa: S603
        command,
        check=True,
        capture_output=True,
        text=True,
    )


class SmokeTestContainerDataSource(ContainerDataSource):
    """Provide predictable container data without requiring a Docker daemon."""

    def __init__(self) -> None:
        self.list_request_count = 0
        self.closed = False

    def list_running_containers(self) -> list[ContainerSummary]:
        self.list_request_count += 1
        return [
            ContainerSummary(
                container_id="smoke-container-id",
                name="edm-smoke-container",
                status="running",
            )
        ]

    def get_logs(
        self,
        container_id: str,
        tail_lines: Union[int, str] = 100,
        since_timestamp: Optional[int] = None,
    ) -> str:
        return "INFO Starting smoke-test service\n" "INFO Smoke-test service is ready"

    def get_environment_variables(self, container_id: str) -> dict[str, str]:
        return {
            "APP_ENV": "smoke-test",
            "LOG_LEVEL": "INFO",
        }

    def get_docker_inspection_data(self, container_id: str) -> dict[str, Any]:
        return {
            "container": {
                "Id": "smoke-container-id",
                "Name": "/edm-smoke-container",
                "Image": "sha256:smoke-image-id",
                "Config": {
                    "Hostname": "smoke-container",
                    "Image": "python:3.12-slim",
                    "Labels": {"com.docker.compose.service": "smoke"},
                },
                "State": {
                    "Status": "running",
                    "Running": True,
                    "Pid": 1,
                },
                "HostConfig": {
                    "NetworkMode": "bridge",
                    "LogConfig": {"Type": "json-file", "Config": {}},
                },
                "NetworkSettings": {
                    "Networks": {"bridge": {"IPAddress": "172.17.0.2"}}
                },
            },
            "image": {
                "Id": "sha256:smoke-image-id",
                "RepoTags": ["python:3.12-slim"],
                "Os": "linux",
                "Architecture": "amd64",
            },
        }

    def get_process_list(self, container_id: str) -> ContainerProcessTable:
        return ContainerProcessTable(
            columns=("PID", "USER", "COMMAND"),
            rows=(
                ("1", "root", "python app.py"),
                ("2", "app", "python worker.py"),
            ),
        )

    def close(self) -> None:
        self.closed = True


class SmokeTestMainLoop:
    """Replace Urwid's interactive event loop during the startup smoke test.

    A real urwid.MainLoop opens the terminal, waits for keyboard input, runs
    scheduled timer callbacks, and redraws the screen. That behavior would
    block an automated test. EDMApp still creates and uses this replacement in
    the normal way, but run() returns immediately so the test can verify both
    startup and shutdown.

    The methods below provide only the parts of Urwid's interface that EDM uses:
    timers on every operating system and a notification pipe on Linux and
    macOS. They do not simulate user input or execute scheduled callbacks.
    """

    def __init__(
        self,
        widget: Any,
        palette: list[tuple[str, ...]],
        handle_mouse: bool,
    ) -> None:
        self.widget = widget
        self.palette = palette
        self.handle_mouse = handle_mouse
        self._pipe_read: Optional[int] = None

    def run(self) -> None:
        """Return immediately instead of opening and controlling a terminal."""

    def set_alarm_in(self, seconds: float, callback: Any) -> object:
        """Return a handle for a timer without waiting or calling its callback.

        Urwid calls these timers alarms. EDM uses them to decide when to check
        for container updates and, on Windows, for completed background tasks.
        A real MainLoop would call callback after seconds. This test only needs
        an object that EDM can later pass to remove_alarm() during shutdown.
        """
        return object()

    def remove_alarm(self, alarm_handle: object) -> bool:
        """Pretend that a previously scheduled timer was cancelled.

        EDM calls this when it replaces a timer or shuts down. No real timer
        exists in this test, so returning True is enough to match Urwid's
        successful-cancellation result.
        """
        return True

    def watch_pipe(self, callback: Any) -> int:
        """Create the notification pipe used on Linux and macOS.

        In production, Urwid watches the read end and calls callback when a
        background worker writes to the other end. The smoke test does not wait
        for notifications, but it creates real file descriptors so notifier
        startup and shutdown follow their normal path.
        """
        pipe_read, pipe_write = os.pipe()
        self._pipe_read = pipe_read
        return pipe_write

    def remove_watch_pipe(self, pipe_write: int) -> bool:
        """Stop the fake pipe watch and close the stored read descriptor.

        PipeBackgroundNotifier closes pipe_write after this method returns, so
        this method closes only the matching read end.
        """
        if self._pipe_read is not None:
            os.close(self._pipe_read)
            self._pipe_read = None
        return True


def test_installed_distribution_exposes_all_edm_modules_and_console_command() -> None:
    module_names = [
        module.name
        for module in pkgutil.walk_packages(
            easy_docker_manager.__path__,
            prefix=f"{easy_docker_manager.__name__}.",
        )
    ]

    for module_name in module_names:
        importlib.import_module(module_name)

    installed_distribution = importlib.metadata.distribution("easy-docker-manager")
    edm_commands = [
        command
        for command in installed_distribution.entry_points
        if command.group == "console_scripts" and command.name == "edm"
    ]
    assert len(edm_commands) == 1
    assert edm_commands[0].value == "easy_docker_manager.main:main"
    assert shutil.which("edm") is not None


def test_installed_cli_supports_help_version_and_package_module() -> None:
    installed_version = importlib.metadata.version("easy-docker-manager")
    edm_command = shutil.which("edm")
    assert edm_command is not None

    help_result = _run_installed_command([edm_command, "--help"])
    command_version_result = _run_installed_command([edm_command, "--version"])
    module_version_result = _run_installed_command(
        [sys.executable, "-m", "easy_docker_manager", "--version"]
    )

    assert "usage: edm [-h] [--version]" in help_result.stdout
    assert command_version_result.stdout == f"edm {installed_version}\n"
    assert module_version_result.stdout == f"edm {installed_version}\n"


def test_default_files_use_the_platform_config_directory() -> None:
    expected_directory = Path(user_config_dir(appname=APP_NAME, appauthor=False))

    assert default_config_path() == expected_directory / "config.json"
    assert default_log_file_path() == expected_directory / "edm.log"
    assert expected_directory.is_absolute()


def test_background_notifier_matches_the_operating_system() -> None:
    expected_system = os.getenv("EDM_SMOKE_EXPECTED_SYSTEM")
    if expected_system is not None:
        assert platform.system() == expected_system

    notifier = create_background_notifier()

    if os.name == "nt":
        assert isinstance(notifier, PollingBackgroundNotifier)
    else:
        assert isinstance(notifier, PipeBackgroundNotifier)


def test_application_completes_basic_startup_and_shutdown(monkeypatch) -> None:
    container_data_source = SmokeTestContainerDataSource()
    monkeypatch.setattr(app_module.urwid, "MainLoop", SmokeTestMainLoop)
    app = app_module.EDMApp(
        app_config=AppConfig(),
        container_data_source=container_data_source,
    )

    app.run()

    assert isinstance(app.ui_event_loop, SmokeTestMainLoop)
    assert container_data_source.list_request_count == 1
    assert container_data_source.closed is True
