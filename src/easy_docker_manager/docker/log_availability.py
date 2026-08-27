"""Check whether Docker can read back a container's output logs.

Docker uses a logging driver to decide where each container's standard output
and error are stored or sent. Common logging drivers include json-file, local,
journald, and none. The none driver discards the output, and some other drivers
send it somewhere that the Docker logs command cannot read back. This module
reads the configured driver name and recognizes the errors Docker returns when
logs cannot be read.
"""

from __future__ import annotations

from typing import Any, Optional


def get_container_logging_driver_name(container: Optional[Any]) -> str:
    """Return the name of the container's configured logging driver.

    Docker stores this name in the container's HostConfig.LogConfig.Type field.
    The function returns "unknown" when the container or that field is missing.
    """
    if container is None:
        return "unknown"

    attrs = getattr(container, "attrs", {}) or {}
    log_config = attrs.get("HostConfig", {}).get("LogConfig", {}) or {}
    return log_config.get("Type") or "unknown"


def docker_error_indicates_logs_are_unavailable(exc: Exception) -> bool:
    """Return True when Docker says it cannot read stored container logs.

    get_container_logs() calls this after a Docker log request fails. A True
    result means retrying will not help, so EDM shows that logs are unavailable
    and stops polling that container.
    """
    message = str(exc).lower()
    return (
        "configured logging driver does not support reading" in message
        or "logging driver does not support reading" in message
        or "logs are not available" in message
    )


__all__ = [
    "docker_error_indicates_logs_are_unavailable",
    "get_container_logging_driver_name",
]
