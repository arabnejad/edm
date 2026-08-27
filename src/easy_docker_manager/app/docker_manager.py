"""Give the terminal code one place to request Docker data.

EDMApp and TerminalController use DockerManager instead of calling the separate
refresh classes themselves. DockerManager forwards container-list refreshes,
tab loads, and log polls to the class responsible for each request.
"""

from __future__ import annotations

import time

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.container_log_updates import ContainerLogUpdater
from easy_docker_manager.app.running_container_refresh import (
    RunningContainerListRefresher,
)
from easy_docker_manager.app.selected_tab_load import SelectedTabContentLoader
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.tabs.tab_data_loader import ContainerTabTextLoader


class DockerManager:
    """Route Docker data requests to the three request handlers.

    EDMApp asks when Docker data should be refreshed. TerminalController uses
    the same object after the user changes a container, tab, or sort order.
    RunningContainerListRefresher handles the container list,
    SelectedTabContentLoader handles full tab loads, and ContainerLogUpdater
    handles later log polls.
    """

    MINIMUM_REQUEST_CHECK_DELAY = 0.05
    IDLE_REQUEST_CHECK_DELAY = 1.0

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        tab_data_loader: ContainerTabTextLoader,
        docker_container_client: DockerContainerClient,
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.tab_data_loader = tab_data_loader
        self.docker_container_client = docker_container_client

        self.container_log_updater = ContainerLogUpdater(
            state,
            app_config,
            background_executor,
            docker_container_client,
        )
        self.selected_tab_content_loader = SelectedTabContentLoader(
            state,
            app_config,
            background_executor,
            tab_data_loader,
            self.container_log_updater,
        )
        self.running_container_list_refresher = RunningContainerListRefresher(
            state,
            app_config,
            background_executor,
            docker_container_client,
            self.prepare_selected_container_details,
            self.container_log_updater.remove_log_cursors_for_stopped_containers,
        )

    def refresh_docker_data_if_needed(self) -> None:
        """Start scheduled container, tab, and log requests when needed.

        EDMApp calls this after startup, user input, finished worker tasks, and
        each timed refresh check. Each handler skips work when the same type of
        request is already running.
        """
        current_time = time.monotonic()
        self.running_container_list_refresher.refresh_if_needed(current_time)
        self.selected_tab_content_loader.refresh_if_needed(current_time)

        initial_log_load_in_progress = self._is_initial_log_content_load_in_progress()
        self.container_log_updater.poll_if_needed(
            current_time,
            initial_log_load_in_progress=initial_log_load_in_progress,
        )

    def get_next_docker_data_refresh_delay(self) -> float:
        """Return how long EDM should wait before checking Docker work again."""
        initial_log_load_in_progress = self._is_initial_log_content_load_in_progress()
        request_times = [
            request_time
            for request_time in (
                self.running_container_list_refresher.get_next_refresh_time(),
                self.selected_tab_content_loader.get_next_refresh_time(),
                self.container_log_updater.get_next_poll_time(
                    initial_log_load_in_progress=initial_log_load_in_progress
                ),
            )
            if request_time is not None
        ]
        if not request_times:
            return self.IDLE_REQUEST_CHECK_DELAY
        return max(
            self.MINIMUM_REQUEST_CHECK_DELAY,
            min(request_times) - time.monotonic(),
        )

    def start_running_container_list_refresh(self, force: bool = False) -> bool:
        """Ask the list refresher to load the running containers."""
        return (
            self.running_container_list_refresher.start_running_container_list_refresh(
                force
            )
        )

    def load_selected_tab_content_if_needed(self, force: bool = False) -> bool:
        """Ask the tab loader to load or reuse the selected container tab."""
        return self.selected_tab_content_loader.load_selected_tab_content_if_needed(
            force
        )

    def prepare_selected_container_details(self) -> None:
        """Prepare tab content after the user selects another container."""
        self.container_log_updater.reset_after_selection_change()
        self.selected_tab_content_loader.prepare_selected_container_details()

    def prepare_active_detail_tab(self) -> None:
        """Prepare tab content after the user switches detail tabs."""
        self.container_log_updater.reset_after_selection_change()
        self.selected_tab_content_loader.prepare_active_detail_tab()

    def apply_container_sort_to_current_list(self) -> None:
        """Reorder the current container list using the selected sort."""
        self.running_container_list_refresher.apply_container_sort_to_current_list()

    def _is_initial_log_content_load_in_progress(self) -> bool:
        """Return True while the selected container's first log load is running."""
        container_id = self.state.selected_container_id
        if not container_id:
            return False
        return self.selected_tab_content_loader.is_initial_log_content_load_in_progress(
            container_id
        )


__all__ = ["DockerManager"]
