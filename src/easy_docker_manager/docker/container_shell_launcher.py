"""Find and open a container shell through the Docker command."""

from __future__ import annotations

# The Docker CLI handles keyboard input, output, and terminal resizing for us.
# Doing this through the SDK would mean forwarding each of those ourselves.
import subprocess  # nosec B404

from easy_docker_manager.core.docker_connections import DockerContextDetails
from easy_docker_manager.docker.docker_cli import (
    DockerCommandNotFoundError,
    build_docker_cli_command_prefix,
)


class ContainerShellLaunchError(RuntimeError):
    """Raised when EDM cannot start the Docker Exec command."""


class ContainerShellLauncher:
    """Find a supported shell and build its interactive Docker Exec command."""

    supported_shell_executables = ("/bin/bash", "/bin/sh")

    def find_available_shell_executable(
        self,
        container_id: str,
        docker_context: DockerContextDetails,
    ) -> str:
        """Return the first supported shell that starts in the container."""
        command_prefix = self._build_command_prefix(docker_context)
        last_error = ""
        for shell_executable in self.supported_shell_executables:
            try:
                completed_command = subprocess.run(  # noqa: S603  # nosec B603
                    [
                        *command_prefix,
                        "exec",
                        container_id,
                        shell_executable,
                        "-c",
                        "exit 0",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                raise ContainerShellLaunchError(
                    f"Could not start the Docker Exec command: {exc}"
                ) from exc
            if completed_command.returncode == 0:
                return shell_executable
            last_error = completed_command.stderr.strip()

        message = "The container does not provide /bin/bash or /bin/sh."
        if last_error:
            message = f"{message} Docker reported: {last_error}"
        raise ContainerShellLaunchError(message)

    def build_interactive_shell_command(
        self,
        container_id: str,
        shell_executable: str,
        docker_context: DockerContextDetails,
    ) -> list[str]:
        """Build the Docker Exec command used by the terminal workspace."""
        command = self._build_command_prefix(docker_context)
        command.extend(
            [
                "exec",
                "--interactive",
                "--tty",
                container_id,
                shell_executable,
            ]
        )
        return command

    def open_shell(
        self,
        container_id: str,
        shell_executable: str,
        docker_context: DockerContextDetails,
    ) -> int:
        """Attach the current terminal to a shell on systems without a PTY widget."""
        command = self.build_interactive_shell_command(
            container_id,
            shell_executable,
            docker_context,
        )
        try:
            completed_command = subprocess.run(  # noqa: S603  # nosec B603
                command,
                check=False,
            )
        except OSError as exc:
            raise ContainerShellLaunchError(
                f"Could not start the Docker Exec command: {exc}"
            ) from exc
        return completed_command.returncode

    @staticmethod
    def _build_command_prefix(
        docker_context: DockerContextDetails,
    ) -> list[str]:
        """Build the common Docker command and turn lookup errors into UI errors."""
        try:
            return build_docker_cli_command_prefix(docker_context)
        except DockerCommandNotFoundError as exc:
            raise ContainerShellLaunchError(
                "Could not open the container shell because the docker command "
                "was not found in PATH."
            ) from exc


__all__ = ["ContainerShellLaunchError", "ContainerShellLauncher"]
