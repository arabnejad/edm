"""Coordinate the Docker data workflows used by the terminal interface.

DockerManager remains the object used by EDMApp and TerminalController. It
delegates container-list refreshes, selected-tab loads, and log updates to
small components that own those request lifecycles. This keeps the public UI
workflow unchanged while placing each Future beside its completion method.
"""

from __future__ import annotations

import time

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.container_log_updates import ContainerLogUpdater
from easy_docker_manager.app.running_container_refresh import (
    RunningContainerListRefresher,
)
from easy_docker_manager.app.selected_tab_load import SelectedTabContentLoader
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient
from easy_docker_manager.tabs.tab_data_loader import TabDataLoader


class DockerManager:
    """Provide one entry point for all Docker data used by the terminal UI.

    EDMApp asks this class to start due Docker work and calculate the next
    refresh delay. TerminalController reports container, tab, and sorting
    changes through the same public methods as before. DockerManager delegates
    each operation to the component that owns its request and result handling.
    """

    MINIMUM_REQUEST_CHECK_DELAY = 0.05
    IDLE_REQUEST_CHECK_DELAY = 1.0

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        tab_data_loader: TabDataLoader,
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
        """Ask each Docker data component to start work that is now due.

        EDMApp calls this after startup, user input, completed work, and each
        scheduled timer check. Every component prevents duplicate requests for
        the work it already has in progress.
        """
        current_time = time.monotonic()
        self.running_container_list_refresher.refresh_if_due(current_time)
        self.selected_tab_content_loader.refresh_if_due(current_time)

        initial_log_load_in_progress = self._is_initial_log_content_load_in_progress()
        self.container_log_updater.poll_if_due(
            current_time,
            initial_log_load_in_progress=initial_log_load_in_progress,
        )

    def get_next_docker_data_refresh_delay(self) -> float:
        """Return how long EDMApp should wait before checking Docker work again."""
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
        """Start a running-container list refresh through its owning component."""
        return (
            self.running_container_list_refresher.start_running_container_list_refresh(
                force
            )
        )

    def load_selected_tab_content_if_needed(self, force: bool = False) -> bool:
        """Load or reuse the selected tab through its owning component."""
        return self.selected_tab_content_loader.load_selected_tab_content_if_needed(
            force
        )

    def prepare_selected_container_details(self) -> None:
        """Reset log polling and prepare details after container selection changes."""
        self.container_log_updater.reset_after_selection_change()
        self.selected_tab_content_loader.prepare_selected_container_details()

    def prepare_active_detail_tab(self) -> None:
        """Reset log polling and prepare details after the active tab changes."""
        self.container_log_updater.reset_after_selection_change()
        self.selected_tab_content_loader.prepare_active_detail_tab()

    def apply_container_sort_to_current_list(self) -> None:
        """Apply the selected container order through the list refresher."""
        self.running_container_list_refresher.apply_container_sort_to_current_list()

    def _is_initial_log_content_load_in_progress(self) -> bool:
        """Return whether log polling must wait for the first Logs response."""
        container_id = self.state.selected_container_id
        if not container_id:
            return False
        return self.selected_tab_content_loader.is_initial_log_content_load_in_progress(
            container_id
        )


__all__ = ["DockerManager"]
