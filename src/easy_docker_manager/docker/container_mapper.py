"""Copy Docker SDK container data into EDM's ContainerSummary."""

from __future__ import annotations

from typing import Any

from easy_docker_manager.core.containers import ContainerSummary

DOCKER_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
DOCKER_COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def to_container_summary(container: Any) -> ContainerSummary:
    """Copy the container fields needed by the UI into ContainerSummary."""
    container_attributes = getattr(container, "attrs", {}) or {}
    container_state = container_attributes.get("State", {}) or {}
    container_config = container_attributes.get("Config", {}) or {}

    container_id = getattr(container, "id", None) or container_attributes.get("Id", "")
    fallback_container_name = getattr(container, "short_id", None) or container_id[:12]
    name = getattr(container, "name", None) or container_attributes.get(
        "Name", ""
    ).lstrip("/")
    status = getattr(container, "status", None) or container_state.get(
        "Status", "unknown"
    )
    image_name = container_config.get("Image", "")
    created_at = container_attributes.get("Created", "")
    container_labels = container_config.get("Labels", {}) or {}
    compose_project_name = container_labels.get(DOCKER_COMPOSE_PROJECT_LABEL) or None
    compose_service_name = container_labels.get(DOCKER_COMPOSE_SERVICE_LABEL) or None

    return ContainerSummary(
        container_id=container_id,
        name=name or fallback_container_name or "unknown",
        status=status,
        image_name=image_name,
        created_at=created_at,
        compose_project_name=compose_project_name,
        compose_service_name=compose_service_name,
    )


__all__ = ["to_container_summary"]
