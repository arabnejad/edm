"""Convert Docker SDK errors into errors understood by EDM."""

from __future__ import annotations

from typing import NoReturn

from docker.errors import NotFound

from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerNotFoundError,
    DockerRequestFailedError,
    FailedDockerRequestType,
)


def raise_container_request_error(
    failed_request_type: FailedDockerRequestType,
    container_id: str,
    exc: Exception,
) -> NoReturn:
    """Raise the EDM error that matches a failed Docker request."""
    if isinstance(exc, NotFound):
        raise ContainerNotFoundError(container_id) from exc
    if failed_request_type == FailedDockerRequestType.FETCH_LOGS:
        raise ContainerLogFetchError(container_id, str(exc)) from exc
    raise DockerRequestFailedError(
        failed_request_type,
        container_id,
        str(exc),
    ) from exc


__all__ = ["raise_container_request_error"]
