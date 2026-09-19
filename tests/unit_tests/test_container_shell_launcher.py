from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from easy_docker_manager.core.docker_connections import (
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.docker import container_shell_launcher, docker_cli
from easy_docker_manager.docker.container_shell_launcher import (
    ContainerShellLauncher,
    ContainerShellLaunchError,
)


def test_find_available_shell_prefers_bash(monkeypatch) -> None:
    run_command = Mock(return_value=SimpleNamespace(returncode=0, stderr=""))
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(container_shell_launcher.subprocess, "run", run_command)
    docker_context = DockerContextDetails(
        "default",
        "unix:///var/run/docker.sock",
        DockerConnectionTransport.LOCAL,
    )

    shell_executable = ContainerShellLauncher().find_available_shell_executable(
        "container-id",
        docker_context,
    )

    assert shell_executable == "/bin/bash"
    run_command.assert_called_once_with(
        [
            "/usr/bin/docker",
            "--context",
            "default",
            "exec",
            "container-id",
            "/bin/bash",
            "-c",
            "exit 0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_find_available_shell_falls_back_to_sh(monkeypatch) -> None:
    run_command = Mock(
        side_effect=[
            SimpleNamespace(returncode=127, stderr="bash not found"),
            SimpleNamespace(returncode=0, stderr=""),
        ]
    )
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(container_shell_launcher.subprocess, "run", run_command)

    shell_executable = ContainerShellLauncher().find_available_shell_executable(
        "container-id",
        DockerContextDetails(
            "default",
            "unix:///var/run/docker.sock",
            DockerConnectionTransport.LOCAL,
        ),
    )

    assert shell_executable == "/bin/sh"
    assert run_command.call_count == 2
    assert run_command.call_args.args[0][5] == "/bin/sh"


def test_find_available_shell_reports_when_bash_and_sh_are_missing(
    monkeypatch,
) -> None:
    run_command = Mock(
        return_value=SimpleNamespace(returncode=127, stderr="executable not found")
    )
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(container_shell_launcher.subprocess, "run", run_command)

    with pytest.raises(
        ContainerShellLaunchError,
        match="does not provide /bin/bash or /bin/sh.*executable not found",
    ):
        ContainerShellLauncher().find_available_shell_executable(
            "container-id",
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )


def test_open_shell_uses_the_selected_named_context(monkeypatch) -> None:
    run_command = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/usr/bin/docker",
    )
    monkeypatch.setattr(container_shell_launcher.subprocess, "run", run_command)
    docker_context = DockerContextDetails(
        "remote-server-context",
        "ssh://docker-user@remote-server-address",
        DockerConnectionTransport.SSH,
    )

    exit_code = ContainerShellLauncher().open_shell(
        "container-id",
        "/bin/bash",
        docker_context,
    )

    assert exit_code == 0
    run_command.assert_called_once_with(
        [
            "/usr/bin/docker",
            "--context",
            "remote-server-context",
            "exec",
            "--interactive",
            "--tty",
            "container-id",
            "/bin/bash",
        ],
        check=False,
    )


def test_open_shell_uses_default_context_name_for_localhost(monkeypatch) -> None:
    run_command = Mock(return_value=SimpleNamespace(returncode=3))
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/usr/bin/docker",
    )
    monkeypatch.setattr(container_shell_launcher.subprocess, "run", run_command)
    docker_context = DockerContextDetails(
        "default",
        "unix:///var/run/docker.sock",
        DockerConnectionTransport.LOCAL,
    )

    exit_code = ContainerShellLauncher().open_shell(
        "container-id",
        "/bin/sh",
        docker_context,
    )

    assert exit_code == 3
    assert run_command.call_args.args[0][1:3] == ["--context", "default"]


def test_open_shell_keeps_docker_host_environment_connection(monkeypatch) -> None:
    run_command = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/usr/bin/docker",
    )
    monkeypatch.setattr(container_shell_launcher.subprocess, "run", run_command)
    docker_context = DockerContextDetails(
        "DOCKER_HOST",
        "tcp://docker.example.com:2376",
        DockerConnectionTransport.TCP,
        uses_docker_environment=True,
    )

    ContainerShellLauncher().open_shell(
        "container-id",
        "powershell.exe",
        docker_context,
    )

    command = run_command.call_args.args[0]
    assert "--context" not in command
    assert command[-1] == "powershell.exe"


def test_open_shell_reports_missing_docker_command(monkeypatch) -> None:
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: None)

    with pytest.raises(
        ContainerShellLaunchError,
        match="docker command was not found in PATH",
    ):
        ContainerShellLauncher().open_shell(
            "container-id",
            "/bin/sh",
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )


def test_open_shell_reports_command_start_error(monkeypatch) -> None:
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/usr/bin/docker",
    )
    monkeypatch.setattr(
        container_shell_launcher.subprocess,
        "run",
        Mock(side_effect=OSError("permission denied")),
    )

    with pytest.raises(
        ContainerShellLaunchError,
        match="permission denied",
    ):
        ContainerShellLauncher().open_shell(
            "container-id",
            "/bin/sh",
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )
