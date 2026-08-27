from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import Mock

import pytest

from easy_docker_manager.app import docker_manager as docker_manager_module
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerRefreshError,
    DockerContainerClient,
    DockerRequestFailedError,
    FailedDockerRequestType,
    LogsUnavailableError,
)
from easy_docker_manager.tabs.tab_data_loader import TabDataLoader


@dataclass
class RecordedRequest:
    """Store one worker request so a test can finish it later."""

    fn: Callable[..., Any]
    arguments: tuple[Any, ...]
    completion_callback: Callable[[Future], bool]
    future: Future


class RecordingBackgroundExecutor:
    """Record submitted work without starting worker threads."""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []

    def submit(
        self,
        fn: Callable[..., Any],
        *arguments: Any,
        on_complete: Callable[[Future], bool],
    ) -> Future:
        future: Future = Future()
        self.requests.append(
            RecordedRequest(
                fn=fn,
                arguments=arguments,
                completion_callback=on_complete,
                future=future,
            )
        )
        return future

    def finish_request(
        self,
        request_index: int = -1,
        result: Any = None,
        *,
        exception: Optional[BaseException] = None,
    ) -> bool:
        request = self.requests[request_index]
        if exception is not None:
            request.future.set_exception(exception)
        else:
            request.future.set_result(result)
        return request.completion_callback(request.future)


@dataclass
class DockerManagerTestSetup:
    docker_manager: DockerManager
    state: TerminalSessionState
    background_executor: RecordingBackgroundExecutor
    tab_data_loader: Mock
    docker_container_client: Mock


@pytest.fixture
def docker_manager_factory():
    def create_docker_manager(
        state: Optional[TerminalSessionState] = None,
        app_config: Optional[AppConfig] = None,
    ) -> DockerManagerTestSetup:
        selected_state = state if state is not None else TerminalSessionState()
        selected_config = app_config if app_config is not None else AppConfig()
        background_executor = RecordingBackgroundExecutor()
        tab_data_loader = Mock(spec=TabDataLoader)
        docker_container_client = Mock(spec=DockerContainerClient)
        docker_manager = DockerManager(
            selected_state,
            selected_config,
            background_executor,  # type: ignore[arg-type]
            tab_data_loader,
            docker_container_client,
        )
        return DockerManagerTestSetup(
            docker_manager=docker_manager,
            state=selected_state,
            background_executor=background_executor,
            tab_data_loader=tab_data_loader,
            docker_container_client=docker_container_client,
        )

    return create_docker_manager


def test_due_container_refresh_is_submitted_once(
    monkeypatch,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert len(test_setup.background_executor.requests) == 1
    request = test_setup.background_executor.requests[0]
    assert request.fn == test_setup.docker_container_client.list_running_containers
    assert request.arguments == ()
    assert test_setup.docker_manager._next_container_refresh_at == 12.0


def test_visible_non_log_tab_is_reloaded_on_its_interval(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "OLD=value"
    test_setup = docker_manager_factory(
        state,
        AppConfig(tab_refresh_interval=3.0),
    )
    test_setup.docker_manager._next_container_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    request = test_setup.background_executor.requests[0]
    assert request.fn == test_setup.tab_data_loader.load_tab_text
    assert request.arguments == ("container-1", TabName.ENV)
    assert test_setup.docker_manager._next_visible_tab_refresh_at == 13.0


def test_loaded_readable_logs_are_polled_when_due(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "initial"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(docker_manager_module.time, "time", lambda: 50.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    request = test_setup.background_executor.requests[0]
    assert request.fn == test_setup.docker_manager._fetch_log_poll_content
    assert request.arguments == ("container-1", 100, None)
    assert test_setup.docker_manager._next_log_poll_at == 11.0


def test_unreadable_logs_are_not_polled(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.unreadable_log_container_ids.add("container-1")
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.requests == []


def test_next_request_check_uses_nearest_deadline_and_idle_delay(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.TOP)
    docker_manager = docker_manager_factory(state).docker_manager
    docker_manager._next_container_refresh_at = 100.0
    docker_manager._next_visible_tab_refresh_at = 8.5
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 5.0)

    assert docker_manager.get_next_docker_data_refresh_delay() == 3.5

    docker_manager._tab_load_future = Future()
    docker_manager._container_refresh_future = Future()
    assert docker_manager.get_next_docker_data_refresh_delay() == 1.0


def test_overdue_request_check_uses_small_positive_delay(
    monkeypatch,
    docker_manager_factory,
) -> None:
    docker_manager = docker_manager_factory().docker_manager
    docker_manager._next_container_refresh_at = 4.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 5.0)
    assert docker_manager.get_next_docker_data_refresh_delay() == 0.05


def test_container_refresh_honors_deadline_and_force(
    monkeypatch,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager._next_container_refresh_at = 20.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)

    assert not test_setup.docker_manager.start_running_container_list_refresh()
    assert test_setup.docker_manager.start_running_container_list_refresh(force=True)
    assert not test_setup.docker_manager.start_running_container_list_refresh(
        force=True
    )
    assert len(test_setup.background_executor.requests) == 1


def test_refresh_selects_first_container_and_loads_its_active_tab(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    test_setup = docker_manager_factory()
    containers = [
        container_summary_factory("one"),
        container_summary_factory("two"),
    ]
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.finish_request(result=containers)
    assert test_setup.state.selected_container_id == "one"
    assert test_setup.state.status_message == "Loading Logs..."
    assert len(test_setup.background_executor.requests) == 2
    assert test_setup.background_executor.requests[1].arguments == (
        "one",
        TabName.LOGS,
    )


def test_refresh_preserves_selection_and_reapplies_active_sort(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_containers=[
            container_summary_factory("one"),
            container_summary_factory("two"),
        ],
        selected_container_index=1,
        container_sort_field=ContainerSortField.IMAGE,
        container_sort_descending=True,
    )
    test_setup = docker_manager_factory(state)
    refreshed = [
        container_summary_factory("two", image_name="nginx:latest"),
        container_summary_factory("three", image_name="redis:7"),
    ]
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.finish_request(result=refreshed)
    assert [item.container_id for item in state.running_containers] == [
        "three",
        "two",
    ]
    assert state.selected_container_id == "two"


def test_unchanged_refresh_recovers_from_error_status(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.status_message = "Container refresh failed: offline"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.finish_request(
        result=list(state.running_containers)
    )
    assert state.status_message == "1 running containers"


def test_repeated_empty_refresh_does_not_redraw_twice(docker_manager_factory) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_running_container_list_refresh(force=True)
    assert test_setup.background_executor.finish_request(result=[])
    assert test_setup.state.status_message == "No running containers."

    test_setup.docker_manager.start_running_container_list_refresh(force=True)
    assert not test_setup.background_executor.finish_request(result=[])


@pytest.mark.parametrize(
    "error",
    [ContainerRefreshError("offline"), RuntimeError("unexpected")],
)
def test_refresh_failure_keeps_existing_containers_and_shows_error(
    error: Exception,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.finish_request(exception=error)
    assert state.running_containers
    assert state.status_message == f"Container refresh failed: {error}"


def test_replaced_refresh_completion_is_ignored(
    docker_manager_factory,
    completed_future_factory,
) -> None:
    docker_manager = docker_manager_factory().docker_manager
    assert not docker_manager._apply_running_container_list_refresh_result(
        completed_future_factory([])
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
    state.tab_load_errors[selected_tab_key] = "old"
    test_setup = docker_manager_factory(state)
    monkeypatch.setattr(docker_manager_module.time, "time", lambda: 123.9)

    assert test_setup.docker_manager.load_selected_tab_content_if_needed()
    assert selected_tab_key not in state.tab_load_errors
    assert state.status_message == "Loading Logs..."

    assert test_setup.background_executor.finish_request(result="first logs")
    assert state.tab_content_cache[selected_tab_key] == "first logs"
    assert test_setup.docker_manager._log_cursor_by_container_id == {"container-1": 123}


def test_running_old_tab_load_finishes_before_loading_new_selection(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_containers=[
            container_summary_factory("one"),
            container_summary_factory("two"),
        ],
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
        running_containers=[
            container_summary_factory("one"),
            container_summary_factory("two"),
        ],
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

    assert test_setup.background_executor.finish_request(result="config")
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

    assert test_setup.background_executor.finish_request(
        exception=LogsUnavailableError("none")
    )
    assert "container-1" in state.unreadable_log_container_ids
    assert "driver 'none'" in state.tab_content_cache[selected_tab_key]
    assert state.status_message == "Logs unavailable for selected container."


def test_temporary_initial_log_error_keeps_cached_text(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "old logs"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed(force=True)

    assert test_setup.background_executor.finish_request(
        exception=ContainerLogFetchError("container-1", "timeout")
    )
    assert state.tab_content_cache[selected_tab_key] == "old logs"
    assert state.tab_load_errors[selected_tab_key].startswith("Log fetch failed:")


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
def test_non_log_tab_errors_are_saved_without_replacing_content(
    error: Exception,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed()

    assert test_setup.background_executor.finish_request(exception=error)
    assert selected_tab_key not in state.tab_content_cache
    assert state.tab_load_errors[selected_tab_key].startswith("Error loading Env:")


def test_log_poll_uses_saved_time_and_merges_new_lines(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "A\nB"
    test_setup = docker_manager_factory(state, AppConfig(log_tail=25))
    test_setup.docker_manager._next_container_refresh_at = 100.0
    test_setup.docker_manager._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(docker_manager_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()
    request = test_setup.background_executor.requests[0]
    assert request.arguments == ("container-1", "all", 150)
    assert test_setup.background_executor.finish_request(result="B\nC")

    assert state.tab_content_cache[selected_tab_key] == "A\nB\nC"
    assert test_setup.docker_manager._log_cursor_by_container_id["container-1"] == 200


def test_first_log_poll_can_clear_stale_cached_text(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "stale"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(docker_manager_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.finish_request(result="")
    assert state.tab_content_cache[selected_tab_key] == ""


def test_empty_incremental_log_poll_keeps_cached_text_and_advances_time(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "existing"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    test_setup.docker_manager._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(docker_manager_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert not test_setup.background_executor.finish_request(result="")
    assert state.tab_content_cache[selected_tab_key] == "existing"
    assert test_setup.docker_manager._log_cursor_by_container_id["container-1"] == 200


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
def test_failed_log_poll_keeps_previous_time(
    error: Exception,
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "existing"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    test_setup.docker_manager._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(docker_manager_module.time, "time", lambda: 200.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.finish_request(exception=error)
    assert state.status_message.startswith("Log fetch failed:")
    assert test_setup.docker_manager._log_cursor_by_container_id["container-1"] == 150


def test_unreadable_log_poll_stops_future_requests(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "existing"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.finish_request(
        exception=LogsUnavailableError("none")
    )
    assert "container-1" in state.unreadable_log_container_ids


def test_successful_log_poll_clears_previous_failure_status(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "existing"
    state.status_message = "Log fetch failed: timeout"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager._next_container_refresh_at = 100.0
    test_setup.docker_manager._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.finish_request(result="")
    assert state.status_message == "Loaded Logs"


def test_hidden_container_log_update_changes_cache_without_redraw(
    docker_manager_factory,
    session_state_factory,
    completed_future_factory,
) -> None:
    state = session_state_factory("visible")
    docker_manager = docker_manager_factory(state).docker_manager
    completed_request = completed_future_factory("line")
    docker_manager._log_poll_future = completed_request

    assert not docker_manager._apply_log_poll_result(
        "hidden",
        True,
        200,
        completed_request,
    )
    assert state.tab_content_cache[ContainerTabKey("hidden", TabName.LOGS)] == "line"


def test_container_sort_keeps_selection_and_can_restore_docker_order(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_containers=[
            container_summary_factory("z", name="Zulu"),
            container_summary_factory("a", name="alpha"),
        ],
        selected_container_index=0,
        container_sort_field=ContainerSortField.NAME,
    )
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.apply_container_sort_to_current_list()
    assert [item.container_id for item in state.running_containers] == ["a", "z"]
    assert state.selected_container_id == "z"

    state.container_sort_field = ContainerSortField.DOCKER_ORDER
    test_setup.docker_manager.apply_container_sort_to_current_list()
    assert [item.container_id for item in state.running_containers] == ["z", "a"]


def test_log_poll_reset_cancels_queued_work_and_removes_stopped_tracking(
    docker_manager_factory,
) -> None:
    docker_manager = docker_manager_factory().docker_manager
    queued_log_request = Future()
    docker_manager._log_poll_future = queued_log_request
    docker_manager._next_log_poll_at = 20.0
    docker_manager._log_cursor_by_container_id = {"live": 10, "old": 20}

    docker_manager._reset_log_polling_after_selection_change()
    docker_manager._remove_log_cursors_for_stopped_containers({"live"})

    assert queued_log_request.cancelled()
    assert docker_manager._log_poll_future is None
    assert docker_manager._next_log_poll_at == 0.0
    assert docker_manager._log_cursor_by_container_id == {"live": 10}


def test_worker_log_load_applies_line_and_character_limits(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = docker_manager_factory(
        state,
        AppConfig(max_log_lines=2, max_log_line_chars=32),
    )
    test_setup.docker_container_client.get_container_logs.return_value = (
        f"old\n{'x' * 100}\nnew"
    )

    trimmed_logs = test_setup.docker_manager._fetch_log_poll_content(
        "container-1",
        "all",
        10,
    )

    test_setup.docker_container_client.get_container_logs.assert_called_once_with(
        "container-1",
        "all",
        10,
    )
    assert trimmed_logs.splitlines()[-1] == "new"
    assert "old" not in trimmed_logs


def test_combining_log_content_handles_empty_and_duplicate_batches() -> None:
    combine_log_content = DockerManager._combine_existing_and_new_log_content
    assert combine_log_content("", "A") == "A"
    assert combine_log_content("A", "") == "A"
    assert combine_log_content("A\nB", "A\nB") == "A\nB"
