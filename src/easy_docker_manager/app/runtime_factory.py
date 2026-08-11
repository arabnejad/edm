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

from easy_docker_manager.app.background_task_result_handler import (
    BackgroundTaskResultHandler,
)
from easy_docker_manager.app.background_task_runner import BackgroundTaskRunner
from easy_docker_manager.app.scheduler import BackgroundTaskScheduler
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.content_cache import LRUTabContentCache
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.docker.base import ContainerDataSource
from easy_docker_manager.docker.client_factory import create_docker_client
from easy_docker_manager.docker.local import LocalContainerDataSource
from easy_docker_manager.tabs.tab_data_loader import TabDataLoader
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.keyboard_controller import KeyboardController
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView
from easy_docker_manager.ui.ui_controller import UIController


@dataclass
class EDMRuntime:
    """Hold the objects EDMApp uses while the terminal interface is running."""

    container_data_source: ContainerDataSource
    task_runner: BackgroundTaskRunner
    terminal_layout_view: TerminalLayoutView
    scheduler: BackgroundTaskScheduler
    ui_controller: UIController
    keyboard_controller: KeyboardController
    background_task_result_handler: BackgroundTaskResultHandler


class EDMRuntimeFactory:
    """Create and connect the default objects used by EDMApp.

    The factory creates the Docker data source, session state, background task
    objects, controllers, formatter, and terminal view. It connects them and
    returns EDMApp's direct dependencies in EDMRuntime. EDMApp can then focus
    on running and stopping the terminal UI.
    """

    def __init__(
        self,
        app_config: Optional[AppConfig] = None,
        container_data_source: Optional[ContainerDataSource] = None,
    ) -> None:
        self.app_config = app_config if app_config is not None else AppConfig()
        if container_data_source is not None:
            self.container_data_source = container_data_source
        else:
            self.container_data_source = LocalContainerDataSource(
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
            tab_content_cache=LRUTabContentCache(
                self.app_config.content_cache_size,
                self.app_config.content_cache_max_bytes,
            ),
        )
        tab_data_loader = TabDataLoader(self.container_data_source, self.app_config)
        detail_tab_text_formatter = DetailTabTextFormatter()
        task_runner = BackgroundTaskRunner(
            max_workers=self.app_config.max_workers,
            notify_task_ready=notify_background_task_ready,
        )
        terminal_layout_view = TerminalLayoutView(self.app_config)
        scheduler = BackgroundTaskScheduler(
            state,
            self.app_config,
            task_runner,
            tab_data_loader,
            self.container_data_source,
        )
        ui_controller = UIController(
            state,
            terminal_layout_view,
            detail_tab_text_formatter,
            scheduler,
        )
        keyboard_controller = KeyboardController(ui_controller)
        background_task_result_handler = BackgroundTaskResultHandler(
            state,
            self.app_config,
            scheduler,
            ui_controller,
        )
        return EDMRuntime(
            container_data_source=self.container_data_source,
            task_runner=task_runner,
            terminal_layout_view=terminal_layout_view,
            scheduler=scheduler,
            ui_controller=ui_controller,
            keyboard_controller=keyboard_controller,
            background_task_result_handler=background_task_result_handler,
        )


__all__ = ["EDMRuntime", "EDMRuntimeFactory"]
