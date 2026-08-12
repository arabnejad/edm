"""Check whether Docker can return a container's output logs.

Docker uses a logging driver to decide where each container's standard output
and error are stored or sent. Common logging drivers include json-file, local,
journald, and none. The none driver discards the output, and some other drivers
send it somewhere that the Docker logs command cannot read back. This module
reads the configured driver name and recognizes Docker errors that mean logs
are unavailable.
"""

from __future__ import annotations

from typing import Any, Optional


def get_unreadable_log_driver(container: Any) -> Optional[str]:
    """Return "none" when Docker is configured to discard container logs.

    The none logging driver does not store standard output or error, so Docker
    cannot return logs for that container. Other driver types are tried because
    Docker itself must report whether they support reading.
    """
    logging_driver_name = get_container_log_driver(container)
    return logging_driver_name if logging_driver_name == "none" else None


def get_container_log_driver(container: Optional[Any]) -> str:
    """Return the name of the container's configured logging driver.

    Docker stores this name in the container's HostConfig.LogConfig.Type field.
    The function returns "unknown" when the container or that field is missing.
    """
    if container is None:
        return "unknown"

    attrs = getattr(container, "attrs", {}) or {}
    log_config = attrs.get("HostConfig", {}).get("LogConfig", {}) or {}
    return log_config.get("Type") or "unknown"


def is_unsupported_log_error(exc: Exception) -> bool:
    """Return True when Docker says it cannot read stored container logs.

    get_logs() calls this after a Docker log request fails. A True result means
    retrying will not help, so EDM shows that logs are unavailable and stops
    polling that container.
    """
    message = str(exc).lower()
    return (
        "configured logging driver does not support reading" in message
        or "logging driver does not support reading" in message
        or "logs are not available" in message
    )


__all__ = [
    "get_container_log_driver",
    "is_unsupported_log_error",
    "get_unreadable_log_driver",
]
