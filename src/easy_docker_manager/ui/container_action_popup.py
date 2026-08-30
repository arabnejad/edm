"""Build the Stop and Restart popup for one running container."""

from __future__ import annotations

import urwid

from easy_docker_manager.core.container_actions import (
    ContainerActionMenuState,
    ContainerLifecycleAction,
)


def build_container_action_popup_menu(
    menu_state: ContainerActionMenuState,
    background_widget: urwid.Widget,
) -> urwid.Overlay:
    """Place the container action menu above the main terminal layout."""
    if menu_state.is_awaiting_confirmation:
        content = _build_confirmation_content(menu_state)
        popup_height = 10
    else:
        content = _build_action_selection_content(menu_state)
        popup_height = 8 + len(menu_state.available_actions)

    popup = urwid.AttrMap(
        urwid.LineBox(
            urwid.Filler(content, valign="top"),
            title="Container Actions",
            title_attr="container_action_menu_title",
        ),
        "container_action_menu",
    )
    return urwid.Overlay(
        popup,
        background_widget,
        align="center",
        width=58,
        valign="middle",
        height=popup_height,
    )


def _build_action_selection_content(
    menu_state: ContainerActionMenuState,
) -> urwid.Pile:
    """Build the container name, action choices, and menu keys."""
    action_rows: list[urwid.Widget] = []
    for index, action in enumerate(menu_state.available_actions):
        action_text = f"> {action.display_name} container"
        if index == menu_state.selected_action_index:
            action_rows.append(
                urwid.AttrMap(
                    urwid.Text(action_text, wrap="clip"),
                    "container_action_menu_selected",
                )
            )
        else:
            action_rows.append(urwid.Text(f"  {action.display_name} container"))

    return urwid.Pile(
        [
            urwid.Text(
                [
                    ("muted", "Container: "),
                    ("value", menu_state.container_name),
                ],
                wrap="clip",
            ),
            urwid.Text(""),
            *action_rows,
            urwid.AttrMap(urwid.Divider("─"), "title_border"),
            urwid.Text("Up/Down Select    Enter Continue    Esc Cancel"),
        ]
    )


def _build_confirmation_content(
    menu_state: ContainerActionMenuState,
) -> urwid.Pile:
    """Build the warning shown before EDM changes the container state."""
    action = menu_state.selected_action
    return urwid.Pile(
        [
            urwid.Text(
                [
                    ("container_action_menu_title", action.display_name),
                    f' container "{menu_state.container_name}"?',
                ],
                wrap="clip",
            ),
            urwid.Text(""),
            urwid.Text(_get_action_explanation(action), wrap="space"),
            urwid.AttrMap(urwid.Divider("─"), "title_border"),
            urwid.Text("Enter Confirm    Esc Cancel"),
        ]
    )


def _get_action_explanation(action: ContainerLifecycleAction) -> str:
    """Return the short explanation shown before one action runs."""
    if action == ContainerLifecycleAction.STOP:
        return "The container will stop and disappear from the running-container list."
    return "The container will restart with its existing Docker configuration."


__all__ = ["build_container_action_popup_menu"]
