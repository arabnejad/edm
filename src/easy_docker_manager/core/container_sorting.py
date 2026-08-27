"""Define and apply the available container-list sort orders."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from easy_docker_manager.core.containers import ContainerSummary


class ContainerSortField(str, Enum):
    """Fields users can choose from the container sorting menu."""

    DOCKER_ORDER = "Docker order"
    NAME = "Name"
    IMAGE = "Image"
    STATUS = "Status"
    CREATED_AT = "Creation time"


@dataclass
class ContainerSortMenuState:
    """Store the choices currently shown in the container sorting menu.

    TerminalController creates this object when the menu opens. These temporary
    choices do not change the container list until the user presses Enter.
    Pressing Esc discards them and keeps the current order.
    """

    selected_sort_field: ContainerSortField
    sort_descending: bool


def get_container_list_in_requested_order(
    containers: list[ContainerSummary],
    sort_field: ContainerSortField,
    descending: bool,
) -> list[ContainerSummary]:
    """Return containers in the requested order without changing the input list.

    RunningContainerListRefresher calls this after Docker refreshes the
    container list and when the user applies a choice from the sorting menu.
    An empty image name or creation time stays at the end in either direction.
    """
    if sort_field == ContainerSortField.DOCKER_ORDER:
        return list(containers)

    containers_with_values = []
    containers_without_values = []
    for container in containers:
        sort_value = _container_sort_value(container, sort_field)
        if sort_value:
            containers_with_values.append((sort_value, container))
        else:
            containers_without_values.append(container)

    sorted_containers = sorted(
        containers_with_values,
        key=lambda item: (item[0].casefold(), item[1].container_id.casefold()),
        reverse=descending,
    )
    containers_without_values.sort(key=lambda container: container.container_id)
    return [
        *(container for _sort_value, container in sorted_containers),
        *containers_without_values,
    ]


def _container_sort_value(
    container: ContainerSummary,
    sort_field: ContainerSortField,
) -> str:
    """Return the ContainerSummary value used by one sort field."""
    if sort_field == ContainerSortField.NAME:
        return container.name
    if sort_field == ContainerSortField.IMAGE:
        return container.image_name
    if sort_field == ContainerSortField.STATUS:
        return container.status
    if sort_field == ContainerSortField.CREATED_AT:
        return container.created_at
    return ""


__all__ = [
    "ContainerSortField",
    "ContainerSortMenuState",
    "get_container_list_in_requested_order",
]
