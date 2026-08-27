"""Build and update the running-container list shown on the left."""

from __future__ import annotations

import urwid

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)
from easy_docker_manager.ui.formatting import MarkupSegment


class RunningContainerListPanel:
    """Display the running-container list and its left-panel controls.

    TerminalLayoutView creates this once and calls render() for each redraw.
    The panel reads TerminalSessionState to update its title, rows, sort summary,
    status text, focus, and border. It does not change the selection or start
    Docker requests.
    """

    def __init__(self, app_config: AppConfig) -> None:
        self.app_config = app_config
        self.container_rows: urwid.SimpleFocusListWalker = urwid.SimpleFocusListWalker(
            []
        )
        self.container_list_view = urwid.ListBox(self.container_rows)
        self.container_sort_text = urwid.Text("", wrap="clip")
        self.panel = urwid.AttrMap(
            urwid.LineBox(self._build_container_frame()),
            "border_inactive",
        )
        self.widget = urwid.Pile(
            [
                ("pack", self._build_title_panel()),
                ("weight", 1, self.panel),
            ]
        )

    def render(self, state: TerminalSessionState) -> None:
        """Update the rows, sort summary, focus, and border from session state."""
        self._rebuild_container_list_and_focus_on_selected_container(state)
        self._update_selected_sort_display_text(state)
        border_style = (
            "border_active"
            if state.active_focus_area == FocusArea.CONTAINERS
            else "border_inactive"
        )
        self.panel.set_attr_map({None: border_style})

    def _build_title_panel(self) -> urwid.Widget:
        """Build the Easy Docker Manager title above the container list."""
        title = urwid.AttrMap(
            urwid.Text("Easy Docker Manager", align="center", wrap="clip"),
            "app_title",
        )
        return urwid.AttrMap(urwid.LineBox(title), "title_border")

    def _build_container_frame(self) -> urwid.Widget:
        """Build the container header, scrollable rows, and footer."""
        header = urwid.Pile(
            [
                (
                    "pack",
                    urwid.Text(
                        [
                            ("accent", "* "),
                            ("host", "localhost"),
                            ("status_ok", " (active)"),
                        ],
                        wrap="clip",
                    ),
                ),
                ("pack", urwid.AttrMap(urwid.Divider("─"), "muted")),
            ]
        )
        footer = urwid.Pile(
            [
                urwid.Text(
                    [
                        ("muted", "Refresh "),
                        ("value", f"{self.app_config.refresh_interval:g}s"),
                        ("muted", " | Logs "),
                        ("value", f"{self.app_config.log_tail}"),
                        ("muted", " lines"),
                    ],
                    wrap="clip",
                ),
                self.container_sort_text,
            ]
        )
        return urwid.Frame(
            self.container_list_view,
            header=header,
            footer=urwid.AttrMap(footer, "status"),
        )

    def _rebuild_container_list_and_focus_on_selected_container(
        self, state: TerminalSessionState
    ) -> None:
        """Rebuild the list and focus its selected container row.

        render() calls this during each panel redraw. It creates rows from the
        running containers, replaces the existing Urwid rows, and moves focus
        to the selected index. It does not change the selected index stored in
        TerminalSessionState.
        """
        rows: list[urwid.Widget] = []
        for index, container in enumerate(state.running_containers):
            if index == state.selected_container_index:
                selected_style = (
                    "selected"
                    if state.active_focus_area == FocusArea.CONTAINERS
                    else "selected_inactive"
                )
                rows.append(
                    urwid.AttrMap(
                        urwid.Text(
                            f"> {container.name} ({container.status})",
                            wrap="clip",
                        ),
                        selected_style,
                    )
                )
                continue

            row_text: list[MarkupSegment] = [
                ("muted", "  "),
                ("container", container.name),
                ("muted", " ("),
                ("container_status", container.status),
                ("muted", ")"),
            ]
            rows.append(urwid.Text(row_text, wrap="clip"))

        if not rows:
            rows.append(urwid.Text(("muted", "No running containers."), wrap="clip"))

        self.container_rows[:] = rows
        selected_index = state.selected_container_index or 0
        self.container_rows.set_focus(min(selected_index, len(rows) - 1))

    def _update_selected_sort_display_text(self, state: TerminalSessionState) -> None:
        """Show the selected sort field and direction below the container list."""
        sort_field = state.container_sort_field
        sort_text: list[MarkupSegment] = [
            ("muted", "Sort: "),
            ("value", sort_field.value),
        ]
        if sort_field != ContainerSortField.DOCKER_ORDER:
            direction = (
                " descending" if state.container_sort_descending else " ascending"
            )
            sort_text.append(("muted", direction))
        self.container_sort_text.set_text(sort_text)


__all__ = ["RunningContainerListPanel"]
