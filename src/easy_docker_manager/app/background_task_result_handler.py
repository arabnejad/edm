"""Apply finished worker tasks to UI state.

Workers fetch Docker data, but they do not change UI state. EDMApp calls
BackgroundTaskResultHandler on the UI thread after the runner reports finished
work. The handler updates caches, status messages, and selection state there.

The workflow from task completion to a possible redraw is:

1. EDMApp takes CompletedTask objects from the runner's queue.
2. The scheduler rejects tasks that were cancelled or replaced.
3. The handler applies each current task according to its TaskKind:

   - REFRESH updates the running-container list. If the refresh fails, the old
     list stays visible and only the status message changes.
   - FETCH_TAB_CONTENT stores Logs, Env, Config, or Top text for the container
     and tab that started the request. If the user selected something else
     while the task was running, the newly selected tab is loaded next.
   - FETCH_LOG_UPDATES adds new lines to the correct container's Logs cache.
     After a successful request, it saves the request time so the next poll
     asks Docker only for newer logs. A failed request does not change that
     time, so the next attempt does not skip logs.

4. The handler reads the Future, which contains either the worker's result or
   the error raised while the worker was running.
5. The handler returns True when EDMApp needs to redraw the screen.

This module never makes Docker requests. It only handles their results.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Optional

from easy_docker_manager.app.background_task_runner import (
    CompletedTask,
    DetailTaskContext,
    LogTaskContext,
    TaskKind,
)
from easy_docker_manager.app.scheduler import BackgroundTaskScheduler
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.content_cache import ContainerTabKey
from easy_docker_manager.core.log_text import count_line_overlap, trim_log_text
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.docker.base import (
    ContainerLogFetchError,
    ContainerRefreshError,
    DockerDataSourceError,
    LogsUnavailableError,
)
from easy_docker_manager.tabs.tab_data_loader import format_logs_unavailable_message
from easy_docker_manager.ui.ui_controller import UIController

logger = logging.getLogger(__name__)


class BackgroundTaskResultHandler:
    """Update UI state after a background task finishes.

    EDMApp calls this class on the UI thread. It ignores results from tasks that
    the scheduler has replaced, stores tab text, adds log updates, reports
    errors, and keeps the selected log line in the correct position.
    """

    def __init__(
        self,
        state: UISessionState,
        app_config: AppConfig,
        scheduler: BackgroundTaskScheduler,
        ui_controller: UIController,
    ) -> None:
        self.state = state
        self.app_config = app_config
        self.scheduler = scheduler
        self.ui_controller = ui_controller

    def handle_completed_task(self, completed_task: CompletedTask) -> bool:
        """Apply one finished worker task.

        EDMApp calls this for every item returned by pop_all_completed_tasks().
        The method uses the task kind to choose the correct result handler. It
        returns True when the result changed something visible on the screen.
        """
        # Ignore a task if a newer Future has replaced it.
        if not self.scheduler.claim_completed_task(completed_task):
            return False

        # A refresh needs no extra task context. Its Future returns the new
        # container list or raises the error from the background task.
        if completed_task.kind == TaskKind.REFRESH:
            return self.handle_container_refresh_completion(completed_task.future)

        # Use the saved tab key because selection may have changed during the load.
        if completed_task.kind == TaskKind.FETCH_TAB_CONTENT and isinstance(
            completed_task.task_context, DetailTaskContext
        ):
            selection_changed_during_load = (
                completed_task.task_context.container_tab_key
                != self.state.selected_container_tab_key
            )
            should_redraw = self.handle_tab_content_completion(
                completed_task.future,
                completed_task.task_context,
            )

            # A running Docker request cannot be cancelled. Load the current
            # selection now if the completed task belongs to an older selection.
            if selection_changed_during_load:
                should_redraw = (
                    self.scheduler.schedule_selected_tab_load(force=False)
                    or should_redraw
                )
            return should_redraw

        # The log context identifies the container, says whether to replace or
        # append its cached logs, and provides the time for the next log request.
        if completed_task.kind == TaskKind.FETCH_LOG_UPDATES and isinstance(
            completed_task.task_context, LogTaskContext
        ):
            return self.handle_log_poll_completion(
                completed_task.future,
                completed_task.task_context,
            )

        # A task kind with the wrong context is an internal scheduling error.
        logger.error(
            "Completed %s task has invalid task context",
            completed_task.kind.value,
        )
        return False

    def handle_container_refresh_completion(
        self,
        container_refresh_future: Future,
    ) -> bool:
        """Apply a container refresh, keeping the current list after an error."""
        try:
            running_containers = container_refresh_future.result()
        except ContainerRefreshError as exc:
            logger.warning("Container refresh failed: %s", exc)
            self.state.status_message = f"Container refresh failed: {exc}"
            return True
        except Exception as exc:
            logger.warning("Container refresh failed: %s", exc)
            self.state.status_message = f"Container refresh failed: {exc}"
            return True
        return self.ui_controller.update_running_containers(running_containers)

    def handle_tab_content_completion(
        self,
        tab_content_future: Future,
        task_context: DetailTaskContext,
    ) -> bool:
        """Store text or an error for a completed tab load.

        handle_completed_task() calls this for FETCH_TAB_CONTENT. The key saved
        when the request started identifies the cache entry that receives the
        result, even if the user has since changed selection. The method returns
        True only when the visible tab changed.
        """
        # Use the key saved when the task started. The user may now be viewing a
        # different container or tab, but this result belongs to the old selection.
        container_tab_key = task_context.container_tab_key
        is_active_tab = container_tab_key == self.state.selected_container_tab_key

        # Read the worker result here so errors are handled on the UI thread.
        try:
            content = tab_content_future.result()

        # An unreadable logging driver will fail every time, so stop polling it.
        except LogsUnavailableError as exc:
            logger.info("Initial logs are unavailable: %s", exc)
            self._mark_logs_unavailable(
                container_tab_key.container_id,
                exc,
                container_tab_key,
                update_status=is_active_tab,
            )
            return is_active_tab

        # Do not replace cached content with a temporary error. A later request
        # can retry while the previous Logs content remains available.
        except ContainerLogFetchError as exc:
            logger.warning("Initial log load failed: %s", exc)
            self._record_tab_load_error(
                container_tab_key,
                f"Log fetch failed: {exc}",
                is_active_tab,
            )
            return is_active_tab

        # Save expected Docker errors for the tab that made the request.
        except DockerDataSourceError as exc:
            logger.warning("%s load failed: %s", container_tab_key.tab_name.value, exc)
            self._record_tab_load_error(
                container_tab_key,
                f"Error loading {container_tab_key.tab_name.value}: {exc}",
                is_active_tab,
            )
            return is_active_tab

        # Show unexpected failures in the UI and keep them in the application log.
        except Exception as exc:
            logger.warning(
                "Detail load failed for %s: %s",
                container_tab_key.tab_name.value,
                exc,
            )
            self._record_tab_load_error(
                container_tab_key,
                f"Error loading {container_tab_key.tab_name.value}: {exc}",
                is_active_tab,
            )
            return is_active_tab

        # A successful retry clears the old error for this tab.
        self.state.tab_load_errors.pop(container_tab_key, None)

        # Trim logs before caching them to limit rendering work and memory use.
        if container_tab_key.tab_name == TabName.LOGS:
            content = self._apply_log_display_limits(content)

        # Store the result even if the user has moved to another tab. It will be
        # ready immediately if the user returns to this container and tab.
        self.state.tab_content_cache[container_tab_key] = content

        # A hidden tab can update its cache without redrawing the screen.
        if container_tab_key == self.state.selected_container_tab_key:

            # The first Logs result starts polling. Keep focus on the newest line
            # while log-tail following is enabled.
            if container_tab_key.tab_name == TabName.LOGS:
                if task_context.initial_log_request_started_at is not None:
                    self.scheduler.record_initial_log_load_success(
                        container_tab_key.container_id,
                        task_context.initial_log_request_started_at,
                    )
                if self.state.follow_log_tail:
                    self.ui_controller.select_last_detail_line()
            self.state.status_message = (
                f"Loaded {self.state.active_detail_tab_name.value}"
            )
            return True
        return False

    def handle_log_poll_completion(
        self,
        log_future: Future,
        task_context: LogTaskContext,
    ) -> bool:
        """Apply one completed log update to the Logs cache.

        The saved container ID identifies the Logs cache to update, and the
        replace flag says whether to replace or append its text. After a
        successful request, the scheduler saves its start time for Docker's
        next since value. A failed request keeps the previous time so a retry
        cannot skip logs. The method returns True when EDMApp should redraw.
        """
        # Use the saved container id because selection may have changed.
        container_id = task_context.container_id

        # Hidden containers still update their cache, but do not need a redraw.
        is_logs_tab_visible = (
            container_id == self.state.selected_container_id
            and self.state.active_detail_tab_name == TabName.LOGS
        )

        # Read the worker result here so errors are handled on the UI thread.
        try:
            content = log_future.result()

        # An unreadable logging driver will keep failing, so stop polling it.
        except LogsUnavailableError as exc:
            logger.info("Logs are unavailable: %s", exc)
            self._mark_logs_unavailable(
                container_id,
                exc,
                update_status=is_logs_tab_visible,
            )
            return is_logs_tab_visible

        # Keep the previous log timestamp after a temporary error so a retry
        # cannot skip lines.
        except ContainerLogFetchError as exc:
            logger.warning("Log fetch failed: %s", exc)
            if is_logs_tab_visible:
                self.state.status_message = f"Log fetch failed: {exc}"
            return is_logs_tab_visible

        # Other Docker errors also keep the previous log timestamp.
        except DockerDataSourceError as exc:
            logger.warning("Log fetch failed: %s", exc)
            if is_logs_tab_visible:
                self.state.status_message = f"Log fetch failed: {exc}"
            return is_logs_tab_visible

        # Unexpected errors are logged and also keep the previous log timestamp.
        except Exception as exc:
            logger.warning("Log fetch failed: %s", exc)
            if is_logs_tab_visible:
                self.state.status_message = f"Log fetch failed: {exc}"
            return is_logs_tab_visible

        # The first update may replace the cache. Later updates append new lines.
        should_redraw = self._update_cached_logs(
            container_id,
            content,
            replace_existing=task_context.replace_existing,
        )

        # Save the request start time only after its result was stored successfully.
        self.scheduler.record_log_poll_success(
            container_id,
            task_context.request_started_at,
        )

        # Clear an old failure message even if the successful update was empty.
        recovered_from_failure = (
            is_logs_tab_visible
            and self.state.status_message.startswith("Log fetch failed:")
        )
        if recovered_from_failure:
            self.state.status_message = "Loaded Logs"
        return should_redraw or recovered_from_failure

    def _update_cached_logs(
        self,
        container_id: Optional[str],
        content: str,
        replace_existing: bool = False,
    ) -> bool:
        """Merge new text into one container's Logs cache.

        handle_log_poll_completion() calls this after a successful Docker
        request. It can replace the cache or append non-duplicate lines, then
        applies the display limits. True means the visible Logs tab changed.
        """
        # An empty incremental response adds nothing. An empty replacement is
        # meaningful because it clears text left by the previous full load.
        if not container_id or (not content and not replace_existing):
            return False

        # Store the update under the container that started the request.
        cache_key = ContainerTabKey(
            container_id=container_id,
            tab_name=TabName.LOGS,
        )

        # Read the actual cached value so an empty replacement can still be
        # recognized as a change when old text is present.
        existing = self.state.tab_content_cache.get(cache_key, "") or ""

        # A replacement starts fresh; a normal update keeps existing history.
        updated = (
            content if replace_existing else self._merge_log_updates(existing, content)
        )

        # Docker may repeat lines around the saved since timestamp. Remove the
        # exact overlap before adding the incoming lines.
        if updated == existing:
            return False

        # Apply display limits before saving the updated text.
        self.state.tab_content_cache[cache_key] = self._apply_log_display_limits(
            updated
        )

        # Keep focus on the newest line while the visible Logs tab follows its tail.
        if (
            container_id == self.state.selected_container_id
            and self.state.active_detail_tab_name == TabName.LOGS
            and self.state.follow_log_tail
        ):
            self.ui_controller.select_last_detail_line()
            return True

        # Redraw only when this container's Logs tab is visible.
        return (
            container_id == self.state.selected_container_id
            and self.state.active_detail_tab_name == TabName.LOGS
        )

    def _mark_logs_unavailable(
        self,
        container_id: Optional[str],
        exc: LogsUnavailableError,
        cache_key: Optional[ContainerTabKey] = None,
        *,
        update_status: bool = True,
    ) -> None:
        """Stop polling unreadable logs and cache the message shown to the user."""
        if container_id is not None:
            self.state.unreadable_log_container_ids.add(container_id)
            key = (
                cache_key
                if cache_key is not None
                else ContainerTabKey(
                    container_id=container_id,
                    tab_name=TabName.LOGS,
                )
            )
            self.state.tab_content_cache[key] = format_logs_unavailable_message(exc)
            self.state.tab_load_errors.pop(key, None)
        if update_status:
            self.state.status_message = "Logs unavailable for selected container."

    def _record_tab_load_error(
        self,
        container_tab_key: ContainerTabKey,
        message: str,
        update_status: bool,
    ) -> None:
        """Save a tab error without replacing its cached content."""
        self.state.tab_load_errors[container_tab_key] = message
        if update_status:
            self.state.status_message = message

    @staticmethod
    def _merge_log_updates(existing: str, incoming: str) -> str:
        """Append only incoming lines that are not already at the cache end."""
        if not existing:
            return incoming

        existing_lines = existing.splitlines()
        incoming_lines = incoming.splitlines()
        if not incoming_lines:
            return existing

        overlap = count_line_overlap(existing_lines, incoming_lines)
        new_lines = incoming_lines[overlap:]
        if not new_lines:
            return existing
        return "\n".join([*existing_lines, *new_lines])

    def _apply_log_display_limits(self, content: str) -> str:
        """Trim log text to the configured line and character limits."""
        return trim_log_text(
            content,
            max_lines=self.app_config.max_log_lines,
            max_line_chars=self.app_config.max_log_line_chars,
        )


__all__ = ["BackgroundTaskResultHandler"]
