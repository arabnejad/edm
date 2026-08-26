"""Build and connect the objects used by EDMApp.

EDMApp uses this module during setup. The factory creates the shared session
state, Docker access, background processing, controllers, formatter, and
terminal view. EDMRuntime returns the objects that EDMApp uses directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.tab_content_cache import TabContentCache
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.docker.local_container_client import LocalDockerContainerClient
from easy_docker_manager.tabs.tab_data_loader import TabDataLoader
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.keyboard_controller import KeyboardController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView
from easy_docker_manager.ui.ui_controller import UIController


@dataclass
class EDMRuntime:
    """Hold the objects EDMApp uses while the terminal interface is running."""

    docker_container_client: DockerContainerClient
    background_executor: BackgroundExecutor
    terminal_layout_view: TerminalLayoutView
    docker_manager: DockerManager
    ui_controller: UIController
    keyboard_controller: KeyboardController


class EDMRuntimeFactory:
    """Create and connect the default objects used by EDMApp.

    The factory creates the Docker client, session state, Docker manager,
    background executor, controllers, formatter, and terminal view. It
    connects them and returns EDMApp's direct dependencies in EDMRuntime.
    EDMApp can then focus on starting and stopping the terminal UI.
    """

    def __init__(
        self,
        app_config: Optional[AppConfig] = None,
        docker_container_client: Optional[DockerContainerClient] = None,
    ) -> None:
        self.app_config = app_config if app_config is not None else AppConfig()
        if docker_container_client is not None:
            self.docker_container_client = docker_container_client
        else:
            self.docker_container_client = LocalDockerContainerClient(
                # This partial is equivalent to the lambda below:
                # lambda: create_docker_client(self.app_config.docker_request_timeout)
                create_client=partial(
                    create_docker_client,
                    self.app_config.docker_request_timeout,
                ),
            )

    def create_runtime(
        self,
        notify_background_task_ready: Callable[[], None],
    ) -> EDMRuntime:
        """Create and connect all objects used by one EDMApp instance."""
        state = UISessionState(
            tab_content_cache=TabContentCache(
                self.app_config.content_cache_size,
                self.app_config.content_cache_max_bytes,
            ),
        )
        tab_data_loader = TabDataLoader(self.docker_container_client, self.app_config)
        detail_tab_text_formatter = DetailTabTextFormatter()
        background_executor = BackgroundExecutor(
            max_workers=self.app_config.max_workers,
            notify_completion_ready=notify_background_task_ready,
        )
        terminal_layout_view = TerminalLayoutView(self.app_config)
        docker_manager = DockerManager(
            state,
            self.app_config,
            background_executor,
            tab_data_loader,
            self.docker_container_client,
        )
        ui_controller = UIController(
            state,
            terminal_layout_view,
            detail_tab_text_formatter,
            docker_manager,
        )
        keyboard_controller = KeyboardController(ui_controller)
        return EDMRuntime(
            docker_container_client=self.docker_container_client,
            background_executor=background_executor,
            terminal_layout_view=terminal_layout_view,
            docker_manager=docker_manager,
            ui_controller=ui_controller,
            keyboard_controller=keyboard_controller,
        )


__all__ = ["EDMRuntime", "EDMRuntimeFactory"]
