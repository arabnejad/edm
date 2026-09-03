from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import Mock

import pytest

from easy_docker_manager.app import (
    container_log_updates as container_log_updates_module,
)
from easy_docker_manager.app import docker_manager as docker_manager_module
from easy_docker_manager.app import (
    running_container_refresh as container_refresh_module,
)
from easy_docker_manager.app import selected_tab_load as selected_tab_load_module
from easy_docker_manager.app.container_lifecycle_action_runner import (
    ContainerLifecycleActionRunner,
)
from easy_docker_manager.app.container_log_updates import ContainerLogUpdater
from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.app.running_container_refresh import (
    RunningContainerListRefresher,
)
from easy_docker_manager.app.selected_tab_load import SelectedTabContentLoader
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_actions import ContainerLifecycleAction
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.running_container_list import RunningContainerList
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerLogsUnavailableError,
    DockerContainerClient,
    DockerRequestFailedError,
    FailedDockerRequestType,
    RunningContainerListRefreshError,
)
from easy_docker_manager.tabs.tab_data_loader import ContainerTabTextLoader


@dataclass
class RecordedBackgroundSubmission:
    """Store one worker request so a test can finish it later."""

    fn: Callable[..., Any]
    arguments: tuple[Any, ...]
    completion_callback: Callable[[Future], bool]
    future: Future


class RecordingBackgroundExecutor:
    """Record submitted work without starting worker threads."""

    def __init__(self) -> None:
        self.requests: list[RecordedBackgroundSubmission] = []

    def submit(
        self,
        fn: Callable[..., Any],
        *arguments: Any,
        on_complete: Callable[[Future], bool],
    ) -> Future:
        future: Future = Future()
        self.requests.append(
            RecordedBackgroundSubmission(
                fn=fn,
                arguments=arguments,
                completion_callback=on_complete,
                future=future,
            )
        )
        return future

    def complete_submission(
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
    running_container_list_refresher: RunningContainerListRefresher
    selected_tab_content_loader: SelectedTabContentLoader
    container_log_updater: ContainerLogUpdater
    container_lifecycle_action_runner: ContainerLifecycleActionRunner
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
        tab_data_loader = Mock(spec=ContainerTabTextLoader)
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
            running_container_list_refresher=(
                docker_manager.running_container_list_refresher
            ),
            selected_tab_content_loader=docker_manager.selected_tab_content_loader,
            container_log_updater=docker_manager.container_log_updater,
            container_lifecycle_action_runner=(
                docker_manager.container_lifecycle_action_runner
            ),
            state=selected_state,
            background_executor=background_executor,
            tab_data_loader=tab_data_loader,
            docker_container_client=docker_container_client,
        )

    return create_docker_manager


def test_scheduled_container_refresh_is_submitted_once(
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
    assert test_setup.running_container_list_refresher._next_refresh_at == 12.0


def test_context_change_discards_all_active_docker_work(
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    active_futures = [Future(), Future(), Future()]
    test_setup.running_container_list_refresher._refresh_future = active_futures[0]
    test_setup.selected_tab_content_loader._tab_load_future = active_futures[1]
    test_setup.container_log_updater._log_poll_future = active_futures[2]
    test_setup.container_log_updater._log_cursor_by_container_id["old"] = 100

    test_setup.docker_manager.reset_after_docker_context_change()

    assert all(future.cancelled() for future in active_futures)
    assert test_setup.running_container_list_refresher._refresh_future is None
    assert test_setup.selected_tab_content_loader._tab_load_future is None
    assert test_setup.container_log_updater._log_poll_future is None
    assert test_setup.container_log_updater._log_cursor_by_container_id == {}


@pytest.mark.parametrize(
    "tab_name",
    [TabName.ENV, TabName.CONFIG, TabName.STATS, TabName.TOP],
)
def test_visible_periodically_refreshed_tab_is_reloaded_on_its_interval(
    tab_name: TabName,
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=tab_name)
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "OLD=value"
    test_setup = docker_manager_factory(
        state,
        AppConfig(tab_refresh_interval=3.0),
    )
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(selected_tab_load_module.time, "monotonic", lambda: 10.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    request = test_setup.background_executor.requests[0]
    assert request.fn == test_setup.tab_data_loader.load_tab_text
    assert request.arguments == ("container-1", tab_name)
    assert test_setup.selected_tab_content_loader._next_tab_refresh_at == 13.0


def test_loaded_readable_logs_are_polled_after_the_interval(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "initial"
    test_setup = docker_manager_factory(state)
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(container_log_updates_module.time, "time", lambda: 50.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    request = test_setup.background_executor.requests[0]
    assert request.fn == test_setup.container_log_updater._fetch_log_poll_content
    assert request.arguments == ("container-1", 100, None)
    assert test_setup.container_log_updater._next_log_poll_at == 11.0


def test_unreadable_logs_are_not_polled(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.unreadable_log_container_ids.add("container-1")
    test_setup = docker_manager_factory(state)
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.requests == []


def test_next_request_check_uses_nearest_deadline_and_idle_delay(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.TOP)
    test_setup = docker_manager_factory(state)
    docker_manager = test_setup.docker_manager
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    test_setup.selected_tab_content_loader._next_tab_refresh_at = 8.5
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 5.0)

    assert docker_manager.get_next_docker_data_refresh_delay() == 3.5

    test_setup.selected_tab_content_loader._tab_load_future = Future()
    test_setup.running_container_list_refresher._refresh_future = Future()
    assert docker_manager.get_next_docker_data_refresh_delay() == 1.0


def test_late_request_check_uses_small_positive_delay(
    monkeypatch,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    docker_manager = test_setup.docker_manager
    test_setup.running_container_list_refresher._next_refresh_at = 4.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 5.0)
    assert docker_manager.get_next_docker_data_refresh_delay() == 0.05


def test_container_refresh_honors_deadline_and_force(
    monkeypatch,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.running_container_list_refresher._next_refresh_at = 20.0
    monkeypatch.setattr(container_refresh_module.time, "monotonic", lambda: 10.0)

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

    assert test_setup.background_executor.complete_submission(result=containers)
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
        running_container_list=RunningContainerList(
            [
                container_summary_factory("one"),
                container_summary_factory("two"),
            ]
        ),
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

    assert test_setup.background_executor.complete_submission(result=refreshed)
    assert [
        item.container_id for item in state.running_container_list.displayed_containers
    ] == [
        "three",
        "two",
    ]
    assert state.selected_container_id == "two"


def test_unchanged_refresh_clears_explicit_error_state(
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.container_list_refresh_error_message = "Container refresh failed: offline"
    state.status_message = "A different status message"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(
        result=list(state.running_container_list.displayed_containers)
    )
    assert state.status_message == "1 running containers"
    assert state.container_list_refresh_error_message is None


def test_repeated_empty_refresh_does_not_redraw_twice(docker_manager_factory) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_running_container_list_refresh(force=True)
    assert test_setup.background_executor.complete_submission(result=[])
    assert test_setup.state.status_message == "No running containers."

    test_setup.docker_manager.start_running_container_list_refresh(force=True)
    assert not test_setup.background_executor.complete_submission(result=[])


@pytest.mark.parametrize(
    "error",
    [RunningContainerListRefreshError("offline"), RuntimeError("unexpected")],
)
def test_refresh_failure_keeps_existing_containers_and_shows_error(
    error: Exception,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(exception=error)
    assert state.running_container_list.displayed_containers
    assert state.status_message == f"Container refresh failed: {error}"
    assert (
        state.container_list_refresh_error_message
        == f"Container refresh failed: {error}"
    )


def test_replaced_refresh_completion_is_ignored(
    docker_manager_factory,
    completed_future_factory,
) -> None:
    container_list_refresher = docker_manager_factory().running_container_list_refresher
    assert not container_list_refresher._apply_running_container_list_refresh_result(
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
        running_container_list=RunningContainerList(
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
        running_container_list=RunningContainerList(
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


def test_log_poll_uses_saved_time_and_merges_new_lines(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "A\nB"
    test_setup = docker_manager_factory(state, AppConfig(initial_log_tail_lines=25))
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    test_setup.container_log_updater._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(container_log_updates_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()
    request = test_setup.background_executor.requests[0]
    assert request.arguments == ("container-1", "all", 150)
    assert test_setup.background_executor.complete_submission(result="B\nC")

    assert state.tab_content_cache[selected_tab_key] == "A\nB\nC"
    assert (
        test_setup.container_log_updater._log_cursor_by_container_id["container-1"]
        == 200
    )


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
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(container_log_updates_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.complete_submission(result="")
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
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    test_setup.container_log_updater._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(container_log_updates_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert not test_setup.background_executor.complete_submission(result="")
    assert state.tab_content_cache[selected_tab_key] == "existing"
    assert (
        test_setup.container_log_updater._log_cursor_by_container_id["container-1"]
        == 200
    )


def test_merged_incremental_logs_are_limited_before_caching(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_cache[selected_tab_key] = "oldest\nexisting"
    test_setup = docker_manager_factory(
        state,
        AppConfig(max_log_lines=2, max_log_line_chars=32),
    )
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    test_setup.container_log_updater._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(container_log_updates_module.time, "time", lambda: 200.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.complete_submission(
        result="incoming-1\nincoming-2"
    )
    assert state.tab_content_cache[selected_tab_key] == "incoming-1\nincoming-2"


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
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    test_setup.container_log_updater._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(container_log_updates_module.time, "time", lambda: 200.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.complete_submission(exception=error)
    assert selected_tab_key not in state.tab_content_cache
    assert selected_tab_key in state.tab_content_error_messages
    assert state.tab_content_error_messages[selected_tab_key] == state.status_message
    assert (
        test_setup.container_log_updater._log_cursor_by_container_id["container-1"]
        == 150
    )


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
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.complete_submission(
        exception=ContainerLogsUnavailableError("none")
    )
    assert "container-1" in state.unreadable_log_container_ids
    assert selected_tab_key not in state.tab_content_cache
    assert selected_tab_key in state.tab_content_error_messages


def test_successful_log_poll_clears_previous_failure_status(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    selected_tab_key = state.selected_container_tab_key
    assert selected_tab_key is not None
    state.tab_content_error_messages[selected_tab_key] = "Log fetch failed: timeout"
    state.status_message = "A different status message"
    test_setup = docker_manager_factory(state)
    test_setup.running_container_list_refresher._next_refresh_at = 100.0
    test_setup.container_log_updater._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.complete_submission(result="")
    assert state.status_message == "Loaded Logs"
    assert selected_tab_key not in state.tab_content_error_messages
    assert state.tab_content_cache[selected_tab_key] == ""


def test_hidden_container_log_update_changes_cache_without_redraw(
    docker_manager_factory,
    session_state_factory,
    completed_future_factory,
) -> None:
    state = session_state_factory("visible")
    container_log_updater = docker_manager_factory(state).container_log_updater
    completed_request = completed_future_factory("line")
    container_log_updater._log_poll_future = completed_request

    assert not container_log_updater._apply_log_poll_result(
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
        running_container_list=RunningContainerList(
            [
                container_summary_factory("z", name="Zulu"),
                container_summary_factory("a", name="alpha"),
            ]
        ),
        selected_container_index=0,
        container_sort_field=ContainerSortField.NAME,
    )
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.rebuild_displayed_container_list()
    assert [
        item.container_id for item in state.running_container_list.displayed_containers
    ] == ["a", "z"]
    assert state.selected_container_id == "z"

    state.container_sort_field = ContainerSortField.DOCKER_ORDER
    test_setup.docker_manager.rebuild_displayed_container_list()
    assert [
        item.container_id for item in state.running_container_list.displayed_containers
    ] == ["z", "a"]


def test_compose_grouping_keeps_the_same_container_selected(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_container_list=RunningContainerList(
            [
                container_summary_factory("standalone", name="agent"),
                container_summary_factory(
                    "compose-web",
                    name="web",
                    compose_project_name="example",
                ),
            ]
        ),
        selected_container_index=0,
    )
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.rebuild_displayed_container_list()

    assert [
        container.container_id
        for container in state.running_container_list.displayed_containers
    ] == ["compose-web", "standalone"]
    assert state.selected_container_id == "standalone"


def test_container_filter_keeps_matching_containers_in_the_selected_sort_order(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_container_list=RunningContainerList(
            [
                container_summary_factory(
                    "worker",
                    name="Zulu worker",
                    image_name="redis:7",
                ),
                container_summary_factory(
                    "web",
                    name="Alpha web",
                    image_name="python:3.12",
                ),
                container_summary_factory(
                    "cache",
                    name="Beta cache",
                    image_name="redis:6",
                ),
            ]
        ),
        selected_container_index=1,
        container_filter_query="REDIS",
        container_sort_field=ContainerSortField.NAME,
    )
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.rebuild_displayed_container_list()

    assert [
        container.container_id
        for container in state.running_container_list.displayed_containers
    ] == [
        "cache",
        "worker",
    ]
    assert state.running_container_list.unfiltered_container_count == 3
    assert state.selected_container_id == "cache"


def test_container_filter_with_no_matches_clears_selection_and_updates_status(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_container_list=RunningContainerList([container_summary_factory("web")]),
        selected_container_index=0,
        container_filter_query="missing",
    )
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.rebuild_displayed_container_list()

    assert state.running_container_list.displayed_containers == []
    assert state.selected_container_index is None
    assert state.status_message == "No running containers match the filter."


def test_container_refresh_reapplies_filter_without_removing_hidden_container_data(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(container_filter_query="redis")
    hidden_container_tab_key = ContainerTabKey("web", TabName.LOGS)
    state.tab_content_cache[hidden_container_tab_key] = "saved logs"
    test_setup = docker_manager_factory(state)
    refreshed_containers = [
        container_summary_factory("web", image_name="python:3.12"),
        container_summary_factory("cache", image_name="redis:7"),
    ]
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(
        result=refreshed_containers
    )
    assert [
        container.container_id
        for container in state.running_container_list.displayed_containers
    ] == ["cache"]
    assert state.running_container_list.unfiltered_container_count == 2
    assert hidden_container_tab_key in state.tab_content_cache


def test_first_refresh_with_no_filter_matches_replaces_loading_status(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(container_filter_query="redis")
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_running_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(
        result=[container_summary_factory("web", image_name="python:3.12")]
    )
    assert state.running_container_list.displayed_containers == []
    assert state.selected_container_index is None
    assert state.status_message == "No running containers match the filter."


def test_log_poll_reset_cancels_queued_work_and_removes_stopped_tracking(
    docker_manager_factory,
) -> None:
    container_log_updater = docker_manager_factory().container_log_updater
    queued_log_request = Future()
    container_log_updater._log_poll_future = queued_log_request
    container_log_updater._next_log_poll_at = 20.0
    container_log_updater._log_cursor_by_container_id = {"live": 10, "old": 20}

    container_log_updater.reset_after_selection_change()
    container_log_updater.remove_log_cursors_for_stopped_containers({"live"})

    assert queued_log_request.cancelled()
    assert container_log_updater._log_poll_future is None
    assert container_log_updater._next_log_poll_at == 0.0
    assert container_log_updater._log_cursor_by_container_id == {"live": 10}


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

    trimmed_logs = test_setup.container_log_updater._fetch_log_poll_content(
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
    combine_log_content = ContainerLogUpdater._combine_existing_and_new_log_content
    assert combine_log_content("", "A") == "A"
    assert combine_log_content("A", "") == "A"
    assert combine_log_content("A\nB", "A\nB") == "A\nB"


@pytest.mark.parametrize(
    (
        "action",
        "docker_client_method_name",
        "progress_message",
        "completed_message",
    ),
    [
        (
            ContainerLifecycleAction.STOP,
            "stop_container",
            'Stopping container "web"...',
            'Container "web" stopped. Refreshing containers...',
        ),
        (
            ContainerLifecycleAction.RESTART,
            "restart_container",
            'Restarting container "web"...',
            'Container "web" restarted. Refreshing containers...',
        ),
    ],
)
def test_container_lifecycle_action_runs_once_and_refreshes_after_success(
    action: ContainerLifecycleAction,
    docker_client_method_name: str,
    progress_message: str,
    completed_message: str,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()

    assert test_setup.docker_manager.start_container_lifecycle_action(
        action,
        "container-1",
        "web",
    )
    assert not test_setup.docker_manager.start_container_lifecycle_action(
        ContainerLifecycleAction.STOP,
        "container-1",
        "web",
    )
    assert test_setup.docker_manager.is_container_lifecycle_action_in_progress
    action_request = test_setup.background_executor.requests[0]
    assert action_request.fn == getattr(
        test_setup.docker_container_client,
        docker_client_method_name,
    )
    assert action_request.arguments == ("container-1",)
    assert test_setup.state.status_message == progress_message

    assert test_setup.background_executor.complete_submission(result=None)
    assert not test_setup.docker_manager.is_container_lifecycle_action_in_progress
    assert test_setup.state.status_message == completed_message
    refresh_request = test_setup.background_executor.requests[1]
    assert refresh_request.fn == (
        test_setup.docker_container_client.list_running_containers
    )


def test_failed_container_lifecycle_action_shows_error_without_refreshing(
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_container_lifecycle_action(
        ContainerLifecycleAction.STOP,
        "container-1",
        "worker",
    )

    assert test_setup.background_executor.complete_submission(
        exception=RuntimeError("permission denied")
    )
    assert test_setup.state.status_message == (
        'Could not stop container "worker": permission denied'
    )
    assert len(test_setup.background_executor.requests) == 1


def test_action_completion_reloads_after_an_older_refresh_finishes(
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_running_container_list_refresh(force=True)
    test_setup.docker_manager.start_container_lifecycle_action(
        ContainerLifecycleAction.STOP,
        "container-1",
        "web",
    )

    assert test_setup.background_executor.complete_submission(1, result=None)
    assert len(test_setup.background_executor.requests) == 2

    assert test_setup.background_executor.complete_submission(0, result=[])
    assert len(test_setup.background_executor.requests) == 3
    follow_up_refresh = test_setup.background_executor.requests[2]
    assert follow_up_refresh.fn == (
        test_setup.docker_container_client.list_running_containers
    )
