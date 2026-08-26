"""Build the container sorting menu."""

from __future__ import annotations

import urwid

from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    ContainerSortMenuState,
)


def build_container_sort_popup_menu(
    menu_state: ContainerSortMenuState,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the current sorting choices above the main terminal layout."""
    sort_field_rows: list[urwid.Widget] = []
    for sort_field in ContainerSortField:
        is_selected = sort_field == menu_state.selected_sort_field
        prefix = "> " if is_selected else "  "
        style = "sort_menu_selected" if is_selected else "sort_menu"
        sort_field_rows.append(
            urwid.AttrMap(
                urwid.Text(f"{prefix}{sort_field.value}", wrap="clip"),
                style,
            )
        )

    if menu_state.selected_sort_field == ContainerSortField.DOCKER_ORDER:
        direction = "Not applicable"
    else:
        direction = "Descending" if menu_state.sort_descending else "Ascending"

    menu_rows = [
        *sort_field_rows,
        urwid.Divider("─"),
        urwid.Text([("muted", "Direction: "), ("value", direction)]),
        urwid.Divider("─"),
        urwid.Text("Up/Down Field   Left/Right Direction", wrap="clip"),
        urwid.Text("Enter Apply     Esc Cancel", wrap="clip"),
    ]
    menu = urwid.AttrMap(
        urwid.LineBox(
            urwid.Filler(urwid.Pile(menu_rows), valign="top"),
            title="Sort Containers",
            title_attr="sort_menu_title",
        ),
        "sort_menu",
    )
    return urwid.Overlay(
        menu,
        background_widget,
        align="center",
        width=48,
        valign="middle",
        height=12,
    )


__all__ = ["build_container_sort_popup_menu"]
