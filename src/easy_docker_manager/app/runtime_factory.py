"""Create the objects needed to run one EDMApp.

The factory creates the shared session state, Docker client, worker pool,
controllers, and terminal views. It connects them once during startup and
returns the objects used directly by EDMApp.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.config.app_config_store import AppConfigStore
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.tab_content_cache import TabContentCache
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.diagnostics import get_installed_edm_version
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.docker.local_container_client import LocalDockerContainerClient
from easy_docker_manager.tab_export.writer import TabExportWriter
from easy_docker_manager.tabs.tab_data_loader import ContainerTabTextLoader
from easy_docker_manager.tabs.tab_text_filter import TabTextFilter
from easy_docker_manager.ui.container_action_controller import ContainerActionController
from easy_docker_manager.ui.diagnostics_controller import DiagnosticsController
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.keyboard_controller import KeyboardController
from easy_docker_manager.ui.settings_controller import SettingsController
from easy_docker_manager.ui.tab_export_controller import TabExportController
from easy_docker_manager.ui.terminal_controller import TerminalController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView


@dataclass
class EDMRuntime:
    """Group the objects that EDMApp uses directly while it is running."""

    docker_container_client: DockerContainerClient
    background_executor: BackgroundExecutor
    terminal_layout_view: TerminalLayoutView
    docker_manager: DockerManager
    terminal_controller: TerminalController
    keyboard_controller: KeyboardController


class EDMRuntimeFactory:
    """Create and connect one complete set of EDM runtime objects.

    EDMApp uses this factory during startup. Keeping object creation here keeps
    EDMApp focused on running the interface and also lets tests provide a
    different config or Docker client.
    """

    def __init__(
        self,
        app_config: Optional[AppConfig] = None,
        docker_container_client: Optional[DockerContainerClient] = None,
        app_config_store: Optional[AppConfigStore] = None,
    ) -> None:
        self.app_config = app_config if app_config is not None else AppConfig()
        if docker_container_client is not None:
            self.docker_container_client = docker_container_client
        else:
            self.docker_container_client = LocalDockerContainerClient(
                # This partial is equivalent to the lambda below:
                # lambda: create_docker_client(self.app_config.docker_request_timeout)
                create_docker_client=partial(
                    create_docker_client,
                    self.app_config.docker_request_timeout,
                ),
            )
        self.launch_directory = Path.cwd().resolve()
        self.app_config_store = (
            app_config_store if app_config_store is not None else AppConfigStore()
        )

    def create_runtime(
        self,
        notify_background_task_ready: Callable[[], None],
    ) -> EDMRuntime:
        """Create and connect all objects used by one EDMApp instance."""
        state = TerminalSessionState(
            tab_content_cache=TabContentCache(
                self.app_config.tab_content_cache_max_entries,
                self.app_config.tab_content_cache_max_bytes,
            ),
        )
        tab_data_loader = ContainerTabTextLoader(
            self.docker_container_client, self.app_config
        )
        tab_text_filter = TabTextFilter()
        detail_tab_text_formatter = DetailTabTextFormatter()
        background_executor = BackgroundExecutor(
            max_background_worker_threads=(
                self.app_config.max_background_worker_threads
            ),
            notify_ui_completion_ready=notify_background_task_ready,
        )
        terminal_layout_view = TerminalLayoutView(
            self.app_config,
            installed_edm_version=get_installed_edm_version(),
        )
        docker_manager = DockerManager(
            state,
            self.app_config,
            background_executor,
            tab_data_loader,
            self.docker_container_client,
        )
        terminal_controller = TerminalController(
            state,
            terminal_layout_view,
            tab_text_filter,
            detail_tab_text_formatter,
            docker_manager,
        )
        tab_export_controller = TabExportController(
            state,
            tab_text_filter,
            background_executor,
            TabExportWriter(),
            self.launch_directory,
        )
        diagnostics_controller = DiagnosticsController(
            state,
            background_executor,
            self.docker_container_client,
        )
        settings_controller = SettingsController(state, self.app_config_store)
        container_action_controller = ContainerActionController(state, docker_manager)
        keyboard_controller = KeyboardController(
            terminal_controller,
            tab_export_controller,
            diagnostics_controller,
            settings_controller,
            container_action_controller,
        )
        return EDMRuntime(
            docker_container_client=self.docker_container_client,
            background_executor=background_executor,
            terminal_layout_view=terminal_layout_view,
            docker_manager=docker_manager,
            terminal_controller=terminal_controller,
            keyboard_controller=keyboard_controller,
        )


__all__ = ["EDMRuntime", "EDMRuntimeFactory"]
