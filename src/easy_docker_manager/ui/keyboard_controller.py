"""Map terminal keypresses to EDM actions."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from easy_docker_manager.core.terminal_session_state import FocusArea
from easy_docker_manager.ui.tab_export_controller import TabExportController
from easy_docker_manager.ui.terminal_controller import TerminalController


class KeyAction(Enum):
    """Tell EDMApp what to do after a keypress."""

    NONE = "none"
    REDRAW = "redraw"
    QUIT = "quit"


class KeyboardController:
    """Handle EDM keyboard shortcuts, filtering, and search input.

    EDMApp sends each Urwid key name here. This class handles simple focus and
    text-input changes, sends navigation and container display options to
    TerminalController, and passes export-menu keys to TabExportController.
    """

    def __init__(
        self,
        terminal_controller: TerminalController,
        tab_export_controller: TabExportController,
    ) -> None:
        """Keep both UI controllers and their shared session state."""
        self.terminal_controller = terminal_controller
        self.tab_export_controller = tab_export_controller
        self.state = terminal_controller.state

    def handle_keypress(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> KeyAction:
        """Handle one keypress and tell EDMApp whether to redraw or quit."""
        if self.state.tab_export_menu_state is not None:
            return self._handle_tab_export_menu_keypress(key)
        if self.state.container_sort_menu_state is not None:
            return self._handle_container_sort_menu_keypress(key)
        if self.state.is_editing_container_filter:
            return self._handle_container_filter_keypress(key)
        if self.state.is_search_active:
            return (
                KeyAction.REDRAW
                if self._handle_search_keypress(key, terminal_size)
                else KeyAction.NONE
            )

        if key in {"q", "Q"}:
            return KeyAction.QUIT
        if key == "enter":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return KeyAction.NONE
            self.state.active_focus_area = FocusArea.DETAIL
            return KeyAction.REDRAW
        elif key == "esc":
            if self.state.active_focus_area == FocusArea.CONTAINERS:
                return KeyAction.NONE
            self.state.is_search_active = False
            self.state.active_focus_area = FocusArea.CONTAINERS
            return KeyAction.REDRAW
        elif key == "up":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return (
                    KeyAction.REDRAW
                    if self.terminal_controller.move_selected_detail_line(
                        "up", terminal_size
                    )
                    else KeyAction.NONE
                )
            else:
                return (
                    KeyAction.REDRAW
                    if self.terminal_controller.move_selected_container_index(-1)
                    else KeyAction.NONE
                )
        elif key == "down":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return (
                    KeyAction.REDRAW
                    if self.terminal_controller.move_selected_detail_line(
                        "down", terminal_size
                    )
                    else KeyAction.NONE
                )
            else:
                return (
                    KeyAction.REDRAW
                    if self.terminal_controller.move_selected_container_index(1)
                    else KeyAction.NONE
                )
        elif key == "[":
            return (
                KeyAction.REDRAW
                if self.terminal_controller.switch_active_detail_tab(-1)
                else KeyAction.NONE
            )
        elif key == "]":
            return (
                KeyAction.REDRAW
                if self.terminal_controller.switch_active_detail_tab(1)
                else KeyAction.NONE
            )
        elif key == "/":
            self.state.active_focus_area = FocusArea.DETAIL
            self.state.is_search_active = True
            return KeyAction.REDRAW
        elif key in {"s", "S"} and self.state.active_focus_area == FocusArea.CONTAINERS:
            return (
                KeyAction.REDRAW
                if self.terminal_controller.open_container_sort_menu()
                else KeyAction.NONE
            )
        elif key in {"f", "F"} and self.state.active_focus_area == FocusArea.CONTAINERS:
            return (
                KeyAction.REDRAW
                if self.terminal_controller.start_editing_container_filter()
                else KeyAction.NONE
            )
        elif key in {"e", "E"} and self.state.active_focus_area == FocusArea.DETAIL:
            return (
                KeyAction.REDRAW
                if self.tab_export_controller.open_tab_export_menu()
                else KeyAction.NONE
            )
        elif (
            key in {"page up", "page down", "home", "end"}
            and self.state.active_focus_area == FocusArea.DETAIL
        ):
            return (
                KeyAction.REDRAW
                if self.terminal_controller.move_selected_detail_line(
                    key, terminal_size
                )
                else KeyAction.NONE
            )
        return KeyAction.NONE

    def _handle_tab_export_menu_keypress(self, key: str) -> KeyAction:
        """Pass one export-menu key to TabExportController."""
        changed = self.tab_export_controller.handle_menu_keypress(key)
        return KeyAction.REDRAW if changed else KeyAction.NONE

    def _handle_container_sort_menu_keypress(self, key: str) -> KeyAction:
        """Handle navigation, apply, and cancel keys in the sorting menu."""
        changed = False
        if key == "up":
            changed = self.terminal_controller.move_container_sort_menu_selection(-1)
        elif key == "down":
            changed = self.terminal_controller.move_container_sort_menu_selection(1)
        elif key == "left":
            changed = self.terminal_controller.set_container_sort_menu_direction(
                descending=False
            )
        elif key == "right":
            changed = self.terminal_controller.set_container_sort_menu_direction(
                descending=True
            )
        elif key == "enter":
            changed = self.terminal_controller.apply_container_sort_menu()
        elif key == "esc":
            changed = self.terminal_controller.close_container_sort_menu()
        return KeyAction.REDRAW if changed else KeyAction.NONE

    def _handle_container_filter_keypress(self, key: str) -> KeyAction:
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
        return KeyAction.REDRAW if changed else KeyAction.NONE

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


__all__ = ["KeyboardController", "KeyAction"]
