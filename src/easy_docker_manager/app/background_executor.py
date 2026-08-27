"""Run blocking work without holding up the terminal interface.

Docker requests and file writes can take time. BackgroundExecutor runs them in
worker threads so the UI thread remains free to handle keys and redraw the
screen.

The caller provides two functions when submitting work:

1. A worker function that may block.
2. A completion function that applies the result to UI state.

The worker function runs in the thread pool. When it finishes, the executor
puts its completion function in a queue and wakes EDMApp. EDMApp later runs the
completion function on the UI thread. Worker threads therefore never update
TerminalSessionState or Urwid widgets.
"""

from __future__ import annotations

import queue
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from threading import Lock
from typing import Any, TypeVar

WorkerResult = TypeVar("WorkerResult")
UICompletionCallback = Callable[[], bool]


class BackgroundExecutor:
    """Run blocking functions and queue their UI-thread completion functions.

    DockerManager uses this executor for Docker requests, and
    TabExportController uses it for export file writes. Each completion
    callback is defined beside the code that starts the work. EDMApp drains the
    callback queue whenever BackgroundNotifier reports a finished operation.
    """

    def __init__(
        self,
        max_workers: int,
        notify_completion_ready: Callable[[], None],
    ) -> None:
        """Create the worker pool and save the function that wakes EDMApp."""
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._completed_callbacks: queue.SimpleQueue[UICompletionCallback] = (
            queue.SimpleQueue()
        )
        self._notify_completion_ready = notify_completion_ready
        self._shutdown_lock = Lock()
        self._is_shutting_down = False

    def submit(
        self,
        fn: Callable[..., WorkerResult],
        *function_arguments: Any,
        on_complete: Callable[[Future[WorkerResult]], bool],
    ) -> Future[WorkerResult]:
        """Run fn in a worker and queue on_complete after it finishes.

        Values in function_arguments are passed only to fn. The on_complete
        function receives the finished Future later on the UI thread, where it
        can safely update session state.

        For example:

            submit(
                load_tab_text,
                container_id,
                tab_name,
                on_complete=handle_loaded_tab,
            )

        runs load_tab_text(container_id, tab_name) in a worker. EDMApp later
        calls handle_loaded_tab(future) on the UI thread.
        """
        with self._shutdown_lock:
            if self._is_shutting_down:
                raise RuntimeError("BackgroundExecutor is shutting down")
            future = self._thread_pool.submit(fn, *function_arguments)

        completion_callback = partial(on_complete, future)

        # A Future may already be finished when this callback is registered.
        # Register it after releasing the lock because queueing also uses the lock.
        future.add_done_callback(
            lambda _finished_future: self._queue_completion_callback(
                completion_callback
            )
        )
        return future

    def get_and_remove_all_ui_completion_callbacks(
        self,
    ) -> list[UICompletionCallback]:
        """Remove and return every completion waiting for the UI thread.

        EDMApp calls this after the notifier wakes it. Removing callbacks here
        ensures that each background result is handled once.
        """
        completion_callbacks: list[UICompletionCallback] = []
        while True:
            try:
                completion_callbacks.append(self._completed_callbacks.get_nowait())
            except queue.Empty:
                break
        return completion_callbacks

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting work and optionally wait for running work to finish."""
        with self._shutdown_lock:
            if self._is_shutting_down:
                return
            self._is_shutting_down = True
        self._thread_pool.shutdown(wait=wait, cancel_futures=True)

    def _queue_completion_callback(
        self,
        completion_callback: UICompletionCallback,
    ) -> None:
        """Queue one UI callback and tell EDMApp that it is ready."""
        with self._shutdown_lock:
            if self._is_shutting_down:
                return
            self._completed_callbacks.put(completion_callback)
            self._notify_completion_ready()


__all__ = ["BackgroundExecutor", "UICompletionCallback"]
