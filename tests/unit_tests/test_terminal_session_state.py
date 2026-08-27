from __future__ import annotations

from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.tab_export import TabExportMenuState
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)


def test_state_defaults_describe_the_initial_screen() -> None:
    state = TerminalSessionState()

    assert state.running_containers == []
    assert state.selected_container_index is None
    assert state.active_detail_tab_name == TabName.LOGS
    assert state.active_focus_area == FocusArea.CONTAINERS
    assert state.status_message == "Loading containers..."
    assert state.container_sort_field == ContainerSortField.DOCKER_ORDER
    assert not state.container_sort_descending
    assert state.container_sort_menu_state is None
    assert state.tab_export_menu_state is None


def test_selected_container_properties_require_a_valid_index(
    container_summary_factory,
) -> None:
    state = TerminalSessionState(running_containers=[container_summary_factory()])

    assert state.selected_container_summary is None
    assert state.selected_container_id is None
    assert state.selected_container_tab_key is None

    state.selected_container_index = 0
    assert state.selected_container_id == "container-1"
    assert state.selected_container_tab_key == ContainerTabKey(
        container_id="container-1",
        tab_name=TabName.LOGS,
    )

    state.selected_container_index = 4
    assert state.selected_container_summary is None


def test_find_running_container_index_returns_matching_position(
    container_summary_factory,
) -> None:
    state = TerminalSessionState(
        running_containers=[
            container_summary_factory("one"),
            container_summary_factory("two"),
        ]
    )

    assert state.find_running_container_index("two") == 1
    assert state.find_running_container_index("missing") is None
    assert state.find_running_container_index(None) is None


def test_selected_detail_line_is_kept_within_available_range() -> None:
    state = TerminalSessionState(detail_selected_line_index=10)
    state.keep_selected_detail_line_within_available_range(3)
    assert state.detail_selected_line_index == 2

    state.detail_selected_line_index = -5
    state.keep_selected_detail_line_within_available_range(3)
    assert state.detail_selected_line_index == 0

    state.detail_selected_line_index = 2
    state.keep_selected_detail_line_within_available_range(0)
    assert state.detail_selected_line_index == 0


def test_remove_stopped_container_state_removes_all_stopped_container_data() -> None:
    state = TerminalSessionState()
    live_container_tab_key = ContainerTabKey("live", TabName.LOGS)
    stopped_container_tab_key = ContainerTabKey("stopped", TabName.ENV)
    state.tab_content_cache[live_container_tab_key] = "live"
    state.tab_content_cache[stopped_container_tab_key] = "stopped"
    state.tab_search_queries = {
        live_container_tab_key: "ok",
        stopped_container_tab_key: "old",
    }
    state.unreadable_log_container_ids = {"live", "stopped"}
    state.tab_load_errors = {
        live_container_tab_key: "live error",
        stopped_container_tab_key: "old error",
    }
    state.tab_export_menu_state = TabExportMenuState(
        stopped_container_tab_key,
        "stopped",
        "output.txt",
        len("output.txt"),
    )

    state.remove_stopped_container_state({"live"})

    assert live_container_tab_key in state.tab_content_cache
    assert stopped_container_tab_key not in state.tab_content_cache
    assert state.tab_search_queries == {live_container_tab_key: "ok"}
    assert state.unreadable_log_container_ids == {"live"}
    assert state.tab_load_errors == {live_container_tab_key: "live error"}
    assert state.tab_export_menu_state is None
