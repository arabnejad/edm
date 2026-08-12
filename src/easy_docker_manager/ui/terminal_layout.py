"""Build and redraw the Urwid terminal layout."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Union

import urwid

from easy_docker_manager.core import AppConfig
from easy_docker_manager.core.log_text import count_line_overlap
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.ui_session_state import FocusArea, UISessionState
from easy_docker_manager.ui.formatting import MarkupSegment


class FocusableDetailLine(urwid.Text):
    """Display one selectable line in the scrollable detail-text view.

    The detail panel displays urwid.Text rows in a scrollable list. A normal
    urwid.Text row cannot receive focus inside that list. EDM needs each detail
    line to receive focus so keyboard navigation can select it, scroll it into
    view, and apply the selected-line color. This subclass makes those text rows
    focusable without changing how their text is displayed.
    """

    def selectable(self) -> bool:
        """Tell the scrollable detail list that this row may receive focus.

        Returning True does not mean the row is always selected. It means the
        list may select this row when EDM moves the detail-line selection.
        """
        return True

    def keypress(self, size: tuple[int, ...], key: str) -> Optional[str]:
        """Leave the key unhandled so EDMApp can process it.

        Urwid requires a selectable widget to implement keypress(). Returning
        the unchanged key allows EDM's keyboard controller to handle navigation
        and shortcuts.
        """
        return key


class TerminalLayoutView:
    """Build EDM's Urwid widgets and redraw them from UI state.

    UIController passes the current UISessionState and prepared detail lines to
    render(). This class updates the title, container list, tabs, detail rows,
    status, footer, and borders. It does not load Docker data or change state.
    Unchanged detail rows are reused to reduce rendering work.
    """

    def __init__(self, app_config: AppConfig) -> None:
        """Create the widgets reused for every EDM redraw."""
        self.app_config = app_config
        self.container_rows: urwid.SimpleFocusListWalker = urwid.SimpleFocusListWalker(
            []
        )
        self.container_list_view = urwid.ListBox(self.container_rows)
        self.container_title_text = urwid.Text(
            "Container: none selected",
            wrap="clip",
        )
        self.detail_tabs_text = urwid.Text("", wrap="clip")
        self.search_query_text = urwid.Text("", wrap="clip")
        self.detail_rows: urwid.SimpleFocusListWalker = urwid.SimpleFocusListWalker([])
        self.detail_text_view = urwid.ListBox(self.detail_rows)
        self._cached_detail_view_key: Optional[tuple[Optional[str], TabName, str]] = (
            None
        )
        self._cached_detail_lines: list[str] = []
        self._cached_detail_line_widgets: list[FocusableDetailLine] = []
        self.detail_status_text = urwid.Text("", wrap="clip")
        self.shortcut_footer_text = urwid.Text("", wrap="clip")
        self.container_panel: Optional[urwid.AttrMap] = None
        self.detail_panel: Optional[urwid.AttrMap] = None
        self.layout = self._build_layout()

    def build_palette(self) -> list[tuple[str, str, str]]:
        """Return the named colors passed to the Urwid main loop."""
        return [
            ("app_title", "light blue,bold", "default"),
            ("footer", "light blue,bold", "default"),
            ("shortcut_key", "black,bold", "light green"),
            ("key", "yellow,bold", "default"),
            ("title_border", "light blue,bold", "default"),
            ("border_active", "white,bold", "default"),
            ("border_inactive", "dark gray", "default"),
            ("panel_header", "light gray", "default"),
            ("title", "light cyan,bold", "default"),
            ("accent", "yellow,bold", "default"),
            ("host", "light cyan", "default"),
            ("selected", "white,bold", "dark magenta"),
            ("selected_inactive", "white", "dark gray"),
            ("detail_selected", "black", "light gray"),
            ("container", "light gray", "default"),
            ("container_status", "light green", "default"),
            ("tab", "white", "default"),
            ("active_detail_tab", "black,bold", "white"),
            ("status", "dark gray", "default"),
            ("muted", "dark gray", "default"),
            ("value", "light cyan", "default"),
            ("status_ok", "light green", "default"),
            ("highlight", "black", "yellow"),
            ("error", "light red", "default"),
            ("log_time", "light cyan", "default"),
            ("log_info", "light gray", "default"),
            ("log_debug", "dark gray", "default"),
            ("log_warning", "yellow", "default"),
            ("log_error", "light red,bold", "default"),
            ("log_number", "light cyan", "default"),
            ("log_http", "light green", "default"),
        ]

    def render(
        self,
        state: UISessionState,
        detail_lines: list[str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> None:
        """Redraw the screen from current UI state and prepared detail lines."""
        self._update_panel_border_styles(state)
        self._render_container_list(state)
        self._render_detail_header(state)
        self._render_detail_lines(state, detail_lines, format_detail_line)
        self.detail_status_text.set_text(state.status_message)

    def focus_detail_line(self, index: int) -> None:
        """Move focus to an available row in the scrollable detail list."""
        if self.detail_rows:
            self.detail_rows.set_focus(min(index, len(self.detail_rows) - 1))

    def _build_layout(self) -> urwid.Widget:
        """Build the container pane, detail pane, and shortcut footer."""
        container_header = urwid.Pile(
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
        container_footer = urwid.Text(
            [
                ("muted", "Refresh "),
                ("value", f"{self.app_config.refresh_interval:g}s"),
                ("muted", " | Logs "),
                ("value", f"{self.app_config.log_tail}"),
                ("muted", " lines"),
            ],
            wrap="clip",
        )
        container_frame = urwid.Frame(
            self.container_list_view,
            header=container_header,
            footer=urwid.AttrMap(container_footer, "status"),
        )
        container_column = urwid.Pile(
            [
                ("pack", self._build_title_panel()),
                (
                    "weight",
                    1,
                    self._build_focusable_panel(
                        container_frame,
                        FocusArea.CONTAINERS,
                    ),
                ),
            ]
        )

        detail_header = urwid.Pile(
            [
                (
                    "pack",
                    urwid.AttrMap(self.container_title_text, "panel_header"),
                ),
                ("pack", urwid.Text("", wrap="clip")),
                ("pack", self.detail_tabs_text),
                ("pack", self.search_query_text),
            ]
        )
        detail_frame = urwid.Frame(
            self.detail_text_view,
            header=detail_header,
            footer=urwid.AttrMap(self.detail_status_text, "status"),
        )
        main_columns = urwid.Columns(
            [
                ("weight", 35, container_column),
                (
                    "weight",
                    65,
                    self._build_focusable_panel(
                        detail_frame,
                        FocusArea.DETAIL,
                    ),
                ),
            ],
            dividechars=1,
            focus_column=0,
        )
        self.shortcut_footer_text.set_text(
            [
                ("shortcut_key", " q "),
                ("footer", " Quit  "),
                ("shortcut_key", " Enter "),
                ("footer", " Detail  "),
                ("shortcut_key", " Esc "),
                ("footer", " Containers  "),
                ("shortcut_key", " [ "),
                ("footer", " Previous Tab  "),
                ("shortcut_key", " ] "),
                ("footer", " Next Tab  "),
                ("shortcut_key", " / "),
                ("footer", " Search"),
            ]
        )
        return urwid.Frame(
            main_columns,
            footer=urwid.AttrMap(self.shortcut_footer_text, "footer"),
        )

    def _build_title_panel(self) -> urwid.Widget:
        """Build the title box shown above the container list."""
        title = urwid.AttrMap(
            urwid.Text("Easy Docker Manager", align="center", wrap="clip"),
            "app_title",
        )
        return urwid.AttrMap(urwid.LineBox(title), "title_border")

    def _build_focusable_panel(
        self,
        body: urwid.Widget,
        focus_area: FocusArea,
    ) -> urwid.Widget:
        """Add a border and save it so focus can change its color."""
        panel = urwid.AttrMap(urwid.LineBox(body), "border_inactive")
        if focus_area == FocusArea.CONTAINERS:
            self.container_panel = panel
        else:
            self.detail_panel = panel
        return panel

    def _update_panel_border_styles(self, state: UISessionState) -> None:
        """Use the active border color on the pane that owns keyboard focus."""
        container_border_style = (
            "border_active"
            if state.active_focus_area == FocusArea.CONTAINERS
            else "border_inactive"
        )
        detail_border_style = (
            "border_active"
            if state.active_focus_area == FocusArea.DETAIL
            else "border_inactive"
        )
        if self.container_panel is not None:
            self.container_panel.set_attr_map({None: container_border_style})
        if self.detail_panel is not None:
            self.detail_panel.set_attr_map({None: detail_border_style})

    def _render_container_list(self, state: UISessionState) -> None:
        """Rebuild the container rows and restore the current selection."""
        rows: list[urwid.Widget] = []
        for index, container in enumerate(state.running_containers):
            if index == state.selected_container_index:
                text = f"> {container.name} ({container.status})"
                attr = (
                    "selected"
                    if state.active_focus_area == FocusArea.CONTAINERS
                    else "selected_inactive"
                )
                widget: urwid.Widget = urwid.AttrMap(
                    urwid.Text(text, wrap="clip"),
                    attr,
                )
            else:
                row_markup: list[MarkupSegment] = [
                    ("muted", "  "),
                    ("container", container.name),
                    ("muted", " ("),
                    ("container_status", container.status),
                    ("muted", ")"),
                ]
                widget = urwid.Text(row_markup, wrap="clip")
            rows.append(widget)
        if not rows:
            rows.append(urwid.Text(("muted", "No running containers."), wrap="clip"))
        self.container_rows[:] = rows
        focus = (
            state.selected_container_index
            if state.selected_container_index is not None
            else 0
        )
        if rows:
            self.container_rows.set_focus(min(focus, len(rows) - 1))

    def _render_detail_header(self, state: UISessionState) -> None:
        """Update the container title, tab names, and current search text."""
        container_name = (
            state.selected_container_summary.name
            if state.selected_container_summary
            else "none selected"
        )
        self.container_title_text.set_text(
            [("accent", "Container: "), ("title", container_name)]
        )

        tab_markup: list[MarkupSegment] = [("muted", " ")]
        for tab in TabName:
            label = f" {tab.value.title()} "
            if tab == state.active_detail_tab_name:
                tab_markup.extend([("active_detail_tab", label), ("muted", " ")])
            else:
                tab_markup.extend([("tab", label), ("muted", " ")])
        self.detail_tabs_text.set_text(tab_markup)

        container_tab_key = state.selected_container_tab_key
        query = (
            state.tab_search_queries.get(container_tab_key, "")
            if container_tab_key is not None
            else ""
        )
        if state.is_search_active:
            self.search_query_text.set_text([("key", "/"), ("selected", query)])
        elif query:
            self.search_query_text.set_text([("muted", "/"), ("value", query)])
        else:
            self.search_query_text.set_text(("muted", ""))

    def _render_detail_lines(
        self,
        state: UISessionState,
        lines: list[str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> None:
        """Show the prepared detail rows and highlight the selected one."""
        container_tab_key = state.selected_container_tab_key
        query = (
            state.tab_search_queries.get(container_tab_key, "")
            if container_tab_key is not None
            else ""
        )
        detail_view_key = (
            state.selected_container_id,
            state.active_detail_tab_name,
            query,
        )
        detail_line_widgets = self._get_or_build_detail_line_widgets(
            lines or [""],
            detail_view_key,
            format_detail_line,
        )
        rows: list[urwid.Widget] = list(detail_line_widgets)
        selected_index = min(state.detail_selected_line_index, len(rows) - 1)
        if state.active_focus_area == FocusArea.DETAIL:
            rows[selected_index] = urwid.AttrMap(
                rows[selected_index],
                "detail_selected",
            )
        self.detail_rows[:] = rows
        self.detail_rows.set_focus(selected_index)

    def _get_or_build_detail_line_widgets(
        self,
        lines: list[str],
        detail_view_key: tuple[Optional[str], TabName, str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> list[FocusableDetailLine]:
        """Reuse existing row widgets when their text and formatting still match.

        A container, tab, or search-query change rebuilds every row. During log
        updates, rows that are still present are reused and widgets are created
        only for new lines.
        """
        if (
            detail_view_key == self._cached_detail_view_key
            and lines == self._cached_detail_lines
        ):
            return self._cached_detail_line_widgets

        if detail_view_key != self._cached_detail_view_key:
            detail_line_widgets = [
                self._build_detail_line_widget(line, format_detail_line)
                for line in lines
            ]
        else:
            overlap = count_line_overlap(self._cached_detail_lines, lines)
            retained_line_widgets = (
                self._cached_detail_line_widgets[-overlap:] if overlap else []
            )
            detail_line_widgets = [
                *retained_line_widgets,
                *(
                    self._build_detail_line_widget(line, format_detail_line)
                    for line in lines[overlap:]
                ),
            ]

        self._cached_detail_view_key = detail_view_key
        self._cached_detail_lines = list(lines)
        self._cached_detail_line_widgets = detail_line_widgets
        return detail_line_widgets

    @staticmethod
    def _build_detail_line_widget(
        line: str,
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> FocusableDetailLine:
        """Build one focusable detail row from prepared line markup."""
        return FocusableDetailLine(format_detail_line(line), wrap="any")


__all__ = ["FocusableDetailLine", "TerminalLayoutView"]
