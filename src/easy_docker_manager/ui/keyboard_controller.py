"""Map terminal keypresses to UI state actions."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from easy_docker_manager.core.ui_session_state import FocusArea
from easy_docker_manager.ui.ui_controller import UIController


class KeyAction(Enum):
    """Tell EDMApp what to do after a keypress."""

    NONE = "none"
    RENDER = "render"
    QUIT = "quit"


class KeyboardController:
    """Handle EDM keyboard shortcuts and search input.

    EDMApp sends each Urwid key name here. This controller updates search text
    and keyboard focus. It asks UIController to move selections or switch tabs.
    """

    def __init__(self, ui_controller: UIController) -> None:
        """Keep the UI controller and its shared session state."""
        self.ui_controller = ui_controller
        self.state = ui_controller.state

    def handle_keypress(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> KeyAction:
        """Handle one keypress and tell EDMApp whether to redraw or quit."""
        if self.state.is_container_sort_menu_open:
            return self._handle_container_sort_menu_keypress(key)
        if self.state.is_search_active:
            return (
                KeyAction.RENDER
                if self._handle_search_keypress(key, terminal_size)
                else KeyAction.NONE
            )

        if key in {"q", "Q"}:
            return KeyAction.QUIT
        if key == "enter":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return KeyAction.NONE
            self.state.active_focus_area = FocusArea.DETAIL
            return KeyAction.RENDER
        elif key == "esc":
            if self.state.active_focus_area == FocusArea.CONTAINERS:
                return KeyAction.NONE
            self.state.is_search_active = False
            self.state.active_focus_area = FocusArea.CONTAINERS
            return KeyAction.RENDER
        elif key == "up":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return (
                    KeyAction.RENDER
                    if self.ui_controller.move_detail_selection("up", terminal_size)
                    else KeyAction.NONE
                )
            else:
                return (
                    KeyAction.RENDER
                    if self.ui_controller.move_container_selection(-1)
                    else KeyAction.NONE
                )
        elif key == "down":
            if self.state.active_focus_area == FocusArea.DETAIL:
                return (
                    KeyAction.RENDER
                    if self.ui_controller.move_detail_selection("down", terminal_size)
                    else KeyAction.NONE
                )
            else:
                return (
                    KeyAction.RENDER
                    if self.ui_controller.move_container_selection(1)
                    else KeyAction.NONE
                )
        elif key == "[":
            return (
                KeyAction.RENDER
                if self.ui_controller.switch_detail_tab(-1)
                else KeyAction.NONE
            )
        elif key == "]":
            return (
                KeyAction.RENDER
                if self.ui_controller.switch_detail_tab(1)
                else KeyAction.NONE
            )
        elif key == "/":
            self.state.active_focus_area = FocusArea.DETAIL
            self.state.is_search_active = True
            return KeyAction.RENDER
        elif key in {"s", "S"} and self.state.active_focus_area == FocusArea.CONTAINERS:
            return (
                KeyAction.RENDER
                if self.ui_controller.open_container_sort_menu()
                else KeyAction.NONE
            )
        elif (
            key in {"page up", "page down", "home", "end"}
            and self.state.active_focus_area == FocusArea.DETAIL
        ):
            return (
                KeyAction.RENDER
                if self.ui_controller.move_detail_selection(key, terminal_size)
                else KeyAction.NONE
            )
        return KeyAction.NONE

    def _handle_container_sort_menu_keypress(self, key: str) -> KeyAction:
        """Handle navigation, apply, and cancel keys while sorting is open."""
        changed = False
        if key == "up":
            changed = self.ui_controller.move_container_sort_menu_selection(-1)
        elif key == "down":
            changed = self.ui_controller.move_container_sort_menu_selection(1)
        elif key == "left":
            changed = self.ui_controller.set_container_sort_menu_direction(
                descending=False
            )
        elif key == "right":
            changed = self.ui_controller.set_container_sort_menu_direction(
                descending=True
            )
        elif key == "enter":
            changed = self.ui_controller.apply_container_sort_menu()
        elif key == "esc":
            changed = self.ui_controller.close_container_sort_menu()
        return KeyAction.RENDER if changed else KeyAction.NONE

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
                self.ui_controller.move_detail_selection(key, terminal_size)
                or focus_changed
            )
        if key == "[":
            return self.ui_controller.switch_detail_tab(-1)
        if key == "]":
            return self.ui_controller.switch_detail_tab(1)

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
