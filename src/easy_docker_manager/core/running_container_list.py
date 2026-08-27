"""Keep the Docker container list and its displayed form together."""

from __future__ import annotations

from typing import Optional

from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    get_container_list_in_requested_order,
)
from easy_docker_manager.core.containers import ContainerSummary


class RunningContainerList:
    """Keep all running containers and the filtered list shown in EDM.

    Keeping both lists lets EDM clear a filter or restore Docker order without
    making another Docker request.
    """

    def __init__(
        self,
        containers_received_from_docker: Optional[list[ContainerSummary]] = None,
    ) -> None:
        # Keep our own list so later changes to the caller's list cannot change
        # the container state stored by EDM.
        self._all_running_containers = (
            list(containers_received_from_docker)
            if containers_received_from_docker is not None
            else []
        )
        self._displayed_containers = list(self._all_running_containers)

    @property
    def displayed_containers(self) -> list[ContainerSummary]:
        """Return the sorted and filtered containers shown in the left panel."""
        return self._displayed_containers

    @property
    def unfiltered_container_count(self) -> int:
        """Return the number of running containers reported by Docker."""
        return len(self._all_running_containers)

    @property
    def all_running_container_ids(self) -> set[str]:
        """Return the IDs from the latest successful Docker refresh."""
        return {container.container_id for container in self._all_running_containers}

    def replace_all_running_containers(
        self,
        containers: list[ContainerSummary],
    ) -> None:
        """Replace the complete list after a successful Docker refresh.

        A copy is stored so later changes to the Docker result cannot change the
        list kept by EDM.
        """
        self._all_running_containers = list(containers)

    def rebuild_displayed_containers(
        self,
        sort_field: ContainerSortField,
        sort_descending: bool,
        filter_query: str,
    ) -> list[ContainerSummary]:
        """Apply the current sort and filter and return the new displayed list."""
        sorted_containers = get_container_list_in_requested_order(
            self._all_running_containers,
            sort_field,
            sort_descending,
        )
        self._displayed_containers = self._filter_containers(
            sorted_containers,
            filter_query,
        )
        return self._displayed_containers

    def _filter_containers(
        self,
        containers: list[ContainerSummary],
        filter_query: str,
    ) -> list[ContainerSummary]:
        """Keep containers whose name, image, or status contains the query.

        casefold() handles case-insensitive Unicode comparisons more reliably
        than lower().
        """
        case_insensitive_query = filter_query.casefold()
        if not case_insensitive_query:
            return containers

        return [
            container
            for container in containers
            if any(
                case_insensitive_query in field_value.casefold()
                for field_value in (
                    container.name,
                    container.image_name,
                    container.status,
                )
            )
        ]


__all__ = ["RunningContainerList"]
