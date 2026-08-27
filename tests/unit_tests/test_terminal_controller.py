from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.running_container_list import RunningContainerList
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.terminal_session_state import TerminalSessionState
from easy_docker_manager.tabs.tab_text_filter import TabTextFilter
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.terminal_controller import TerminalController


@dataclass
class TerminalControllerTestSetup:
    terminal_controller: TerminalController
    terminal_layout_view: Mock
    docker_manager: Mock


@pytest.fixture
def terminal_controller_factory():
    def create_controller(state: TerminalSessionState):
        terminal_layout_view = Mock()
        docker_manager = Mock()
        terminal_controller = TerminalController(
            state,
            terminal_layout_view,
            TabTextFilter(),
            DetailTabTextFormatter(),
            docker_manager,
        )
        return TerminalControllerTestSetup(
            terminal_controller=terminal_controller,
            terminal_layout_view=terminal_layout_view,
            docker_manager=docker_manager,
        )

    return create_controller


def test_active_detail_tab_display_lines_show_empty_and_error_messages(
    terminal_controller_factory,
    container_summary_factory,
) -> None:
    state = TerminalSessionState()
    test_setup = terminal_controller_factory(state)
    controller = test_setup.terminal_controller
    assert controller.get_active_detail_tab_display_lines() == [
        "Select a running container."
    ]

    state.running_container_list = RunningContainerList([container_summary_factory()])
    state.selected_container_index = 0
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    assert controller.get_active_detail_tab_display_lines() == ["Loading..."]

    state.tab_content_error_messages[container_tab_key] = "failed"
    assert controller.get_active_detail_tab_display_lines() == ["failed"]
    state.tab_content_error_messages.clear()

    for tab, message in [
        (TabName.LOGS, "No logs available."),
        (TabName.ENV, "No environment variables."),
        (TabName.CONFIG, "No container configuration."),
        (TabName.TOP, "No processes."),
    ]:
        state.active_detail_tab_name = tab
        tab_key = state.selected_container_tab_key
        assert tab_key is not None
        state.tab_content_cache[tab_key] = ""
        assert controller.get_active_detail_tab_display_lines() == [message]


def test_active_log_tab_display_lines_use_the_saved_query(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "INFO ok\nERROR failed"
    state.tab_search_queries[container_tab_key] = "ERROR"
    test_setup = terminal_controller_factory(state)

    assert test_setup.terminal_controller.get_active_detail_tab_display_lines() == [
        "ERROR failed"
    ]


def test_render_passes_lines_and_error_state_to_the_view(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.CONFIG)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_error_messages[container_tab_key] = "failed"
    test_setup = terminal_controller_factory(state)

    test_setup.terminal_controller.update_terminal_view()

    rendered_state, lines, line_markup = (
        test_setup.terminal_layout_view.render.call_args.args
    )
    assert rendered_state is state
    assert lines == ["failed"]
    assert line_markup("failed") == [("error", "failed")]


def test_cached_tab_content_stays_visible_after_refresh_error(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "VALUE=previous"
    state.tab_content_error_messages[container_tab_key] = "Error loading Env: timeout"
    test_setup = terminal_controller_factory(state)

    test_setup.terminal_controller.update_terminal_view()

    _, lines, format_detail_line = test_setup.terminal_layout_view.render.call_args.args
    assert lines == ["VALUE=previous"]
    assert format_detail_line("VALUE=previous") != [("error", "VALUE=previous")]


@pytest.mark.parametrize(
    ("navigation_key", "starting_line", "expected_line"),
    [
        ("up", 2, 1),
        ("down", 0, 1),
        ("home", 2, 0),
        ("end", 0, 3),
        ("page up", 3, 0),
        ("page down", 0, 3),
    ],
)
def test_move_selected_detail_line(
    navigation_key: str,
    starting_line: int,
    expected_line: int,
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    cache_key = state.selected_container_tab_key
    assert cache_key is not None
    state.tab_content_cache[cache_key] = "A\nB\nC\nD"
    state.detail_selected_line_index = starting_line
    test_setup = terminal_controller_factory(state)

    selection_changed = test_setup.terminal_controller.move_selected_detail_line(
        navigation_key,
        terminal_size=(80, 10),
    )

    assert selection_changed
    assert state.detail_selected_line_index == expected_line
    test_setup.terminal_layout_view.focus_detail_line.assert_called_with(expected_line)


def test_moving_up_in_logs_disables_tail_following(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    cache_key = state.selected_container_tab_key
    assert cache_key is not None
    state.tab_content_cache[cache_key] = "A\nB"
    state.detail_selected_line_index = 1
    test_setup = terminal_controller_factory(state)

    assert test_setup.terminal_controller.move_selected_detail_line("up")
    assert not state.follow_log_tail


def test_move_selection_to_last_detail_line_moves_focus(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "A\nB\nC"
    test_setup = terminal_controller_factory(state)

    assert test_setup.terminal_controller.move_selection_to_last_detail_line()
    assert state.detail_selected_line_index == 2
    test_setup.terminal_layout_view.focus_detail_line.assert_called_once_with(2)


def test_move_selected_container_index_loads_the_new_container(
    terminal_controller_factory,
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
    )
    test_setup = terminal_controller_factory(state)

    assert test_setup.terminal_controller.move_selected_container_index(1)
    assert state.selected_container_id == "two"
    docker_manager = test_setup.docker_manager
    docker_manager.prepare_selected_container_details.assert_called_once_with()


def test_container_selection_does_not_move_outside_bounds(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = terminal_controller_factory(state)

    assert not test_setup.terminal_controller.move_selected_container_index(-1)
    docker_manager = test_setup.docker_manager
    docker_manager.prepare_selected_container_details.assert_not_called()


def test_sort_menu_applies_the_selected_field_and_direction(
    terminal_controller_factory,
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
    )
    test_setup = terminal_controller_factory(state)

    assert test_setup.terminal_controller.open_container_sort_menu()
    assert test_setup.terminal_controller.move_container_sort_menu_selection(1)
    assert isinstance(state.container_sort_menu_state, ContainerSortMenuState)
    assert (
        state.container_sort_menu_state.selected_sort_field == ContainerSortField.NAME
    )
    assert test_setup.terminal_controller.set_container_sort_menu_direction(
        descending=True
    )
    assert test_setup.terminal_controller.apply_container_sort_menu()

    assert state.container_sort_field == ContainerSortField.NAME
    assert state.container_sort_descending
    assert state.container_sort_menu_state is None
    docker_manager = test_setup.docker_manager
    docker_manager.rebuild_displayed_container_list.assert_called_once_with()


def test_sort_menu_can_cancel_and_reject_unavailable_movements(
    terminal_controller_factory,
) -> None:
    state = TerminalSessionState()
    test_setup = terminal_controller_factory(state)

    assert not test_setup.terminal_controller.close_container_sort_menu()
    assert not test_setup.terminal_controller.move_container_sort_menu_selection(1)
    assert not test_setup.terminal_controller.set_container_sort_menu_direction(
        descending=True
    )
    assert not test_setup.terminal_controller.apply_container_sort_menu()

    assert test_setup.terminal_controller.open_container_sort_menu()
    assert not test_setup.terminal_controller.open_container_sort_menu()
    assert not test_setup.terminal_controller.move_container_sort_menu_selection(-1)
    assert not test_setup.terminal_controller.set_container_sort_menu_direction(
        descending=True
    )
    assert test_setup.terminal_controller.close_container_sort_menu()
    assert state.container_sort_field == ContainerSortField.DOCKER_ORDER


def test_docker_order_ignores_direction_in_the_sort_menu(
    terminal_controller_factory,
) -> None:
    state = TerminalSessionState()
    test_setup = terminal_controller_factory(state)

    test_setup.terminal_controller.open_container_sort_menu()
    assert not test_setup.terminal_controller.set_container_sort_menu_direction(
        descending=True
    )
    assert test_setup.terminal_controller.apply_container_sort_menu()
    assert not state.container_sort_descending


def test_container_filter_query_changes_rebuild_the_displayed_container_list(
    terminal_controller_factory,
) -> None:
    state = TerminalSessionState(container_filter_query="red")
    test_setup = terminal_controller_factory(state)
    controller = test_setup.terminal_controller

    assert controller.add_character_to_container_filter("i")
    assert state.container_filter_query == "redi"
    assert controller.remove_last_character_from_container_filter()
    assert state.container_filter_query == "red"
    assert test_setup.docker_manager.rebuild_displayed_container_list.call_count == 2


def test_container_filter_input_can_keep_or_restore_the_previous_query(
    terminal_controller_factory,
) -> None:
    state = TerminalSessionState(container_filter_query="redis")
    test_setup = terminal_controller_factory(state)
    controller = test_setup.terminal_controller

    assert controller.start_editing_container_filter()
    assert not controller.start_editing_container_filter()
    assert state.is_editing_container_filter
    assert state.container_filter_query_before_editing == "redis"
    assert controller.finish_editing_container_filter()
    assert not state.is_editing_container_filter
    assert state.container_filter_query == "redis"

    assert controller.start_editing_container_filter()
    assert controller.add_character_to_container_filter("7")
    assert state.container_filter_query == "redis7"
    assert controller.cancel_container_filter_editing()
    assert not state.is_editing_container_filter
    assert state.container_filter_query == "redis"
    assert test_setup.docker_manager.rebuild_displayed_container_list.call_count == 2


def test_switch_active_detail_tab_changes_tab_and_notifies_docker_manager(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.detail_selected_line_index = 5
    test_setup = terminal_controller_factory(state)

    assert test_setup.terminal_controller.switch_active_detail_tab(1)
    assert state.active_detail_tab_name == TabName.ENV
    docker_manager = test_setup.docker_manager
    docker_manager.prepare_active_detail_tab.assert_called_once_with()


def test_switch_active_detail_tab_wraps_from_top_to_logs(
    terminal_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.TOP)
    test_setup = terminal_controller_factory(state)

    test_setup.terminal_controller.switch_active_detail_tab(1)

    assert state.active_detail_tab_name == TabName.LOGS
    docker_manager = test_setup.docker_manager
    docker_manager.prepare_active_detail_tab.assert_called_once_with()
