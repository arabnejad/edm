"""Read container data through the active Docker SDK connection.

This client opens the startup context when the first request arrives and
reuses the connection. When the user changes context, it switches to the
client that passed the connection check. It also converts Docker SDK failures
into EDM errors for the rest of the application.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional, Union

from docker import DockerClient
from docker.errors import DockerException, NotFound

from easy_docker_manager.core.containers import (
    ContainerProcessTable,
    ContainerResourceStatsSnapshot,
    ContainerSummary,
)
from easy_docker_manager.docker.container_client import (
    ContainerLifecycleActionError,
    ContainerLogsUnavailableError,
    ContainerNotFoundError,
    DockerContainerClient,
    DockerDaemonDetails,
    FailedDockerRequestType,
    RunningContainerListRefreshError,
)
from easy_docker_manager.docker.container_mapper import to_container_summary
from easy_docker_manager.docker.container_resource_stats_builder import (
    build_container_resource_stats_snapshot,
)
from easy_docker_manager.docker.error_mapping import raise_container_request_error
from easy_docker_manager.docker.log_availability import (
    docker_error_indicates_logs_are_unavailable,
    get_container_logging_driver_name,
)

logger = logging.getLogger(__name__)


class DockerSDKContainerClient(DockerContainerClient):
    """Send EDM's container requests through the Docker Python SDK."""

    def __init__(
        self,
        create_docker_client: Callable[[], DockerClient],
    ) -> None:
        """Save the client factory but do not connect until the first request."""
        self._create_docker_client = create_docker_client
        self._docker_client: Optional[DockerClient] = None
        self._docker_clients_retained_until_shutdown: list[DockerClient] = []
        self._last_resource_stats_snapshot_by_container_id: dict[
            str, ContainerResourceStatsSnapshot
        ] = {}

    def _get_or_create_docker_client(self) -> DockerClient:
        """Open the Docker connection on first use and reuse it afterward."""
        if self._docker_client is None:
            try:
                self._docker_client = self._create_docker_client()
            except DockerException:
                logger.exception("Failed to connect to Docker")
                raise

        return self._docker_client

    def list_running_containers(self) -> list[ContainerSummary]:
        """Return running containers or raise RunningContainerListRefreshError."""
        try:
            docker_containers = self._get_or_create_docker_client().containers.list(
                filters={"status": "running"}
            )
        except Exception as exc:
            logger.warning("Error fetching running containers: %s", exc)
            raise RunningContainerListRefreshError(str(exc)) from exc

        container_summaries = []
        for container in docker_containers:
            try:
                container_summaries.append(to_container_summary(container))
            except Exception as exc:
                logger.warning("Skipping container summary: %s", exc)
        self._remove_last_resource_stats_samples_for_stopped_containers(
            {container.container_id for container in container_summaries}
        )
        return container_summaries

    def get_container_logs(
        self,
        container_id: str,
        tail_lines: Union[int, str] = 100,
        since_timestamp: Optional[int] = None,
    ) -> str:
        """Return container logs or raise an EDM error when Docker cannot read them."""
        container = None
        try:
            container = self._get_or_create_docker_client().containers.get(container_id)
            logging_driver_name = get_container_logging_driver_name(container)
            # Docker's "none" logging driver discards standard output and error.
            if logging_driver_name == "none":
                raise ContainerLogsUnavailableError(logging_driver_name)

            log_options: dict[str, Any] = {"tail": tail_lines, "timestamps": True}
            if since_timestamp is not None:
                log_options["since"] = since_timestamp
            logs = container.logs(**log_options)
            return self._decode_container_log_response(logs)
        except ContainerLogsUnavailableError:
            raise
        except NotFound as exc:
            raise ContainerNotFoundError(container_id) from exc
        except Exception as exc:
            if docker_error_indicates_logs_are_unavailable(exc):
                logging_driver_name = get_container_logging_driver_name(container)
                logger.info(
                    "Logs unavailable for logging driver %s", logging_driver_name
                )
                raise ContainerLogsUnavailableError(logging_driver_name) from exc
            logger.warning(
                "Error fetching logs for container %s: %s", container_id, exc
            )
            raise_container_request_error(
                FailedDockerRequestType.FETCH_LOGS,
                container_id,
                exc,
            )

    def get_container_environment_variables(
        self,
        container_id: str,
    ) -> dict[str, str]:
        """Return the environment variables stored in Docker inspection data."""
        try:
            container = self._get_or_create_docker_client().containers.get(container_id)
            environment_entries = container.attrs.get("Config", {}).get("Env", [])
            environment_variables: dict[str, str] = {}
            for environment_entry in environment_entries:
                if "=" in environment_entry:
                    name, value = environment_entry.split("=", 1)
                    environment_variables[name] = value
            return environment_variables
        except Exception as exc:
            logger.exception("Error fetching env for container %s", container_id)
            raise_container_request_error(
                FailedDockerRequestType.LOAD_ENVIRONMENT,
                container_id,
                exc,
            )

    def get_container_inspection_data(self, container_id: str) -> dict[str, Any]:
        """Return container inspection data and any available image data."""
        try:
            docker_client = self._get_or_create_docker_client()
            container = docker_client.containers.get(container_id)
            container_attrs = container.attrs
            image_attrs = self._load_image_inspection_data_for_container(
                docker_client,
                container_attrs,
            )
            return {
                "container": container_attrs,
                "image": image_attrs,
            }
        except Exception as exc:
            logger.exception("Error fetching config for container %s", container_id)
            raise_container_request_error(
                FailedDockerRequestType.LOAD_CONFIGURATION,
                container_id,
                exc,
            )

    def get_container_top_process_table(
        self,
        container_id: str,
    ) -> ContainerProcessTable:
        """Run Docker top for one container and return its columns and rows."""
        try:
            container = self._get_or_create_docker_client().containers.get(container_id)
            top_data = container.top()
        except Exception as exc:
            logger.exception("Error fetching processes for container %s", container_id)
            raise_container_request_error(
                FailedDockerRequestType.LOAD_PROCESS_LIST,
                container_id,
                exc,
            )

        columns = tuple(str(value) for value in (top_data.get("Titles") or []))
        rows = tuple(
            tuple(str(value) for value in process)
            for process in (top_data.get("Processes") or [])
        )
        return ContainerProcessTable(columns=columns, rows=rows)

    def get_container_resource_stats(
        self,
        container_id: str,
    ) -> ContainerResourceStatsSnapshot:
        """Fetch current stats and calculate rates from the last saved sample."""
        try:
            container = self._get_or_create_docker_client().containers.get(container_id)
            docker_stats_response = container.stats(stream=False)
            if not isinstance(docker_stats_response, dict):
                raise TypeError(
                    "Docker returned resource statistics in an unknown format"
                )

            current_resource_stats_snapshot = build_container_resource_stats_snapshot(
                docker_stats_response,
                container.attrs,
                self._last_resource_stats_snapshot_by_container_id.get(container_id),
            )
            self._last_resource_stats_snapshot_by_container_id[container_id] = (
                current_resource_stats_snapshot
            )
            return current_resource_stats_snapshot
        except Exception as exc:
            logger.exception(
                "Error fetching resource statistics for container %s",
                container_id,
            )
            raise_container_request_error(
                FailedDockerRequestType.LOAD_CONTAINER_RESOURCE_STATS,
                container_id,
                exc,
            )

    def stop_container(self, container_id: str) -> None:
        """Stop the running container identified by container_id."""
        try:
            container = self._get_or_create_docker_client().containers.get(container_id)
            container.stop()
        except NotFound as exc:
            raise ContainerNotFoundError(container_id) from exc
        except Exception as exc:
            logger.warning("Could not stop container %s: %s", container_id, exc)
            raise ContainerLifecycleActionError("stop", container_id, str(exc)) from exc

    def restart_container(self, container_id: str) -> None:
        """Restart the container without changing its Docker configuration."""
        try:
            container = self._get_or_create_docker_client().containers.get(container_id)
            container.restart()
        except NotFound as exc:
            raise ContainerNotFoundError(container_id) from exc
        except Exception as exc:
            logger.warning("Could not restart container %s: %s", container_id, exc)
            raise ContainerLifecycleActionError(
                "restart", container_id, str(exc)
            ) from exc

    def get_docker_daemon_details(self) -> DockerDaemonDetails:
        """Ask the active daemon for the version details used by diagnostics."""
        try:
            version_response = self._get_or_create_docker_client().version()
        except Exception as exc:
            logger.warning("Unable to read Docker daemon version: %s", exc)
            raise

        if not isinstance(version_response, dict):
            raise TypeError("Docker returned daemon details in an unknown format")
        return DockerDaemonDetails(
            daemon_version=_get_non_empty_text(version_response.get("Version")),
            api_version=_get_non_empty_text(version_response.get("ApiVersion")),
            operating_system=_get_non_empty_text(version_response.get("Os")),
            architecture=_get_non_empty_text(version_response.get("Arch")),
        )

    def switch_docker_connection(
        self,
        validated_docker_client: DockerClient,
    ) -> None:
        """Switch to a client that has already passed the connection check.

        A request for the previous context may still be running. Its client
        stays open so the request can finish, but DockerManager ignores the
        result. EDM closes the old client at shutdown after all workers finish.
        """
        previous_docker_client = self._docker_client
        self._docker_client = validated_docker_client
        self._last_resource_stats_snapshot_by_container_id.clear()
        if (
            previous_docker_client is not None
            and previous_docker_client is not validated_docker_client
        ):
            self._docker_clients_retained_until_shutdown.append(previous_docker_client)

    def close(self) -> None:
        """Close the active client and any clients kept after context changes.

        EDMApp calls this after its workers finish, so none of these clients
        are still handling a Docker request.
        """
        docker_clients = [*self._docker_clients_retained_until_shutdown]
        if self._docker_client is not None:
            docker_clients.append(self._docker_client)
        self._docker_clients_retained_until_shutdown.clear()
        self._docker_client = None
        self._last_resource_stats_snapshot_by_container_id.clear()

        for docker_client in docker_clients:
            try:
                docker_client.close()
            except Exception as exc:
                logger.debug("Could not close Docker connection: %s", exc)

    @staticmethod
    def _decode_container_log_response(
        container_log_response: Union[bytes, str],
    ) -> str:
        """Return a Docker log response as a Python string.

        The Docker SDK may return bytes or a string. Byte responses are decoded
        as UTF-8, and invalid bytes are replaced so malformed log output does
        not stop the Logs tab from loading.
        """
        if isinstance(container_log_response, bytes):
            return container_log_response.decode("utf-8", errors="replace")
        return container_log_response

    def _load_image_inspection_data_for_container(
        self,
        docker_client: DockerClient,
        container_attrs: dict[str, Any],
    ) -> dict[str, Any]:
        """Load inspection data for the container's image when available."""
        image_reference = container_attrs.get("Image") or (
            container_attrs.get("Config", {}) or {}
        ).get("Image")
        if not image_reference:
            return {}
        try:
            image_attrs = docker_client.images.get(image_reference).attrs
            return image_attrs if isinstance(image_attrs, dict) else {}
        except Exception as exc:
            logger.debug(
                "Image inspect unavailable for %s: %s",
                image_reference,
                exc,
            )
            return {}

    def _remove_last_resource_stats_samples_for_stopped_containers(
        self,
        running_container_ids: set[str],
    ) -> None:
        """Remove saved rate samples for containers that are no longer running."""
        stopped_container_ids = (
            self._last_resource_stats_snapshot_by_container_id.keys()
            - running_container_ids
        )
        for container_id in stopped_container_ids:
            del self._last_resource_stats_snapshot_by_container_id[container_id]


def _get_non_empty_text(value: Any) -> Optional[str]:
    """Return a non-empty string from Docker, or None for a missing value."""
    return value if isinstance(value, str) and value else None


__all__ = ["DockerSDKContainerClient"]
