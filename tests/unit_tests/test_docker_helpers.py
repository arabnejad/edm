from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import DockerException, NotFound

from easy_docker_manager.docker import client_factory
from easy_docker_manager.docker.container_client import (
    ContainerLogFetchError,
    ContainerLogsUnavailableError,
    ContainerNotFoundError,
    DockerContainerClient,
    DockerRequestFailedError,
    FailedDockerRequestType,
)
from easy_docker_manager.docker.container_mapper import to_container_summary
from easy_docker_manager.docker.error_mapping import raise_container_request_error
from easy_docker_manager.docker.log_availability import (
    docker_error_indicates_logs_are_unavailable,
    get_container_logging_driver_name,
)


def test_docker_container_client_is_abstract() -> None:
    with pytest.raises(TypeError):
        DockerContainerClient()  # type: ignore[abstract]


def test_create_docker_client_passes_the_timeout(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    docker_client = object()
    docker_from_env = Mock(return_value=docker_client)
    monkeypatch.setattr(client_factory.docker, "from_env", docker_from_env)

    assert client_factory.create_docker_client(3.5) is docker_client
    docker_from_env.assert_called_once_with(timeout=3.5)


@pytest.mark.parametrize(
    "docker_host",
    ["unix:///var/run/docker.sock", "npipe:////./pipe/docker_engine"],
)
def test_create_docker_client_accepts_local_endpoints(
    monkeypatch,
    docker_host: str,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", docker_host)
    docker_from_env = Mock(return_value=object())
    monkeypatch.setattr(client_factory.docker, "from_env", docker_from_env)

    client_factory.create_docker_client(2.5)

    docker_from_env.assert_called_once_with(timeout=2.5)


@pytest.mark.parametrize(
    "docker_host",
    ["tcp://docker.example.com:2376", "ssh://docker.example.com"],
)
def test_create_docker_client_rejects_remote_endpoints(
    monkeypatch,
    docker_host: str,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", docker_host)
    docker_from_env = Mock()
    monkeypatch.setattr(client_factory.docker, "from_env", docker_from_env)

    with pytest.raises(DockerException, match="local Docker"):
        client_factory.create_docker_client(2.5)

    docker_from_env.assert_not_called()


def test_create_docker_client_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="request_timeout must be positive"):
        client_factory.create_docker_client(0)


def test_container_mapper_prefers_sdk_attributes() -> None:
    container = SimpleNamespace(
        id="full-id",
        short_id="short-id",
        name="web",
        status="running",
        attrs={
            "State": {"Status": "stopped"},
            "Config": {
                "Image": "nginx:latest",
                "Labels": {
                    "com.docker.compose.project": "example",
                    "com.docker.compose.service": "web",
                },
            },
            "Created": "2026-01-01T12:00:00Z",
        },
    )

    container_summary = to_container_summary(container)

    assert container_summary.container_id == "full-id"
    assert container_summary.name == "web"
    assert container_summary.status == "running"
    assert container_summary.image_name == "nginx:latest"
    assert container_summary.created_at == "2026-01-01T12:00:00Z"
    assert container_summary.compose_project_name == "example"
    assert container_summary.compose_service_name == "web"


def test_container_mapper_uses_inspection_fallbacks() -> None:
    container = SimpleNamespace(
        attrs={
            "Id": "abcdefghijklmnop",
            "Name": "/worker",
            "State": {"Status": "paused"},
            "Config": {"Image": "worker:1.0"},
            "Created": "2025-12-01T12:00:00Z",
        }
    )

    container_summary = to_container_summary(container)

    assert container_summary.container_id == "abcdefghijklmnop"
    assert container_summary.name == "worker"
    assert container_summary.status == "paused"
    assert container_summary.image_name == "worker:1.0"
    assert container_summary.created_at == "2025-12-01T12:00:00Z"
    assert container_summary.compose_project_name is None
    assert container_summary.compose_service_name is None


def test_container_mapper_uses_unknown_when_no_name_exists() -> None:
    container_summary = to_container_summary(SimpleNamespace(attrs={}))
    assert container_summary.name == "unknown"
    assert container_summary.status == "unknown"


def test_docker_error_types_keep_request_details() -> None:
    container_not_found_error = ContainerNotFoundError("abcdefghijklmnop")
    request_failed_error = DockerRequestFailedError(
        FailedDockerRequestType.LOAD_ENVIRONMENT,
        "abcdefghijklmnop",
        "denied",
    )
    logs_unavailable_error = ContainerLogsUnavailableError("none")

    assert str(container_not_found_error) == "Container not found: abcdefghijkl"
    assert (
        request_failed_error.failed_request_type
        == FailedDockerRequestType.LOAD_ENVIRONMENT
    )
    assert request_failed_error.container_id == "abcdefghijklmnop"
    assert request_failed_error.reason == "denied"
    assert "Environment load failed" in str(request_failed_error)
    assert logs_unavailable_error.logging_driver_name == "none"


def test_error_mapping_raises_missing_container_error() -> None:
    with pytest.raises(ContainerNotFoundError):
        raise_container_request_error(
            FailedDockerRequestType.LOAD_CONFIGURATION,
            "abc",
            NotFound("missing"),
        )


def test_error_mapping_raises_specific_log_error() -> None:
    with pytest.raises(ContainerLogFetchError, match="timeout"):
        raise_container_request_error(
            FailedDockerRequestType.FETCH_LOGS,
            "abc",
            RuntimeError("timeout"),
        )


def test_error_mapping_raises_general_request_error() -> None:
    with pytest.raises(DockerRequestFailedError) as raised_error:
        raise_container_request_error(
            FailedDockerRequestType.LOAD_PROCESS_LIST,
            "abc",
            RuntimeError("denied"),
        )

    assert (
        raised_error.value.failed_request_type
        == FailedDockerRequestType.LOAD_PROCESS_LIST
    )


def test_container_logging_driver_name_is_read_from_inspection_data() -> None:
    container = SimpleNamespace(attrs={"HostConfig": {"LogConfig": {"Type": "none"}}})

    assert get_container_logging_driver_name(container) == "none"
    assert get_container_logging_driver_name(None) == "unknown"


def test_container_logging_driver_name_returns_readable_driver_name() -> None:
    container = SimpleNamespace(
        attrs={"HostConfig": {"LogConfig": {"Type": "json-file"}}}
    )
    assert get_container_logging_driver_name(container) == "json-file"


@pytest.mark.parametrize(
    "message",
    [
        "configured logging driver does not support reading",
        "logging driver does not support reading",
        "logs are not available for this container",
    ],
)
def test_docker_error_indicates_when_logs_are_unavailable(message: str) -> None:
    assert docker_error_indicates_logs_are_unavailable(RuntimeError(message))


def test_unrelated_docker_error_does_not_indicate_logs_are_unavailable() -> None:
    assert not docker_error_indicates_logs_are_unavailable(
        RuntimeError("connection reset")
    )
