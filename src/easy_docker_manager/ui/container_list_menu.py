"""Build the container list options menu."""

from __future__ import annotations

import urwid

from easy_docker_manager.core.container_sorting import (
    ContainerListMenuField,
    ContainerListMenuState,
    ContainerSortField,
)


def build_container_list_popup_menu(
    menu_state: ContainerListMenuState,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the current visibility and sorting choices above the main layout."""
    menu_rows: list[urwid.Widget] = []
    for menu_field in ContainerListMenuField:
        is_selected = menu_field == menu_state.selected_field
        prefix = "> " if is_selected else "  "
        style = "container_list_menu_selected" if is_selected else "container_list_menu"
        menu_rows.append(
            urwid.AttrMap(
                urwid.Text(
                    f"{prefix}{menu_field.value:<12} "
                    f"{_get_container_list_menu_field_value(menu_state, menu_field)}",
                    wrap="clip",
                ),
                style,
            )
        )

    menu_rows.extend(
        [
            urwid.Divider("─"),
            urwid.Text("Up/Down Field   Left/Right Change", wrap="clip"),
            urwid.Text("Enter Apply     Esc Cancel", wrap="clip"),
        ]
    )
    menu = urwid.AttrMap(
        urwid.LineBox(
            urwid.Filler(urwid.Pile(menu_rows), valign="top"),
            title="Container List",
            title_attr="container_list_menu_title",
        ),
        "container_list_menu",
    )
    return urwid.Overlay(
        menu,
        background_widget,
        align="center",
        width=52,
        valign="middle",
        height=9,
    )


def _get_container_list_menu_field_value(
    menu_state: ContainerListMenuState,
    menu_field: ContainerListMenuField,
) -> str:
    """Return the value shown beside one menu field."""
    if menu_field == ContainerListMenuField.VIEW_MODE:
        return menu_state.view_mode.value
    if menu_field == ContainerListMenuField.SORT_FIELD:
        return menu_state.sort_field.value
    if menu_state.sort_field == ContainerSortField.DOCKER_ORDER:
        return "Not applicable"
    return "Descending" if menu_state.sort_descending else "Ascending"


__all__ = ["build_container_list_popup_menu"]
