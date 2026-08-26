"""Load container data in the background and apply finished results.

DockerManager owns the complete workflow for container refreshes,
detail-tab loads, and incremental log updates. It decides when a request is
needed, submits it to BackgroundExecutor, and applies its result later on the
UI thread.

Keeping both halves of each request here makes the flow easier to follow. The
method that starts a request names its completion method directly, so there is
no task enum or separate result dispatcher between them.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future
from functools import partial
from typing import Optional, Union

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.core import AppConfig, ContainerSummary
from easy_docker_manager.core.container_sorting import (
    get_container_list_in_requested_order,
)
from easy_docker_manager.core.log_text import (
    apply_limits_to_log_content,
    count_repeated_lines_between_batches,
)
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    DockerContainerClient,
    DockerContainerClientError,
    LogsUnavailableError,
)
from easy_docker_manager.tabs.tab_data_loader import (
    TabDataLoader,
    build_logs_unavailable_error_message,
)

logger = logging.getLogger(__name__)


class DockerManager:
    """Manage Docker data used by the terminal interface.

    EDMApp calls refresh_docker_data_if_needed() after user input, completed
    background work, and scheduled timer checks. UIController calls the
    selection-change methods after the user chooses another container or tab.
    DockerManager starts each required background operation, tracks it until
    it finishes, and saves the result in UISessionState. It also remembers when
    container refreshes, tab reloads, and log polls should run next.

    Completion methods run on the UI thread. They update UISessionState and
    return True when the visible screen needs to be redrawn.
    """

    LOG_POLL_INTERVAL = 1.0
    PERIODICALLY_REFRESHED_TABS = (TabName.ENV, TabName.CONFIG, TabName.TOP)
    MINIMUM_REQUEST_CHECK_DELAY = 0.05
    IDLE_REQUEST_CHECK_DELAY = 1.0

    def __init__(
        self,
        state: UISessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        tab_data_loader: TabDataLoader,
        docker_container_client: DockerContainerClient,
    ) -> None:
        """Save the shared objects and make the first timed requests due."""
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.tab_data_loader = tab_data_loader
        self.docker_container_client = docker_container_client

        # A saved Future means that request is already running or waiting for
        # its completion callback to be handled on the UI thread.
        self._container_refresh_future: Optional[Future[list[ContainerSummary]]] = None
        self._tab_load_future: Optional[Future[str]] = None
        self._log_poll_future: Optional[Future[str]] = None

        # Docker's since argument is a Unix timestamp. Each successful log
        # request saves its start time here for the next request.
        self._log_cursor_by_container_id: dict[str, int] = {}

        # Zero makes startup work immediately due. Monotonic time is used for
        # intervals so a system-clock adjustment cannot disturb the schedule.
        self._next_container_refresh_at = 0.0
        self._next_visible_tab_refresh_at = 0.0
        self._next_log_poll_at = 0.0

        # Keep Docker's original order separately so the sorting menu can
        # restore it after another sort has been applied.
        self._containers_in_docker_order = list(state.running_containers)

    def refresh_docker_data_if_needed(self) -> None:
        """Start background Docker updates that are currently needed.

        EDMApp calls this after startup, user input, completed work, and each
        scheduled timer check. The method checks the container refresh, visible
        tab refresh, and log poll schedules. It returns without contacting
        Docker when no update is needed. Active-request checks prevent the same
        operation from being started twice.
        """
        now = time.monotonic()

        if now >= self._next_container_refresh_at:
            self.start_running_container_list_refresh()
            self._next_container_refresh_at = now + self.app_config.refresh_interval

        if (
            self.state.active_detail_tab_name in self.PERIODICALLY_REFRESHED_TABS
            and self.state.selected_container_id
            and now >= self._next_visible_tab_refresh_at
            and self._tab_load_future is None
        ):
            self.load_selected_tab_content_if_needed(force=True)

        container_id = self.state.selected_container_id
        if (
            self.state.active_detail_tab_name == TabName.LOGS
            and container_id
            and container_id not in self.state.unreadable_log_container_ids
            and now >= self._next_log_poll_at
            and self._log_poll_future is None
            and not self._is_initial_log_content_load_in_progress(container_id)
        ):
            self._request_log_poll(container_id)
            self._next_log_poll_at = now + self.LOG_POLL_INTERVAL

    def get_next_docker_data_refresh_delay(self) -> float:
        """Return the delay before EDMApp checks for Docker updates again.

        EDMApp uses this value to set the timer that will next call
        refresh_docker_data_if_needed(). Running work is left out because its
        completion notification will wake EDMApp. A short minimum delay
        prevents a tight loop when an update is already overdue.
        """
        now = time.monotonic()
        request_times = []

        if self._container_refresh_future is None:
            request_times.append(self._next_container_refresh_at)

        if (
            self.state.active_detail_tab_name in self.PERIODICALLY_REFRESHED_TABS
            and self.state.selected_container_id
            and self._tab_load_future is None
        ):
            request_times.append(self._next_visible_tab_refresh_at)

        container_id = self.state.selected_container_id
        if (
            self.state.active_detail_tab_name == TabName.LOGS
            and container_id
            and container_id not in self.state.unreadable_log_container_ids
            and self._log_poll_future is None
            and not self._is_initial_log_content_load_in_progress(container_id)
        ):
            request_times.append(self._next_log_poll_at)

        if not request_times:
            return self.IDLE_REQUEST_CHECK_DELAY
        return max(self.MINIMUM_REQUEST_CHECK_DELAY, min(request_times) - now)

    def start_running_container_list_refresh(self, force: bool = False) -> bool:
        """Start loading a fresh list of running containers in the background.

        This refreshes the list shown by EDM; it does not start or restart any
        Docker container. EDMApp uses force=True during startup. A forced
        refresh ignores the normal timer but still cannot overlap a refresh
        already in progress. True means a new background operation was started.
        """
        if self._container_refresh_future is not None:
            return False
        if not force and time.monotonic() < self._next_container_refresh_at:
            return False

        self._container_refresh_future = self.background_executor.submit(
            self.docker_container_client.list_running_containers,
            on_complete=self._apply_running_container_list_refresh_result,
        )
        return True

    def load_selected_tab_content_if_needed(self, force: bool = False) -> bool:
        """Load content for the selected container and tab when needed.

        DockerManager calls this after the user selects another container or
        tab. Cached content is reused by default. Timed Env, Config, and Top
        refreshes use force=True to load fresh content instead.

        If another tab load is already running, this method lets it finish.
        Its completion callback then loads the container and tab that are
        selected at that time.

        True means a load started or must wait for the active load to finish.
        """
        container_tab_key = self.state.selected_container_tab_key
        if container_tab_key is None:
            return False
        if not force and container_tab_key in self.state.tab_content_cache:
            return False

        self.state.status_message = f"Loading {container_tab_key.tab_name.value}..."

        if (
            self._tab_load_future is not None
            and not self._tab_load_future.done()
            and not self._tab_load_future.cancel()
        ):
            return True
        if self._tab_load_future is not None:
            self._tab_load_future = None

        self.state.tab_load_errors.pop(container_tab_key, None)
        initial_log_request_started_at = (
            int(time.time()) if container_tab_key.tab_name == TabName.LOGS else None
        )
        self._tab_load_future = self.background_executor.submit(
            self.tab_data_loader.load_tab_text,
            container_tab_key.container_id,
            container_tab_key.tab_name,
            on_complete=partial(
                self._apply_tab_content_load_result,
                container_tab_key,
                initial_log_request_started_at,
            ),
        )

        if container_tab_key.tab_name in self.PERIODICALLY_REFRESHED_TABS:
            self._next_visible_tab_refresh_at = (
                time.monotonic() + self.app_config.tab_refresh_interval
            )
        return True

    def prepare_selected_container_details(self) -> None:
        """Prepare the detail area after the selected container changes.

        UIController calls this after keyboard navigation changes the selected
        container. DockerManager also calls it when a container-list refresh
        selects a different container. It resets detail navigation and log
        polling, shows cached tab content when available, and starts a
        background load when content is missing.
        """
        self._reset_log_polling_after_selection_change()
        self.state.detail_selected_line_index = 0
        self.state.follow_log_tail = True
        selected_tab_key = self.state.selected_container_tab_key
        has_cached_content = (
            selected_tab_key is not None
            and selected_tab_key in self.state.tab_content_cache
        )
        if has_cached_content:
            self.state.status_message = (
                f"Loaded {self.state.active_detail_tab_name.value}"
            )
        self.load_selected_tab_content_if_needed(force=not has_cached_content)

    def prepare_active_detail_tab(self) -> None:
        """Prepare the detail area after the active tab changes.

        UIController calls this after changing active_detail_tab_name. The
        method resets detail navigation and log polling, enables log-tail
        following only for Logs, shows cached content immediately, and loads
        missing content in the background.
        """
        self._reset_log_polling_after_selection_change()
        self.state.detail_selected_line_index = 0
        self.state.follow_log_tail = self.state.active_detail_tab_name == TabName.LOGS
        selected_tab_key = self.state.selected_container_tab_key
        if (
            selected_tab_key is not None
            and selected_tab_key in self.state.tab_content_cache
        ):
            self.state.status_message = (
                f"Loaded {self.state.active_detail_tab_name.value}"
            )
        self.load_selected_tab_content_if_needed(force=False)

    def apply_container_sort_to_current_list(self) -> None:
        """Reorder the current list while keeping the same container selected.

        UIController calls this after the user confirms the sorting menu. The
        original Docker order remains available for a later Docker order choice.
        """
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

    def _reset_log_polling_after_selection_change(self) -> None:
        """Reset log polling after the selected container or tab changes.

        A queued poll is cancelled when possible, and the next poll time is set
        to zero so Logs can update immediately for the new selection. A Docker
        request already running cannot be cancelled. It finishes normally, but
        its saved container ID keeps its result with the original container.
        """
        if self._log_poll_future is not None:
            if not self._log_poll_future.done():
                if self._log_poll_future.cancel():
                    self._log_poll_future = None
            else:
                self._log_poll_future = None
        self._next_log_poll_at = 0.0

    def _request_log_poll(self, container_id: str) -> None:
        """Request the next available log lines for one container."""
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

    def _apply_running_container_list_refresh_result(
        self,
        container_refresh_future: Future[list[ContainerSummary]],
    ) -> bool:
        """Apply a finished running-container list refresh to session state.

        BackgroundExecutor calls this on the UI thread. A successful result
        updates the displayed container list. A failure keeps the existing
        list and shows an error. A stale result is ignored when a newer refresh
        has replaced it. The return value tells EDMApp whether to redraw.
        """
        if container_refresh_future is not self._container_refresh_future:
            return False
        self._container_refresh_future = None

        try:
            running_containers = container_refresh_future.result()
        except Exception as exc:
            logger.warning("Container refresh failed: %s", exc)
            self.state.status_message = f"Container refresh failed: {exc}"
            return True
        return self._apply_refreshed_running_container_list(running_containers)

    def _apply_tab_content_load_result(
        self,
        requested_tab_key: ContainerTabKey,
        initial_log_request_started_at: Optional[int],
        tab_load_future: Future[str],
    ) -> bool:
        """Apply a finished tab-content load to session state.

        BackgroundExecutor calls this on the UI thread with the container and
        tab that started the load. A stale Future is ignored. Otherwise, the
        result or error is stored under the original tab key. If the user moved
        to another container or tab while loading, content for that current
        selection is loaded next. The return value tells EDMApp whether to
        redraw.
        """
        if tab_load_future is not self._tab_load_future:
            return False
        self._tab_load_future = None

        selection_changed_while_loading = (
            requested_tab_key != self.state.selected_container_tab_key
        )
        should_redraw = self._store_tab_load_result(
            tab_load_future,
            requested_tab_key,
            initial_log_request_started_at,
        )
        if selection_changed_while_loading:
            should_redraw = (
                self.load_selected_tab_content_if_needed(force=False) or should_redraw
            )
        return should_redraw

    def _store_tab_load_result(
        self,
        tab_load_future: Future[str],
        requested_tab_key: ContainerTabKey,
        initial_log_request_started_at: Optional[int],
    ) -> bool:
        """Store loaded tab content or its error in the current UI state.

        The result is stored under requested_tab_key even if the user selected
        another container or tab while it was loading. Successful Logs content
        is limited before caching. When the requested tab is still visible,
        this method also updates its status and prepares incremental log
        polling. The return value tells the caller whether the screen changed.
        """
        is_active_tab = requested_tab_key == self.state.selected_container_tab_key

        try:
            content = tab_load_future.result()
        except LogsUnavailableError as exc:
            logger.info("Initial logs are unavailable: %s", exc)
            self._record_container_logs_as_unavailable(
                requested_tab_key.container_id,
                exc,
                requested_tab_key,
                update_status=is_active_tab,
            )
            return is_active_tab
        except ContainerLogFetchError as exc:
            logger.warning("Initial log load failed: %s", exc)
            self._store_tab_load_error(
                requested_tab_key,
                f"Log fetch failed: {exc}",
                update_status=is_active_tab,
            )
            return is_active_tab
        except DockerContainerClientError as exc:
            logger.warning("%s load failed: %s", requested_tab_key.tab_name.value, exc)
            self._store_tab_load_error(
                requested_tab_key,
                f"Error loading {requested_tab_key.tab_name.value}: {exc}",
                update_status=is_active_tab,
            )
            return is_active_tab
        except Exception as exc:
            logger.warning(
                "Detail load failed for %s: %s",
                requested_tab_key.tab_name.value,
                exc,
            )
            self._store_tab_load_error(
                requested_tab_key,
                f"Error loading {requested_tab_key.tab_name.value}: {exc}",
                update_status=is_active_tab,
            )
            return is_active_tab

        self.state.tab_load_errors.pop(requested_tab_key, None)
        if requested_tab_key.tab_name == TabName.LOGS:
            content = self._apply_configured_limits_to_log_content(content)
        self.state.tab_content_cache[requested_tab_key] = content

        if not is_active_tab:
            return False
        if (
            requested_tab_key.tab_name == TabName.LOGS
            and initial_log_request_started_at is not None
        ):
            self._log_cursor_by_container_id[requested_tab_key.container_id] = (
                initial_log_request_started_at
            )
            self._next_log_poll_at = 0.0
        self.state.status_message = f"Loaded {self.state.active_detail_tab_name.value}"
        return True

    def _apply_log_poll_result(
        self,
        container_id: str,
        replace_existing: bool,
        request_started_at: int,
        log_poll_future: Future[str],
    ) -> bool:
        """Merge a successful log response or show its temporary error."""
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
            self._record_container_logs_as_unavailable(
                container_id,
                exc,
                update_status=is_logs_tab_visible,
            )
            return is_logs_tab_visible
        except Exception as exc:
            logger.warning("Log fetch failed: %s", exc)
            if is_logs_tab_visible:
                self.state.status_message = f"Log fetch failed: {exc}"
            return is_logs_tab_visible

        should_redraw = self._apply_log_content_to_cache(
            container_id,
            content,
            replace_existing=replace_existing,
        )
        self._log_cursor_by_container_id[container_id] = request_started_at

        recovered_from_failure = (
            is_logs_tab_visible
            and self.state.status_message.startswith("Log fetch failed:")
        )
        if recovered_from_failure:
            self.state.status_message = "Loaded Logs"
        return should_redraw or recovered_from_failure

    def _apply_refreshed_running_container_list(
        self,
        running_containers: list[ContainerSummary],
    ) -> bool:
        """Apply the latest Docker container list to the UI session.

        This runs after a container-list refresh succeeds. It reapplies the
        selected sorting option, removes cached data for stopped containers,
        and keeps the same container selected when possible. It also updates
        the status message and prepares the selected container's details when
        the selection changes. The return value tells EDMApp whether to redraw.
        """
        previously_selected_container_id = self.state.selected_container_id
        previous_displayed_containers = self.state.running_containers
        self._containers_in_docker_order = list(running_containers)
        displayed_containers = self._get_sorted_containers(running_containers)
        running_container_ids = {
            container.container_id for container in running_containers
        }
        self.state.remove_stopped_container_state(running_container_ids)
        self._remove_log_cursors_for_stopped_containers(running_container_ids)

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
            self.prepare_selected_container_details()
        return True

    def _apply_log_content_to_cache(
        self,
        container_id: str,
        content: str,
        *,
        replace_existing: bool,
    ) -> bool:
        """Store new log content in one container's Logs cache.

        A first log response replaces the cache. Later responses are merged
        with the existing text so lines repeated by Docker are not duplicated.
        The configured display limits are applied before the text is stored.
        The return value is true when the visible Logs tab needs to be redrawn.
        """
        if not content and not replace_existing:
            return False

        cache_key = ContainerTabKey(container_id, TabName.LOGS)
        existing_content = self.state.tab_content_cache.get(cache_key, "") or ""
        updated_content = (
            content
            if replace_existing
            else self._combine_existing_and_new_log_content(existing_content, content)
        )
        if updated_content == existing_content:
            return False

        self.state.tab_content_cache[cache_key] = (
            self._apply_configured_limits_to_log_content(updated_content)
        )
        return (
            container_id == self.state.selected_container_id
            and self.state.active_detail_tab_name == TabName.LOGS
        )

    def _record_container_logs_as_unavailable(
        self,
        container_id: str,
        error: LogsUnavailableError,
        cache_key: Optional[ContainerTabKey] = None,
        *,
        update_status: bool,
    ) -> None:
        """Record that Docker cannot provide logs for one container.

        Initial log loading and later log polling both call this after Docker
        reports that the container's logging driver cannot be read. The method
        stops future polling, caches an explanation for the Logs tab, clears
        any temporary load error, and updates the status when requested.
        """
        self.state.unreadable_log_container_ids.add(container_id)
        logs_cache_key = cache_key or ContainerTabKey(container_id, TabName.LOGS)
        self.state.tab_content_cache[logs_cache_key] = (
            build_logs_unavailable_error_message(error)
        )
        self.state.tab_load_errors.pop(logs_cache_key, None)
        if update_status:
            self.state.status_message = "Logs unavailable for selected container."

    def _store_tab_load_error(
        self,
        container_tab_key: ContainerTabKey,
        message: str,
        *,
        update_status: bool,
    ) -> None:
        """Store a tab-load error without replacing its cached content.

        This is called when loading Logs, Env, Config, or Top fails. The error
        is saved for the requested container and tab. When that tab is still
        visible, the same message is also shown in the status area.
        """
        self.state.tab_load_errors[container_tab_key] = message
        if update_status:
            self.state.status_message = message

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

    def _remove_log_cursors_for_stopped_containers(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Remove saved log cursors for containers that are no longer running.

        This runs after the container list is refreshed. Each cursor stores the
        timestamp that the next log request passes to Docker's since argument.
        A stopped container no longer needs that timestamp, so its entry is removed.
        """
        self._log_cursor_by_container_id = {
            container_id: since_timestamp
            for container_id, since_timestamp in (
                self._log_cursor_by_container_id.items()
            )
            if container_id in running_container_ids
        }

    def _fetch_log_poll_content(
        self,
        container_id: str,
        tail_lines: Union[int, str],
        since_timestamp: Optional[int],
    ) -> str:
        """Fetch one log-poll response and apply the display limits.

        BackgroundExecutor runs this away from the UI thread after
        _request_log_poll starts a request. The returned text is later passed
        to _apply_log_poll_result on the UI thread.
        """
        content = self.docker_container_client.get_container_logs(
            container_id,
            tail_lines,
            since_timestamp,
        )
        return self._apply_configured_limits_to_log_content(content)

    def _is_initial_log_content_load_in_progress(self, container_id: str) -> bool:
        """Return whether the first Logs content request is still running.

        DockerManager checks this before starting a log poll and while deciding
        when to check for more Docker data. No cached Logs content together
        with an active tab request means the initial load has not finished yet.
        Waiting prevents an incremental poll from overlapping that first load.
        """
        logs_cache_key = ContainerTabKey(container_id, TabName.LOGS)
        return bool(
            logs_cache_key not in self.state.tab_content_cache
            and self._tab_load_future is not None
        )

    @staticmethod
    def _combine_existing_and_new_log_content(
        existing_content: str, new_content: str
    ) -> str:
        """Combine cached and newly fetched log content without repeating overlap.

        Incremental Docker requests can repeat lines from the end of the
        previous response. This method removes only the lines shared by the end
        of existing_content and the start of new_content. Duplicate lines in
        other positions are kept because they may be valid log entries.
        """
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

    def _apply_configured_limits_to_log_content(self, content: str) -> str:
        """Apply the configured line count and line length limits to logs.

        Initial log loading and incremental polling call this before storing
        content in the cache. Keeping only the configured number of recent
        lines and limiting each line's length keeps rendering and memory use
        predictable.
        """
        return apply_limits_to_log_content(
            content,
            max_lines=self.app_config.max_log_lines,
            max_line_chars=self.app_config.max_log_line_chars,
        )


__all__ = ["DockerManager"]
