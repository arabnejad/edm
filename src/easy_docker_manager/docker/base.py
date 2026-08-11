"""Define how EDM reads container data and reports Docker failures.

ContainerDataSource lists the Docker information needed by the rest of the
application, such as running containers, logs, environment variables, and
processes. The error classes convert Docker SDK exceptions into specific EDM
errors that the terminal UI knows how to display.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional, Union

from easy_docker_manager.core import ContainerProcessTable, ContainerSummary


class DockerDataSourceError(RuntimeError):
    """Base error for container data requests."""


class ContainerNotFoundError(DockerDataSourceError):
    """Raised when Docker no longer has the requested container."""

    def __init__(self, container_id: str) -> None:
        self.container_id = container_id
        super().__init__(f"Container not found: {container_id[:12]}")


class FailedDockerRequestType(str, Enum):
    """Describe which Docker request failed.

    LocalContainerDataSource passes one of these values from an except block to
    raise_container_request_error. The value tells that function what the code
    was trying to load when Docker raised the exception.

    For example, get_environment_variables passes LOAD_ENVIRONMENT after its
    Docker call fails.
    The error handler then:

    1. Raises ContainerNotFoundError if Docker cannot find the container.
    2. Raises ContainerLogFetchError when the request type is FETCH_LOGS.
    3. Raises DockerRequestFailedError for the other request types.

    The text value is included in the final message. For example,
    LOAD_ENVIRONMENT produces a message beginning with "Environment load failed".
    """

    FETCH_LOGS = "Log fetch"
    LOAD_ENVIRONMENT = "Environment load"
    LOAD_CONFIGURATION = "Config load"
    LOAD_PROCESS_LIST = "Process list load"


class DockerRequestFailedError(DockerDataSourceError):
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


class LogsUnavailableError(DockerDataSourceError):
    """Raised when Docker cannot read logs for the configured logging driver."""

    def __init__(self, driver: str) -> None:
        self.driver = driver
        super().__init__(f"Logs unavailable for Docker logging driver '{driver}'")


class ContainerRefreshError(DockerDataSourceError):
    """Raised when a container refresh fails before a valid list is available."""


class ContainerLogFetchError(DockerRequestFailedError):
    """Raised when Docker fails to return logs for a transient reason."""

    def __init__(self, container_id: str, reason: str) -> None:
        super().__init__(FailedDockerRequestType.FETCH_LOGS, container_id, reason)


class ContainerDataSource(ABC):
    """Provide the container data needed by the application.

    The scheduler and tab loaders use this interface instead of calling the
    Docker SDK directly. This keeps Docker details out of the UI code.
    """

    @abstractmethod
    def list_running_containers(self) -> list[ContainerSummary]:
        """Return running containers or raise ContainerRefreshError on failure."""

    @abstractmethod
    def get_logs(
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
    def get_environment_variables(self, container_id: str) -> dict[str, str]:
        """Return environment variables configured for a container."""

    @abstractmethod
    def get_docker_inspection_data(self, container_id: str) -> dict[str, Any]:
        """Return Docker inspect/config data used by the Config tab."""

    @abstractmethod
    def get_process_list(self, container_id: str) -> ContainerProcessTable:
        """Return the process-list columns and rows for a container."""

    @abstractmethod
    def close(self) -> None:
        """Close any client or connection owned by the data source."""


__all__ = [
    "ContainerDataSource",
    "ContainerLogFetchError",
    "ContainerNotFoundError",
    "ContainerRefreshError",
    "DockerDataSourceError",
    "DockerRequestFailedError",
    "FailedDockerRequestType",
    "LogsUnavailableError",
]
