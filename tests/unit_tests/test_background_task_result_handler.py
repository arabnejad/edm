from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from easy_docker_manager.app.background_task_result_handler import (
    BackgroundTaskResultHandler,
)
from easy_docker_manager.app.background_task_runner import (
    CompletedTask,
    DetailTaskContext,
    LogTaskContext,
    TaskKind,
)
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.content_cache import ContainerTabKey
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.docker.base import (
    ContainerLogFetchError,
    ContainerRefreshError,
    DockerRequestFailedError,
    FailedDockerRequestType,
    LogsUnavailableError,
)


@dataclass
class ResultHandlerTestSetup:
    handler: BackgroundTaskResultHandler
    scheduler: Mock
    ui_controller: Mock


@pytest.fixture
def handler_factory(session_state_factory):
    def create_handler(state=None, config=None):
        selected_state = state if state is not None else session_state_factory()
        scheduler = Mock()
        scheduler.claim_completed_task.return_value = True
        scheduler.schedule_selected_tab_load.return_value = False
        ui_controller = Mock()
        ui_controller.update_running_containers.return_value = True
        ui_controller.select_last_detail_line.return_value = True
        handler = BackgroundTaskResultHandler(
            selected_state,
            config if config is not None else AppConfig(),
            scheduler,
            ui_controller,
        )
        return ResultHandlerTestSetup(
            handler=handler,
            scheduler=scheduler,
            ui_controller=ui_controller,
        )

    return create_handler


def test_handle_completed_task_ignores_replaced_task(
    handler_factory,
    completed_future_factory,
) -> None:
    test_setup = handler_factory()
    handler = test_setup.handler
    scheduler = test_setup.scheduler
    ui_controller = test_setup.ui_controller
    scheduler.claim_completed_task.return_value = False
    completed_task = CompletedTask(TaskKind.REFRESH, completed_future_factory([]))

    assert not handler.handle_completed_task(completed_task)
    ui_controller.update_running_containers.assert_not_called()


def test_completed_refresh_updates_the_running_container_list(
    handler_factory,
    completed_future_factory,
    container_summary_factory,
) -> None:
    test_setup = handler_factory()
    handler = test_setup.handler
    ui_controller = test_setup.ui_controller
    containers = [container_summary_factory()]
    completed_task = CompletedTask(
        TaskKind.REFRESH,
        completed_future_factory(containers),
    )

    assert handler.handle_completed_task(completed_task)
    ui_controller.update_running_containers.assert_called_once_with(containers)


@pytest.mark.parametrize(
    "error",
    [ContainerRefreshError("offline"), RuntimeError("unexpected")],
)
def test_refresh_failure_keeps_list_and_updates_status(
    error: Exception,
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = handler_factory(state)
    handler = test_setup.handler
    ui_controller = test_setup.ui_controller

    assert handler.handle_container_refresh_completion(
        completed_future_factory(exception=error)
    )
    assert state.running_containers
    assert state.status_message == f"Container refresh failed: {error}"
    ui_controller.update_running_containers.assert_not_called()


def test_active_tab_content_is_cached_and_updates_status(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_load_errors[container_tab_key] = "old"
    handler = handler_factory(state).handler

    assert handler.handle_tab_content_completion(
        completed_future_factory("A=1"),
        DetailTaskContext(container_tab_key),
    )
    assert state.tab_content_cache[container_tab_key] == "A=1"
    assert container_tab_key not in state.tab_load_errors
    assert state.status_message == "Loaded Env"


def test_hidden_tab_content_is_cached_without_redrawing(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.LOGS)
    hidden_container_tab_key = ContainerTabKey("container-1", TabName.CONFIG)
    handler = handler_factory(state).handler

    assert not handler.handle_tab_content_completion(
        completed_future_factory("config"),
        DetailTaskContext(hidden_container_tab_key),
    )
    assert state.tab_content_cache[hidden_container_tab_key] == "config"


def test_initial_logs_are_trimmed_and_start_polling(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    test_setup = handler_factory(
        state,
        AppConfig(max_log_lines=2, max_log_line_chars=32),
    )
    handler = test_setup.handler
    scheduler = test_setup.scheduler
    ui_controller = test_setup.ui_controller
    content = f"old\n{'x' * 100}\nnew"

    assert handler.handle_tab_content_completion(
        completed_future_factory(content),
        DetailTaskContext(container_tab_key, initial_log_request_started_at=100),
    )
    assert "old" not in state.tab_content_cache[container_tab_key]
    scheduler.record_initial_log_load_success.assert_called_once_with(
        "container-1",
        100,
    )
    ui_controller.select_last_detail_line.assert_called_once_with()


def test_unreadable_initial_logs_are_cached_and_not_polled(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    handler = handler_factory(state).handler

    assert handler.handle_tab_content_completion(
        completed_future_factory(exception=LogsUnavailableError("none")),
        DetailTaskContext(container_tab_key),
    )
    assert "container-1" in state.unreadable_log_container_ids
    assert "driver 'none'" in state.tab_content_cache[container_tab_key]
    assert state.status_message == "Logs unavailable for selected container."


def test_temporary_initial_log_error_keeps_cached_text(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "old logs"
    handler = handler_factory(state).handler

    assert handler.handle_tab_content_completion(
        completed_future_factory(
            exception=ContainerLogFetchError("container-1", "timeout")
        ),
        DetailTaskContext(container_tab_key),
    )
    assert state.tab_content_cache[container_tab_key] == "old logs"
    assert state.tab_load_errors[container_tab_key].startswith("Log fetch failed:")


@pytest.mark.parametrize(
    "error",
    [
        DockerRequestFailedError(
            FailedDockerRequestType.LOAD_ENVIRONMENT,
            "container-1",
            "denied",
        ),
        RuntimeError("unexpected"),
    ],
)
def test_tab_errors_are_stored_separately_from_content(
    error: Exception,
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    handler = handler_factory(state).handler

    assert handler.handle_tab_content_completion(
        completed_future_factory(exception=error),
        DetailTaskContext(container_tab_key),
    )
    assert container_tab_key not in state.tab_content_cache
    assert state.tab_load_errors[container_tab_key].startswith("Error loading Env:")


def test_completed_old_tab_load_schedules_the_current_tab(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    old_container_tab_key = ContainerTabKey("container-1", TabName.CONFIG)
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler
    scheduler.schedule_selected_tab_load.return_value = True
    completed_task = CompletedTask(
        TaskKind.FETCH_TAB_CONTENT,
        completed_future_factory("config"),
        DetailTaskContext(old_container_tab_key),
    )

    assert handler.handle_completed_task(completed_task)
    scheduler.schedule_selected_tab_load.assert_called_once_with(force=False)


def test_invalid_task_context_is_rejected(
    handler_factory,
    completed_future_factory,
) -> None:
    handler = handler_factory().handler
    completed_task = CompletedTask(
        TaskKind.FETCH_TAB_CONTENT,
        completed_future_factory("text"),
    )
    assert not handler.handle_completed_task(completed_task)


def test_log_update_appends_new_lines_and_advances_the_log_cursor(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "A\nB"
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler
    ui_controller = test_setup.ui_controller
    log_task_context = LogTaskContext("container-1", False, 200)

    assert handler.handle_log_poll_completion(
        completed_future_factory("B\nC"),
        log_task_context,
    )
    assert state.tab_content_cache[container_tab_key] == "A\nB\nC"
    scheduler.record_log_poll_success.assert_called_once_with("container-1", 200)
    ui_controller.select_last_detail_line.assert_called_once_with()


def test_first_log_update_can_replace_existing_text(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "old"
    handler = handler_factory(state).handler

    handler.handle_log_poll_completion(
        completed_future_factory("new"),
        LogTaskContext("container-1", True, 200),
    )
    assert state.tab_content_cache[container_tab_key] == "new"


def test_empty_replacement_log_update_clears_existing_text(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "stale"
    handler = handler_factory(state).handler

    assert handler.handle_log_poll_completion(
        completed_future_factory(""),
        LogTaskContext("container-1", True, 200),
    )
    assert state.tab_content_cache[container_tab_key] == ""


def test_empty_incremental_log_update_keeps_existing_text(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "existing"
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler

    assert not handler.handle_log_poll_completion(
        completed_future_factory(""),
        LogTaskContext("container-1", False, 200),
    )
    assert state.tab_content_cache[container_tab_key] == "existing"
    scheduler.record_log_poll_success.assert_called_once_with("container-1", 200)


@pytest.mark.parametrize(
    "error",
    [
        ContainerLogFetchError("container-1", "timeout"),
        DockerRequestFailedError(
            FailedDockerRequestType.FETCH_LOGS,
            "container-1",
            "denied",
        ),
        RuntimeError("unexpected"),
    ],
)
def test_failed_log_update_does_not_advance_the_log_cursor(
    error: Exception,
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler

    assert handler.handle_log_poll_completion(
        completed_future_factory(exception=error),
        LogTaskContext("container-1", False, 200),
    )
    assert state.status_message.startswith("Log fetch failed:")
    scheduler.record_log_poll_success.assert_not_called()


def test_unreadable_incremental_logs_stop_future_polling(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler

    assert handler.handle_log_poll_completion(
        completed_future_factory(exception=LogsUnavailableError("none")),
        LogTaskContext("container-1", False, 200),
    )
    assert "container-1" in state.unreadable_log_container_ids
    scheduler.record_log_poll_success.assert_not_called()


def test_hidden_container_log_update_changes_cache_without_redrawing(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory("visible")
    hidden_container_tab_key = ContainerTabKey("hidden", TabName.LOGS)
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler

    assert not handler.handle_log_poll_completion(
        completed_future_factory("line"),
        LogTaskContext("hidden", True, 200),
    )
    assert state.tab_content_cache[hidden_container_tab_key] == "line"
    scheduler.record_log_poll_success.assert_called_once_with("hidden", 200)


def test_successful_empty_log_update_clears_failure_status(
    handler_factory,
    completed_future_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.status_message = "Log fetch failed: timeout"
    test_setup = handler_factory(state)
    handler = test_setup.handler
    scheduler = test_setup.scheduler

    assert handler.handle_log_poll_completion(
        completed_future_factory(""),
        LogTaskContext("container-1", False, 200),
    )
    assert state.status_message == "Loaded Logs"
    scheduler.record_log_poll_success.assert_called_once_with("container-1", 200)


def test_merge_log_updates_handles_empty_and_duplicate_batches() -> None:
    merge_log_updates = BackgroundTaskResultHandler._merge_log_updates
    assert merge_log_updates("", "A") == "A"
    assert merge_log_updates("A", "") == "A"
    assert merge_log_updates("A\nB", "A\nB") == "A\nB"
