"""Read Docker contexts saved on this computer."""

from __future__ import annotations

import os

import docker
from docker.errors import DockerException

from easy_docker_manager.core.docker_connections import (
    DockerConnectionTransport,
    DockerContextDetails,
)

DOCKER_HOST_ENVIRONMENT_CONNECTION_NAME = "DOCKER_HOST"
LOCAL_DOCKER_ENDPOINT_SCHEMES = {"unix", "npipe"}


class DockerContextReader:
    """Read saved Docker contexts and find the one EDM should use at startup.

    This only reads Docker's local configuration files. It does not contact a
    Docker daemon. EDM opens a connection later, when it loads containers or
    the user selects another context.
    """

    def get_startup_docker_context(self) -> DockerContextDetails:
        """Return the context selected by Docker's environment or config file."""
        docker_context_name = os.getenv("DOCKER_CONTEXT")
        if docker_context_name:
            return self._get_context_details(docker_context_name)

        docker_host = os.getenv("DOCKER_HOST")
        if docker_host:
            return _build_context_details(
                DOCKER_HOST_ENVIRONMENT_CONNECTION_NAME,
                docker_host,
                uses_docker_environment=True,
            )

        current_context = docker.ContextAPI.get_current_context()
        if current_context is None:
            raise DockerException("Docker did not return its current context")
        return _build_context_details(current_context.name, current_context.Host or "")

    def list_configured_docker_contexts(self) -> list[DockerContextDetails]:
        """Return saved contexts and the active DOCKER_HOST entry, if present."""
        contexts = [
            _build_context_details(context.name, context.Host or "")
            for context in docker.ContextAPI.contexts()
            if context is not None
        ]

        docker_context_name = os.getenv("DOCKER_CONTEXT")
        docker_host = os.getenv("DOCKER_HOST")
        if docker_host and not docker_context_name:
            contexts.append(
                _build_context_details(
                    DOCKER_HOST_ENVIRONMENT_CONNECTION_NAME,
                    docker_host,
                    uses_docker_environment=True,
                )
            )

        contexts.sort(
            key=lambda context: (
                context.context_name != "default",
                context.display_name.casefold(),
            )
        )
        return contexts

    @staticmethod
    def _get_context_details(context_name: str) -> DockerContextDetails:
        """Return a named context or an unsupported entry when it is missing."""
        context = docker.ContextAPI.get_context(context_name)
        if context is None:
            return DockerContextDetails(
                context_name=context_name,
                docker_host="",
                transport=DockerConnectionTransport.UNKNOWN,
            )
        return _build_context_details(context.name, context.Host or "")


def _build_context_details(
    context_name: str,
    docker_host: str,
    *,
    uses_docker_environment: bool = False,
) -> DockerContextDetails:
    """Read the connection type from a Docker endpoint URL."""
    endpoint_scheme = docker_host.partition("://")[0].casefold()
    if endpoint_scheme in LOCAL_DOCKER_ENDPOINT_SCHEMES:
        transport = DockerConnectionTransport.LOCAL
    elif endpoint_scheme == "ssh":
        transport = DockerConnectionTransport.SSH
    elif endpoint_scheme in {"tcp", "http", "https"}:
        transport = DockerConnectionTransport.TCP
    else:
        transport = DockerConnectionTransport.UNKNOWN
    return DockerContextDetails(
        context_name=context_name,
        docker_host=docker_host,
        transport=transport,
        uses_docker_environment=uses_docker_environment,
    )


__all__ = [
    "DOCKER_HOST_ENVIRONMENT_CONNECTION_NAME",
    "DockerContextReader",
]
