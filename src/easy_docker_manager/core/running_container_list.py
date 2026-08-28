"""Keep the Docker container list and its displayed form together."""

from __future__ import annotations

from typing import Optional

from easy_docker_manager.core.container_sorting import (
    ContainerSortField,
    get_container_list_in_requested_order,
)
from easy_docker_manager.core.containers import ContainerSummary


class RunningContainerList:
    """Keep Docker's full container list and the list currently shown in EDM.

    Keeping both lists lets EDM apply Compose grouping, sorting, and filtering
    without making another Docker request.
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
        """Apply the current filter and sort, then group Compose containers."""
        matching_containers = self._filter_containers(
            self._all_running_containers,
            filter_query,
        )
        self._displayed_containers = self._group_containers_by_compose_project(
            matching_containers,
            sort_field,
            sort_descending,
        )
        return self._displayed_containers

    @staticmethod
    def _group_containers_by_compose_project(
        containers: list[ContainerSummary],
        sort_field: ContainerSortField,
        sort_descending: bool,
    ) -> list[ContainerSummary]:
        """Place Compose projects together and leave other containers at the end."""
        containers_by_compose_project: dict[str, list[ContainerSummary]] = {}
        containers_without_compose_project: list[ContainerSummary] = []

        # Split the containers by Compose project first. Keep containers with no
        # project label in a separate list so they can be added at the end.
        for container in containers:
            if container.compose_project_name is None:
                containers_without_compose_project.append(container)
                continue
            containers_by_compose_project.setdefault(
                container.compose_project_name,
                [],
            ).append(container)

        # Sort the project names to keep the sections in a predictable order.
        # Sort containers inside each project so the projects stay separate.
        grouped_containers: list[ContainerSummary] = []
        compose_project_names = sorted(
            containers_by_compose_project,
            key=str.casefold,
        )
        for compose_project_name in compose_project_names:
            grouped_containers.extend(
                get_container_list_in_requested_order(
                    containers_by_compose_project[compose_project_name],
                    sort_field,
                    sort_descending,
                )
            )

        # Add containers started without Compose last. They use the same sort
        # settings, but the UI does not give them a project heading.
        grouped_containers.extend(
            get_container_list_in_requested_order(
                containers_without_compose_project,
                sort_field,
                sort_descending,
            )
        )
        return grouped_containers

    def _filter_containers(
        self,
        containers: list[ContainerSummary],
        filter_query: str,
    ) -> list[ContainerSummary]:
        """Keep containers whose displayed or Compose data contains the query.

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
                    container.compose_project_name or "",
                    container.compose_service_name or "",
                )
            )
        ]


__all__ = ["RunningContainerList"]
