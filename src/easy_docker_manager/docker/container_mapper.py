"""Map Docker SDK objects into EDM core models."""

from __future__ import annotations

from typing import Any

from easy_docker_manager.core import ContainerSummary


def to_container_summary(container: Any) -> ContainerSummary:
    """Copy the container fields needed by the UI into ContainerSummary."""
    container_attributes = getattr(container, "attrs", {}) or {}
    container_state = container_attributes.get("State", {}) or {}

    container_id = getattr(container, "id", None) or container_attributes.get("Id", "")
    fallback_name = getattr(container, "short_id", None) or container_id[:12]
    name = getattr(container, "name", None) or container_attributes.get(
        "Name", ""
    ).lstrip("/")
    status = getattr(container, "status", None) or container_state.get(
        "Status", "unknown"
    )

    return ContainerSummary(
        container_id=container_id,
        name=name or fallback_name or "unknown",
        status=status,
    )


__all__ = ["to_container_summary"]
