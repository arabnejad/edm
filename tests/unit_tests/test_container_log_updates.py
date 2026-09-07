from __future__ import annotations

from concurrent.futures import Future

import pytest

from easy_docker_manager.app import (
    container_log_updates as container_log_updates_module,
)
from easy_docker_manager.app import docker_manager as docker_manager_module
from easy_docker_manager.app.container_log_updates import ContainerLogUpdater
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_list import ContainerList
from easy_docker_manager.core.tabs import (
    ContainerTabKey,
    TabName,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerLogsUnavailableError,
    DockerRequestFailedError,
    FailedDockerRequestType,
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
    test_setup.container_log_updater._log_cursor_by_container_id["container-1"] = 150
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.complete_submission(result="")
    assert state.status_message == "Loaded Logs"
    assert selected_tab_key not in state.tab_content_error_messages
    assert state.tab_content_cache[selected_tab_key] == ""


def test_hidden_container_log_update_changes_cache_without_redraw(
    docker_manager_factory,
    container_summary_factory,
    completed_future_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
            [
                container_summary_factory("visible"),
                container_summary_factory("hidden"),
            ]
        ),
        selected_container_index=0,
    )
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


def test_log_poll_reset_cancels_queued_work_and_removes_non_running_tracking(
    docker_manager_factory,
) -> None:
    container_log_updater = docker_manager_factory().container_log_updater
    queued_log_request = Future()
    container_log_updater._log_poll_future = queued_log_request
    container_log_updater._next_log_poll_at = 20.0
    container_log_updater._log_cursor_by_container_id = {"live": 10, "old": 20}

    container_log_updater.reset_after_selection_change()
    container_log_updater.remove_log_cursors_for_non_running_containers({"live"})

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
