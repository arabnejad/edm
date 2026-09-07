from __future__ import annotations

from concurrent.futures import Future

import pytest

from easy_docker_manager.app import (
    container_log_updates as container_log_updates_module,
)
from easy_docker_manager.app import docker_manager as docker_manager_module
from easy_docker_manager.app import selected_tab_load as selected_tab_load_module
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_list import ContainerList
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.containers import ContainerListViewMode
from easy_docker_manager.core.tabs import (
    CONTAINER_NOT_RUNNING_MESSAGE,
    TabName,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState


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
    assert request.fn == test_setup.docker_container_client.list_containers
    assert request.arguments == ()
    assert test_setup.container_list_refresher._next_refresh_at == 12.0


def test_context_change_discards_all_active_docker_work(
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    active_futures = [Future(), Future(), Future()]
    test_setup.container_list_refresher._refresh_future = active_futures[0]
    test_setup.selected_tab_content_loader._tab_load_future = active_futures[1]
    test_setup.container_log_updater._log_poll_future = active_futures[2]
    test_setup.container_log_updater._log_cursor_by_container_id["old"] = 100

    test_setup.docker_manager.reset_after_docker_context_change()

    assert all(future.cancelled() for future in active_futures)
    assert test_setup.container_list_refresher._refresh_future is None
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
        AppConfig(detail_tab_refresh_interval_seconds=3.0),
    )
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
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
    test_setup.container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)

    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert test_setup.background_executor.requests == []


def test_stopped_container_logs_load_once_without_starting_live_polling(
    monkeypatch,
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
            [container_summary_factory("stopped", status="exited")]
        ),
        container_list_view_mode=ContainerListViewMode.ALL,
        selected_container_index=0,
    )
    state.container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )
    test_setup = docker_manager_factory(state)

    assert test_setup.docker_manager.load_selected_tab_content_if_needed()
    initial_log_request = test_setup.background_executor.requests[0]
    assert initial_log_request.arguments == ("stopped", TabName.LOGS)
    assert test_setup.background_executor.complete_submission(result="final log")
    assert test_setup.container_log_updater._log_cursor_by_container_id == {}

    test_setup.container_list_refresher._next_refresh_at = 100.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 10.0)
    test_setup.docker_manager.refresh_docker_data_if_needed()

    assert len(test_setup.background_executor.requests) == 1
    assert (
        test_setup.container_log_updater.get_next_poll_time(
            initial_log_load_in_progress=False
        )
        is None
    )


@pytest.mark.parametrize("tab_name", [TabName.STATS, TabName.TOP])
def test_stopped_container_live_tab_shows_message_without_worker_request(
    tab_name: TabName,
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
            [container_summary_factory("stopped", status="exited")]
        ),
        container_list_view_mode=ContainerListViewMode.ALL,
        selected_container_index=0,
        active_detail_tab_name=tab_name,
    )
    state.container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )
    test_setup = docker_manager_factory(state)

    assert test_setup.docker_manager.load_selected_tab_content_if_needed()

    assert test_setup.background_executor.requests == []
    assert state.tab_content_cache[state.selected_container_tab_key] == (
        CONTAINER_NOT_RUNNING_MESSAGE
    )
    assert state.status_message == f"Loaded {tab_name.value}"


def test_next_request_check_uses_nearest_deadline_and_idle_delay(
    monkeypatch,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.TOP)
    test_setup = docker_manager_factory(state)
    docker_manager = test_setup.docker_manager
    test_setup.container_list_refresher._next_refresh_at = 100.0
    test_setup.selected_tab_content_loader._next_tab_refresh_at = 8.5
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 5.0)

    assert docker_manager.get_next_docker_data_refresh_delay() == 3.5

    test_setup.selected_tab_content_loader._tab_load_future = Future()
    test_setup.container_list_refresher._refresh_future = Future()
    assert docker_manager.get_next_docker_data_refresh_delay() == 1.0


def test_late_request_check_uses_small_positive_delay(
    monkeypatch,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    docker_manager = test_setup.docker_manager
    test_setup.container_list_refresher._next_refresh_at = 4.0
    monkeypatch.setattr(docker_manager_module.time, "monotonic", lambda: 5.0)
    assert docker_manager.get_next_docker_data_refresh_delay() == 0.05
