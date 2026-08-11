"""Apply UI navigation rules and prepare state for rendering."""

from __future__ import annotations

from typing import Optional

from easy_docker_manager.app.scheduler import BackgroundTaskScheduler
from easy_docker_manager.core import ContainerSummary
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import UISessionState
from easy_docker_manager.ui.formatting import DetailTabTextFormatter
from easy_docker_manager.ui.terminal_layout import TerminalLayoutView


class UIController:
    """Handle navigation that affects state, data loading, and rendering.

    KeyboardController handles individual keys. This class moves container and
    detail selections, switches tabs, prepares visible text, asks the scheduler
    for missing data, and sends the resulting state to TerminalLayoutView.
    """

    DETAIL_TABS = tuple(TabName)

    def __init__(
        self,
        state: UISessionState,
        terminal_layout_view: TerminalLayoutView,
        detail_tab_text_formatter: DetailTabTextFormatter,
        scheduler: BackgroundTaskScheduler,
    ) -> None:
        self.state = state
        self.terminal_layout_view = terminal_layout_view
        self.detail_tab_text_formatter = detail_tab_text_formatter
        self.scheduler = scheduler

    @staticmethod
    def _estimate_detail_page_height(
        terminal_size: Optional[tuple[int, ...]],
    ) -> int:
        """Estimate how many detail rows fit on one page."""
        if terminal_size and len(terminal_size) >= 2:
            return max(1, terminal_size[1] - 5)
        return 20

    def render_current_state(self) -> None:
        """Prepare the active tab lines and redraw the terminal view."""
        detail_lines = self.get_visible_detail_lines()
        self.state.keep_detail_selection_in_bounds(len(detail_lines))
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

    def get_visible_detail_lines(self) -> list[str]:
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

    def move_detail_selection(
        self,
        key: str,
        terminal_size: Optional[tuple[int, ...]] = None,
    ) -> bool:
        """Move through detail lines and pause log following when moving upward."""
        previous_index = self.state.detail_selected_line_index
        previous_follow = self.state.follow_log_tail
        line_count = max(1, len(self.get_visible_detail_lines()))
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
        self.state.keep_detail_selection_in_bounds(line_count)
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

    def select_last_detail_line(self) -> bool:
        """Select the last visible detail line."""
        previous_index = self.state.detail_selected_line_index
        lines = self.get_visible_detail_lines()
        self.state.detail_selected_line_index = max(0, len(lines) - 1)
        self.terminal_layout_view.focus_detail_line(
            self.state.detail_selected_line_index
        )
        return self.state.detail_selected_line_index != previous_index

    def move_container_selection(self, selection_offset: int) -> bool:
        """Move container selection by an offset without leaving the list bounds."""
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
        self._handle_container_selection_change()
        return True

    def switch_detail_tab(self, tab_offset: int) -> bool:
        """Switch tabs, restore cached text, or schedule a missing tab load."""
        active_tab_index = self.DETAIL_TABS.index(self.state.active_detail_tab_name)
        self.state.active_detail_tab_name = self.DETAIL_TABS[
            (active_tab_index + tab_offset) % len(self.DETAIL_TABS)
        ]
        self.scheduler.reset_log_poll_schedule()
        self.state.detail_selected_line_index = 0
        self.state.follow_log_tail = self.state.active_detail_tab_name == TabName.LOGS
        if (
            self.state.active_detail_tab_name == TabName.LOGS
            and self.state.follow_log_tail
        ):
            self.select_last_detail_line()
        cache_key = self.state.selected_container_tab_key
        if cache_key is not None and cache_key in self.state.tab_content_cache:
            self.state.status_message = (
                f"Loaded {self.state.active_detail_tab_name.value}"
            )
        self.scheduler.schedule_selected_tab_load(force=False)
        return True

    def update_running_containers(
        self,
        running_containers: list[ContainerSummary],
    ) -> bool:
        """Apply a refreshed container list and keep the same id selected."""
        previously_selected_container_id = self.state.selected_container_id
        previous_signature = [
            (item.container_id, item.name, item.status)
            for item in self.state.running_containers
        ]
        running_container_ids = {
            container.container_id for container in running_containers
        }
        self.state.remove_stopped_container_state(running_container_ids)
        self.scheduler.remove_stopped_container_log_tracking(running_container_ids)

        refreshed_signature = [
            (item.container_id, item.name, item.status) for item in running_containers
        ]
        if refreshed_signature == previous_signature:
            if (
                not running_containers
                and self.state.status_message != "No running containers."
            ):
                self.state.status_message = "No running containers."
                return True
            if running_containers and self.state.status_message.startswith(
                "Container refresh failed:"
            ):
                self.state.status_message = (
                    f"{len(running_containers)} running containers"
                )
                return True
            return False

        self.state.running_containers = running_containers
        if not self.state.running_containers:
            self.state.selected_container_index = None
            self.state.status_message = "No running containers."
            return True

        self.state.selected_container_index = self.state.find_running_container_index(
            previously_selected_container_id
        )
        if self.state.selected_container_index is None:
            self.state.selected_container_index = 0

        self.state.status_message = (
            f"{len(self.state.running_containers)} running containers"
        )
        if (
            self.state.selected_container_id != previously_selected_container_id
            or previously_selected_container_id is None
        ):
            self._handle_container_selection_change()
        return True

    def _handle_container_selection_change(self) -> bool:
        """Reset detail navigation and load the newly selected container tab."""
        self.scheduler.reset_log_poll_schedule()
        self.state.detail_selected_line_index = 0
        self.state.follow_log_tail = True
        cache_key = self.state.selected_container_tab_key
        has_cached_content = (
            cache_key is not None and cache_key in self.state.tab_content_cache
        )
        if self.state.active_detail_tab_name == TabName.LOGS and has_cached_content:
            self.select_last_detail_line()
        if has_cached_content:
            self.state.status_message = (
                f"Loaded {self.state.active_detail_tab_name.value}"
            )
        self.scheduler.schedule_selected_tab_load(force=not has_cached_content)
        return True


__all__ = ["UIController"]
