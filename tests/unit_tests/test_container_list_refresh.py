from __future__ import annotations

import pytest

from easy_docker_manager.app import (
    container_list_refresh as container_refresh_module,
)
from easy_docker_manager.core.container_list import ContainerList
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.containers import ContainerListViewMode
from easy_docker_manager.core.tabs import (
    CONTAINER_NOT_RUNNING_MESSAGE,
    ContainerTabKey,
    TabName,
)
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.docker.container_client import (
    ContainerListRefreshError,
)


def test_container_refresh_honors_deadline_and_force(
    monkeypatch,
    docker_manager_factory,
) -> None:
    test_setup = docker_manager_factory()
    test_setup.container_list_refresher._next_refresh_at = 20.0
    monkeypatch.setattr(container_refresh_module.time, "monotonic", lambda: 10.0)

    assert not test_setup.docker_manager.start_container_list_refresh()
    assert test_setup.docker_manager.start_container_list_refresh(force=True)
    assert not test_setup.docker_manager.start_container_list_refresh(force=True)
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
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(result=containers)
    assert test_setup.state.selected_container_id == "one"
    assert test_setup.state.status_message == "Loading Logs..."
    assert len(test_setup.background_executor.requests) == 2
    assert test_setup.background_executor.requests[1].arguments == (
        "one",
        TabName.LOGS,
    )


def test_all_containers_view_includes_stopped_containers(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(container_list_view_mode=ContainerListViewMode.ALL)
    test_setup = docker_manager_factory(state)
    containers = [
        container_summary_factory("running"),
        container_summary_factory("stopped", status="exited"),
    ]
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(result=containers)

    assert [
        container.container_id
        for container in state.container_list.displayed_containers
    ] == ["running", "stopped"]
    assert state.status_message == "Loading Logs..."


def test_selected_container_stopping_reloads_its_final_logs(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    running_container = container_summary_factory("container-1")
    state = TerminalSessionState(
        container_list=ContainerList([running_container]),
        container_list_view_mode=ContainerListViewMode.ALL,
        selected_container_index=0,
    )
    logs_key = ContainerTabKey("container-1", TabName.LOGS)
    state.tab_content_cache[logs_key] = "old logs"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_container_list_refresh(force=True)

    stopped_container = container_summary_factory("container-1", status="exited")
    assert test_setup.background_executor.complete_submission(
        result=[stopped_container]
    )

    log_request = test_setup.background_executor.requests[1]
    assert log_request.arguments == ("container-1", TabName.LOGS)


@pytest.mark.parametrize("unavailable_tab", [TabName.STATS, TabName.TOP])
def test_status_change_clears_all_cached_tabs_and_reloads_the_visible_tab(
    unavailable_tab: TabName,
    docker_manager_factory,
    session_state_factory,
    container_summary_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    state.container_list_view_mode = ContainerListViewMode.ALL
    state.container_list.replace_all_containers(
        [container_summary_factory(), container_summary_factory("other")]
    )
    state.container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )
    for tab_name in TabName:
        state.tab_content_cache[ContainerTabKey("container-1", tab_name)] = (
            "details from before the container stopped"
        )
    retained_logs_key = ContainerTabKey("other", TabName.LOGS)
    state.tab_content_cache[retained_logs_key] = "other container logs"
    logs_key = ContainerTabKey("container-1", TabName.LOGS)
    state.tab_search_queries[logs_key] = "shutdown"
    state.unreadable_log_container_ids.add("container-1")
    state.tab_content_error_messages[logs_key] = "old error"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_container_list_refresh(force=True)

    test_setup.background_executor.complete_submission(
        result=[
            container_summary_factory(status="exited"),
            container_summary_factory("other"),
        ]
    )
    assert all(
        ContainerTabKey("container-1", tab_name) not in state.tab_content_cache
        for tab_name in TabName
    )
    assert state.tab_content_cache[retained_logs_key] == "other container logs"
    assert state.tab_content_error_messages == {}
    assert state.tab_search_queries[logs_key] == "shutdown"
    assert state.unreadable_log_container_ids == {"container-1"}
    assert test_setup.background_executor.requests[-1].arguments == (
        "container-1",
        TabName.ENV,
    )

    test_setup.background_executor.complete_submission(result="ENV=value")
    state.active_detail_tab_name = unavailable_tab
    request_count = len(test_setup.background_executor.requests)
    test_setup.docker_manager.prepare_active_detail_tab()

    unavailable_tab_key = ContainerTabKey("container-1", unavailable_tab)
    assert state.tab_content_cache[unavailable_tab_key] == (
        CONTAINER_NOT_RUNNING_MESSAGE
    )
    assert len(test_setup.background_executor.requests) == request_count


def test_stopped_container_that_was_never_selected_loads_environment_on_demand(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    initially_selected = container_summary_factory("selected", name="selected")
    later_selected = container_summary_factory("later", name="later")
    state = TerminalSessionState(
        container_list=ContainerList([initially_selected, later_selected]),
        container_list_view_mode=ContainerListViewMode.ALL,
        selected_container_index=0,
        active_detail_tab_name=TabName.ENV,
    )
    state.container_list.rebuild_displayed_containers(
        ContainerListViewMode.ALL,
        ContainerSortField.DOCKER_ORDER,
        False,
        "",
    )
    state.tab_content_cache[ContainerTabKey("selected", TabName.ENV)] = "SELECTED=1"
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_container_list_refresh(force=True)

    test_setup.background_executor.complete_submission(
        result=[
            initially_selected,
            container_summary_factory("later", name="later", status="exited"),
        ]
    )
    assert len(test_setup.background_executor.requests) == 1

    state.selected_container_index = state.find_container_index("later")
    test_setup.docker_manager.prepare_selected_container_details()

    assert test_setup.background_executor.requests[-1].arguments == (
        "later",
        TabName.ENV,
    )
    test_setup.background_executor.complete_submission(result="STOPPED_CONTAINER=1")
    assert state.tab_content_cache[ContainerTabKey("later", TabName.ENV)] == (
        "STOPPED_CONTAINER=1"
    )


def test_tab_load_started_before_stop_is_discarded_before_final_logs_load(
    docker_manager_factory,
    session_state_factory,
    container_summary_factory,
) -> None:
    state = session_state_factory()
    state.container_list_view_mode = ContainerListViewMode.ALL
    logs_key = state.selected_container_tab_key
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.load_selected_tab_content_if_needed()
    test_setup.background_executor.requests[0].future.set_running_or_notify_cancel()

    test_setup.docker_manager.start_container_list_refresh(force=True)
    test_setup.background_executor.complete_submission(
        result=[container_summary_factory(status="exited")]
    )
    test_setup.background_executor.complete_submission(0, result="logs before stop")

    assert logs_key not in state.tab_content_cache
    assert test_setup.background_executor.requests[-1].arguments == (
        "container-1",
        TabName.LOGS,
    )
    test_setup.background_executor.complete_submission(result="final shutdown logs")
    assert state.tab_content_cache[logs_key] == "final shutdown logs"


def test_late_log_poll_cannot_change_final_stopped_container_logs(
    docker_manager_factory,
    session_state_factory,
    container_summary_factory,
) -> None:
    state = session_state_factory()
    state.container_list_view_mode = ContainerListViewMode.ALL
    logs_key = state.selected_container_tab_key
    state.tab_content_cache[logs_key] = "old logs"
    test_setup = docker_manager_factory(state)
    test_setup.container_log_updater.record_initial_log_load_success("container-1", 100)
    test_setup.container_log_updater.poll_if_needed(
        10.0, initial_log_load_in_progress=False
    )
    test_setup.background_executor.requests[0].future.set_running_or_notify_cancel()

    test_setup.docker_manager.start_container_list_refresh(force=True)
    test_setup.background_executor.complete_submission(
        result=[container_summary_factory(status="exited")]
    )
    test_setup.background_executor.complete_submission(result="final shutdown logs")

    assert not test_setup.background_executor.complete_submission(
        0,
        result="old log batch",
    )
    assert state.tab_content_cache[logs_key] == "final shutdown logs"
    assert state.tab_content_error_messages == {}
    assert state.status_message == "Loaded Logs"
    assert test_setup.container_log_updater._log_cursor_by_container_id == {}


def test_refresh_preserves_selection_and_reapplies_active_sort(
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
        selected_container_index=1,
        container_sort_field=ContainerSortField.IMAGE,
        container_sort_descending=True,
    )
    test_setup = docker_manager_factory(state)
    refreshed = [
        container_summary_factory("two", image_name="nginx:latest"),
        container_summary_factory("three", image_name="redis:7"),
    ]
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(result=refreshed)
    assert [
        item.container_id for item in state.container_list.displayed_containers
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
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(
        result=list(state.container_list.displayed_containers)
    )
    assert state.status_message == "1 running container"
    assert state.container_list_refresh_error_message is None


def test_repeated_empty_refresh_does_not_redraw_twice(docker_manager_factory) -> None:
    test_setup = docker_manager_factory()
    test_setup.docker_manager.start_container_list_refresh(force=True)
    assert test_setup.background_executor.complete_submission(result=[])
    assert test_setup.state.status_message == "No running containers."

    test_setup.docker_manager.start_container_list_refresh(force=True)
    assert not test_setup.background_executor.complete_submission(result=[])


@pytest.mark.parametrize(
    "error",
    [ContainerListRefreshError("offline"), RuntimeError("unexpected")],
)
def test_refresh_failure_keeps_existing_containers_and_shows_error(
    error: Exception,
    docker_manager_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(exception=error)
    assert state.container_list.displayed_containers
    assert state.status_message == f"Container refresh failed: {error}"
    assert (
        state.container_list_refresh_error_message
        == f"Container refresh failed: {error}"
    )


def test_replaced_refresh_completion_is_ignored(
    docker_manager_factory,
    completed_future_factory,
) -> None:
    container_list_refresher = docker_manager_factory().container_list_refresher
    assert not container_list_refresher._apply_container_list_refresh_result(
        completed_future_factory([])
    )


def test_container_sort_keeps_selection_and_can_restore_docker_order(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
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
        item.container_id for item in state.container_list.displayed_containers
    ] == ["a", "z"]
    assert state.selected_container_id == "z"

    state.container_sort_field = ContainerSortField.DOCKER_ORDER
    test_setup.docker_manager.rebuild_displayed_container_list()
    assert [
        item.container_id for item in state.container_list.displayed_containers
    ] == ["z", "a"]


def test_compose_grouping_keeps_the_same_container_selected(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
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
        for container in state.container_list.displayed_containers
    ] == ["compose-web", "standalone"]
    assert state.selected_container_id == "standalone"


def test_container_filter_keeps_matching_containers_in_the_selected_sort_order(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList(
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
        for container in state.container_list.displayed_containers
    ] == [
        "cache",
        "worker",
    ]
    assert state.container_list.all_container_count == 3
    assert state.selected_container_id == "cache"


def test_container_filter_with_no_matches_clears_selection_and_updates_status(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        container_list=ContainerList([container_summary_factory("web")]),
        selected_container_index=0,
        container_filter_query="missing",
    )
    test_setup = docker_manager_factory(state)

    test_setup.docker_manager.rebuild_displayed_container_list()

    assert state.container_list.displayed_containers == []
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
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(
        result=refreshed_containers
    )
    assert [
        container.container_id
        for container in state.container_list.displayed_containers
    ] == ["cache"]
    assert state.container_list.all_container_count == 2
    assert hidden_container_tab_key in state.tab_content_cache


def test_first_refresh_with_no_filter_matches_replaces_loading_status(
    docker_manager_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState(container_filter_query="redis")
    test_setup = docker_manager_factory(state)
    test_setup.docker_manager.start_container_list_refresh(force=True)

    assert test_setup.background_executor.complete_submission(
        result=[container_summary_factory("web", image_name="python:3.12")]
    )
    assert state.container_list.displayed_containers == []
    assert state.selected_container_index is None
    assert state.status_message == "No running containers match the filter."
