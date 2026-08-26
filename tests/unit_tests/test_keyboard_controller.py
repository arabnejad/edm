from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import FocusArea, UISessionState
from easy_docker_manager.ui.keyboard_controller import KeyAction, KeyboardController


@dataclass
class KeyboardControllerTestSetup:
    keyboard_controller: KeyboardController
    ui_controller: Mock


@pytest.fixture
def keyboard_controller_factory():
    def create_keyboard_controller(state: UISessionState):
        ui_controller = Mock()
        ui_controller.state = state
        keyboard_controller = KeyboardController(ui_controller)
        return KeyboardControllerTestSetup(
            keyboard_controller=keyboard_controller,
            ui_controller=ui_controller,
        )

    return create_keyboard_controller


@pytest.mark.parametrize("pressed_key", ["q", "Q"])
def test_quit_keys_request_exit(pressed_key: str, keyboard_controller_factory) -> None:
    test_setup = keyboard_controller_factory(UISessionState())
    assert test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.QUIT


def test_enter_and_escape_change_active_panel(keyboard_controller_factory) -> None:
    state = UISessionState()
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller

    assert keyboard_controller.handle_keypress("enter") == KeyAction.RENDER
    assert state.active_focus_area == FocusArea.DETAIL
    assert keyboard_controller.handle_keypress("enter") == KeyAction.NONE

    assert keyboard_controller.handle_keypress("esc") == KeyAction.RENDER
    assert state.active_focus_area == FocusArea.CONTAINERS
    assert keyboard_controller.handle_keypress("esc") == KeyAction.NONE


def test_arrow_keys_move_the_active_panel_selection(
    keyboard_controller_factory,
) -> None:
    state = UISessionState()
    test_setup = keyboard_controller_factory(state)
    test_setup.ui_controller.move_selected_container_index.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("down") == KeyAction.RENDER
    test_setup.ui_controller.move_selected_container_index.assert_called_once_with(1)

    state.active_focus_area = FocusArea.DETAIL
    test_setup.ui_controller.move_selected_detail_line.return_value = True
    assert (
        test_setup.keyboard_controller.handle_keypress("up", (80, 24))
        == KeyAction.RENDER
    )
    test_setup.ui_controller.move_selected_detail_line.assert_called_once_with(
        "up", (80, 24)
    )


def test_bracket_keys_switch_tabs_in_both_directions(
    keyboard_controller_factory,
) -> None:
    test_setup = keyboard_controller_factory(UISessionState())
    test_setup.ui_controller.switch_active_detail_tab.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("[") == KeyAction.RENDER
    assert test_setup.keyboard_controller.handle_keypress("]") == KeyAction.RENDER
    assert test_setup.ui_controller.switch_active_detail_tab.call_args_list[0].args == (
        -1,
    )
    assert test_setup.ui_controller.switch_active_detail_tab.call_args_list[1].args == (
        1,
    )


def test_sort_key_opens_menu_only_from_running_container_list_panel(
    keyboard_controller_factory,
) -> None:
    state = UISessionState()
    test_setup = keyboard_controller_factory(state)
    test_setup.ui_controller.open_container_sort_menu.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("s") == KeyAction.RENDER
    test_setup.ui_controller.open_container_sort_menu.assert_called_once_with()

    state.active_focus_area = FocusArea.DETAIL
    assert test_setup.keyboard_controller.handle_keypress("S") == KeyAction.NONE


@pytest.mark.parametrize(
    ("pressed_key", "controller_method", "expected_arguments"),
    [
        ("up", "move_container_sort_menu_selection", (-1,)),
        ("down", "move_container_sort_menu_selection", (1,)),
        ("left", "set_container_sort_menu_direction", ()),
        ("right", "set_container_sort_menu_direction", ()),
        ("enter", "apply_container_sort_menu", ()),
        ("esc", "close_container_sort_menu", ()),
    ],
)
def test_sort_menu_routes_its_keyboard_controls(
    keyboard_controller_factory,
    pressed_key: str,
    controller_method: str,
    expected_arguments: tuple[object, ...],
) -> None:
    state = UISessionState(
        container_sort_menu_state=ContainerSortMenuState(
            selected_sort_field=ContainerSortField.DOCKER_ORDER,
            sort_descending=False,
        )
    )
    test_setup = keyboard_controller_factory(state)
    method = getattr(test_setup.ui_controller, controller_method)
    method.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.RENDER
    )
    method.assert_called_once()
    assert method.call_args.args == expected_arguments
    if pressed_key in {"left", "right"}:
        assert method.call_args.kwargs == {"descending": pressed_key == "right"}


def test_sort_menu_ignores_unrelated_keys(keyboard_controller_factory) -> None:
    state = UISessionState(
        container_sort_menu_state=ContainerSortMenuState(
            selected_sort_field=ContainerSortField.DOCKER_ORDER,
            sort_descending=False,
        )
    )
    test_setup = keyboard_controller_factory(state)

    assert test_setup.keyboard_controller.handle_keypress("q") == KeyAction.NONE


def test_search_text_is_stored_per_selected_tab(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller

    assert keyboard_controller.handle_keypress("/") == KeyAction.RENDER
    assert state.is_search_active
    assert state.active_focus_area == FocusArea.DETAIL
    assert keyboard_controller.handle_keypress("A") == KeyAction.RENDER

    container_tab_key = state.selected_container_tab_key
    assert container_tab_key is not None
    assert state.tab_search_queries[container_tab_key] == "A"


def test_backspace_edits_query_without_moving_an_empty_query(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller
    keyboard_controller.handle_keypress("/")
    keyboard_controller.handle_keypress("A")

    assert keyboard_controller.handle_keypress("backspace") == KeyAction.RENDER
    assert keyboard_controller.handle_keypress("backspace") == KeyAction.NONE


def test_enter_closes_search_and_keeps_detail_focus(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller
    keyboard_controller.handle_keypress("/")

    assert keyboard_controller.handle_keypress("enter") == KeyAction.RENDER
    assert not state.is_search_active
    assert state.active_focus_area == FocusArea.DETAIL


def test_escape_closes_search_and_returns_to_containers(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller
    keyboard_controller.handle_keypress("/")

    assert keyboard_controller.handle_keypress("esc") == KeyAction.RENDER
    assert not state.is_search_active
    assert state.active_focus_area == FocusArea.CONTAINERS


def test_search_navigation_moves_detail_without_changing_query(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = keyboard_controller_factory(state)
    test_setup.keyboard_controller.handle_keypress("/")
    test_setup.keyboard_controller.handle_keypress("x")
    test_setup.ui_controller.move_selected_detail_line.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress("page down", (80, 24))
        == KeyAction.RENDER
    )
    test_setup.ui_controller.move_selected_detail_line.assert_called_once_with(
        "page down",
        (80, 24),
    )
    assert next(iter(state.tab_search_queries.values())) == "x"


def test_page_navigation_is_ignored_while_running_container_list_panel_is_active(
    keyboard_controller_factory,
) -> None:
    test_setup = keyboard_controller_factory(UISessionState())
    assert test_setup.keyboard_controller.handle_keypress("page down") == KeyAction.NONE
    test_setup.ui_controller.move_selected_detail_line.assert_not_called()


def test_unknown_key_does_nothing(keyboard_controller_factory) -> None:
    test_setup = keyboard_controller_factory(UISessionState())
    assert test_setup.keyboard_controller.handle_keypress("f1") == KeyAction.NONE
