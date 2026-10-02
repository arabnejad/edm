"""Build the active-tab export menu."""

from __future__ import annotations

import urwid

from easy_docker_manager.tab_export.definitions import (
    TabExportMenuField,
    TabExportMenuState,
    TabExportPhase,
)
from easy_docker_manager.ui.formatting import MarkupSegment


def build_tab_export_popup_menu(
    menu_state: TabExportMenuState,
    background_widget: urwid.Widget,
    scroll_body: urwid.Scrollable,
) -> urwid.Overlay:
    """Place the export form or its current result message above the layout."""
    if menu_state.phase == TabExportPhase.WRITING:
        rows = [
            urwid.Text("Writing the selected tab to:", wrap="clip"),
            urwid.Text(("value", menu_state.file_path), wrap="any"),
        ]
        instructions = "Please wait for the file write to finish."
    elif menu_state.phase == TabExportPhase.CONFIRMING_OVERWRITE:
        rows = [
            urwid.Text(("export_warning", "This file already exists:"), wrap="clip"),
            urwid.Text(("value", menu_state.file_path), wrap="any"),
        ]
        instructions = "Enter Overwrite   Esc Back"
    else:
        rows = _build_tab_export_form_rows(menu_state)
        instructions = "Up/Down Field   Left/Right Scope\nEnter Export     Esc Cancel"

    scroll_body.original_widget = urwid.Pile(rows)
    footer = urwid.Pile(
        [
            urwid.Divider(),
            urwid.Text(instructions, wrap="clip"),
            urwid.Text("PgUp/PgDn Scroll", wrap="clip"),
        ]
    )

    popup = urwid.AttrMap(
        urwid.LineBox(
            urwid.Frame(scroll_body, footer=footer),
            title=f"Export {menu_state.container_tab_key.tab_name.value}",
            title_attr="export_menu_title",
        ),
        "export_menu",
    )
    return urwid.Overlay(
        popup,
        background_widget,
        align="center",
        width=76,
        valign="middle",
        height=17,
    )


def _build_tab_export_form_rows(
    menu_state: TabExportMenuState,
) -> list[urwid.Widget]:
    """Build the path, scope, warning, and error shown before writing."""
    file_style = (
        "export_menu_selected"
        if menu_state.selected_field == TabExportMenuField.FILE_PATH
        else "export_menu"
    )
    scope_style = (
        "export_menu_selected"
        if menu_state.selected_field == TabExportMenuField.SCOPE
        else "export_menu"
    )
    rows: list[urwid.Widget] = [
        urwid.Text([("muted", "Container: "), ("value", menu_state.container_name)]),
        urwid.Divider(),
        urwid.Text(
            (
                "export_warning",
                "Warning: exported text may contain passwords, tokens, URLs, "
                "or other sensitive data. Review the file before sharing it.",
            ),
            wrap="any",
        ),
        urwid.Divider(),
        urwid.Text(
            (
                file_style,
                (
                    "> File"
                    if menu_state.selected_field == TabExportMenuField.FILE_PATH
                    else "  File"
                ),
            )
        ),
        urwid.Text(_format_export_path(menu_state), wrap="any"),
        urwid.Text(
            (
                scope_style,
                (
                    "> Scope: "
                    if menu_state.selected_field == TabExportMenuField.SCOPE
                    else "  Scope: "
                )
                + menu_state.scope.value,
            ),
            wrap="clip",
        ),
    ]
    if menu_state.error_message:
        rows.extend(
            [
                urwid.Divider(),
                urwid.Text(("error", menu_state.error_message), wrap="any"),
            ]
        )
    return rows


def _format_export_path(menu_state: TabExportMenuState) -> list[MarkupSegment]:
    """Return the path text with a visible cursor at its editing position."""
    cursor_index = min(
        menu_state.file_path_cursor_index,
        len(menu_state.file_path),
    )
    before_cursor = menu_state.file_path[:cursor_index]
    cursor_character = (
        menu_state.file_path[cursor_index]
        if cursor_index < len(menu_state.file_path)
        else " "
    )
    after_cursor = (
        menu_state.file_path[cursor_index + 1 :]
        if cursor_index < len(menu_state.file_path)
        else ""
    )
    return [
        ("value", before_cursor),
        ("export_path_cursor", cursor_character),
        ("value", after_cursor),
    ]


__all__ = ["build_tab_export_popup_menu"]
