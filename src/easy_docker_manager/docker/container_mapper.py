"""Copy Docker list response data into EDM's ContainerSummary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from easy_docker_manager.core.containers import ContainerSummary

DOCKER_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
DOCKER_COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def _format_container_creation_time(created_at_value: Any) -> str:
    """Return Docker's creation time in the format EDM already uses."""
    if isinstance(created_at_value, (int, float)):
        return datetime.fromtimestamp(created_at_value, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return "" if created_at_value is None else str(created_at_value)


def to_container_summary(
    docker_container_list_item: dict[str, Any],
) -> ContainerSummary:
    """Copy the fields EDM needs from one Docker container-list item."""
    container_id = str(docker_container_list_item.get("Id") or "")
    container_names = docker_container_list_item.get("Names") or []
    container_name = (
        str(container_names[0]).lstrip("/") if container_names else container_id[:12]
    )
    status = str(docker_container_list_item.get("State") or "unknown")
    image_name = str(docker_container_list_item.get("Image") or "")
    created_at = _format_container_creation_time(
        docker_container_list_item.get("Created")
    )
    container_labels = docker_container_list_item.get("Labels") or {}
    compose_project_name = container_labels.get(DOCKER_COMPOSE_PROJECT_LABEL) or None
    compose_service_name = container_labels.get(DOCKER_COMPOSE_SERVICE_LABEL) or None

    return ContainerSummary(
        container_id=container_id,
        name=container_name or "unknown",
        status=status,
        image_name=image_name,
        created_at=created_at,
        compose_project_name=compose_project_name,
        compose_service_name=compose_service_name,
    )


__all__ = ["to_container_summary"]
