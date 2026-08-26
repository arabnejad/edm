"""Apply UI navigation rules and prepare state for rendering."""

from __future__ import annotations

from typing import Optional

from easy_docker_manager.app.docker_manager import DockerManager
from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView


class UIController:
    """Handle navigation, menu choices, search, and screen rendering.

    KeyboardController handles individual keys. This class moves container and
    detail selections, switches tabs, prepares visible text, and sends the
    current state to TerminalLayoutView. DockerManager owns Docker
    requests and updates the state when their results are ready.
    """

    DETAIL_TABS = tuple(TabName)
    CONTAINER_SORT_FIELDS = tuple(ContainerSortField)

    def __init__(
        self,
        state: UISessionState,
        terminal_layout_view: TerminalLayoutView,
        detail_tab_text_formatter: DetailTabTextFormatter,
        docker_manager: DockerManager,
    ) -> None:
        self.state = state
        self.terminal_layout_view = terminal_layout_view
        self.detail_tab_text_formatter = detail_tab_text_formatter
        self.docker_manager = docker_manager

    @staticmethod
    def _estimate_detail_page_height(
        terminal_size: Optional[tuple[int, ...]],
    ) -> int:
        """Estimate how many detail rows fit on one page."""
        if terminal_size and len(terminal_size) >= 2:
            return max(1, terminal_size[1] - 5)
        return 20

    def update_terminal_view(self) -> None:
        """Update the parts of EDM's terminal screen that can change.

        The terminal view is the full-screen layout containing the running
        container list, selected container details, shortcut footer, and any
        open popup. EDMApp calls this method at startup and after keyboard or
        background activity changes visible information.
        """
        detail_lines = self.get_active_detail_tab_display_lines()
        if (
            self.state.active_detail_tab_name == TabName.LOGS
            and self.state.follow_log_tail
        ):
            self.state.detail_selected_line_index = max(0, len(detail_lines) - 1)
        self.state.keep_selected_detail_line_within_available_range(len(detail_lines))
        container_tab_key = self.state.selected_container_tab_key
        query = (
            self.state.tab_search_queries.get(container_tab_key, "")
            if container_tab_key is not None
            else ""
        )
        is_error = container_tab_key in self.state.tab_load_errors or (
            self.state.active_detail_tab_name == TabName.LOGS
            and self.state.selected_container_id
            in self.state.unreadable_log_container_ids
        )
        self.terminal_layout_view.render(
            self.state,
            detail_lines,
            lambda line: self.detail_tab_text_formatter.format_detail_line(
                line,
                self.state.active_detail_tab_name,
                query,
                is_error=is_error,
            ),
        )

    def get_active_detail_tab_display_lines(self) -> list[str]:
        """Return the loading, error, empty, or content lines for the active tab."""
        container_tab_key = self.state.selected_container_tab_key
        if container_tab_key is None:
            return ["Select a running container."]
        load_error = self.state.tab_load_errors.get(container_tab_key)
        if load_error:
            return [load_error]
        if container_tab_key not in self.state.tab_content_cache:
            return ["Loading..."]

        content = self.state.tab_content_cache[container_tab_key]
        if content == "":
            return [self.get_empty_tab_message(self.state.active_detail_tab_name)]

        query = self.state.tab_search_queries.get(container_tab_key, "")
        return self.detail_tab_text_formatter.prepare_visible_lines(
            content, self.state.active_detail_tab_name, query
        )

    @staticmethod
    def get_empty_tab_message(tab_name: TabName) -> str:
        """Return the message shown after a tab loads with no text content."""
        if tab_name == TabName.LOGS:
            return "No logs available."
        if tab_name == TabName.ENV:
            return "No environment variables."
        if tab_name == TabName.CONFIG:
            return "No container configuration."
        if tab_name == TabName.TOP:
            return "No processes."
        return "No content available."

    def move_selected_detail_line(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> bool:
        """Move through detail lines and pause log following when moving upward."""
        previous_index = self.state.detail_selected_line_index
        previous_follow = self.state.follow_log_tail
        line_count = max(1, len(self.get_active_detail_tab_display_lines()))
        visible_height = self._estimate_detail_page_height(terminal_size)
        page_size = max(1, visible_height - 1)
        if key == "up":
            self.state.detail_selected_line_index -= 1
        elif key == "down":
            self.state.detail_selected_line_index += 1
        elif key == "page up":
            self.state.detail_selected_line_index -= page_size
        elif key == "page down":
            self.state.detail_selected_line_index += page_size
        elif key == "home":
            self.state.detail_selected_line_index = 0
        elif key == "end":
            self.state.detail_selected_line_index = line_count - 1
        self.state.keep_selected_detail_line_within_available_range(line_count)
        if self.state.active_detail_tab_name == TabName.LOGS:
            self.state.follow_log_tail = (
                self.state.detail_selected_line_index >= line_count - 1
            )
        changed = (
            self.state.detail_selected_line_index != previous_index
            or self.state.follow_log_tail != previous_follow
        )
        if not changed:
            return False
        self.terminal_layout_view.focus_detail_line(
            self.state.detail_selected_line_index
        )
        return True

    def move_selection_to_last_detail_line(self) -> bool:
        """Select the last visible detail line."""
        previous_index = self.state.detail_selected_line_index
        lines = self.get_active_detail_tab_display_lines()
        self.state.detail_selected_line_index = max(0, len(lines) - 1)
        self.terminal_layout_view.focus_detail_line(
            self.state.detail_selected_line_index
        )
        return self.state.detail_selected_line_index != previous_index

    def move_selected_container_index(self, selection_offset: int) -> bool:
        """Move the selection without passing the first or last container."""
        if not self.state.running_containers:
            return False
        previous_index = self.state.selected_container_index
        if self.state.selected_container_index is None:
            self.state.selected_container_index = 0
        else:
            self.state.selected_container_index = max(
                0,
                min(
                    len(self.state.running_containers) - 1,
                    self.state.selected_container_index + selection_offset,
                ),
            )
        if self.state.selected_container_index == previous_index:
            return False
        self.docker_manager.prepare_selected_container_details()
        return True

    def open_container_sort_menu(self) -> bool:
        """Open the sorting menu with the active sort choices selected."""
        if self.state.container_sort_menu_state is not None:
            return False
        self.state.container_sort_menu_state = ContainerSortMenuState(
            selected_sort_field=self.state.container_sort_field,
            sort_descending=self.state.container_sort_descending,
        )
        return True

    def close_container_sort_menu(self) -> bool:
        """Close the sorting menu without changing the container order."""
        if self.state.container_sort_menu_state is None:
            return False
        self.state.container_sort_menu_state = None
        return True

    def move_container_sort_menu_selection(self, selection_offset: int) -> bool:
        """Move the selection without passing the first or last sort option."""
        sort_menu_state = self.state.container_sort_menu_state
        if sort_menu_state is None:
            return False
        previous_field = sort_menu_state.selected_sort_field
        previous_index = self.CONTAINER_SORT_FIELDS.index(previous_field)
        selected_index = max(
            0,
            min(
                len(self.CONTAINER_SORT_FIELDS) - 1,
                previous_index + selection_offset,
            ),
        )
        sort_menu_state.selected_sort_field = self.CONTAINER_SORT_FIELDS[selected_index]
        return sort_menu_state.selected_sort_field != previous_field

    def set_container_sort_menu_direction(self, *, descending: bool) -> bool:
        """Choose the sort direction shown in the sorting menu."""
        sort_menu_state = self.state.container_sort_menu_state
        if (
            sort_menu_state is None
            or sort_menu_state.selected_sort_field == ContainerSortField.DOCKER_ORDER
            or sort_menu_state.sort_descending == descending
        ):
            return False
        sort_menu_state.sort_descending = descending
        return True

    def apply_container_sort_menu(self) -> bool:
        """Apply the menu choices while keeping the same container selected."""
        sort_menu_state = self.state.container_sort_menu_state
        if sort_menu_state is None:
            return False

        self.state.container_sort_field = sort_menu_state.selected_sort_field
        self.state.container_sort_descending = (
            sort_menu_state.sort_descending
            if self.state.container_sort_field != ContainerSortField.DOCKER_ORDER
            else False
        )
        self.state.container_sort_menu_state = None
        self.docker_manager.apply_container_sort_to_current_list()
        return True

    def switch_active_detail_tab(self, tab_offset: int) -> bool:
        """Switch tabs, restore cached text, or schedule a missing tab load."""
        active_tab_index = self.DETAIL_TABS.index(self.state.active_detail_tab_name)
        self.state.active_detail_tab_name = self.DETAIL_TABS[
            (active_tab_index + tab_offset) % len(self.DETAIL_TABS)
        ]
        self.docker_manager.prepare_active_detail_tab()
        return True


__all__ = ["UIController"]
