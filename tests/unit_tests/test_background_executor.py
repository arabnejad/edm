from __future__ import annotations

from threading import Event

import pytest

from easy_docker_manager.app.background_executor import BackgroundExecutor


def test_executor_runs_function_and_queues_its_ui_completion_callback() -> None:
    completion_notification = Event()
    background_executor = BackgroundExecutor(
        max_background_worker_threads=1,
        notify_ui_completion_ready=completion_notification.set,
    )

    def handle_completion(completed_future) -> bool:
        return completed_future.result() == 5

    try:
        future = background_executor.submit(
            lambda left, right: left + right,
            2,
            3,
            on_complete=handle_completion,
        )

        assert future.result(timeout=2) == 5
        assert completion_notification.wait(timeout=2)
        completion_callbacks = (
            background_executor.get_and_remove_all_ui_completion_callbacks()
        )
        assert len(completion_callbacks) == 1
        assert completion_callbacks[0]()
        assert background_executor.get_and_remove_all_ui_completion_callbacks() == []
    finally:
        background_executor.shutdown()


def test_fast_completion_does_not_deadlock_callback_registration() -> None:
    completion_notification = Event()
    background_executor = BackgroundExecutor(
        max_background_worker_threads=1,
        notify_ui_completion_ready=completion_notification.set,
    )

    try:
        future = background_executor.submit(
            lambda: "done",
            on_complete=lambda _future: False,
        )
        assert future.result(timeout=2) == "done"
        assert completion_notification.wait(timeout=2)
    finally:
        background_executor.shutdown()


def test_shutdown_stops_new_submissions_and_can_be_called_twice() -> None:
    background_executor = BackgroundExecutor(
        max_background_worker_threads=1,
        notify_ui_completion_ready=lambda: None,
    )
    background_executor.shutdown()
    background_executor.shutdown()

    with pytest.raises(RuntimeError, match="shutting down"):
        background_executor.submit(
            lambda: None,
            on_complete=lambda _future: False,
        )
