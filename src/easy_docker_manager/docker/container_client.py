"""Define the Docker container requests used by the rest of EDM.

DockerContainerClient lists the operations without depending on the Docker SDK
types. The error classes give the application clear failures for missing
containers, unreadable logs, and other Docker request problems.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional, Union

from easy_docker_manager.core.containers import (
    ContainerProcessTable,
    ContainerResourceStatsSnapshot,
    ContainerSummary,
)


class DockerContainerClientError(RuntimeError):
    """Base error for requests made through DockerContainerClient."""


class ContainerNotFoundError(DockerContainerClientError):
    """Raised when Docker no longer has the requested container."""

    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        super().__init__(f"Container not found: {container_id[:12]}")


class FailedDockerRequestType(str, Enum):
    """Identify the data EDM was trying to read when Docker failed.

    LocalDockerContainerClient passes one of these values to
    raise_container_request_error() from an except block. The error mapper uses
    it to choose a specific EDM exception and build a useful message.

    For example, get_container_environment_variables passes LOAD_ENVIRONMENT
    when its Docker call fails. The error mapper then:

    1. Raises ContainerNotFoundError if Docker cannot find the container.
    2. Raises ContainerLogFetchError when the request type is FETCH_LOGS.
    3. Raises DockerRequestFailedError for the other request types.

    The text value is included in the final message. For example,
    LOAD_ENVIRONMENT produces a message beginning with "Environment load failed".
    """

    FETCH_LOGS = "Log fetch"
    LOAD_ENVIRONMENT = "Environment load"
    LOAD_CONFIGURATION = "Config load"
    LOAD_CONTAINER_RESOURCE_STATS = "Resource statistics load"
    LOAD_PROCESS_LIST = "Process list load"


class DockerRequestFailedError(DockerContainerClientError):
    """Raised when Docker rejects or cannot complete a container request."""

    def __init__(
        self,
        failed_request_type: FailedDockerRequestType,
        container_id: str,
        reason: str,
    ) -> None:
        self.failed_request_type = failed_request_type
        self.container_id = container_id
        self.reason = reason
        super().__init__(
            f"{failed_request_type.value} failed for container "
            f"{container_id[:12]}: {reason}"
        )


class ContainerLogsUnavailableError(DockerContainerClientError):
    """Raised when Docker cannot read logs for the configured logging driver."""

    def __init__(self, logging_driver_name: str) -> None:
        self.logging_driver_name = logging_driver_name
        super().__init__(
            "Logs unavailable for Docker logging driver " f"'{logging_driver_name}'"
        )


class RunningContainerListRefreshError(DockerContainerClientError):
    """Raised when a container refresh fails before a valid list is available."""


class ContainerLogFetchError(DockerRequestFailedError):
    """Raised when Docker fails to return logs for a transient reason."""

    def __init__(self, container_id: str, reason: str) -> None:
        super().__init__(FailedDockerRequestType.FETCH_LOGS, container_id, reason)


class DockerContainerClient(ABC):
    """List the Docker container operations that EDM can request.

    DockerManager and ContainerTabTextLoader use this interface instead of
    importing Docker SDK objects. LocalDockerContainerClient connects to Docker
    when EDM runs. Tests can provide a fake client without a Docker daemon.
    """

    @abstractmethod
    def list_running_containers(self) -> list[ContainerSummary]:
        """Return running containers or report that the list could not load."""

    @abstractmethod
    def get_container_logs(
        self,
        container_id: str,
        tail_lines: Union[int, str] = 100,
        since_timestamp: Optional[int] = None,
    ) -> str:
        """Return log text or raise ContainerLogFetchError on transient failure.

        For example, tail_lines=100 requests the latest 100 lines. Incremental
        polling uses tail_lines="all" with since_timestamp set to the previous
        request's start time, so Docker returns logs written since that request.
        """

    @abstractmethod
    def get_container_environment_variables(
        self,
        container_id: str,
    ) -> dict[str, str]:
        """Return environment variables from the container's Docker configuration."""

    @abstractmethod
    def get_container_inspection_data(self, container_id: str) -> dict[str, Any]:
        """Return container inspection data and related image data when available."""

    @abstractmethod
    def get_container_top_process_table(
        self,
        container_id: str,
    ) -> ContainerProcessTable:
        """Return the columns and process rows reported by Docker top."""

    @abstractmethod
    def get_container_resource_stats(
        self,
        container_id: str,
    ) -> ContainerResourceStatsSnapshot:
        """Return one current resource-usage sample for a container."""

    @abstractmethod
    def close(self) -> None:
        """Close the Docker connection if this client opened one."""


__all__ = [
    "DockerContainerClient",
    "ContainerLogFetchError",
    "ContainerNotFoundError",
    "RunningContainerListRefreshError",
    "DockerContainerClientError",
    "DockerRequestFailedError",
    "FailedDockerRequestType",
    "ContainerLogsUnavailableError",
]
