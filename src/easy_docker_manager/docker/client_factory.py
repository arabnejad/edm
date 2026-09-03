"""Create Docker SDK clients and check that they can reach their daemon."""

from __future__ import annotations

from contextlib import suppress
from typing import Optional

import docker
from docker import DockerClient
from docker.errors import DockerException

from easy_docker_manager.core.docker_connections import DockerContextDetails


class DockerContextConnectionError(RuntimeError):
    """Report why EDM could not use a selected Docker context."""


def create_docker_client(
    docker_context: DockerContextDetails,
    request_timeout: float,
) -> DockerClient:
    """Create a Docker SDK client for one supported context."""
    if request_timeout <= 0:
        raise ValueError("request_timeout must be positive")
    if not docker_context.docker_host:
        raise DockerException(
            f'Docker context "{docker_context.context_name}" has no endpoint'
        )
    if not docker_context.is_supported:
        raise DockerException(docker_context.unsupported_reason)

    if docker_context.uses_docker_environment:
        return docker.from_env(
            timeout=request_timeout,
            use_ssh_client=False,
        )
    return docker.from_context(
        docker_context.context_name,
        timeout=request_timeout,
        use_ssh_client=False,
    )


def create_validated_docker_client_for_context(
    docker_context: DockerContextDetails,
    request_timeout: float,
) -> DockerClient:
    """Open and ping a Docker context, then return the connected client.

    For an SSH context, the Docker SDK uses Paramiko. Authentication must
    already work with an SSH key or ssh-agent because EDM cannot show a
    password prompt. The ping also checks that the remote user can access
    Docker. If the check fails, this function closes the new client.
    """
    docker_client: Optional[DockerClient] = None
    try:
        docker_client = create_docker_client(docker_context, request_timeout)
        docker_client.ping()
    except Exception as exc:
        if docker_client is not None:
            with suppress(Exception):
                docker_client.close()
        raise DockerContextConnectionError(
            _build_docker_context_connection_error_message(docker_context, exc)
        ) from exc
    assert docker_client is not None
    return docker_client


def _build_docker_context_connection_error_message(
    docker_context: DockerContextDetails,
    error: BaseException,
) -> str:
    """Turn common SSH and Docker failures into a short menu message."""
    error_type_name = type(error).__name__
    error_text = " ".join(str(error).split())

    if error_type_name == "AuthenticationException":
        return (
            "SSH authentication failed. Configure an SSH key or ssh-agent, "
            f'then run: docker --context "{docker_context.context_name}" ps'
        )
    if error_type_name == "BadHostKeyException":
        return "The SSH host key does not match the saved known_hosts entry."
    if "not found in known_hosts" in error_text:
        return "The SSH host key is not trusted. Connect with ssh once and try again."
    if error_type_name == "NoValidConnectionsError":
        return "The remote SSH host could not be reached."
    if error_type_name in {"TimeoutError", "ReadTimeout", "ConnectTimeout"}:
        return "The Docker connection timed out."
    if error_text:
        return error_text
    return error_type_name


__all__ = [
    "DockerContextConnectionError",
    "create_docker_client",
    "create_validated_docker_client_for_context",
]
