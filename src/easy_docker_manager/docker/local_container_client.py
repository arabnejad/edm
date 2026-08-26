"""Send container requests to Docker running on this computer.

LocalDockerContainerClient connects to the local Docker daemon through the
Docker Python SDK. It lists running containers and loads their logs,
environment variables, inspection data, and process lists. The connection is
created when the first request is made and reused while EDM is running. EDMApp
closes it during shutdown. Callers receive EDM error types instead of Docker
SDK exceptions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional, Union

import docker
from docker.errors import DockerException, NotFound

from easy_docker_manager.core import ContainerProcessTable, ContainerSummary
from easy_docker_manager.docker.container_client import (
    ContainerNotFoundError,
    ContainerRefreshError,
    DockerContainerClient,
    FailedDockerRequestType,
    LogsUnavailableError,
)
from easy_docker_manager.docker.container_mapper import to_container_summary
from easy_docker_manager.docker.error_mapping import raise_container_request_error
from easy_docker_manager.docker.log_availability import (
    docker_error_indicates_logs_are_unavailable,
    get_container_logging_driver_name,
)

logger = logging.getLogger(__name__)


class LocalDockerContainerClient(DockerContainerClient):
    """Perform EDM's container requests through the local Docker daemon."""

    def __init__(
        self,
        create_client: Callable[[], docker.DockerClient],
    ) -> None:
        """Keep the client factory and wait to connect until data is requested."""
        self._create_docker_client = create_client
        self._docker_client_instance: Optional[docker.DockerClient] = None

    def _get_or_create_docker_client(self) -> docker.DockerClient:
        """Create the Docker client on first use, then reuse it."""
        if self._docker_client_instance is None:
            try:
                self._docker_client_instance = self._create_docker_client()
            except DockerException:
                logger.exception("Failed to connect to local Docker")
                raise

        return self._docker_client_instance

    def list_running_containers(self) -> list[ContainerSummary]:
        """Return local running containers or raise ContainerRefreshError."""
        try:
            docker_containers = self._get_or_create_docker_client().containers.list(
                filters={"status": "running"}
            )
        except Exception as exc:
            logger.warning("Error fetching running containers: %s", exc)
            raise ContainerRefreshError(str(exc)) from exc

        container_summaries = []
        for container in docker_containers:
            try:
                container_summaries.append(to_container_summary(container))
            except Exception as exc:
                logger.warning("Skipping container summary: %s", exc)
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
                raise LogsUnavailableError(logging_driver_name)

            log_options: dict[str, Any] = {"tail": tail_lines, "timestamps": True}
            if since_timestamp is not None:
                log_options["since"] = since_timestamp
            logs = container.logs(**log_options)
            return self._decode_log_chunk(logs)
        except LogsUnavailableError:
            raise
        except NotFound as exc:
            raise ContainerNotFoundError(container_id) from exc
        except Exception as exc:
            if docker_error_indicates_logs_are_unavailable(exc):
                logging_driver_name = get_container_logging_driver_name(container)
                logger.info(
                    "Logs unavailable for logging driver %s", logging_driver_name
                )
                raise LogsUnavailableError(logging_driver_name) from exc
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
            container = self._get_or_create_docker_client().containers.get(container_id)
            container_attrs = container.attrs
            image_attrs = self._load_image_inspection_data_for_container(
                container_attrs
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

    def close(self) -> None:
        """Close the Docker SDK client if it has been created.

        EDMApp.run() calls this from its cleanup block after the terminal UI
        stops and all background tasks finish. If no Docker request was made,
        no client exists and this method does nothing. After closing the client,
        it clears the saved reference so the closed client cannot be reused.
        """
        if self._docker_client_instance:
            self._docker_client_instance.close()
            self._docker_client_instance = None

    @staticmethod
    def _decode_log_chunk(chunk: Union[bytes, str]) -> str:
        """Return a Docker log response as a Python string.

        get_container_logs() calls this because the Docker SDK may return bytes
        or a string. Byte responses are decoded as UTF-8. Any invalid bytes are
        replaced instead of raising an error, so malformed log output does not
        stop the Logs tab from loading.
        """
        if isinstance(chunk, bytes):
            return chunk.decode("utf-8", errors="replace")
        return chunk

    def _load_image_inspection_data_for_container(
        self,
        container_attrs: dict[str, Any],
    ) -> dict[str, Any]:
        """Load inspection data for the container's image when available."""
        image_reference = container_attrs.get("Image") or (
            container_attrs.get("Config", {}) or {}
        ).get("Image")
        if not image_reference:
            return {}
        try:
            image_attrs = (
                self._get_or_create_docker_client().images.get(image_reference).attrs
            )
            return image_attrs if isinstance(image_attrs, dict) else {}
        except Exception as exc:
            logger.debug(
                "Image inspect unavailable for %s: %s",
                image_reference,
                exc,
            )
            return {}


__all__ = ["LocalDockerContainerClient"]
