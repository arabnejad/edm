"""Build and update the selected container details shown on the right."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Union

import urwid

from easy_docker_manager.core.log_text import count_repeated_lines_between_batches
from easy_docker_manager.core.tabs import TabName
from easy_docker_manager.core.terminal_session_state import (
    FocusArea,
    TerminalSessionState,
)
from easy_docker_manager.ui.formatting import MarkupSegment


class FocusableDetailLine(urwid.Text):
    """Display one detail line that keyboard navigation can select.

    A normal urwid.Text row cannot receive focus in a scrollable list. EDM
    needs focusable rows so Up, Down, Page Up, and Page Down can select a line
    and keep it visible. The row returns every key unchanged because EDMApp,
    rather than the row itself, handles keyboard input.
    """

    def selectable(self) -> bool:
        """Allow the scrollable detail view to select this row."""
        return True

    def keypress(self, size: tuple[int, ...], key: str) -> Optional[str]:
        """Return the key unchanged so EDMApp can handle it."""
        return key


class SelectedContainerDetailsPanel:
    """Display details for the container selected in the left panel.

    TerminalLayoutView passes in text prepared by TerminalController. The panel
    shows the container name, tabs, search query, scrollable content, and status
    message. It reuses existing rows when possible, especially as new log lines
    arrive, to avoid rebuilding every Urwid text widget.
    """

    def __init__(self) -> None:
        self.container_title_text = urwid.Text("Container: none selected", wrap="clip")
        self.detail_tabs_text = urwid.Text("", wrap="clip")
        self.search_query_text = urwid.Text("", wrap="clip")
        self.detail_status_text = urwid.Text("", wrap="clip")
        self.detail_rows: urwid.SimpleFocusListWalker = urwid.SimpleFocusListWalker([])
        self.detail_text_view = urwid.ListBox(self.detail_rows)
        self.panel = urwid.AttrMap(
            urwid.LineBox(self._build_container_details_frame()),
            "border_inactive",
        )
        self.widget = self.panel

        self._cached_view_key: Optional[tuple[Optional[str], TabName, str]] = None
        self._cached_lines: list[str] = []
        self._cached_line_widgets: list[FocusableDetailLine] = []

    def render(
        self,
        state: TerminalSessionState,
        detail_lines: list[str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> None:
        """Redraw the details panel from the current session state and lines."""
        self._update_container_name_tabs_and_search_text(state)
        self._update_visible_tab_lines_and_focus(
            state,
            detail_lines,
            format_detail_line,
        )
        self.detail_status_text.set_text(state.status_message)
        border_style = (
            "border_active"
            if state.active_focus_area == FocusArea.DETAIL
            else "border_inactive"
        )
        self.panel.set_attr_map({None: border_style})

    def move_focus_to_selected_detail_line(self, line_index: int) -> None:
        """Move visual focus to the selected line so it remains visible.

        TerminalLayoutView calls this after TerminalController changes the
        selected line index. If the index is beyond the available rows, focus
        moves to the final row instead.
        """
        if self.detail_rows:
            self.detail_rows.set_focus(min(line_index, len(self.detail_rows) - 1))

    def _build_container_details_frame(self) -> urwid.Widget:
        """Build the selected container header, tab content, and status footer."""
        header = urwid.Pile(
            [
                ("pack", urwid.AttrMap(self.container_title_text, "panel_header")),
                ("pack", urwid.Text("", wrap="clip")),
                ("pack", self.detail_tabs_text),
                ("pack", self.search_query_text),
            ]
        )
        return urwid.Frame(
            self.detail_text_view,
            header=header,
            footer=urwid.AttrMap(self.detail_status_text, "status"),
        )

    def _update_container_name_tabs_and_search_text(
        self,
        state: TerminalSessionState,
    ) -> None:
        """Update the selected container name, tab labels, and search text."""
        selected_container = state.selected_container_summary
        container_name = (
            selected_container.name if selected_container else "none selected"
        )
        self.container_title_text.set_text(
            [("accent", "Container: "), ("title", container_name)]
        )

        tab_text: list[MarkupSegment] = [("muted", " ")]
        for tab_name in TabName:
            label = f" {tab_name.value.title()} "
            style = (
                "active_detail_tab"
                if tab_name == state.active_detail_tab_name
                else "tab"
            )
            tab_text.extend([(style, label), ("muted", " ")])
        self.detail_tabs_text.set_text(tab_text)

        selected_tab_key = state.selected_container_tab_key
        search_query = (
            state.tab_search_queries.get(selected_tab_key, "")
            if selected_tab_key is not None
            else ""
        )
        if state.is_search_active:
            self.search_query_text.set_text([("key", "/"), ("selected", search_query)])
        elif search_query:
            self.search_query_text.set_text([("muted", "/"), ("value", search_query)])
        else:
            self.search_query_text.set_text(("muted", ""))

    def _update_visible_tab_lines_and_focus(
        self,
        state: TerminalSessionState,
        lines: list[str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> None:
        """Show the active tab's lines and focus its selected line.

        render() calls this whenever the right panel changes. It reuses existing
        rows where possible, highlights the selected line, and keeps it visible.
        TerminalSessionState remains the source of the selected line index.
        """
        selected_tab_key = state.selected_container_tab_key
        search_query = (
            state.tab_search_queries.get(selected_tab_key, "")
            if selected_tab_key is not None
            else ""
        )
        view_key = (
            state.selected_container_id,
            state.active_detail_tab_name,
            search_query,
        )
        line_widgets = self._get_cached_or_build_tab_display_lines(
            lines or [""],
            view_key,
            format_detail_line,
        )
        displayed_rows: list[urwid.Widget] = list(line_widgets)
        selected_line_index = min(
            state.detail_selected_line_index,
            len(displayed_rows) - 1,
        )
        if state.active_focus_area == FocusArea.DETAIL:
            displayed_rows[selected_line_index] = urwid.AttrMap(
                displayed_rows[selected_line_index],
                "detail_selected",
            )
        self.detail_rows[:] = displayed_rows
        self.detail_rows.set_focus(selected_line_index)

    def _get_cached_or_build_tab_display_lines(
        self,
        lines: list[str],
        view_key: tuple[Optional[str], TabName, str],
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> list[FocusableDetailLine]:
        """Return cached tab display lines or build the lines that changed.

        Switching container, tab, or query builds a fresh list. A log update
        often removes lines from the top and adds lines at the bottom. Rows that
        still match the previous update are reused.
        """
        if view_key == self._cached_view_key and lines == self._cached_lines:
            return self._cached_line_widgets

        if view_key != self._cached_view_key:
            line_widgets = [
                self._build_tab_display_line(line, format_detail_line) for line in lines
            ]
        else:
            repeated_line_count = count_repeated_lines_between_batches(
                self._cached_lines,
                lines,
            )
            retained_widgets = (
                self._cached_line_widgets[-repeated_line_count:]
                if repeated_line_count
                else []
            )
            line_widgets = [
                *retained_widgets,
                *(
                    self._build_tab_display_line(line, format_detail_line)
                    for line in lines[repeated_line_count:]
                ),
            ]

        self._cached_view_key = view_key
        self._cached_lines = list(lines)
        self._cached_line_widgets = line_widgets
        return line_widgets

    @staticmethod
    def _build_tab_display_line(
        line: str,
        format_detail_line: Callable[[str], Union[str, list[MarkupSegment]]],
    ) -> FocusableDetailLine:
        """Build one focusable display line from its text and formatting."""
        return FocusableDetailLine(format_detail_line(line), wrap="any")


__all__ = ["FocusableDetailLine", "SelectedContainerDetailsPanel"]
