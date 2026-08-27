"""Store the data that changes during one EDM terminal session.

A terminal session starts when EDM opens and ends when the application exits.
The state includes the running containers, current selection, active tab,
keyboard focus, loaded text, search queries, open menu, status message, and
Docker request errors.

TerminalController and TabExportController update it after keyboard input. The
Docker request classes save lists, tab content, log updates, and errors after
their requests finish. The view classes read it when drawing the screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)
from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.running_container_list import RunningContainerList
from easy_docker_manager.core.tab_content_cache import TabContentCache
from easy_docker_manager.core.tabs import ContainerTabKey, TabName
from easy_docker_manager.tab_export.definitions import TabExportMenuState


class FocusArea(str, Enum):
    """Top-level panes that can receive keyboard focus."""

    CONTAINERS = "containers"
    DETAIL = "detail"


def _create_default_tab_content_cache() -> TabContentCache:
    """Create a cache from AppConfig defaults for standalone session state."""
    app_config = AppConfig()
    return TabContentCache(
        max_entries=app_config.tab_content_cache_max_entries,
        max_total_bytes=app_config.tab_content_cache_max_bytes,
    )


@dataclass
class TerminalSessionState:
    """Keep all changing data used to draw and control the terminal screen.

    TerminalController and TabExportController update this object after
    keyboard input. The Docker request classes update it when their work
    finishes. This class contains no Urwid widgets and makes no Docker calls;
    the view classes read it during each redraw.
    """

    # Latest Docker list together with the sorted and filtered list shown in EDM.
    running_container_list: RunningContainerList = field(
        default_factory=RunningContainerList
    )
    # Index of the selected item in the displayed container list, or None when empty.
    selected_container_index: Optional[int] = None
    # Text matched against each container's name, image, and status.
    container_filter_query: str = ""
    # Query active before filter editing began. None means editing is inactive.
    container_filter_query_before_editing: Optional[str] = None
    # Sort order currently applied to the container list.
    container_sort_field: ContainerSortField = ContainerSortField.DOCKER_ORDER
    container_sort_descending: bool = False
    # Temporary choices in the container sort menu. None means the menu is closed.
    container_sort_menu_state: Optional[ContainerSortMenuState] = None
    # Current choices in the tab export menu. None means the menu is closed.
    tab_export_menu_state: Optional[TabExportMenuState] = None
    # Detail tab currently displayed in the right panel.
    active_detail_tab_name: TabName = TabName.LOGS
    # Which panel receives keyboard input.
    active_focus_area: FocusArea = FocusArea.CONTAINERS
    # Index of the selected line in the right detail panel.
    detail_selected_line_index: int = 0
    # Whether the Logs tab should remain positioned at its newest line.
    follow_log_tail: bool = True
    # Status text displayed below the right detail panel.
    status_message: str = "Loading containers..."
    # Most recent running-container list refresh error, or None after success.
    container_list_refresh_error_message: Optional[str] = None
    # Whether printable keyboard input is editing the active search query.
    is_search_active: bool = False
    # Loaded tab text keyed by container and detail tab.
    tab_content_cache: TabContentCache = field(
        default_factory=_create_default_tab_content_cache
    )
    # Search text keyed independently for each container and detail tab.
    tab_search_queries: dict[ContainerTabKey, str] = field(default_factory=dict)
    # Container IDs whose logging drivers do not support Docker log reads.
    unreadable_log_container_ids: set[str] = field(default_factory=set)
    # Most recent load or refresh error for each container tab.
    tab_content_error_messages: dict[ContainerTabKey, str] = field(default_factory=dict)

    @property
    def is_editing_container_filter(self) -> bool:
        """Return whether keyboard input is currently editing the filter."""
        return self.container_filter_query_before_editing is not None

    @property
    def selected_container_summary(self) -> Optional[ContainerSummary]:
        """Return the selected running-container summary, if the index is valid."""
        displayed_containers = self.running_container_list.displayed_containers
        if self.selected_container_index is None:
            return None
        if not 0 <= self.selected_container_index < len(displayed_containers):
            return None
        return displayed_containers[self.selected_container_index]

    @property
    def selected_container_id(self) -> Optional[str]:
        """Return the selected container id, or None when nothing is selected."""
        selected_container = self.selected_container_summary
        return selected_container.container_id if selected_container else None

    @property
    def selected_container_tab_key(self) -> Optional[ContainerTabKey]:
        """Return the selected container and active detail tab as one key."""
        if not self.selected_container_id:
            return None
        return ContainerTabKey(
            container_id=self.selected_container_id,
            tab_name=self.active_detail_tab_name,
        )

    def find_running_container_index(
        self,
        container_id: Optional[str],
    ) -> Optional[int]:
        """Return a container's index in the displayed container list."""
        if container_id is None:
            return None
        for index, container in enumerate(
            self.running_container_list.displayed_containers
        ):
            if container.container_id == container_id:
                return index
        return None

    def keep_selected_detail_line_within_available_range(self, line_count: int) -> None:
        """Keep the selected detail line at a valid index.

        The available range starts at index 0 and ends at line_count - 1. For
        example, three displayed lines have valid indexes 0, 1, and 2.
        TerminalController calls this after detail content changes and after
        keyboard navigation. When no lines are available, the selected index
        resets to 0.
        """
        if line_count <= 0:
            self.detail_selected_line_index = 0
            return
        self.detail_selected_line_index = max(
            0, min(line_count - 1, self.detail_selected_line_index)
        )

    def remove_state_for_stopped_containers(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Remove saved session data for containers that are no longer running."""
        self.tab_content_cache.remove_cached_tab_content_for_stopped_containers(
            running_container_ids
        )
        self.tab_search_queries = {
            key: query
            for key, query in self.tab_search_queries.items()
            if not key.container_id or key.container_id in running_container_ids
        }
        self.unreadable_log_container_ids.intersection_update(running_container_ids)
        self.tab_content_error_messages = {
            key: message
            for key, message in self.tab_content_error_messages.items()
            if key.container_id in running_container_ids
        }
        if (
            self.tab_export_menu_state is not None
            and self.tab_export_menu_state.container_tab_key.container_id
            not in running_container_ids
        ):
            self.tab_export_menu_state = None


__all__ = [
    "FocusArea",
    "TerminalSessionState",
]
