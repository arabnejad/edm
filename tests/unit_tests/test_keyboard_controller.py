from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from easy_docker_manager.config.settings_definitions import SettingsMenuState
from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)
from easy_docker_manager.diagnostics import create_initial_diagnostics_report
from easy_docker_manager.tab_export.definitions import TabExportMenuState
from easy_docker_manager.ui.diagnostics_controller import DiagnosticsController
from easy_docker_manager.ui.keyboard_controller import KeyAction, KeyboardController
from easy_docker_manager.ui.settings_controller import SettingsController
from easy_docker_manager.ui.tab_export_controller import TabExportController


@dataclass
class KeyboardControllerTestSetup:
    keyboard_controller: KeyboardController
    terminal_controller: Mock
    tab_export_controller: Mock
    diagnostics_controller: Mock
    settings_controller: Mock


@pytest.fixture
def keyboard_controller_factory():
    def create_keyboard_controller(state: TerminalSessionState):
        terminal_controller = Mock()
        terminal_controller.state = state
        tab_export_controller = Mock(spec=TabExportController)
        diagnostics_controller = Mock(spec=DiagnosticsController)
        settings_controller = Mock(spec=SettingsController)
        keyboard_controller = KeyboardController(
            terminal_controller,
            tab_export_controller,
            diagnostics_controller,
            settings_controller,
        )
        return KeyboardControllerTestSetup(
            keyboard_controller=keyboard_controller,
            terminal_controller=terminal_controller,
            tab_export_controller=tab_export_controller,
            diagnostics_controller=diagnostics_controller,
            settings_controller=settings_controller,
        )

    return create_keyboard_controller


def test_h_opens_diagnostics_popup(keyboard_controller_factory) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    test_setup.diagnostics_controller.open_diagnostics_popup.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("h") == KeyAction.REDRAW
    test_setup.diagnostics_controller.open_diagnostics_popup.assert_called_once_with()


def test_uppercase_h_opens_diagnostics_popup(keyboard_controller_factory) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    test_setup.diagnostics_controller.open_diagnostics_popup.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("H") == KeyAction.REDRAW
    test_setup.diagnostics_controller.open_diagnostics_popup.assert_called_once_with()


@pytest.mark.parametrize("pressed_key", ["p", "P"])
def test_p_opens_settings_menu(
    pressed_key: str,
    keyboard_controller_factory,
) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    test_setup.settings_controller.open_settings_menu.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.REDRAW
    )
    test_setup.settings_controller.open_settings_menu.assert_called_once_with()


def test_settings_menu_delegates_all_keys_to_its_controller(
    keyboard_controller_factory,
) -> None:
    state = TerminalSessionState(settings_menu_state=SettingsMenuState(AppConfig()))
    test_setup = keyboard_controller_factory(state)
    test_setup.settings_controller.handle_menu_keypress.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("q") == KeyAction.REDRAW
    test_setup.settings_controller.handle_menu_keypress.assert_called_once_with("q")


def test_diagnostics_popup_accepts_only_escape(keyboard_controller_factory) -> None:
    state = TerminalSessionState(
        diagnostics_popup_report=create_initial_diagnostics_report()
    )
    test_setup = keyboard_controller_factory(state)
    test_setup.diagnostics_controller.close_diagnostics_popup.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("q") == KeyAction.NONE
    assert test_setup.keyboard_controller.handle_keypress("down") == KeyAction.NONE
    assert test_setup.keyboard_controller.handle_keypress("esc") == KeyAction.REDRAW
    test_setup.diagnostics_controller.close_diagnostics_popup.assert_called_once_with()


@pytest.mark.parametrize("pressed_key", ["q", "Q"])
def test_quit_keys_request_exit(pressed_key: str, keyboard_controller_factory) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    assert test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.QUIT


def test_enter_and_escape_change_active_panel(keyboard_controller_factory) -> None:
    state = TerminalSessionState()
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller

    assert keyboard_controller.handle_keypress("enter") == KeyAction.REDRAW
    assert state.active_focus_area == FocusArea.DETAIL
    assert keyboard_controller.handle_keypress("enter") == KeyAction.NONE

    assert keyboard_controller.handle_keypress("esc") == KeyAction.REDRAW
    assert state.active_focus_area == FocusArea.CONTAINERS
    assert keyboard_controller.handle_keypress("esc") == KeyAction.NONE


def test_arrow_keys_move_the_active_panel_selection(
    keyboard_controller_factory,
) -> None:
    state = TerminalSessionState()
    test_setup = keyboard_controller_factory(state)
    test_setup.terminal_controller.move_selected_container_index.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("down") == KeyAction.REDRAW
    test_setup.terminal_controller.move_selected_container_index.assert_called_once_with(
        1
    )

    state.active_focus_area = FocusArea.DETAIL
    test_setup.terminal_controller.move_selected_detail_line.return_value = True
    assert (
        test_setup.keyboard_controller.handle_keypress("up", (80, 24))
        == KeyAction.REDRAW
    )
    test_setup.terminal_controller.move_selected_detail_line.assert_called_once_with(
        "up", (80, 24)
    )


def test_bracket_keys_switch_tabs_in_both_directions(
    keyboard_controller_factory,
) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    test_setup.terminal_controller.switch_active_detail_tab.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("[") == KeyAction.REDRAW
    assert test_setup.keyboard_controller.handle_keypress("]") == KeyAction.REDRAW
    assert test_setup.terminal_controller.switch_active_detail_tab.call_args_list[
        0
    ].args == (-1,)
    assert test_setup.terminal_controller.switch_active_detail_tab.call_args_list[
        1
    ].args == (1,)


def test_sort_key_opens_menu_only_from_running_container_list_panel(
    keyboard_controller_factory,
) -> None:
    state = TerminalSessionState()
    test_setup = keyboard_controller_factory(state)
    test_setup.terminal_controller.open_container_sort_menu.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("s") == KeyAction.REDRAW
    test_setup.terminal_controller.open_container_sort_menu.assert_called_once_with()

    state.active_focus_area = FocusArea.DETAIL
    assert test_setup.keyboard_controller.handle_keypress("S") == KeyAction.NONE


def test_filter_key_starts_input_only_from_running_container_list_panel(
    keyboard_controller_factory,
) -> None:
    state = TerminalSessionState()
    test_setup = keyboard_controller_factory(state)
    test_setup.terminal_controller.start_editing_container_filter.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("f") == KeyAction.REDRAW
    test_setup.terminal_controller.start_editing_container_filter.assert_called_once_with()

    state.active_focus_area = FocusArea.DETAIL
    assert test_setup.keyboard_controller.handle_keypress("F") == KeyAction.NONE


def test_export_key_opens_menu_only_from_details_panel(
    keyboard_controller_factory,
) -> None:
    state = TerminalSessionState(active_focus_area=FocusArea.DETAIL)
    test_setup = keyboard_controller_factory(state)
    test_setup.tab_export_controller.open_tab_export_menu.return_value = True

    assert test_setup.keyboard_controller.handle_keypress("e") == KeyAction.REDRAW
    test_setup.tab_export_controller.open_tab_export_menu.assert_called_once_with()

    state.active_focus_area = FocusArea.CONTAINERS
    assert test_setup.keyboard_controller.handle_keypress("E") == KeyAction.NONE


@pytest.mark.parametrize(
    "pressed_key",
    ["up", "down", "tab", "enter", "esc", "left", "q", "Q", "x"],
)
def test_export_menu_delegates_every_key_to_its_controller(
    keyboard_controller_factory,
    pressed_key: str,
) -> None:
    state = TerminalSessionState(
        tab_export_menu_state=TabExportMenuState(
            ContainerTabKey("container-1", TabName.LOGS),
            "web",
            "logs.log",
            len("logs.log"),
        )
    )
    test_setup = keyboard_controller_factory(state)
    test_setup.tab_export_controller.handle_menu_keypress.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.REDRAW
    )
    test_setup.tab_export_controller.handle_menu_keypress.assert_called_once_with(
        pressed_key
    )


def test_export_menu_does_not_redraw_when_its_controller_reports_no_change(
    keyboard_controller_factory,
) -> None:
    state = TerminalSessionState(
        tab_export_menu_state=TabExportMenuState(
            ContainerTabKey("container-1", TabName.LOGS),
            "web",
            "logs.log",
            len("logs.log"),
        )
    )
    test_setup = keyboard_controller_factory(state)
    test_setup.tab_export_controller.handle_menu_keypress.return_value = False

    assert test_setup.keyboard_controller.handle_keypress("q") == KeyAction.NONE
    test_setup.tab_export_controller.handle_menu_keypress.assert_called_once_with("q")


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
    state = TerminalSessionState(
        container_sort_menu_state=ContainerSortMenuState(
            selected_sort_field=ContainerSortField.DOCKER_ORDER,
            sort_descending=False,
        )
    )
    test_setup = keyboard_controller_factory(state)
    method = getattr(test_setup.terminal_controller, controller_method)
    method.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.REDRAW
    )
    method.assert_called_once()
    assert method.call_args.args == expected_arguments
    if pressed_key in {"left", "right"}:
        assert method.call_args.kwargs == {"descending": pressed_key == "right"}


def test_sort_menu_ignores_unrelated_keys(keyboard_controller_factory) -> None:
    state = TerminalSessionState(
        container_sort_menu_state=ContainerSortMenuState(
            selected_sort_field=ContainerSortField.DOCKER_ORDER,
            sort_descending=False,
        )
    )
    test_setup = keyboard_controller_factory(state)

    assert test_setup.keyboard_controller.handle_keypress("q") == KeyAction.NONE


@pytest.mark.parametrize(
    ("pressed_key", "controller_method", "expected_arguments"),
    [
        ("enter", "finish_editing_container_filter", ()),
        ("esc", "cancel_container_filter_editing", ()),
        ("backspace", "remove_last_character_from_container_filter", ()),
        ("x", "add_character_to_container_filter", ("x",)),
        ("q", "add_character_to_container_filter", ("q",)),
        ("s", "add_character_to_container_filter", ("s",)),
        ("[", "add_character_to_container_filter", ("[",)),
        ("]", "add_character_to_container_filter", ("]",)),
    ],
)
def test_container_filter_routes_only_its_editing_keys(
    keyboard_controller_factory,
    pressed_key: str,
    controller_method: str,
    expected_arguments: tuple[object, ...],
) -> None:
    state = TerminalSessionState(container_filter_query_before_editing="")
    test_setup = keyboard_controller_factory(state)
    method = getattr(test_setup.terminal_controller, controller_method)
    method.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.REDRAW
    )
    method.assert_called_once_with(*expected_arguments)


@pytest.mark.parametrize(
    "pressed_key",
    ["up", "down", "page up", "page down", "home", "end", "delete"],
)
def test_container_filter_ignores_navigation_and_other_shortcuts(
    keyboard_controller_factory,
    pressed_key: str,
) -> None:
    state = TerminalSessionState(container_filter_query_before_editing="")
    test_setup = keyboard_controller_factory(state)

    assert test_setup.keyboard_controller.handle_keypress(pressed_key) == KeyAction.NONE
    assert not test_setup.terminal_controller.method_calls


def test_search_text_is_stored_per_selected_tab(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory(tab=TabName.ENV)
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller

    assert keyboard_controller.handle_keypress("/") == KeyAction.REDRAW
    assert state.is_search_active
    assert state.active_focus_area == FocusArea.DETAIL
    assert keyboard_controller.handle_keypress("A") == KeyAction.REDRAW

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

    assert keyboard_controller.handle_keypress("backspace") == KeyAction.REDRAW
    assert keyboard_controller.handle_keypress("backspace") == KeyAction.NONE


def test_enter_closes_search_and_keeps_detail_focus(
    keyboard_controller_factory,
    session_state_factory,
) -> None:
    state = session_state_factory()
    test_setup = keyboard_controller_factory(state)
    keyboard_controller = test_setup.keyboard_controller
    keyboard_controller.handle_keypress("/")

    assert keyboard_controller.handle_keypress("enter") == KeyAction.REDRAW
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

    assert keyboard_controller.handle_keypress("esc") == KeyAction.REDRAW
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
    test_setup.terminal_controller.move_selected_detail_line.return_value = True

    assert (
        test_setup.keyboard_controller.handle_keypress("page down", (80, 24))
        == KeyAction.REDRAW
    )
    test_setup.terminal_controller.move_selected_detail_line.assert_called_once_with(
        "page down",
        (80, 24),
    )
    assert next(iter(state.tab_search_queries.values())) == "x"


def test_page_navigation_is_ignored_while_running_container_list_panel_is_active(
    keyboard_controller_factory,
) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    assert test_setup.keyboard_controller.handle_keypress("page down") == KeyAction.NONE
    test_setup.terminal_controller.move_selected_detail_line.assert_not_called()


def test_unknown_key_does_nothing(keyboard_controller_factory) -> None:
    test_setup = keyboard_controller_factory(TerminalSessionState())
    assert test_setup.keyboard_controller.handle_keypress("f12") == KeyAction.NONE
