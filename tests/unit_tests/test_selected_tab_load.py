from __future__ import annotations

from unittest.mock import Mock

import pytest

from easy_docker_manager.app import selected_tab_load as selected_tab_load_module
from easy_docker_manager.core.container_list import ContainerList
from easy_docker_manager.core.tabs import (
    TabName,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerLogsUnavailableError,
    DockerRequestFailedError,
    FailedDockerRequestType,
)


def test_tab_load_requires_selection_and_reuses_cached_text(
    docker_manager_factory,
    session_state_factory,
) -> None:
    empty_setup = docker_manager_factory()
    assert not empty_setup.docker_manager.load_selected_tab_content_if_needed()

    state = session_state_factory(tab=TabName.ENV)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "A=1"
    cached_setup = docker_manager_factory(state)
    assert not cached_setup.docker_manager.load_selected_tab_content_if_needed()
    assert cached_setup.background_executor.requests == []


def test_tab_load_clears_old_error_and_records_initial_log_time(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_error_messages[selected_tab_key] = "old"
    test_setup = docker_manager_factory(state)
    monkeypatch.setattr(selected_tab_load_module.time, "time", lambda: 123.9)

    assert test_setup.docker_manager.load_selected_tab_content_if_needed()
    assert selected_tab_key not in state.tab_content_error_messages
    assert state.status_message == "Loading Logs..."

    assert test_setup.background_executor.complete_submission(result="first logs")
    assert state.tab_content_cache[selected_tab_key] == "first logs"
    assert test_setup.container_log_updater._log_cursor_by_container_id == {
        "container-1": 123
    }


def test_initial_logs_are_cached_without_applying_worker_limits_again(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    test_setup = docker_manager_factory(state)
    limit_log_content = Mock()
    test_setup.container_log_updater.apply_configured_limits_to_log_content = (
        limit_log_content
    )

    test_setup.docker_manager.load_selected_tab_content_if_needed()
    assert test_setup.background_executor.complete_submission(
        result="limited by worker"
    )

    assert state.tab_content_cache[selected_tab_key] == "limited by worker"
    limit_log_content.assert_not_called()


def test_running_old_tab_load_finishes_before_loading_new_selection(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
            [
                container_summary_factory("one"),
                container_summary_factory("two"),
            ]
        ),
        selected_container_index=0,
        active_detail_tab_name=TabName.ENV,
    )
    test_setup = docker_manager_factory(state)
    assert test_setup.docker_manager.load_selected_tab_content_if_needed()
    first_request = test_setup.background_executor.requests[0]
    first_request.future.set_running_or_notify_cancel()

    state.selected_container_index = 1
    test_setup.docker_manager.prepare_selected_container_details()
    assert len(test_setup.background_executor.requests) == 1

    first_request.future.set_result("OLD=1")
    assert first_request.completion_callback(first_request.future)
    assert len(test_setup.background_executor.requests) == 2
    assert test_setup.background_executor.requests[1].arguments == (
        "two",
        TabName.ENV,
    )


def test_queued_old_tab_load_is_cancelled_and_replaced(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
            [
                container_summary_factory("one"),
                container_summary_factory("two"),
            ]
        ),
        selected_container_index=0,
        active_detail_tab_name=TabName.CONFIG,
    )
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed()
    old_request = test_setup.background_executor.requests[0]

    state.selected_container_index = 1
    test_setup.docker_manager.prepare_selected_container_details()

    assert old_request.future.cancelled()
    assert len(test_setup.background_executor.requests) == 2


def test_tab_change_reuses_cache_and_updates_navigation_state(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "A=1"
    state.detail_selected_line_index = 5
    state.follow_log_tail = True
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.prepare_active_detail_tab()

    assert state.detail_selected_line_index == 0
    assert not state.follow_log_tail
    assert state.status_message == "Loaded Env"
    assert test_setup.background_executor.requests == []


def test_hidden_tab_result_is_cached_before_current_tab_load_starts(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.CONFIG)
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed()
    requested_tab_key = state.selected_container_tab_key
    assert requested_tab_key is not None
    state.active_detail_tab_name = TabName.ENV

    assert test_setup.background_executor.complete_submission(result="config")
    assert state.tab_content_cache[requested_tab_key] == "config"
    assert test_setup.background_executor.requests[1].arguments == (
        "container-1",
        TabName.ENV,
    )


def test_unreadable_initial_logs_are_cached_and_stop_polling(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed()

    assert test_setup.background_executor.complete_submission(
        exception=ContainerLogsUnavailableError("none")
    )
    assert "container-1" in state.unreadable_log_container_ids
    assert selected_tab_key not in state.tab_content_cache
    assert "driver 'none'" in state.tab_content_error_messages[selected_tab_key]
    assert state.status_message == "Logs unavailable for selected container."


def test_temporary_initial_log_error_removes_cached_text(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "old logs"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed(force=True)

    assert test_setup.background_executor.complete_submission(
        exception=ContainerLogFetchError("container-1", "timeout")
    )
    assert selected_tab_key not in state.tab_content_cache
    assert state.tab_content_error_messages[selected_tab_key].startswith(
        "Log fetch failed:"
    )


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
def test_non_log_tab_refresh_errors_keep_cached_content(
    error: Exception,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "VALUE=previous"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed(force=True)

    assert test_setup.background_executor.complete_submission(exception=error)
    assert state.tab_content_cache[selected_tab_key] == "VALUE=previous"
    assert state.tab_content_error_messages[selected_tab_key].startswith(
        "Error loading Env:"
    )


def test_stats_refresh_error_removes_the_previous_resource_sample(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.STATS)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "old resource sample"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed(force=True)

    assert test_setup.background_executor.complete_submission(
        exception=DockerRequestFailedError(
            FailedDockerRequestType.LOAD_CONTAINER_RESOURCE_STATS,
            "container-1",
            "timeout",
        )
    )
    assert selected_tab_key not in state.tab_content_cache
    assert state.tab_content_error_messages[selected_tab_key].startswith(
        "Error loading Stats:"
    )
