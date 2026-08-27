"""Poll for new container logs and update cached log text."""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future
from functools import partial
from typing import Optional, Union

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.log_text import (
    apply_limits_to_log_content,
    count_repeated_lines_between_batches,
)
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    DockerContainerClient,
    LogsUnavailableError,
)
from easy_docker_manager.tabs.tab_data_loader import (
    build_logs_unavailable_error_message,
)

logger = logging.getLogger(__name__)


class ContainerLogUpdater:
    """Fetch new log lines and merge them into each container's Logs cache.

    DockerManager asks this object to poll when the selected Logs tab is due.
    It owns the poll Future, poll timer, and Docker since timestamps. Completed
    polls update the matching container cache even when the user has selected
    another container before the request finishes.
    """

    LOG_POLL_INTERVAL = 1.0

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        docker_container_client: DockerContainerClient,
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.docker_container_client = docker_container_client

        self._log_poll_future: Optional[Future[str]] = None
        self._next_log_poll_at = 0.0
        self._log_cursor_by_container_id: dict[str, int] = {}

    def poll_if_due(
        self,
        current_time: float,
        *,
        initial_log_load_in_progress: bool,
    ) -> None:
        """Start a log poll when the visible Logs tab is ready for one."""
        container_id = self.state.selected_container_id
        if (
            self.state.active_detail_tab_name != TabName.LOGS
            or not container_id
            or container_id in self.state.unreadable_log_container_ids
            or current_time < self._next_log_poll_at
            or self._log_poll_future is not None
            or initial_log_load_in_progress
        ):
            return

        self._request_log_poll(container_id)
        self._next_log_poll_at = current_time + self.LOG_POLL_INTERVAL

    def get_next_poll_time(
        self,
        *,
        initial_log_load_in_progress: bool,
    ) -> Optional[float]:
        """Return the next useful poll time, or None when polling should wait."""
        container_id = self.state.selected_container_id
        if (
            self.state.active_detail_tab_name != TabName.LOGS
            or not container_id
            or container_id in self.state.unreadable_log_container_ids
            or self._log_poll_future is not None
            or initial_log_load_in_progress
        ):
            return None
        return self._next_log_poll_at

    def reset_after_selection_change(self) -> None:
        """Cancel queued log work and make the new selection immediately due."""
        if self._log_poll_future is not None:
            if not self._log_poll_future.done():
                if self._log_poll_future.cancel():
                    self._log_poll_future = None
            else:
                self._log_poll_future = None
        self._next_log_poll_at = 0.0

    def record_initial_log_load_success(
        self,
        container_id: str,
        request_started_at: int,
    ) -> None:
        """Use the initial request time as the starting point for later polls."""
        self._log_cursor_by_container_id[container_id] = request_started_at
        self._next_log_poll_at = 0.0

    def record_container_logs_as_unavailable(
        self,
        container_id: str,
        error: LogsUnavailableError,
        cache_key: Optional[ContainerTabKey] = None,
        *,
        update_status: bool,
    ) -> None:
        """Show why logs cannot be read and stop polling this container."""
        self.state.unreadable_log_container_ids.add(container_id)
        logs_cache_key = cache_key or ContainerTabKey(container_id, TabName.LOGS)
        self.record_container_log_fetch_failure(
            container_id,
            build_logs_unavailable_error_message(error),
            cache_key=logs_cache_key,
            update_status=False,
        )
        if update_status:
            self.state.status_message = "Logs unavailable for selected container."

    def record_container_log_fetch_failure(
        self,
        container_id: str,
        message: str,
        cache_key: Optional[ContainerTabKey] = None,
        *,
        update_status: bool,
    ) -> None:
        """Remove stale logs and store the error from a failed log request.

        Initial log loads and later log polls both call this after Docker fails
        to return logs. Removing the previous cache prevents old lines from
        looking current while the error is active.
        """
        logs_cache_key = cache_key or ContainerTabKey(container_id, TabName.LOGS)
        self.state.tab_content_cache.remove_cached_tab_content(logs_cache_key)
        self.state.tab_content_errors[logs_cache_key] = message
        if update_status:
            self.state.status_message = message

    def remove_log_cursors_for_stopped_containers(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Forget Docker since timestamps belonging to stopped containers."""
        self._log_cursor_by_container_id = {
            container_id: since_timestamp
            for container_id, since_timestamp in (
                self._log_cursor_by_container_id.items()
            )
            if container_id in running_container_ids
        }

    def apply_configured_limits_to_log_content(self, content: str) -> str:
        """Apply EDM's line-count and line-length limits before caching logs."""
        return apply_limits_to_log_content(
            content,
            max_lines=self.app_config.max_log_lines,
            max_line_chars=self.app_config.max_log_line_chars,
        )

    def _request_log_poll(self, container_id: str) -> None:
        """Submit the next incremental log request for one container."""
        since_timestamp = self._log_cursor_by_container_id.get(container_id)
        tail_lines: Union[int, str] = (
            self.app_config.log_tail if since_timestamp is None else "all"
        )
        replace_existing = since_timestamp is None
        request_started_at = int(time.time())

        self._log_poll_future = self.background_executor.submit(
            self._fetch_log_poll_content,
            container_id,
            tail_lines,
            since_timestamp,
            on_complete=partial(
                self._apply_log_poll_result,
                container_id,
                replace_existing,
                request_started_at,
            ),
        )

    def _apply_log_poll_result(
        self,
        container_id: str,
        replace_existing: bool,
        request_started_at: int,
        log_poll_future: Future[str],
    ) -> bool:
        """Merge the current poll result and report whether the UI changed."""
        if log_poll_future is not self._log_poll_future:
            return False
        self._log_poll_future = None

        is_logs_tab_visible = (
            container_id == self.state.selected_container_id
            and self.state.active_detail_tab_name == TabName.LOGS
        )
        try:
            content = log_poll_future.result()
        except LogsUnavailableError as exc:
            logger.info("Logs are unavailable: %s", exc)
            self.record_container_logs_as_unavailable(
                container_id,
                exc,
                update_status=is_logs_tab_visible,
            )
            return is_logs_tab_visible
        except Exception as exc:
            logger.warning("Log fetch failed: %s", exc)
            error_message = f"Log fetch failed: {exc}"
            self.record_container_log_fetch_failure(
                container_id,
                error_message,
                update_status=is_logs_tab_visible,
            )
            return is_logs_tab_visible

        should_redraw = self._apply_log_content_to_cache(
            container_id,
            content,
            replace_existing=replace_existing,
        )
        self._log_cursor_by_container_id[container_id] = request_started_at

        logs_cache_key = ContainerTabKey(container_id, TabName.LOGS)
        recovered_from_failure = (
            self.state.tab_content_errors.pop(logs_cache_key, None) is not None
        )
        if recovered_from_failure and is_logs_tab_visible:
            self.state.status_message = "Loaded Logs"
        return should_redraw or (is_logs_tab_visible and recovered_from_failure)

    def _apply_log_content_to_cache(
        self,
        container_id: str,
        content: str,
        *,
        replace_existing: bool,
    ) -> bool:
        """Replace or extend one container's cached Logs content."""
        cache_key = ContainerTabKey(container_id, TabName.LOGS)
        cache_already_exists = cache_key in self.state.tab_content_cache
        if not content and not replace_existing and cache_already_exists:
            return False

        existing_content = self.state.tab_content_cache.get(cache_key, "") or ""
        updated_content = (
            content
            if replace_existing
            else self._combine_existing_and_new_log_content(existing_content, content)
        )
        if updated_content == existing_content and cache_already_exists:
            return False

        self.state.tab_content_cache[cache_key] = (
            self.apply_configured_limits_to_log_content(updated_content)
        )
        return (
            container_id == self.state.selected_container_id
            and self.state.active_detail_tab_name == TabName.LOGS
        )

    def _fetch_log_poll_content(
        self,
        container_id: str,
        tail_lines: Union[int, str],
        since_timestamp: Optional[int],
    ) -> str:
        """Fetch and limit one log-poll response in a worker thread."""
        content = self.docker_container_client.get_container_logs(
            container_id,
            tail_lines,
            since_timestamp,
        )
        return self.apply_configured_limits_to_log_content(content)

    @staticmethod
    def _combine_existing_and_new_log_content(
        existing_content: str,
        new_content: str,
    ) -> str:
        """Combine two log batches without repeating their shared edge lines."""
        if not existing_content:
            return new_content
        new_lines = new_content.splitlines()
        if not new_lines:
            return existing_content

        existing_lines = existing_content.splitlines()
        repeated_line_count = count_repeated_lines_between_batches(
            existing_lines,
            new_lines,
        )
        lines_to_append = new_lines[repeated_line_count:]
        if not lines_to_append:
            return existing_content
        return "\n".join([*existing_lines, *lines_to_append])


__all__ = ["ContainerLogUpdater"]
