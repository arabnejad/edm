"""Run slow work outside the UI thread and report when it finishes.

Docker requests can take time. BackgroundTaskRunner runs them in a thread pool
so keyboard input and screen updates stay responsive. The scheduler submits
container, tab, and log work through this runner.

The workflow from submission to result handling is:

1. BackgroundTaskScheduler calls submit() with a function and its arguments.
2. A worker thread runs the function while the scheduler tracks its Future.
3. _queue_completed_task() puts the finished Future in the completion queue and
   wakes EDMApp.
4. EDMApp drains the queue on the UI thread and gives each task to
   BackgroundTaskResultHandler.
5. The result handler updates session state and tells EDMApp whether to redraw.

Worker threads only fetch data. They never update UI state or Urwid widgets.
"""

from __future__ import annotations

import queue
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Any, Optional, Union

from easy_docker_manager.core.content_cache import ContainerTabKey


class TaskKind(Enum):
    """Name each type of background work.

    A CompletedTask keeps this value so BackgroundTaskResultHandler knows
    whether it received a container refresh, a tab load, or a log update.
    """

    # Refresh the list of running Docker containers.
    REFRESH = "refresh"
    # Fetch content for the active Logs, Env, Config, or Top tab.
    FETCH_TAB_CONTENT = "fetch_tab_content"
    # Fetch new log lines for the selected container.
    FETCH_LOG_UPDATES = "fetch_log_updates"


@dataclass(frozen=True)
class DetailTaskContext:
    """Remember which container tab requested a background load.

    The result handler uses container_tab_key even if the user changes selection
    before the request finishes. Initial Logs loads also keep their start time
    so the next poll does not miss lines. Other tabs leave that value as None.
    It is frozen so this request information cannot change while the task moves
    from a worker thread back to the UI thread.
    """

    container_tab_key: ContainerTabKey
    initial_log_request_started_at: Optional[int] = None


@dataclass(frozen=True)
class LogTaskContext:
    """Remember how to apply a completed log update.

    The scheduler creates this for FETCH_LOG_UPDATES. The result handler uses
    container_id to choose the cache entry and replace_existing to decide
    whether to replace or append text. After a successful request,
    request_started_at becomes Docker's since value for the next log request.
    It is frozen so the completed result is always applied with the same
    container, merge mode, and request time that the scheduler originally set.
    """

    container_id: str
    replace_existing: bool
    request_started_at: int


# Extra information needed after each task finishes:
# - FETCH_TAB_CONTENT uses DetailTaskContext.
# - FETCH_LOG_UPDATES uses LogTaskContext.
# REFRESH uses None because it needs no additional information.
TaskContext = Union[DetailTaskContext, LogTaskContext]


@dataclass(frozen=True)
class CompletedTask:
    """Carry one finished worker task back to the UI thread.

    BackgroundTaskRunner creates this when work is submitted and queues it after
    the Future finishes. EDMApp then passes it to BackgroundTaskResultHandler.

    The result handler uses kind to choose how to process the task. future holds
    the return value or exception. task_context holds any extra information
    needed for tab and log results. It is frozen so the task kind, Future, and
    context cannot be replaced after the worker queues the task for the UI
    thread.
    """

    kind: TaskKind
    future: Future
    task_context: Optional[TaskContext] = None


class BackgroundTaskRunner:
    """Run submitted functions in a worker thread pool.

    Each task has a TaskKind and optional context for later result handling.
    When it finishes, the runner queues a CompletedTask and calls notify so
    EDMApp can process the result on the UI thread.
    """

    def __init__(
        self,
        max_workers: int,
        notify_task_ready: Callable[[], None],
    ) -> None:
        """Create the worker pool and keep the callback that wakes EDMApp."""
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._completed_tasks: queue.SimpleQueue[CompletedTask] = queue.SimpleQueue()
        self._notify_task_ready = notify_task_ready
        self._lock = Lock()
        self._shutdown = False

    def submit(
        self,
        task_kind: TaskKind,
        fn: Callable[..., Any],
        *task_args: Any,
        task_context: Optional[TaskContext] = None,
    ) -> Future:
        """Submit a function to the worker pool and return its Future.

        BackgroundTaskScheduler calls this for container refreshes, tab loads,
        and log updates. Values in *task_args are passed to fn.
        task_context is kept with CompletedTask for the result handler instead
        of being passed to the function. Its position after *task_args makes it
        keyword-only.

        For example, this submission

            submit(
                TaskKind.FETCH_TAB_CONTENT,
                fetch,
                container_id,
                tab_name,
                task_context=detail_context,
            )

        calls fetch(container_id, tab_name) in a worker
        while retaining detail_context for result handling.

        The scheduler keeps the returned Future to track the active task. The
        result handler later reads the same Future on the UI thread.
        """
        with self._lock:
            if self._shutdown:
                raise RuntimeError("BackgroundTaskRunner is shutting down")
            future = self._executor.submit(fn, *task_args)
            completed_task = CompletedTask(
                kind=task_kind,
                future=future,
                task_context=task_context,
            )
        # Python calls the callback immediately if the Future already finished.
        # Register it after releasing the lock because the callback uses that lock.
        future.add_done_callback(
            lambda _future: self._queue_completed_task(completed_task)
        )
        return future

    def pop_all_completed_tasks(self) -> list[CompletedTask]:
        """Remove and return all tasks waiting for UI-thread handling.

        EDMApp calls this after the notifier wakes the UI thread. Removing tasks
        from the queue here ensures each completion is handled once.
        """
        completed_tasks: list[CompletedTask] = []
        while True:
            try:
                completed_tasks.append(self._completed_tasks.get_nowait())
            except queue.Empty:
                break
        return completed_tasks

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting work and optionally wait for running tasks to finish."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _queue_completed_task(self, completed_task: CompletedTask) -> None:
        """Queue one finished task and notify EDMApp."""
        with self._lock:
            if self._shutdown:
                return
        self._completed_tasks.put(completed_task)
        self._notify_task_ready()


__all__ = [
    "BackgroundTaskRunner",
    "CompletedTask",
    "DetailTaskContext",
    "LogTaskContext",
    "TaskContext",
    "TaskKind",
]
