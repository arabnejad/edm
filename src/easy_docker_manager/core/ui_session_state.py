"""Store the UI information used during one run of EDM.

A UI session starts when EDM opens and ends when the application exits. This
module records the running containers, current selection, keyboard focus,
loaded tab text, search queries, and loading errors. Controllers update this
information after user input or completed background work. The terminal view
reads it when drawing the screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.content_cache import ContainerTabKey, LRUTabContentCache
from easy_docker_manager.core.tabs import TabName


class FocusArea(str, Enum):
    """Top-level panes that can receive keyboard focus."""

    CONTAINERS = "containers"
    DETAIL = "detail"


def _create_default_tab_content_cache() -> LRUTabContentCache:
    """Create a cache from AppConfig defaults for standalone UI state."""
    app_config = AppConfig()
    return LRUTabContentCache(
        max_entries=app_config.content_cache_size,
        max_total_bytes=app_config.content_cache_max_bytes,
    )


@dataclass
class UISessionState:
    """Keep the current selection, focus, search, and loaded tab text.

    Controllers update this object after keyboard input or completed background
    work. It contains no Urwid widgets and makes no Docker calls. The terminal
    view reads this same object during each redraw.
    """

    # Running container summaries displayed in the left panel.
    running_containers: list[ContainerSummary] = field(default_factory=list)
    # Index of the selected item in running_containers, or None when empty.
    selected_container_index: Optional[int] = None
    # Sort order currently applied to the container list.
    container_sort_field: ContainerSortField = ContainerSortField.DOCKER_ORDER
    container_sort_descending: bool = False
    # Temporary choices shown while the container sorting menu is open.
    is_container_sort_menu_open: bool = False
    container_sort_menu_field: ContainerSortField = ContainerSortField.DOCKER_ORDER
    container_sort_menu_descending: bool = False
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
    # Whether printable keyboard input is editing the active search query.
    is_search_active: bool = False
    # Loaded tab text keyed by container and detail tab.
    tab_content_cache: LRUTabContentCache = field(
        default_factory=_create_default_tab_content_cache
    )
    # Search text keyed independently for each container and detail tab.
    tab_search_queries: dict[ContainerTabKey, str] = field(default_factory=dict)
    # Container IDs whose logging drivers do not support Docker log reads.
    unreadable_log_container_ids: set[str] = field(default_factory=set)
    # Most recent loading error for each container tab.
    tab_load_errors: dict[ContainerTabKey, str] = field(default_factory=dict)

    @property
    def selected_container_summary(self) -> Optional[ContainerSummary]:
        """Return the selected running-container summary, if the index is valid."""
        if self.selected_container_index is None:
            return None
        if not 0 <= self.selected_container_index < len(self.running_containers):
            return None
        return self.running_containers[self.selected_container_index]

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
        """Return a container's current index in running_containers."""
        if container_id is None:
            return None
        for index, container in enumerate(self.running_containers):
            if container.container_id == container_id:
                return index
        return None

    def keep_detail_selection_in_bounds(self, line_count: int) -> None:
        """Keep the selected detail line within the available line range."""
        if line_count <= 0:
            self.detail_selected_line_index = 0
            return
        self.detail_selected_line_index = max(
            0, min(line_count - 1, self.detail_selected_line_index)
        )

    def remove_stopped_container_state(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Remove saved UI data for containers that are no longer running."""
        self.tab_content_cache.remove_stopped_container_entries(running_container_ids)
        self.tab_search_queries = {
            key: query
            for key, query in self.tab_search_queries.items()
            if not key.container_id or key.container_id in running_container_ids
        }
        self.unreadable_log_container_ids.intersection_update(running_container_ids)
        self.tab_load_errors = {
            key: message
            for key, message in self.tab_load_errors.items()
            if key.container_id in running_container_ids
        }


__all__ = [
    "FocusArea",
    "UISessionState",
]
