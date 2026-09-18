"""Define the container actions available from EDM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContainerLifecycleAction(str, Enum):
    """Name an action available for the selected container."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RECREATE_COMPOSE_SERVICE = "recreate Compose service"

    @property
    def display_name(self) -> str:
        """Return the action name shown in the container action menu."""
        return {
            ContainerLifecycleAction.START: "Start",
            ContainerLifecycleAction.STOP: "Stop",
            ContainerLifecycleAction.RESTART: "Restart",
            ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE: (
                "Recreate Compose service"
            ),
        }[self]


def get_available_actions_for_container_status(
    container_status: str,
    can_recreate_compose_service: bool = False,
) -> list[ContainerLifecycleAction]:
    """Return the actions EDM supports for the reported Docker status."""
    normalized_status = container_status.casefold()
    if normalized_status == "running":
        available_actions = [
            ContainerLifecycleAction.RESTART,
            ContainerLifecycleAction.STOP,
        ]
    elif normalized_status in {"created", "exited"}:
        available_actions = [ContainerLifecycleAction.START]
    else:
        return []

    if can_recreate_compose_service:
        if normalized_status == "running":
            available_actions.insert(
                1,
                ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE,
            )
        else:
            available_actions.append(ContainerLifecycleAction.RECREATE_COMPOSE_SERVICE)
    return available_actions


@dataclass
class ContainerActionMenuState:
    """Keep the target container and current choice while its menu is open."""

    container_id: str
    container_name: str
    available_actions: list[ContainerLifecycleAction]
    selected_action_index: int = 0
    is_awaiting_confirmation: bool = False

    @property
    def selected_action(self) -> ContainerLifecycleAction:
        """Return the action currently highlighted in the menu."""
        return self.available_actions[self.selected_action_index]


__all__ = [
    "ContainerActionMenuState",
    "ContainerLifecycleAction",
    "get_available_actions_for_container_status",
]
