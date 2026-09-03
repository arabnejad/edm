"""Build the Docker context selection popup."""

from __future__ import annotations

import urwid

from easy_docker_manager.core.docker_connections import DockerConnectionMenuState


def build_docker_connection_popup_menu(
    menu_state: DockerConnectionMenuState,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the Docker context list above the main terminal layout."""
    context_rows = [
        _build_docker_context_row(menu_state, index)
        for index in range(len(menu_state.docker_contexts))
    ]
    if not context_rows:
        context_rows.append(urwid.Text(("muted", "No Docker contexts found.")))

    context_list = urwid.ListBox(urwid.SimpleFocusListWalker(context_rows))
    if menu_state.docker_contexts:
        context_list.set_focus(menu_state.selected_context_index)

    selected_context = menu_state.selected_docker_context
    selected_endpoint = selected_context.docker_host if selected_context else "N/A"
    message = menu_state.context_discovery_error_message
    if selected_context is not None:
        message = menu_state.connection_error_messages.get(
            selected_context.context_name,
            "",
        )

    content = urwid.Pile(
        [
            ("weight", 1, context_list),
            ("pack", urwid.AttrMap(urwid.Divider("─"), "title_border")),
            (
                "pack",
                urwid.Text(
                    [("muted", "Endpoint: "), ("value", selected_endpoint)],
                    wrap="clip",
                ),
            ),
            ("pack", urwid.Text(("error", message), wrap="space")),
            ("pack", urwid.AttrMap(urwid.Divider("─"), "title_border")),
            ("pack", urwid.Text("Up/Down Select    Enter Connect    Esc Close")),
        ]
    )
    popup = urwid.AttrMap(
        urwid.LineBox(
            content,
            title="Docker Connections",
            title_attr="docker_connection_menu_title",
        ),
        "docker_connection_menu",
    )
    popup_height = min(22, max(11, len(context_rows) + 9))
    return urwid.Overlay(
        popup,
        background_widget,
        align="center",
        width=88,
        valign="middle",
        height=popup_height,
    )


def _build_docker_context_row(
    menu_state: DockerConnectionMenuState,
    context_index: int,
) -> urwid.Widget:
    """Build one context row with its transport and current status."""
    docker_context = menu_state.docker_contexts[context_index]
    is_selected = context_index == menu_state.selected_context_index
    selection_marker = "> " if is_selected else "  "
    status_text = "Not checked"
    status_style = "muted"
    if docker_context.context_name == menu_state.active_context_name:
        status_text = "Active"
        status_style = "status_ok"
    elif docker_context.context_name == menu_state.context_name_being_validated:
        status_text = "Checking..."
        status_style = "accent"
    elif docker_context.context_name in menu_state.connection_error_messages:
        status_text = "Unavailable"
        status_style = "error"
    elif not docker_context.is_supported:
        status_text = "Unsupported"
        status_style = "muted"

    # The row highlight already sets the colors for all three columns. Applying
    # the status style as well would leave a dark patch in the selected row.
    displayed_status = status_text if is_selected else (status_style, status_text)
    row = urwid.Columns(
        [
            (
                28,
                urwid.Text(
                    f"{selection_marker}{docker_context.display_name}",
                    wrap="clip",
                ),
            ),
            (16, urwid.Text(docker_context.transport_label, wrap="clip")),
            urwid.Text(displayed_status, wrap="clip"),
        ],
        dividechars=1,
    )
    if is_selected:
        return urwid.AttrMap(row, "docker_connection_menu_selected")
    return row


__all__ = ["build_docker_connection_popup_menu"]
