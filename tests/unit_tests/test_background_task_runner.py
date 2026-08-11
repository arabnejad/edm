from __future__ import annotations

from dataclasses import FrozenInstanceError
from threading import Event

import pytest

from easy_docker_manager.app.background_task_runner import (
    BackgroundTaskRunner,
    DetailTaskContext,
    LogTaskContext,
    TaskKind,
)
from easy_docker_manager.core.content_cache import ContainerTabKey
from easy_docker_manager.core.tabs import TabName


def test_task_kind_values_name_each_background_operation() -> None:
    assert TaskKind.REFRESH.value == "refresh"
    assert TaskKind.FETCH_TAB_CONTENT.value == "fetch_tab_content"
    assert TaskKind.FETCH_LOG_UPDATES.value == "fetch_log_updates"


def test_task_contexts_are_immutable() -> None:
    detail_task_context = DetailTaskContext(ContainerTabKey("abc", TabName.ENV))
    log_task_context = LogTaskContext(
        "abc",
        replace_existing=False,
        request_started_at=10,
    )

    with pytest.raises(FrozenInstanceError):
        detail_task_context.initial_log_request_started_at = 20  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        log_task_context.replace_existing = True  # type: ignore[misc]


def test_runner_executes_function_and_queues_completed_task() -> None:
    completion_notification = Event()
    task_runner = BackgroundTaskRunner(
        max_workers=1,
        notify_task_ready=completion_notification.set,
    )
    task_context = DetailTaskContext(ContainerTabKey("abc", TabName.ENV))

    try:
        future = task_runner.submit(
            TaskKind.FETCH_TAB_CONTENT,
            lambda left, right: left + right,
            2,
            3,
            task_context=task_context,
        )

        assert future.result(timeout=2) == 5
        assert completion_notification.wait(timeout=2)
        completed_tasks = task_runner.pop_all_completed_tasks()
        assert len(completed_tasks) == 1
        assert completed_tasks[0].kind == TaskKind.FETCH_TAB_CONTENT
        assert completed_tasks[0].future is future
        assert completed_tasks[0].task_context is task_context
        assert task_runner.pop_all_completed_tasks() == []
    finally:
        task_runner.shutdown()


def test_fast_task_completion_does_not_deadlock_callback_registration() -> None:
    completion_notification = Event()
    task_runner = BackgroundTaskRunner(
        max_workers=1,
        notify_task_ready=completion_notification.set,
    )

    try:
        future = task_runner.submit(TaskKind.REFRESH, lambda: "done")
        assert future.result(timeout=2) == "done"
        assert completion_notification.wait(timeout=2)
    finally:
        task_runner.shutdown()


def test_shutdown_stops_new_submissions_and_is_idempotent() -> None:
    task_runner = BackgroundTaskRunner(
        max_workers=1,
        notify_task_ready=lambda: None,
    )
    task_runner.shutdown()
    task_runner.shutdown()

    with pytest.raises(RuntimeError, match="shutting down"):
        task_runner.submit(TaskKind.REFRESH, lambda: None)
