"""Build Docker CLI commands for the connection selected in EDM."""

from __future__ import annotations

import shutil

from easy_docker_manager.core.docker_connections import DockerContextDetails


class DockerCommandNotFoundError(RuntimeError):
    """Raised when the docker command is not available in PATH."""


def build_docker_cli_command_prefix(
    docker_context: DockerContextDetails,
) -> list[str]:
    """Return the docker command and the selected context argument."""
    docker_executable = shutil.which("docker")
    if docker_executable is None:
        raise DockerCommandNotFoundError("docker command was not found in PATH")

    command = [docker_executable]
    if not docker_context.uses_docker_environment:
        command.extend(["--context", docker_context.context_name])
    return command


__all__ = ["DockerCommandNotFoundError", "build_docker_cli_command_prefix"]
