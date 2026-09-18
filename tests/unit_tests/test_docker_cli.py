from __future__ import annotations

import pytest

from easy_docker_manager.core.docker_connections import (
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.docker import docker_cli
from easy_docker_manager.docker.docker_cli import (
    DockerCommandNotFoundError,
    build_docker_cli_command_prefix,
)


def test_command_prefix_uses_selected_docker_context(monkeypatch) -> None:
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: "/bin/docker")
    docker_context = DockerContextDetails(
        "remote-server-context",
        "ssh://docker-user@remote-server-address",
        DockerConnectionTransport.SSH,
    )

    assert build_docker_cli_command_prefix(docker_context) == [
        "/bin/docker",
        "--context",
        "remote-server-context",
    ]


def test_command_prefix_keeps_docker_environment_connection(monkeypatch) -> None:
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: "/bin/docker")
    docker_context = DockerContextDetails(
        "DOCKER_HOST",
        "tcp://docker.example.com:2376",
        DockerConnectionTransport.TCP,
        uses_docker_environment=True,
    )

    assert build_docker_cli_command_prefix(docker_context) == ["/bin/docker"]


def test_command_prefix_reports_missing_docker_command(monkeypatch) -> None:
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: None)
    docker_context = DockerContextDetails(
        "default",
        "unix:///var/run/docker.sock",
        DockerConnectionTransport.LOCAL,
    )

    with pytest.raises(
        DockerCommandNotFoundError,
        match="docker command was not found in PATH",
    ):
        build_docker_cli_command_prefix(docker_context)
