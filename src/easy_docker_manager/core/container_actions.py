"""Define the container actions available from EDM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContainerLifecycleAction(str, Enum):
    """Name an action that changes an existing container's state."""

    STOP = "stop"
    RESTART = "restart"

    @property
    def display_name(self) -> str:
        """Return the action name shown in the container action menu."""
        return self.value.capitalize()


def get_available_actions_for_container_status(
    container_status: str,
) -> list[ContainerLifecycleAction]:
    """Return the actions EDM supports for the reported Docker status."""
    normalized_status = container_status.casefold()
    if normalized_status != "running":
        return []
    return [
        ContainerLifecycleAction.RESTART,
        ContainerLifecycleAction.STOP,
    ]


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
