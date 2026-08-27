"""Refresh, sort, and maintain the running-container list."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core import AppConfig, ContainerSummary
from easy_docker_manager.core.container_sorting import (
    get_container_list_in_requested_order,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient

logger = logging.getLogger(__name__)


class RunningContainerListRefresher:
    """Keep the running-container list current and in the requested order.

    DockerManager asks this object to refresh the list when its timer is due or
    when EDM starts. It owns the refresh Future and applies the completed
    result on the UI thread. A successful refresh preserves the selected
    container, reapplies sorting, and removes state for stopped containers.
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
        self._containers_in_docker_order = list(state.running_containers)

    def refresh_if_due(self, current_time: float) -> None:
        """Start a container-list refresh when its scheduled time has arrived."""
        if current_time < self._next_refresh_at:
            return
        self.start_running_container_list_refresh()
        self._next_refresh_at = current_time + self.app_config.refresh_interval

    def get_next_refresh_time(self) -> Optional[float]:
        """Return the next refresh time, or None while a refresh is active."""
        if self._refresh_future is not None:
            return None
        return self._next_refresh_at

    def start_running_container_list_refresh(self, force: bool = False) -> bool:
        """Start loading the running-container list in a worker thread.

        DockerManager calls this during startup and scheduled refresh checks.
        force bypasses the timer but never starts a second overlapping request.
        True means a new request was submitted.
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

    def apply_container_sort_to_current_list(self) -> None:
        """Apply the selected sort while keeping the same container selected."""
        selected_container_id = self.state.selected_container_id
        self.state.running_containers = self._get_sorted_containers(
            self._containers_in_docker_order
        )
        self.state.selected_container_index = self.state.find_running_container_index(
            selected_container_id
        )
        if (
            self.state.selected_container_index is None
            and self.state.running_containers
        ):
            self.state.selected_container_index = 0

    def _apply_running_container_list_refresh_result(
        self,
        container_refresh_future: Future[list[ContainerSummary]],
    ) -> bool:
        """Apply the current refresh result and report whether the UI changed."""
        if container_refresh_future is not self._refresh_future:
            return False
        self._refresh_future = None

        try:
            running_containers = container_refresh_future.result()
        except Exception as exc:
            logger.warning("Container refresh failed: %s", exc)
            self.state.status_message = f"Container refresh failed: {exc}"
            return True
        return self._apply_refreshed_running_container_list(running_containers)

    def _apply_refreshed_running_container_list(
        self,
        running_containers: list[ContainerSummary],
    ) -> bool:
        """Store a successful refresh while preserving sorting and selection."""
        previously_selected_container_id = self.state.selected_container_id
        previous_displayed_containers = self.state.running_containers
        self._containers_in_docker_order = list(running_containers)
        displayed_containers = self._get_sorted_containers(running_containers)
        running_container_ids = {
            container.container_id for container in running_containers
        }
        self.state.remove_stopped_container_state(running_container_ids)
        self._remove_stopped_container_log_cursors(running_container_ids)

        if displayed_containers == previous_displayed_containers:
            if (
                not running_containers
                and self.state.status_message != "No running containers."
            ):
                self.state.status_message = "No running containers."
                return True
            if running_containers and self.state.status_message.startswith(
                "Container refresh failed:"
            ):
                self.state.status_message = (
                    f"{len(running_containers)} running containers"
                )
                return True
            return False

        self.state.running_containers = displayed_containers
        if not displayed_containers:
            self.state.selected_container_index = None
            self.state.status_message = "No running containers."
            return True

        self.state.selected_container_index = self.state.find_running_container_index(
            previously_selected_container_id
        )
        if self.state.selected_container_index is None:
            self.state.selected_container_index = 0

        self.state.status_message = (
            f"{len(self.state.running_containers)} running containers"
        )
        if (
            self.state.selected_container_id != previously_selected_container_id
            or previously_selected_container_id is None
        ):
            self._prepare_selected_container_details()
        return True

    def _get_sorted_containers(
        self,
        containers: list[ContainerSummary],
    ) -> list[ContainerSummary]:
        """Return containers in the sort order selected for this UI session."""
        return get_container_list_in_requested_order(
            containers,
            self.state.container_sort_field,
            self.state.container_sort_descending,
        )


__all__ = ["RunningContainerListRefresher"]
