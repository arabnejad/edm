"""Build and update the running-container list shown on the left."""

from __future__ import annotations

from typing import Optional

import urwid

from easy_docker_manager.core.config import AppConfig
from easy_docker_manager.core.container_sorting import ContainerSortField
from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)
from easy_docker_manager.diagnostics import build_edm_title
from easy_docker_manager.ui.formatting import MarkupSegment

GITHUB_REPOSITORY_TEXT = "github.com/arabnejad/edm"


class RunningContainerListPanel:
    """Draw the running containers and the controls shown above the list.

    TerminalLayoutView creates this panel once. On each redraw, render() reads
    TerminalSessionState and updates the existing Urwid widgets. This class
    only changes what is shown; it does not select containers or call Docker.
    """

    def __init__(self, app_config: AppConfig, installed_edm_version: str) -> None:
        self.app_config = app_config
        self.application_title = build_edm_title(installed_edm_version)
        self.container_rows: urwid.SimpleFocusListWalker = urwid.SimpleFocusListWalker(
            []
        )
        self.container_list_view = urwid.ListBox(self.container_rows)
        self.container_filter_text = urwid.Text("", wrap="clip")
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
        """Redraw the container rows, controls, focus, and border."""
        self._rebuild_container_list_and_focus_on_selected_container(state)
        self._update_container_filter_display_text(state)
        self._update_selected_sort_display_text(state)
        border_style = (
            "border_active"
            if state.active_focus_area == FocusArea.CONTAINERS
            else "border_inactive"
        )
        self.panel.set_attr_map({None: border_style})

    def _build_title_panel(self) -> urwid.Widget:
        """Build the application title and repository link."""
        title_content = urwid.Pile(
            [
                (
                    "pack",
                    urwid.AttrMap(
                        urwid.Text(
                            self.application_title,
                            align="center",
                            wrap="clip",
                        ),
                        "app_title",
                    ),
                ),
                ("pack", urwid.Text("")),
                (
                    "pack",
                    urwid.AttrMap(
                        urwid.Text(
                            GITHUB_REPOSITORY_TEXT,
                            align="center",
                            wrap="clip",
                        ),
                        "repository_link",
                    ),
                ),
            ]
        )
        return urwid.AttrMap(urwid.LineBox(title_content), "title_border")

    def _build_container_frame(self) -> urwid.Widget:
        """Build the host details, list controls, container rows, and footer."""
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
                ("pack", self.container_filter_text),
                ("pack", self.container_sort_text),
                ("pack", urwid.AttrMap(urwid.Divider("─"), "muted")),
            ]
        )
        footer = urwid.Text(
            [
                ("muted", "Refresh "),
                (
                    "value",
                    f"{self.app_config.container_list_refresh_interval_seconds:g}s",
                ),
                ("muted", " | Logs "),
                ("value", f"{self.app_config.initial_log_tail_lines}"),
                ("muted", " lines"),
            ],
            wrap="clip",
        )
        return urwid.Frame(
            self.container_list_view,
            header=header,
            footer=urwid.AttrMap(footer, "status"),
        )

    def _rebuild_container_list_and_focus_on_selected_container(
        self, state: TerminalSessionState
    ) -> None:
        """Replace the list rows and focus the selected container.

        A Compose project heading is kept with its first container row. This
        keeps one selectable list item per container, so the row index still
        matches selected_container_index. This method moves Urwid's focus but
        does not change the selected index stored in the session state.
        """
        displayed_containers = state.running_container_list.displayed_containers

        # Count each project's containers before building its heading. For
        # example, a project with two containers is shown as "example (2)".
        containers_per_compose_project: dict[str, int] = {}
        for container in displayed_containers:
            if container.compose_project_name is not None:
                containers_per_compose_project[container.compose_project_name] = (
                    containers_per_compose_project.get(
                        container.compose_project_name,
                        0,
                    )
                    + 1
                )

        rows: list[urwid.Widget] = []
        previous_compose_project_name: Optional[str] = None
        for index, container in enumerate(displayed_containers):
            container_row = self._build_container_row(state, index, container)
            compose_project_name = container.compose_project_name

            # RunningContainerList has already grouped the containers. A new
            # project name means this row starts the next section.
            starts_new_container_section = (
                compose_project_name != previous_compose_project_name
            )
            container_section_rows: list[urwid.Widget] = []
            if starts_new_container_section and index > 0:
                container_section_rows.append(
                    urwid.AttrMap(urwid.Divider("─"), "muted")
                )
            if starts_new_container_section and compose_project_name is not None:
                compose_project_container_count = containers_per_compose_project[
                    compose_project_name
                ]
                container_section_rows.append(
                    urwid.Text(
                        [
                            ("title", f" {compose_project_name}"),
                            (
                                "muted",
                                f" ({compose_project_container_count})",
                            ),
                        ],
                        wrap="clip",
                    )
                )
            container_section_rows.append(container_row)

            # Keep the heading and separator with the first container in the
            # section. Up and Down can then skip straight between containers.
            rows.append(
                urwid.Pile([("pack", row) for row in container_section_rows])
                if len(container_section_rows) > 1
                else container_row
            )
            previous_compose_project_name = compose_project_name

        if not rows:
            empty_message = "No running containers."
            if (
                state.container_filter_query
                and state.running_container_list.unfiltered_container_count > 0
            ):
                empty_message = (
                    f'No running containers match "{state.container_filter_query}".'
                )
            rows.append(urwid.Text(("muted", empty_message), wrap="clip"))

        self.container_rows[:] = rows
        selected_index = state.selected_container_index or 0
        self.container_rows.set_focus(min(selected_index, len(rows) - 1))

    @staticmethod
    def _build_container_row(
        state: TerminalSessionState,
        container_index: int,
        container: ContainerSummary,
    ) -> urwid.Widget:
        """Build one container row with its selected or normal style."""
        if container_index == state.selected_container_index:
            selected_style = (
                "selected"
                if state.active_focus_area == FocusArea.CONTAINERS
                else "selected_inactive"
            )
            return urwid.AttrMap(
                urwid.Text(
                    f"> {container.name} ({container.status})",
                    wrap="clip",
                ),
                selected_style,
            )

        row_text: list[MarkupSegment] = [
            ("muted", "  "),
            ("container", container.name),
            ("muted", " ("),
            ("container_status", container.status),
            ("muted", ")"),
        ]
        return urwid.Text(row_text, wrap="clip")

    def _update_container_filter_display_text(
        self,
        state: TerminalSessionState,
    ) -> None:
        """Show the applied query, match count, and whether input is active."""
        filter_query = state.container_filter_query
        filter_text: list[MarkupSegment] = [
            ("shortcut_key", " f "),
            ("muted", " Filter: "),
        ]
        if filter_query:
            filter_text.extend(
                [
                    ("value", filter_query),
                    (
                        "muted",
                        " "
                        f"({len(state.running_container_list.displayed_containers)}/"
                        f"{state.running_container_list.unfiltered_container_count})",
                    ),
                ]
            )
        else:
            filter_text.append(("muted", "off"))
        if state.is_editing_container_filter:
            filter_text.append(("accent", " [editing]"))
        self.container_filter_text.set_text(filter_text)

    def _update_selected_sort_display_text(self, state: TerminalSessionState) -> None:
        """Show the selected sort field and direction above the container list."""
        sort_field = state.container_sort_field
        sort_text: list[MarkupSegment] = [
            ("shortcut_key", " s "),
            ("muted", " Sort: "),
            ("value", sort_field.value),
        ]
        if sort_field != ContainerSortField.DOCKER_ORDER:
            direction = (
                " descending" if state.container_sort_descending else " ascending"
            )
            sort_text.append(("muted", direction))
        self.container_sort_text.set_text(sort_text)


__all__ = ["RunningContainerListPanel"]
