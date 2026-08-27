"""Run slow functions without blocking the terminal interface.

Docker requests and file writes can take time. BackgroundExecutor runs them in
worker threads so the UI thread remains free to handle keys and redraw the
screen.

Each submission includes two functions:

1. A worker function that may block.
2. A completion function that applies the result to session state or the screen.

The first function runs in the thread pool. When it finishes, the executor puts
the second function in a queue and wakes EDMApp. EDMApp runs that completion
function on the UI thread, so worker threads never change TerminalSessionState
or Urwid widgets directly.
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
    """Run slow functions in workers and queue their completion callbacks.

    DockerManager uses this executor for Docker requests, and
    TabExportController uses it for file writes. The caller supplies the
    callback that knows how to apply each result. BackgroundNotifier wakes
    EDMApp, which then runs the queued callbacks on the UI thread.
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

        # add_done_callback() runs the callback immediately if the Future has
        # already finished. Register it after releasing _shutdown_lock because
        # _queue_completion_callback() needs the same lock.
        future.add_done_callback(
            lambda _finished_future: self._queue_completion_callback(
                completion_callback
            )
        )
        return future

    def get_and_remove_all_ui_completion_callbacks(
        self,
    ) -> list[UICompletionCallback]:
        """Remove and return all callbacks waiting for the UI thread.

        EDMApp calls this after the notifier wakes it. A callback is removed
        from the queue before it runs, so each result is handled only once.
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
