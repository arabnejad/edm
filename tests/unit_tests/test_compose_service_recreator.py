from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from easy_docker_manager.core.docker_connections import (
    DockerConnectionTransport,
    DockerContextDetails,
)
from easy_docker_manager.docker import compose_service_recreator, docker_cli
from easy_docker_manager.docker.compose_service_recreator import (
    DockerComposeServiceRecreateError,
    DockerComposeServiceRecreator,
)


def test_recreate_service_runs_compose_for_the_selected_context(
    monkeypatch,
    tmp_path: Path,
    container_summary_factory,
) -> None:
    first_config_file = tmp_path / "compose.yaml"
    second_config_file = tmp_path / "compose.override.yaml"
    first_config_file.write_text("services: {}\n", encoding="utf-8")
    second_config_file.write_text("services: {}\n", encoding="utf-8")
    run_command = Mock()
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/bin/docker",
    )
    monkeypatch.setattr(compose_service_recreator.subprocess, "run", run_command)
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory=str(tmp_path),
        compose_config_file_paths=("compose.yaml", str(second_config_file)),
    )
    docker_context = DockerContextDetails(
        "remote-server-context",
        "ssh://docker-user@remote-server-address",
        DockerConnectionTransport.SSH,
    )

    DockerComposeServiceRecreator().recreate_service(container, docker_context)

    run_command.assert_called_once_with(
        [
            "/bin/docker",
            "--context",
            "remote-server-context",
            "compose",
            "--project-directory",
            str(tmp_path),
            "--file",
            str(first_config_file),
            "--file",
            str(second_config_file),
            "--project-name",
            "example",
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
            "web",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def test_recreate_service_keeps_docker_host_environment_connection(
    monkeypatch,
    tmp_path: Path,
    container_summary_factory,
) -> None:
    config_file = tmp_path / "compose.yaml"
    config_file.write_text("services: {}\n", encoding="utf-8")
    run_command = Mock()
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/bin/docker",
    )
    monkeypatch.setattr(compose_service_recreator.subprocess, "run", run_command)
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory=str(tmp_path),
        compose_config_file_paths=(str(config_file),),
    )
    docker_context = DockerContextDetails(
        "DOCKER_HOST",
        "tcp://docker.example.com:2376",
        DockerConnectionTransport.TCP,
        uses_docker_environment=True,
    )

    DockerComposeServiceRecreator().recreate_service(container, docker_context)

    command = run_command.call_args.args[0]
    assert "--context" not in command


def test_recreate_service_reports_missing_docker_command(
    monkeypatch,
    container_summary_factory,
) -> None:
    monkeypatch.setattr(docker_cli.shutil, "which", lambda _: None)

    with pytest.raises(
        DockerComposeServiceRecreateError,
        match="docker command was not found in PATH",
    ):
        DockerComposeServiceRecreator().recreate_service(
            container_summary_factory(),
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )


def test_recreate_service_reports_missing_compose_labels(
    monkeypatch,
    container_summary_factory,
) -> None:
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/bin/docker",
    )

    with pytest.raises(
        DockerComposeServiceRecreateError,
        match="missing the Docker Compose labels",
    ):
        DockerComposeServiceRecreator().recreate_service(
            container_summary_factory(),
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )


def test_recreate_service_reports_missing_working_directory(
    monkeypatch,
    tmp_path: Path,
    container_summary_factory,
) -> None:
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/bin/docker",
    )
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory=str(tmp_path / "missing"),
        compose_config_file_paths=("compose.yaml",),
    )

    with pytest.raises(
        DockerComposeServiceRecreateError,
        match="working directory was not found",
    ):
        DockerComposeServiceRecreator().recreate_service(
            container,
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )


def test_recreate_service_reports_missing_config_file(
    monkeypatch,
    tmp_path: Path,
    container_summary_factory,
) -> None:
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/bin/docker",
    )
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory=str(tmp_path),
        compose_config_file_paths=("missing.yaml",),
    )

    with pytest.raises(
        DockerComposeServiceRecreateError,
        match="configuration file was not found",
    ):
        DockerComposeServiceRecreator().recreate_service(
            container,
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )


def test_recreate_service_reports_compose_command_error(
    monkeypatch,
    tmp_path: Path,
    container_summary_factory,
) -> None:
    config_file = tmp_path / "compose.yaml"
    config_file.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        docker_cli.shutil,
        "which",
        lambda _: "/bin/docker",
    )
    monkeypatch.setattr(
        compose_service_recreator.subprocess,
        "run",
        Mock(
            side_effect=subprocess.CalledProcessError(
                1,
                ["docker", "compose"],
                stderr="service web is invalid",
            )
        ),
    )
    container = container_summary_factory(
        compose_project_name="example",
        compose_service_name="web",
        compose_working_directory=str(tmp_path),
        compose_config_file_paths=(str(config_file),),
    )

    with pytest.raises(
        DockerComposeServiceRecreateError,
        match="service web is invalid",
    ):
        DockerComposeServiceRecreator().recreate_service(
            container,
            DockerContextDetails(
                "default",
                "unix:///var/run/docker.sock",
                DockerConnectionTransport.LOCAL,
            ),
        )
