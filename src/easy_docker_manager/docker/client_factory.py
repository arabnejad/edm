"""Create Docker SDK clients for the local environment."""

from __future__ import annotations

import os
from typing import Optional

import docker
from docker.errors import DockerException

LOCAL_DOCKER_ENDPOINT_PREFIXES = ("unix://", "npipe://")


def create_docker_client(request_timeout: float) -> docker.DockerClient:
    """Create a Docker client for a local socket or Windows named pipe."""
    if request_timeout <= 0:
        raise ValueError("request_timeout must be positive")
    _validate_local_docker_endpoint(os.getenv("DOCKER_HOST"))
    return docker.from_env(timeout=request_timeout)


def _validate_local_docker_endpoint(docker_host: Optional[str]) -> None:
    """Reject DOCKER_HOST values that connect through a remote transport."""
    if not docker_host:
        return
    if docker_host.lower().startswith(LOCAL_DOCKER_ENDPOINT_PREFIXES):
        return
    raise DockerException(
        "EDM supports local Docker sockets and Windows named pipes only; "
        f"DOCKER_HOST is set to {docker_host!r}"
    )


__all__ = ["create_docker_client"]
