"""Refresh the container list and apply its display options."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.containers import ContainerListViewMode, ContainerSummary
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import DockerContainerClient

logger = logging.getLogger(__name__)


class ContainerListRefresher:
    """Refresh the container list and keep its selection valid.

    DockerManager calls this when EDM starts and whenever the refresh timer
    expires. This class tracks the current request and handles its result on the
    UI thread. After a successful refresh, it rebuilds the displayed list,
    keeps the same container selected when possible, and removes saved data for
    containers that no longer exist.
    """

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        docker_container_client: DockerContainerClient,
        prepare_selected_container_details: Callable[[bool], None],
        remove_non_running_container_log_cursors: Callable[[set[str]], None],
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.docker_container_client = docker_container_client
        self._prepare_selected_container_details = prepare_selected_container_details
        self._remove_non_running_container_log_cursors = (
            remove_non_running_container_log_cursors
        )

        self._refresh_future: Optional[Future[list[ContainerSummary]]] = None
        self._refresh_requested_after_current_request = False
        self._next_refresh_at = 0.0

    def refresh_if_needed(self, current_time: float) -> None:
        """Start a container-list refresh when the next refresh time is reached."""
        if current_time < self._next_refresh_at:
            return
        self.start_container_list_refresh()
        self._next_refresh_at = (
            current_time + self.app_config.container_list_refresh_interval_seconds
        )

    def get_next_refresh_time(self) -> Optional[float]:
        """Return the next refresh time, or None while a refresh is active."""
        if self._refresh_future is not None:
            return None
        return self._next_refresh_at

    def start_container_list_refresh(self, force: bool = False) -> bool:
        """Start loading the container list in a worker thread.

        DockerManager calls this during startup and scheduled refresh checks.
        force skips the timer check but never starts a second request while one
        is running. The method returns True only when it submits new work.
        """
        if self._refresh_future is not None:
            return False
        if not force and time.monotonic() < self._next_refresh_at:
            return False

        self._refresh_future = self.background_executor.submit(
            self.docker_container_client.list_containers,
            on_complete=self._apply_container_list_refresh_result,
        )
        return True

    def request_immediate_container_list_refresh(self) -> None:
        """Refresh now, or as soon as the current refresh finishes.

        Stop or Restart may finish while an older container-list request is
        still running. That older result may no longer be correct, so EDM
        discards it and asks Docker for the list again.
        """
        self._next_refresh_at = 0.0
        if self._refresh_future is not None:
            self._refresh_requested_after_current_request = True
            return
        self.start_container_list_refresh(force=True)

    def reset_after_docker_context_change(self) -> None:
        """Ignore an unfinished refresh and allow the new context to refresh now."""
        previous_refresh_future = self._refresh_future
        self._refresh_future = None
        self._refresh_requested_after_current_request = False
        self._next_refresh_at = 0.0
        if previous_refresh_future is not None:
            previous_refresh_future.cancel()

    def rebuild_displayed_container_list(self) -> None:
        """Rebuild the displayed list after its visibility, sort, or filter changes.

        TerminalController calls this after the user changes a list option.
        The same container stays selected if it is still displayed. Otherwise,
        EDM selects the first matching container.
        """
        previously_selected_container_id = self.state.selected_container_id
        displayed_containers = self.state.container_list.rebuild_displayed_containers(
            self.state.container_list_view_mode,
            self.state.container_sort_field,
            self.state.container_sort_descending,
            self.state.container_filter_query,
        )
        self.state.selected_container_index = self.state.find_container_index(
            previously_selected_container_id
        )
        if self.state.selected_container_index is None and displayed_containers:
            self.state.selected_container_index = 0
        if not displayed_containers:
            self.state.status_message = self._get_empty_container_list_message()
        else:
            self.state.status_message = self._get_container_count_message()
        if self.state.selected_container_id != previously_selected_container_id:
            self._prepare_selected_container_details(False)

    def _apply_container_list_refresh_result(
        self,
        container_refresh_future: Future[list[ContainerSummary]],
    ) -> bool:
        """Store the finished refresh and return True when the screen should redraw."""
        if container_refresh_future is not self._refresh_future:
            return False
        self._refresh_future = None

        if self._refresh_requested_after_current_request:
            self._refresh_requested_after_current_request = False
            self.start_container_list_refresh(force=True)
            return True

        try:
            containers = container_refresh_future.result()
        except Exception as exc:
            logger.warning("Container refresh failed: %s", exc)
            error_message = f"Container refresh failed: {exc}"
            self.state.container_list_refresh_error_message = error_message
            self.state.status_message = error_message
            return True
        return self._apply_refreshed_container_list(containers)

    def _apply_refreshed_container_list(
        self,
        containers: list[ContainerSummary],
    ) -> bool:
        """Store a refreshed list without losing its sort or selected container."""
        previously_selected_container_id = self.state.selected_container_id
        container_list = self.state.container_list
        previous_displayed_containers = list(container_list.displayed_containers)
        previous_container_count = container_list.all_container_count
        recovered_from_refresh_error = (
            self.state.container_list_refresh_error_message is not None
        )
        self.state.container_list_refresh_error_message = None
        status_changed_container_ids = container_list.replace_all_containers(containers)
        if status_changed_container_ids:
            # Every cached tab is a snapshot of one container state. For example,
            # after a stop, Logs needs its final lines and Config needs the exit data.
            # Tabs that were never opened have no saved result, so there is nothing
            # to remove for them.
            self.state.clear_loaded_details_for_containers(status_changed_container_ids)
        displayed_containers = container_list.rebuild_displayed_containers(
            self.state.container_list_view_mode,
            self.state.container_sort_field,
            self.state.container_sort_descending,
            self.state.container_filter_query,
        )
        self.state.remove_state_for_missing_containers(container_list.all_container_ids)
        self._remove_non_running_container_log_cursors(
            container_list.running_container_ids
        )

        displayed_list_changed = displayed_containers != previous_displayed_containers
        container_count_changed = len(containers) != previous_container_count
        if not displayed_list_changed:
            if not displayed_containers:
                empty_list_message = self._get_empty_container_list_message()
                status_changed = self.state.status_message != empty_list_message
                self.state.status_message = empty_list_message
                return (
                    status_changed
                    or container_count_changed
                    or recovered_from_refresh_error
                )
            if containers and recovered_from_refresh_error:
                self.state.status_message = self._get_container_count_message()
                return True
            return container_count_changed

        if not displayed_containers:
            self.state.selected_container_index = None
            self.state.status_message = self._get_empty_container_list_message()
            if previously_selected_container_id is not None:
                self._prepare_selected_container_details(False)
            return True

        self.state.selected_container_index = self.state.find_container_index(
            previously_selected_container_id
        )
        if self.state.selected_container_index is None:
            self.state.selected_container_index = 0

        self.state.status_message = self._get_container_count_message()
        selected_container_changed = (
            self.state.selected_container_id != previously_selected_container_id
            or previously_selected_container_id is None
        )
        selected_container_status_changed = (
            not selected_container_changed
            and self.state.selected_container_id in status_changed_container_ids
        )
        if selected_container_changed or selected_container_status_changed:
            self._prepare_selected_container_details(selected_container_status_changed)
        return True

    def _get_empty_container_list_message(self) -> str:
        """Return the empty-list message for the current view and filter."""
        container_list = self.state.container_list
        selected_view_count = container_list.get_container_count_for_view(
            self.state.container_list_view_mode
        )
        container_description = (
            "running containers"
            if self.state.container_list_view_mode == ContainerListViewMode.RUNNING_ONLY
            else "containers"
        )
        if self.state.container_filter_query and selected_view_count:
            return f"No {container_description} match the filter."
        return f"No {container_description}."

    def _get_container_count_message(self) -> str:
        """Return a short summary of the current Docker container list."""
        container_list = self.state.container_list
        if self.state.container_list_view_mode == ContainerListViewMode.RUNNING_ONLY:
            count = container_list.running_container_count
            return f"{count} running container{'s' if count != 1 else ''}"
        all_count = container_list.all_container_count
        running_count = container_list.running_container_count
        not_running_count = all_count - running_count
        return (
            f"{all_count} container{'s' if all_count != 1 else ''} "
            f"({running_count} running, {not_running_count} not running)"
        )


__all__ = ["ContainerListRefresher"]
