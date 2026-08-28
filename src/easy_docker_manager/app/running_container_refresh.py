"""Refresh the running-container list and apply its display options."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient

logger = logging.getLogger(__name__)


class RunningContainerListRefresher:
    """Refresh the running-container list and keep its selection valid.

    DockerManager calls this when EDM starts and whenever the refresh timer
    expires. This class tracks the current request and handles its result on the
    UI thread. After a successful refresh, it rebuilds the displayed list,
    keeps the same container selected when possible, and removes saved data for
    stopped containers.
    """

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        docker_container_client: DockerContainerClient,
        prepare_selected_container_details: Callable[[], None],
        remove_stopped_container_log_cursors: Callable[[set[str]], None],
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.docker_container_client = docker_container_client
        self._prepare_selected_container_details = prepare_selected_container_details
        self._remove_stopped_container_log_cursors = (
            remove_stopped_container_log_cursors
        )

        self._refresh_future: Optional[Future[list[ContainerSummary]]] = None
        self._next_refresh_at = 0.0

    def refresh_if_needed(self, current_time: float) -> None:
        """Start a container-list refresh when the next refresh time is reached."""
        if current_time < self._next_refresh_at:
            return
        self.start_running_container_list_refresh()
        self._next_refresh_at = (
            current_time + self.app_config.container_list_refresh_interval_seconds
        )

    def get_next_refresh_time(self) -> Optional[float]:
        """Return the next refresh time, or None while a refresh is active."""
        if self._refresh_future is not None:
            return None
        return self._next_refresh_at

    def start_running_container_list_refresh(self, force: bool = False) -> bool:
        """Start loading the running-container list in a worker thread.

        DockerManager calls this during startup and scheduled refresh checks.
        force skips the timer check but never starts a second request while one
        is running. The method returns True only when it submits new work.
        """
        if self._refresh_future is not None:
            return False
        if not force and time.monotonic() < self._next_refresh_at:
            return False

        self._refresh_future = self.background_executor.submit(
            self.docker_container_client.list_running_containers,
            on_complete=self._apply_running_container_list_refresh_result,
        )
        return True

    def rebuild_displayed_container_list(self) -> None:
        """Rebuild the displayed list after its sort or filter changes.

        TerminalController calls this after the user changes sorting or
        filtering. The same container stays selected if it is still in the
        displayed list. Otherwise, EDM selects the first matching container.
        """
        previously_selected_container_id = self.state.selected_container_id
        displayed_containers = (
            self.state.running_container_list.rebuild_displayed_containers(
                self.state.container_sort_field,
                self.state.container_sort_descending,
                self.state.container_filter_query,
            )
        )
        self.state.selected_container_index = self.state.find_running_container_index(
            previously_selected_container_id
        )
        if self.state.selected_container_index is None and displayed_containers:
            self.state.selected_container_index = 0
        if not displayed_containers:
            self.state.status_message = (
                "No running containers match the filter."
                if self.state.running_container_list.unfiltered_container_count
                else "No running containers."
            )
        if self.state.selected_container_id != previously_selected_container_id:
            self._prepare_selected_container_details()

    def _apply_running_container_list_refresh_result(
        self,
        container_refresh_future: Future[list[ContainerSummary]],
    ) -> bool:
        """Store the finished refresh and return True when the screen should redraw."""
        if container_refresh_future is not self._refresh_future:
            return False
        self._refresh_future = None

        try:
            running_containers = container_refresh_future.result()
        except Exception as exc:
            logger.warning("Container refresh failed: %s", exc)
            error_message = f"Container refresh failed: {exc}"
            self.state.container_list_refresh_error_message = error_message
            self.state.status_message = error_message
            return True
        return self._apply_refreshed_running_container_list(running_containers)

    def _apply_refreshed_running_container_list(
        self,
        running_containers: list[ContainerSummary],
    ) -> bool:
        """Store a refreshed list without losing its sort or selected container."""
        previously_selected_container_id = self.state.selected_container_id
        container_list = self.state.running_container_list
        previous_displayed_containers = list(container_list.displayed_containers)
        previous_running_container_count = container_list.unfiltered_container_count
        recovered_from_refresh_error = (
            self.state.container_list_refresh_error_message is not None
        )
        self.state.container_list_refresh_error_message = None
        container_list.replace_all_running_containers(running_containers)
        displayed_containers = container_list.rebuild_displayed_containers(
            self.state.container_sort_field,
            self.state.container_sort_descending,
            self.state.container_filter_query,
        )
        running_container_ids = container_list.all_running_container_ids
        self.state.remove_state_for_stopped_containers(running_container_ids)
        self._remove_stopped_container_log_cursors(running_container_ids)

        displayed_list_changed = displayed_containers != previous_displayed_containers
        running_container_count_changed = (
            len(running_containers) != previous_running_container_count
        )
        if not displayed_list_changed:
            if not displayed_containers:
                empty_list_message = (
                    "No running containers match the filter."
                    if running_containers
                    else "No running containers."
                )
                status_changed = self.state.status_message != empty_list_message
                self.state.status_message = empty_list_message
                return (
                    status_changed
                    or running_container_count_changed
                    or recovered_from_refresh_error
                )
            if running_containers and recovered_from_refresh_error:
                self.state.status_message = (
                    f"{len(running_containers)} running containers"
                )
                return True
            return running_container_count_changed

        if not displayed_containers:
            self.state.selected_container_index = None
            self.state.status_message = (
                "No running containers match the filter."
                if running_containers
                else "No running containers."
            )
            if previously_selected_container_id is not None:
                self._prepare_selected_container_details()
            return True

        self.state.selected_container_index = self.state.find_running_container_index(
            previously_selected_container_id
        )
        if self.state.selected_container_index is None:
            self.state.selected_container_index = 0

        self.state.status_message = f"{len(running_containers)} running containers"
        if (
            self.state.selected_container_id != previously_selected_container_id
            or previously_selected_container_id is None
        ):
            self._prepare_selected_container_details()
        return True


__all__ = ["RunningContainerListRefresher"]
