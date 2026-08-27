"""Load and refresh content for the selected container tab."""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future
from functools import partial
from typing import Optional

from easy_docker_manager.app.background_executor import BackgroundExecutor
from easy_docker_manager.app.container_log_updates import ContainerLogUpdater
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    DockerContainerClientError,
    LogsUnavailableError,
)
from easy_docker_manager.tabs.tab_data_loader import TabDataLoader

logger = logging.getLogger(__name__)


class SelectedTabContentLoader:
    """Load text for the selected container's active detail tab.

    DockerManager calls this object after the selected container or tab
    changes. It owns the tab-load Future, reuses cached text, and periodically
    reloads Env, Config, and Top. A result is stored under the container and tab
    that requested it, even if the user changes selection while it is loading.
    """

    PERIODICALLY_REFRESHED_TABS = (TabName.ENV, TabName.CONFIG, TabName.TOP)

    def __init__(
        self,
        state: TerminalSessionState,
        app_config: AppConfig,
        background_executor: BackgroundExecutor,
        tab_data_loader: TabDataLoader,
        container_log_updater: ContainerLogUpdater,
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.background_executor = background_executor
        self.tab_data_loader = tab_data_loader
        self.container_log_updater = container_log_updater

        self._tab_load_future: Optional[Future[str]] = None
        self._next_tab_refresh_at = 0.0

    def refresh_if_due(self, current_time: float) -> None:
        """Reload the visible Env, Config, or Top tab when its timer is due."""
        if (
            self.state.active_detail_tab_name not in self.PERIODICALLY_REFRESHED_TABS
            or not self.state.selected_container_id
            or current_time < self._next_tab_refresh_at
            or self._tab_load_future is not None
        ):
            return
        self.load_selected_tab_content_if_needed(force=True)

    def get_next_refresh_time(self) -> Optional[float]:
        """Return the visible tab's next refresh time when it can be scheduled."""
        if (
            self.state.active_detail_tab_name not in self.PERIODICALLY_REFRESHED_TABS
            or not self.state.selected_container_id
            or self._tab_load_future is not None
        ):
            return None
        return self._next_tab_refresh_at

    def load_selected_tab_content_if_needed(self, force: bool = False) -> bool:
        """Load the selected tab unless suitable cached content can be reused.

        DockerManager calls this after selection changes and scheduled tab
        refreshes. If an older request is already running, it finishes first
        and its completion callback starts the load for the latest selection.
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

        self.state.tab_content_errors.pop(container_tab_key, None)
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
            self._next_tab_refresh_at = (
                time.monotonic() + self.app_config.tab_refresh_interval
            )
        return True

    def prepare_selected_container_details(self) -> None:
        """Reset detail navigation and load the newly selected container tab."""
        self.state.detail_selected_line_index = 0
        self.state.follow_log_tail = True
        selected_tab_key = self.state.selected_container_tab_key
        has_cached_content = (
            selected_tab_key is not None
            and selected_tab_key in self.state.tab_content_cache
        )
        if has_cached_content and selected_tab_key is not None:
            self.state.status_message = self.state.tab_content_errors.get(
                selected_tab_key,
                f"Loaded {self.state.active_detail_tab_name.value}",
            )
        self.load_selected_tab_content_if_needed(force=not has_cached_content)

    def prepare_active_detail_tab(self) -> None:
        """Reset detail navigation and load or reuse the newly active tab."""
        self.state.detail_selected_line_index = 0
        self.state.follow_log_tail = self.state.active_detail_tab_name == TabName.LOGS
        selected_tab_key = self.state.selected_container_tab_key
        if (
            selected_tab_key is not None
            and selected_tab_key in self.state.tab_content_cache
        ):
            self.state.status_message = self.state.tab_content_errors.get(
                selected_tab_key,
                f"Loaded {self.state.active_detail_tab_name.value}",
            )
        self.load_selected_tab_content_if_needed(force=False)

    def is_initial_log_content_load_in_progress(self, container_id: str) -> bool:
        """Return whether the first Logs request for this container is active."""
        logs_cache_key = ContainerTabKey(container_id, TabName.LOGS)
        return bool(
            logs_cache_key not in self.state.tab_content_cache
            and self._tab_load_future is not None
        )

    def _apply_tab_content_load_result(
        self,
        requested_tab_key: ContainerTabKey,
        initial_log_request_started_at: Optional[int],
        tab_load_future: Future[str],
    ) -> bool:
        """Store the current tab-load result and load a newer selection next."""
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
        """Store loaded content or its error under the tab that requested it."""
        is_active_tab = requested_tab_key == self.state.selected_container_tab_key

        try:
            content = tab_load_future.result()
        except LogsUnavailableError as exc:
            logger.info("Initial logs are unavailable: %s", exc)
            self.container_log_updater.record_container_logs_as_unavailable(
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

        self.state.tab_content_errors.pop(requested_tab_key, None)
        self.state.tab_content_cache[requested_tab_key] = content

        if not is_active_tab:
            return False
        if (
            requested_tab_key.tab_name == TabName.LOGS
            and initial_log_request_started_at is not None
        ):
            self.container_log_updater.record_initial_log_load_success(
                requested_tab_key.container_id,
                initial_log_request_started_at,
            )
        self.state.status_message = f"Loaded {self.state.active_detail_tab_name.value}"
        return True

    def _store_tab_load_error(
        self,
        container_tab_key: ContainerTabKey,
        message: str,
        *,
        update_status: bool,
    ) -> None:
        """Store a tab error and remove stale content from failed Logs loads.

        Env, Config, and Top keep their last successful snapshot after a
        refresh error. Logs are different: old lines could look current, so a
        failed Logs request clears them and displays the error instead.
        """
        if container_tab_key.tab_name == TabName.LOGS:
            self.container_log_updater.record_container_log_fetch_failure(
                container_tab_key.container_id,
                message,
                cache_key=container_tab_key,
                update_status=update_status,
            )
            return

        self.state.tab_content_errors[container_tab_key] = message
        if update_status:
            self.state.status_message = message


__all__ = ["SelectedTabContentLoader"]
