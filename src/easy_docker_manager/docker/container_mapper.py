"""Copy Docker list response data into EDM's ContainerSummary."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from easy_docker_manager.core.containers import ContainerSummary

DOCKER_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
DOCKER_COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
DOCKER_COMPOSE_WORKING_DIRECTORY_LABEL = "com.docker.compose.project.working_dir"
DOCKER_COMPOSE_CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
CONTAINER_HEALTH_STATUS_PATTERN = re.compile(
    r"\((?:health:\s*)?(healthy|unhealthy|starting)\)",
    re.IGNORECASE,
)
CONTAINER_EXIT_CODE_PATTERN = re.compile(r"^Exited\s+\((\d+)\)", re.IGNORECASE)


def _get_compose_config_file_paths(label_value: object) -> tuple[str, ...]:
    """Split Compose's comma-separated configuration file label."""
    if not isinstance(label_value, str):
        return ()
    return tuple(path.strip() for path in label_value.split(",") if path.strip())


def _format_container_creation_time(created_at_value: Any) -> str:
    """Return Docker's creation time in the format EDM already uses."""
    if isinstance(created_at_value, (int, float)):
        return datetime.fromtimestamp(created_at_value, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return "" if created_at_value is None else str(created_at_value)


def _get_container_health_status(
    container_state: str,
    docker_status_text: str,
) -> str | None:
    """Read the health result from Docker's running status text."""
    if container_state.casefold() != "running":
        return None
    health_status_match = CONTAINER_HEALTH_STATUS_PATTERN.search(docker_status_text)
    if health_status_match is None:
        return None
    return health_status_match.group(1).casefold()


def _get_container_exit_code(
    container_state: str,
    docker_status_text: str,
) -> int | None:
    """Read the exit code from Docker's stopped status text."""
    if container_state.casefold() != "exited":
        return None
    exit_code_match = CONTAINER_EXIT_CODE_PATTERN.search(docker_status_text)
    if exit_code_match is None:
        return None
    return int(exit_code_match.group(1))


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
    # Sparse list results put health and exit details inside this display text.
    # Reading it here avoids a separate inspect request for every container.
    docker_status_text = str(docker_container_list_item.get("Status") or "")
    image_name = str(docker_container_list_item.get("Image") or "")
    created_at = _format_container_creation_time(
        docker_container_list_item.get("Created")
    )
    container_labels = docker_container_list_item.get("Labels") or {}
    compose_project_name = container_labels.get(DOCKER_COMPOSE_PROJECT_LABEL) or None
    compose_service_name = container_labels.get(DOCKER_COMPOSE_SERVICE_LABEL) or None
    compose_working_directory = (
        container_labels.get(DOCKER_COMPOSE_WORKING_DIRECTORY_LABEL) or None
    )
    compose_config_file_paths = _get_compose_config_file_paths(
        container_labels.get(DOCKER_COMPOSE_CONFIG_FILES_LABEL)
    )

    return ContainerSummary(
        container_id=container_id,
        name=container_name or "unknown",
        status=status,
        image_name=image_name,
        created_at=created_at,
        compose_project_name=compose_project_name,
        compose_service_name=compose_service_name,
        health_status=_get_container_health_status(status, docker_status_text),
        exit_code=_get_container_exit_code(status, docker_status_text),
        compose_working_directory=compose_working_directory,
        compose_config_file_paths=compose_config_file_paths,
    )


__all__ = ["to_container_summary"]
