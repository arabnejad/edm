"""Recreate one Docker Compose service with the Docker command."""

from __future__ import annotations

# Docker Compose has no Python API, so this adapter runs a fixed argument list.
import subprocess  # nosec B404
from pathlib import Path

from easy_docker_manager.core.containers import ContainerSummary
from easy_docker_manager.core.docker_connections import DockerContextDetails
from easy_docker_manager.docker.docker_cli import (
    DockerCommandNotFoundError,
    build_docker_cli_command_prefix,
)


class DockerComposeServiceRecreateError(RuntimeError):
    """Raised when EDM cannot run the Compose recreation command."""


class DockerComposeServiceRecreator:
    """Check Compose metadata and recreate one service in the background."""

    def recreate_service(
        self,
        container: ContainerSummary,
        docker_context: DockerContextDetails,
    ) -> None:
        """Run Docker Compose for the service represented by container."""
        try:
            compose_command = build_docker_cli_command_prefix(docker_context)
        except DockerCommandNotFoundError as exc:
            raise DockerComposeServiceRecreateError(
                "Docker Compose is unavailable because the docker command was not "
                "found in PATH."
            ) from exc

        compose_project_name = container.compose_project_name
        compose_service_name = container.compose_service_name
        compose_working_directory = container.compose_working_directory
        compose_config_file_paths = container.compose_config_file_paths
        if (
            not compose_project_name
            or not compose_service_name
            or not compose_working_directory
            or not compose_config_file_paths
        ):
            raise DockerComposeServiceRecreateError(
                "The container is missing the Docker Compose labels needed for "
                "recreation."
            )

        working_directory = Path(compose_working_directory)
        if not working_directory.is_dir():
            raise DockerComposeServiceRecreateError(
                f"Docker Compose working directory was not found: {working_directory}"
            )

        config_file_paths = tuple(
            self._resolve_config_file_path(path, working_directory)
            for path in compose_config_file_paths
        )
        for config_file_path in config_file_paths:
            if not config_file_path.is_file():
                raise DockerComposeServiceRecreateError(
                    f"Docker Compose configuration file was not found: "
                    f"{config_file_path}"
                )

        compose_command.extend(
            self._build_recreate_arguments(
                working_directory,
                config_file_paths,
                compose_project_name,
                compose_service_name,
            )
        )
        try:
            subprocess.run(  # noqa: S603  # nosec B603
                compose_command,
                cwd=working_directory,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            command_error = (exc.stderr or exc.stdout or "").strip()
            if not command_error:
                command_error = f"command exited with status {exc.returncode}"
            raise DockerComposeServiceRecreateError(
                f"Docker Compose could not recreate the service: {command_error}"
            ) from exc

    @staticmethod
    def _resolve_config_file_path(
        config_file_path: str,
        working_directory: Path,
    ) -> Path:
        """Resolve a relative Compose file from the project's working directory."""
        path = Path(config_file_path)
        return path if path.is_absolute() else working_directory / path

    @staticmethod
    def _build_recreate_arguments(
        working_directory: Path,
        config_file_paths: tuple[Path, ...],
        compose_project_name: str,
        compose_service_name: str,
    ) -> list[str]:
        """Build the fixed Docker Compose arguments used for recreation."""
        arguments = [
            "compose",
            "--project-directory",
            str(working_directory),
        ]
        for config_file_path in config_file_paths:
            arguments.extend(["--file", str(config_file_path)])
        arguments.extend(
            [
                "--project-name",
                compose_project_name,
                "up",
                "--detach",
                "--no-deps",
                "--force-recreate",
                compose_service_name,
            ]
        )
        return arguments


__all__ = [
    "DockerComposeServiceRecreateError",
    "DockerComposeServiceRecreator",
]
