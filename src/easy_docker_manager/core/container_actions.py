"""Define the container actions available from EDM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContainerAction(str, Enum):
    """Name an action available for the selected container."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    OPEN_SHELL = "open shell"
    RECREATE_COMPOSE_SERVICE = "recreate Compose service"

    @property
    def display_name(self) -> str:
        """Return the action name shown in the container action menu."""
        return {
            ContainerAction.START: "Start",
            ContainerAction.STOP: "Stop",
            ContainerAction.RESTART: "Restart",
            ContainerAction.OPEN_SHELL: "Open shell",
            ContainerAction.RECREATE_COMPOSE_SERVICE: ("Recreate Compose service"),
        }[self]


def get_available_actions_for_container_status(
    container_status: str,
    can_recreate_compose_service: bool = False,
) -> list[ContainerAction]:
    """Return the actions EDM supports for the reported Docker status."""
    normalized_status = container_status.casefold()
    if normalized_status == "running":
        available_actions = [
            ContainerAction.RESTART,
            ContainerAction.OPEN_SHELL,
        ]
        if can_recreate_compose_service:
            available_actions.append(ContainerAction.RECREATE_COMPOSE_SERVICE)
        available_actions.append(ContainerAction.STOP)
        return available_actions
    elif normalized_status in {"created", "exited"}:
        available_actions = [ContainerAction.START]
    else:
        return []

    if can_recreate_compose_service:
        available_actions.append(ContainerAction.RECREATE_COMPOSE_SERVICE)
    return available_actions


@dataclass
class ContainerActionMenuState:
    """Keep the target container and current choice while its menu is open."""

    container_id: str
    container_name: str
    available_actions: list[ContainerAction]
    selected_action_index: int = 0
    is_showing_action_details: bool = False

    @property
    def selected_action(self) -> ContainerAction:
        """Return the action currently highlighted in the menu."""
        return self.available_actions[self.selected_action_index]


__all__ = [
    "ContainerActionMenuState",
    "ContainerAction",
    "get_available_actions_for_container_status",
]
