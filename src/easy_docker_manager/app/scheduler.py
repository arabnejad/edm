"""Schedule container refreshes, tab loads, and log updates.

BackgroundTaskScheduler checks when container refreshes, visible tab reloads,
and log updates are due. It sends slow work to BackgroundTaskRunner and keeps
one current Future for each task type so it does not start duplicate requests.
BackgroundTaskResultHandler processes the results after the work finishes.

The scheduling workflow is:

1. EDMApp calls schedule_next_tasks() after startup, user input, completed
   background work, and scheduled timer checks.
2. A container refresh starts when it is due. Env, Config, and Top reload only
   while visible. A log poll starts only while a readable Logs tab is visible.
3. UIController asks for a tab load after container or tab selection changes.
4. The scheduler keeps one current Future for each kind of work.
5. The result handler calls claim_completed_task() and ignores replaced work.
6. After a successful log request, the scheduler saves when that request
   started. The next request passes this time to Docker so it asks only for
   logs from that point onward. A failed request keeps the previous time so a
   retry cannot skip logs.
7. EDMApp asks how long it should wait and sets an Urwid timer for the next
   check.
"""

from __future__ import annotations

import time
from concurrent.futures import Future
from typing import Optional, Union

from easy_docker_manager.app.background_task_runner import (
    BackgroundTaskRunner,
    CompletedTask,
    DetailTaskContext,
    LogTaskContext,
    TaskKind,
)
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.content_cache import ContainerTabKey
from easy_docker_manager.core.log_text import trim_log_text
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.docker.base import ContainerDataSource
from easy_docker_manager.tabs.tab_data_loader import TabDataLoader


class BackgroundTaskScheduler:
    """Start background work when it is due and prevent duplicate requests.

    EDMApp uses it for timed container refreshes, visible tab reloads, and log
    updates. UIController asks it to load the selected tab after navigation.
    BackgroundTaskResultHandler tells it when work has finished and when the
    saved time for the next log request can be updated.
    """

    LOG_POLL_INTERVAL = 1.0
    PERIODICALLY_REFRESHED_TABS = (TabName.ENV, TabName.CONFIG, TabName.TOP)
    MIN_SCHEDULER_DELAY = 0.05
    IDLE_SCHEDULER_DELAY = 1.0

    def __init__(
        self,
        state: UISessionState,
        app_config: AppConfig,
        task_runner: BackgroundTaskRunner,
        tab_data_loader: TabDataLoader,
        container_data_source: ContainerDataSource,
    ) -> None:
        """Save the required objects and make the first scheduled work due.

        EDMRuntimeFactory calls this once while building EDMApp. The deadlines
        start at zero so the first scheduling pass can run immediately.
        """
        self.state = state
        self.app_config = app_config
        self.task_runner = task_runner
        self.tab_data_loader = tab_data_loader
        self.container_data_source = container_data_source

        # Keep the current Future for each task type. A stored Future shows that
        # work is already running, so the scheduler does not start a duplicate.
        # It also lets the result handler reject results from older requests.
        self._container_refresh_future: Optional[Future] = None
        self._tab_load_future: Optional[Future] = None
        self._log_poll_future: Optional[Future] = None

        # Save the start time of each container's last successful log request.
        # When the user returns to that container, Docker receives this time as
        # its since value and returns logs from that point onward.
        self._log_cursor_by_container_id: dict[str, int] = {}

        # Zero allows immediate startup work. Later deadlines use monotonic time
        # so system clock changes do not affect the schedule.
        self._next_container_refresh_at = 0.0
        self._next_visible_tab_refresh_at = 0.0
        self._next_log_poll_at = 0.0

    def schedule_next_tasks(self) -> None:
        """Start any container refresh, tab reload, or log poll that is due.

        EDMApp calls this after startup, user input, completed background work,
        and scheduled timer checks. It does not start work that is already
        running. Log polling starts only after the first Logs content has been
        loaded and stored.
        """
        now = time.monotonic()

        # Refresh on the configured interval. schedule_container_refresh prevents
        # two refresh requests from running at the same time.
        if now >= self._next_container_refresh_at:
            self.schedule_container_refresh()
            self._next_container_refresh_at = now + self.app_config.refresh_interval

        # Env, Config, and Top use full reloads. Only reload the visible tab,
        # and wait for an existing tab request to finish before starting another.
        if (
            self.state.active_detail_tab_name in self.PERIODICALLY_REFRESHED_TABS
            and self.state.selected_container_id
            and now >= self._next_visible_tab_refresh_at
            and self._tab_load_future is None
        ):
            self.schedule_selected_tab_load(force=True)

        # Poll only a readable, visible Logs tab after its first load is complete.
        container_id = self.state.selected_container_id
        if (
            self.state.active_detail_tab_name == TabName.LOGS
            and container_id
            and container_id not in self.state.unreadable_log_container_ids
            and now >= self._next_log_poll_at
            and self._log_poll_future is None
            and not self._initial_log_snapshot_pending(container_id)
        ):
            self.schedule_log_poll()
            self._next_log_poll_at = now + self.LOG_POLL_INTERVAL

    def seconds_until_next_task_check(self) -> float:
        """Return how many seconds EDMApp should wait before checking again.

        EDMApp uses this delay to set its next timer. Running tasks are not
        included because their completion notification will wake the app. The
        minimum delay prevents repeated checks with no pause when work is overdue.
        """
        now = time.monotonic()
        deadlines = []

        # A running refresh will wake EDMApp when it finishes.
        if self._container_refresh_future is None:
            deadlines.append(self._next_container_refresh_at)

        # A running tab load will wake EDMApp when it finishes. Otherwise, add
        # the reload time only for the visible Env, Config, or Top tab.
        if (
            self.state.active_detail_tab_name in self.PERIODICALLY_REFRESHED_TABS
            and self.state.selected_container_id
            and self._tab_load_future is None
        ):
            deadlines.append(self._next_visible_tab_refresh_at)

        # Add the log deadline only when a poll could start on the next check.
        container_id = self.state.selected_container_id
        if (
            self.state.active_detail_tab_name == TabName.LOGS
            and container_id
            and container_id not in self.state.unreadable_log_container_ids
            and self._log_poll_future is None
            and not self._initial_log_snapshot_pending(container_id)
        ):
            deadlines.append(self._next_log_poll_at)

        # Use a slow fallback check when no task currently has a useful deadline.
        if not deadlines:
            return self.IDLE_SCHEDULER_DELAY
        next_deadline = min(deadlines)
        return max(self.MIN_SCHEDULER_DELAY, next_deadline - now)

    def schedule_container_refresh(self, force: bool = False) -> None:
        """Start a container refresh unless one is already running.

        EDMApp uses force=True for startup. It skips the deadline but still does
        not start a second refresh while the first one is running.
        """
        # A forced refresh may skip the deadline, but it may not overlap another one.
        if self._container_refresh_future and not self._container_refresh_future.done():
            return

        # Normal refreshes wait for their deadline.
        if not force and time.monotonic() < self._next_container_refresh_at:
            return

        # Keep the Future until the result handler claims it.
        self._container_refresh_future = self.task_runner.submit(
            TaskKind.REFRESH,
            self.container_data_source.list_running_containers,
        )

    def schedule_selected_tab_load(self, force: bool = False) -> bool:
        """Load the selected tab when needed or force a fresh Docker request.

        UIController calls this after selection changes. The result handler calls
        it again if an older request finishes after another tab was selected. The
        periodic scheduler uses force=True to reload visible Env, Config, and Top
        data even when cached content exists. True means a load started or is
        waiting for the current request to finish.
        """
        # A tab cannot load until a container is selected.
        container_id = self.state.selected_container_id
        if not container_id:
            return False

        # Save both values so the result reaches the tab that requested it.
        container_tab_key = self.state.selected_container_tab_key
        if container_tab_key is None:
            return False

        # Normal navigation reuses cached text; forced loads fetch it again.
        if not force and container_tab_key in self.state.tab_content_cache:
            return False

        self.state.status_message = (
            f"Loading {self.state.active_detail_tab_name.value}..."
        )

        if self._tab_load_future and not self._tab_load_future.done():
            if not self._tab_load_future.cancel():
                # A running request cannot be cancelled. Its result handler will
                # load the current selection after this request finishes.
                return True
            self._tab_load_future = None

        # Clear the old error when a new attempt begins.
        self.state.tab_load_errors.pop(container_tab_key, None)

        # Logs continue to update after their first load, unlike the other tabs.
        # Save when this request starts so the next successful log request can
        # pass that time to Docker as its since value.
        initial_log_request_started_at = (
            int(time.time()) if container_tab_key.tab_name == TabName.LOGS else None
        )
        self._tab_load_future = self.task_runner.submit(
            TaskKind.FETCH_TAB_CONTENT,
            self.tab_data_loader.load_tab_text,
            container_tab_key.container_id,
            container_tab_key.tab_name,
            task_context=DetailTaskContext(
                container_tab_key=container_tab_key,
                initial_log_request_started_at=initial_log_request_started_at,
            ),
        )
        if container_tab_key.tab_name in self.PERIODICALLY_REFRESHED_TABS:
            self._next_visible_tab_refresh_at = (
                time.monotonic() + self.app_config.tab_refresh_interval
            )
        return True

    def schedule_log_poll(self) -> None:
        """Start the next log update for the selected container.

        schedule_next_tasks() calls this only after checking that Logs can be
        polled. A container without a saved log time loads the configured number
        of recent lines. Later calls ask Docker for logs from the start time of
        the last successful request.
        """
        container_id = self.state.selected_container_id
        if not container_id:
            return

        # Without a saved time, load a fresh set of recent lines. Otherwise,
        # request all logs written since the last successful request started.
        since_timestamp = self._log_cursor_by_container_id.get(container_id)
        tail_lines: Union[int, str] = (
            self.app_config.log_tail if since_timestamp is None else "all"
        )

        # Save this time only after the request succeeds. If the request fails,
        # the next attempt uses the older time and cannot skip logs.
        request_started_at = int(time.time())
        self._log_poll_future = self.task_runner.submit(
            TaskKind.FETCH_LOG_UPDATES,
            self._fetch_log_update,
            container_id,
            tail_lines,
            since_timestamp,
            task_context=LogTaskContext(
                container_id=container_id,
                replace_existing=since_timestamp is None,
                request_started_at=request_started_at,
            ),
        )

    def claim_completed_task(self, completed_task: CompletedTask) -> bool:
        """Check that a finished task is still current, then mark it as finished.

        BackgroundTaskResultHandler calls this before using a task result. The
        scheduler compares the task's Future with the Future saved when that task
        was started. A match means this is the current request. The scheduler
        then sets its saved Future to None and allows the result to update the
        UI. A different Future belongs to an older request, so its result is
        ignored.
        """
        # Only the exact Future stored for this task type represents the current
        # request. Any other Future belongs to an older or replaced request.
        if (
            completed_task.kind == TaskKind.REFRESH
            and completed_task.future is self._container_refresh_future
        ):
            self._container_refresh_future = None
            return True
        if (
            completed_task.kind == TaskKind.FETCH_TAB_CONTENT
            and completed_task.future is self._tab_load_future
        ):
            self._tab_load_future = None
            return True
        if (
            completed_task.kind == TaskKind.FETCH_LOG_UPDATES
            and completed_task.future is self._log_poll_future
        ):
            self._log_poll_future = None
            return True
        return False

    def record_initial_log_load_success(
        self,
        container_id: str,
        request_started_at: int,
    ) -> None:
        """Prepare incremental log polling after the first Logs load succeeds.

        The result handler calls this after storing the first Logs content. It
        saves when that request started, and the next Docker request uses this
        time as its since value. This includes logs written while the first
        request was running. Repeated boundary lines are removed when logs merge.
        """
        self._log_cursor_by_container_id[container_id] = request_started_at
        self._next_log_poll_at = 0.0

    def record_log_poll_success(
        self,
        container_id: str,
        request_started_at: int,
    ) -> None:
        """Save the start time used by the next incremental log request.

        The result handler calls this after it stores a FETCH_LOG_UPDATES result.
        It saves when that request started, and the next request passes this time
        to Docker as its since value. This method is not called after a failure,
        so a retry uses the previous time and cannot skip logs.
        """
        self._log_cursor_by_container_id[container_id] = request_started_at

    def reset_log_poll_schedule(self) -> None:
        """Allow the new selection to be polled as soon as possible.

        UIController calls this after a container or tab change. A queued request
        is cancelled when possible. A running request stays tracked until it
        finishes, and the next poll becomes due immediately afterward.
        """
        if self._log_poll_future and not self._log_poll_future.done():
            # Future.cancel() works only before a worker starts the request.
            if self._log_poll_future.cancel():
                self._log_poll_future = None
        else:
            self._log_poll_future = None
        self._next_log_poll_at = 0.0

    def remove_stopped_container_log_tracking(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Delete saved log times for containers that are no longer running.

        UIController calls this after a successful container refresh. Removing
        these unused entries prevents log-tracking data from growing throughout
        a long session.
        """
        self._log_cursor_by_container_id = {
            container_id: log_cursor
            for container_id, log_cursor in self._log_cursor_by_container_id.items()
            if container_id in running_container_ids
        }

    def _fetch_log_update(
        self,
        container_id: str,
        tail_lines: Union[int, str],
        since_timestamp: Optional[int],
    ) -> str:
        """Fetch one log update and trim it before returning.

        BackgroundTaskRunner calls this for FETCH_LOG_UPDATES. Trimming on the
        worker thread limits memory use and work on the UI thread.
        """
        content = self.container_data_source.get_logs(
            container_id,
            tail_lines,
            since_timestamp,
        )
        return trim_log_text(
            content,
            max_lines=self.app_config.max_log_lines,
            max_line_chars=self.app_config.max_log_line_chars,
        )

    def _initial_log_snapshot_pending(self, container_id: str) -> bool:
        """Return True while the first Logs load is still being handled.

        The scheduler checks this before polling. The first load must store its
        Logs content and save its request time before incremental updates begin.
        """
        cache_key = ContainerTabKey(
            container_id=container_id,
            tab_name=TabName.LOGS,
        )
        # Wait when Logs has not been cached yet and a tab load is still running.
        return bool(
            cache_key not in self.state.tab_content_cache
            and self._tab_load_future is not None
        )


__all__ = ["BackgroundTaskScheduler"]
