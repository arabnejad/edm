from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from easy_docker_manager.core import ContainerSummary
from easy_docker_manager.core.content_cache import ContainerTabKey
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.ui_controller import UIController


@dataclass
class UIControllerTestSetup:
    controller: UIController
    terminal_layout_view: Mock
    scheduler: Mock


@pytest.fixture
def controller_factory():
    def create_controller(state: UISessionState):
        terminal_layout_view = Mock()
        scheduler = Mock()
        scheduler.schedule_selected_tab_load.return_value = True
        ui_controller = UIController(
            state,
            terminal_layout_view,
            DetailTabTextFormatter(),
            scheduler,
        )
        return UIControllerTestSetup(
            controller=ui_controller,
            terminal_layout_view=terminal_layout_view,
            scheduler=scheduler,
        )

    return create_controller


def test_visible_lines_return_messages_for_each_empty_or_error_state(
    controller_factory,
    container_summary_factory,
) -> None:
    state = UISessionState()
    test_setup = controller_factory(state)
    controller = test_setup.controller
    assert controller.get_visible_detail_lines() == ["Select a running container."]

    state.running_containers = [container_summary_factory()]
    state.selected_container_index = 0
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    assert controller.get_visible_detail_lines() == ["Loading..."]

    state.tab_load_errors[container_tab_key] = "failed"
    assert controller.get_visible_detail_lines() == ["failed"]
    state.tab_load_errors.clear()

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
        assert controller.get_visible_detail_lines() == [message]


def test_visible_log_lines_use_the_saved_query(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "INFO ok\nERROR failed"
    state.tab_search_queries[container_tab_key] = "ERROR"
    test_setup = controller_factory(state)

    assert test_setup.controller.get_visible_detail_lines() == ["ERROR failed"]


def test_render_passes_lines_and_error_state_to_the_view(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.CONFIG)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_load_errors[container_tab_key] = "failed"
    test_setup = controller_factory(state)

    test_setup.controller.render_current_state()

    rendered_state, lines, line_markup = (
        test_setup.terminal_layout_view.render.call_args.args
    )
    assert rendered_state is state
    assert lines == ["failed"]
    assert line_markup("failed") == [("error", "failed")]


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
def test_move_detail_selection(
    navigation_key: str,
    starting_line: int,
    expected_line: int,
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    cache_key = state.selected_container_tab_key
    assert cache_key is not None
    state.tab_content_cache[cache_key] = "A\nB\nC\nD"
    state.detail_selected_line_index = starting_line
    test_setup = controller_factory(state)

    selection_changed = test_setup.controller.move_detail_selection(
        navigation_key,
        terminal_size=(80, 10),
    )

    assert selection_changed
    assert state.detail_selected_line_index == expected_line
    test_setup.terminal_layout_view.focus_detail_line.assert_called_with(expected_line)


def test_moving_up_in_logs_disables_tail_following(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    cache_key = state.selected_container_tab_key
    assert cache_key is not None
    state.tab_content_cache[cache_key] = "A\nB"
    state.detail_selected_line_index = 1
    test_setup = controller_factory(state)

    assert test_setup.controller.move_detail_selection("up")
    assert not state.follow_log_tail


def test_select_last_detail_line_moves_focus(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    state.tab_content_cache[container_tab_key] = "A\nB\nC"
    test_setup = controller_factory(state)

    assert test_setup.controller.select_last_detail_line()
    assert state.detail_selected_line_index == 2
    test_setup.terminal_layout_view.focus_detail_line.assert_called_once_with(2)


def test_move_container_selection_loads_the_new_container(
    controller_factory,
    container_summary_factory,
) -> None:
    state = UISessionState(
        running_containers=[
            container_summary_factory("one"),
            container_summary_factory("two"),
        ],
        selected_container_index=0,
    )
    test_setup = controller_factory(state)

    assert test_setup.controller.move_container_selection(1)
    assert state.selected_container_id == "two"
    test_setup.scheduler.reset_log_poll_schedule.assert_called_once_with()
    test_setup.scheduler.schedule_selected_tab_load.assert_called_once_with(force=True)


def test_container_selection_does_not_move_outside_bounds(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = controller_factory(state)

    assert not test_setup.controller.move_container_selection(-1)
    test_setup.scheduler.schedule_selected_tab_load.assert_not_called()


def test_switch_detail_tab_resets_navigation_and_requests_content(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.detail_selected_line_index = 5
    test_setup = controller_factory(state)

    assert test_setup.controller.switch_detail_tab(1)
    assert state.active_detail_tab_name == TabName.ENV
    assert state.detail_selected_line_index == 0
    assert not state.follow_log_tail
    test_setup.scheduler.reset_log_poll_schedule.assert_called_once_with()
    test_setup.scheduler.schedule_selected_tab_load.assert_called_once_with(force=False)


def test_switch_to_cached_tab_updates_status(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.LOGS)
    env_key = ContainerTabKey("container-1", TabName.ENV)
    state.tab_content_cache[env_key] = "A=1"
    test_setup = controller_factory(state)

    test_setup.controller.switch_detail_tab(1)

    assert state.status_message == "Loaded Env"


def test_update_running_containers_selects_first_and_loads_it(
    controller_factory,
    container_summary_factory,
) -> None:
    state = UISessionState()
    test_setup = controller_factory(state)
    containers = [
        container_summary_factory("one"),
        container_summary_factory("two"),
    ]

    assert test_setup.controller.update_running_containers(containers)
    assert state.selected_container_index == 0
    assert state.status_message == "2 running containers"
    test_setup.scheduler.remove_stopped_container_log_tracking.assert_called_once_with(
        {"one", "two"}
    )
    test_setup.scheduler.schedule_selected_tab_load.assert_called_once_with(force=True)


def test_update_running_containers_preserves_selection_by_id(
    controller_factory,
    container_summary_factory,
) -> None:
    state = UISessionState(
        running_containers=[
            container_summary_factory("one"),
            container_summary_factory("two"),
        ],
        selected_container_index=1,
    )
    test_setup = controller_factory(state)
    refreshed = [
        ContainerSummary("two", "two-new", "running"),
        container_summary_factory("three"),
    ]

    assert test_setup.controller.update_running_containers(refreshed)
    assert state.selected_container_id == "two"
    test_setup.scheduler.schedule_selected_tab_load.assert_not_called()


def test_unchanged_refresh_clears_old_error_status(
    controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    state.status_message = "Container refresh failed: offline"
    test_setup = controller_factory(state)

    assert test_setup.controller.update_running_containers(
        list(state.running_containers)
    )
    assert state.status_message == "1 running containers"


def test_repeated_empty_refresh_does_not_request_another_redraw(
    controller_factory,
) -> None:
    state = UISessionState()
    test_setup = controller_factory(state)

    assert test_setup.controller.update_running_containers([])
    assert state.status_message == "No running containers."
    assert not test_setup.controller.update_running_containers([])
