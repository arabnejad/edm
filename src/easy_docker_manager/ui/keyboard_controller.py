"""Map terminal keypresses to EDM actions."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from easy_docker_manager.config.settings_definitions import SettingsMenuState
from easy_docker_manager.core.container_actions import ContainerActionMenuState
from easy_docker_manager.core.container_sorting import ContainerListMenuState
from easy_docker_manager.core.docker_connections import DockerConnectionMenuState
from easy_docker_manager.core.terminal_session_state import FocusArea
from easy_docker_manager.diagnostics import DiagnosticsReport
from easy_docker_manager.tab_export.definitions import TabExportMenuState
from easy_docker_manager.ui.container_action_controller import ContainerActionController
from easy_docker_manager.ui.diagnostics_controller import DiagnosticsController
from easy_docker_manager.ui.docker_connection_controller import (
    DockerConnectionController,
)
from easy_docker_manager.ui.settings_controller import SettingsController
from easy_docker_manager.ui.tab_export_controller import TabExportController
from easy_docker_manager.ui.terminal_controller import TerminalController


class KeypressResult(Enum):
    """Tell EDMApp what to do after a keypress."""

    NONE = "none"
    REDRAW = "redraw"
    QUIT = "quit"


class KeyboardController:
    """Handle EDM keyboard shortcuts, filtering, and search input.

    EDMApp sends each Urwid key name here. This class handles simple focus and
    text-input changes, sends navigation and container display options to
    TerminalController, and passes popup actions to their controllers.
    """

    def __init__(
        self,
        terminal_controller: TerminalController,
        tab_export_controller: TabExportController,
        diagnostics_controller: DiagnosticsController,
        settings_controller: SettingsController,
        container_action_controller: ContainerActionController,
        docker_connection_controller: DockerConnectionController,
    ) -> None:
        """Keep the UI controllers and their shared session state."""
        self.terminal_controller = terminal_controller
        self.tab_export_controller = tab_export_controller
        self.diagnostics_controller = diagnostics_controller
        self.settings_controller = settings_controller
        self.container_action_controller = container_action_controller
        self.docker_connection_controller = docker_connection_controller
        self.state = terminal_controller.state

    def handle_keypress(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> KeypressResult:
        """Handle one keypress and tell EDMApp whether to redraw or quit."""
        active_popup = self.state.active_popup
        if isinstance(active_popup, DiagnosticsReport):
            return self._handle_diagnostics_popup_keypress(key)
        if isinstance(active_popup, SettingsMenuState):
            return self._handle_settings_menu_keypress(key)
        if isinstance(active_popup, ContainerActionMenuState):
            return self._handle_container_action_menu_keypress(key)
        if isinstance(active_popup, DockerConnectionMenuState):
            return self._handle_docker_connection_menu_keypress(key)
        if isinstance(active_popup, TabExportMenuState):
            return self._handle_tab_export_menu_keypress(key)
        if isinstance(active_popup, ContainerListMenuState):
            return self._handle_container_list_menu_keypress(key)
        if self.state.is_editing_container_filter:
            return self._handle_container_filter_keypress(key)
        if self.state.is_search_active:
            return (
                KeypressResult.REDRAW
                if self._handle_search_keypress(key, terminal_size)
                else KeypressResult.NONE
            )

        if key in {"h", "H"}:
            return (
                KeypressResult.REDRAW
                if self.diagnostics_controller.open_diagnostics_popup()
                else KeypressResult.NONE
            )
        if key in {"p", "P"}:
            return (
                KeypressResult.REDRAW
                if self.settings_controller.open_settings_menu()
                else KeypressResult.NONE
            )
        if key in {"a", "A"}:
            return (
                KeypressResult.REDRAW
                if self.container_action_controller.open_container_action_menu()
                else KeypressResult.NONE
            )
        if key in {"c", "C"}:
            return (
                KeypressResult.REDRAW
                if self.docker_connection_controller.open_docker_connection_menu()
                else KeypressResult.NONE
            )
        if key in {"q", "Q"}:
            return KeypressResult.QUIT
        if key == "enter":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return KeypressResult.NONE
            self.state.active_focus_area = FocusArea.DETAIL
            return KeypressResult.REDRAW
        elif key == "esc":
            if self.state.active_focus_area == FocusArea.CONTAINERS:
                return KeypressResult.NONE
            self.state.is_search_active = False
            self.state.active_focus_area = FocusArea.CONTAINERS
            return KeypressResult.REDRAW
        elif key == "up":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return (
                    KeypressResult.REDRAW
                    if self.terminal_controller.move_selected_detail_line(
                        "up", terminal_size
                    )
                    else KeypressResult.NONE
                )
            else:
                return (
                    KeypressResult.REDRAW
                    if self.terminal_controller.move_selected_container_index(-1)
                    else KeypressResult.NONE
                )
        elif key == "down":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return (
                    KeypressResult.REDRAW
                    if self.terminal_controller.move_selected_detail_line(
                        "down", terminal_size
                    )
                    else KeypressResult.NONE
                )
            else:
                return (
                    KeypressResult.REDRAW
                    if self.terminal_controller.move_selected_container_index(1)
                    else KeypressResult.NONE
                )
        elif key == "[":
            return (
                KeypressResult.REDRAW
                if self.terminal_controller.switch_active_detail_tab(-1)
                else KeypressResult.NONE
            )
        elif key == "]":
            return (
                KeypressResult.REDRAW
                if self.terminal_controller.switch_active_detail_tab(1)
                else KeypressResult.NONE
            )
        elif key == "/":
            self.state.active_focus_area = FocusArea.DETAIL
            self.state.is_search_active = True
            return KeypressResult.REDRAW
        elif key in {"s", "S"} and self.state.active_focus_area == FocusArea.CONTAINERS:
            return (
                KeypressResult.REDRAW
                if self.terminal_controller.open_container_list_menu()
                else KeypressResult.NONE
            )
        elif key in {"f", "F"} and self.state.active_focus_area == FocusArea.CONTAINERS:
            return (
                KeypressResult.REDRAW
                if self.terminal_controller.start_editing_container_filter()
                else KeypressResult.NONE
            )
        elif key in {"e", "E"} and self.state.active_focus_area == FocusArea.DETAIL:
            return (
                KeypressResult.REDRAW
                if self.tab_export_controller.open_tab_export_menu()
                else KeypressResult.NONE
            )
        elif (
            key in {"page up", "page down", "home", "end"}
            and self.state.active_focus_area == FocusArea.DETAIL
        ):
            return (
                KeypressResult.REDRAW
                if self.terminal_controller.move_selected_detail_line(
                    key, terminal_size
                )
                else KeypressResult.NONE
            )
        return KeypressResult.NONE

    def _handle_diagnostics_popup_keypress(self, key: str) -> KeypressResult:
        """Close diagnostics with Esc and ignore other keys while it is open."""
        if key != "esc":
            return KeypressResult.NONE
        return (
            KeypressResult.REDRAW
            if self.diagnostics_controller.close_diagnostics_popup()
            else KeypressResult.NONE
        )

    def _handle_settings_menu_keypress(self, key: str) -> KeypressResult:
        """Pass one settings key to SettingsController."""
        changed = self.settings_controller.handle_menu_keypress(key)
        return KeypressResult.REDRAW if changed else KeypressResult.NONE

    def _handle_container_action_menu_keypress(self, key: str) -> KeypressResult:
        """Pass one action-menu key to ContainerActionController."""
        changed = self.container_action_controller.handle_menu_keypress(key)
        return KeypressResult.REDRAW if changed else KeypressResult.NONE

    def _handle_docker_connection_menu_keypress(self, key: str) -> KeypressResult:
        """Pass one connection-menu key to DockerConnectionController."""
        changed = self.docker_connection_controller.handle_menu_keypress(key)
        return KeypressResult.REDRAW if changed else KeypressResult.NONE

    def _handle_tab_export_menu_keypress(self, key: str) -> KeypressResult:
        """Pass one export-menu key to TabExportController."""
        changed = self.tab_export_controller.handle_menu_keypress(key)
        return KeypressResult.REDRAW if changed else KeypressResult.NONE

    def _handle_container_list_menu_keypress(self, key: str) -> KeypressResult:
        """Handle navigation, changes, apply, and cancel in the list menu."""
        changed = False
        if key == "up":
            changed = self.terminal_controller.move_container_list_menu_selection(-1)
        elif key == "down":
            changed = self.terminal_controller.move_container_list_menu_selection(1)
        elif key == "left":
            changed = (
                self.terminal_controller.change_selected_container_list_menu_value(-1)
            )
        elif key == "right":
            changed = (
                self.terminal_controller.change_selected_container_list_menu_value(+1)
            )
        elif key == "enter":
            changed = self.terminal_controller.apply_container_list_menu()
        elif key == "esc":
            changed = self.terminal_controller.close_container_list_menu()
        return KeypressResult.REDRAW if changed else KeypressResult.NONE

    def _handle_container_filter_keypress(self, key: str) -> KeypressResult:
        """Handle filter input while blocking unrelated terminal shortcuts."""
        changed = False
        if key == "enter":
            changed = self.terminal_controller.finish_editing_container_filter()
        elif key == "esc":
            changed = self.terminal_controller.cancel_container_filter_editing()
        elif key == "backspace":
            changed = (
                self.terminal_controller.remove_last_character_from_container_filter()
            )
        elif len(key) == 1 and key.isprintable():
            changed = self.terminal_controller.add_character_to_container_filter(key)
        return KeypressResult.REDRAW if changed else KeypressResult.NONE

    def _handle_search_keypress(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> bool:
        """Handle text editing and navigation while search mode is open."""
        container_tab_key = self.state.selected_container_tab_key
        query = (
            self.state.tab_search_queries.get(container_tab_key, "")
            if container_tab_key is not None
            else ""
        )
        if key in {"up", "down", "page up", "page down", "home", "end"}:
            focus_changed = self.state.active_focus_area != FocusArea.DETAIL
            self.state.active_focus_area = FocusArea.DETAIL
            return (
                self.terminal_controller.move_selected_detail_line(key, terminal_size)
                or focus_changed
            )
        if key == "[":
            return self.terminal_controller.switch_active_detail_tab(-1)
        if key == "]":
            return self.terminal_controller.switch_active_detail_tab(1)

        if key == "esc":
            changed = (
                self.state.is_search_active
                or self.state.active_focus_area != FocusArea.CONTAINERS
            )
            self.state.is_search_active = False
            self.state.active_focus_area = FocusArea.CONTAINERS
            return changed
        elif key == "enter":
            changed = (
                self.state.is_search_active
                or self.state.active_focus_area != FocusArea.DETAIL
            )
            self.state.is_search_active = False
            self.state.active_focus_area = FocusArea.DETAIL
            return changed
        elif key == "backspace":
            if not query or container_tab_key is None:
                return False
            self.state.tab_search_queries[container_tab_key] = query[:-1]
            self.state.detail_selected_line_index = 0
            return True
        elif len(key) == 1 and key.isprintable():
            if container_tab_key is None:
                return False
            self.state.tab_search_queries[container_tab_key] = query + key
            self.state.active_focus_area = FocusArea.DETAIL
            self.state.detail_selected_line_index = 0
            return True
        return False


__all__ = ["KeyboardController", "KeypressResult"]
